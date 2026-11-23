"""Measure matched horizontal sections of an EFT outfit in Blender.

Run against the suit blend with --accessories and --out after Blender's --.
Use --reference-only instead of --accessories for the vanilla benchmark.
An optional --head-json accepts a vanilla head in Blender world coordinates.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_art import load_accessories, presentation_pose
from pmc_reference import load_pmc
from v2_fit_qa import digest, object_set, review


SLICES = {
    "shoulder": 1.485,
    "chest": 1.375,
    "waist": 1.115,
}
CENTRAL = {"Pelvis", "Spine1", "Spine2", "Spine3", "Neck", "LCollarbone", "RCollarbone"}
SHOULDER = CENTRAL | {"LUpperarm", "RUpperarm"}
HEAD_BASE_Z = 1.6


def section_edges(meshes, sections, depsgraph):
    points = {name: [] for name in sections}
    extremes = {name: [] for name in sections}
    for obj in meshes:
        mesh = obj.data
        mesh.calc_loop_triangles()
        vertices, faces = review._mesh(obj, depsgraph)
        if len(mesh.vertices) != len(vertices) or len(mesh.loop_triangles) != len(faces):
            raise ValueError(f"Evaluated topology changed for {obj.name}")
        for name, z in sections.items():
            allowed = SHOULDER if name == "shoulder" else CENTRAL
            groups = {group.index for group in obj.vertex_groups
                      if group.name.removeprefix("Base Human") in allowed}
            weights = [sum(group.weight for group in vertex.groups if group.group in groups)
                       for vertex in mesh.vertices]
            for face in faces:
                if sum(weights[i] for i in face) < 1.5:
                    continue
                a, b, c = (vertices[i] for i in face)
                for start, end in ((a, b), (b, c), (c, a)):
                    if (start.z <= z < end.z) or (end.z <= z < start.z):
                        p = start.lerp(end, (z - start.z) / (end.z - start.z))
                        points[name].append(p)
                        extremes[name].append((p.x, obj.name))
    return {
        name: {**span(values),
               "lateral_extreme_objects": [min(extremes[name])[1], max(extremes[name])[1]]}
        for name, values in points.items()
    }


def span(points):
    low, high = zip(*(minmax(axis) for axis in zip(*points)))
    return {
        "bounds_world_m": [[round(v, 5) for v in corner] for corner in (low, high)],
        **{label + "_mm": round((end - start) * 1000, 2)
           for label, start, end in zip(("width", "depth", "height"), low, high)},
    }


def minmax(values):
    return min(values), max(values)


def head_vertices(path):
    return [Vector(point) for point in json.loads(path.read_text(encoding="utf-8"))["positions"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--accessories", type=Path)
    source.add_argument("--reference-only", action="store_true")
    parser.add_argument("--head-json", type=Path)
    parser.add_argument("--pmc-assets", type=Path, help="Extracted vanilla meshes used for the matched PMC render.")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.pmc_assets and not args.head_json:
        args.head_json = args.pmc_assets / "usec_head.json"
    if args.reference_only and not args.head_json:
        parser.error("--reference-only requires --head-json")
    vanilla_head = head_vertices(args.head_json) if args.head_json else []
    above_neck = [vertex for vertex in vanilla_head if vertex.z >= HEAD_BASE_Z]
    refs = [bpy.data.objects[name] for name in ("REF_top", "REF_pants")]
    for obj in refs:
        obj.hide_viewport = False
        obj.hide_set(False)
    data = {
        "blend_sha256": digest(Path(bpy.data.filepath)),
        "section_method": "World X span and Y span of exact horizontal triangle-edge cuts. "
                          "Retain triangles with mean listed skeleton weight >= 0.5. For shoulders "
                          "only, add the upper arms to the centerline bone set. Elbows, forearms, "
                          "hands and legs are excluded from all three sections.",
        "slice_labels": {name: {"z_m": z, "bones": sorted(SHOULDER if name == "shoulder" else CENTRAL)}
                         for name, z in SLICES.items()},
        "poses": {},
    }
    suit = refs if args.reference_only else object_set(0)
    if args.pmc_assets:
        data["pmc_mesh_sources"] = {
            stem: digest(args.pmc_assets / f"{stem}.json")
            for stem in ("usec_body", "pants_usec_commando", "usec_head")
        }
        if args.reference_only:
            suit, _ = load_pmc(bpy.context.scene, args.pmc_assets.resolve(), review.ARM)
    if args.accessories:
        helmet, _, _ = load_accessories(args.accessories.resolve())
        data["accessories_sha256"] = digest(args.accessories)
    else:
        helmet = []
    bpy.context.view_layer.update()
    try:
        for pose, arm_angles in (
            ("rest", None),
            ("presentation_arms_down_52", (52, 0)),
            ("presentation_arms_down_36_sweep_23", (36, 23)),
        ):
            if arm_angles is None:
                review.set_pose("rest")
            else:
                presentation_pose(review.ARM, *arm_angles)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            sections = section_edges(suit, SLICES, depsgraph)
            head = ([v for obj in helmet for v in review._mesh(obj, depsgraph)[0]]
                    if helmet else above_neck)
            head_bounds = span(head)
            sections["helmet" if helmet else "vanilla_head"] = head_bounds
            sections["head_to_shoulder_width"] = round(
                head_bounds["width_mm"] / sections["shoulder"]["width_mm"], 4)
            sections["waist_to_chest_width"] = round(
                sections["waist"]["width_mm"] / sections["chest"]["width_mm"], 4)
            data["poses"][pose] = sections
    finally:
        review.restore_pose()
    if args.head_json:
        data["vanilla_head_json_sha256"] = digest(args.head_json)
        data["vanilla_head_reference"] = {
            "asset": "usec_head_eric.bundle / USEC_head_Eric_lod0_base",
            "full_mesh_bounds": span(vanilla_head),
            "above_neck_z_cutoff_m": HEAD_BASE_Z,
            "above_neck_bounds": span(above_neck),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
