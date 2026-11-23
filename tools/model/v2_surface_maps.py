"""Procedural color, tangent normal and gloss atlas authoring for Juggernaut."""
from pathlib import Path
import struct
import zlib

import numpy as np

SIZE = 4096
TILE = 1024
PAD = 32
INNER = TILE - 2 * PAD
LAYOUT_TAG = b"JuggernautLayout\x00v3-manganese-id"

# The tile coordinates are measured from the lower-left atlas corner. The metric
# span defines the real surface width represented by each square's inner area.
SWATCHES = {
    # The legacy "olive" family is the main neutral manganese armor finish.
    "olive": (0, 0, .58, (53, 52, 51), 91, "paint"),
    "graphite": (1, 0, .56, (40, 40, 41), 78, "paint"),
    "steel": (2, 0, .43, (77, 77, 78), 126, "steel"),
    "edge": (3, 0, .56, (83, 82, 81), 114, "edge"),
    "fabric": (0, 1, .46, (32, 30, 29), 38, "fabric"),
    "fabricdark": (1, 1, .44, (23, 23, 23), 30, "fabric"),
    "strap": (2, 1, .36, (33, 32, 31), 34, "strap"),
    "rubber": (3, 1, .45, (32, 31, 31), 54, "rubber"),
    "red": (0, 2, .31, (131, 53, 36), 74, "paint"),
    "tan": (1, 2, .32, (174, 151, 102), 49, "paint"),
    "chest_id": (2, 2, .10, (42, 42, 40), 83, "paint"),
    "dock_service": (3, 2, .10, (40, 40, 40), 76, "paint"),
    "edge_dark": (0, 3, .48, (56, 55, 54), 88, "edge"),
    "seam": (1, 3, .39, (39, 38, 37), 33, "strap"),
    "marking": (2, 3, .31, (109, 104, 96), 49, "paint"),
    "black": (3, 3, .53, (23, 23, 24), 43, "rubber"),
}


def _noise(rng, frequency):
    """Interpolated signed noise with smooth transitions between lattice points."""
    grid = rng.uniform(-1, 1, (frequency + 1, frequency + 1)).astype(np.float32)
    points = np.arange(TILE, dtype=np.float32) * frequency / TILE
    cell = points.astype(np.int32)
    blend = points - cell.astype(np.float32)
    blend *= blend * (3 - 2 * blend)
    rows = grid[cell, :] * (1 - blend[:, None]) + grid[cell + 1, :] * blend[:, None]
    return rows[:, cell] * (1 - blend[None, :]) + rows[:, cell + 1] * blend[None, :]


