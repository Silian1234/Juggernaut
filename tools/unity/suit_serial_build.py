"""Package original Juggernaut suit art using the working EXO3 dress/loot template.

Usage:
  python tools/unity/suit_serial_build.py [--source EXO3.bundle] [--art art/suit]
  python tools/unity/suit_serial_build.py --verify-only

Requires NumPy and Pillow with DDS DXT encoding. Run from the project root.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from suit_serial_file import Record, SerializedFile, align, array, pptr, read_string, string, unityfs
from suit_serial_mesh import mesh_updates

NAME = "item_equipment_juggernaut_suit"
BUNDLE_KEY = f"assets/content/items/equipment/juggernaut/{NAME}.bundle"
PREFAB_KEY = BUNDLE_KEY.removesuffix(".bundle") + ".prefab"
SOURCE = Path(
    r"C:\SPT41\SPT_Runtime\user\mods\FullBodyArmor\bundles\assets\content\items\equipment"
    r"\exoskeleton\item_equipment_exoskeleton_t3.bundle"
)
ROOT_BONE = "Root_Joint/Base HumanPelvis"
EXPECTED_DEPENDENCIES = [
    "assets/commonassets/physics/physicsmaterials.bundle", "cubemaps", "shaders"
]
VERSION = "2022.3.43f1"
SLOT_NAME = "mod_power_cell"
SLOT_IDS = (7142348912569200140, 7142348912569200141)
SLOT_ORIGIN = (0, .2695, 1.28075)
SLOT_POSITION = struct.pack("<3f", *SLOT_ORIGIN)
# EFT SlotView.InsertItem gives a child without ModPlacer +90 degrees on X.
# The socket's 180-degree Z turn composes with that rotation to face the meter aft.
SLOT_ROTATION = struct.pack("<4f", 0, 0, 1, 0)


def unpack(path):
    meta, files = unityfs.read_bundle(path)
    mains = [name for name, flag in meta["nodes"] if flag == 4]
    if meta["engine"] != VERSION or len(mains) != 1:
        raise ValueError(f"{path} is not a single {VERSION} UnityFS bundle")
    cab = mains[0]
    sf = SerializedFile(files[cab])
    if sf.version != VERSION or sf.platform != 19:
        raise ValueError(f"unexpected Unity serialized version/target: {sf.version}/{sf.platform}")
    return sf, cab, meta, files


def texture_payload(path, is_normal):
    with Image.open(path) as image:
        image = image.convert("RGB")
    if image.size not in {(2048, 2048), (4096, 4096)}:
        raise ValueError(f"Expected a square 2K or 4K atlas at {path}, found {image.size}")
    size = image.width
    # Unity's DXT5nm swizzle packs X in A and Y in G. The EXO source stores G
    # in B as well. Unity serialized texture rows run bottom to top.
    image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    mips = []
    while True:
        if is_normal:
            x, y, _ = image.split()
            red = Image.new("L", image.size, 255)
            pixels = Image.merge("RGBA", (red, y, y, x))
        else:
            pixels = image.convert("RGBA")
        out = BytesIO()
        pixels.save(out, "DDS", pixel_format="DXT5" if is_normal else "DXT1")
        dds = out.getvalue()
        expected = ((image.width + 3) // 4) * ((image.height + 3) // 4) * (16 if is_normal else 8)
        if len(dds) != 128 + expected:
            raise ValueError(f"unexpected DDS encoded size for {path}: {image.size}")
        mips.append(dds[128:])
        if image.size == (1, 1):
            break
        image = image.resize((image.width // 2, image.height // 2), Image.Resampling.BOX)
    return b"".join(mips), size, len(mips)


def read_strings(data):
    size, = struct.unpack_from("<i", data)
    result = []
    offset = 4
    for _ in range(size):
        value, offset = read_string(data, offset)
        result.append(value)
    if offset != len(data):
        raise ValueError("unexpected trailing string-array bytes")
    return result


def local_pid(data):
    file_id, pid = struct.unpack("<iq", data)
    if file_id:
        raise ValueError("required a local PPtr")
    return pid


def members(sf, class_id):
    return [record for record in sf.records.values() if sf.class_id(record) == class_id]


def named(sf, class_id):
    return {
        read_string(sf.fields(record)["m_Name"])[0]: record for record in members(sf, class_id)
    }


def add_power_cell_slot(sf, prefab_root):
    root = sf.records[prefab_root]
    transforms = {
        local_pid(sf.fields(record)["m_GameObject"]): record for record in members(sf, 4)
    }
    root_transform = transforms[prefab_root]
    slot_go_id, slot_transform_id = SLOT_IDS
    if any(pid in sf.records for pid in SLOT_IDS):
        raise ValueError("power cell slot object IDs already in use")
    slot_go = Record(slot_go_id, root.type_index, root.data)
    sf.replace_fields(slot_go, {
        "m_Component": array(1, pptr(0, slot_transform_id)),
        "m_Name": string(SLOT_NAME),
    })
    slot_transform = Record(slot_transform_id, root_transform.type_index, root_transform.data)
    sf.replace_fields(slot_transform, {
        "m_GameObject": pptr(0, slot_go_id),
        "m_LocalRotation": SLOT_ROTATION,
        "m_LocalPosition": SLOT_POSITION,
        "m_Children": bytes(4),
        "m_Father": pptr(0, root_transform.path_id),
    })
    root_children = sf.fields(root_transform)["m_Children"]
    child_count, = struct.unpack_from("<i", root_children)
    sf.replace_fields(root_transform, {
        "m_Children": array(child_count + 1, root_children[4:] + pptr(0, slot_transform_id)),
    })
    sf.records[slot_go_id] = slot_go
    sf.records[slot_transform_id] = slot_transform


def create_bundle(source, art, output, data):
    sf, old_cab, metadata, _ = unpack(source)
    meshes = named(sf, 43)
    textures = named(sf, 28)
    if set(meshes) != {f"exo_t3_{tag}{lod}" for tag in ("lod", "loot") for lod in (0, 1)}:
        raise ValueError("template must provide two dressed and two loot EXO3 meshes")
    texture_names = {"exo_dif", "exo_nrm", "exo_gloss"}
    if set(textures) != texture_names:
        raise ValueError("expected the three EXO3 material maps")

    bones = data["bones"]
    paths = [bone["path"] for bone in bones]
    if len(paths) != len(set(paths)) or not all(
        (path == ROOT_BONE or path.startswith(ROOT_BONE + "/"))
        and path.rsplit("/", 1)[-1] == bone["name"] for bone, path in zip(bones, paths)
    ):
        raise ValueError("bone paths must be unique EFT pelvis paths matched by name")

    digest = hashlib.sha256(BUNDLE_KEY.encode("utf-8"))
    digest.update(SLOT_POSITION + SLOT_ROTATION)
    digest.update((art / "suit_unity.json").read_bytes())
    for name in sorted(textures):
        digest.update((art / "textures" / f"{name}.png").read_bytes())
    cab = "CAB-" + digest.hexdigest()[:32]
    stream_path = f"archive:/{cab}/{cab}.resS"
    stream = bytearray()
    for name, record in textures.items():
        is_normal = name == "exo_nrm"
        payload, size, mip_count = texture_payload(art / "textures" / f"{name}.png", is_normal)
        fields = sf.fields(record)
        observed = struct.unpack_from("<4i", fields["m_TextureFormat"] + fields["m_MipCount"]
                                      + fields["m_Width"] + fields["m_Height"])
        if observed != ((12 if is_normal else 10), 12, 2048, 2048):
            raise ValueError(f"{name}: unsupported texture properties {observed}")
        sf.replace_fields(record, {
            "m_Name": string(name.replace("exo_", "juggernaut_")),
            "m_ColorSpace": struct.pack("<i", int(name == "exo_dif")),
            "m_Width": struct.pack("<i", size),
            "m_Height": struct.pack("<i", size),
            "m_MipCount": struct.pack("<i", mip_count),
            "m_CompleteImageSize": struct.pack("<I", len(payload)),
            "m_StreamData": struct.pack("<QI", len(stream), len(payload)) + string(stream_path),
        })
        stream += payload
        stream += bytes(align(len(stream), 16) - len(stream))

    match_updates = {}
    for name, mesh in meshes.items():
        index = int(name[-1])
        kind = name.split("_")[-1]
        updates = mesh_updates(data["lods"][index], bones if kind.startswith("lod") else None,
                               f"juggernaut_{kind}")
        match_updates[mesh.path_id] = updates
        sf.replace_fields(mesh, updates)

    name_updates = {
        "item_equipment_exoskeleton_t3": NAME,
        "AR_Redut_T5_lod0": "juggernaut_lod0",
        "AR_Redut_T5_lod1": "juggernaut_lod1",
    }
    for root in members(sf, 1):
        name = read_string(sf.fields(root)["m_Name"])[0]
        if name in name_updates:
            sf.replace_fields(root, {"m_Name": string(name_updates[name])})

    filters = {
        local_pid(fields["m_GameObject"]): local_pid(fields["m_Mesh"])
        for record in members(sf, 33) if (fields := sf.fields(record))
    }
    dresser_bounds = {}
    for record in members(sf, 137):
        fields = sf.fields(record)
        bounds = match_updates[local_pid(fields["m_Mesh"])]["m_LocalAABB"]
        center_extent = np.frombuffer(bounds, "<f4").copy()
        center_extent[3:] = np.maximum(center_extent[3:] + .15, 1.2)
        dresser_bounds[record.path_id] = center_extent
        sf.replace_fields(record, {
            "m_Bones": array(len(paths), pptr(0, 0) * len(paths)),
            "m_AABB": center_extent.tobytes(),
        })

    loot_center_extent = np.frombuffer(
        match_updates[meshes["exo_t3_loot0"].path_id]["m_LocalAABB"], "<f4"
    )
    for record in members(sf, 65):
        fields = sf.fields(record)
        game_object = local_pid(fields["m_GameObject"])
        if game_object in filters:
            fitted = np.frombuffer(match_updates[filters[game_object]]["m_LocalAABB"], "<f4")
            extent = fitted[3:]
        else:
            fitted = loot_center_extent
            # The root loot box is smaller than the per-LOD boxes in EXO3.
            # Fit it to the same fraction of the new geometry bounds.
            extent = fitted[3:] * np.array([.80, .62, .49], dtype="<f4")
        sf.replace_fields(record, {
            "m_Size": (2 * extent).tobytes(), "m_Center": fitted[:3].tobytes()
        })

    for record in members(sf, 205):
        fields = sf.fields(record)
        first_render = local_pid(fields["m_LODs"][16:28])
        center_extent = dresser_bounds.get(first_render, loot_center_extent)
        sf.replace_fields(record, {
            "m_LocalReferencePoint": center_extent[:3].tobytes(),
            "m_Size": struct.pack("<f", 2 * max(center_extent[3:])),
        })

    skins = 0
    for record in members(sf, 114):
        fields = sf.fields(record)
        if "_bonePaths" in fields:
            sf.replace_fields(record, {
                "_bonePaths": array(len(paths), b"".join(map(string, paths))),
                "_rootBonePath": string(ROOT_BONE),
            })
            skins += 1
        elif "pivotPosition" in fields:
            sf.replace_fields(record, {"pivotPosition": loot_center_extent[:3].tobytes()})
    if skins != 2:
        raise ValueError("template must have two EFT skin scripts")
    for material in members(sf, 21):
        sf.replace_fields(material, {"m_Name": string("juggernaut_suit")})

    bundle, = members(sf, 142)
    fields = sf.fields(bundle)
    container_count, = struct.unpack_from("<i", fields["m_Container"])
    _, old_key_end = read_string(fields["m_Container"], 4)
    if container_count != 1 or read_strings(fields["m_Dependencies"]) != EXPECTED_DEPENDENCIES:
        raise ValueError("unexpected asset container or dependency layout")
    first, count, file_id, prefab_root = struct.unpack_from("<iiiq", fields["m_Container"], old_key_end)
    preload_count, = struct.unpack_from("<i", fields["m_PreloadTable"])
    if file_id or first or count != preload_count:
        raise ValueError("unexpected template preload table")
    add_power_cell_slot(sf, prefab_root)
    preload = fields["m_PreloadTable"][4:] + b"".join(pptr(0, pid) for pid in SLOT_IDS)
    sf.replace_fields(bundle, {
        "m_Name": string(BUNDLE_KEY), "m_AssetBundleName": string(BUNDLE_KEY),
        "m_Container": array(1, string(PREFAB_KEY) + struct.pack("<iiiq", 0, count + 2, 0, prefab_root)),
        "m_PreloadTable": array(preload_count + 2, preload),
    })
    metadata["nodes"] = [(name.replace(old_cab, cab), flag) for name, flag in metadata["nodes"]]
    files = {cab: sf.pack(), f"{cab}.resS": bytes(stream)}
    output.parent.mkdir(parents=True, exist_ok=True)
    unityfs.write_bundle(output, metadata, files)


def verify_bundle(path, source, data, textures):
    sf, cab, metadata, files = unpack(path)
    template, old_cab, _, original_files = unpack(source)
    if cab == old_cab or len(files) != 2 or f"{cab}.resS" not in files:
        raise ValueError("wrong CAB or resource identities")
    if sf.prefix[48:] != template.prefix[48:] or sf.suffix != template.suffix:
        raise ValueError("type table, scripts or external dependencies changed")
    if {(p, o.type_index) for p, o in sf.records.items() if p not in SLOT_IDS} != {
        (p, o.type_index) for p, o in template.records.items()
    }:
        raise ValueError("object table differs from EXO3 template")
    for record in sf.records.values():
        sf.spans(record)

    manifest, = members(sf, 142)
    fields = sf.fields(manifest)
    prefab, offset = read_string(fields["m_Container"], 4)
    if prefab != PREFAB_KEY or read_string(fields["m_AssetBundleName"])[0] != BUNDLE_KEY:
        raise ValueError("incorrect public asset names")
    preload_offset, preload_count, file_id, root = struct.unpack_from("<iiiq", fields["m_Container"], offset)
    preload_size, = struct.unpack_from("<i", fields["m_PreloadTable"])
    if file_id or preload_offset != 0 or preload_count != preload_size:
        raise ValueError("unexpected asset preload table")
    if sf.fields(sf.records[root])["m_Name"] != string(NAME):
        raise ValueError("wrong prefab root")
    slot_go, slot_transform = (sf.records[pid] for pid in SLOT_IDS)
    slot_info = sf.fields(slot_transform)
    root_transform = sf.records[local_pid(slot_info["m_Father"])]
    root_info = sf.fields(root_transform)
    if (sf.fields(slot_go)["m_Name"] != string(SLOT_NAME)
            or sf.fields(slot_go)["m_Component"] != array(1, pptr(0, slot_transform.path_id))
            or slot_info["m_GameObject"] != pptr(0, slot_go.path_id)
            or slot_info["m_LocalPosition"] != SLOT_POSITION
            or slot_info["m_LocalRotation"] != SLOT_ROTATION
            or root_info["m_GameObject"] != pptr(0, root)
            or root_info["m_Children"][-12:] != pptr(0, slot_transform.path_id)):
        raise ValueError("incorrect power cell slot transform")
    for pos in range(4, 4 + 12 * preload_size, 12):
        file_id, pid = struct.unpack_from("<iq", fields["m_PreloadTable"], pos)
        if (file_id == 0 and pid not in sf.records) or not 0 <= file_id <= 3:
            raise ValueError("invalid preload reference")

    texinfo = {}
    resource = files[f"{cab}.resS"]
    for name, record in named(sf, 28).items():
        info = sf.fields(record)
        start, size = struct.unpack_from("<QI", info["m_StreamData"])
        res_path, end = read_string(info["m_StreamData"], 12)
        expected, width, mip_count = texture_payload(textures / (name.replace("juggernaut_", "exo_") + ".png"),
                                                     name.endswith("_nrm"))
        shape = struct.unpack("<3i", info["m_Width"] + info["m_Height"] + info["m_MipCount"])
        if shape != (width, width, mip_count):
            raise ValueError(f"{name}: atlas header differs from the supplied maps")
        if (res_path != f"archive:/{cab}/{cab}.resS" or size != len(expected)
                or start != align(start, 16) or end != len(info["m_StreamData"])):
            raise ValueError("wrong texture resource stream")
        if resource[start:start + size] != expected:
            raise ValueError("texture data differs from corresponding PNG")
        texinfo[name] = {"width": width, "height": width, "mip_levels": mip_count, "bytes": size}

    meshinfo = {}
    for name, record in named(sf, 43).items():
        info = sf.fields(record)
        lod = data["lods"][int(name[-1])]
        skinned = "_lod" in name
        vertices = len(lod["v"]) // 3
        n, channels = struct.unpack_from("<II", info["m_VertexData"])
        offset = 8 + channels * 4
        payload_size, = struct.unpack_from("<I", info["m_VertexData"], offset)
        vertex_data = info["m_VertexData"][offset + 4:]
        expected_size = (align(vertices * 40, 16) + align(vertices * 8, 16) + vertices * 32
                         if skinned else vertices * 48)
        if (n, channels, payload_size, len(vertex_data)) != (vertices, 14, expected_size, expected_size):
            raise ValueError(f"{name}: wrong vertex stream layout")
        stride = 10 if skinned else 12
        stream0 = np.frombuffer(vertex_data, "<f4", vertices * stride).reshape(vertices, stride)
        assert np.array_equal(stream0[:, :3], np.asarray(lod["v"], dtype="<f4").reshape(-1, 3))
        assert np.array_equal(stream0[:, 3:6], np.asarray(lod["n"], dtype="<f4").reshape(-1, 3))
        assert np.isfinite(stream0).all()
        uv_values = (np.frombuffer(vertex_data, "<f4", vertices * 2, align(vertices * 40, 16))
                     if skinned else stream0[:, 10:12].ravel())
        assert np.array_equal(uv_values, np.asarray(lod["uv"], dtype="<f4"))
        assert np.array_equal(np.frombuffer(info["m_IndexBuffer"], "<u4", offset=4), lod["t"])
        if skinned:
            bone_start = align(vertices * 40, 16) + align(vertices * 8, 16)
            weights = np.frombuffer(vertex_data, "<f4", offset=bone_start).reshape(vertices, 8)[:, :4]
            indices = np.frombuffer(vertex_data, "<u4", offset=bone_start).reshape(vertices, 8)[:, 4:]
            assert np.array_equal(weights.ravel(), np.asarray(lod["bw"], dtype="<f4"))
            assert np.array_equal(indices.ravel(), lod["bi"])
            matrices = [np.array(b["bindpose"], dtype="<f4").reshape(4, 4).T for b in data["bones"]]
            assert info["m_BindPose"] == array(len(matrices), np.asarray(matrices, dtype="<f4").tobytes())
        meshinfo[name] = {"vertices": n, "triangles": len(lod["t"]) // 3, "skinned": skinned}
    for script in members(sf, 114):
        info = sf.fields(script)
        if "_bonePaths" in info:
            assert read_strings(info["_bonePaths"]) == [bone["path"] for bone in data["bones"]]
            assert read_string(info["_rootBonePath"])[0] == ROOT_BONE
            renderer = sf.records[local_pid(info["_skinnedMeshRenderer"])]
            renderer_info = sf.fields(renderer)
            assert struct.unpack_from("<i", renderer_info["m_Bones"])[0] == len(data["bones"])
            assert sf.class_id(renderer) == 137
            assert sf.class_id(sf.records[local_pid(renderer_info["m_Mesh"])]) == 43
    deps = read_strings(fields["m_Dependencies"])
    assert deps == EXPECTED_DEPENDENCIES
    old_sha256 = hashlib.sha256(original_files[old_cab]).hexdigest()
    return {
        "unity_version": metadata["engine"], "cab": cab, "donor_serialized_sha256": old_sha256,
        "bundle_key": BUNDLE_KEY, "prefab_key": PREFAB_KEY, "dependencies": deps,
        "objects": len(sf.records), "mesh_data": meshinfo, "textures": texinfo,
        "power_cell_slot": {"path": f"{NAME}/{SLOT_NAME}", "position": SLOT_ORIGIN,
                            "parent": "prefab root", "follows_spine_in_game": None},
        "bone_count": len(data["bones"]), "runtime_tested": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--art", type=Path, default=Path("art/suit"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    output = args.output or args.art / "serial" / (NAME + ".bundle")
    if output.resolve() == args.source.resolve():
        raise ValueError("source bundle is read-only")
    data = json.loads((args.art / "suit_unity.json").read_text(encoding="utf-8"))
    if not args.verify_only:
        temporary = output.with_suffix(".tmp")
        if temporary.resolve() == args.source.resolve():
            raise ValueError("source bundle is read-only")
        try:
            create_bundle(args.source, args.art, temporary, data)
            report = verify_bundle(temporary, args.source, data, args.art / "textures")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        report = verify_bundle(output, args.source, data, args.art / "textures")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

