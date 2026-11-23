"""Refit inherited deltoid and elbow shells for the existing arm motion."""

from mathutils import Vector

from arms import ArmBasis
from poses import BONE


def thin_deltoid(obj, rig, side):
    """Reduce the crown and rim depth while keeping the fitted backing."""
    shoulder = rig.matrix_world @ rig.data.bones[BONE + side + "Upperarm"].head_local
    elbow = rig.matrix_world @ rig.data.bones[BONE + side + "Forearm1"].head_local
    axis = (elbow - shoulder).normalized()
    backing_tag = obj.data.attributes["v5c_inner"].data
    backing = {idx for face in obj.data.polygons if backing_tag[face.index].value
               for idx in face.vertices}
    to_mesh = obj.matrix_world.inverted().to_3x3()
    for vertex in obj.data.vertices:
        if vertex.index in backing:
            continue
        from_shoulder = obj.matrix_world @ vertex.co - shoulder
        radial = (from_shoulder - axis * from_shoulder.dot(axis)).normalized()
        vertex.co -= to_mesh @ (radial * .011)


def add_shoulder_relief(obj, rig, side, direction):
    """Ease the proximal rim as the upper arm flexes or elevates."""
    obj.shape_key_add(name="Basis", from_mix=False)
    relief = obj.shape_key_add(name="Deltoid articulation relief", from_mix=False)
    for vertex in relief.data:
        width = abs((obj.matrix_world @ vertex.co).x)
        proximal = min(1.0, max(0.0, (.250 - width) / .103))
        vertex.co += direction * proximal

    driver = relief.driver_add("value").driver
    driver.type = "SCRIPTED"
    for name, axis in (("flexion", "ROT_X"), ("elevation", "ROT_Y")):
        variable = driver.variables.new()
        variable.name = name
        variable.type = "TRANSFORMS"
        target = variable.targets[0]
        target.id = rig
        target.bone_target = BONE + side + "Upperarm"
        target.transform_type = axis
        target.transform_space = "LOCAL_SPACE"
        target.rotation_mode = "XYZ"
    driver.expression = (
        "max(0.46 * min(1, max(0, (abs(flexion) - 0.28) / 0.32)), "
        "min(1, max(0, (abs(elevation) - 0.38) / 0.77)))"
    )


def integrate(lod, collection, rig):
    """Make bind-space geometry adjustments before the triangle budget pass."""
    changed = []
    for obj in collection.all_objects:
        if obj.get("part") != "arm_plates":
            continue
        side, _, label = obj.name.split(".")[0].partition(" ")
        if side not in {"L", "R"} or label not in {"Deltoid shell", "Elbow impact cap"}:
            continue
        sign = 1 if side == "L" else -1
        to_mesh = obj.matrix_world.inverted().to_3x3()
        if label == "Deltoid shell":
            thin_deltoid(obj, rig, side)
            # Relieve the proximal rim that swings into the shoulder girdle.
            # Fade the adjustment before the distal edge meets the lower lame.
            relief = .035 if lod == 0 else (.045 if side == "L" else .040)
            direction = to_mesh @ Vector((sign * relief, 0, 0))
            add_shoulder_relief(obj, rig, side, direction)
        else:
            elbow = rig.matrix_world @ rig.data.bones[BONE + side + "Forearm1"].head_local
            wrist = rig.matrix_world @ rig.data.bones[BONE + side + "Palm"].head_local
            basis = ArmBasis(elbow, wrist, sign)
            # The coarse backing has longer edges across the convex cloth fold.
            lift = .008 if lod == 0 else (.0115 if side == "L" else .0125)
            offset = to_mesh @ (basis.up * lift)
            for vertex in obj.data.vertices:
                vertex.co += offset
        obj.data.update()
        changed.append(obj)
    return changed


def fit_outer_thighs(lod, collection, rig):
    """Give the distal rear quarter of the outer thigh room at high knee flexion."""
    for side in ("L", "R"):
        obj = collection.all_objects[f"LegArmour_{side}_LOD{lod}"]
        roles = obj.data.attributes["armor_component"].data
        shell = {i for face in obj.data.polygons if roles[face.index].value == 1
                 for i in face.vertices}
        fixed = {i for face in obj.data.polygons if roles[face.index].value != 1
                 for i in face.vertices}
        if not obj.data.shape_keys:
            obj.shape_key_add(name="Basis", from_mix=False)
        relief = obj.shape_key_add(name="Outer thigh knee clearance", from_mix=False)
        to_mesh = obj.matrix_world.inverted().to_3x3()
        travel = (.033, -.012, .018) if side == "L" else (-.027, 0, 0)
        offset = to_mesh @ Vector(travel)
        for index in shell - fixed:
            vertex = relief.data[index]
            bind = obj.matrix_world @ vertex.co
            # The mounting lugs sit forward of this taper and retain their fit.
            rear = min(1.0, max(0.0, (bind.y - .002) / .046))
            distal = min(1.0, max(0.0, (.745 - bind.z) / .075))
            vertex.co += offset * rear * distal
        driver = relief.driver_add("value").driver
        driver.type = "SCRIPTED"
        variable = driver.variables.new()
        variable.name = "flexion"
        variable.type = "TRANSFORMS"
        target = variable.targets[0]
        target.id = rig
        target.bone_target = BONE + side + "Calf"
        target.transform_type = "ROT_Z"
        target.transform_space = "LOCAL_SPACE"
        target.rotation_mode = "XYZ"
        flexion_range = 0.62 if side == "L" else 0.42
        driver.expression = f"min(1, max(0, (-flexion - 1.18) / {flexion_range}))"
    if lod == 1:
        fit_medial_greave(collection, rig)


def fit_medial_greave(collection, rig):
    """Ease the coarse left greave rim at the deepest knee flexion."""
    obj = collection.all_objects["LegArmour_L_LOD1"]
    roles = obj.data.attributes["armor_component"].data
    rim = {i for face in obj.data.polygons if roles[face.index].value == 4
           for i in face.vertices}
    fixed = {i for face in obj.data.polygons if roles[face.index].value != 4
             for i in face.vertices}
    relief = obj.shape_key_add(name="Medial greave knee clearance", from_mix=False)
    offset = obj.matrix_world.inverted().to_3x3() @ Vector((-.007, -.006, -.008))
    for index in rim - fixed:
        vertex = relief.data[index]
        x, y, z = obj.matrix_world @ vertex.co
        medial = max(0.0, 1.0 - abs(x - .080) / .032)
        rear = max(0.0, 1.0 - abs(y - .040) / .034)
        proximal = max(0.0, 1.0 - abs(z - .425) / .038)
        vertex.co += offset * medial * rear * proximal
    driver = relief.driver_add("value").driver
    driver.type = "SCRIPTED"
    variable = driver.variables.new()
    variable.name = "flexion"
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = rig
    target.bone_target = BONE + "LCalf"
    target.transform_type = "ROT_Z"
    target.transform_space = "LOCAL_SPACE"
    target.rotation_mode = "XYZ"
    driver.expression = "min(1, max(0, (-flexion - 1.65) / 0.15))"
