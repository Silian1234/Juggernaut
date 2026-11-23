"""Compare the final scene against the archived pass-one scene in Blender."""

from hashlib import file_digest, sha256
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_qa import ROOT, all_upstream, differences, is_direct_link, open_scene, scene_snapshot


def snapshot(path):
    open_scene(path)
    result = scene_snapshot()
    layers = {}
    for obj in sorted((obj for obj in bpy.data.objects if obj.type == "MESH"), key=lambda obj: obj.name):
        layer_records = []
        for layer in obj.data.uv_layers:
            coordinates = np.empty(len(layer.uv) * 2, dtype=np.float32)
            layer.uv.foreach_get("vector", coordinates)
            layer_records.append({"name": layer.name, "loops": len(layer.uv),
                                  "active_render": layer.active_render, "active_clone": layer.active_clone,
                                  "sha256": sha256(coordinates.tobytes()).hexdigest()})
        layers[obj.name] = {"layers": layer_records, "active_index": obj.data.uv_layers.active_index}
    return result, layers


def map_bindings():
    atlas_slots = json.loads((ROOT / "work/bake/atlas_slots.json").read_text(encoding="utf-8"))
    assigned = 0
    errors = []
    records = {}
    for name, slots in atlas_slots.items():
        obj = bpy.data.objects[name]
        for index, atlas in slots.items():
            material = obj.material_slots[int(index)].material
            if material and material.name == f"V5d Atlas | {atlas.capitalize()}":
                assigned += 1
            else:
                errors.append(f"{name}: unexpected material in slot {index}")
    for atlas in sorted({atlas for slots in atlas_slots.values() for atlas in slots.values()}):
        material = bpy.data.materials[f"V5d Atlas | {atlas.capitalize()}"]
        nodes = material.node_tree.nodes
        output, = (node for node in nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output)
        upstream = list(all_upstream(output.inputs["Surface"]))
        normal, = (node for node in upstream if node.type == "NORMAL_MAP")
        reflection, = (node for node in upstream if node.bl_idname == "ShaderNodeBsdfMetallic")
        gloss_link, = reflection.inputs["Roughness"].links
        gloss = gloss_link.from_node
        spec = nodes["Atlas specgloss"]
        if not (normal.space == "TANGENT" and normal.uv_map == "V5_Bake"
                and is_direct_link(normal.inputs["Color"], nodes["Atlas normal"], "Color")
                and is_direct_link(reflection.inputs["Normal"], normal, "Normal")
                and is_direct_link(reflection.inputs["Base Color"], spec, "Color")
                and gloss.operation == "SUBTRACT" and not gloss.inputs[0].is_linked
                and gloss.inputs[0].default_value == 1.0
                and is_direct_link(gloss.inputs[1], spec, "Alpha")):
            errors.append(f"{atlas}: unexpected shader routing")
        images = {}
        for role, space in (("albedo", "sRGB"), ("normal", "Non-Color"), ("specgloss", "Non-Color")):
            node = nodes[f"Atlas {role}"]
            image = node.image
            observed = Path(bpy.path.abspath(image.filepath)).resolve()
            expected = ROOT / f"textures/v5d/{atlas}_{role}.png"
            uv_link, = node.inputs["Vector"].links
            if (node not in upstream or uv_link.from_node.type != "UVMAP"
                    or uv_link.from_node.uv_map != "V5_Bake" or observed != expected
                    or image.colorspace_settings.name != space or not all(image.size)
                    or (role != "normal" and image.alpha_mode != "CHANNEL_PACKED")):
                errors.append(f"{atlas}: unexpected {role} image settings")
            with observed.open("rb") as stream:
                digest = file_digest(stream, "sha256").hexdigest()
            if image.packed_file and sha256(image.packed_file.data).hexdigest() != digest:
                errors.append(f"{atlas}: the packed {role} image differs from disk")
            images[role] = {"path": str(observed), "sha256": digest, "size": list(image.size)}
        records[atlas] = images
    return {"meshes": len(atlas_slots), "slots": assigned, "images": records, "errors": errors}


def main():
    work = ROOT / "work/bake_v5b"
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    paths = [value for value in args if value != "--check-materials"]
    target_path = Path(paths[0]).resolve() if paths else ROOT / "juggernaut_v5_textured.blend"
    source_path = work / "pass1.blend"
    source, source_layers = snapshot(source_path)
    target, target_layers = snapshot(target_path)
    changes = differences(source, target)
    uv_changes = [name for name in sorted(source_layers.keys() | target_layers.keys())
                  if source_layers.get(name) != target_layers.get(name)]
    counts = {"EXO_LOD0": 79_984, "EXO_LOD1": 45_638}
    counts_match = all(target["triangles"][lod]["mesh"] == count and
                       target["triangles"][lod]["evaluated_scene"] == count
                       for lod, count in counts.items())
    ok = counts_match and not uv_changes and not any(changes.values())
    result = {"source": str(source_path), "target": str(target_path), "passed": ok,
              "differences": changes, "uv_changes": uv_changes, "counts_match": counts_match,
              "triangle_counts": target["triangles"], "object_counts": target["counts"],
              "frozen_uv_layers": target_layers}
    if "--check-materials" in args:
        result["material_bindings"] = map_bindings()
        ok = ok and not result["material_bindings"]["errors"]
        result["passed"] = ok
    (work / "qa_frozen_v5b.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "frozen_uv_layers"}, indent=2))
    if not ok:
        raise RuntimeError("Frozen-scene comparison failed")


if __name__ == "__main__":
    main()
