"""Read atlas PNG bytes and verify coverage, normal vectors, and map padding."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

sys.dont_write_bytecode = True
from bake_raster import PAD, ROOT, SIZES, TILE_ROWS, rasterize, seed_subpixel_islands

WORK = ROOT / "work/bake_v5b"
NORMAL_BACKGROUND = (128, 128, 255)
NORMAL_LENGTH_TOLERANCE = np.sqrt(3) / 255 + 1e-6
MAX_TILT_DEGREES = 38
QUANTILES = (0, 1, 10, 50, 90, 95, 99, 99.9, 100)


def read_png(directory, atlas, role, size, modes):
    path = directory / f"{atlas}_{role}.png"
    with path.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        if image.mode not in modes or image.size != (size, size):
            raise ValueError(f"{path.name}: found {image.mode} {image.size}, expected {modes} {size}px square")
        record = {"mode": image.mode, "size": list(image.size), "sha256": digest}
        return np.asarray(image)[::-1], record


def summary(values):
    return {"min": np.min(values, axis=0).tolist(), "mean": np.mean(values, axis=0).tolist(),
            "max": np.max(values, axis=0).tolist()}


def quantiles(values):
    return dict(zip((str(p) for p in QUANTILES), np.percentile(values, QUANTILES).tolist()))


def clusters(peaks):
    h, w = peaks.shape
    supported = np.zeros_like(peaks)
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        first = (slice(0, h - dy), slice(max(0, -dx), min(w, w - dx)))
        second = (slice(dy, h), slice(max(0, dx), min(w, w + dx)))
        adjacent = peaks[first] & peaks[second]
        supported[first] |= adjacent
        supported[second] |= adjacent
    return {"count": int(peaks.sum()), "isolated_8_connected": int((peaks & ~supported).sum())}


def inspect_normals(rgb, y, x, labels, surface_codes, surface_names, objects, object_names):
    tilt = np.empty(labels.shape, np.float32)
    lengths = np.empty_like(tilt)
    size = len(labels)
    for base in range(0, size, TILE_ROWS):
        tile = slice(base, base + TILE_ROWS)
        vectors = rgb[tile].astype(np.float32) * (2 / 255) - 1
        lengths[tile] = np.linalg.norm(vectors, axis=2)
        tilt[tile] = np.degrees(np.arctan2(np.hypot(vectors[..., 0], vectors[..., 1]), vectors[..., 2]))

    occupied = tilt[y, x]
    faces = labels[y, x]
    face = faces[peak := int(occupied.argmax())]
    worst = {"degrees": float(occupied[peak]), "png_xy": [int(x[peak]), int(size - y[peak] - 1)],
             "rgb": rgb[y[peak], x[peak]].tolist(), "material": str(surface_names[face]),
             "object": str(object_names[objects[face]])}
    chart = surface_codes[faces]
    strongest_neighbor = np.full(len(x), -np.inf, np.float32)
    for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
        yy, xx = np.clip(y + dy, 0, size - 1), np.clip(x + dx, 0, size - 1)
        neighbor = labels[yy, xx]
        valid = (neighbor >= 0) & (surface_codes[neighbor] == chart) & ((yy != y) | (xx != x))
        np.maximum(strongest_neighbor, np.where(valid, tilt[yy, xx], -np.inf), out=strongest_neighbor)
    excess = occupied - strongest_neighbor
    spikes = (occupied > 20) & np.isfinite(excess) & (excess > 8)
    if spikes.any():
        candidates = np.flatnonzero(spikes)
        peak_spikes = candidates[np.argsort(excess[candidates])[-10:][::-1]]
    else:
        peak_spikes = []
    return {"occupied_tilt_degrees": quantiles(occupied), "max_occupied_tilt": worst,
            "full_png_max_tilt_degrees": float(tilt.max()),
            "occupied_percent_over_one_degree": float(100 * (occupied > 1).mean()),
            "spikes_over_20_deg_and_8_deg_above_all_same_chart_neighbors": int(spikes.sum()),
            "strongest_spikes": [{"png_xy": [int(x[i]), int(size - y[i] - 1)], "tilt_deg": float(occupied[i]),
                                  "excess_deg": float(excess[i]), "rgb": rgb[y[i], x[i]].tolist(),
                                  "material": str(surface_names[faces[i]]),
                                  "object": str(object_names[objects[faces[i]]])} for i in peak_spikes],
            "decoded_length_all_png": {"min": float(lengths.min()), "max": float(lengths.max())},
            "non_unit_beyond_rgb8_rounding_all_png": int((np.abs(lengths - 1) > NORMAL_LENGTH_TOLERANCE).sum()),
            "back_or_grazing_normals_all_png": int((rgb[..., 2] <= 127).sum())}, occupied


def padding_audit(labels, maps, padding):
    size = len(labels)
    result = {key: {"incorrect_padding": 0, "non_default_unused": 0} for key in maps}
    count = 0
    for start in range(0, size, TILE_ROWS):
        stop = min(start + TILE_ROWS, size)
        base, end = max(start - padding, 0), min(stop + padding, size)
        candidate = labels[base:end] < 0
        local = slice(start - base, stop - base)
        if candidate.all():
            pad = np.zeros_like(candidate[local])
        else:
            distances, indices = distance_transform_edt(candidate, return_indices=True)
            pad = candidate[local] & (distances[local] <= padding)
            row, col = np.nonzero(pad)
            src_row, src_col = indices[:, row + start - base, col]
        count += int(pad.sum())
        unused = candidate[local] & ~pad
        for key, (pixels, background) in maps.items():
            if pad.any():
                different = pixels[row + start, col] != pixels[src_row + base, src_col]
                result[key]["incorrect_padding"] += int(np.count_nonzero(np.any(different, axis=1)
                                                                        if different.ndim == 2 else different))
            different = pixels[start:stop][unused] != background
            result[key]["non_default_unused"] += int(np.count_nonzero(np.any(different, axis=1)
                                                                       if different.ndim == 2 else different))
    return {"padding_distance": padding, "dilated_texels": count, "maps": result}


def audit_atlas(directory, atlas, size, old_only):
    with np.load(ROOT / f"work/bake/{atlas}.npz", allow_pickle=False) as source:
        uv, charts = source["uv"], source["chart"]
        material, names = source["mat"], source["material_names"]
        objects, object_names = source["obj"], source["object_names"]
    labels, _, _, det, overlap = rasterize(uv, size)
    y, x = np.nonzero(labels >= 0)
    face = labels[y, x]
    seeded, unseeded = seed_subpixel_islands(uv, det, charts, labels)
    _, surface_codes = np.unique(np.column_stack((charts, material)), axis=0, return_inverse=True)
    report = {"size": size, "covered_texel_centers": int(len(x)), "overlaps": overlap,
              "seeded_islands": seeded, "unseeded_islands": unseeded, "files": {}}
    normal, report["files"]["normal"] = read_png(directory, atlas, "normal", size, ("RGB",))
    normal_args = (y, x, labels, surface_codes, names[material], objects, object_names)
    report["normal"], tilt = inspect_normals(normal, *normal_args)
    if old_only:
        return report
    old_normal, old_file = read_png(WORK / "old_maps", atlas, "normal", size, ("RGB",))
    report["old_normal"], _ = inspect_normals(old_normal, *normal_args)
    report["old_normal"]["file"] = old_file
    del old_normal

    loaded = {"normal": (normal, NORMAL_BACKGROUND)}
    for role, mode, background in (("albedo", "RGBA", 0), ("specgloss", "RGBA", 0),
                                   ("metallic", "L", 0)):
        pixels, report["files"][role] = read_png(directory, atlas, role, size, (mode,))
        loaded[role] = (pixels, background)
    swizzle, report["files"]["normal_dxt5nm"] = read_png(directory, atlas, "normal_dxt5nm", size, ("RGBA",))
    report["channel_checks"] = {"albedo_alpha_equals_specgloss_alpha": bool(np.array_equal(
        loaded["albedo"][0][..., 3], loaded["specgloss"][0][..., 3])),
        "normal_swizzle_red_255": bool((swizzle[..., 0] == 255).all()),
        "normal_swizzle_green_blue_equal_y": bool(np.array_equal(swizzle[..., 1], normal[..., 1]) and
                                                    np.array_equal(swizzle[..., 2], normal[..., 1])),
        "normal_swizzle_alpha_equals_x": bool(np.array_equal(swizzle[..., 3], normal[..., 0]))}
    del swizzle
    for role, background in (("ao", 255), ("curvature", 128), ("position", 0)):
        pixels, report["files"][role] = read_png(directory, atlas, role, size, ("L",))
        loaded[role] = pixels, background
    report["padding"] = padding_audit(labels, loaded, PAD)

    pixels = loaded["specgloss"][0][y, x]
    curvature = loaded["curvature"][0][y, x]
    report["steel_chip_spatial"] = {}
    report["materials"] = []
    for material_id in np.unique(material):
        mask = material[face] == material_id
        name = str(names[material_id])
        entry = {"material_id": int(material_id), "name": name, "covered_texels": int(mask.sum())}
        if mask.any():
            values = pixels[mask] / 255
            entry.update(spec_rgb=summary(values[:, :3]), gloss=summary(values[:, 3]),
                         gloss_quantiles=quantiles(values[:, 3]), normal_tilt_degrees=quantiles(tilt[mask]))
        report["materials"].append(entry)

        if name not in {"V5 | Dark graphite frame", "Powerpack black", "Powerpack edge", "Powerpack plate"}:
            continue
        selector = mask & (pixels[:, 0] >= round(.65 * 255))
        high = np.zeros(labels.shape, bool)
        high[y[selector], x[selector]] = True
        chip = clusters(high)
        chip["threshold_spec_r"] = round(.65 * 255) / 255
        if selector.any():
            nonchip = mask & ~selector
            chip.update(spec_rgb=summary(pixels[selector, :3] / 255), gloss=summary(pixels[selector, 3] / 255),
                        curvature_median_chip_byte=float(np.median(curvature[selector])),
                        curvature_median_nonchip_byte=float(np.median(curvature[nonchip])),
                        percent_positive_curvature_chip=float(100 * (curvature[selector] > 128).mean()),
                        percent_positive_curvature_nonchip=float(100 * (curvature[nonchip] > 128).mean()))
        report["steel_chip_spatial"][name] = chip
    return report


def markdown(atlases):
    def rgb(values):
        return "/".join(f"{value:.3f}" for value in values)

    paragraphs = ["Значения рассчитаны по байтам RGBA, делённым на 255. Каждый центр текселя внутри UV-треугольника имеет одинаковый вес. Дилатация и служебные точки субпиксельных островов исключены."]
    for atlas, info in atlases.items():
        lines = [f"#### `{atlas}`", "", "| ID | Исходный материал | Тексели | Spec RGB среднее | Spec RGB мин. | Spec RGB макс. | Gloss среднее | Gloss мин. | Gloss макс. |",
                 "|---:|---|---:|---|---|---|---:|---:|---:|"]
        for entry in info["materials"]:
            name = entry["name"].replace("|", "\\|")
            stats = ([rgb(entry["spec_rgb"][key]) for key in ("mean", "min", "max")]
                     + [f'{entry["gloss"][key]:.3f}' for key in ("mean", "min", "max")]
                     if entry["covered_texels"] else ["—"] * 6)
            columns = [str(entry["material_id"]), name, str(entry["covered_texels"]), *stats]
            lines.append("| " + " | ".join(columns) + " |")
        paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", type=Path, default=ROOT / "textures/v5d")
    parser.add_argument("--old-only", action="store_true")
    args = parser.parse_args()
    directory = WORK / "old_maps" if args.old_only else args.maps.resolve()
    report = {"maps": str(directory), "atlases": {}, "errors": []}
    for atlas, size in SIZES.items():
        info = audit_atlas(directory, atlas, size, args.old_only)
        report["atlases"][atlas] = info
        print(atlas, info["normal"]["max_occupied_tilt"], flush=True)
        if args.old_only:
            continue
        for key in ("non_unit_beyond_rgb8_rounding_all_png", "back_or_grazing_normals_all_png"):
            if info["normal"][key]:
                report["errors"].append(f"{atlas}: {key} = {info['normal'][key]}")
        if info["normal"]["full_png_max_tilt_degrees"] > MAX_TILT_DEGREES:
            report["errors"].append(f"{atlas}: full atlas tilt exceeds {MAX_TILT_DEGREES} degrees")
        if info["overlaps"] or info["unseeded_islands"]:
            report["errors"].append(f"{atlas}: geometry coverage overlaps or unseeded islands")
        for key, valid in info["channel_checks"].items():
            if not valid:
                report["errors"].append(f"{atlas}: {key}")
        for role, counts in info["padding"]["maps"].items():
            if counts["incorrect_padding"] or counts["non_default_unused"]:
                report["errors"].append(f"{atlas}: {role} padding/background {counts}")
    filename = "qa_old_normals.json" if args.old_only else "qa_images_v5b.json"
    (WORK / filename).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not args.old_only:
        (WORK / "materials_table.md").write_text(markdown(report["atlases"]), encoding="utf-8")
    print(json.dumps(report["errors"]))
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
