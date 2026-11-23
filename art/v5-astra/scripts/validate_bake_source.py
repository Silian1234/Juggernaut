"""Verify source/final equality at vertices, loops, weights, shape keys, and rig."""
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parent.parent

def vector(value):
    return tuple(float(component) for component in value)

def snapshot():
    meshes = {}
    rigs = {}
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            mesh = obj.data
            coordinates = tuple(vector(v.co) for v in mesh.vertices)
            weights = tuple(tuple((g.group, g.weight) for g in v.groups) for v in mesh.vertices)
            keys = {} if mesh.shape_keys is None else {
                block.name: (block.relative_key.name, block.value,
                             tuple(vector(item.co) for item in block.data))
                for block in mesh.shape_keys.key_blocks
            }
            meshes[obj.name] = (
                tuple(tuple(row) for row in obj.matrix_world), coordinates, weights, keys,
                tuple((tuple(p.vertices), p.material_index, p.use_smooth) for p in mesh.polygons),
                tuple(tuple(edge.vertices) for edge in mesh.edges),
                tuple(vector(corner.vector) for corner in mesh.corner_normals),
                tuple(group.name for group in obj.vertex_groups),
                tuple((modifier.type, modifier.object.name) for modifier in obj.modifiers
                      if modifier.type == "ARMATURE" and modifier.object),
                tuple(slot.material.name if slot.material else "" for slot in obj.material_slots),
            )
        elif obj.type == "ARMATURE":
            rigs[obj.name] = (
                tuple(tuple(row) for row in obj.matrix_world),
                tuple((bone.name, bone.parent.name if bone.parent else None,
                       tuple(tuple(row) for row in bone.matrix_local), bone.use_deform)
                      for bone in obj.data.bones),
                tuple((bone.name, tuple(tuple(row) for row in bone.matrix_basis))
                      for bone in obj.pose.bones),
            )
    return meshes, rigs

bpy.ops.wm.open_mainfile(filepath=str(ROOT / "juggernaut_v5.blend"))
before_mesh, before_rig = snapshot()
bpy.ops.wm.open_mainfile(filepath=str(ROOT / "work" / "bake" / "layout.blend"))
after_mesh, after_rig = snapshot()
assert before_mesh.keys() == after_mesh.keys()
assert before_rig.keys() == after_rig.keys()
for name, data in before_mesh.items():
    assert data == after_mesh[name], (name, [i for i, (a, b) in enumerate(zip(data, after_mesh[name])) if a != b])
for name, data in before_rig.items():
    assert data == after_rig[name], name
print(f"Unchanged geometry, normals, material slots, weights and shape keys on {len(before_mesh)} meshes. {len(before_rig)} rigs unchanged.")
