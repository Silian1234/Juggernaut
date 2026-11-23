"""Sample opaque exterior coverage of the actual vanilla USEC Eric head."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from accessory_qa import HEAD_PIVOT
from v2_fit_qa import VIEWS, armor_check, combine, coverage, digest, object_set, review
from worn_proportions import HEAD_BASE_Z, span


def load_helmet_parts(path):
    with bpy.data.libraries.load(str(path.resolve()), link=False) as (_, target):
        target.collections = ["JUG_HELMET", "JUG_HELMET_LOD1"]
    for lod, collection in enumerate(target.collections):
        bpy.context.scene.collection.children.link(collection)
        armor_check.make_visible(collection)
        yield lod, [obj for obj in collection.all_objects if obj.type == "MESH"]


def deform_bone(armature, name):
    bone = armature.pose.bones[name]
    return (armature.matrix_world @ bone.matrix @ bone.bone.matrix_local.inverted()
            @ armature.matrix_world.inverted())


def head_motion(armature, local_yaw):
    rotation = Matrix.Rotation(math.radians(local_yaw), 4, "Z")
    return (deform_bone(armature, "Base HumanNeck") @ Matrix.Translation(HEAD_PIVOT)
            @ rotation @ Matrix.Translation(-HEAD_PIVOT))


def deform_head(head, indices, weights, transforms):
    return [
        sum(((transforms[index] @ vertex) * weight
             for index, weight in zip(vertex_indices, vertex_weights) if weight > 0), Vector())
        for vertex, vertex_indices, vertex_weights in zip(head, indices, weights)
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accessories", type=Path, required=True)
    parser.add_argument("--head-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--head-only", action="store_true",
                        help="Apply all yaw at the Head pivot with Neck held at rest.")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    suit = {lod: object_set(lod) for lod in (0, 1)}
    helmets = dict(load_helmet_parts(args.accessories))
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    helmet = {lod: combine(review._mesh(obj, deps) for obj in objects)
              for lod, objects in helmets.items()}
    donor = json.loads(args.head_json.read_text(encoding="utf-8"))
    head = [Vector(point) for point in donor["positions"]]
    bones = [path.rsplit("/", 1)[-1] for path in donor["bonePaths"]]
    indices = donor["boneIndices"]
    weights = donor["boneWeights"]
    if len(head) != len(indices) or len(head) != len(weights):
        raise ValueError("Native head skin rows do not match the vertex count")
    if any(len(row) != 4 for row in indices + weights):
        raise ValueError("Expected four native skin weights and indices per head vertex")
    if any(not math.isclose(sum(row), 1, abs_tol=1e-5) for row in weights):
        raise ValueError("A native head vertex has unnormalized skin weights")
    if bones.count("Base HumanHead") != 1:
        raise ValueError(f"Could not identify donor Head bone in {bones}")
    triangles = donor["triangles"]
    labels = [
        "head_and_upper_neck" if any(head[i].z >= HEAD_BASE_Z for i in face) else "lower_neck"
        for face in triangles
    ]
    no_mask = [[False] * 3 for _ in triangles]
    covered = {
        "accessories_sha256": digest(args.accessories),
        "suit_blend_sha256": digest(Path(bpy.data.filepath)),
        "head_json_sha256": digest(args.head_json),
        "donor": "assets/content/characters/character/prefabs/usec_head_eric.bundle / USEC_head_Eric_lod0_base",
        "donor_transform": "JSON coordinates are world metres in Blender, converted by negating source Unity X.",
        "donor_world_bounds": span(head),
        "region_cutoff_world_z_m": HEAD_BASE_Z,
        "regions": "In rest, a triangle belongs to head_and_upper_neck if at least one vertex meets "
                   "the z cutoff. All other triangles belong to lower_neck. No triangles or "
                   "first-hit points are intentionally discarded. Original garments are outside the "
                   "occluder set, which contains only suit and helmet for the corresponding LOD.",
        "method": "2 mm orthographic first-hit projections from 10 exterior directions using opaque "
                  "two-sided triangles. All ray origins are beyond the full scene geometry. "
                  "Between directions, projected samples may cover the same surface.",
        "pitch_mm": 2,
        "head_pivot_world_m": list(HEAD_PIVOT),
        "native_bone_paths": donor["bonePaths"],
        "yaw": "Synthetic test, not animation capture. Entire yaw is applied to Head with Neck held "
               "at rest when head_only is true. Otherwise Neck and its child Head each receive "
               "half the yaw. The donor uses original four-influence skinning, the rigid helmet "
               "follows the composed Head transform, and the suit retains its own weights.",
        "head_only": args.head_only,
        "angles_degrees": {},
    }
    try:
        for yaw in (-75, -45, 0, 45, 75):
            review.set_pose("rest")
            neck_yaw = 0 if args.head_only else yaw / 2
            review._rotate("Base HumanNeck", Vector((0, 0, 1)), neck_yaw)
            deps = bpy.context.evaluated_depsgraph_get()
            head_transform = head_motion(review.ARM, yaw - neck_yaw)
            transforms = [
                head_transform if bone == "Base HumanHead" else deform_bone(review.ARM, bone)
                for bone in bones
            ]
            head_turned = deform_head(head, indices, weights, transforms)
            posed = [combine([*(review._mesh(obj, deps) for obj in suit[lod]),
                              ([head_transform @ point for point in helmet[lod][0]], helmet[lod][1])])
                     for lod in (0, 1)]
            points = head_turned + posed[0][0] + posed[1][0]
            head_tree = armor_check.mesh_tree(head_turned, triangles)
            suit_trees = [armor_check.mesh_tree(*mesh) for mesh in posed]
            views = {}
            for name, direction in VIEWS.items():
                rows, _ = coverage(head_tree, suit_trees, points, labels, no_mask,
                                   direction, .002, crop=head_turned)
                views[name] = rows
            totals = [sum(view[lod]["visible_pixels"] for view in views.values()) for lod in (0, 1)]
            covered["angles_degrees"][yaw] = {"visible_rays_by_lod": totals, "views": views}
            print(f"yaw {yaw:+d}: LOD0/LOD1 visible rays {totals}", flush=True)
    finally:
        review.restore_pose()
    args.out.write_text(json.dumps(covered, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
