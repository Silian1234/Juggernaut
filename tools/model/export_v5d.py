# Export the approved V5d model into the Juggernaut bundle pipeline formats.
#   suit   : art/v5d_suit/suit_unity.json (skinned, EXO format) + textures exo_dif/exo_nrm/exo_gloss (one 4K atlas:
#            armor, textile and frame atlases are packed into three 2K quadrants)
#   helmet : art/v5d_rigid/helmet.json, helmet_lod1.json  (rigid, Blender world coordinates, one material)
#   thermal: art/v5d_rigid/thermal.json                    (rigid, LOD0 only)
# Run: blender -b juggernaut_v5_textured.blend --python export_v5d.py -- <maps dir> <project root>
import bpy, json, sys, os, shutil
from pathlib import Path
import numpy as np

maps, root = (Path(p) for p in sys.argv[sys.argv.index("--") + 1:][:2])
SUIT = root / "art/v5d_suit"; RIGID = root / "art/v5d_rigid"
for d in (SUIT / "textures", RIGID / "textures"):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- suit atlas (quadrants in UV space)
QUAD = {"V5d Atlas | Armor": (0.0, 0.5), "V5d Atlas | Textile": (0.5, 0.5), "V5d Atlas | Frame": (0.0, 0.0)}
SRC = {"V5d Atlas | Armor": "armor", "V5d Atlas | Textile": "textile", "V5d Atlas | Frame": "frame"}


def load(path, srgb):
    im = bpy.data.images.load(str(path)); im.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    w, h = im.size
    a = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)   # bottom-up rows, like UV space
    bpy.data.images.remove(im); return a


def down2(a):
    return a.reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2, 4).mean(axis=(1, 3))


def save(a, path, srgb):
    h, w = a.shape[:2]
    im = bpy.data.images.new(path.stem, w, h, alpha=True)
    im.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    im.pixels.foreach_set(np.clip(a, 0, 1).astype(np.float32).ravel())
    im.filepath_raw = str(path); im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)


def pack_suit_maps():
    out = {k: np.zeros((4096, 4096, 4), np.float32) for k in ("dif", "nrm", "gloss")}
    out["nrm"][..., 0] = out["nrm"][..., 1] = 0.5; out["nrm"][..., 2] = 1.0
    for mat, (u0, v0) in QUAD.items():
        s = SRC[mat]
        alb = down2(load(maps / f"{s}_albedo.png", True))
        nrm = down2(load(maps / f"{s}_normal.png", False))
        sg = down2(load(maps / f"{s}_specgloss.png", False))
        x0, y0 = int(u0 * 4096), int(v0 * 4096)
        sl = (slice(y0, y0 + 2048), slice(x0, x0 + 2048))
        out["dif"][sl] = alb
        n = nrm.copy(); v = n[..., :3] * 2 - 1
        v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6); n[..., :3] = v * 0.5 + 0.5
        out["nrm"][sl] = n
        g = sg.copy(); g[..., 0] = g[..., 1] = g[..., 2] = sg[..., 0]      # _SpecMap: specular level
        out["gloss"][sl] = g
    for k in out:
        out[k][..., 3] = 1.0
        save(out[k], SUIT / "textures" / f"exo_{k}.png", k == "dif")
    print("SUIT ATLAS written")


# ---------------------------------------------------------------- suit mesh (skinned)
BIND = json.loads((root / "art/suit/eft_bindposes.json").read_text())
bind = {b: v for e in BIND.values() for b, v in e["bind"].items()}
used = []


def bone_index(name):
    if name not in bind:
        raise RuntimeError(f"bone {name} has no EFT bindpose")
    if name not in used:
        used.append(name)
    return used.index(name)


def suit_objects(lod):
    return [o for o in bpy.data.collections[f"EXO_LOD{lod}"].all_objects
            if o.type == "MESH" and o.get("part") not in ("helmet", "thermal")]


