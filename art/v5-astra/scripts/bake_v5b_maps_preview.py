from __future__ import annotations

import argparse
import hashlib
import json
from functools import lru_cache
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


ROOT = Path(__file__).resolve().parents[1]
BG, INK, MUTED, RULE = "#151a1e", "#ecf1f0", "#aebdb9", "#3a4849"
MINT, ORANGE = "#9fcec2", "#ecab6f"
ATLAS = (
    ("frame", "Рама"), ("armor", "Броня"),
    ("textile", "Ткань"), ("helmet", "Шлем"),
)
CHANNELS = (
    ("albedo", "Альбедо", "Цвет · sRGB"),
    ("normal", "Нормали", "Тангенциальный RGB"),
    ("spec_rgb", "Отражение", "SpecMap · RGB"),
    ("gloss", "Глянец", "SpecMap · A"),
    ("ao", "Окклюзия", "AO · 0…1"),
    ("curvature", "Кривизна", "Со знаком"),
)
CROPS = (
    ("frame", "Ось привода", "L Shoulder drive pivot", "V5 | Steel hardware", "normal"),
    ("frame", "Корпус привода", "L Elbow planetary actuator", "V5 | Dark graphite frame", "spec_rgb"),
    ("armor", "Кромка ножной брони", "LegArmour_L_LOD0", "V5 | Khaki paint", "spec_rgb"),
    ("textile", "Плетение чехла плиты", "V5_Carrier_FrontPlateBag_LOD0", "V5 | Carrier charcoal plate bag", "normal"),
    ("helmet", "Визор", "Visor | smoked wraparound face shield", "Helmet | smoked black visor", "normal"),
    ("helmet", "Корпус шлема", "FAST | high-cut laminate shell", "Helmet | graphite laminate", "normal"),
)
CROP_WIDTH, CROP_HEIGHT = 132, 98


@lru_cache
def font(size, bold=False):
    candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" /
                  ("segoeuib.ttf" if bold else "segoeui.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu") /
                  ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise FileNotFoundError("A Cyrillic-compatible Segoe UI or DejaVu Sans font is required")


def fmt(draw, xy, value, size, color=INK, bold=False, anchor=None):
    draw.text(xy, value, font=font(size, bold), fill=color, anchor=anchor)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def poly_mask(points, size):
    mask = Image.new("1", (size, size))
    draw = ImageDraw.Draw(mask)
    for polygon in points:
        draw.polygon([tuple(point) for point in polygon], fill=1)
    return mask


def curvature_palette():
    positions = np.arange(256)
    # Preserve one common signed range across every atlas.
    stops = np.array(((48, 130, 198), (60, 68, 70), (234, 156, 83)))
    return np.stack([np.interp(positions, (0, 128, 255), stops[:, n])
                     for n in range(3)], axis=-1).astype(np.uint8)