def _scuffs(rng, clustered):
    """Accumulate individual gouges with tapered tips and displaced shoulders."""
    cut = np.zeros((TILE, TILE), np.float32)
    shoulder = np.zeros_like(cut)
    clusters = rng.uniform(64, TILE - 64, (12, 2)) if clustered else ()
    count = 87 if clustered else 51
    for attempt in range(count):
        if clustered and attempt < 65:
            x, y = np.clip(clusters[attempt % len(clusters)] + rng.normal(0, 30, 2),
                           0, TILE - 1)
        else:
            x, y = rng.uniform(0, TILE, 2)
        if clustered:
            length = rng.uniform(6, 43) if attempt < count - 9 else rng.uniform(45, 104)
        else:
            length = rng.uniform(7, 45) if attempt < count - 6 else rng.uniform(50, 113)
        angle = rng.normal(-.42, .26) if attempt < count - 10 else rng.uniform(-np.pi, np.pi)
        dx = np.cos(angle)
        dy = np.sin(angle)
        width = rng.uniform(.55, 1.7)
        margin = 5 * width + 2
        x0 = max(0, int(min(x, x + dx * length) - margin))
        x1 = min(TILE, int(max(x, x + dx * length) + margin) + 1)
        y0 = max(0, int(min(y, y + dy * length) - margin))
        y1 = min(TILE, int(max(y, y + dy * length) + margin) + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        along = (xx - x) * dx + (yy - y) * dy
        across = ((yy - y) * dx - (xx - x) * dy) / width
        fade = np.sin(np.pi * np.clip(along / length, 0, 1)) ** .64
        fade *= rng.uniform(.38, 1)
        channel = np.exp(-2.6 * across ** 2) * fade
        lip = np.exp(-2.8 * (np.abs(across) - 1.25) ** 2) * fade
        cut[y0:y1, x0:x1] = np.maximum(cut[y0:y1, x0:x1], channel)
        shoulder[y0:y1, x0:x1] = np.maximum(shoulder[y0:y1, x0:x1], lip)
    return cut, shoulder


def _brushing(rng):
    # Stretch the same smooth noise into fine horizontal finishing lines.
    field = _noise(rng, 413)[:, :64]
    x = np.linspace(0, field.shape[1] - 1, TILE, dtype=np.float32)
    left = x.astype(np.int32)
    fraction = x - left
    right = np.minimum(left + 1, field.shape[1] - 1)
    return field[:, left] * (1 - fraction) + field[:, right] * fraction


def _thread_relief(x, y, medium, fibre, width, height):
    # Alternating over/under crossings resolve into a fine weave up close.
    warp = (.5 + .5 * np.cos(x * 2 * np.pi / width + medium * .29)) ** 1.8
    weft = (.5 + .5 * np.cos(y * 2 * np.pi / height + medium * .31)) ** 1.8
    crossings = (np.floor(x / width) + np.floor(y / height)) % 2
    warp_weight = .29 + .71 * crossings
    weft_weight = 1.29 - warp_weight
    warp_hair = 1 + .12 * np.cos(x * np.pi * .91 + fibre * 1.2)
    weft_hair = 1 + .12 * np.cos(y * np.pi * .88 - fibre * 1.2)
    return warp * warp_weight * warp_hair + weft * weft_weight * weft_hair


_GLYPHS = {
    "0": ("01110","11011","11011","11011","11011","11011","01110"),
    "2": ("01110","11011","00011","00110","01100","11000","11111"),
    "3": ("11110","00011","00011","01110","00011","00011","11110"),
    "8": ("01110","11011","11011","01110","11011","11011","01110"),
    "A": ("00100","01110","11011","11011","11111","11011","11011"),
    "C": ("01111","11000","11000","11000","11000","11000","01111"),
    "D": ("11110","11011","11011","11011","11011","11011","11110"),
    "E": ("11111","11000","11000","11110","11000","11000","11111"),
    "G": ("01111","11000","11000","11011","11011","11011","01111"),
    "I": ("01110","00100","00100","00100","00100","00100","01110"),
    "J": ("00111","00011","00011","00011","11011","11011","01110"),
    "K": ("11011","11011","11110","11100","11110","11011","11011"),
    "M": ("11011","11111","11111","11011","11011","11011","11011"),
    "O": ("01110","11011","11011","11011","11011","11011","01110"),
    "P": ("11110","11011","11011","11110","11000","11000","11000"),
    "R": ("11110","11011","11011","11110","11100","11010","11011"),
    "S": ("01111","11000","11000","01110","00011","00011","11110"),
    "T": ("11111","00100","00100","00100","00100","00100","00100"),
    "V": ("11011","11011","11011","11011","11011","01110","00100"),
    "W": ("11011","11011","11011","11011","11111","11111","11011"),
    "Y": ("11011","11011","01110","00100","00100","00100","00100"),
    "/": ("00001","00011","00010","00100","01100","01000","10000"),
    " ": ("00000",) * 7,
}


def _caption(mask, text, left, top, step):
    height = int(step * 2.55)
    for char in text:
        for row, strokes in enumerate(_GLYPHS[char]):
            for column, stroke in enumerate(strokes):
                if stroke == "1":
                    x = left + column * step
                    y = top + row * height
                    mask[y:y+height, x:x+step] = 1
        left += step * 6


def _identification(name, base, gloss, relief, x, y, grain, grime, pore):
    ink = np.zeros_like(relief)
    accent = np.zeros_like(relief)
    if name == "chest_id":
        _caption(ink, "TG JG/03", 97, 267, 18)
        ink[707:722, 101:921] = .63
        for i in range(3):
            accent[766:816, 103 + i * 46:135 + i * 46] = .70
        relief += ink * .2
        ink *= .86
        printed = (177, 174, 165)
        detail = (132, 113, 80)
    else:
        # Screen-printed identification on the removable power pack.
        _caption(ink, "POWER PACK", 116, 237, 13)
        _caption(ink, "SERVICE", 119, 543, 13)
        _caption(accent, "02", 751, 553, 11)
        ink *= .67
        accent *= .65
        printed = (115, 112, 104)
        detail = (126, 105, 76)
    coverage = np.clip(1 - grime * .32 + grain * .15 + pore * .16, .42, 1)
    grit = np.clip((grain * .55 + pore * .44 - .41) * 1.35, 0, .70)
    for mask, color in ((ink, printed), (accent, detail)):
        alpha = np.clip(mask * coverage * (1 - grit), 0, 1)
        base = base * (1 - alpha[..., None]) + np.asarray(color) * alpha[..., None]
        gloss = gloss * (1 - alpha * .17)
    return base, gloss


def _tile(name, desc, *, weathered=False):
    tx, ty, _, color, gloss_level, kind = desc
    rng = np.random.default_rng(21669 + ty * 4 + tx)
    coarse = _noise(rng, 8)
    mottle = _noise(rng, 25)
    medium = _noise(rng, 74)
    grain = _noise(rng, 229)
    pore = rng.uniform(-1, 1, (TILE, TILE)).astype(np.float32)
    y, x = (
        np.arange(TILE, dtype=np.float32)[:, None], np.arange(TILE, dtype=np.float32)[None, :]
    )
    grime = np.clip((coarse + mottle * .48 + medium * .17 - .29) * 1.1, 0, 1)
    dust = np.clip((coarse * .42 - mottle * .55 + grain * .25 - .22) * 1.2, 0, 1)
    tint = np.asarray(color, dtype=np.float32)[None, None, :]
    base = tint + (coarse * 2.6 + mottle * 2.2 + medium * 1.8)[..., None]
    gloss = gloss_level - 20 * grime + 8 * mottle + 5 * medium + 3 * grain

    if kind in ("fabric", "strap"):
        pitch = 4.4 if kind == "fabric" else 7.5
        thread = _thread_relief(x, y, medium, grain, pitch, pitch * .82)
        if kind == "strap":
            rib = np.cos(x * 2 * np.pi / 14.5 + medium * .14)
            thread = thread * .47 + (.5 + .5 * rib) * .55
        shadow = (thread - .5) * 8 + pore * .8
        base += shadow[..., None]
        base += dust[..., None] * (4, 4, 3)
        base -= grime[..., None] * (5, 5, 5)
        relief = thread * .34 + grain * .045 + pore * .022
        gloss += thread * 10 - dust * 3
        if weathered and name in ("strap", "tan"):
            # Two parallel rows of bar stitches flank the densely ribbed tape.
            u = (x - PAD) / (INNER - 1)
            edge = np.minimum(np.abs(u - .155), np.abs(u - .845))
            hem = np.exp(-((edge - .024) * 120) ** 2)
            stitch = np.exp(-(edge * 95) ** 2)
            stitch = stitch * (.5 + .5 * np.cos(y * 2 * np.pi / 31)) ** 2
            field = mottle * 5 + medium * 4 + shadow * .9 - 18 * grime + dust * 2
            base += (field - hem * 12)[..., None]
            base += stitch[..., None] * (39, 33, 24)
            relief += hem * .19 + stitch * .5
            gloss -= hem * 12 + stitch * 9
    elif kind == "rubber":
        craters = np.clip(-grain * .8 + pore * .22 - .24, 0, 1)
        base += (grain * 2.8 + pore * 1.3 - craters * 2.7)[..., None]
        base += dust[..., None] * (5, 4, 3)
        base -= grime[..., None] * (6, 6, 6)
        relief = grain * .095 + medium * .18 - craters * .27
        gloss -= craters * 12
    else:
        clustered = kind == "edge"
        cut, lip = _scuffs(rng, clustered)
        transfer = np.clip((medium * .7 + grain * .55 + pore * .1 - .74) * 1.6, 0, 1)
        base -= grime[..., None] * (9, 9, 8)
        base += dust[..., None] * (4, 4, 3)
        base += grain[..., None] * 1.7
        relief = medium * .16 + grain * .063 + pore * .016 + lip * .16 - cut * .55
        if kind == "paint":
            exposed = cut * .52 + transfer * .07
            bare_metal = np.array((121, 119, 116))
            base += (bare_metal - base) * exposed[..., None] + lip[..., None] * 3
            gloss += 61 * exposed
        else:
            brush = _brushing(rng)
            rubbed = np.clip(mottle * .52 + medium * .17 - .14, 0, .48)
            base += (brush * 4.8 + rubbed * 17 + cut * 12 + lip * 6)[..., None]
            gloss += brush * 10 + rubbed * 31 - cut * 24
            relief += brush * .19
        if weathered and name in ("olive", "graphite", "edge", "edge_dark"):
            patina = np.clip((coarse * .6 + mottle * .62 - .04) * 1.44, 0, .85)
            speckle = np.clip(medium * .75 + grain * .32 - .44, 0, .55)
            abrasion = cut * (0.75 if kind == "edge" else .57)
            worn = np.array((86, 78, 66) if kind == "edge" else (114, 108, 95))
            base += patina[..., None] * (14, 9, 4)
            base += speckle[..., None] * (9, 7, 5)
            base += (worn - base) * abrasion[..., None]
            base -= (grime * 5 + lip * 2)[..., None]
            gloss += 24 * abrasion - 11 * patina
            relief += medium * .11 + lip * .21 - cut * .18

    if name in ("chest_id", "dock_service"):
        base, gloss = _identification(name, base, gloss, relief, x, y, grain, grime, pore)

    # The source arrays are stored top-down. Positive du follows array x, and
    # positive tangent dv is opposite to the row axis.
    dy, dx = np.gradient(relief)
    norm = np.sqrt(1 + dx * dx + dy * dy)
    normal = np.stack((-dx / norm, dy / norm, 1 / norm), axis=-1)
    normal = np.round((normal * .5 + .5) * 255).astype(np.uint8)
    base = np.clip(np.round(base), 0, 255).astype(np.uint8)
    gloss = np.clip(np.round(gloss), 0, 255).astype(np.uint8)
    return base, normal, np.repeat(gloss[..., None], 3, axis=-1)


def _chunk(tag, data):
    checksum = zlib.crc32(tag + data)
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", checksum)


def _save_png(path, pixels, layout_tag=LAYOUT_TAG):
    """Write RGB PNG without requiring Pillow inside Blender."""
    height, width, _ = pixels.shape
    delta = np.empty((height, width * 3 + 1), dtype=np.uint8)
    delta[:, 0] = 1
    delta[:, 1:4] = pixels[:, 0, :]
    np.subtract(pixels[:, 1:, :], pixels[:, :-1, :],
                out=delta[:, 4:].reshape(height, width - 1, 3))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as output:
        output.write(b"\x89PNG\r\n\x1a\n")
        output.write(_chunk(b"IHDR", header))
        output.write(_chunk(b"tEXt", layout_tag))
        output.write(_chunk(b"IDAT", zlib.compress(delta, 5)))
        output.write(_chunk(b"IEND", b""))
    temporary.replace(path)


def generate(paths):
    atlases = [np.empty((SIZE, SIZE, 3), dtype=np.uint8) for _ in paths]
    for name, desc in SWATCHES.items():
        tx, ty = desc[:2]
        x = tx * TILE
        y = SIZE - (ty + 1) * TILE
        for atlas, tile in zip(atlases, _tile(name, desc)):
            atlas[y:y+TILE, x:x+TILE] = tile
    for target, atlas in zip(paths, atlases):
        target.parent.mkdir(parents=True, exist_ok=True)
        _save_png(target, atlas)
        print(f"EXO atlas: {target} ({SIZE} x {SIZE})", flush=True)


