"""Extract the TV-110 plate bag, folded pouches and utility pouch from local EFT."""
import argparse
import json
from pathlib import Path

import numpy as np

from extract_pmc_reference import SOURCE, bundle, decode_normal, decode_texture, mesh_data, object_fields, read_string


OUTPUT = Path(__file__).resolve().parents[2] / "art/build/v4-tactical"
BUNDLE = Path("assets/content/items/equipment/rig_tv110/item_equipment_rig_tv110.bundle")
# The groups are sorted by triangle count, leaving equal counts in original
# index-buffer order. Use the textured body renderer mesh, including native seams.
PARTS = (
    {"carrier": (0,), "left": (7, 27, 38), "right": (8, 26, 37), "utility": (3,),
     "tool": (5, 30, 55)},
    {"carrier": (0,), "left": (8, 21, 24), "right": (9, 20, 25), "utility": (2,),
     "tool": (11, 45)},
)
COUNTS = (
    {"carrier": 766, "left": 304, "right": 304, "utility": 354, "tool": 274},
    {"carrier": 204, "left": 93, "right": 84, "utility": 130, "tool": 51},
)


def connected_faces(mesh):
    vertices = np.asarray(mesh["positions"])
    _, weld = np.unique(vertices.round(5), axis=0, return_inverse=True)
    parents = list(range(weld.max() + 1))

    def root(index):
        while parents[index] != index:
            index = parents[index]
        return index

    faces = np.asarray(mesh["triangles"])
    joined = weld[faces]
    for a, b, c in joined:
        parents[root(b)] = parents[root(c)] = root(a)
    groups = {}
    for triangle, (a, _, _) in enumerate(joined):
        groups.setdefault(root(a), []).append(triangle)
    return sorted(groups.values(), key=len, reverse=True)


def select(mesh, groups):
    faces = [mesh["triangles"][i] for i in groups]
    used = sorted({index for face in faces for index in face})
    order = {old: new for new, old in enumerate(used)}
    return {field: [mesh[field][old] for old in used]
            for field in ("positions", "normals", "uv")} | {
                "triangles": [[order[old] for old in face] for face in faces]
            }


def extract(source, output):
    path = source / BUNDLE
    serialized, resources = bundle(path)
    output.mkdir(parents=True, exist_ok=True)
    for lod in (0, 1):
        mesh_name = f"CR_tv110_body_lod{lod}"
        candidates = [record for record in serialized.records.values()
                      if serialized.class_id(record) == 43 and read_string(record.data)[0] == mesh_name]
        mesh = mesh_data(serialized.fields(candidates[0]))
        if any(mesh_data(serialized.fields(record)) != mesh for record in candidates[1:]):
            raise ValueError(f"Nonidentical instances of {mesh_name} in {path}")
        groups = connected_faces(mesh)
        parts = {}
        for name, indices in PARTS[lod].items():
            triangles = [triangle for index in indices for triangle in groups[index]]
            if len(triangles) != COUNTS[lod][name]:
                raise ValueError(f"Unexpected TV-110 mesh topology for {mesh_name} {name}")
            parts[name] = select(mesh, triangles)
        (output / f"tv110-lod{lod}.json").write_text(json.dumps(parts, separators=(",", ":")))
    for name, winding in (("albedo", "diff"), ("normal", "nrm"), ("gloss", "gloss")):
        fields = object_fields(serialized, 28, f"item_equipment_rig_tv110_{winding}")
        texture = decode_texture(fields, resources)
        if name == "normal":
            texture = decode_normal(texture)
        else:
            texture = texture.convert("RGB")
        texture.save(output / f"tv110-{name}.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE, help="Local EFT Windows bundle root")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    extract(args.source, args.output)
