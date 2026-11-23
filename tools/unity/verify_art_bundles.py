"""Audit delivered bundles with the 2022.3.43f1 native reader and installed EFT dependencies.

Run with Windows Python, lz4 and the Unity editor toolset installed. The game is read-only.
"""
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path
from uuid import uuid4

import lz4.block
import numpy as np
import unityfs
from build_rigid_bundles import REDUT_SHADER_ID, TEXTURE_SLOTS
from suit_serial_file import SerializedFile, read_string


ROOT = Path(__file__).resolve().parents[2]
EFT = Path("C:/SPT41/EscapeFromTarkov_Data/StreamingAssets/Windows")
TOOLS = Path("C:/Program Files/Unity/Hub/Editor/2022.3.43f1/Editor/Data/Tools")
NATIVE_DIR = ROOT / "art/build/native"
VERSION = "2022.3.43f1"
FOLDER = "assets/content/items/equipment/juggernaut"
ITEMS = ("item_equipment_juggernaut_suit", "item_equipment_juggernaut_helmet",
         "item_juggernaut_thermal_module", "item_juggernaut_power_cell")
COMMON = ("shaders", "cubemaps", "assets/commonassets/physics/physicsmaterials.bundle")
POINTER = re.compile(r"m_FileID (-?\d+) \(int\)\s+m_PathID (-?\d+) \(SInt64\)")


def cstring(f):
    value = bytearray()
    while True:
        ch = f.read(1)
        if not ch:
            raise EOFError("unterminated UnityFS header")
        if ch == b"\0":
            return value.decode()
        value += ch


def inflate(data, size, flags):
    if flags & 63 in (2, 3):
        return lz4.block.decompress(data, uncompressed_size=size)
    return unityfs.decomp(data, flags, size)


def game_index(path):
    """Read only the first CAB's object table, even for the large global shaders bundle."""
    with path.open("rb") as f:
        assert cstring(f) == "UnityFS"
        version, = struct.unpack(">I", f.read(4))
        cstring(f)
        assert cstring(f) == VERSION
        total, compressed, size, flags = struct.unpack(">qIII", f.read(20))
        if version >= 7:
            f.seek((f.tell() + 15) & ~15)
        start = f.tell()
        if flags & 128:
            f.seek(total - compressed)
        info = inflate(f.read(compressed), size, flags)
        start = start if flags & 128 else start + compressed
        f.seek((start + 15) & ~15 if flags & 512 else start)
        count, = struct.unpack_from(">i", info, 16)
        blocks = list(struct.iter_unpack(">IIH", info[20:20 + count * 10]))
        offset = 20 + count * 10
        node_count, = struct.unpack_from(">i", info, offset)
        offset += 4
        nodes = []
        for _ in range(node_count):
            pos, length, _ = struct.unpack_from(">qqI", info, offset)
            name, offset = unityfs.cstr(info, offset + 20)
            nodes.append((name, pos, length))
        name, pos, _ = next(node for node in nodes if "." not in node[0])
        buf = bytearray()
        end = None
        for rawsize, compsize, mode in blocks:
            buf.extend(inflate(f.read(compsize), rawsize, mode))
            if end is None and len(buf) >= pos + 48:
                end = pos + struct.unpack_from(">q", buf, pos + 32)[0]
            if end is not None and len(buf) >= end:
                break
        sf = unityfs.SF(bytes(buf[pos:end]))
        assert sf.ver == VERSION
        return name, {obj["pathID"]: obj["classID"] for obj in sf.objects}


def field(s, name):
    return re.search(r'^\s*' + re.escape(name) + r' "([^"]*)" \(string\)', s, re.M).group(1)


