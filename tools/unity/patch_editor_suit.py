"""Resolve the editor's suit placeholders against the actual Redut material in EFT 40743."""
import argparse
from pathlib import Path
import struct

from build_rigid_bundles import split_maps
from suit_serial_file import SerializedFile, pptr, unityfs
from verify_art_bundles import COMMON, EFT, FOLDER, ROOT, VERSION


KEY = FOLDER + "/item_equipment_juggernaut_suit.bundle"
REDUT = "assets/content/items/equipment/armor_redut_t5/item_equipment_armor_redut_t5.bundle"


def read(path):
    meta, files = unityfs.read_bundle(path)
    cab, = [name for name, flag in meta["nodes"] if flag == 4]
    sf = SerializedFile(files[cab])
    assert sf.version == VERSION
    return meta, files, cab, sf, unityfs.SF(files[cab]).externals


def of_class(sf, cls):
    return [r for r in sf.records.values() if sf.class_id(r) == cls]


def patch(build, source, game, out):
    _, _, _, donor, donor_ext = read(game / REDUT)
    mat, = of_class(donor, 21)
    fields = donor.fields(mat)
    textures, *_ = split_maps(fields["m_SavedProperties"])
    physic, = {donor.fields(col)["m_Material"] for col in of_class(donor, 65)}
    targets = [fields["m_Shader"], textures["_Cube"][:12], physic]
    meta, files, name, suit, suit_ext = read(source)
    for key, cls, target in zip(COMMON, (48, 89, 134), targets, strict=True):
        _, _, dummy_cab, dummy, _ = read(build / key)
        dummy_record, = of_class(dummy, cls)
        file_id, game_id = struct.unpack("<iq", target)
        assert file_id > 0
        game_cab = donor_ext[file_id - 1].split("/")[-1]
        slot, = [i + 1 for i, value in enumerate(suit_ext) if value.endswith("/" + dummy_cab)]
        old, new = pptr(slot, dummy_record.path_id), pptr(slot, game_id)
        hits = 0
        for record in suit.records.values():
            if suit.class_id(record) in (21, 65, 142):
                hits += record.data.count(old)
                record.data = record.data.replace(old, new)
        assert hits >= 2, (key, hits)
        assert len(game_cab) == len(dummy_cab) and dummy_cab.encode() in suit.suffix
        suit.suffix = suit.suffix.replace(dummy_cab.encode(), game_cab.encode())
    files[name] = suit.pack()
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(".tmp")
    try:
        unityfs.write_bundle(temp, meta, files)
        _, _, _, check, external = read(temp)
        assert set(external) == set(donor_ext)
        assert len(check.records) == len(suit.records)
        temp.replace(out)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "art/build/suit")
    parser.add_argument("--game", type=Path, default=EFT)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "art/build/editor-patched" / KEY)
    args = parser.parse_args()
    patch(args.build, args.source or args.build / KEY, args.game, args.out)
    print(args.out)
