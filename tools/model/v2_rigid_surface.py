"""Generate UV-mapped accessory surface textures from Blender material metadata."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def material_class(name):
    rules = (
        ("label", ("label",)),
        ("optical", ("glass", "lens", "coating")),
        ("elastomer", ("rubber", "elastomer", "gasket", "pad", "liner", "seal")),
        ("rim", ("edging", "rim", "bevel", "edge")),
        ("metal", ("gunmetal", "brass", "fastener", "metal", "alloy", "bolt")),
        ("ink", ("markings", "charge", "accent", "ocher", "stripe")),
    )
    name = name.lower()
    for finish, terms in rules:
        if any(term in name for term in terms):
            return finish
    return "paint"


def tile_noise(random, resolution, cells):
    pixels = np.round(random.random((cells, cells)) * 255).astype("uint8")
    closed = np.pad(pixels, ((1, 1), (1, 1)), mode="wrap")
    border = resolution // cells
    image = Image.fromarray(closed).resize((resolution + 2 * border,) * 2, Image.Resampling.BICUBIC)
    return np.asarray(image, dtype=np.float32)[border:border + resolution, border:border + resolution] / 255


def scuffs(random, size, quantity, short):
    image = Image.new("L", (size * 2, size * 2))
    draw = ImageDraw.Draw(image)
    for _ in range(quantity):
        x, y = random.integers(0, size * 2, 2)
        dx = int(random.uniform(1.5, 20 if short else 110) * size / 512)
        dy = int(dx * random.uniform(-.43, .64))
        width = int(random.choice((1, 1, 1, 2, 3)))
        tone = int(random.integers(28, 191))
        end = (x + dx, y + dy)
        draw.line(((x, y), (x + dx // 2, y + dy // 2 - 1), end), fill=tone, width=width)
    return np.asarray(image.resize((size, size), Image.Resampling.LANCZOS), dtype=np.float32) / 255


def plate_print(name, size):
    name = name.lower()
    if "power" in name:
        title, line, subtitle = "JUGGERNAUT", "PWR CELL  /  JG-06", "HANDLE WITH CARE"
    elif "cell" in name:
        title, line, subtitle = "CAUTION", "POWER TERMINALS", "KEEP CONTACTS DRY"
    else:
        title, line, subtitle = "THERMAL OPTICS", "IR MODULE  /  JG-02", "KEEP OPTIC CLEAR"
    paper = Image.new("L", (size, size))
    draw = ImageDraw.Draw(paper)
    pad = round(size * .054)
    draw.rounded_rectangle((pad, pad, size - pad, size - pad), radius=pad,
                           outline=133, width=max(2, pad // 6))
    for y in (.35, .72):
        draw.line((pad * 2, size * y, size - pad * 2, size * y), fill=136, width=max(2, pad // 8))
    for y, message, scale in ((.15, title, .087), (.42, line, .063), (.54, subtitle, .06)):
        font = ImageFont.load_default(size=round(size * scale))
        draw.text((pad * 2, size * y), message, fill=242, font=font)
    for i in range(27):
        x = size * (.116 + i * .017)
        width = 1.7 if i % 5 in (0, 1, 4) else 1.1
        draw.rectangle((x, size * .77, x + size * width / 230, size * .88), fill=180)
    caution = Image.new("L", (size, size))
    ink = ImageDraw.Draw(caution)
    for i in range(4):
        x = size * (.67 + i * .048)
        ink.polygon(((x, size * .77), (x + size * .023, size * .77),
                     (x - size * .01, size * .88), (x - size * .034, size * .88)), fill=219)
    return np.asarray(paper, dtype=np.float32) / 255, np.asarray(caution, dtype=np.float32) / 255


def rgba(rgb, alpha):
    return Image.fromarray(np.round(np.clip(np.dstack((rgb, alpha)), 0, 1) * 255).astype("uint8"))


def surface(spec, size):
    name = spec["name"]
    finish = material_class(name)
    color = np.array([spec["color"][channel] for channel in "rgb"], dtype=np.float32)
    emission = spec.get("emission", {})
    color += [min(.27, emission.get(channel, 0) * .42) for channel in "rgb"]
    random = np.random.default_rng(int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "little"))
    broad, grain, rough = [tile_noise(random, size, cells) for cells in (8, 32, 128)]
    dust = np.maximum(0, .7 * broad + .3 * grain - .61)
    fine = random.random((size, size), dtype=np.float32) - .5
    scratches = scuffs(random, size, 170 if finish == "optical" else 540, finish in {"optical", "elastomer"})
    px = (np.arange(size, dtype=np.float32) + .5) / size
    u, v = np.meshgrid(px, px)
    distance = np.minimum(np.minimum(u, 1 - u), np.minimum(v, 1 - v))
    rim = np.maximum(0, 1 - distance / .09)
    height = .15 * fine + .35 * rough + .28 * grain
    diffuse = color * (1 + .20 * (grain - .5) + .15 * (broad - .5) + .13 * fine)[..., None]
    diffuse += (dust ** 1.2)[..., None] * np.array([.090, .063, .034])
    gloss = spec["smoothness"] + .06 * (rough - .5) - dust * .65

    if finish in {"paint", "rim", "metal"}:
        is_crown = "composite shell" in name.lower()
        wear = rim * (.09 if is_crown else .24 if finish == "paint" else .46)
        threshold, chip_limit = (.83, .37) if finish == "paint" else (.80, .60)
        islands = np.clip((.6 * rough + .4 * grain + wear - threshold) * 3.4, 0, chip_limit)
        islands *= np.where(broad > .48, 1, .35)
        incisions = scratches * (.20 if finish == "paint" else .58)
        rubbed = np.maximum(islands, incisions)
        steel = np.array((.175, .150, .115)) if finish != "metal" else color * 1.85
        diffuse = diffuse * (1 - rubbed[..., None]) + steel * rubbed[..., None]
        height -= islands * .88 + scratches * .67
        gloss += .31 * rubbed
        if finish == "metal":
            brush = np.sin(v * np.pi * 2 * 149 + grain)
            diffuse *= 1 + .04 * brush[..., None]
            height += .18 * brush
        if finish == "paint":
            # Broken shallow oxide pits pick up only on the broad painted panels.
            pits = np.clip((rough - .71) * 4, 0, 1) * (grain > .51)
            diffuse *= 1 - .24 * pits[..., None]
            height -= pits * .55
            if "faceplate" in name.lower() or "composite shell" in name.lower():
                # Mirrored cut lines stop shy of the upper and lower plate edges.
                side = np.abs(u - .5)
                track = .58 - .42 * side + .025 * np.cos(side * np.pi * 5)
                ends = (side > .17) & (side < .43)
                cut = np.exp(-((v - track) * 420) ** 2) * ends
                lip = np.exp(-((v - track - .003) * 360) ** 2) * ends
                diffuse *= 1 + (.067 * lip - .18 * cut)[..., None]
                height += .28 * lip - .72 * cut
                gloss += .08 * lip - .10 * cut

    if finish == "elastomer":
        dimples = np.sin(u * np.pi * 120) * np.sin(v * np.pi * 120)
        height += .37 * dimples * (.62 + .38 * broad)
        height -= scratches * .18
        diffuse *= 1 + .06 * dimples[..., None]

    if finish == "optical":
        radius = np.sqrt((u - .48) ** 2 + (v - .49) ** 2)
        polish = np.exp(-((radius - .34) * 9) ** 2)
        coating = np.cos((u * 1.3 + v * .65 - .94) * np.pi * 2.2)
        is_lens = "lens" in name.lower() or "ruby" in name.lower()
        if is_lens:
            diffuse = color * (.70 + .17 * polish + .14 * (coating + 1))[..., None]
            diffuse += np.stack((polish * .012, polish * .002, polish * .004), axis=-1)
        else:
            diffuse = color * (.90 + .09 * coating + .08 * broad)[..., None]
            diffuse += np.stack((polish * .003, polish * .003, polish * .004), axis=-1)
        diffuse += scratches[..., None] * .012 + dust[..., None] * .014
        height = .012 * fine + .04 * rough - .10 * scratches
        gloss = np.clip(spec["smoothness"] + .035 * polish - .10 * scratches - .23 * dust, .55, .92)

    if finish == "label":
        lettering, caution = plate_print(name, size)
        pigment = np.maximum(lettering, caution)
        pigment *= (1 - scratches ** .65 * .82) * (1 - dust * 1.45)
        diffuse = diffuse * (1 - pigment[..., None])
        diffuse += lettering[..., None] * pigment[..., None] * np.array((.65, .66, .53))
        diffuse += caution[..., None] * pigment[..., None] * np.array((.74, .40, .072))
        height += pigment * .36 - scratches * .45
        gloss += pigment * .07

    if finish == "ink":
        diffuse *= 1 - .42 * scratches[..., None]
        height -= .52 * scratches

    gloss = np.clip(gloss, .07, .98)
    # Derivatives against OpenGL +U and +V. Image rows increase toward -V.
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * .36
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * .36
    length = np.sqrt(dx * dx + dy * dy + 1)
    encoded_normal = np.dstack((-dx / length, dy / length, 1 / length)) * .5 + .5
    diffuse = np.clip(diffuse, 0, 1)
    encoded_color = np.where(diffuse < .0031308, 12.92 * diffuse, 1.055 * diffuse ** (1 / 2.4) - .055)
    reflectance = np.clip(gloss * (.64 + .30 * spec["metallic"]), .07, .98)
    return {
        "albedo": rgba(encoded_color, gloss),
        "normal": Image.fromarray(np.round(encoded_normal * 255).astype("uint8")),
        "gloss": rgba(np.repeat(reflectance[..., None], 3, axis=2), gloss),
    }


def generate(art, target):
    target.mkdir(parents=True, exist_ok=True)
    material_specs = {}
    for kind in ("helmet", "thermal", "cell"):
        data = json.loads((art / f"{kind}.json").read_text(encoding="utf-8-sig"))
        for spec in data["materials"]:
            known = material_specs.setdefault(spec["name"], spec)
            if known != spec:
                raise ValueError(f"Material {spec['name']} has conflicting settings")
    manifest = {}
    for name, spec in sorted(material_specs.items()):
        finish = material_class(name)
        size = 1024 if finish in {"paint", "rim", "optical", "label"} else 512
        material_id = hashlib.sha256(name.encode()).hexdigest()[:10]
        slug = "_".join(name.lower().split())
        stem = "".join(c for c in slug if c.isascii() and (c.isalnum() or c == "_"))
        maps = {}
        for channel, image in surface(spec, size).items():
            filename = f"{stem}_{material_id}_{channel}.png"
            image.save(target / filename)
            maps[channel] = filename
        manifest[name] = maps
    (target / "rigid_materials.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Authored {len(manifest)} surface sets in {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    generate(args.art, args.out or args.art / "textures")
