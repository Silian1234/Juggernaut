"""Render V5 with Cycles. Run through Blender with juggernaut_v5.blend open."""

import argparse
from hashlib import file_digest
from math import radians
import os
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector


ENTRY = Path(__file__).resolve().parents[1]
WORK = ENTRY / "work" / "render"
VIEWS = (
    ("front", (0, -1, .065)),
    ("front-quarter", (-.68, -1, .079)),
    ("side", (-1, 0, .065)),
    ("back", (0, 1, .065)),
    ("back-quarter", (-.68, 1, .079)),
)
FRAME_PARTS = {"upper_frame", "arm_frame", "leg_frame"}
FRAME_VIEWS = tuple((name, (direction[0], direction[1], .025))
                    for name, direction in VIEWS if name in {"front", "side", "back"})


def collection_meshes(scene, show_reference=False):
    lod = bpy.data.collections.get("EXO_LOD0")
    selected = {
        obj for obj in lod.all_objects
        if obj.type == "MESH" and not obj.get("optional") and obj.get("part") != "thermal"
    } if lod else set()
    reference_layers = {
        "REF_top": "Undersuit | Combat shirt",
        "REF_pants": "Undersuit | Combat trousers",
        "REF_head": "Undersuit | Head",
    }
    # Reference garments occupy the same space as the production undersuit.
    # Show each reference only when there is no corresponding LOD0 mesh.
    for name, clothing in reference_layers.items():
        reference = bpy.data.objects.get(name)
        if reference and (show_reference or not any(obj.name.startswith(clothing) for obj in selected)):
            selected.add(reference)
    if not selected:
        raise ValueError("No LOD0 or reference clothing meshes in this file")
    for collection in bpy.data.collections:
        if any(obj in selected for obj in collection.all_objects):
            collection.hide_viewport = False
            collection.hide_render = False
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.hide_render = obj not in selected
            if obj in selected:
                obj.hide_viewport = False
                obj.hide_set(False)
        elif obj.type in {"LIGHT", "CAMERA"}:
            obj.hide_render = True
    bpy.context.view_layer.update()
    return selected


