"""Extract renderer-local fit geometry from the three EFT 40743 helmet donors."""
import argparse
import json
from pathlib import Path
import struct

from suit_serial_file import SerializedFile, read_string, unityfs


ROOT = Path(__file__).resolve().parents[2]
DONORS = {
    "item_equipment_helmet_vulkan_5": "item_equipment_helmet_vulkan5_lod0_base",
    "item_equipment_helmet_hops_core_fast": "helmet_ops_core_fast_LOD0_base",
    "item_equipment_helmet_opscore_rac_headset": "helmet_ops_core_rac_headset_LOD0",
}


def extract(game, stem, mesh_name):
    source, = game.glob(f"assets/content/items/equipment/**/{stem}.bundle")
    meta, files = unityfs.read_bundle(source)
    cab, = [name for name, flags in meta["nodes"] if flags == 4]
    sf = SerializedFile(files[cab])
    if (meta["engine"], sf.version) != ("2022.3.43f1", "2022.3.43f1"):
        raise ValueError(f"{source} does not use Unity 2022.3.43f1")
    fields, = [sf.fields(record) for record in sf.records.values()
               if sf.class_id(record) == 43
               and read_string(record.data)[0].casefold() == mesh_name.casefold()]

    vertices = fields["m_VertexData"]
    count, channels = struct.unpack_from("<II", vertices)
    channel_rows = list(struct.iter_unpack("<4B", vertices[8:8 + 4 * channels]))
    if not channel_rows or channel_rows[0] != (0, 0, 0, 3):
        raise ValueError(f"{mesh_name} has an unexpected position channel")
    if any(stream != 0 for stream, _, _, dimension in channel_rows if dimension & 15):
        raise ValueError(f"{mesh_name} uses an unexpected multi-stream layout")
    inline_offset = 8 + 4 * channels
    byte_count, = struct.unpack_from("<I", vertices, inline_offset)
    if byte_count:
        data = vertices[inline_offset + 4:inline_offset + 4 + byte_count]
    else:
        stream = fields["m_StreamData"]
        offset, byte_count = struct.unpack_from("<QI", stream)
        path = read_string(stream, 12)[0].rsplit("/", 1)[-1]
        data = files[path][offset:offset + byte_count]
    if not count or len(data) != byte_count or byte_count % count != 0:
        raise ValueError(f"{mesh_name} has an invalid vertex buffer")
    stride = byte_count // count
    positions = [struct.unpack_from("<3f", data, i * stride) for i in range(count)]

    buffer = fields["m_IndexBuffer"]
    size, = struct.unpack_from("<I", buffer)
    index_format, = struct.unpack("<I", fields["m_IndexFormat"])
    index_type = {0: "H", 1: "I"}[index_format]
    index_width = struct.calcsize(index_type)
    indices = [index for (index,) in struct.iter_unpack("<" + index_type, buffer[4:4 + size])]
    submeshes = []
    content = fields["m_SubMeshes"]
    groups, = struct.unpack_from("<I", content)
    if len(content) != 4 + 48 * groups:
        raise ValueError(f"{mesh_name} has an unexpected submesh table layout")
    for group in range(groups):
        offset, length, topology, base = struct.unpack_from("<4I", content, 4 + 48 * group)
        if topology or length % 3 or offset % index_width:
            raise ValueError(f"{mesh_name} group {group} is not a triangle list")
        start = offset // index_width
        values = [base + index for index in indices[start:start + length]]
        if len(values) != length or any(index >= count for index in values):
            raise ValueError(f"{mesh_name} group {group} references missing indices")
        submeshes.append(values)
    return {"positions": positions, "submeshes": submeshes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path,
                        default=Path(r"C:/SPT41/EscapeFromTarkov_Data/StreamingAssets/Windows"))
    parser.add_argument("--out", type=Path, default=ROOT / "art/rigid")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for stem, mesh_name in DONORS.items():
        data = extract(args.game, stem, mesh_name)
        path = args.out / f"{stem}_fit_reference.json"
        path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf8")
        count = sum(len(group) // 3 for group in data["submeshes"])
        print(f"{path.name}: {len(data['positions'])} vertices, {count} triangles")


if __name__ == "__main__":
    main()
