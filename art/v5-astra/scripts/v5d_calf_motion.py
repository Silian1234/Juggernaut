"""Build and drive nested posterior calf plates on the native leg rig."""

from functools import lru_cache
from math import cos, radians, sin

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from leg_shells import between, lerp, shell_grid
from legs import Geometry, TrouserSkin, _materials
from poses import ANGLES, BONE, apply_pose
from v5c_shin import SHIN_AXES, greave_skin, worn_clearance


CALF_ROLE = 8
SEGMENTS = ((.151, .254), (.247, .349), (.343, .441))
LABELS = ("Lower", "Middle", "Upper")
THICKNESS = .0055
# Per-segment axial travel and radial tier, in metres.
REGULAR = ((.040, .009), (.087, .017))
DEEP = ((.071, .011), (.132, .0215))


def _casting(geo, segment):
    low, high = SEGMENTS[segment]
    geo.armor_component = CALF_ROLE

    @lru_cache(maxsize=None)
    def profile(u, v):
        edge = abs(u * 2 - 1)
        t = (v - low) / (high - low)
        lower_clip = (.028 * max(0, (edge - .57) / .43) if segment == 0
                      else .006 * max(0, (edge - .70) / .30))
        upper_clip = (.027 * min(1, max(0, (.91 - edge) / .55)) if segment == 2
                      else .004 * max(0, (edge - .73) / .27))
        z = v + lower_clip * (1 - t) - upper_clip * t
        x, y = between(SHIN_AXES, z)
        angle = radians(lerp(125, 240, u))
        dx, dy = sin(angle), -cos(angle)
        # The outward bottom rim passes over the next shell's thinned top.
        lip = .0060 * max(0, 1 - (v - low) / .024) if segment else 0
        radius = worn_clearance(geo, (x, y, z), .0078 + lip, (dx, dy))
        return Vector((x, y, z)), Vector((dx, dy, 0)), radius

    def project(u, v, offset):
        center, radial, radius = profile(u, v)
        taper = .0024 * max(0, 1 - (high - v) / .021) if segment < 2 else 0
        return center + radial * (radius + (THICKNESS + offset) * (THICKNESS - taper) / THICKNESS)

    columns = ((0, .16, .34, .53, .72, .86, 1) if geo.lod
               else (0, .14, .29, .44, .58, .72, .86, 1))
    stations = (0, .19, .46, .72, 1) if segment == 0 else (0, .22, .63, 1)
    levels = [lerp(low, high, t) for t in stations]
    size = len(columns) * len(levels)
    shell_grid(geo, project, columns, levels, lambda p: greave_skin(geo, p), THICKNESS)
    geo.inner_faces = {
        CALF_ROLE: [i for i, face in enumerate(geo.faces)
                    if all(size <= vertex < 2 * size for vertex in face)]
    }


def _remove_one_piece_shell(obj):
    mesh = bmesh.new()
    retired = f"panel_depth_pairs_{CALF_ROLE}"
    try:
        mesh.from_mesh(obj.data)
        original = mesh.verts.layers.int.new("V5D source vertex")
        for vertex in mesh.verts:
            vertex[original] = vertex.index
        role = mesh.faces.layers.int["armor_component"]
        posterior = [face for face in mesh.faces if face[role] == CALF_ROLE]
        if not posterior:
            raise ValueError(f"Missing rear calf on {obj.name}")
        bmesh.ops.delete(mesh, geom=posterior, context="FACES")
        mesh.verts.index_update()
        indices = {vertex[original]: vertex.index for vertex in mesh.verts}
        mesh.verts.layers.int.remove(original)
        depth = {key: [indices[i] for i in obj[key]]
                 for key in obj.keys()
                 if key.startswith("panel_depth_pairs_") and key != retired}
        mesh.to_mesh(obj.data)
    finally:
        mesh.free()
    for key, value in depth.items():
        obj[key] = value
    if retired in obj:
        del obj[retired]
    if (direction := f"panel_depth_{CALF_ROLE}") in obj:
        del obj[direction]
    obj.data.update()


def rebuild(lod, collection, rig):
    """Replace each rear calf casting before the downstream triangle budget."""
    trousers = collection.all_objects[f"Undersuit | Combat trousers LOD{lod}"]
    fit = TrouserSkin(trousers, rig)
    materials = _materials()
    parts = []
    for side, sign in (("L", 1), ("R", -1)):
        original = collection.all_objects[f"LegArmour_{side}_LOD{lod}"]
        _remove_one_piece_shell(original)
        for index, label in enumerate(LABELS):
            geo = Geometry(sign, lod, None, fit)
            _casting(geo, index)
            obj = geo.emit(f"Calf Armour {label}_{side}_LOD{lod}", "leg_plates",
                           collection, rig, materials)
            obj["side"] = side
            obj["calf_segment"] = index
            parts.append(obj)
    return parts


