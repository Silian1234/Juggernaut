"""Assemble inspection contacts from full-size studio PNGs after the Blender renders."""
import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


REFERENCES = Path(__file__).resolve().parents[2] / "docs/feedback/refs"


def label(draw, x, y, title, face):
    draw.text((x, y), title, font=face, anchor="mt", fill=(235, 237, 227))


def comparison_sheet(root, face):
    views = (("front", "FRONT"), ("back", "BACK"), ("side", "SIDE · THERMAL FITTED"))
    tile = (500, 467)
    canvas = Image.new("RGB", (tile[0] * len(views), tile[1] + 34), (19, 22, 22))
    draw = ImageDraw.Draw(canvas)
    for index, (name, title) in enumerate(views):
        with Image.open(root / "previews" / f"{name}.png") as image:
            if image.size != (1500, 1400):
                raise ValueError(f"{name} comparison has unexpected size {image.size}")
            x = index * tile[0]
            canvas.paste(image.resize(tile, Image.Resampling.LANCZOS), (x, 0))
            label(draw, x + tile[0] // 2, tile[1] + 7, title, face)
    canvas.save(root / "comparison-contact.png")


def design_review(root, face):
    canvas = Image.new("RGB", (1720, 1450), (19, 22, 23))
    draw = ImageDraw.Draw(canvas)
    title_face = ImageFont.truetype(face.path, 30)
    draw.text((32, 21), "JUGGERNAUT / VISUAL REVIEW", font=title_face, fill=(235, 237, 227))
    accent = (225, 177, 111)
    for index, (stem, view) in enumerate((("front", "FRONT"), ("three_quarter", "THREE QUARTER"))):
        x = 32 + index * 838
        with Image.open(root / "previews" / f"{stem}.png") as image:
            if image.size != (1500, 1400):
                raise ValueError(f"{stem} review has unexpected size {image.size}")
            canvas.paste(image.resize((790, 737), Image.Resampling.LANCZOS), (x, 98))
        draw.text((x, 71), view, font=face, fill=accent)
        label(draw, x + 197, 846, "JUGGERNAUT", face)
        label(draw, x + 593, 846, "VANILLA USEC PMC · SAME SCALE", face)
    for index, (filename, description) in enumerate((
        ("ref1_tactical_heavy.png", "REF 1 · TACTICAL HEAVY"),
        ("ref6_engineer_specialist.png", "REF 6 · ENGINEER SPECIALIST"),
    )):
        x = 32 + index * 838
        draw.line((x, 889, x + 790, 889), fill=(88, 97, 93))
        draw.text((x, 904), description, font=face, fill=accent)
        with Image.open(REFERENCES / filename) as image:
            reference = ImageOps.contain(image.convert("RGB"), (790, 497), Image.Resampling.LANCZOS)
        canvas.paste(reference, (x + (790 - reference.width) // 2, 935))
    canvas.save(root / "design-review.png")


def icon_sheet(root, face):
    icons = ("suit", "helmet", "thermal_module", "power_cell")
    canvas = Image.new("RGBA", (278 * len(icons), 286), (26, 31, 31, 255))
    draw = ImageDraw.Draw(canvas)
    for index, name in enumerate(icons):
        with Image.open(root / "icons" / f"{name}.png") as image:
            if image.size != (256, 256) or image.mode != "RGBA" or image.getextrema()[3] != (0, 255):
                raise ValueError(f"{name} must be a 256×256 transparent PNG")
            x = index * 278
            canvas.alpha_composite(image, (x + 11, 0))
            label(draw, x + 139, 264, name.replace("_", " ").upper(), face)
    canvas.convert("RGB").save(root / "icon-contact.png")


def detail_sheet(root, face):
    details = (("visor", "VISOR, SHOULDERS AND RIG"), ("cassette", "REAR CASSETTE AND HOSES"),
               ("ankle", "OUTER LEG FRAME AND ANKLE"), ("pouches", "COYOTE POUCH FABRIC"))
    canvas = Image.new("RGB", (1624, 1742), (19, 22, 23))
    draw = ImageDraw.Draw(canvas)
    draw.text((22, 15), "JUGGERNAUT / EQUIPMENT DETAILS",
              font=ImageFont.truetype(face.path, 30), fill=(235, 237, 227))
    for index, (name, title) in enumerate(details):
        row, column = divmod(index, 2)
        x, y = 22 + column * 800, 62 + row * 834
        draw.text((x, y), title, font=face, fill=(225, 177, 111))
        with Image.open(root / "detail-renders" / f"{name}.png") as image:
            if image.size != (780, 780):
                raise ValueError(f"{name} detail has unexpected size {image.size}")
            canvas.paste(image, (x, y + 26))
    canvas.save(root / "previews" / "details.png")


def flex_sheet(root, face):
    poses = (("crouch", "CROUCH"), ("elbow110", "ELBOW 110°"), ("knee120", "KNEE 120°"))
    tile = (350, 377)
    masthead = 32
    canvas = Image.new("RGB", (tile[0] * len(poses), masthead + tile[1] * 2), (19, 22, 22))
    draw = ImageDraw.Draw(canvas)
    for col, (pose, title) in enumerate(poses):
        x = col * tile[0]
        label(draw, x + tile[0] // 2, 7, title, face)
        for row, view in enumerate(("three_quarter", "side")):
            with Image.open(root / "flex" / f"{pose}_{view}.png") as image:
                if image.size != (520, 560):
                    raise ValueError(f"{pose} {view} has unexpected size {image.size}")
                canvas.paste(image.resize(tile, Image.Resampling.LANCZOS),
                             (x, masthead + row * tile[1]))
    canvas.save(root / "flex-contact.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("render_output", type=Path)
    parser.add_argument("--flex", action="store_true")
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()
    root = args.render_output
    face = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts/bahnschrift.ttf"), 16)
    comparison_sheet(root, face)
    design_review(root, face)
    icon_sheet(root, face)
    with Image.open(root / "banner.png") as banner:
        if banner.size != (1920, 1080) or banner.mode != "RGB":
            raise ValueError("Banner must be a 1920×1080 RGB PNG")
    if args.flex:
        flex_sheet(root, face)
    if args.details:
        detail_sheet(root, face)
    print("Verified dimensions and wrote contact sheets")


if __name__ == "__main__":
    main()
