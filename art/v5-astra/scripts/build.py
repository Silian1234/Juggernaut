"""Rebuild the competition scene from its local EFT bind scene and art sources."""
import argparse
from collections import defaultdict
import importlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from finish import flat_material


def collection(name):
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def group_equipment(target, lod):
    """Let the reviewer isolate the drive, armor and removable module in the Outliner."""
    categories = {
        "upper_frame": "Power frame", "arm_frame": "Power frame", "leg_frame": "Power frame",
        "arm_plates": "Limb armor", "leg_plates": "Limb armor", "waist_armor": "Limb armor",
        "carrier": "Carrier and belt", "pack": "Backpack",
        "additional_plates": "Articulated armor",
        "helmet": "Helmet", "thermal": "Thermal module", "cloth": "Combat clothing",
    }
    groups = {}
    for obj in list(target.objects):
        label = categories.get(obj.get("part"))
        if obj.name in {"mod_nvg", "mod_equipment_001"}:
            label = "Helmet"
        if label is None:
            continue
        if label not in groups:
            groups[label] = bpy.data.collections.new(f"{label} · LOD{lod}")
            target.children.link(groups[label])
        groups[label].objects.link(obj)
        target.objects.unlink(obj)


def witness_uniform(obj):
    obj.data.materials.clear()
    obj.data.materials.append(flat_material("Reference | field uniform", (.090, .084, .061), .86))


def witness_head(coll, rig):
    source = ROOT / "source/reference"
    donor = json.loads((source / "usec_head.json").read_text())
    mesh = bpy.data.meshes.new("Eric original head")
    mesh.from_pydata(donor["positions"], [], donor["triangles"])
    mesh.update()
    for face in mesh.polygons:
        face.use_smooth = True
    mesh.normals_split_custom_set_from_vertices(donor["normals"])
    mesh.materials.append(flat_material("Reference | skin", (.33, .178, .114), .75))
    obj = bpy.data.objects.new("REF_head", mesh)
    coll.objects.link(obj)
    paths = [p.split("/")[-1] for p in donor["bonePaths"]]
    for i, (bones, weights) in enumerate(zip(donor["boneIndices"], donor["boneWeights"])):
        row = defaultdict(float)
        for bone, weight in zip(bones, weights):
            if weight:
                name = paths[bone]
                row["Base HumanNeck" if name == "Base HumanHead" else name] += weight
        for name, weight in row.items():
            group = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
            group.add([i], weight, "REPLACE")
    obj.parent = rig
    obj.modifiers.new("Native reference skin", "ARMATURE").object = rig
    return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "juggernaut_v5.blend")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.is_relative_to(ROOT / "source"):
        raise ValueError("Save within the entry, outside its source directory")
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / "source/base_scene.blend"))
    rig = bpy.data.objects["EFT_Bind"]
    refs = [bpy.data.objects[name] for name in ("REF_top", "REF_pants")]
    keep = {rig, *refs}
    for obj in list(bpy.data.objects):
        if obj not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    for view in scene.view_layers:
        view.material_override = None
    base = collection("EFT reference character")
    for obj in keep:
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        base.objects.link(obj)
        obj.hide_viewport = obj.hide_render = False
        obj.hide_set(False)
    for coll in list(bpy.data.collections):
        if coll != base and not coll.all_objects:
            bpy.data.collections.remove(coll)
    bpy.data.orphans_purge(do_recursive=True)
    rig.data.pose_position = "REST"
    bpy.context.view_layer.update()
    for obj in refs:
        witness_uniform(obj)
    witness_head(base, rig)
    groups = []
    totals = []
    for lod in (0, 1):
        target = collection(f"EXO_LOD{lod}")
        groups.append(target)
        for module in ("cloth", "carrier", "legs", "arms", "pack", "headgear",
                       "v5d_thigh", "v5d_arms"):
            previous = set(target.objects)
            importlib.import_module(module).build(lod, target, rig)
            for obj in set(target.objects)-previous:
                if obj.type == "MESH":
                    if not obj.get("part"):
                        obj["part"] = module
        budget = importlib.import_module("v5d_budget")
        budget.optimize(lod, target, rig)
        importlib.import_module("v5d_pelvis").build(lod, target, rig)
        importlib.import_module("v5d_tassets").build(lod, target, rig)
        importlib.import_module("v5d_torso").build(lod, target, rig)
        importlib.import_module("v5d_articulation").integrate(lod, target, rig)
        importlib.import_module("v5d_armfit").fit(lod, target, rig)
        calf = importlib.import_module("v5d_calf_motion")
        calf.rebuild(lod, target, rig)
        budget.optimize_existing_armor(lod, target, rig, target_triangles=80_000 if lod == 0 else 44_000)
        importlib.import_module("v5d_backing").fit(lod, target, rig)
        calf.install(lod, target, rig)
        importlib.import_module("v5d_articulation").fit_outer_thighs(lod, target, rig)
        importlib.import_module("v5d_rims").fit(lod, target)
        importlib.import_module("v5d_armfit").seat_fasteners(lod, target, rig)
        bpy.context.view_layer.update()
        counts = defaultdict(int)
        for obj in target.all_objects:
            if obj.type == "MESH":
                obj.data.calc_loop_triangles()
                counts[obj["part"]] += len(obj.data.loop_triangles)
        totals.append(sum(counts.values()))
        print(f"LOD{lod} triangles by part: {dict(sorted(counts.items()))}", flush=True)
        group_equipment(target, lod)
    print(f"Worn LOD0 / LOD1 including thermal: {totals}", flush=True)
    if totals[0] > 80_000:
        raise ValueError("Worn LOD0 exceeds 80,000 triangles")
    groups[1].hide_render = groups[1].hide_viewport = True
    rig.hide_render = True
    rig.show_in_front = False
    bpy.ops.object.select_all(action="DESELECT")
    rig.hide_set(True)
    for window in bpy.data.screens:
        for area in window.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.overlay.show_overlays = False
                space.shading.color_type = "MATERIAL"
                space.shading.type = "MATERIAL"
                space.region_3d.view_rotation = Vector((.28, 1, -.065)).to_track_quat("-Z", "Y")
                space.region_3d.view_distance = 3.3
                space.region_3d.view_location = (0,0,.94)
                space.region_3d.view_perspective = "ORTHO"
    bpy.data.orphans_purge(do_recursive=True)
    for mat in bpy.data.materials:
        if not mat.users or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type not in {"BSDF_PRINCIPLED", "OUTPUT_MATERIAL"}:
                raise ValueError(f"Non-constant material in geometry review: {mat.name} / {node.name}")
    if any(image.source == "FILE" for image in bpy.data.images):
        raise ValueError("Unexpected file texture left in the geometry review scene")
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True, relative_remap=False)


if __name__ == "__main__":
    main()
