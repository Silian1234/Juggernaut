"""Build the Juggernaut v4 on the original EFT reference rig in Blender 5.3.

    blender -b exo_t3a.blend --python-exit-code 1 --python tools/model/suit_build.py
"""

import argparse
from pathlib import Path
import sys

import bpy

HERE = Path(__file__).resolve().parent
ART = HERE.parents[1] / "art"
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))


def prepare():
    rig = bpy.data.objects["EFT_Bind"]
    keep = {rig, bpy.data.objects["REF_top"], bpy.data.objects["REF_pants"]}
    for obj in list(bpy.data.objects):
        if obj not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)
    collections = []
    for name in ("EXO_LOD0", "EXO_LOD1"):
        collection = bpy.data.collections.get(name)
        if collection is None:
            collection = bpy.data.collections.new(name)
            bpy.context.scene.collection.children.link(collection)
        collection.hide_viewport = False
        collection.hide_render = False
        collections.append(collection)
    for obj in keep:
        obj.hide_viewport = False
        obj.hide_set(False)
        obj.hide_render = False
    rig.data.pose_position = "REST"
    for collection in list(bpy.data.collections):
        if not len(collection.all_objects) and collection not in collections:
            bpy.data.collections.remove(collection)
    bpy.data.orphans_purge(do_recursive=True)
    bpy.context.view_layer.update()
    return rig, collections


def main():
    from v2_plates import Armor
    import v3_fabric
    import v4_back
    import v4_legs
    import v4_stencils
    import v4_tactical
    import v4_upper

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ART / "suit/suit.blend")
    parser.add_argument("--draft", action="store_true", help="Keep unbaked working materials.")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    output = args.output.resolve()
    if output == Path(bpy.data.filepath).resolve() or not output.is_relative_to(ART):
        raise ValueError("Select a new scene path inside the project's art directory.")
    if args.draft and output == ART / "suit/suit.blend":
        raise ValueError("Give the unbaked draft a separate --output.")
    rig, collections = prepare()
    for lod, collection in enumerate(collections):
        v3_fabric.build(lod, collection, rig)
        bpy.context.view_layer.update()
        armor = Armor(lod, collection, rig, revision="V4")
        v4_upper.torso(armor)
        for side in ("L", "R"):
            v4_upper.arm(armor, side)
            v4_legs.leg(armor, side)
        v4_back.back(armor)
        v4_tactical.tactical(armor)
        v4_stencils.build(armor)
        bpy.context.view_layer.update()
    if not args.draft:
        import v2_surface
        import v4_surface
        v2_surface.finalize(collections, uv_only=True)
        v4_surface.finalize(collections, output.parent / "textures")
    for lod, collection in enumerate(collections):
        triangles = 0
        for obj in collection.all_objects:
            if obj.type == "MESH":
                obj.data.calc_loop_triangles()
                triangles += len(obj.data.loop_triangles)
        print(f"LOD{lod}: {triangles:,} triangles")
    collections[1].hide_render = True
    collections[1].hide_viewport = True
    rig.data.pose_position = "REST"
    bpy.context.preferences.filepaths.save_version = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True, relative_remap=False)


if __name__ == "__main__":
    main()