def export_suit():
    lods = []
    for lod in (0, 1):
        V, N, UV, T, BI, BW = [], [], [], [], [], []
        for o in sorted(suit_objects(lod), key=lambda o: o.name):
            me = o.data; me.calc_loop_triangles()
            uvl = me.uv_layers.active.data
            names = {g.index: g.name for g in o.vertex_groups}
            mw = o.matrix_world; nmat = mw.to_3x3().inverted().transposed()
            cn = me.corner_normals
            idx = {}
            for t in me.loop_triangles:
                mat = me.materials[t.material_index].name
                u0, v0 = QUAD[mat]
                tri = []
                for k in range(3):
                    li = t.loops[k]; vi = me.loops[li].vertex_index
                    n = (nmat @ cn[li].vector).normalized()
                    uv = uvl[li].uv
                    uv = (u0 + 0.5 * min(max(uv[0], 0), 1), v0 + 0.5 * min(max(uv[1], 0), 1))
                    key = (vi, round(n.x, 4), round(n.y, 4), round(n.z, 4), round(uv[0], 5), round(uv[1], 5))
                    if key not in idx:
                        idx[key] = len(V)
                        co = mw @ me.vertices[vi].co
                        V.append([-co.x, co.y, co.z]); N.append([-n.x, n.y, n.z]); UV.append([uv[0], uv[1]])
                        ws = sorted(((names[g.group], g.weight) for g in me.vertices[vi].groups if g.weight > 1e-5),
                                    key=lambda x: -x[1])[:4]
                        if not ws:
                            raise ValueError(f"{o.name} vertex {vi} has no influences")
                        s = sum(w for _, w in ws)
                        BI.append([bone_index(b) for b, _ in ws] + [0] * (4 - len(ws)))
                        BW.append([w / s for _, w in ws] + [0.0] * (4 - len(ws)))
                    tri.append(idx[key])
                T.append([tri[0], tri[2], tri[1]])
        lods.append({"v": [c for x in V for c in x], "n": [c for x in N for c in x], "uv": [c for x in UV for c in x],
                     "t": [i for x in T for i in x], "bi": [i for x in BI for i in x], "bw": [w for x in BW for w in x]})
        print(f"SUIT LOD{lod} verts {len(V)} tris {len(T)}")
    bones = []
    for b in used:
        bp = np.linalg.inv(np.array(bind[b]["world"]))
        bones.append({"name": b, "path": bind[b]["path"], "bindpose": [float(x) for x in bp.T.flatten()]})
    (SUIT / "suit_unity.json").write_text(json.dumps({"bones": bones, "lods": lods}), encoding="utf-8")
    print("SUIT exported, bones", len(bones))


# ---------------------------------------------------------------- rigid (helmet, thermal)
def rigid_json(objs, name):
    positions, normals, uv, indices = [], [], [], []
    for o in sorted(objs, key=lambda o: o.name):
        me = o.data; me.calc_loop_triangles()
        uvl = me.uv_layers.active.data; cn = me.corner_normals
        mw = o.matrix_world; nmat = mw.to_3x3().inverted().transposed()
        idx = {}
        for t in me.loop_triangles:
            tri = []
            for k in range(3):
                li = t.loops[k]; vi = me.loops[li].vertex_index
                n = (nmat @ cn[li].vector).normalized(); u = uvl[li].uv
                key = (vi, round(n.x, 4), round(n.y, 4), round(n.z, 4), round(u[0], 5), round(u[1], 5))
                if key not in idx:
                    idx[key] = len(positions); co = mw @ me.vertices[vi].co
                    positions.append({"x": co.x, "y": co.y, "z": co.z})
                    normals.append({"x": n.x, "y": n.y, "z": n.z})
                    uv.append({"x": u[0], "y": u[1]})
                tri.append(idx[key])
            indices.extend(tri)
    mesh = {"name": name, "positions": positions, "normals": normals, "uv": uv,
            "submeshes": [{"material": 0, "indices": indices}]}
    spec = {"name": "V5d helmet", "color": {"r": 1, "g": 1, "b": 1, "a": 1}, "metallic": 0.35, "smoothness": 0.35,
            "emission": {"r": 0, "g": 0, "b": 0, "a": 1}}
    print(f"RIGID {name} verts {len(positions)} tris {len(indices) // 3}")
    return {"name": name, "meshes": [mesh], "materials": [spec]}


def part_objects(lod, part):
    return [o for o in bpy.data.collections[f"EXO_LOD{lod}"].all_objects if o.type == "MESH" and o.get("part") == part]


def export_rigid():
    for lod, fname in ((0, "helmet.json"), (1, "helmet_lod1.json")):
        (RIGID / fname).write_text(json.dumps(rigid_json(part_objects(lod, "helmet"), "helmet")), encoding="utf-8")
    (RIGID / "thermal.json").write_text(json.dumps(rigid_json(part_objects(0, "thermal"), "thermal")), encoding="utf-8")
    for k in ("albedo", "normal", "specgloss"):
        shutil.copy2(maps / f"helmet_{k}.png", RIGID / "textures" / f"v5d_helmet_{k}.png")
    # cell stays the approved v4 item: copy its source and maps
    v4 = root / "art/accessories"
    shutil.copy2(v4 / "cell.json", RIGID / "cell.json")
    manifest = json.loads((v4 / "textures/rigid_materials.json").read_text(encoding="utf-8"))
    for files in manifest.values():
        for f in files.values():
            shutil.copy2(v4 / "textures" / f, RIGID / "textures" / f)
    manifest["V5d helmet"] = {"albedo": "v5d_helmet_albedo.png", "normal": "v5d_helmet_normal.png",
                              "gloss": "v5d_helmet_specgloss.png"}
    (RIGID / "textures/rigid_materials.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("RIGID exported")


pack_suit_maps()
export_suit()
export_rigid()
print("ALL DONE")