def verify(path, game, tools, native_dir=NATIVE_DIR):
    meta, nodes = unityfs.read_bundle(path)
    assert meta["engine"] == VERSION, meta
    cab, = [name for name in nodes if "." not in name]
    sf = unityfs.SF(nodes[cab])
    assert sf.ver == VERSION and sf.platform == 19, (sf.ver, sf.platform)
    native_dir.mkdir(parents=True, exist_ok=True)
    scratch = native_dir / ("extract-" + uuid4().hex)
    scratch.mkdir()
    source = scratch / path.name
    extracted = scratch / (path.name + "_data")
    dump = native_dir / (path.stem + ".txt")
    try:
        shutil.copyfile(path, source)
        result = subprocess.run([str(tools / "WebExtract.exe"), str(source)],
                                check=True, capture_output=True)
        assert b"All ok!" in result.stdout + result.stderr
        assert {f.name for f in extracted.iterdir()} == set(nodes)
        for name, payload in nodes.items():
            assert (extracted / name).read_bytes() == payload
        subprocess.run([str(tools / "binary2text.exe"), str(extracted / cab), str(dump),
                        "-largebinaryhashonly"], check=True, capture_output=True)
        native = dump.read_text(encoding="utf-8", errors="replace")
    finally:
        for name in nodes:
            (extracted / name).unlink(missing_ok=True)
        if extracted.exists():
            extracted.rmdir()
        source.unlink(missing_ok=True)
        scratch.rmdir()
    records = re.split(r"^ID: (-?\d+) \(ClassID: (\d+)\) ([^\n]+)\n", native, flags=re.M)[1:]
    objects = {int(pid): (int(cid), body) for pid, cid, _, body in zip(*[iter(records)] * 4)}
    assert {k: v[0] for k, v in objects.items()} == {o["pathID"]: o["classID"] for o in sf.objects}
    external = [line.split("/")[-1] for line in sf.externals]
    assert set(external) <= game.keys(), external
    scripts, meshes, parts = [], {}, []
    materials = {}
    shader_bindings = {}
    suit = path.stem == ITEMS[0]
    texture_encodings = {
        "_MainTex": (10, 1), "_BumpMap": (12, 0), "_SpecMap": (10, 0),
    } if suit else {prop: (fmt, color) for prop, (_, fmt, color) in TEXTURE_SLOTS.items()}
    pointers = 0
    for pid, (cid, body) in objects.items():
        for file_id, target in POINTER.findall(body):
            file_id, target = int(file_id), int(target)
            if file_id or target:
                table = objects if not file_id else game[external[file_id - 1]][1]
                assert target in table, (path.name, pid, file_id, target)
                pointers += 1
        for start, size, resource in re.findall(
                r'offset (\d+) [^\n]+\n\s*size (\d+) [^\n]+\n\s*path "([^"]+)"', body):
            assert resource.split("/")[-1] in nodes, resource
            assert int(start) + int(size) <= len(nodes[resource.split("/")[-1]])
        if cid == 115:
            scripts.append(".".join(filter(None, (field(body, "m_Namespace"), field(body, "m_ClassName")))))
        if cid == 1:
            parts.append(field(body, "m_Name"))
        if cid == 21:
            slots = {}
            material = field(body, "m_Name")
            shader = re.search(r'm_Shader  \(PPtr<Shader>\)\s+' + POINTER.pattern, body)
            assert shader and 0 < int(shader[1]) <= len(external), (path.name, material)
            shader_key, shader_objects = game[external[int(shader[1]) - 1]]
            shader_id = int(shader[2])
            assert shader_key == "shaders" and shader_id == REDUT_SHADER_ID, (path.name, material, shader_id)
            assert shader_objects[shader_id] == 48
            shader_bindings[material] = {"dependencyKey": shader_key, "pathID": shader_id}
            for prop, encoding in texture_encodings.items():
                ref = re.search(r'first "' + prop + r'" \(string\)\s+second  \(UnityTexEnv\)\s+'
                                r'm_Texture  \(PPtr<Texture>\)\s+' + POINTER.pattern, body)
                assert ref and int(ref[1]) == 0 and int(ref[2]), (path.name, prop)
                kind, description = objects[int(ref[2])]
                assert kind == 28
                values = {k: int(re.search(r'^\s*m_' + k + r' (\d+) ', description, re.M)[1])
                          for k in ("Width", "Height", "MipCount", "TextureFormat", "ColorSpace")}
                size = values["Width"]
                assert size == values["Height"] and size in ({4096} if suit else {512, 1024})
                assert values["MipCount"] == size.bit_length(), (path.name, prop, values)
                assert (values["TextureFormat"], values["ColorSpace"]) == encoding, (path.name, prop, values)
                slots[prop] = dict(name=field(description, "m_Name"), **values)
            materials[material] = slots
        if cid == 43:
            tris = sum(map(int, re.findall(r"^\s*indexCount (\d+)", body, re.M))) // 3
            assert tris > 0
            meshes[field(body, "m_Name")] = tris
        if cid == 142:
            bundle = field(body, "m_AssetBundleName")
            prefab = re.search(r'm_Container .*?first "([^"]+)".*?asset  \(PPtr<Object>\)\s*'
                               r'm_FileID 0 \(int\)\s*m_PathID (-?\d+)', body, re.S)
            assert prefab and objects[int(prefab[2])][0] == 1
            prefab = prefab[1]
            dep_section = re.search(r'm_Dependencies  \(vector\)(.*?)\n\s*m_IsStreamedSceneAssetBundle', body, re.S)
            deps = re.findall(r'data "([^"]+)"', dep_section[1])
    assert bundle == f"{FOLDER}/{path.name}"
    assert prefab == bundle.removesuffix(".bundle") + ".prefab"
    assert set(deps) == {game[name][0] for name in external}, (external, deps)
    if "suit" in path.name:
        assert {"Skin", "Loot"} <= set(parts)
        assert {"DressItem", "PreviewPivot", "EFT.Visual.SkinDress", "Diz.Skinning.Skin"} <= set(scripts)
        assert len(meshes) == 4
    elif "helmet" in path.name:
        assert {"mod_nvg", "mod_equipment_001"} <= set(parts)
    elif "thermal" in path.name:
        assert set(scripts) == {"EFT.Visual.Dress", "PreviewPivot"}
        assert all("juggernaut" in field(body, "m_Name").lower()
                   for cid, body in objects.values() if cid == 21)
        assert not any(cid == 48 for cid, _ in objects.values()), "unexpected embedded shader"
    assert materials, (path.name, "missing materials")
    return dict(key=bundle, prefab=prefab, dependencyKeys=deps, cab=cab, materials=materials,
                shaderBindings=shader_bindings,
                objects=len(objects), resolvedPointers=pointers, scripts=sorted(scripts),
                gameObjects=parts, meshes=meshes, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


class MountedItem:
    """Read local transforms and draw-vertex positions from the packed rigid meshes."""
    def __init__(self, path):
        _, files = unityfs.read_bundle(path)
        self.sf = SerializedFile(next(data for key, data in files.items() if "." not in key))
        self.transforms = {}
        self.names = {}
        for record in self.sf.records.values():
            if self.sf.class_id(record) == 4:
                f = self.sf.fields(record)
                owner = self.ptr(f["m_GameObject"])
                obj = self.sf.fields(self.sf.records[owner])
                self.names[read_string(obj["m_Name"])[0]] = owner
                self.transforms[owner] = f

    @staticmethod
    def ptr(raw):
        fid, pid = struct.unpack("<iq", raw)
        assert not fid
        return pid

    def matrix(self, name):
        f = self.transforms[self.names[name]]
        matrix = np.eye(4)
        x, y, z, w = struct.unpack("<4f", f["m_LocalRotation"])
        xyz = np.array([x, y, z])
        skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
        rot = (w*w - xyz @ xyz) * np.eye(3) + 2*np.outer(xyz, xyz) + 2*w*skew
        matrix[:3, :3] = rot @ np.diag(struct.unpack("<3f", f["m_LocalScale"]))
        matrix[:3, 3] = struct.unpack("<3f", f["m_LocalPosition"])
        return matrix

    def lod(self, name):
        sf = self.sf
        filters = [sf.fields(record) for record in sf.records.values() if sf.class_id(record) == 33]
        mesh_ref, = [f["m_Mesh"] for f in filters if self.ptr(f["m_GameObject"]) == self.names[name]]
        mesh = sf.fields(sf.records[self.ptr(mesh_ref)])
        data = mesh["m_VertexData"]
        count, channels = struct.unpack_from("<II", data)
        start = 8 + channels * 4 + 4
        raw = np.frombuffer(data, "<f4", count * 12, start).reshape(count, 12)
        points = np.column_stack((raw[:, :3], np.ones(count)))
        return (self.matrix(name) @ points.T).T

    def prefab_layout(self):
        """Extract integration-relevant state independently of meshes, materials and CAB IDs."""
        sf = self.sf
        parents = {}
        names = {}
        for owner, transform in self.transforms.items():
            names[owner] = read_string(sf.fields(sf.records[owner])["m_Name"])[0]
            parent = self.ptr(transform["m_Father"])
            parents[owner] = self.ptr(sf.fields(sf.records[parent])["m_GameObject"]) if parent else None

        def path(owner):
            return (path(parents[owner]) + "/" if parents[owner] is not None else "") + names[owner]

        layout = {}
        for owner, transform in self.transforms.items():
            fields = sf.fields(sf.records[owner])
            row = {"layer": struct.unpack("<I", fields["m_Layer"])[0], "active": bool(fields["m_IsActive"][0]),
                   "components": []}
            for _, component_id in struct.iter_unpack("<iq", fields["m_Component"][4:]):
                component = sf.records[component_id]
                kind = sf.class_id(component)
                entry = {"classID": kind}
                if kind == 114:
                    script = sf.records[self.ptr(sf.fields(component)["m_Script"])]
                    desc = sf.fields(script)
                    entry["script"] = ".".join(filter(None, (read_string(desc[k])[0]
                                              for k in ("m_Namespace", "m_ClassName"))))
                if kind == 205:
                    data = sf.fields(component)["m_LODs"]
                    count, = struct.unpack_from("<i", data)
                    offset = 4
                    levels = []
                    for _ in range(count):
                        height, fade, renderers = struct.unpack_from("<ffi", data, offset)
                        offset += 12
                        targets = []
                        for _ in range(renderers):
                            target = sf.records[self.ptr(data[offset:offset + 12])]
                            targets.append(path(self.ptr(sf.fields(target)["m_GameObject"])))
                            offset += 12
                        levels.append(dict(height=height, fade=fade, renderers=targets))
                    assert offset == len(data)
                    entry["levels"] = levels
                row["components"].append(entry)
            if names[owner].startswith("mod_"):
                for key, fmt in (("m_LocalPosition", "<3f"), ("m_LocalRotation", "<4f"), ("m_LocalScale", "<3f")):
                    row[key] = list(struct.unpack(fmt, transform[key]))
            node = path(owner)
            if node in layout:
                raise ValueError(f"Ambiguous prefab path {node}")
            layout[node] = row
        return layout


def check_attachment_frames(directory):
    suit, helmet, thermal, cell = [MountedItem(directory / (n + ".bundle")) for n in ITEMS]
    # ContainerCollectionView.SlotView.InsertItem in EFT 40743, for items without ModPlacer.
    insert = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
    anchor = np.asarray(json.loads((ROOT / "art/rigid/bundle_stats.json").read_text())["headAnchor"])

    def authored(kind):
        source = json.loads((ROOT / f"art/accessories/{kind}.json").read_text())
        return np.array([[p[a] for a in "xyz"] for part in source["meshes"] for p in part["positions"]])

    # Suit mesh axes are Blender (-X,Y,Z). The cell indicator faces aft in its dock.
    target = authored("cell") * [1, -1, 1] + [0, .2695, 1.28075]
    actual = (suit.matrix("mod_power_cell") @ insert @ cell.lod(ITEMS[3] + "_LOD0").T).T[:, :3]
    cell_error = np.linalg.norm(actual - target, axis=1).max()
    thermal_pose = helmet.matrix("mod_nvg") @ insert
    actual = (thermal_pose @ thermal.lod(ITEMS[2] + "_LOD0").T).T[:, :3]
    authored_pod = authored("thermal") - anchor
    target = authored_pod[:, [0, 2, 1]] * [-1, 1, -1]
    thermal_error = np.linalg.norm(actual - target, axis=1).max()
    assert max(cell_error, thermal_error) < 2e-6, (cell_error, thermal_error)
    return float(cell_error), float(thermal_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eft", type=Path, default=EFT)
    parser.add_argument("--tools", type=Path, default=TOOLS)
    parser.add_argument("--bundles", type=Path, default=ROOT / "server/bundles" / FOLDER)
    parser.add_argument("--output", type=Path, default=ROOT / "art/build/bundle-audit.json")
    parser.add_argument("--native-dir", type=Path, default=NATIVE_DIR, help="Directory for binary2text dumps.")
    parser.add_argument("--compare-layout", type=Path, help="Compare hierarchy, components, LODs and mounts with a prior audit.")
    args = parser.parse_args()
    game = {}
    for key in COMMON:
        cab, objects = game_index(args.eft / key)
        game[cab] = (key, objects)
    items = [verify(args.bundles / (name + ".bundle"), game, args.tools, args.native_dir) for name in ITEMS]
    previous = {row["key"]: row for row in json.loads(args.compare_layout.read_text(encoding="utf-8-sig"))} if args.compare_layout else {}
    for row in items:
        row["layout"] = MountedItem(args.bundles / Path(row["key"]).name).prefab_layout()
        if previous:
            for key in ("prefab", "dependencyKeys", "layout"):
                if row[key] != previous[row["key"]][key]:
                    raise ValueError(f"{row['key']} changed {key} from {args.compare_layout}")
            row["matchesPriorLayout"] = True
    cell_error, thermal_error = check_attachment_frames(args.bundles)
    items[2]["mountedVertexMaxErrorMetres"] = thermal_error
    items[3]["mountedVertexMaxErrorMetres"] = cell_error
    assert len({row["cab"] for row in items}) == len(items)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(items, indent=2), encoding="utf-8")
    for row in items:
        print(row["key"], row["objects"], "objects,", row["resolvedPointers"], "resolved pointers")


if __name__ == "__main__":
    main()
