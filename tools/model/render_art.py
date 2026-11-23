"""Render the final Blender models without modifying either source.

python -B tools/model/extract_pmc_reference.py --out art/build/v3-presentation/pmc-assets
blender -b art/suit/suit.blend --python tools/model/render_art.py
py -3.10 tools/model/render_banner.py
"""

import argparse
import os
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pmc_reference import load_pmc, snapshot_pmc
from suit_cell_fit import mount

ACCESSORIES = ("JUG_HELMET", "JUG_THERMAL", "JUG_CELL")
FLEX_POSES = ("crouch", "elbow110", "knee120")
FLEX_VIEWS = {"three_quarter": (.54, -1, .13), "side": (1, 0, .015)}
VIEWS = {
    "front": (0, -1, .015),
    "three_quarter": (.52, -1, .035),
    "back": (0, 1, .015),
    "side": (1, 0, .015),
}


def collection_meshes(collection):
    return [obj for obj in collection.all_objects if obj.type == "MESH"]


def load_accessories(path):
    with bpy.data.libraries.load(str(path), link=False) as (source, target):
        missing = set(ACCESSORIES) - set(source.collections)
        if missing:
            raise ValueError(f"Missing accessory collections in {path}: {sorted(missing)}")
        target.collections = list(ACCESSORIES)
    for collection in target.collections:
        bpy.context.scene.collection.children.link(collection)
    return [collection_meshes(collection) for collection in target.collections]


def mounted_cell(scene, cell, armature):
    """Place render instances on the same dock checked by suit_cell_fit.py."""
    dock = armature.pose.bones["Base HumanSpine3"]
    posed = armature.matrix_world @ dock.matrix @ dock.bone.matrix_local.inverted()
    posed @= armature.matrix_world.inverted()
    transform = posed @ Matrix.Translation(mount(Vector((0, 0, 0))))
    transform @= Matrix.Diagonal((-1, -1, 1, 1))
    instances = []
    for source in cell:
        instance = source.copy()
        scene.collection.objects.link(instance)
        instance.matrix_world = transform @ source.matrix_world
        instances.append(instance)
    return instances


def keep_meshes_visible(scene, meshes):
    chosen = set(meshes)
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.hide_render = obj not in chosen
    bpy.context.view_layer.update()


def bounds(camera, meshes):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rotation = camera.rotation_euler.to_matrix().transposed()
    lows = [float("inf")] * 3
    highs = [-float("inf")] * 3
    lowest_world = float("inf")
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            transform = evaluated.matrix_world
            for vertex in mesh.vertices:
                world = transform @ vertex.co
                lowest_world = min(lowest_world, world.z)
                for axis, value in enumerate(rotation @ world):
                    lows[axis] = min(lows[axis], value)
                    highs[axis] = max(highs[axis], value)
        finally:
            evaluated.to_mesh_clear()
    if lowest_world == float("inf"):
        raise RuntimeError("No renderable geometry was selected")
    center = camera.rotation_euler.to_matrix() @ Vector(
        tuple((lo + hi) / 2 for lo, hi in zip(lows, highs))
    )
    return center, highs[0] - lows[0], highs[1] - lows[1], lowest_world


