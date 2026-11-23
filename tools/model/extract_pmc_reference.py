"""Extract the vanilla USEC reference for Blender from EFT 40743 character bundles."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unity"))
from suit_serial_file import SerializedFile, read_string, unityfs

SOURCE = Path("C:/SPT41/EscapeFromTarkov_Data/StreamingAssets/Windows")
DONORS = {
    "usec_head": ("usec_head_eric", "USEC_head_Eric_lod0_base", "USEC_head_Eric"),
    "usec_body": ("usec_body", "Tshirt_usec_CryeAC_lod0", "Pants_usec_CryeAC"),
    "pants_usec_commando": ("pants_usec_commando", "Pants_usec_commando_lod0", "Pants_usec_commando"),
}


def bundle(path):
    metadata, resources = unityfs.read_bundle(path)
    cab, = [name for name, flags in metadata["nodes"] if flags == 4]
    serialized = SerializedFile(resources[cab])
    if serialized.version != "2022.3.43f1":
        raise ValueError(f"Unexpected Unity version in {path}")
    return serialized, resources


def object_fields(serialized, class_id, name):
    record, = (obj for obj in serialized.records.values()
               if serialized.class_id(obj) == class_id and read_string(obj.data)[0] == name)
    return serialized.fields(record)


def mesh_data(fields):
    vertex = fields["m_VertexData"]
    count, channel_count = struct.unpack_from("<II", vertex)
    stream_end = 8 + 4 * channel_count
    channels = list(struct.iter_unpack("<4B", vertex[8:stream_end]))
    if channels[0:3] != [(0, 0, 0, 3), (0, 12, 0, 3), (0, 24, 0, 4)]:
        raise ValueError(f"Unexpected position and normal layout {channels}")
    uv_stream, uv_offset, uv_format, uv_dimension = channels[4]
    if (uv_stream, uv_offset, uv_format, uv_dimension) != (1, 0, 0, 2):
        raise ValueError(f"Unexpected UV layout {channels}")
    uv_stride = 16 if channels[5] == (1, 8, 0, 2) else 8
    data_size, = struct.unpack_from("<I", vertex, stream_end)
    vertex_data = vertex[stream_end + 4:stream_end + 4 + data_size]
    uv_start = (40 * count + 15) & ~15
    if len(vertex_data) < uv_start + uv_stride * count:
        raise ValueError("Truncated vertex stream")
    pos_norm = [struct.unpack_from("<6f", vertex_data, 40 * i) for i in range(count)]
    uv = [struct.unpack_from("<2f", vertex_data, uv_start + uv_stride * i) for i in range(count)]
    index_format, = struct.unpack("<I", fields["m_IndexFormat"])
    index_type = {0: "H", 1: "I"}[index_format]
    index_width = struct.calcsize(index_type)
    index_buffer = fields["m_IndexBuffer"]
    index_size, = struct.unpack_from("<I", index_buffer)
    indices = [i for (i,) in struct.iter_unpack("<" + index_type, index_buffer[4:4 + index_size])]
    groups = fields["m_SubMeshes"]
    group_count, = struct.unpack_from("<I", groups)
    triangles = []
    for group in range(group_count):
        offset, length, topology, base = struct.unpack_from("<4I", groups, 4 + 48 * group)
        if topology or length % 3 or offset % index_width:
            raise ValueError("Expected triangle list data")
        start = offset // index_width
        triangles.extend((a + base, c + base, b + base) for a, b, c in
                         zip(indices[start:start + length:3], indices[start + 1:start + length:3],
                             indices[start + 2:start + length:3]))
    return {"positions": [(-x, y, z) for x, y, z, *_ in pos_norm],
            "normals": [(-x, y, z) for _, _, _, x, y, z in pos_norm],
            "uv": uv, "triangles": triangles}


def decode_texture(fields, resources):
    width, height, fmt = [struct.unpack("<i", fields[k])[0]
                          for k in ("m_Width", "m_Height", "m_TextureFormat")]
    stream = fields["m_StreamData"]
    offset, length = struct.unpack_from("<QI", stream)
    location = read_string(stream, 12)[0].rsplit("/", 1)[-1]
    data = resources[location][offset:offset + length]
    codec, block_size = {10: (b"DXT1", 8), 12: (b"DXT5", 16)}[fmt]
    top_size = ((width + 3) // 4) * ((height + 3) // 4) * block_size
    header = struct.pack("<7I", 124, 0x81007, height, width, top_size, 0, 0)
    header += bytes(44) + struct.pack("<II4s5I", 32, 4, codec, 0, 0, 0, 0, 0)
    header += struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    with Image.open(BytesIO(b"DDS " + header + data[:top_size])) as source:
        return source.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert("RGBA")


def decode_normal(image):
    """Restore tangent-space RGB from EFT's DXT5nm alpha/green channels."""
    channels = np.asarray(image, dtype=np.float32)
    xy = channels[:, :, [3, 1]] / 127.5 - 1
    z = np.sqrt(np.maximum(0, 1 - np.sum(xy ** 2, axis=2)))
    rgb = np.dstack((channels[:, :, 3], channels[:, :, 1], (z + 1) * 127.5))
    return Image.fromarray(np.rint(rgb).astype(np.uint8))