def _skin_matrices(rig):
    world = rig.matrix_world
    inverse = world.inverted()
    return {bone.name: world @ bone.matrix @ bone.bone.matrix_local.inverted() @ inverse
            for bone in rig.pose.bones if bone.bone.use_deform}


def _mixed_transform(weights, matrices):
    result = Matrix(((0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)))
    for name, weight in weights.items():
        result += weight * matrices[name]
    return result


def _slide_target(point, sign, fit, travel, tier):
    z = point.z - travel
    x0, y0 = between(SHIN_AXES, point.z)
    x1, y1 = between(SHIN_AXES, z)
    start = Vector((sign * x0, y0, point.z))
    end = Vector((sign * x1, y1, z))
    radial = (point - start).normalized()
    source = fit.index.ray_cast(start, radial, .20)[3]
    target = fit.index.ray_cast(end, radial, .20)[3]
    correction = target - source if source is not None and target is not None else 0
    return end + radial * ((point - start).length + correction + tier)


def _make_key(obj, fit, matrices, name, travel, tier):
    if not obj.data.shape_keys:
        obj.shape_key_add(name="Basis")
    key = obj.shape_key_add(name=name, from_mix=False)
    world = obj.matrix_world
    inverse = world.inverted()
    sign = 1 if obj["side"] == "L" else -1
    groups = [group.name for group in obj.vertex_groups]
    for vertex in obj.data.vertices:
        target = _slide_target(world @ vertex.co, sign, fit, travel, tier)
        posed = _mixed_transform(fit.weights(target), matrices) @ target
        original = {groups[group.group]: group.weight for group in vertex.groups}
        # Convert the measured posed target to a pre-armature shape key.
        key.data[vertex.index].co = inverse @ _mixed_transform(original, matrices).inverted_safe() @ posed
    return key


def _drive(key, rig, side, deep):
    driver = key.driver_add("value").driver
    flex = driver.variables.new()
    flex.name = "bend"
    flex.type = "TRANSFORMS"
    target = flex.targets[0]
    target.id = rig
    target.bone_target = BONE + side + "Calf"
    target.transform_type = "ROT_Z"
    target.transform_space = "LOCAL_SPACE"
    target.rotation_mode = "SWING_TWIST_Z"
    regular = "min(1, max(0, (-bend - 0.88) / 0.72))"
    deeper = "min(1, max(0, (-bend - 1.60) / 0.19))"
    driver.expression = deeper if deep else f"{regular} * (1 - {deeper})"


def _apply_swapped_deep_crouch(rig):
    """Use the same anatomical bend with the right leg in the deeper fold."""
    apply_pose(rig, "crouch_deep")
    angles = ANGLES["crouch_deep"]
    pelvis = rig.pose.bones[BONE + "Pelvis"]
    pelvis.location = (0, 0, 0)
    for side, opposite in (("L", "R"), ("R", "L")):
        for joint in ("Thigh1", "Calf", "Foot"):
            x, y, z = angles[opposite + joint]
            rotation = Euler((radians(x), radians(-y), radians(-z))).to_matrix()
            bone = rig.pose.bones[BONE + side + joint]
            basis = bone.bone.matrix_local.to_3x3()
            bone.matrix_basis = (basis.inverted() @ rotation @ basis).to_4x4()
    bpy.context.view_layer.update()
    toes = [rig.pose.bones[BONE + side + "Toe"] for side in ("L", "R")]
    lift = min(bone.bone.head_local.z for bone in toes) - min(bone.head.z for bone in toes)
    pelvis.location = pelvis.bone.matrix_local.to_3x3().inverted() @ Vector((0, 0, lift))
    bpy.context.view_layer.update()


def _install_stage(objects, fit, rig, table, deep=False):
    matrices = _skin_matrices(rig)
    name = "Deep crouch retraction" if deep else "Crouch retraction"
    for obj in objects:
        travel, tier = table[obj["calf_segment"] - 1]
        key = _make_key(obj, fit, matrices, name, travel, tier)
        _drive(key, rig, obj["side"], deep)


def install(lod, collection, rig):
    """Install only shape keys after topology and budget are final."""
    trousers = collection.all_objects[f"Undersuit | Combat trousers LOD{lod}"]
    fit = TrouserSkin(trousers, rig)
    moving = [obj for obj in collection.all_objects if obj.get("calf_segment", 0)]
    previous_pose = rig.data.pose_position
    previous_basis = [(bone, bone.matrix_basis.copy()) for bone in rig.pose.bones]
    try:
        apply_pose(rig, "crouch")
        _install_stage(moving, fit, rig, REGULAR)
        apply_pose(rig, "crouch_deep")
        _install_stage((obj for obj in moving if obj["side"] == "L"), fit, rig, DEEP, deep=True)
        _apply_swapped_deep_crouch(rig)
        _install_stage((obj for obj in moving if obj["side"] == "R"), fit, rig, DEEP, deep=True)
    finally:
        for bone, basis in previous_basis:
            bone.matrix_basis = basis
        rig.data.pose_position = previous_pose
        bpy.context.view_layer.update()
    return moving
