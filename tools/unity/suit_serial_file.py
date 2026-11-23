"""Unity 2022.3.43f1 little-endian SerializedFile records and typed field spans."""
from dataclasses import dataclass
import struct
import unityfs


def align(value, alignment=4):
    return (value + alignment - 1) & -alignment


def string(value):
    data = value.encode("utf-8")
    return struct.pack("<i", len(data)) + data + bytes(align(len(data)) - len(data))


def read_string(data, offset=0):
    size, = struct.unpack_from("<i", data, offset)
    end = offset + 4 + size
    return data[offset + 4:end].decode("utf-8"), align(end)


def array(count, payload):
    return struct.pack("<i", count) + payload


def pptr(file_id, path_id):
    return struct.pack("<iq", file_id, path_id)


COMMON = {
    49: "Array", 55: "Base", 81: "char", 106: "data", 155: "first",
    161: "float", 222: "int", 241: "map", 349: "m_Enabled",
    374: "m_GameObject", 427: "m_Name", 490: "m_Script", 543: "pair",
    778: "second", 795: "size", 840: "string", 894: "TypelessData",
    981: "vector",
}


@dataclass
class Field:
    type: str
    name: str
    size: int
    flags: int
    children: list

    def fixed_size(self):
        if self.size < 0:
            return None
        span = sum(child.fixed_size() or 0 for child in self.children)
        if span and span != self.size:
            return None
        return align(self.size) if self.flags & 0x4000 else self.size

    def end(self, data, start):
        end = start
        if self.type in {"Array", "TypelessData"}:
            count, = struct.unpack_from("<i", data, end)
            if count < 0:
                raise ValueError(f"negative count for {self.name}")
            end += 4
            element = self.children[1]
            stride = element.fixed_size()
            if stride is None:
                for _ in range(count):
                    end = element.end(data, end)
            else:
                end += count * stride
        elif self.children:
            for child in self.children:
                end = child.end(data, end)
        elif self.size >= 0:
            end += self.size
        else:
            raise ValueError(f"variable-size leaf {self.name}")
        return align(end) if self.flags & 0x4000 else end


@dataclass
class Record:
    path_id: int
    type_index: int
    data: bytes


@dataclass
class TypeInfo:
    class_id: int
    script_index: int
    tree: Field | None


class SerializedFile:
    def __init__(self, data):
        if struct.unpack_from(">I", data, 8)[0] != 22 or data[16]:
            raise ValueError("expected little-endian SerializedFile version 22")
        metadata_size, _, data_start, _ = struct.unpack_from(">IqqQ", data, 20)
        self.version, offset = unityfs.cstr(data, 48)
        self.platform, trees, type_count = struct.unpack_from("<iBi", data, offset)
        offset += 9
        self.types = []
        for _ in range(type_count):
            class_id, _, script_index = struct.unpack_from("<iBh", data, offset)
            offset += 23 + (16 if class_id == 114 or script_index >= 0 else 0)
            tree = None
            if trees:
                count, str_size = struct.unpack_from("<ii", data, offset)
                offset += 8
                strings = data[offset + count * 32:offset + count * 32 + str_size]

                def lookup(key):
                    if key & 0x80000000:
                        key &= 0x7fffffff
                        return COMMON.get(key, f"@{key}")
                    return unityfs.cstr(strings, key)[0]

                stack = []
                for index in range(count):
                    _, level, _, field_type, name, size, _, flags, _ = struct.unpack_from(
                        "<HBBIIiiiQ", data, offset + index * 32
                    )
                    field = Field(lookup(field_type), lookup(name), size, flags, [])
                    del stack[level:]
                    if level:
                        stack[-1].children.append(field)
                    else:
                        tree = field
                    stack.append(field)
                offset += count * 32 + str_size
                dependencies, = struct.unpack_from("<i", data, offset)
                offset += 4 + dependencies * 4
            self.types.append(TypeInfo(class_id, script_index, tree))

        self.prefix = data[:offset]
        object_count, = struct.unpack_from("<i", data, offset)
        offset += 4
        self.records = {}
        for _ in range(object_count):
            offset = align(offset)
            path_id, start, size, type_index = struct.unpack_from("<qqIi", data, offset)
            offset += 24
            payload = data[data_start + start:data_start + start + size]
            if len(payload) != size or path_id in self.records:
                raise ValueError("invalid object table")
            self.records[path_id] = Record(path_id, type_index, payload)
        metadata_end = 48 + metadata_size
        if not offset <= metadata_end <= data_start:
            raise ValueError("invalid metadata length")
        self.suffix = data[offset:metadata_end]

    def class_id(self, record):
        return self.types[record.type_index].class_id

    def spans(self, record):
        tree = self.types[record.type_index].tree
        if tree is None:
            raise ValueError("SerializedFile has no type tree")
        offset = 0
        spans = {}
        for child in tree.children:
            end = child.end(record.data, offset)
            spans[child.name] = slice(offset, end)
            offset = end
        if align(offset) != align(len(record.data)):
            raise ValueError(f"{tree.type} {record.path_id}: {offset} vs {len(record.data)}")
        return spans

    def fields(self, record):
        return {key: record.data[span] for key, span in self.spans(record).items()}

    def replace_fields(self, record, updates):
        spans = self.spans(record)
        missing = updates.keys() - spans.keys()
        if missing:
            raise ValueError(f"unknown fields: {sorted(missing)}")
        last = next(reversed(spans.values())).stop
        record.data = (b"".join(updates.get(name, record.data[span]) for name, span in spans.items())
                       + record.data[last:])

    def pack(self):
        metadata = bytearray(self.prefix)
        metadata += struct.pack("<i", len(self.records))
        payload = bytearray()
        for record in sorted(self.records.values(), key=lambda row: row.path_id):
            metadata += bytes(align(len(metadata)) - len(metadata))
            payload += bytes(align(len(payload), 8) - len(payload))
            metadata += struct.pack("<qqIi", record.path_id, len(payload), len(record.data),
                                    record.type_index)
            payload += record.data
        metadata += self.suffix
        data_start = align(len(metadata), 16)
        struct.pack_into(">Iqq", metadata, 20, len(metadata) - 48, data_start + len(payload),
                         data_start)
        return bytes(metadata) + bytes(data_start - len(metadata)) + payload

