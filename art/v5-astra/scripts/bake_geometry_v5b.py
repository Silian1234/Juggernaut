"""Sample geometry masks on the frozen UV triangle buffers.

Run in background Blender. Each LOD casts against its complete assembled
surface, and adjacent polygons can contribute curvature across atlas seams.
"""

from collections import defaultdict
from hashlib import sha256
import json
from math import cos, sin, sqrt, tau
from pathlib import Path

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


WORK = Path(__file__).resolve().parents[1] / "work/bake"
ATLASES = ("armor", "textile", "frame", "helmet")
SOURCE_FIELDS = ("pos", "normals", "lod", "obj", "polygon", "uv")
RAYS = 72
AO_RADIUS = 0.090
CONTACT_RADIUS = 0.022
ORIGIN_BIAS = 0.00028
WELD_SCALE = 1_000_000


def normalized(values):
    lengths = np.linalg.norm(values, axis=-1, keepdims=True)
    return np.divide(values, lengths, out=np.zeros_like(values), where=lengths > 1e-12)


def signed_dihedrals(positions, objects, polygons):
    """Signed polygon dihedrals on welded edges, indexed by opposing corner."""
    welded = np.column_stack((
        np.repeat(objects, 3),
        np.rint(positions.reshape(-1, 3) * WELD_SCALE).astype(np.int64),
    ))
    keys, inverse = np.unique(welded, axis=0, return_inverse=True)
    vertices = inverse.reshape(-1, 3)

    _, face_ids = np.unique(np.column_stack((objects, polygons)), axis=0, return_inverse=True)
    geometric_normals = np.cross(positions[:, 1] - positions[:, 0],
                                 positions[:, 2] - positions[:, 0])
    face_normals = np.zeros((int(face_ids.max()) + 1, 3))
    np.add.at(face_normals, face_ids, geometric_normals)
    face_normals = normalized(face_normals)

    users = defaultdict(list)
    for triangle, ids in enumerate(vertices.tolist()):
        for corner in range(3):
            first = ids[(corner + 1) % 3]
            second = ids[(corner + 2) % 3]
            if first != second:
                low, high = sorted((first, second))
                users[low, high].append((triangle, corner, first == low))

    convex = np.zeros(positions.shape[:2], np.float32)
    concave = np.zeros_like(convex)
    strongest_convex = np.zeros(len(keys), np.float32)
    strongest_concave = np.zeros(len(keys), np.float32)
    for (low, high), adjacent in users.items():
        # An internal tessellation edge or a non-manifold edge has no
        # unambiguous curvature from a pair of outward-facing polygons.
        if len(adjacent) != 2:
            continue
        (a, corner_a, forward_a), (b, corner_b, forward_b) = adjacent
        if forward_a == forward_b or face_ids[a] == face_ids[b]:
            continue
        first_normal, second_normal = face_normals[[face_ids[a], face_ids[b]]]
        axis = normalized((keys[high, 1:] - keys[low, 1:]).astype(np.float64))
        if not forward_a:
            axis = -axis
        angle = np.arctan2(np.dot(axis, np.cross(first_normal, second_normal)),
                           np.dot(first_normal, second_normal))
        amount = float(np.clip((abs(angle) - np.deg2rad(3)) / np.deg2rad(57), 0, 1))
        if angle > 0:
            field, peaks = convex, strongest_convex
        else:
            field, peaks = concave, strongest_concave
        field[a, corner_a] = field[b, corner_b] = amount
        peaks[low] = max(peaks[low], amount)
        peaks[high] = max(peaks[high], amount)
    return convex, concave, (strongest_convex - strongest_concave)[vertices]


def hemisphere():
    for i in range(RAYS):
        fraction = (i + .5) / RAYS
        azimuth = tau * i * .618033988749895
        yield sqrt(fraction) * cos(azimuth), sqrt(fraction) * sin(azimuth), sqrt(1 - fraction)


def sample_visibility(points, axes, tree):
    samples = list(hemisphere())
    contact_falloff = 1 / CONTACT_RADIUS
    ao_falloff = 1 / AO_RADIUS
    visibility = np.ones(len(points), dtype=np.float32)
    contact = np.zeros_like(visibility)
    up, across = Vector((0, 0, 1)), Vector((1, 0, 0))
    for i, (point, axis) in enumerate(zip(points, axes)):
        normal = Vector(axis).normalized()
        tangent = normal.cross(up if abs(normal.z) < .93 else across).normalized()
        bitangent = normal.cross(tangent)
        origin = Vector(point) + normal * ORIGIN_BIAS
        nearby = 0.0
        blocked = 0.0
        for x, y, z in samples:
            direction = tangent * x + bitangent * y + normal * z
            _, _, face, distance = tree.ray_cast(origin, direction, AO_RADIUS)
            if face is not None:
                blocked += (1 - distance * ao_falloff) ** 1.35
                nearby += max(0, 1 - distance * contact_falloff) ** 1.25
        visibility[i] -= blocked / RAYS
        contact[i] = nearby / RAYS
    return visibility, contact


