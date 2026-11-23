"""Repack original static Juggernaut meshes into local EFT 40743 donor prefab structures."""
import argparse
import hashlib
from io import BytesIO
import json
from math import cos, radians, sin, sqrt
from pathlib import Path
import struct

from PIL import Image

from suit_serial_file import Record, SerializedFile, array, pptr, read_string, string, unityfs
from suit_serial_mesh import mesh_updates


ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = "assets/content/items/equipment/juggernaut"
DONORS = {
    "helmet": "item_equipment_helmet_vulkan_5",
    "thermal": "nvg_wilcox_pvs7_adapter",
    "cell": "item_barter_energy_powerbank",
}
OUTPUTS = {
    "helmet": "item_equipment_juggernaut_helmet",
    "thermal": "item_juggernaut_thermal_module",
    "cell": "item_juggernaut_power_cell",
}
FAST_MOUNT_DONOR = "item_equipment_helmet_hops_core_fast"
SURFACE_DONOR = "item_equipment_armor_redut_t5"
REDUT_SHADER_ID = 5560642222599436764
TEXTURE_SLOTS = {
    "_MainTex": ("albedo", 12, 1),
    "_BumpMap": ("normal", 12, 0),
    "_SpecMap": ("gloss", 10, 1),
}
COMPONENTS = {4, 23, 33, 64, 65, 114, 205}
DEPENDENCY_KEYS = {
    "cab-56d919bd5479d38f741da52a6beef92f": "shaders",
    "cab-4d8a4131cf377709ee7c7e960f65d349": "cubemaps",
    "cab-c4ae8b769ad32b6f6553d77ccc5aff87": "assets/commonassets/physics/physicsmaterials.bundle",
}
HEAD_ANCHOR = (-.00062798, .02180314, 1.65807902)
ATTACHED_ROOT_X90 = (sqrt(.5), 0, 0, sqrt(.5))
RAC_OFFSET = (0, .005, -.045)
RAC_PITCH = radians(16)
RAC_X_SCALE = 1.26


def records(sf, class_id):
    return [r for r in sf.records.values() if sf.class_id(r) == class_id]


def one(iterable):
    (value,) = iterable
    return value


def local_id(data):
    file_id, path_id = struct.unpack("<iq", data)
    if file_id:
        raise ValueError(f"expected local reference, got {file_id}:{path_id}")
    return path_id


def pointers(field):
    count, = struct.unpack_from("<i", field)
    if len(field) != 4 + count * 12:
        raise ValueError("wrong PPtr array size")
    return [field[4 + i * 12:16 + i * 12] for i in range(count)]


def ref_array(ids):
    ids = list(ids)
    return array(len(ids), b"".join(pptr(0, path_id) for path_id in ids))


def integers(data):
    return struct.unpack(f"<{len(data) // 4}i", data)


def floats(data):
    return struct.unpack(f"<{len(data) // 4}f", data)


def float_bytes(*args):
    return struct.pack(f"<{len(args)}f", *args)