def read_display(maps, atlas, name, curvature_name, ao_name):
    actual = {"albedo": "albedo", "normal": "normal", "spec_rgb": "specgloss",
              "gloss": "specgloss", "ao": ao_name, "curvature": curvature_name}[name]
    source = Image.open(maps / f"{atlas}_{actual}.png")
    try:
        if name == "gloss":
            return source.getchannel("A").convert("RGB")
        if name == "curvature":
            if source.mode in {"L", "RGB", "RGBA"}:
                indices = np.asarray(source.getchannel(0))
            elif source.mode.startswith("I;16") or source.mode == "I":
                indices = (np.asarray(source, dtype=np.uint32) // 257).astype(np.uint8)
            else:
                raise ValueError(f"Unsupported curvature mode {source.mode}")
            return Image.fromarray(curvature_palette()[indices])
        if name == "ao" and (source.mode.startswith("I;16") or source.mode == "I"):
            pixels = (np.asarray(source, dtype=np.uint32) // 257).astype(np.uint8)
            return Image.fromarray(pixels).convert("RGB")
        return source.convert("RGB")
    finally:
        source.close()


def pick_crop(target, size, source, normal=False):
    extent = np.argwhere(target)
    if not len(extent):
        raise ValueError("Target UV triangles do not cover any pixels")
    y0, x0 = extent.min(axis=0)
    y1, x1 = extent.max(axis=0)
    rgb = np.asarray(source)
    top_min, top_max = max(0, y0 - CROP_HEIGHT // 2), min(size - CROP_HEIGHT, y1 - CROP_HEIGHT // 2)
    left_min, left_max = max(0, x0 - CROP_WIDTH // 2), min(size - CROP_WIDTH, x1 - CROP_WIDTH // 2)
    candidates = []
    for top in range(top_min, max(top_min, top_max) + 1, 20):
        for left in range(left_min, max(left_min, left_max) + 1, 20):
            bottom, right = top + CROP_HEIGHT, left + CROP_WIDTH
            mask = target[top:bottom, left:right]
            coverage = mask.mean()
            if coverage < .03:
                continue
            patch = rgb[top:bottom, left:right][mask].astype(np.float32)
            if normal:
                contrast = float(np.hypot(patch[:, 0] - 128, patch[:, 1] - 128).mean())
                score = min(.7, coverage) * (1 + contrast / 24)
            else:
                contrast = float(np.percentile(patch @ [.2126, .7152, .0722], 95)
                                 - np.percentile(patch @ [.2126, .7152, .0722], 40))
                score = min(.63, coverage) * (1 + contrast / 22)
            candidates.append((score, coverage, left, top))
    if not candidates:
        raise ValueError("No usable crop found")
    _, coverage, left, top = max(candidates)
    return (left, top, left + CROP_WIDTH, top + CROP_HEIGHT), round(coverage, 4)


def histogram(draw, xy, values, color, ymax):
    x, y = xy
    w, h = 146, 57
    draw.line((x, y + h, x + w, y + h), fill=RULE)
    for t in (0, .5, 1):
        tx = x + int(w * t)
        draw.line((tx, y, tx, y + h), fill=RULE)
    for i, count in enumerate(values):
        share_log = np.log1p(999 * count / ymax) / np.log(1000)
        height = round(h * share_log)
        if height:
            left = x + (i * w) // len(values) + 1
            right = x + ((i + 1) * w) // len(values) - 1
            draw.rectangle((left, y + h - height, right, y + h - 1), fill=color)


def main():
    parser = argparse.ArgumentParser(description="V5b map proof from the final PNGs and frozen UVs")
    parser.add_argument("--maps", type=Path, required=True)
    parser.add_argument("--layout", type=Path, default=ROOT / "work" / "bake")
    parser.add_argument("--categories", type=Path, default=ROOT / "work" / "bake_v5b")
    parser.add_argument("--curvature-name", default="curvature")
    parser.add_argument("--ao-name", default="ao")
    parser.add_argument("--output", type=Path, default=ROOT / "renders" / "textured" / "maps_preview.png")
    parser.add_argument("--hashes", type=Path, default=ROOT / "work" / "bake_v5b" / "maps_preview_sources.json")
    args = parser.parse_args()

    side, gap, start_x, start_y, step_y = 296, 13, 216, 169, 335
    width = start_x + 6 * side + 5 * gap + 36
    crops_y = start_y + 4 * step_y + 15
    height = crops_y + 474
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    fmt(draw, (36, 20), "АТЛАСЫ МАТЕРИАЛОВ", 47, bold=True)
    fmt(draw, (width - 37, 34), "ДЖАГГЕРНАУТ   /   V5 · ПРОХОД 2", 20, MINT, True, "ra")
    fmt(draw, (38, 81), "Полные UV-атласы · детали в исходном разрешении", 23, MUTED)
    draw.line((36, 116, width - 36, 116), fill=RULE)

    samples = {}
    manifest = {"sha256": {}, "crops": {}, "histograms": {}}
    short = {
        "albedo": "Цвет", "normal": "Нормали",
        "spec_rgb": "Spec RGB", "gloss": "Gloss A",
        "ao": "Окклюзия", "curvature": "Кривизна",
    }
    stage_preview = args.output.parent
    for col, (_, label, desc) in enumerate(CHANNELS):
        x = start_x + col * (side + gap)
        fmt(draw, (x, 123), label, 22, bold=True)
        fmt(draw, (x, 150), desc, 15, MUTED)

    for row, (atlas, label) in enumerate(ATLAS):
        y = start_y + row * step_y
        layout = args.layout / (atlas + ".npz")
        for path in [layout] + [args.maps / f"{atlas}_{name}.png" for name in
                                ("albedo", "normal", "specgloss", args.ao_name, args.curvature_name)]:
            manifest["sha256"][Path(os.path.relpath(path, ROOT)).as_posix()] = digest(path)
        with np.load(layout) as data:
            size = int(data["resolution"])
            uv = data["uv"].copy()
            uv[..., 0] = uv[..., 0] * size - .5
            uv[..., 1] = (1 - uv[..., 1]) * size - .5
            material = data["mat"]
            materials = data["material_names"]
            objects = data["obj"]
            names = data["object_names"]
            lod = data["lod"]

        images = {name: read_display(args.maps, atlas, name, args.curvature_name, args.ao_name)
                  for name, _, _ in CHANNELS}
        for name, img in images.items():
            if img.size != (size, size):
                raise ValueError(f"{atlas} {name}: {img.size} disagrees with UV layout {size}")

        fmt(draw, (36, y + 3), label, 27, bold=True)
        fmt(draw, (36, y + 40), f"{size} × {size}", 17, MUTED)
        # Use UV occupancy for distributions, excluding padding and empty pixels.
        category_file = args.categories / f"{atlas}_categories.npz"
        with np.load(category_file) as categories:
            occupied = categories["coverage"]
            material_pixels = categories["material_id"]
            object_pixels = categories["object_id"]
            if (not np.array_equal(categories["material_names"], materials)
                    or not np.array_equal(categories["object_names"], names)):
                raise ValueError(f"{atlas} categorical data and UV IDs disagree")
        manifest["sha256"][Path(os.path.relpath(category_file, ROOT)).as_posix()] = digest(category_file)
        with Image.open(args.maps / f"{atlas}_specgloss.png") as specgloss:
            packed = np.asarray(specgloss)[occupied]
        spec = (packed[:, :3] @ [.2126, .7152, .0722]).astype(np.uint8)
        hist_spec = np.bincount(spec // 16, minlength=16).tolist()
        hist_gloss = np.bincount(packed[:, 3] // 16, minlength=16).tolist()
        manifest["histograms"][atlas] = {"spec_rgb_luma": hist_spec, "gloss_a": hist_gloss}
        fmt(draw, (36, y + 85), "Яркость Spec RGB", 15, MINT)
        histogram(draw, (36, y + 111), hist_spec, MINT, len(packed))
        fmt(draw, (36, y + 177), "Gloss A", 15, ORANGE)
        histogram(draw, (36, y + 203), hist_gloss, ORANGE, len(packed))
        for x, value in ((36, "0"), (109, "0,5"), (182, "1")):
            fmt(draw, (x, y + 267), value, 13, MUTED, anchor="mt")

        for col, (name, _, _) in enumerate(CHANNELS):
            x = start_x + col * (side + gap)
            preview = images[name].resize((side, side), Image.Resampling.LANCZOS)
            canvas.paste(preview, (x, y))
            draw.rectangle((x, y, x + side - 1, y + side - 1), outline=RULE)

        for kind, title, obj, mat, channel in CROPS:
            if kind != atlas:
                continue
            eligible = (names[objects] == obj) & (materials[material] == mat) & (lod == 0)
            if not eligible.any():
                raise ValueError(f"{atlas}: no selected faces for {obj} / {mat}")
            object_id = np.flatnonzero(names == obj).item()
            material_id = np.flatnonzero(materials == mat).item()
            target_pixels = (object_pixels == object_id) & (material_pixels == material_id)
            target_lod0 = np.asarray(poly_mask(uv[eligible], size))
            bbox, coverage = pick_crop(target_pixels & target_lod0, size, images[channel], channel == "normal")
            samples[title] = {key: images[key].crop(bbox) for key in short}
            manifest["crops"][title] = {"atlas": atlas, "object": obj, "material": mat,
                                         "bounds_xyxy_top_left": bbox, "target_coverage": coverage}
            # Registration mark on each overview, exactly matching the native crop.
            for col, _ in enumerate(CHANNELS):
                x = start_x + col * (side + gap)
                panel_bbox = [round(coord * side / size) + (x if i % 2 == 0 else y)
                              for i, coord in enumerate(bbox)]
                draw.rectangle(panel_bbox, outline=ORANGE, width=1)

    axis_y = start_y + 4 * step_y - 28
    fmt(draw, (start_x, axis_y), "Гистограммы по UV-поверхности · 16 интервалов · лог. высота", 16, MUTED)
    legend_x = width - 585
    fmt(draw, (legend_x - 325, axis_y), "AO: чёрный — закрыто, белый — открыто", 16, MUTED)
    palette = Image.fromarray(curvature_palette()[None, :, :]).resize((164, 13))
    canvas.paste(palette, (legend_x, axis_y + 4))
    fmt(draw, (legend_x + 177, axis_y), "− впадина  /  0 плоскость  /  + ребро", 16, MUTED)
    draw.line((36, crops_y - 8, width - 36, crops_y - 8), fill=RULE)
    fmt(draw, (36, crops_y + 5), "ДЕТАЛИ 1:1", 26, bold=True)
    fmt(draw, (width - 36, crops_y + 12), "Оранжевые рамки указывают области выборки", 17, MUTED, anchor="ra")

    col_width = (width - 72) // 6
    for index, (_, title, *_rest) in enumerate(CROPS):
        x = 36 + index * col_width
        y = crops_y + 47
        fmt(draw, (x, y), title, 20, bold=True)
        for i, (k, label) in enumerate(short.items()):
            left = x + (i % 2) * (CROP_WIDTH + 8)
            top = y + 48 + (i // 2) * (CROP_HEIGHT + 25)
            fmt(draw, (left, top - 21), label, 14, MUTED)
            canvas.paste(samples[title][k], (left, top))
            draw.rectangle((left - 1, top - 1, left + CROP_WIDTH, top + CROP_HEIGHT), outline=RULE)
    fmt(draw, (36, height - 26), "Spec RGB, Gloss A и AO показаны по байтам PNG · Нормали в деталях 1:1 сохраняют исходный RGB",
        15, MUTED)

    for path, expected in manifest["sha256"].items():
        if digest(ROOT / path) != expected:
            raise RuntimeError(f"Source changed during sheet generation: {path}")

    stage_preview.mkdir(parents=True, exist_ok=True)
    args.hashes.parent.mkdir(parents=True, exist_ok=True)
    info = PngImagePlugin.PngInfo()
    info.add_text("Description", "V5b map proof; each detail crop matches source PNG pixels.")
    temp = args.output.with_suffix(".tmp")
    canvas.save(temp, "PNG", pnginfo=info)
    temp.replace(args.output)
    manifest["output_sha256"] = digest(args.output)
    args.hashes.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.output}: {width} × {height}; {len(manifest['sha256'])} verified source files")


if __name__ == "__main__":
    main()





