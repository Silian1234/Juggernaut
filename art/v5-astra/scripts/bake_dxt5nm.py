"""Prepare/verify the exact uncompressed DXT5nm swizzle used by the EFT bundles."""

from pathlib import Path

from PIL import Image, ImageChops


TEXTURES = Path(__file__).resolve().parents[1] / "textures" / "v5d"
ATLASES = ("armor", "textile", "frame", "helmet")


def swizzle(path, target):
    with Image.open(path) as source:
        if source.mode != "RGB":
            raise ValueError(f"{path}: expected an RGB OpenGL tangent normal map")
        x, y, _ = source.split()
        white = Image.new("L", source.size, 255)
        # This is the same per-pixel encoding as tools/unity/suit_serial_build.py.
        # PNGs retain artist row order. The Unity serializer flips rows at export.
        Image.merge("RGBA", (white, y, y, x)).save(target)
    with Image.open(target) as saved:
        if saved.mode != "RGBA" or saved.size != white.size:
            raise ValueError(f"{target}: invalid format")
        for actual, expected in zip(saved.split(), (white, y, y, x), strict=True):
            if ImageChops.difference(actual, expected).getbbox() is not None:
                raise ValueError(f"{target}: DXT5nm channel verification failed")
        print(f"V5d verified {target.name} {saved.width} px: R=255, G=Y, B=Y, A=X")


if __name__ == "__main__":
    for atlas in ATLASES:
        swizzle(TEXTURES / f"{atlas}_normal.png", TEXTURES / f"{atlas}_normal_dxt5nm.png")
