"""Sweep the helmet and fitted RAC past the v4 radio and shoulder shells."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from accessory_qa import (RAC_OFFSET, RAC_PITCH, RAC_WIDTH, bvh_for,
                          donor_triangles, get_triangles, measure_yaw, soft_helmet_face)
from render_art import presentation_pose


ROOT = Path(__file__).resolve().parents[2]
TARGETS = {
    "radio_whip": ("RadioAntennaBase", "RadioFlexibleWhip"),
    "shoulder_shells": ("ShoulderRoof", "ShoulderMiddleLame", "ShoulderLowerLame", "ShoulderMount"),
}


def source_digest(path):
    path = path.resolve()
    name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    return name.as_posix(), sha256(path.read_bytes()).hexdigest()


def measure(moving, fixed):
    sweep = measure_yaw(moving, fixed, bvh_for(fixed))
    angle = min(sweep, key=lambda yaw: sweep[yaw]["nearest_vertex_surface_mm"])
    return {
        "minimum_vertex_surface_mm": sweep[angle]["nearest_vertex_surface_mm"],
        "minimum_distance_yaw_degrees": angle,
        "intersection_pairs_by_yaw_degrees": {
            yaw: row["intersecting_triangle_pairs"] for yaw, row in sweep.items()
            if row["intersecting_triangle_pairs"]
        },
    }


def evaluated_triangles(objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return get_triangles([obj.evaluated_get(depsgraph) for obj in objects])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accessories", type=Path, required=True)
    parser.add_argument("--rac-reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arms-lowered", type=float, default=0)
    parser.add_argument("--arm-sweep", type=float, default=0)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

    suit = Path(bpy.data.filepath)
    groups = {name: bpy.data.collections[name] for name in ("EXO_LOD0", "EXO_LOD1")}
    with bpy.data.libraries.load(str(args.accessories.resolve()), link=False) as (_, target):
        target.collections = ["JUG_HELMET", "JUG_HELMET_LOD1"]
    for collection in target.collections:
        bpy.context.scene.collection.children.link(collection)
    for collection in (*groups.values(), *target.collections):
        collection.hide_viewport = False
    presentation_pose(bpy.data.objects["EFT_Bind"], args.arms_lowered, args.arm_sweep)

    fitted_rac = donor_triangles(args.rac_reference, RAC_WIDTH, RAC_OFFSET, RAC_PITCH)
    results = {}
    has_intersection = False
    for (name, suit_collection), helmet_collection in zip(groups.items(), target.collections):
        moving = {
            "rigid_helmet": get_triangles(helmet_collection.objects,
                                          lambda obj, face: not soft_helmet_face(obj, face)),
            "soft_helmet_and_gaiter": get_triangles(helmet_collection.objects, soft_helmet_face),
            "fitted_rac": fitted_rac,
        }
        results[name] = {}
        for region, terms in TARGETS.items():
            objects = sorted((obj for obj in suit_collection.objects
                              if obj.type == "MESH" and any(tag in obj.name for tag in terms)),
                             key=lambda obj: obj.name)
            if not objects:
                raise ValueError(f"No objects for {name} {region}")
            fixed = evaluated_triangles(objects)
            metrics = {label: measure(geo, fixed) for label, geo in moving.items()}
            results[name][region] = {"objects": [obj.name for obj in objects], "metrics": metrics}
            has_intersection |= any(row["intersection_pairs_by_yaw_degrees"] for row in metrics.values())

    report = {
        "source_sha256": dict(source_digest(path) for path in (suit, args.accessories, args.rac_reference)),
        "method": "Evaluated suit with fixed arm rotations and rigid head yaw from -75 to +75 degrees in 5-degree steps "
                  "with triangle overlap and nearest vertex-to-surface distances.",
        "arms_lowered_degrees": args.arms_lowered,
        "arm_sweep_degrees": args.arm_sweep,
        "matched_lods": results,
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    for lod, regions in results.items():
        for name, region in regions.items():
            print(lod, name, region["metrics"])
    if has_intersection:
        raise ValueError("Head hardware intersects a radio or shoulder part")


if __name__ == "__main__":
    main()
