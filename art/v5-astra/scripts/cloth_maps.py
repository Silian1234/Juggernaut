"""Build the charcoal color and thread-relief atlases in the native EFT UV space."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ENTRY = Path(__file__).resolve().parents[1]
SOURCE = ENTRY / "source" / "cloth"
TARGET = ENTRY / "textures" / "cloth"

# Traced from the existing Commando trouser atlas on a 768px reference canvas.
TROUSER_SEAMS = (
    ((180, 308), (178, 362), (179, 413)),
    ((571, 293), (578, 349), (580, 413)),
    ((4, 408), (76, 416), (176, 416), (250, 425), (333, 439)),
    ((424, 445), (503, 426), (578, 413), (661, 411), (762, 408)),
    ((228, 441), (232, 477), (223, 527), (219, 582), (220, 650)),
    ((528, 447), (530, 489), (541, 542), (542, 595), (542, 654)),
    ((7, 591), (85, 593), (172, 586), (267, 584), (323, 597)),
    ((433, 587), (513, 585), (579, 581), (654, 587), (762, 586)),
    ((482, 160), (520, 143), (579, 131), (595, 171), (618, 238), (543, 273), (499, 222), (482, 160)),
)


def soften(image, radius):
    return np.asarray(image.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32)


def noise_field(shape, tiles, rng):
    coarse = rng.integers(0, 256, (tiles, tiles), dtype=np.uint8)
    im = Image.fromarray(coarse).resize(shape[::-1], Image.Resampling.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 127.5 - 1


def draw_seams(shape):
    groove = Image.new("L", shape[::-1])
    thread = Image.new("L", shape[::-1])
    groove_draw, thread_draw = ImageDraw.Draw(groove), ImageDraw.Draw(thread)
    scale = shape[0] / 768
    for path in TROUSER_SEAMS:
        points = [(x * scale, y * scale) for x, y in path]
        groove_draw.line(points, fill=205, width=5, joint="curve")
        for ax, ay, bx, by in [(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])]:
            length = np.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / length, (by - ay) / length
            for distance in np.arange(0, length - 3, 6):
                x, y = ax + ux * distance - uy * 3, ay + uy * distance + ux * 3
                thread_draw.line((x, y, x + ux * 3.5, y + uy * 3.5), fill=231, width=2)
    return soften(groove, 1.1) / 255, soften(thread, 0.5) / 255


def save(stem):
    diffuse = Image.open(SOURCE / f"{stem}_d.png").convert("RGB")
    luma = diffuse.convert("L")
    raw = np.asarray(luma, dtype=np.float32)
    local, broad = soften(luma, 4.8), soften(luma, 31)
    gloss = np.asarray(Image.open(SOURCE / f"{stem}_g.png").convert("RGB"), dtype=np.float32).max(axis=2)
    normal = np.asarray(Image.open(SOURCE / f"{stem}_n.png").convert("RGB"), dtype=np.float32)
    slope = (normal[:, :, 0] - 128) * 0.36 + (normal[:, :, 1] - 128) * 0.74
    slope_soft = soften(Image.fromarray(np.clip(slope + 128, 0, 255).astype(np.uint8)), 2) - 128

    rng = np.random.default_rng(seed=184)
    fine = noise_field(raw.shape, 261, rng)
    yarn = noise_field(raw.shape, 99, rng)
    wear = noise_field(raw.shape, 32, rng)
    y, x = np.indices(raw.shape, dtype=np.float32)
    # Over-under thread with a visibly diagonal rib and slower fiber density changes.
    u, v = x * 0.955 + y * 0.296, y * 0.955 - x * 0.296
    twill = np.cos(u * 1.33 + np.sin(v * 1.28) * 0.68)
    cross = np.cos(v * 1.30 + np.pi * np.cos(u * 0.67))
    weave = twill * 0.60 + cross * 0.29 + fine * 0.27 + yarn * 0.11

    trousers = stem == "pants_usec_commando"
    seam, stitches = draw_seams(raw.shape) if trousers else (0, 0)
    high = (raw - local) * 0.17
    mids = (local - broad) * (0.13 if trousers else 0.16)
    value = (31 + high + mids + (broad - 62) * 0.14 + (gloss - 32) * 0.09
             + slope_soft * 0.18 + weave * 4.7 + wear * 4.4 - seam * 13 + stitches * 24)
    value = np.clip(value, 13, 78)
    rgb = np.stack((value * 0.97, value * 0.993, value * 1.015), axis=2)
    height = np.clip(128 + weave * 32 + yarn * 12 + wear * 5 - seam * 23 + stitches * 48, 0, 255)
    Image.fromarray(np.rint(rgb).astype(np.uint8)).save(TARGET / f"{stem}_charcoal.png")
    Image.fromarray(np.rint(height).astype(np.uint8)).save(TARGET / f"{stem}_weave.png")


if __name__ == "__main__":
    for donor in ("usec_body", "pants_usec_commando"):
        save(donor)
