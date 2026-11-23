# Thickens the V5d armour plates: the outer shell of every plate (faces whose normal ray does NOT hit the
# body/clothing within RANGE) is pushed outward along its vertex normals by EXTRA metres; the rims stretch.
# Inner shells, UVs and vertex groups are untouched. Run in Blender:
#   blender -b juggernaut_v5_textured.blend --python thicken_plates.py -- <extra_m> <out.blend>
import sys
import bpy, bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

extra = float(sys.argv[sys.argv.index("--") + 1])
out = sys.argv[sys.argv.index("--") + 2]
RANGE = 0.08

deps = bpy.context.evaluated_depsgraph_get()

def world_bvh(objs):
    verts, polys = [], []
    for o in objs:
        me = o.evaluated_get(deps).to_mesh()
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        polys += [[base + i for i in p.vertices] for p in me.polygons]
        o.evaluated_get(deps).to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys)

def coll_objs(prefix):
    return [o for c in bpy.data.collections if c.name.startswith(prefix) for o in c.objects if o.type == 'MESH']

body = {lod: world_bvh(coll_objs("Combat clothing · " + lod)) for lod in ("LOD0", "LOD1")}
targets = [o for o in coll_objs("Articulated armor") + coll_objs("Limb armor")]
moved_total = 0
for o in targets:
    lod = "LOD1" if "LOD1" in [c.name.split("· ")[-1] for c in o.users_collection] else "LOD0"
    tree = body[lod]
    armor_slots = {i for i, m in enumerate(o.data.materials) if m and ("Armor" in m.name or "Khaki" in m.name or "Knee cop" in m.name)}
    if not armor_slots:
        continue
    bm = bmesh.new(); bm.from_mesh(o.data); bm.normal_update()
    mw = o.matrix_world; nmat = mw.to_3x3().inverted().transposed()
    outer = set()
    for f in bm.faces:
        if f.material_index not in armor_slots:
            continue
        c = mw @ f.calc_center_median(); n = (nmat @ f.normal).normalized()
        hit = tree.ray_cast(c + n * 0.001, n, RANGE)
        if hit[0] is None:                      # facing away from the body -> outer shell
            outer.add(f)
    inner_verts = {v for f in bm.faces if f.material_index in armor_slots and f not in outer for v in f.verts
                   if (nmat @ f.normal).normalized().dot(Vector((0, 0, 0))) == 0 and f.normal.length > 0}
    verts = {v for f in outer for v in f.verts}
    # keep the inner shell in place: only move vertices that belong exclusively to outer faces or rim-free corners
    move = {v for v in verts if all((lf in outer) or (lf.material_index not in armor_slots) or abs(lf.normal.dot(v.normal)) < 0.5
                                    for lf in v.link_faces)}
    for v in move:
        v.co += v.normal * extra
    bm.to_mesh(o.data); bm.free(); o.data.update()
    moved_total += len(move)
print("THICKEN objects", len(targets), "verts moved", moved_total)
bpy.ops.wm.save_as_mainfile(filepath=out, copy=True)
print("SAVED", out)
