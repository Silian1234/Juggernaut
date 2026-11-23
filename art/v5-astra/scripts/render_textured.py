"""Render baked V5d maps under HDRI lighting with Cycles OptiX."""

import argparse
from hashlib import file_digest
from math import radians
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector


sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lower_frame import KNEE_PIN
from render import (
    ENTRY, WORK, Studio, collection_meshes, configure_work_paths,
    render_arms, render_detail, render_poses, render_sheet, vertices, view_bounds,
)

HDRI = ENTRY / "hdri" / "studio.exr"


def sha256(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def log_material_inputs(objects, draft, texture_stage):
    source = Path(bpy.data.filepath).resolve()
    preview = ENTRY / "work" / "bake" / "preview"
    if source == ENTRY / "juggernaut_v5_textured.blend":
        textures = ENTRY / "textures" / "v5d"
    elif draft and source == preview / "juggernaut_v5_preview.blend":
        textures = preview
    else:
        raise RuntimeError(f"Expected juggernaut_v5_textured.blend, found {source}")
    images = {}
    for obj in objects:
        for slot in obj.material_slots:
            material = slot.material
            if not material or not material.node_tree:
                continue
            for node in material.node_tree.nodes:
                if node.type != "TEX_IMAGE" or not node.image:
                    continue
                image = node.image
                path = Path(bpy.path.abspath(image.filepath)).resolve()
                if not path.is_relative_to(textures) or image.packed_file or not path.is_file():
                    raise RuntimeError(f"Expected an external baked atlas for {image.name}: {path}")
                images[image] = path
    paths = set(images.values())
    expected = {
        textures / f"{atlas}_{channel}.png"
        for atlas in ("armor", "textile", "frame", "helmet")
        for channel in ("albedo", "normal", "specgloss")
    }
    if paths != expected:
        raise RuntimeError(f"Unexpected material atlas set: missing {expected - paths}, extra {paths - expected}")
    if texture_stage:
        paths = {texture_stage / path.name for path in paths}
        for image, original in images.items():
            image.filepath = str(texture_stage / original.name)
            image.reload()
    hashes = {path: sha256(path) for path in [source, *sorted(paths)]}
    for path, checksum in hashes.items():
        print(f"RENDER_INPUT_SHA256 {checksum} {path.relative_to(ENTRY)}", flush=True)
    return hashes


def set_backdrop(studio, value):
    world = studio.scene.world.node_tree
    camera_mix = next(node for node in world.nodes if node.type == "MIX_SHADER")
    background = camera_mix.inputs[2].links[0].from_node
    background.inputs[0].default_value = (value, value, value, 1)

    # Alter only camera rays, preserving indirect floor bounce on the model.
    tree = studio.floor.data.materials[0].node_tree
    nodes = tree.nodes
    regular = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    output = next(node for node in nodes if node.type == "OUTPUT_MATERIAL")
    emission = nodes.get("Camera Floor Color")
    if emission is None:
        emission = nodes.new("ShaderNodeEmission")
        emission.name = "Camera Floor Color"
        matte = nodes.new("ShaderNodeBsdfDiffuse")
        matte.inputs["Color"].default_value = (.007, .007, .007, 1)
        matte.inputs["Roughness"].default_value = 1
        add = nodes.new("ShaderNodeAddShader")
        tree.links.new(matte.outputs[0], add.inputs[0])
        tree.links.new(emission.outputs[0], add.inputs[1])
        light_path = nodes.new("ShaderNodeLightPath")
        mix = nodes.new("ShaderNodeMixShader")
        tree.links.new(light_path.outputs["Is Camera Ray"], mix.inputs[0])
        tree.links.new(regular.outputs["BSDF"], mix.inputs[1])
        tree.links.new(add.outputs[0], mix.inputs[2])
        tree.links.new(mix.outputs["Shader"], output.inputs["Surface"])
    emission.inputs["Color"].default_value = (value, value, value, 1)


def configure_hdri(studio, rotation, strength):
    studio.scene.world.name = "Studio | CC0 HDRI"
    tree = studio.scene.world.node_tree
    ambient = next(node for node in tree.nodes if node.type == "MIX_SHADER").inputs[1].links[0].from_node
    ambient.inputs["Strength"].default_value = strength
    environment = tree.nodes.new("ShaderNodeTexEnvironment")
    environment.image = bpy.data.images.load(str(HDRI), check_existing=True)
    environment.projection = "EQUIRECTANGULAR"
    direction = tree.nodes.new("ShaderNodeTexCoord")
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.vector_type = "VECTOR"
    mapping.inputs["Rotation"].default_value.z = radians(rotation)
    tree.links.new(direction.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
    tree.links.new(environment.outputs["Color"], ambient.inputs["Color"])
    width, height = environment.image.size[:]
    if width != 2 * height or not environment.image.is_float:
        raise RuntimeError(f"Expected a floating-point equirectangular HDRI: {HDRI}")
    channels = environment.image.channels
    pixels = np.empty(width * height * channels, dtype=np.float32)
    environment.image.pixels.foreach_get(pixels)
    peak = float(pixels.reshape(-1, channels)[:, :3].max())
    if not np.isfinite(peak) or peak <= 1:
        raise RuntimeError(f"Expected HDRI radiance above 1.0: {HDRI}")
    print(f"RENDER_HDRI {width}x{height} floating-point | peak radiance {peak:g} "
          f"| yaw {rotation} degrees | strength {strength}", flush=True)

    key, fill, rim, bounce = (light for light, _ in studio.lights)
    for light in (key, fill, rim, bounce):
        light.data.color = (1, 1, 1)
    key.data.energy = 53
    key.data.size = .65
    key.data.size_y = 1.35
    fill.data.energy = 0
    rim.data.energy = 61
    rim.data.size = .42
    rim.data.size_y = 1.7
    bounce.data.energy = 0
    studio.lights = [(key, (-1.22, .81, .84)), (rim, (1.36, -.79, .80))]


def render_closeup(studio, name, data, destination, draft):
    knee = Vector(KNEE_PIN)
    center, direction, span = {
        "plate": (knee + Vector((-.067, -.091, -.058)), (.63, -1, .23), .22),
        "frame": (knee + Vector((.007, .007, .027)), (1, -.20, .18), .29),
        "fabric": (Vector((.054, -.145, 1.344)), (.39, -1, .15), .19),
    }[name]
    orientation, _, _ = view_bounds(np.array([center]), direction)
    anchor = orientation.to_matrix().transposed() @ center
    resolution = (800, 625) if draft else (1600, 1250)
    camera = studio.camera.data
    camera.type = "PERSP"
    camera.sensor_fit = "HORIZONTAL"
    camera.sensor_width = 36
    camera.lens = 92
    distance = span * (resolution[0] / resolution[1]) * camera.lens / camera.sensor_width
    lights = studio.lights
    key = lights[0][0]
    watts = key.data.energy
    if name == "fabric":
        # Grazing illumination across the zipper, pouch flaps and MOLLE bands.
        key.data.energy = 82
        studio.lights = [(key, (-.95, .52, .53)), lights[1]]
    try:
        studio.render(destination / f"closeup_{name}.png", resolution, orientation, anchor,
                      span, float(data[:, 2].min()), center, distance=distance)
    finally:
        camera.type = "ORTHO"
        key.data.energy = watts
        studio.lights = lights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--group", choices=("all", "closeups", "plate", "frame", "fabric", "lighting"),
                        default="all")
    parser.add_argument("--stage", default="v5b-stage", help="Stage directory name under work/render")
    parser.add_argument("--hdri-yaw", type=float, default=128)
    parser.add_argument("--hdri-strength", type=float, default=.38)
    parser.add_argument("--texture-stage", type=Path, help="Draft-only alternate atlas directory in work")
    parser.add_argument("--flat-normals", action="store_true", help="Draft-only comparison without normal maps")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if not args.stage or Path(args.stage).name != args.stage or args.stage in {".", ".."}:
        parser.error("--stage must be a directory name")
    texture_stage = args.texture_stage.resolve() if args.texture_stage else None
    if texture_stage and (not args.draft or not texture_stage.is_relative_to(ENTRY / "work")):
        parser.error("--texture-stage requires --draft and a directory under work")
    if args.flat_normals and not args.draft:
        parser.error("--flat-normals requires --draft")

    configure_work_paths()
    stage = WORK / args.stage
    panels = stage / "panels"
    panels.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    rig = bpy.data.objects["EFT_Bind"]
    rig.data.pose_position = "REST"
    selected = collection_meshes(scene)
    hashes = log_material_inputs(selected, args.draft, texture_stage)
    if args.flat_normals:
        materials = {slot.material for obj in selected for slot in obj.material_slots if slot.material}
        for material in materials:
            for node in material.node_tree.nodes if material.node_tree else ():
                if node.type == "NORMAL_MAP":
                    node.inputs["Strength"].default_value = 0
        print("RENDER_DIAGNOSTIC normal map strength set to zero in memory", flush=True)
    for path in (HDRI, Path(__file__).resolve(), ENTRY / "scripts" / "render.py"):
        hashes[path] = sha256(path)
        print(f"RENDER_INPUT_SHA256 {hashes[path]} {path.relative_to(ENTRY)}", flush=True)
    data = vertices(selected)
    samples = 12 if args.draft else 64
    studio = Studio(scene, samples, "OPTIX")
    if not np.isfinite(args.hdri_yaw) or not np.isfinite(args.hdri_strength) or args.hdri_strength <= 0:
        parser.error("HDRI yaw must be finite and strength must be positive")
    configure_hdri(studio, args.hdri_yaw, args.hdri_strength)
    set_backdrop(studio, .017)
    scene.cycles.use_adaptive_sampling = False
    print(f"RENDER_SETTINGS Blender {bpy.app.version_string} | Cycles | {samples} fixed samples "
          "| OptiX GPU denoising | AgX", flush=True)

    names = []
    for name in ("plate", "frame", "fabric"):
        if args.group in ("all", "closeups", name, "lighting"):
            render_closeup(studio, name, data, stage, args.draft)
            names.append(f"closeup_{name}")
    if args.group in ("all", "lighting"):
        canvas = (1300, 327) if args.draft else (2600, 654)
        render_sheet(studio, data, stage / "sheet_dark.png", panels, args.draft, canvas_size=canvas)
        names.append("sheet_dark")
    if args.group == "all":
        set_backdrop(studio, .055)
        render_sheet(studio, data, stage / "sheet.png", panels, args.draft, canvas_size=canvas)
        set_backdrop(studio, .017)
        for name in ("helmet", "legs_front", "legs"):
            render_detail(studio, selected, data, name, stage, args.draft)
        render_arms(studio, rig, selected, stage, panels, args.draft)
        render_poses(studio, rig, selected, stage, panels, args.draft)
        names.extend(("sheet", "helmet", "legs_front", "legs", "arms", "pose"))
    for path, checksum in hashes.items():
        if sha256(path) != checksum:
            raise RuntimeError(f"A render input changed during this session: {path}")
    for name in names:
        path = stage / f"{name}.png"
        print(f"RENDER_OUTPUT_SHA256 {sha256(path)} {path.relative_to(ENTRY)}", flush=True)


if __name__ == "__main__":
    main()
