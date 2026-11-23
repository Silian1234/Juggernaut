"""Audit channel bytes from the delivered PNGs without rewriting them."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from bake_raster import MAX_NORMAL_SLOPE, ROOT, SIZES, STAGING, audit_normals

MODES = {
    "albedo": "RGBA", "normal": "RGB", "specgloss": "RGBA",
    "metallic": "L", "normal_dxt5nm": "RGBA", "ao": "L",
    "curvature": "L", "position": "L",
}


def equal(left, right):
    return ImageChops.difference(left, right).getbbox() is None


def audit(atlas_path):
    report = {"atlases": {}, "errors": []}
    for atlas, size in SIZES.items():
        data = {}
        records = {}
        normal_audit = None
        for role, mode in MODES.items():
            path = atlas_path / f"{atlas}_{role}.png"
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                image.load()
                if image.mode != mode or image.size != (size, size):
                    raise ValueError(f"{path.name} has {image.mode} {image.size}; expected {mode} {size}px square")
                if role == "normal":
                    normal_audit = audit_normals(np.asarray(image))
                split = image.split()
                data[role] = split
                with path.open("rb") as stream:
                    sha = file_digest(stream, "sha256").hexdigest()
                records[role] = {
                    "size": list(image.size), "mode": image.mode, "sha256": sha,
                    "channel_byte_ranges": [channel.getextrema() for channel in split],
                }
        albedo, normal, spec, swizzle = (
            data[key] for key in ("albedo", "normal", "specgloss", "normal_dxt5nm")
        )
        equivalence = {
            "albedo_gloss_matches_specular_gloss": equal(albedo[3], spec[3]),
            "runtime_normal_r_is_255": swizzle[0].getextrema() == (255, 255),
            "runtime_normal_g_and_b_match_tangent_y": equal(swizzle[1], normal[1]) and equal(swizzle[2], normal[1]),
            "runtime_normal_a_matches_tangent_x": equal(swizzle[3], normal[0]),
        }
        tint = ImageChops.lighter(ImageChops.difference(spec[0], spec[1]), ImageChops.difference(spec[1], spec[2]))
        report["atlases"][atlas] = {
            "files": records, "channel_equivalence": equivalence,
            "tinted_specular_texels": size * size - tint.histogram()[0],
            "normal_audit": normal_audit,
        }
        report["errors"].extend(f"{atlas}: {name}" for name, valid in equivalence.items() if not valid)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--textures", type=Path, default=ROOT / "textures" / "v5d")
    parser.add_argument("--report", type=Path, default=STAGING / "qa_images.json")
    args = parser.parse_args()
    report = audit(args.textures)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{args.report}: {len(report['errors'])} channel errors, normal slopes at most {MAX_NORMAL_SLOPE}")
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
