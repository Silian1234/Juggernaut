"""Bake a short-range dirt mask from the assembled rest model for each LOD.

Run in Blender after bake_layout.py. The texture baker interpolates these values
on the original atlas triangles. Samples ignore studio and reference geometry.
"""
from pathlib import Path
from math import cos, sin, sqrt, tau
import json

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


WORK = Path(__file__).resolve().parents[1] / "work/bake"
NAMES = ("armor", "textile", "frame", "helmet")
RADIUS = .048
BIAS = .00055
RAYS = 18


def directional_samples():
    directions = []
    for i in range(RAYS):
        r = sqrt((i + .5) / RAYS)
        phi = tau * i * .618033988749895
        directions.append((r * cos(phi), r * sin(phi), sqrt(1 - r * r)))
    return directions


def sample_shell(points, normals, tree):
    samples = directional_samples()
    out = np.zeros(len(points), dtype=np.float32)
    up, across = Vector((0, 0, 1)), Vector((1, 0, 0))
    for i, (point, axis) in enumerate(zip(points, normals)):
        n = Vector(axis).normalized()
        tangent = n.cross(up if abs(n.z) < .93 else across).normalized()
        bitangent = n.cross(tangent)
        origin = Vector(point) + n * BIAS
        obscured = 0
        for x, y, z in samples:
            direction = tangent*x + bitangent*y + n*z
            _, _, face, distance = tree.ray_cast(origin, direction, RADIUS)
            if face is not None:
                obscured += (1 - distance/RADIUS)**1.4
        out[i] = obscured / len(samples)
    return out


def main():
    buffers = {}
    values = {}
    for name in NAMES:
        with np.load(WORK / (name + ".npz")) as src:
            buffers[name] = tuple(src[k] for k in ("pos", "normals", "lod"))
        values[name] = np.zeros(buffers[name][0].shape[:2], np.float32)
    stats = {"ray_count": RAYS, "radius_mm": RADIUS * 1000, "bias_mm": BIAS * 1000}
    for lod in (0, 1):
        positions = np.concatenate([p[levels == lod] for p, _, levels in buffers.values()])
        positions = positions.reshape(-1, 3)
        indices = np.arange(len(positions)).reshape(-1, 3)
        tree = BVHTree.FromPolygons(positions.tolist(), indices.tolist(), all_triangles=True)
        for name, (p, n, levels) in buffers.items():
            mask = levels == lod
            corners = np.column_stack((p[mask].reshape(-1, 3), n[mask].reshape(-1, 3)))
            # Identical split-loop positions and normals share the same rays.
            _, first, inverse = np.unique(corners.round(5), axis=0, return_index=True, return_inverse=True)
            unique = corners[first]
            cavity = sample_shell(unique[:, :3], unique[:, 3:], tree)
            values[name][mask] = cavity[inverse].reshape(-1, 3)
            print(f"Cavity LOD{lod} {name}: {len(unique)} origins", flush=True)
    for name, field in values.items():
        np.save(WORK / (name + "_cavity.npy"), field)
        stats[name] = {"mean": float(field.mean()), "p95": float(np.percentile(field,95))}
    (WORK / "cavity.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
