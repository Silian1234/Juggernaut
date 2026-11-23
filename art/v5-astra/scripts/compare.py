"""Compare the archived V5C Cycles views against the V5D armor."""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ENTRY = Path(__file__).resolve().parents[1]
WORK = ENTRY / "work" / "render"
BASELINE = ENTRY / "work" / "v5d" / "before"
BACKGROUND = (24, 26, 29)
PANEL = (36, 39, 43)
LABEL = (221, 224, 228)
WIDTH = 1920
GAP = 12
PAD = 18
CAPTION = 40


def load(path):
    with Image.open(path) as source:
        return source.convert("RGB")


def row(canvas, y, height, columns, font):
    draw = ImageDraw.Draw(canvas)
    width = (WIDTH - 2 * PAD - (len(columns) - 1) * GAP) // len(columns)
    for i, (label, source) in enumerate(columns):
        x = PAD + i * (width + GAP)
        image = ImageOps.contain(source, (width, height), Image.Resampling.LANCZOS)
        draw.rectangle((x, y + CAPTION, x + width - 1, y + CAPTION + height - 1), fill=PANEL)
        draw.text((x + 8, y + 7), label, font=font, fill=LABEL)
        canvas.paste(image, (x + (width - image.width) // 2,
                             y + CAPTION + (height - image.height) // 2))
    return y + CAPTION + height + GAP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--output", type=Path, help="Build the board beside a dedicated render set")
    parser.add_argument("--before", type=Path, default=BASELINE,
                        help="Directory containing archived V5C renders")
    args = parser.parse_args()
    custom = args.output.resolve() if args.output else None
    if custom and not custom.is_relative_to(ENTRY):
        parser.error("--output must stay within art/v5-astra")
    renders = custom or (WORK / "draft" if args.draft else WORK / "final-stage" if args.staged
                         else ENTRY / "renders")
    rows = (
        (465, (
            ("V5C / Five views", load(args.before / "sheet.png")),
            ("V5D / Five views", load(renders / "sheet.png")),
        )),
        (455, (
            ("V5C / Front", load(args.before / "legs_front.png")),
            ("V5D / Front", load(renders / "legs_front.png")),
            ("V5C / Rear", load(args.before / "legs_back.png")),
            ("V5D / Rear", load(renders / "legs_back.png")),
        )),
    )
    canvas_height = PAD * 2 + sum(height + CAPTION + GAP for height, _ in rows) - GAP
    canvas = Image.new("RGB", (WIDTH, canvas_height), BACKGROUND)
    font = ImageFont.load_default(size=22)
    y = PAD
    for height, columns in rows:
        y = row(canvas, y, height, columns, font)
    output = renders / "comparison.png"
    canvas.save(output)
    print(f"REVIEW_WRITTEN {output} {canvas.width}x{canvas.height}")


if __name__ == "__main__":
    main()

