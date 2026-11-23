"""Bake the printing and stamped details on the removable rear cartridge."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "textures/pack"
OUT.mkdir(exist_ok=True)
image = Image.new("RGBA", (768, 512))
height = Image.new("L", image.size, 128)
ink = ImageDraw.Draw(image)
stamp = ImageDraw.Draw(height)


def face(size):
    try:
        return ImageFont.truetype("consolab.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


# Inset rubber seal, recessed captive screws and diagonal tool slots.
for inset, gray, relief in ((14, 26, 155), (19, 12, 105), (25, 52, 142)):
    rect = (inset, inset, 767-inset, 511-inset)
    ink.rounded_rectangle(rect, radius=19, outline=(gray, gray, gray-1, 154), width=3)
    stamp.rounded_rectangle(rect, radius=19, outline=relief, width=4)
for x, y in ((47, 48), (721, 48), (47, 465), (721, 465)):
    ink.ellipse((x-10,y-10,x+10,y+10), fill=(42,42,40,225), outline=(72,72,68,190), width=2)
    ink.line((x-5,y+4,x+5,y-4), fill=(14,14,13,245), width=3)
    stamp.ellipse((x-10,y-10,x+10,y+10), fill=146, outline=85, width=3)
    stamp.line((x-5,y+4,x+5,y-4), fill=73, width=3)

# Stencilled manufacturer tag and narrow, glass-covered state-of-charge window.
ink.rounded_rectangle((93,71,673,265), radius=4, fill=(58,58,52,224))
stamp.rounded_rectangle((93,71,673,265), radius=4, fill=137)
ink.text((119,82), "TG  /  ЭНЕРГОБЛОК", font=face(38), fill=(160,157,140,218))
ink.line((120,143,642,143), fill=(155,150,132,174), width=3)
ink.text((121,161),"БП-05   24 В",font=face(32),fill=(153,150,134,226))
ink.text((121,211),"СЕР.  05-0417",font=face(23),fill=(130,127,112,210))
ink.rounded_rectangle((443,173,645,219),radius=7,fill=(18,21,21,255),outline=(95,93,82,204),width=3)
stamp.rounded_rectangle((443,173,645,219),radius=7,fill=102,outline=150,width=3)
for i in range(5):
    color = (127,103,50,223) if i == 0 else (53,56,50,229)
    ink.rectangle((457+i*36,185,481+i*36,206),fill=color)
for y in (325, 351, 377, 403):
    ink.rounded_rectangle((142,y,627,y+10),radius=4,fill=(21,22,21,198))
    ink.line((151,y+10,620,y+10),fill=(65,65,58,142),width=2)
    stamp.rounded_rectangle((142,y,627,y+10),radius=4,fill=85)

image.save(OUT / "cartridge-markings.png")
height.save(OUT / "cartridge-stamp.png")