def sample_atlas(positions, normals, tree):
    # Deduplicate split loops that have the same position and shading normal.
    corners = np.column_stack((positions.reshape(-1, 3), normals.reshape(-1, 3)))
    _, first, inverse = np.unique(corners.round(6), axis=0, return_index=True, return_inverse=True)
    unique = corners[first]
    vertex_ao, vertex_contact = sample_visibility(unique[:, :3], unique[:, 3:], tree)
    center_ao, center_contact = sample_visibility(
        positions.mean(axis=1), normalized(normals.mean(axis=1)), tree,
    )
    return {
        "vertex_ao": vertex_ao[inverse].reshape(-1, 3),
        "center_ao": center_ao,
        "vertex_contact": vertex_contact[inverse].reshape(-1, 3),
        "center_contact": center_contact,
    }


def main():
    buffers = {}
    fields = {}
    stats = {"rays": RAYS, "ao_radius_m": AO_RADIUS, "contact_radius_m": CONTACT_RADIUS,
             "bias_m": ORIGIN_BIAS, "atlases": {}}
    for name in ATLASES:
        with np.load(WORK / f"{name}.npz") as source:
            buffers[name] = {key: source[key] for key in SOURCE_FIELDS}
        shape = buffers[name]["pos"].shape[:2]
        fields[name] = {key: np.zeros(shape, np.float32) for key in (
            "convex_edges", "concave_edges", "vertex_signed_curvature",
            "vertex_ao", "vertex_contact", "vertex_height",
        )}
        for key in ("center_ao", "center_contact"):
            fields[name][key] = np.zeros(shape[0], np.float32)

    bottom = min(buffer["pos"][..., 2].min() for buffer in buffers.values())
    top = max(buffer["pos"][..., 2].max() for buffer in buffers.values())
    stats["height_range_m"] = [float(bottom), float(top)]
    for lod in (0, 1):
        selected = {name: buffer["lod"] == lod for name, buffer in buffers.items()}
        positions, objects, polygons = (
            np.concatenate([buffers[name][key][selected[name]] for name in ATLASES])
            for key in ("pos", "obj", "polygon")
        )
        triangles = np.arange(positions.size // 3).reshape(-1, 3)
        tree = BVHTree.FromPolygons(positions.reshape(-1, 3).tolist(), triangles.tolist(),
                                    all_triangles=True)
        print(f"LOD{lod}: {len(triangles)} triangles in assembled occlusion mesh", flush=True)
        convex, concave, signed = signed_dihedrals(positions, objects, polygons)
        start = 0
        for name, mask in selected.items():
            count = np.count_nonzero(mask)
            if count == 0:
                continue
            section = slice(start, start + count)
            data = fields[name]
            data["convex_edges"][mask] = convex[section]
            data["concave_edges"][mask] = concave[section]
            data["vertex_signed_curvature"][mask] = signed[section]
            data["vertex_height"][mask] = (positions[section, :, 2] - bottom) / (top - bottom)
            for key, values in sample_atlas(
                positions[section], buffers[name]["normals"][mask], tree
            ).items():
                data[key][mask] = values
            start += count
            print(f"LOD{lod}: sampled {count} triangles for {name}", flush=True)
        assert start == len(positions)

    for name, data in fields.items():
        report = {}
        for key, values in data.items():
            low = -1 if key == "vertex_signed_curvature" else 0
            assert np.isfinite(values).all() and low <= values.min() <= values.max() <= 1
            report[key] = {"min": float(values.min()), "mean": float(values.mean()),
                           "max": float(values.max())}
        report["triangle_count"] = len(buffers[name]["pos"])
        source_hash = sha256()
        for key in SOURCE_FIELDS:
            source_hash.update(buffers[name][key].tobytes())
        report["source_sha256"] = source_hash.hexdigest()
        stats["atlases"][name] = report
        np.savez_compressed(WORK / f"{name}_geometry_v5b.npz", **data)
    (WORK / "geometry_v5b.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
