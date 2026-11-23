"""Compare occupied orthographic pixel area of the two LOD0 suits at equal scale."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("JUGGERNAUT_EXO_SOURCE", "C:/SPT/_fullbody_armor/exoskeleton/gpt"))
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))
PIXELS_PER_METRE = 800


def coverage(triangles):
    # Pixel-center rasterization at the same world-space resolution for both suits.
    xy = triangles * PIXELS_PER_METRE
    xy -= np.floor(xy.min(axis=(0, 1)))
    mask = np.zeros(tuple(np.ceil(xy.max(axis=(0, 1))).astype(int) + 1), dtype=bool)
    for a, b, c in xy:
        points = np.stack((a, b, c))
        left, bottom = np.floor(points.min(axis=0)).astype(int)
        right, top = np.ceil(points.max(axis=0)).astype(int)
        x, y = np.ogrid[left:right, bottom:top]
        def side(p, q):
            return (q[0]-p[0]) * (y+.5-p[1]) - (q[1]-p[1]) * (x+.5-p[0])
        if abs((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])) > 1e-6:
            ab, bc, ca = side(a, b), side(b, c), side(c, a)
            mask[left:right, bottom:top] |= ((ab >= 0) & (bc >= 0) & (ca >= 0)
                                              | (ab <= 0) & (bc <= 0) & (ca <= 0))
    return round(np.count_nonzero(mask) / PIXELS_PER_METRE**2, 4)


def measure(path):
    bpy.ops.wm.open_mainfile(filepath=str(path))
    review = runpy.run_path(str(SOURCE / "review.py"))
    review["set_pose"]("down60")
    deps = bpy.context.evaluated_depsgraph_get()
    triangles = []
    for obj in bpy.data.collections["EXO_LOD0"].objects:
        vertices, faces = review["_mesh"](obj, deps)
        triangles.append(np.asarray(vertices)[np.asarray(faces)])
    xyz = np.concatenate(triangles)
    return {name: coverage(xyz[:, :, axes]) for name, axes in (("front_m2", [0, 2]), ("side_m2", [1, 2]))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suit", type=Path, default=ROOT / "art/suit/suit.blend")
    parser.add_argument("--out", type=Path, default=ROOT / "art/suit/silhouette.json")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    source = SOURCE / "exo_t3a.blend"
    suit = args.suit.resolve()
    result = {"exo_t3a": measure(source), "juggernaut": measure(suit),
              "pose": "down60", "pixels_per_metre": PIXELS_PER_METRE,
              "source_blend_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "suit_blend_sha256": hashlib.sha256(suit.read_bytes()).hexdigest()}
    print(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