def studio(scene):
    for obj in scene.objects:
        if obj.type in {"LIGHT", "CAMERA"}:
            obj.hide_render = True
    world = bpy.data.worlds.new("JG Studio Ambient")
    world.use_nodes = True
    world_nodes = world.node_tree.nodes
    world_nodes.clear()
    background = world_nodes.new("ShaderNodeBackground")
    background.inputs[0].default_value = (.45, .48, .50, 1)
    background.inputs[1].default_value = .55
    world_output = world_nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(background.outputs[0], world_output.inputs["Surface"])
    scene.world = world
    camera_data = bpy.data.cameras.new("JG Studio Camera")
    camera_data.type = "ORTHO"
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    lights = []
    for name, color, shape, specular in (
        ("Softbox", (1, .93, .84), "RECTANGLE", .62),
        ("Cool fill", (.80, .90, 1), "DISK", .26),
        ("Strip softbox", (.79, .90, 1), "RECTANGLE", .85),
        ("Bounce", (1, .82, .63), "DISK", .43),
    ):
        data = bpy.data.lights.new("JG Studio " + name, "AREA")
        data.color = color
        data.shape = shape
        data.specular_factor = specular
        light = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(light)
        lights.append(light)
    bpy.ops.mesh.primitive_plane_add(size=512)
    floor = bpy.context.object
    floor.name = "JG Studio Ground"
    material = bpy.data.materials.new(floor.name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(shader.outputs[0], output.inputs["Surface"])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 18
    coords = nodes.new("ShaderNodeTexCoord")
    material.node_tree.links.new(coords.outputs["Object"], noise.inputs["Vector"])
    tones = nodes.new("ShaderNodeValToRGB")
    tones.color_ramp.elements[0].color = (.027, .032, .036, 1)
    tones.color_ramp.elements[1].color = (.054, .063, .067, 1)
    material.node_tree.links.new(noise.outputs["Fac"], tones.inputs["Fac"])
    material.node_tree.links.new(tones.outputs["Color"], shader.inputs["Base Color"])
    shader.inputs["Roughness"].default_value = .8
    floor.data.materials.append(material)
    return camera, lights, floor


def position_lights(lights, center, direction, right, size):
    up = Vector((0, 0, 1))
    setup = (
        (direction * 1.32 - right * .82 + up * 1.38, 200, 1.45, .88),
        (direction * 1.03 + right * 1.04 + up * .36, 157, 1.24, 0),
        (-direction * .72 + right * .84 + up * 1.23, 215, .57, 1.6),
        (-direction * .20 - right * 1.16 + up * .44, 73, .86, 0),
    )
    for light, (position, watts, width, height) in zip(lights, setup):
        light.location = center + position * size
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
        light.data.energy = watts * size ** 2
        light.data.size = width * size
        if height:
            light.data.size_y = height * size


def render(scene, rig, meshes, direction, resolution, margin, path, transparent, draft,
           min_scale=0, detail=None):
    camera, lights, floor = rig
    keep_meshes_visible(scene, meshes)
    direction = Vector(direction).normalized()
    camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    center, width, height, ground = bounds(camera, meshes)
    size = max(width, height)
    aspect = resolution[0] / resolution[1]
    scale = max(width, height * aspect) / min(1, aspect)
    camera.data.ortho_scale = max(scale * margin, min_scale)
    camera_target = center.copy()
    if detail:
        height_above_floor, camera.data.ortho_scale = detail
        camera_target.z = ground + height_above_floor
    camera.location = camera_target + direction * (20 if not transparent else 6)
    camera.data.clip_start = .01
    camera.data.clip_end = 600
    floor.location.z = ground - .0008
    floor.hide_render = transparent
    position_lights(lights, center, direction, camera.rotation_euler.to_matrix().col[0], size)
    scene.render.film_transparent = transparent
    scene.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 50 if draft else 100
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(path.resolve())
    bpy.ops.render.render(write_still=True)
    print(f"RENDER_WRITTEN {path}", flush=True)


def presentation_pose(armature, degrees, arm_sweep=0):
    """Use the validated EXO down-arm axis, retaining the EFT bind matrices."""
    from math import radians
    from mathutils import Quaternion

    armature.data.pose_position = "POSE"
    for bone in armature.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    for side in ("L", "R"):
        prefix = "Base Human" + side
        bone = armature.pose.bones[prefix + "Upperarm"]
        elbow = armature.pose.bones[prefix + "Forearm1"]
        bind_arm = armature.matrix_world.to_3x3() @ (elbow.bone.head_local - bone.bone.head_local)
        axis = bind_arm.cross(Vector((0, 0, -1))).normalized()
        relative = bone.bone.matrix_local.to_quaternion()
        if bone.parent:
            relative = bone.parent.bone.matrix_local.to_quaternion().inverted() @ relative
            relative = bone.parent.matrix.to_quaternion() @ relative
        world = armature.matrix_world.to_quaternion() @ relative
        bone.rotation_mode = "QUATERNION"
        lowered = Quaternion(world.inverted() @ axis, radians(degrees))
        rearward = Quaternion(world.inverted() @ Vector((1, 0, 0)), radians(arm_sweep))
        bone.rotation_quaternion = rearward @ lowered
    bpy.context.view_layer.update()


def stage_comparison(camera, worn, pmc, direction):
    """Space two full-size models on one studio floor, preserving their shared pose."""
    camera.rotation_euler = (-Vector(direction)).to_track_quat("-Z", "Y").to_euler()
    right = camera.rotation_euler.to_matrix().col[0]
    _, worn_width, _, worn_ground = bounds(camera, worn)
    for obj in pmc:
        obj.location = (0, 0, 0)
    bpy.context.view_layer.update()
    _, pmc_width, _, pmc_ground = bounds(camera, pmc)
    offset = right * ((worn_width + pmc_width) / 2 + .34)
    offset.z = worn_ground - pmc_ground
    for obj in pmc:
        obj.location = offset
    bpy.context.view_layer.update()
    return worn + pmc


def render_flex(scene, rig, armor, clothing, cell, armature, args):
    source = os.environ.get("JUGGERNAUT_EXO_SOURCE", "C:/SPT/_fullbody_armor/exoskeleton/gpt")
    sys.path.insert(0, source)
    from review import set_pose

    for pose in FLEX_POSES:
        set_pose(pose)
        meshes = armor + clothing + mounted_cell(scene, cell, armature)
        for name, direction in FLEX_VIEWS.items():
            path = args.destination / "flex" / f"{pose}_{name}.png"
            render(scene, rig, meshes, direction, (520, 560), 1.14, path, False, args.draft,
                   min_scale=1.92)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accessories", type=Path, default=ROOT / "art/accessories/accessories.blend")
    parser.add_argument("--destination", type=Path, default=ROOT / "art")
    parser.add_argument("--pmc-assets", type=Path, default=ROOT / "art/build/v3-presentation/pmc-assets",
                        help="files generated by extract_pmc_reference.py")
    parser.add_argument("--scratch", type=Path, default=Path(os.environ["TEMP"]) / "juggernaut-banner")
    parser.add_argument("--suit-collection", default="EXO_LOD0")
    parser.add_argument("--group", choices=("all", "icons", "previews", "banner", "flex", "details"),
                        default="all")
    parser.add_argument("--view", choices=tuple(VIEWS), action="append",
                        help="render only selected preview views (repeatable)")
    parser.add_argument("--clothing-only", action="store_true",
                        help="render the complete vanilla PMC alone to the clothing folder")
    parser.add_argument("--pose", type=float, default=36, help="upper-arm lowering in degrees")
    parser.add_argument("--arm-sweep", type=float, default=23,
                        help="move the lowered arms rearward in degrees")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--samples", type=int, default=24)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if (args.view or args.clothing_only) and args.group != "previews":
        parser.error("--view and --clothing-only require --group previews")

    scene = bpy.context.scene
    armor_collection = bpy.data.collections.get(args.suit_collection)
    if armor_collection is None:
        parser.error(f"missing suit collection {args.suit_collection!r} in {bpy.data.filepath}")
    armor = collection_meshes(armor_collection)
    helmet, thermal, cell = load_accessories(args.accessories)
    for collection in bpy.data.collections:
        collection.hide_render = False
        collection.hide_viewport = False
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8 if args.draft else args.samples
    scene.cycles.use_denoising = True
    scene.cycles.adaptive_threshold = .05
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -1.25
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    rig = studio(scene)
    armature = bpy.data.objects["EFT_Bind"]
    pmc = []
    if args.group != "icons":
        clothing, head = load_pmc(scene, args.pmc_assets.resolve(), armature)
        pmc = [*clothing, head]
    if args.group == "flex":
        render_flex(scene, rig, armor, clothing, cell, armature, args)
        return
    presentation_pose(armature, args.pose, args.arm_sweep)
    worn = armor + pmc + helmet + mounted_cell(scene, cell, armature)
    fitted = worn + thermal

    def output(meshes, direction, resolution, margin, path, transparent, min_scale=0):
        render(scene, rig, meshes, direction, resolution, margin, path, transparent, args.draft,
               min_scale)

    if args.group in {"previews", "all"}:
        comparison = snapshot_pmc(scene, pmc) if not args.clothing_only else []
        subfolder = "clothing" if args.clothing_only else "previews"
        for name in args.view or VIEWS:
            direction = VIEWS[name]
            variant = fitted if name == "side" else worn
            meshes = pmc if args.clothing_only else stage_comparison(
                rig[0], variant, comparison, direction)
            output(meshes, direction, (1500, 1400), 1.07,
                   args.destination / subfolder / f"{name}.png", False, min_scale=2.24)
    if args.group in {"icons", "all"}:
        for name, meshes, direction in (
            ("suit", armor, (.34, -1, .13)),
            ("helmet", helmet, (.52, -1, .34)),
            ("thermal_module", thermal, (.48, -1, .42)),
            ("power_cell", cell, (.48, -1, .28)),
        ):
            output(meshes, direction, (256, 256), 1.16,
                   args.destination / "icons" / f"{name}.png", True)
    if args.group in {"banner", "all"}:
        for name, meshes, direction, resolution in (
            ("hero", fitted, (.57, -1, .045), (1280, 1632)),
            ("hero_back", fitted, (.45, 1, .035), (820, 1080)),
            ("power_cell", cell, (.43, -1, .31), (385, 385)),
            ("thermal_module", thermal, (.56, -1, .37), (385, 385)),
        ):
            output(meshes, direction, resolution, 1.05, args.scratch / f"{name}.png", True)
    if args.group in {"details", "all"}:
        for name, meshes, direction, frame in (
            ("visor", worn, (.38, -1, .12), (1.54, .88)),
            ("cassette", fitted, (.18, 1, .08), (1.37, .83)),
            ("ankle", worn, (1, -.14, .05), (.405, .92)),
            ("pouches", worn, (.16, -1, .035), (1.40, .46)),
        ):
            path = args.destination / "detail-renders" / f"{name}.png"
            render(scene, rig, meshes, direction, (780, 780), 1, path, False, args.draft, detail=frame)


if __name__ == "__main__":
    main()
