"""Lay out the rendered hero and accessories as a 1920x1080 promotional image.

Run after render_art.py. Requires Pillow and the Windows Bahnschrift font.
"""

import argparse
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[2]
WIDTH, HEIGHT = 1920, 1080
WARM = (229, 176, 106)
PAPER = (237, 236, 218)
MUTED = (171, 178, 163)
INK = (15, 20, 20)


def font(size, weight=400, stretch=100):
    path = Path(os.environ["WINDIR"]) / "Fonts/bahnschrift.ttf"
    face = ImageFont.truetype(str(path), size)
    face.set_variation_by_axes([weight, stretch])
    return face


def tracked(draw, position, label, face, spacing, fill):
    x, y = position
    for char in label:
        draw.text((x, y), char, font=face, fill=fill, anchor="lt")
        x += draw.textlength(char, font=face) + spacing


def backdrop():
    small = Image.new("RGB", (480, 270))
    colors = []
    for row in range(small.height):
        for col in range(small.width):
            x, y = col / small.width, row / small.height
            spot = math.exp(-(((x - .81) * 2.66) ** 2 + ((y - .43) * 1.72) ** 2) * 2.3)
            horizon = math.exp(-((y - .86) / .15) ** 2)
            colors.append(tuple(round(base + light * spot + floor * horizon)
                                for base, light, floor in zip(INK, (48, 67, 63), (7, 9, 8))))
    small.putdata(colors)
    img = small.resize((WIDTH, HEIGHT), Image.Resampling.BICUBIC).convert("RGBA")
    rules = Image.new("RGBA", img.size)
    draw = ImageDraw.Draw(rules)
    # Fine ruled wall and a recessed diagonal light field behind the hero.
    draw.polygon([(1204, 0), (1919, 0), (1919, 1079), (914, 1079)],
                 fill=(109, 139, 128, 16))
    draw.line((1204, 0, 914, 1079), fill=(152, 177, 160, 48), width=2)
    draw.line((1221, 0, 931, 1079), fill=(130, 157, 141, 29), width=1)
    for x in range(1204, WIDTH, 108):
        draw.line((x, 0, x - 24, HEIGHT), fill=(148, 169, 148, 21), width=1)
    for y in range(72, HEIGHT, 72):
        draw.line((1204 - int(y * .265), y, WIDTH, y), fill=(113, 151, 136, 25))
    return Image.alpha_composite(img, rules)


def contain_cutout(path, maximum, vertical_slice=None):
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
        box = rgba.getchannel("A").getbbox()
        if not box:
            raise ValueError(f"Empty render: {path}")
        rgba = rgba.crop(box)
        if vertical_slice:
            top, bottom = (round(rgba.height * extent) for extent in vertical_slice)
            rgba = rgba.crop((0, top, rgba.width, bottom))
        return ImageOps.contain(rgba, maximum, Image.Resampling.LANCZOS)


def card(canvas, scratch, stem, label, left, vertical_slice=None):
    width, top, height = 246, 651, 275
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((left, top, left + width, top + height),
                   fill=(24, 32, 31), outline=(80, 93, 83), width=1)
    draw.line((left + 18, top + 214, left + width - 18, top + 214),
              fill=(80, 93, 83), width=1)
    cutout = contain_cutout(scratch / (stem + ".png"), (width - 36, 178), vertical_slice)
    canvas.alpha_composite(cutout, (left + (width - cutout.width) // 2,
                                    top + 18 + (178 - cutout.height) // 2))
    tracked(draw, (left + 18, top + 235), label, font(18, 630), 1.7, PAPER)


def compose(scratch, output):
    canvas = backdrop()
    shadow = Image.new("RGBA", canvas.size)
    ImageDraw.Draw(shadow).ellipse((1020, 972, 1850, 1040), fill=(3, 7, 7, 175))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(26)))
    hero = contain_cutout(scratch / "hero.png", (720, 960))
    canvas.alpha_composite(hero, (1438 - hero.width // 2, 1012 - hero.height))

    draw = ImageDraw.Draw(canvas)
    draw.line((96, 129, 255, 129), fill=WARM, width=4)
    tracked(draw, (96, 91), "POWERED ARMOR SYSTEM", font(22, 650), 3.2, WARM)
    draw.text((83, 200), "JUGGERNAUT", font=font(179, 740, 77), fill=PAPER, anchor="lt")
    tracked(draw, (98, 361), "FROM TUSHONKAGROUP", font(27, 580), 3.3, PAPER)
    draw.line((98, 441, 880, 441), fill=(91, 107, 101), width=1)
    draw.text((96, 483), "Heavy armored exoskeleton", font=font(37, 530), fill=PAPER, anchor="lt")
    draw.text((98, 536), "Sealed helmet · Modular power and optics",
              font=font(27), fill=MUTED, anchor="lt")
    card(canvas, scratch, "thermal_module", "THERMAL MODULE", 97)
    card(canvas, scratch, "power_cell", "POWER CELL", 365)
    card(canvas, scratch, "hero_back", "REAR DOCK", 633, (.12, .51))
    draw.line((98, 979, 880, 979), fill=(98, 111, 105), width=1)
    tracked(draw, (98, 1005), "SINGLE PLAYER TARKOV", font(17, 530), 2.8, MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, optimize=True)
    print(f"BANNER_WRITTEN {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, default=Path(os.environ["TEMP"]) / "juggernaut-banner")
    parser.add_argument("--output", type=Path, default=ROOT / "art/banner.png")
    arguments = parser.parse_args()
    compose(arguments.scratch, arguments.output)
