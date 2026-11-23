"""Static competition QA poses authored for the native EFT bind skeleton."""

from math import radians

import bpy
from mathutils import Matrix, Vector


POSES = ("rest", "relaxed", "walk", "crouch", "crouch_deep", "arms_raised", "arms_forward")
BONE = "Base Human"
ARM_DIRECTIONS = {
    "relaxed": ((.29, .04, -1), (.08, -.14, -1)),
    "arms_raised": ((.42, -.08, .90), (.17, -.16, .97)),
    "arms_forward": ((.14, -.98, .05), (.03, -.79, .60)),
}

# Angles about the anatomical width (world X) in the unposed bone frame.
# A collar is a separate root in EFT_Bind, so carry it with the chest explicitly.
ANGLES = {
    "walk": {
        "Spine1": (3, 0, -3),
        "Spine3": (1, 0, -4),
        "LThigh1": (-25, 0, 0),
        "LCalf": (16, 0, 0),
        "LFoot": (7, 0, 0),
        "RThigh1": (15, 0, 0),
        "RCalf": (28, 0, 0),
        "RFoot": (-24, 0, 0),
        "LUpperarm": (58, -23, -9),
        "LForearm1": (-26, 0, 0),
        "RUpperarm": (32, 20, 9),
        "RForearm1": (-32, 0, 0),
    },
    "crouch_deep": {
        "Spine1": (22, 0, 0),
        "Spine2": (5, 0, 0),
        "LThigh1": (-68, -5, 0),
        "LCalf": (104, 0, 0),
        "LFoot": (-36, 5, 0),
        "RThigh1": (-64, 4, 0),
        "RCalf": (93, 0, 0),
        "RFoot": (-29, -4, 0),
        "LUpperarm": (9, 0, -7),
        "RUpperarm": (12, 0, 6),
        "LForearm1": (-14, 0, 0),
        "RForearm1": (-17, 0, 0),
    },
}
ANGLES["crouch"] = {
    **ANGLES["crouch_deep"],
    "LThigh1": (-64, -4, 0),
    "LCalf": (93, 0, 0),
    "LFoot": (-29, 4, 0),
}


def _align_arms(rig, directions):
    """Aim the arm segments in armature space, carrying each child in turn."""
    for side, sign in (("L", 1), ("R", -1)):
        prefix = BONE + side
        for moving, child, direction in (
            ("Upperarm", "Forearm1", directions[0]),
            ("Forearm1", "Palm", directions[1]),
        ):
            bone = rig.pose.bones[prefix + moving]
            tip = rig.pose.bones[prefix + child]
            x, y, z = direction
            delta = (tip.head - bone.head).rotation_difference(Vector((x * sign, y, z)))
            rotation = delta.to_matrix().to_4x4() @ bone.matrix
            rotation.translation = bone.head
            bone.matrix = rotation
            bpy.context.view_layer.update()


def _rotate_collars(rig, pose):
    """Include shoulder-girdle elevation or protraction in the new arm poses."""
    for side, sign in (("L", 1), ("R", -1)):
        collar = rig.pose.bones[BONE + side + "Collarbone"]
        if pose == "arms_raised":
            delta = Matrix.Rotation(radians(-24 * sign), 4, "Y")
        else:
            delta = Matrix.Rotation(radians(-12 * sign), 4, "Z")
        rotated = delta @ collar.matrix
        rotated.translation = collar.head
        collar.matrix = rotated
    bpy.context.view_layer.update()


def apply_pose(rig, name):
    """Apply one pose without creating any action, keyframe or constraint."""
    if name not in POSES:
        raise ValueError(f"Unknown competition pose {name!r}")
    rig.data.pose_position = "POSE"
    for bone in rig.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    if name == "rest":
        return

    if name in ARM_DIRECTIONS:
        if name != "relaxed":
            _rotate_collars(rig, name)
        _align_arms(rig, ARM_DIRECTIONS[name])
        return

    for suffix, angles in ANGLES[name].items():
        bone = rig.pose.bones[BONE + suffix]
        basis = bone.bone.matrix_local.to_3x3()
        rotation = Matrix.Identity(3)
        for axis, angle in zip("XYZ", angles):
            rotation = Matrix.Rotation(radians(angle), 3, axis) @ rotation
        bone.matrix_basis = (basis.inverted() @ rotation @ basis).to_4x4()
    bpy.context.view_layer.update()

    floor_bones = [rig.pose.bones[BONE + side + "Toe"] for side in ("L", "R")]
    lift = min(bone.bone.head_local.z for bone in floor_bones)
    lift -= min(bone.head.z for bone in floor_bones)
    pelvis = rig.pose.bones[BONE + "Pelvis"]
    pelvis.location = pelvis.bone.matrix_local.to_3x3().inverted() @ Vector((0, 0, lift))
    bpy.context.view_layer.update()

    chest = rig.pose.bones[BONE + "Spine3"]
    chest_delta = chest.matrix @ chest.bone.matrix_local.inverted()
    for side in ("L", "R"):
        collar = rig.pose.bones[BONE + side + "Collarbone"]
        collar.matrix = chest_delta @ collar.bone.matrix_local
    bpy.context.view_layer.update()