def load_donor(game, stem):
    source = one(game.glob(f"assets/content/items/**/{stem}.bundle"))
    meta, files = unityfs.read_bundle(source)
    cab = one(name for name, flags in meta["nodes"] if flags == 4)
    sf = SerializedFile(files[cab])
    if sf.version != "2022.3.43f1":
        raise ValueError(f"{source} built with {sf.version}")
    return sf, meta


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_texture(sf, record, path, stem, slot):
    channel, format_id, colorspace = TEXTURE_SLOTS[slot]
    with Image.open(path) as source:
        image = source.convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    width, height = image.size
    if width != height or width < 512 or width & (width - 1):
        raise ValueError(f"{path}: expected a square power-of-two texture at least 512 pixels wide")
    pixels = bytearray()
    while True:
        if channel == "normal":
            # Unity DXT5nm stores tangent X in alpha and tangent Y in green.
            x, y, _, _ = image.split()
            normal_red = Image.new("L", image.size, 255)
            bitmap = Image.merge("RGBA", (normal_red, y, y, x))
        else:
            bitmap = image.convert("RGB") if format_id == 10 else image
        buffer = BytesIO()
        bitmap.save(buffer, "DDS", pixel_format="DXT1" if format_id == 10 else "DXT5")
        payload = buffer.getvalue()[128:]
        blocks = ((image.width + 3) // 4) * ((image.height + 3) // 4)
        if len(payload) != blocks * (8 if format_id == 10 else 16):
            raise ValueError(f"{path}: invalid DXT payload at {image.size}")
        pixels.extend(payload)
        if image.width == 1:
            break
        half_size = (image.width // 2, image.height // 2)
        # Alpha carries gloss, so downsample independently from the albedo.
        image = Image.merge("RGBA", tuple(band.resize(half_size, Image.Resampling.BOX) for band in image.split()))
    sf.replace_fields(record, {
        "m_Name": string(stem),
        "m_Width": struct.pack("<i", width),
        "m_Height": struct.pack("<i", height),
        "m_CompleteImageSize": struct.pack("<I", len(pixels)),
        "m_MipsStripped": bytes(4),
        "m_TextureFormat": struct.pack("<i", format_id),
        "m_MipCount": struct.pack("<i", width.bit_length()),
        "m_IsReadable": b"\x01",
        "m_StreamingMipmaps": bytes(4),
        "m_StreamingMipmapsPriority": bytes(4),
        "m_LightmapFormat": bytes(4),
        "m_ColorSpace": struct.pack("<i", colorspace),
        "m_PlatformBlob": bytes(4),
        "image data": array(len(pixels), pixels),
        "m_StreamData": bytes(16),
    })


def split_maps(data):
    offset = 0
    for size in (28, 4, 4, 16):
        count, = struct.unpack_from("<i", data, offset)
        offset += 4
        pairs = {}
        for _ in range(count):
            key, offset = read_string(data, offset)
            pairs[key] = data[offset:offset + size]
            offset += size
        yield pairs
    if offset != len(data):
        raise ValueError("material property sheet has trailing data")


def remap_external(source, target, reference):
    file_id, path_id = struct.unpack("<iq", reference)
    if file_id <= 0:
        raise ValueError("expected a shared asset reference")
    cab = read_external_names(source)[file_id - 1]
    return pptr(read_external_names(target).index(cab) + 1, path_id)


def make_material(sf, record, textures, spec, stem, redut):
    source = redut.fields(one(records(redut, 21)))
    tex, ints, props, colors = split_maps(source["m_SavedProperties"])
    cube = tex["_Cube"]
    tex["_Cube"] = remap_external(redut, sf, cube[:12]) + cube[12:]
    for slot, path_id in textures.items():
        tex[slot] = pptr(0, path_id) + float_bytes(1, 1, 0, 0)
    for key in ("USEHEAT", "_HasTint", "_HeatTemp", "_SkinnedMeshMaterial", "_StencilType", "_USERAIN"):
        if key in props:
            props[key] = bytes(4)
    smoothness = spec["smoothness"]
    metallic = spec["metallic"]
    props["_Glossness"] = float_bytes(.68 + .54 * smoothness)
    props["_Specularness"] = float_bytes(.39 + .40 * metallic)
    colors["_Color"] = float_bytes(1, 1, 1, 1)
    colors["_BaseTintColor"] = float_bytes(1, 1, 1, 1)
    colors["_ReflectColor"] = float_bytes(.36, .39, .42, .16 + .28 * metallic)
    sf.replace_fields(record, {
        "m_Name": string(stem),
        "m_Shader": remap_external(redut, sf, source["m_Shader"]),
        "m_ValidKeywords": bytes(4),
        "m_InvalidKeywords": bytes(4),
        "m_SavedProperties": b"".join(
            array(len(mapping), b"".join(string(k) + v for k, v in mapping.items()))
            for mapping in (tex, ints, props, colors)
        ),
    })


def rotate(v, q):
    x, y, z = v
    qx, qy, qz, qw = q
    scale = 2 / sum(c * c for c in q)
    tx, ty, tz = scale * (qy * z - qz * y), scale * (qz * x - qx * z), scale * (qx * y - qy * x)
    return (x + qw * tx + qy * tz - qz * ty,
            y + qw * ty + qz * tx - qx * tz,
            z + qw * tz + qx * ty - qy * tx)


def compose_rotation(parent, child):
    ax, ay, az, aw = parent
    bx, by, bz, bw = child
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def inverse_transform(point, loc, rot, normal=False):
    if not normal:
        point = tuple(x - y for x, y in zip(point, loc))
    return rotate(point, (-rot[0], -rot[1], -rot[2], rot[3]))


def vector(obj):
    return tuple(obj[k] for k in "xyz")


def blender_to_unity(obj, anchor, normal=False):
    x, y, z = vector(obj)
    if not normal:
        x, y, z = x - anchor[0], y - anchor[1], z - anchor[2]
    return (-x, z, -y)


def unity_geometry(source, anchor, transform, mount=None):
    loc, rot = transform
    positions = []
    normals = []
    uv = []
    triangles = []
    grouped = {}
    for part in source["meshes"]:
        offset = len(positions) // 3
        for field, values, normal in (("positions", positions, False), ("normals", normals, True)):
            for p in part[field]:
                point = blender_to_unity(p, anchor, normal)
                if mount:
                    point = inverse_transform(point, *mount, normal=normal)
                values.extend(inverse_transform(point, loc, rot, normal=normal))
        for p in part["uv"]:
            uv.extend((p["x"], p["y"]))
        for submesh in part["submeshes"]:
            indices = submesh["indices"]
            destination = grouped.setdefault(submesh["material"], [])
            for i in range(0, len(indices), 3):
                a, b, c = indices[i:i + 3]
                destination.extend((a + offset, c + offset, b + offset))
    materials = sorted(grouped)
    sizes = []
    for m in materials:
        if grouped[m]:
            sizes.append(len(grouped[m]))
            triangles.extend(grouped[m])
    materials = [m for m in materials if grouped[m]]
    return {"v": positions, "n": normals, "uv": uv, "t": triangles}, sizes, materials


def bounds(flat):
    columns = [flat[i::3] for i in range(3)]
    mins, maxs = [min(c) for c in columns], [max(c) for c in columns]
    return tuple((a + b) / 2 for a, b in zip(mins, maxs)), tuple(b - a for a, b in zip(mins, maxs))


def collider_geometry(center, size):
    corners = [[center[i] + size[i] / 2 * (1 if (index & (1 << i)) else -1)
                for i in range(3)] for index in range(8)]
    faces = [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
             (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]
    directions = [(-1, 0, 0), (1, 0, 0), (0, -1, 0),
                  (0, 1, 0), (0, 0, -1), (0, 0, 1)]
    geom = dict(v=[], n=[], uv=[], t=[])
    for face, normal in zip(faces, directions):
        start = len(geom["v"]) // 3
        for vertex in face:
            geom["v"].extend(corners[vertex])
            geom["n"].extend(normal)
        geom["uv"].extend((0, 0, 1, 0, 1, 1, 0, 1))
        geom["t"].extend(start + i for i in (0, 2, 1, 0, 3, 2))
    return geom


class Prefab:
    def __init__(self, sf):
        self.sf = sf
        self.gameobjects = {self.name(r): r for r in records(sf, 1)}
        self.transforms = {self.owner(r).path_id: r for r in records(sf, 4)}
        self.root = one(r for r in records(sf, 4) if self.sf.fields(r)["m_Father"] == pptr(0, 0))
        self.root_go = self.owner(self.root)
        self.next_id = max(r for r in sf.records if 0 < r < 8000000000000000000) + 1

    def name(self, record):
        return read_string(self.sf.fields(record)["m_Name"])[0]

    def owner(self, component):
        return self.sf.records[local_id(self.sf.fields(component)["m_GameObject"])]

    def components(self, gameobject):
        return [self.sf.records[local_id(p)] for p in pointers(self.sf.fields(gameobject)["m_Component"])]

    def transform(self, record):
        fields = self.sf.fields(record)
        return floats(fields["m_LocalPosition"]), floats(fields["m_LocalRotation"])

    def update(self, record, **changes):
        self.sf.replace_fields(record, changes)

    def clone(self, template):
        while self.next_id in self.sf.records:
            self.next_id += 1
        new = Record(self.next_id, template.type_index, template.data)
        self.sf.records[new.path_id] = new
        self.next_id += 1
        return new

    def detach_children(self, transform, keep):
        self.update(transform, m_Children=ref_array(r.path_id for r in keep))

    def set_scripts(self):
        scripts = {s.path_id: self.name(s) for s in records(self.sf, 115)}
        allowed = {"PreviewPivot", "Dress"}
        keep = {s.path_id for s in records(self.sf, 114)
                if scripts[local_id(self.sf.fields(s)["m_Script"])] in allowed}
        for obj in records(self.sf, 1):
            components = [r.path_id for r in self.components(obj)
                          if self.sf.class_id(r) != 114 or r.path_id in keep]
            self.update(obj, m_Component=ref_array(components))

    def mount(self, fast, mount_name, slot_template, reuse=False):
        source = fast.gameobjects[mount_name]
        src = fast.sf.fields(fast.transforms[source.path_id])
        gameobject = slot_template if reuse else self.clone(slot_template)
        transform = self.transforms[slot_template.path_id]
        transform = transform if reuse else self.clone(transform)
        self.update(gameobject, m_Name=string(mount_name), m_Component=ref_array([transform.path_id]))
        self.update(transform, m_GameObject=pptr(0, gameobject.path_id),
                    m_Father=pptr(0, self.root.path_id),
                    m_LocalPosition=src["m_LocalPosition"], m_LocalRotation=src["m_LocalRotation"],
                    m_LocalScale=src["m_LocalScale"], m_Children=bytes(4))
        self.transforms[gameobject.path_id] = transform
        return transform


def fit_rac_mount(prefab, transform):
    position, rotation = prefab.transform(transform)
    pitch_rotation = (sin(RAC_PITCH / 2), 0, 0, cos(RAC_PITCH / 2))
    fitted = tuple(coord + offset for coord, offset in zip(position, RAC_OFFSET))
    rotation = compose_rotation(rotation, pitch_rotation)
    prefab.update(transform, m_LocalPosition=float_bytes(*fitted),
                  m_LocalRotation=float_bytes(*rotation), m_LocalScale=float_bytes(RAC_X_SCALE, 1, 1))


def replace_hierarchy(p, kind, stem, fast):
    sf = p.sf
    p.set_scripts()
    renderer = records(sf, 23)
    renderer.sort(key=lambda r: p.name(p.owner(r)).lower())
    children = [p.transforms[p.owner(r).path_id] for r in renderer]
    if kind == "helmet":
        slot = p.gameobjects["mod_equipment"]
        rac = p.mount(fast, "mod_equipment_001", slot, reuse=True)
        fit_rac_mount(p, rac)
        nvg = p.mount(fast, "mod_nvg", slot)
        children.extend((rac, nvg))
    if kind == "cell":
        children.append(p.transforms[p.gameobjects["collider"].path_id])
    p.detach_children(p.root, children)
    p.update(p.root_go, m_Name=string(stem))
    for i, r in enumerate(renderer):
        p.update(p.owner(r), m_Name=string(f"{stem}_LOD{i}"))
    return renderer


def package(p, stem, meta, target):
    sf = p.sf
    container = one(records(sf, 142))
    fields = sf.fields(container)
    # Prune omitted model parts, vanilla textures, extra scripts, and streamed data.
    used = {container.path_id}
    queue = [p.root_go.path_id]
    reference_fields = {"m_GameObject", "m_Father", "m_Shader", "m_Script", "m_Mesh",
                        "m_Material", "m_StaticBatchRoot", "m_ProbeAnchor",
                        "m_LightProbeVolumeOverride", "m_AdditionalVertexStreams",
                        "m_EnlightenVertexStream"}
    reference_arrays = {"m_Component", "m_Children", "m_Materials", "Renderers"}
    externals = set()
    while queue:
        path_id = queue.pop()
        if not path_id or path_id in used:
            continue
        used.add(path_id)
        r = sf.records[path_id]
        fields_r = sf.fields(r)
        refs = []
        for key, field in fields_r.items():
            if key in reference_fields:
                refs.append(field)
            if key in reference_arrays:
                refs.extend(pointers(field))
            if key == "m_SavedProperties":
                tex, *_ = split_maps(field)
                refs.extend(v[:12] for v in tex.values())
        for ref in refs:
            file_id, target_id = struct.unpack("<iq", ref)
            if file_id:
                externals.add(ref)
            else:
                queue.append(target_id)
    sf.records = {pid: r for pid, r in sf.records.items() if pid in used}
    # The donor externals are the common shaders, cubemaps and physic materials.
    external_names = read_external_names(sf)
    if set(external_names) != DEPENDENCY_KEYS.keys():
        raise ValueError(f"unexpected donor external dependencies: {external_names}")
    key = f"{ASSET_DIR}/{stem}.bundle"
    asset = f"{ASSET_DIR}/{stem}.prefab"
    dependencies = [DEPENDENCY_KEYS[name] for name in external_names]
    preload = [pptr(0, pid) for pid in sorted(used - {container.path_id})] + sorted(externals)
    p.update(container, m_Name=string(key), m_AssetBundleName=string(key),
             m_PreloadTable=array(len(preload), b"".join(preload)),
             m_Dependencies=array(len(dependencies), b"".join(map(string, dependencies))),
             m_Container=array(1, string(asset) + struct.pack("<ii", 0, len(preload)) + pptr(0, p.root_go.path_id)))
    payload = sf.pack()
    cab = "CAB-" + hashlib.sha256(payload).hexdigest()[:32]
    meta = {**meta, "nodes": [(cab, 4)]}
    output = ensure_dir(target) / f"{stem}.bundle"
    unityfs.write_bundle(output, meta, {cab: payload})
    actual_meta, actual_files = unityfs.read_bundle(output)
    actual = SerializedFile(actual_files[actual_meta["nodes"][0][0]])
    if len(actual.records) != len(sf.records):
        raise RuntimeError("reopened bundle has an unexpected record count")
    for pid, r in actual.records.items():
        if r.data != sf.records[pid].data:
            raise RuntimeError(f"reopened serialized record {pid} differs")
        actual.fields(r)
    texture_sets = verify_surfaces(actual)
    return {"filename": output.name, "prefabAsset": asset, "bundleKey": key,
            "dependencies": dependencies,
            "cab": cab, "serializedObjects": len(actual.records),
            "materials": texture_sets,
            "scripts": sorted(read_string(actual.fields(r)["m_Name"])[0]
                              for r in records(actual, 115)),
            "boxColliders": len(records(actual, 65)),
            "meshColliders": len(records(actual, 64))}


def read_external_names(sf):
    raw = sf.suffix
    offset = 4 + 12 * struct.unpack_from("<i", raw)[0]
    count, = struct.unpack_from("<i", raw, offset)
    offset += 4
    names = []
    for _ in range(count):
        _, offset = unityfs.cstr(raw, offset)
        path, offset = unityfs.cstr(raw, offset + 20)
        names.append(path.split("/")[-1].lower())
    return names


def verify_surfaces(sf):
    dependencies = read_external_names(sf)
    result = {}
    for material in records(sf, 21):
        fields = sf.fields(material)
        name = read_string(fields["m_Name"])[0]
        textures, *_ = split_maps(fields["m_SavedProperties"])
        shader_file, shader_path = struct.unpack("<iq", fields["m_Shader"])
        if (not 0 < shader_file <= len(dependencies) or shader_path != REDUT_SHADER_ID
                or DEPENDENCY_KEYS[dependencies[shader_file - 1]] != "shaders"):
            raise ValueError(f"{name}: expected installed Redut reflective shader")
        cube_file, cube_path = struct.unpack("<iq", textures["_Cube"][:12])
        if (not 0 < cube_file <= len(dependencies) or not cube_path
                or DEPENDENCY_KEYS[dependencies[cube_file - 1]] != "cubemaps"):
            raise ValueError(f"{name}: expected shared cubemap")
        result[name] = {"shader": shader_path, "cube": cube_path, "maps": {}}
        for slot, (channel, expected_format, expected_space) in TEXTURE_SLOTS.items():
            path_id = local_id(textures[slot][:12])
            texture = sf.records[path_id]
            if sf.class_id(texture) != 28:
                raise ValueError(f"{name} {slot}: expected Texture2D")
            fields = sf.fields(texture)
            width, height, format_id, space, mips = [
                struct.unpack("<i", fields[key])[0] for key in
                ("m_Width", "m_Height", "m_TextureFormat", "m_ColorSpace", "m_MipCount")
            ]
            blocks = sum(max(1, ((width >> i) + 3) // 4) ** 2 for i in range(mips))
            byte_count, = struct.unpack("<i", fields["image data"][:4])
            if (format_id != expected_format or space != expected_space or width < 512
                    or width != height or mips != width.bit_length()
                    or (blocks * (8 if format_id == 10 else 16)) != byte_count
                    or fields["m_StreamData"] != bytes(16)):
                raise ValueError(f"{name} {slot}: texture dimensions, mip payload or encoding mismatch")
            result[name]["maps"][slot] = dict(channel=channel, id=path_id, width=width, height=height,
                                               format=format_id, mips=mips, bytes=byte_count)
    return result


def build(game, art, target, kind, fast, head_anchor, thermal_mount, redut, texture_root, manifest):
    donor, meta = load_donor(game, DONORS[kind])
    prefab = Prefab(donor)
    stem = OUTPUTS[kind]
    renderers = replace_hierarchy(prefab, kind, stem, fast)
    source = json.loads((art / f"{kind}.json").read_text(encoding="utf-8-sig"))
    source_lods = [source]
    lod1 = art / f"{kind}_lod1.json"
    if len(renderers) == 2:
        second = json.loads(lod1.read_text(encoding="utf-8-sig"))
        if [m["name"] for m in second["materials"]] != [m["name"] for m in source["materials"]]:
            raise ValueError(f"{lod1} must use the same material indices as LOD0")
        source_lods.append(second)
    base_material = one(records(donor, 21))
    donor_maps, *_ = split_maps(donor.fields(base_material)["m_SavedProperties"])
    templates = {slot: donor.records[local_id(donor_maps[slot][:12])] for slot in TEXTURE_SLOTS}
    materials = []
    for spec in source["materials"]:
        name = f"{stem}_{spec['name']}"
        mat = prefab.clone(base_material)
        texture_ids = {}
        for slot, (channel, _, _) in TEXTURE_SLOTS.items():
            texture = prefab.clone(templates[slot])
            filename = manifest[spec["name"]][channel]
            make_texture(donor, texture, texture_root / filename, f"{name}_{channel}", slot)
            texture_ids[slot] = texture.path_id
        make_material(donor, mat, texture_ids, spec, name, redut)
        materials.append(mat.path_id)
    result = []
    all_root_positions = []
    anchor = (0, 0, 0) if kind == "cell" else head_anchor
    mount = thermal_mount if kind == "thermal" else None
    for i, (renderer, lod) in enumerate(zip(renderers, source_lods, strict=True)):
        gameobject = prefab.owner(renderer)
        filters = [r for r in prefab.components(gameobject) if donor.class_id(r) == 33]
        mesh = donor.records[local_id(donor.fields(one(filters))["m_Mesh"])]
        transform = prefab.transform(prefab.transforms[gameobject.path_id])
        data, groups, material_indexes = unity_geometry(lod, anchor, transform, mount)
        mesh_name = f"{stem}_mesh_lod{i}"
        donor.replace_fields(mesh, mesh_updates(data, name=mesh_name, groups=groups))
        prefab.update(renderer, m_Materials=ref_array(materials[j] for j in material_indexes))
        loc, rot = transform
        for j in range(0, len(data["v"]), 3):
            all_root_positions.extend(x+y for x,y in zip(rotate(data["v"][j:j+3], rot), loc))
        center, size = bounds(data["v"])
        result.append({"lod": i, "triangles": len(data["t"]) // 3,
                       "vertices": len(data["v"]) // 3, "submeshes": len(groups)})
        for col in prefab.components(gameobject):
            if donor.class_id(col) == 65:
                prefab.update(col, m_Size=float_bytes(*size), m_Center=float_bytes(*center))
    root_center, root_size = bounds(all_root_positions)
    lod_group = one(records(donor, 205))
    prefab.update(lod_group, m_LocalReferencePoint=float_bytes(*root_center),
                  m_Size=float_bytes(max(root_size)))
    if kind == "cell":
        collision_obj = prefab.gameobjects["collider"]
        loc, rot = prefab.transform(prefab.transforms[collision_obj.path_id])
        converted = []
        for i in range(0, len(all_root_positions), 3):
            converted.extend(inverse_transform(all_root_positions[i:i+3], loc, rot))
        center, size = bounds(converted)
        associated = prefab.components(collision_obj)
        box = one(r for r in associated if donor.class_id(r) == 65)
        prefab.update(box, m_Size=float_bytes(*size), m_Center=float_bytes(*center))
        collider_filter = one(r for r in associated if donor.class_id(r) == 33)
        collider_mesh = donor.records[local_id(donor.fields(collider_filter)["m_Mesh"])]
        donor.replace_fields(collider_mesh, mesh_updates(collider_geometry(center, size),
                                                         name=f"{stem}_collider_mesh"))
        mesh_collider = one(records(donor, 64))
        prefab.update(mesh_collider, m_Mesh=pptr(0, collider_mesh.path_id))
    output = package(prefab, stem, meta, target)
    output.update(donor=DONORS[kind], lods=result, rootCenter=root_center, rootSize=root_size)
    return output


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--game", type=Path, default=Path(r"C:/SPT41/EscapeFromTarkov_Data/StreamingAssets/Windows"))
    arg.add_argument("--art", type=Path, default=ROOT / "art/accessories")
    arg.add_argument("--out", type=Path, default=ROOT / "art/build/rigid-v2-test")
    arg.add_argument("--textures", type=Path, help="Directory containing rigid_materials.json and the PNG maps")
    arg.add_argument("--evidence", type=Path, default=ROOT / "art/rigid/bundle_stats.json")
    arg.add_argument("--head-anchor", type=float, nargs=3, default=HEAD_ANCHOR,
                     help="Head pivot in the source Blender scene, measured from the EFT rest transforms.")
    args = arg.parse_args()
    fast = Prefab(load_donor(args.game, FAST_MOUNT_DONOR)[0])
    redut = load_donor(args.game, SURFACE_DONOR)[0]
    texture_root = args.textures or args.art / "textures"
    manifest = json.loads((texture_root / "rigid_materials.json").read_text(encoding="utf-8"))
    slot_position, slot_rotation = fast.transform(fast.transforms[fast.gameobjects["mod_nvg"].path_id])
    # EFT 40743 SlotView.InsertItem rotates the attached item root +90 degrees
    # about X for cosmetic parts without a ModPlacer. Leave the socket itself vanilla.
    attach_frame = (slot_position, compose_rotation(slot_rotation, ATTACHED_ROOT_X90))
    bundle_stats = {}
    for kind in DONORS:
        result = build(args.game, args.art, args.out, kind, fast, tuple(args.head_anchor), attach_frame,
                       redut, texture_root, manifest)
        bundle_stats[kind] = result
        print(f"{result['filename']}: {result['lods']}")
    helmet_meta, helmet_files = unityfs.read_bundle(args.out / f"{OUTPUTS['helmet']}.bundle")
    packed_helmet = Prefab(SerializedFile(helmet_files[helmet_meta["nodes"][0][0]]))
    slots = {}
    for name in ("mod_nvg", "mod_equipment_001"):
        part = packed_helmet.transforms[packed_helmet.gameobjects[name].path_id]
        loc, rot = packed_helmet.transform(part)
        slots[name] = {"position": loc, "rotation": rot,
                       "scale": floats(packed_helmet.sf.fields(part)["m_LocalScale"]),
                       "source": FAST_MOUNT_DONOR}
    ensure_dir(args.evidence.parent)
    args.evidence.write_text(json.dumps({"headAnchor": args.head_anchor, "slots": slots,
                                        "attachedRootRotation": ATTACHED_ROOT_X90,
                                        "bundles": bundle_stats}, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
