"""Bake a textile color tile with muted, irregular panel stitching."""

from math import sin
from pathlib import Path
from random import Random

from PIL import Image, ImageDraw, ImageFilter


def build():
    width, height = 1024, 384
    rng = Random(803)
    stains = Image.new("L", (31, 13))
    stains.putdata([rng.randrange(45, 210) for _ in range(31 * 13)])
    stains = stains.resize((width, height), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(11))
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            val = 24 + (stains.getpixel((x, y)) - 128) * .061
            val += rng.choice((-9, -4, -1, 1, 3, 6, 11))
            val += 3 * sin(x * 1.89) * sin(y * 1.36)
            pixels[x, y] = (int(val * 1.02), int(val), int(val * .97))

    draw = ImageDraw.Draw(image)
    for index, y in enumerate((15, 145, 256, 370)):
        for x in range(rng.randrange(8, 19), width - 14, 9):
            if rng.random() < (.22 if index in {1, 2} else .11):
                continue
            y1 = y + 2.1 * sin(x / 95 + index) + rng.uniform(-1.65, 1.65)
            value = rng.randint(46, 71) if index in {1, 2} else rng.randint(51, 83)
            draw.line((x, y1, x + rng.randint(3, 6), y1 + rng.uniform(-.4, .4)),
                      fill=(value, int(value * .92), int(value * .79)), width=rng.choice((1, 2, 2)))
    for x in (17, width - 20):
        for y in range(20, height - 12, 8):
            if rng.random() > .17:
                x1 = x + 1.3 * sin(y / 42) + rng.uniform(-1.4, 1.4)
                value = rng.randint(44, 74)
                draw.line((x1, y, x1 + rng.uniform(-.8, .8), y + rng.randint(4, 6)),
                          fill=(value, int(value * .91), int(value * .78)), width=2)
    image.save(Path(__file__).resolve().parents[1] / "textures" / "carrier-loop.png")


if __name__ == "__main__":
    build()