def head_skinning(serialized, mesh_name, fields):
    """Get native influences and the bone paths used by this LOD's EFT Skin."""
    vertex = fields["m_VertexData"]
    count, channel_count = struct.unpack_from("<II", vertex)
    header = 8 + 4 * channel_count
    channels = list(struct.iter_unpack("<4B", vertex[8:header]))
    if channels[12:14] != [(2, 0, 0, 4), (2, 16, 10, 4)] or channels[5][3]:
        raise ValueError(f"Unexpected head skin layout for {mesh_name}")
    offset = ((count * 40 + 15) & ~15) + ((count * 8 + 15) & ~15)
    stream = np.frombuffer(vertex, dtype=np.dtype([("weight", "<f4", 4), ("index", "<u4", 4)]),
                           count=count, offset=header + 4 + offset)

    def follow(pointer):
        file_id, object_id = struct.unpack("<iq", pointer)
        if file_id:
            raise ValueError("Expected a local head renderer or mesh")
        return serialized.fields(serialized.records[object_id])

    for record in serialized.records.values():
        if serialized.class_id(record) != 114:
            continue
        skin = serialized.fields(record)
        if "_bonePaths" not in skin:
            continue
        renderer = follow(skin["_skinnedMeshRenderer"])
        if read_string(follow(renderer["m_Mesh"])["m_Name"])[0] == mesh_name:
            data = skin["_bonePaths"]
            path_count, = struct.unpack_from("<i", data)
            paths, cursor = [], 4
            for _ in range(path_count):
                path, cursor = read_string(data, cursor)
                paths.append(path)
            if int(stream["index"].max()) >= path_count or not np.allclose(stream["weight"].sum(1), 1, atol=1e-4):
                raise ValueError("Invalid native head weights or indices")
            return {"bonePaths": paths, "boneWeights": stream["weight"].tolist(),
                    "boneIndices": stream["index"].tolist()}
    raise ValueError(f"Missing EFT Skin for {mesh_name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=SOURCE, help="EFT StreamingAssets/Windows")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    prefabs = args.game / "assets/content/characters/character/prefabs"
    for stem, (bundle_name, mesh_name, texture_name) in DONORS.items():
        serialized, resources = bundle(prefabs / f"{bundle_name}.bundle")
        fields = object_fields(serialized, 43, mesh_name)
        mesh = mesh_data(fields)
        if stem == "usec_head":
            mesh.update(head_skinning(serialized, mesh_name, fields))
        (args.out / f"{stem}.json").write_text(json.dumps(mesh, separators=(",", ":")),
                                              encoding="utf8")
        for suffix in ("d", "g", "n"):
            texture = object_fields(serialized, 28, f"{texture_name}_{suffix}")
            decoded = decode_texture(texture, resources)
            if suffix == "n":
                decoded = decode_normal(decoded)
            decoded.save(args.out / f"{stem}_{suffix}.png")
        print(f"{bundle_name}.bundle / {mesh_name}: {len(mesh['positions'])} vertices, "
              f"{len(mesh['triangles'])} triangles", flush=True)


if __name__ == "__main__":
    main()