def vertices(objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    chunks = []
    for obj in sorted(objects, key=lambda item: item.name):
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        points = np.empty((len(mesh.vertices), 3), dtype=np.float32)
        try:
            mesh.vertices.foreach_get("co", points.ravel())
            transform = np.asarray(evaluated.matrix_world)
            chunks.append(points @ transform[:3, :3].T + transform[:3, 3])
        finally:
            evaluated.to_mesh_clear()
    return np.concatenate(chunks)


def view_bounds(points, direction):
    direction = Vector(direction).normalized()
    orientation = (-direction).to_track_quat("-Z", "Y")
    rotation = orientation.to_matrix()
    plane = points @ np.asarray(rotation)
    return orientation, plane.min(axis=0), plane.max(axis=0)


def add_floor():
    bpy.ops.mesh.primitive_plane_add(size=400)
    floor = bpy.context.object
    floor.name = "Studio | Gray floor"
    material = bpy.data.materials.new(floor.name)
    if material.node_tree is None:
        material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    shader.inputs["Base Color"].default_value = (.006, .006, .006, 1)
    shader.inputs["Roughness"].default_value = 1
    shader.inputs["Specular IOR Level"].default_value = .035
    shader.inputs["Emission Color"].default_value = (.055, .055, .055, 1)
    shader.inputs["Emission Strength"].default_value = 1
    floor.data.materials.append(material)
    return floor


class Studio:
    def __init__(self, scene, samples, device):
        self.scene = scene
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.adaptive_threshold = .024
        scene.cycles.max_bounces = 7
        scene.cycles.diffuse_bounces = 3
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
        scene.view_settings.exposure = -.20
        scene.render.resolution_percentage = 100
        scene.render.pixel_aspect_x = 1
        scene.render.pixel_aspect_y = 1
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.color_depth = "8"
        scene.render.use_compositing = False
        scene.render.use_sequencer = False
        scene.render.use_persistent_data = True
        self.enable_gpu(device)

        scene.world = bpy.data.worlds.new("Studio | Gray")
        if scene.world.node_tree is None:
            scene.world.use_nodes = True
        nodes = scene.world.node_tree.nodes
        nodes.clear()
        link = scene.world.node_tree.links.new
        output = nodes.new("ShaderNodeOutputWorld")
        ambient = nodes.new("ShaderNodeBackground")
        ambient.inputs[0].default_value = (.21, .21, .21, 1)
        ambient.inputs[1].default_value = .52
        background = nodes.new("ShaderNodeBackground")
        background.inputs[0].default_value = (.056, .056, .056, 1)
        light_path = nodes.new("ShaderNodeLightPath")
        mix = nodes.new("ShaderNodeMixShader")
        link(light_path.outputs["Is Camera Ray"], mix.inputs[0])
        link(ambient.outputs[0], mix.inputs[1])
        link(background.outputs[0], mix.inputs[2])
        link(mix.outputs[0], output.inputs["Surface"])

        camera_data = bpy.data.cameras.new("Studio | Orthographic")
        camera_data.type = "ORTHO"
        camera_data.clip_end = 200
        self.camera = bpy.data.objects.new(camera_data.name, camera_data)
        scene.collection.objects.link(self.camera)
        scene.camera = self.camera
        self.floor = add_floor()
        settings = (
            ("Key", (1, .981, .954), 275, 1.25, 1.65, (-1.76, 1.54, 1.68)),
            ("Fill", (.97, .98, 1), 142, 1.52, 1.72, (1.4, 1.40, .45)),
            ("Rim", (.94, .96, 1), 190, .72, 1.76, (1.57, -1.56, 1.42)),
            ("Back bounce", (1, .97, .94), 65, 1.23, 1.75, (-1.57, -.95, .44)),
        )
        self.lights = []
        for name, color, watts, size, height, position in settings:
            data = bpy.data.lights.new("Studio | " + name, "AREA")
            data.shape = "RECTANGLE"
            data.color = color
            data.energy = watts
            data.size = size
            data.size_y = height
            obj = bpy.data.objects.new(data.name, data)
            scene.collection.objects.link(obj)
            self.lights.append((obj, position))

    def enable_gpu(self, device):
        preferences = bpy.context.preferences.addons["cycles"].preferences
        options = ("OPTIX", "CUDA") if device == "AUTO" else (device,)
        for backend in options:
            try:
                preferences.compute_device_type = backend
                preferences.refresh_devices()
            except (TypeError, RuntimeError) as exc:
                print(f"CYCLES_BACKEND_UNAVAILABLE {backend}: {exc}", flush=True)
                continue
            for item in preferences.devices:
                item.use = False
            gpu = next((item for item in preferences.devices if item.type == backend), None)
            if gpu is None:
                print(f"CYCLES_BACKEND_UNAVAILABLE {backend}: no matching GPU", flush=True)
                continue
            gpu.use = True
            self.scene.cycles.device = "GPU"
            self.scene.cycles.use_denoising = backend == "OPTIX"
            if backend == "OPTIX":
                self.scene.cycles.denoiser = "OPTIX"
                self.scene.cycles.denoising_use_gpu = True
            active = [item for item in preferences.devices if item.use]
            if len(active) != 1 or active[0].id != gpu.id:
                raise RuntimeError("Failed to isolate the selected Cycles GPU")
            print(f"CYCLES_GPU {backend} | {gpu.name} | {gpu.id} | CPU devices disabled", flush=True)
            return
        raise RuntimeError(f"No GPU available for Cycles backends {options}")

    def render(self, path, resolution, orientation, anchor, height, floor_z, light_center, distance=25):
        rotation = orientation.to_matrix()
        self.camera.rotation_mode = "QUATERNION"
        self.camera.rotation_quaternion = orientation
        self.camera.location = rotation @ Vector(anchor) + rotation.col[2] * distance
        self.camera.data.ortho_scale = height * max(1, resolution[0] / resolution[1])
        self.floor.location.z = floor_z - .0015
        right, toward = rotation.col[0], rotation.col[2]
        toward.z = 0
        toward.normalize()
        for light, (x, y, z) in self.lights:
            light.location = light_center + right * x + toward * y + Vector((0, 0, z))
            light.rotation_euler = (light_center - light.location).to_track_quat("-Z", "Y").to_euler()
        self.scene.render.resolution_x, self.scene.render.resolution_y = resolution
        self.scene.render.filepath = str(path)
        print(f"RENDER_STARTED {resolution[0]}x{resolution[1]} {path}", flush=True)
        result = bpy.ops.render.render(write_still=True)
        if "FINISHED" not in result or not path.is_file():
            raise RuntimeError(f"Cycles did not write {path}")
        print(f"RENDER_WRITTEN {path}", flush=True)


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    width, height = image.size
    image.colorspace_settings.name = "Non-Color"
    data = np.empty((height, width, 4), dtype=np.float32)
    image.pixels.foreach_get(data.ravel())
    bpy.data.images.remove(image)
    return data


def write_pixels(path, canvas):
    height, width = canvas.shape[:2]
    image = bpy.data.images.new(path.name, width, height, alpha=False)
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(canvas.ravel())
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    print(f"RENDER_WRITTEN {path}", flush=True)


def combine(path, files, widths, overlap, feather_height=.16):
    image_height = pixels(files[0]).shape[0]
    total_width = sum(widths)
    canvas = np.zeros((image_height, total_width + 2 * overlap, 4), dtype=np.float32)
    weights = np.zeros((image_height, total_width + 2 * overlap), dtype=np.float32)
    start = 0
    x = np.linspace(-1, 1, 2 * overlap)
    # Blend the floor between panels over a wider region than the upper
    # background to keep shadows and silhouettes visible.
    floor_feather = np.clip(1 - np.arange(image_height) / (feather_height * image_height), 0, 1)
    feather_width = .23 + .77 * floor_feather
    ramp = (1 + np.sin(np.pi * .5 * np.clip(x[None, :] / feather_width[:, None], -1, 1))) * .5
    for file, width in zip(files, widths):
        data = pixels(file)
        blend = np.ones((image_height, width + 2 * overlap), dtype=np.float32)
        blend[:, :2 * overlap] = ramp
        blend[:, -2 * overlap:] = ramp[:, ::-1]
        stop = start + blend.shape[1]
        canvas[:, start:stop] += data * blend[:, :, None]
        weights[:, start:stop] += blend
        start += width
    rgb = canvas[:, overlap:-overlap] / weights[:, overlap:-overlap, None]
    write_pixels(path, np.ascontiguousarray(rgb))


def render_sheet(studio, points, destination, panels, draft, views=VIEWS, canvas_size=None):
    width, height = (1400, 600) if draft else (2800, 1200)
    equal_columns = destination.stem in {"sheet", "sheet_dark"}
    if equal_columns:
        width, height = (1300, 560) if draft else (2600, 1120)
    elif views == FRAME_VIEWS:
        width = 1080 if draft else 2160
    if canvas_size is not None:
        width, height = canvas_size
    footprint = [view_bounds(points, direction) for _, direction in views]
    mesh_widths = np.array([hi[0] - lo[0] for _, lo, hi in footprint])
    body_height = max(hi[1] - lo[1] for _, lo, hi in footprint)
    floor = points[:, 2].min()
    overlap = 24 if draft else 48
    min_spacing = 19 if draft else 38
    if equal_columns:
        column_width = width // len(views)
        frame_height = max(body_height / .927, mesh_widths.max() * height / (column_width - min_spacing))
        widths = [column_width] * len(views)
    else:
        frame_height = max(body_height / .927,
                           mesh_widths.sum() * height / (width - min_spacing * len(views)))
        whitespace = (width - mesh_widths.sum() * height / frame_height) / len(views)
        edges = np.rint(np.cumsum(np.r_[0, mesh_widths * height / frame_height + whitespace])).astype(int)
        widths = np.diff(edges)
    files = []
    for index, ((name, _), (orientation, lo, hi)) in enumerate(zip(views, footprint)):
        anchor = (lo + hi) * .5
        # All five images share a floor projection and unaltered body scale.
        empty_height = frame_height - body_height
        floor_points = points[points[:, 2] <= floor + .014]
        floor_axis = float((floor_points @ np.asarray(orientation.to_matrix()))[:, 1].min())
        anchor[1] = floor_axis + frame_height * .5 - empty_height * .40
        path = panels / f"{destination.stem}-{name}.png"
        studio.render(path, (int(widths[index]) + 2 * overlap, height), orientation, anchor,
                      frame_height, floor, Vector((0, 0, 1.01)))
        files.append(path)
    combine(destination, files, widths, overlap)


def render_detail(studio, objects, points, name, destination, draft):
    floor = points[:, 2].min()
    stature = points[:, 2].max() - floor
    size = 512 if draft else 1024
    if name == "helmet":
        helmet = [obj for obj in objects if obj.get("part") == "helmet"]
        focus = vertices(helmet) if helmet else points[points[:, 2] > floor + .83 * stature]
        direction = (1, -.72, .055)
        margin = 1.20
        light_center = (0, 0, float(focus[:, 2].mean()))
    else:
        from lower_frame import HIP_PIN, KNEE_PIN

        if name == "leg_match":
            knee_z = KNEE_PIN[2]
            lower, upper = knee_z - .23, knee_z + .16
        else:
            lower, upper = floor, HIP_PIN[2] + .075
        focus = points[(points[:, 2] >= lower) & (points[:, 2] <= upper)]
        if name in {"leg_match", "legs_quarter"}:
            focus = focus[focus[:, 0] > 0]
        direction = {
            "legs_front": (0, -1, .025),
            "legs_back": (0, 1, .025),
            "legs_quarter": (.65, -1, .025),
            "legs": (1, -.68, .045),
            "leg_match": (1, 0, 0),
        }[name]
        margin = 1.12
        light_center = (0, 0, (lower + upper) * .5)
    orientation, lo, hi = view_bounds(focus, direction)
    anchor = (lo + hi) * .5
    if name == "helmet":
        anchor[1] -= .020
    resolution = (size, size)
    if name in {"leg_match", "legs_quarter"}:
        resolution = (round(size * .715), size)
        vertical_span = hi[1] - lo[1]
    elif name == "legs":
        vertical_span = hi[1] - lo[1]
    else:
        vertical_span = max((hi - lo)[:2])
    studio.render(destination / (name + ".png"), resolution, orientation, anchor,
                  vertical_span * margin, floor, Vector(light_center))


def render_shoulder(studio, rig, objects, destination, draft):
    from poses import BONE

    shoulder = rig.matrix_world @ rig.pose.bones[BONE + "LUpperarm"].head
    center = shoulder + Vector((.061, -.024, -.083))
    floor = float(vertices(objects)[:, 2].min())
    size = 512 if draft else 1024
    for name, direction in (
        ("shoulder_low_front_quarter", (.72, -1, .035)),
        ("shoulder_low_side", (1, -.29, .035)),
    ):
        orientation, _, _ = view_bounds(np.array([center]), direction)
        anchor = orientation.to_matrix().transposed() @ center
        studio.render(destination / f"{name}.png", (round(size * .825), size),
                      orientation, anchor, .43, floor, center)


def render_distance(studio, points, destination):
    resolution = (1920, 1080)
    direction = (1, -.79, .015)
    orientation, lo, hi = view_bounds(points, direction)
    rotation = orientation.to_matrix()
    anchor = (lo + hi) * .5
    camera = studio.camera
    camera_data = camera.data
    previous_sensor_fit = camera_data.sensor_fit
    camera_data.type = "PERSP"
    camera_data.lens = 50
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.sensor_width = 36
    metres_per_unit = studio.scene.unit_settings.scale_length
    studio.render(destination, resolution, orientation, anchor, hi[1] - lo[1],
                  float(points[:, 2].min()), Vector((0, 0, 1.01)), distance=20 / metres_per_unit)
    target = rotation @ Vector(anchor)
    camera_space = (points - np.asarray(camera.location)) @ np.asarray(rotation)
    projected = camera_space[:, 1] / -camera_space[:, 2] * camera_data.lens / camera_data.sensor_width * resolution[0]
    print(f"DISTANCE_CHECK {(camera.location - target).length * metres_per_unit:.3f} m | "
          f"50 mm / 36 mm | {resolution[0]}x{resolution[1]} | "
          f"{np.ptp(projected):.1f} px projected mesh height", flush=True)
    camera_data.type = "ORTHO"
    camera_data.sensor_fit = previous_sensor_fit


def render_poses(studio, rig, objects, destination, panels, draft):
    from poses import apply_pose

    height = 430 if draft else 860
    width = 290 if draft else 580
    overlap = 32 if draft else 64
    views = (
        ("walk", (-.85, -1, .065)),
        ("crouch", (-1, -.80, .09)),
        ("crouch_deep", (1, -.57, .09)),
        ("arms_raised", (.48, -1, .055)),
        ("arms_forward", (1, -.57, .075)),
    )
    bounds = []
    for name, direction in views:
        apply_pose(rig, name)
        points = vertices(objects)
        orientation, lo, hi = view_bounds(points, direction)
        floor = float(points[:, 2].min())
        feet = points[points[:, 2] <= floor + .014]
        floor_axis = float((feet @ np.asarray(orientation.to_matrix()))[:, 1].min())
        bounds.append((orientation, lo, hi, floor, floor_axis, float(points[:, 2].mean())))
    frame = max(max(hi[1] - floor_axis, (hi[0] - lo[0]) * height / width)
                for _, lo, hi, _, floor_axis, _ in bounds) * 1.13
    files = []
    for (name, _), (orientation, lo, hi, floor, floor_axis, center_z) in zip(views, bounds, strict=True):
        apply_pose(rig, name)
        anchor = (lo + hi) * .5
        anchor[1] = floor_axis + .44 * frame
        path = panels / f"pose-{name}.png"
        studio.render(path, (width + 2 * overlap, height), orientation, anchor, frame,
                      floor, Vector((0, 0, center_z)))
        files.append(path)
    combine(destination / "pose.png", files, [width] * len(views), overlap, feather_height=.32)
    apply_pose(rig, "rest")


def render_arms(studio, rig, objects, destination, panels, draft):
    from poses import BONE, _align_arms, apply_pose

    width, height = (1024, 480) if draft else (2048, 960)
    gutter = 12 if draft else 24
    sides = ("R", "L")
    arm_parts = {
        side: [obj for obj in objects if obj.name.startswith(side + " ") and (
            obj.get("part") in {"arm_plates", "arm_frame"} or obj.get("v5d_region", "").startswith(
                ("upper_arm_", "forearm_", "elbow_", "hand_"))
        )] for side in sides
    }
    floor = float(vertices(objects)[:, 2].min())
    helmet = [obj for obj in objects if obj.get("part") == "helmet"]
    gloves = [obj for obj in objects if obj.name.startswith("Undersuit | Tactical gloves")]
    # Open the arms and rotate the forearms to face the medial plates toward
    # one front camera. This is separate from the five QA poses.
    apply_pose(rig, "rest")
    _align_arms(rig, ((.73, -.60, -.24), (.69, -.58, -.38)))
    for side, angle in (("L", -30), ("R", 30)):
        forearm = rig.pose.bones[BONE + side + "Forearm1"]
        palm = rig.pose.bones[BONE + side + "Palm"]
        origin = forearm.head.copy()
        axis = (palm.head - origin).normalized()
        turned = Matrix.Rotation(radians(angle), 4, axis) @ forearm.matrix
        turned.translation = origin
        forearm.matrix = turned
        bpy.context.view_layer.update()

    focus = vertices(helmet + gloves + arm_parts["R"] + arm_parts["L"])
    orientation, lo, hi = view_bounds(focus, (0, -1, .48))
    anchor = (lo + hi) * .5
    frame = max(hi[1] - lo[1], (hi[0] - lo[0]) * height / width) * 1.14
    center = orientation @ Vector(anchor)
    upper = panels / "arms-inner.png"
    studio.render(upper, (width, height), orientation, anchor, frame, floor, center)
    apply_pose(rig, "rest")

    hand_width = (width - 2 * gutter) // 2
    hands = []
    for side, parts in arm_parts.items():
        def joint(name):
            return rig.matrix_world @ rig.pose.bones[BONE + side + name].head

        gauntlet = next((obj for obj in parts if obj.get("v5d_region") == "hand_back"), None)
        if gauntlet is None:
            continue
        hand = vertices([gauntlet])
        surface_center = hand.mean(axis=0)
        _, _, axes = np.linalg.svd(hand - surface_center, full_matrices=False)
        dorsal = axes[-1]
        if dorsal @ (surface_center - np.asarray(joint("Palm"))) < 0:
            dorsal = -dorsal
        for name in ("Palm", "Digit21", "Digit51"):
            hand = np.vstack((hand, np.asarray(joint(name))))
        orientation, lo, hi = view_bounds(hand, dorsal)
        anchor = (lo + hi) * .5
        path = panels / f"arm-{side.lower()}-gauntlet.png"
        studio.render(path, (hand_width, height // 2), orientation, anchor, .22, floor,
                      Vector(surface_center), distance=2)
        hands.append(path)
    arm_row = pixels(upper)
    if len(hands) == len(sides):
        # Image pixels run bottom-up. Keep the independent tiles separated.
        board = np.full((height + gutter + height // 2, width, 4), (.115, .115, .115, 1),
                        dtype=np.float32)
        board[-height:] = arm_row
        for index, path in enumerate(hands):
            start = index * (hand_width + 2 * gutter)
            board[:height // 2, start:start + hand_width] = pixels(path)
        arm_row = board
    write_pixels(destination / "arms.png", arm_row)


def configure_work_paths():
    WORK.mkdir(parents=True, exist_ok=True)
    os.chdir(WORK)
    for key, name in (
        ("OPTIX_CACHE_PATH", "optix"),
        ("CUDA_CACHE_PATH", "cuda"),
        ("TEMP", "tmp"),
        ("TMP", "tmp"),
    ):
        path = WORK / name
        path.mkdir(exist_ok=True)
        os.environ[key] = str(path)
    bpy.context.preferences.filepaths.temporary_directory = str(WORK / "tmp")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("all", "v5d", "sheet", "helmet", "legs", "legs_front",
                                            "legs_back", "details", "pose", "arms", "frame",
                                            "distance", "probe"), default="all")
    parser.add_argument("--device", choices=("AUTO", "OPTIX", "CUDA"), default="AUTO")
    parser.add_argument("--samples", type=int)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--staged", action="store_true", help="Write final-resolution images to work/render/final-stage")
    parser.add_argument("--output", type=Path, help="Use a dedicated image directory within this entry")
    parser.add_argument("--show-reference", action="store_true",
                        help="Show native witness clothing alongside the production undersuit")
    parser.add_argument("--relaxed", action="store_true",
                        help="Render the same five views with arms lowered, as relaxed.png")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    custom = args.output.resolve() if args.output else None
    if custom and not custom.is_relative_to(ENTRY):
        parser.error("--output must stay within art/v5-astra")
    configure_work_paths()
    sys.path.insert(0, str(ENTRY / "scripts"))
    destination = custom or (WORK / "draft" if args.draft else WORK / "final-stage" if args.staged
                             else ENTRY / "renders")
    panels = custom / "panels" if custom else WORK / ("draft-panels" if args.draft else "panels")
    destination.mkdir(parents=True, exist_ok=True)
    panels.mkdir(exist_ok=True)

    scene = bpy.context.scene
    samples = args.samples or (14 if args.draft else 64)
    if args.group == "probe":
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        studio = Studio(scene, 2, args.device)
        orientation, _, _ = view_bounds(np.zeros((1, 3)), (0, -1, .35))
        studio.render(WORK / "gpu-probe.png", (64, 64), orientation, (0, 0, 0), 1, 0, Vector((0, 0, .5)))
        return

    rig = bpy.data.objects["EFT_Bind"]
    source = Path(bpy.data.filepath)
    with source.open("rb") as stream:
        print(f"RENDER_SOURCE_SHA256 {file_digest(stream, 'sha256').hexdigest()} {source}", flush=True)
    rig.data.pose_position = "REST"
    selected = collection_meshes(scene, show_reference=args.show_reference)
    if args.relaxed:
        from poses import apply_pose
        apply_pose(rig, "relaxed")
        args.group = "sheet"
    data = vertices(selected)
    studio = Studio(scene, samples, args.device)
    if args.group in {"all", "v5d", "sheet"}:
        filename = "relaxed.png" if args.relaxed else "sheet.png"
        render_sheet(studio, data, destination / filename, panels, args.draft)
    for name in ("helmet", "legs", "legs_front", "legs_back"):
        if args.group in {"all", name} or (args.group in {"details", "v5d"} and name != "helmet"):
            render_detail(studio, selected, data, name, destination, args.draft)
    if args.group in {"all", "legs", "details"}:
        for name in ("leg_match", "legs_quarter"):
            render_detail(studio, selected, data, name, panels, args.draft)
    if args.group in {"all", "v5d", "pose"}:
        render_poses(studio, rig, selected, destination, panels, args.draft)
    if args.group in {"all", "v5d", "arms"}:
        render_arms(studio, rig, selected, destination, panels, args.draft)
    if args.group in {"all", "distance"}:
        from poses import apply_pose

        apply_pose(rig, "relaxed")
        render_distance(studio, vertices(selected), destination / "distance20.png")
    if args.group == "all":
        from poses import apply_pose

        apply_pose(rig, "relaxed")
        render_sheet(studio, vertices(selected), destination / "relaxed.png", panels, args.draft)
    if args.group in {"all", "details"}:
        from poses import apply_pose

        apply_pose(rig, "relaxed")
        render_shoulder(studio, rig, selected, panels, args.draft)
    if args.group in {"all", "frame"}:
        frame = {obj for obj in selected if obj.get("part") in FRAME_PARTS}
        missing = FRAME_PARTS - {obj.get("part") for obj in frame}
        if missing:
            raise RuntimeError(f"Missing LOD0 frame components: {sorted(missing)}")
        from poses import apply_pose

        apply_pose(rig, "relaxed")
        for obj in selected - frame:
            obj.hide_render = True
        render_sheet(studio, vertices(frame), destination / "frame.png", panels, args.draft, FRAME_VIEWS)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
