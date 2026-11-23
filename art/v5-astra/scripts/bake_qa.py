"""Audit a V5 bake with Blender's background Python.

blender -b --python-exit-code 1 --python art/v5-astra/scripts/bake_qa.py
Pass -- --source-only to inventory the frozen scene before the bake exists.
"""

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
from hashlib import file_digest, sha256
import json
import math
from pathlib import Path
import re
import struct
import sys

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mathutils import Matrix, Vector, Quaternion, Euler
from qa_frozen import fingerprint, matrix, object_attachment, weights_signature

ROOT = Path(__file__).resolve().parents[1]
LODS = ("EXO_LOD0", "EXO_LOD1")


def id_reference(item):
    return (item.bl_rna.identifier, item.name_full) if item else None


def property_values(owner):
    result = {}
    for prop in owner.bl_rna.properties:
        if prop.identifier in {"rna_type", "name"} or prop.type == "COLLECTION":
            continue
        value = getattr(owner, prop.identifier)
        if prop.type == "POINTER":
            if not value or isinstance(value, bpy.types.ID):
                result[prop.identifier] = id_reference(value)
        elif isinstance(value, Matrix):
            result[prop.identifier] = matrix(value)
        elif getattr(prop, "is_array", False) or isinstance(value, (Vector, Quaternion, Euler)):
            result[prop.identifier] = list(value)
        else:
            result[prop.identifier] = sorted(value) if isinstance(value, set) else value
    return result


def drivers(owner):
    animation = owner.animation_data
    if not animation:
        return []
    return [(curve.data_path, curve.array_index, curve.mute,
             curve.driver.type, curve.driver.expression, curve.driver.use_self,
             [(var.name, var.type, [property_values(target) for target in var.targets])
              for var in curve.driver.variables],
             [property_values(modifier) for modifier in curve.modifiers],
             [(tuple(key.co), tuple(key.handle_left), tuple(key.handle_right), key.interpolation)
              for key in curve.keyframe_points])
            for curve in animation.drivers]


def morphs(keys):
    if keys is None:
        return None
    return {
        "settings": [keys.use_relative, keys.eval_time],
        "blocks": [(block.name, block.relative_key.name, block.value, block.mute,
                    block.vertex_group, block.slider_min, block.slider_max, block.interpolation,
                    [tuple(point.co) for point in block.data])
                   for block in keys.key_blocks],
        "drivers": drivers(keys),
    }


def signature(obj):
    fields = object_attachment(obj)
    fields["drivers"] = drivers(obj)
    fields["modifier_settings"] = [(mod.name, property_values(mod)) for mod in obj.modifiers]
    fields["constraints"] = [(constraint.name, property_values(constraint))
                             for constraint in obj.constraints]
    if obj.type == "MESH":
        mesh = obj.data
        fields.update({
            "vertices": [tuple(vertex.co) for vertex in mesh.vertices],
            "topology": [[tuple(edge.vertices) for edge in mesh.edges],
                         [tuple(face.vertices) for face in mesh.polygons]],
            "material_slot_indices": [face.material_index for face in mesh.polygons],
            "original_uvs": {layer.name: [tuple(loop.vector) for loop in layer.uv]
                             for layer in mesh.uv_layers if layer.name != "V5_Bake"},
            "normals_shading": [mesh.has_custom_normals,
                               [edge.use_edge_sharp for edge in mesh.edges],
                               [face.use_smooth for face in mesh.polygons],
                               [tuple(normal.vector) for normal in mesh.corner_normals]
                               if mesh.has_custom_normals else None],
            "groups": [(group.name, group.lock_weight) for group in obj.vertex_groups],
            "weights": weights_signature(obj, range(len(mesh.vertices))),
            "mesh_drivers": drivers(mesh),
            "morphs": morphs(mesh.shape_keys),
        })
    if obj.type == "ARMATURE":
        fields["rest_bones"] = [(bone.name, bone.parent.name if bone.parent else None,
                                 matrix(bone.matrix_local), tuple(bone.head_local),
                                 tuple(bone.tail_local), property_values(bone))
                                for bone in obj.data.bones]
        fields["pose"] = [(bone.name, matrix(bone.matrix_basis), bone.rotation_mode,
                           [(constraint.name, property_values(constraint))
                            for constraint in bone.constraints])
                          for bone in obj.pose.bones]
        fields["rig_drivers"] = drivers(obj.data)
    return {key: fingerprint(value) for key, value in fields.items()}


def open_scene(path):
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    bpy.context.view_layer.update()


def scene_snapshot():
    memberships = {}
    triangles = {}
    rig = {obj.name for obj in bpy.context.scene.objects if obj.type == "ARMATURE"}
    statistics = Counter()
    for name in LODS:
        objects = sorted(bpy.data.collections[name].all_objects, key=lambda obj: obj.name)
        memberships[name] = [obj.name for obj in objects]
        depsgraph = bpy.context.evaluated_depsgraph_get()
        authored_count = evaluated_count = 0
        for obj in objects:
            if obj.type != "MESH":
                continue
            obj.data.calc_loop_triangles()
            authored_count += len(obj.data.loop_triangles)
            evaluated_mesh = obj.evaluated_get(depsgraph).data
            evaluated_mesh.calc_loop_triangles()
            evaluated_count += len(evaluated_mesh.loop_triangles)
        triangles[name] = {"mesh": authored_count, "evaluated_scene": evaluated_count}
    objects = {}
    for name in sorted(set().union(*memberships.values(), rig)):
        obj = bpy.data.objects[name]
        objects[name] = signature(obj)
        statistics[obj.type] += 1
        statistics["driver_curves"] += len(drivers(obj))
        if obj.type == "MESH" and (keys := obj.data.shape_keys):
            statistics["morph_blocks"] += len(keys.key_blocks)
            statistics["morph_driver_curves"] += len(drivers(keys))
    return {"memberships": memberships, "triangles": triangles, "objects": objects,
            "counts": dict(statistics)}


def differences(source, target):
    old, new = source["objects"], target["objects"]
    return {
        "missing": sorted(old.keys() - new.keys()),
        "added": sorted(new.keys() - old.keys()),
        "changed": {name: [field for field in sorted(old[name].keys() | new[name].keys())
                           if old[name].get(field) != new[name].get(field)]
                    for name in sorted(old.keys() & new.keys()) if old[name] != new[name]},
        "membership_changed": source["memberships"] != target["memberships"],
        "triangle_counts_changed": source["triangles"] != target["triangles"],
    }


def linked_images(socket, visited=None):
    visited = set() if visited is None else visited
    for link in socket.links:
        node = link.from_node
        identifier = node.as_pointer()
        if identifier in visited:
            continue
        visited.add(identifier)
        if node.type == "TEX_IMAGE" and node.image:
            yield node
        else:
            for input_socket in node.inputs:
                yield from linked_images(input_socket, visited)


def all_upstream(socket):
    pending = [socket]
    seen = set()
    while pending:
        input_socket = pending.pop()
        for link in input_socket.links:
            node = link.from_node
            identifier = node.as_pointer()
            if identifier not in seen:
                seen.add(identifier)
                yield node
                pending.extend(node.inputs)


def sha256_file(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def is_direct_link(socket, node, output_name):
    return len(socket.links) == 1 and socket.links[0].from_node == node and socket.links[0].from_socket.name == output_name


def check_gloss_routing(material, shader, node, errors):
    roughness = shader.inputs["Roughness"]
    if not is_direct_link(shader.inputs["Specular IOR Level"], node, "Color"):
        errors.append(f"{material.name} specular input is not using the specular RGB channel")
    links = list(roughness.links)
    invert = links[0].from_node if len(links) == 1 else None
    if (not invert or invert.type != "MATH" or invert.operation != "SUBTRACT"
            or invert.inputs[0].is_linked or invert.inputs[0].default_value != 1.0
            or not is_direct_link(invert.inputs[1], node, "Alpha")):
        errors.append(f"{material.name} roughness is not driven by one minus gloss alpha")


def inspect_image(node, role, errors):
    image = node.image
    path = Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()
    label = f"{role} image {image.name}"
    expected_space = "sRGB" if role == "albedo" else "Non-Color"
    expected_channels = {"albedo": 6, "normal": 2, "gloss_specular": 6, "metallic": 0}
    if image.colorspace_settings.name != expected_space:
        errors.append(f"{label} has color space {image.colorspace_settings.name!r}, expected {expected_space}")
    record = {"path": str(path), "size": list(image.size),
              "color_space": image.colorspace_settings.name, "alpha_mode": image.alpha_mode,
              "packed": bool(image.packed_file)}
    if role in {"albedo", "gloss_specular"} and image.alpha_mode != "CHANNEL_PACKED":
        errors.append(f"{label} needs Channel Packed alpha")
    if not path.is_relative_to(ROOT / "textures") or not path.is_file():
        errors.append(f"{label} does not reference an existing delivered texture: {path}")
    else:
        with path.open("rb") as stream:
            header = stream.read(29)
        if len(header) != 29 or header[:8] != b"\x89PNG\r\n\x1a\n":
            errors.append(f"{label} has an invalid PNG header")
        else:
            width, height, bits, color_type = struct.unpack(">IIBB", header[16:26])
            record.update(size=[width, height], bit_depth=bits, png_color_type=color_type,
                          sha256=sha256_file(path))
            if color_type != expected_channels[role] or bits != 8:
                errors.append(f"{label} has PNG type {color_type} at {bits} bits, expected type {expected_channels[role]} at 8 bits")
            if list(image.size) != [width, height]:
                errors.append(f"{label} has inconsistent on-disk and Blender dimensions")
            if image.packed_file and sha256(image.packed_file.data).hexdigest() != record["sha256"]:
                errors.append(f"{label} packed data differs from delivered texture")
    return record


def region(obj):
    name = obj.name.lower()
    if any(word in name for word in ("glove", "knuckle", " hand")):
        return "hands"
    if "forearm" in name or "wrist" in name:
        return "forearms"
    return obj.get("part") or "uncategorized"


def cloth_forearm_weights(obj):
    groups = {group.index for group in obj.vertex_groups if "forearm" in group.name.lower()}
    return [sum(weight.weight for weight in vertex.groups if weight.group in groups)
            for vertex in obj.data.vertices]


def signed_double_area(uv):
    ab, ac = uv[1] - uv[0], uv[2] - uv[0]
    return ab[0] * ac[1] - ab[1] * ac[0]


def density_record(triangles):
    areas = np.array(triangles, dtype=np.float64)
    ratios = np.sqrt(areas[:, 1] / areas[:, 0])
    order = np.argsort(ratios)
    cumulative = np.cumsum(areas[order, 0])
    indices = np.searchsorted(cumulative, cumulative[-1] * np.array([.1, .5, .9]))
    return {"triangles": len(triangles), "surface_m2": round(float(areas[:, 0].sum()), 6),
            "uv_area_px2": round(float(areas[:, 1].sum()), 2),
            "px_per_m_rms": round(float(math.sqrt(areas[:, 1].sum() / areas[:, 0].sum())), 2),
            "px_per_m_area_weighted_p10_p50_p90": ratios[order[indices]].round(2).tolist()}


def raster_overlap(triangles, size):
    """Count pixel centers hit by distinct triangle interiors at delivered resolution."""
    width, height = size
    occupied = np.zeros((height, width), dtype=np.uint8)
    for uv in triangles:
        points = uv * (width, height)
        if signed_double_area(points) < 0:
            points = points[[0, 2, 1]]
        left, bottom = np.maximum(np.ceil(points.min(axis=0) - .5).astype(int), 0)
        right, top = np.minimum(np.floor(points.max(axis=0) - .5).astype(int), (width - 1, height - 1))
        if left > right or bottom > top:
            continue
        x = np.arange(left, right + 1)[None, :] + .5
        y = np.arange(bottom, top + 1)[:, None] + .5
        inside = np.ones((top-bottom+1, right-left+1), dtype=bool)
        for a, b in zip(points, np.roll(points, -1, axis=0)):
            edge = b - a
            inside &= edge[0] * (y - a[1]) - edge[1] * (x - a[0]) > 1e-7
        subset = occupied[bottom:top+1, left:right+1]
        subset[inside] = np.minimum(subset[inside] + 1, 2)
    return occupied


def raster_record(occupied):
    return {"pixels_covered": int(np.count_nonzero(occupied)),
            "overlapping_pixel_centers": int(np.count_nonzero(occupied == 2)),
            "pixel_coverage_fraction": round(float(np.count_nonzero(occupied) / occupied.size), 6)}


def audit_maps():
    errors = []
    materials = {}
    atlases = {}
    image_cache = {}

    @lru_cache(maxsize=None)
    def inspect_material(material):
        if not material or not material.node_tree:
            errors.append(f"Missing node-based material: {material}")
            return None
        outputs = [node for node in material.node_tree.nodes
                   if node.type == "OUTPUT_MATERIAL" and node.is_active_output]
        shaders = {node for output in outputs for node in all_upstream(output.inputs["Surface"])
                   if node.type == "BSDF_PRINCIPLED"}
        if len(shaders) != 1:
            errors.append(f"{material.name} has {len(shaders)} active Principled shaders")
            return None
        shader = shaders.pop()
        roles = {"albedo": ("Base Color",), "normal": ("Normal",),
                 "gloss_specular": ("Roughness", "Specular IOR Level"),
                 "metallic": ("Metallic",)}
        images = {}
        explicit_uvs = set()
        for role, inputs in roles.items():
            matching = {node for name in inputs for node in linked_images(shader.inputs[name])}
            if len(matching) != 1:
                errors.append(f"{material.name} has {len(matching)} linked {role} maps")
                continue
            node = matching.pop()
            if role == "gloss_specular":
                check_gloss_routing(material, shader, node, errors)
            maps = [uv for uv in all_upstream(node.inputs["Vector"]) if uv.type == "UVMAP"]
            if maps:
                explicit_uvs.update(uv.uv_map for uv in maps if uv.uv_map)
            if role == "normal":
                normal_nodes = [item for item in all_upstream(shader.inputs["Normal"])
                                if item.type == "NORMAL_MAP" and item.space == "TANGENT"
                                and node in set(linked_images(item.inputs["Color"]))]
                if len(normal_nodes) != 1:
                    errors.append(f"{material.name} normal image is not routed into a tangent Normal Map")
                explicit_uvs.update(item.uv_map for item in normal_nodes if item.uv_map)
            key = (node.image.name, role)
            if key not in image_cache:
                image_cache[key] = inspect_image(node, role, errors)
            images[role] = image_cache[key]
        materials[material.name] = {"maps": images, "explicit_uv_layers": sorted(explicit_uvs)}
        if len(explicit_uvs) > 1:
            errors.append(f"{material.name} sends atlas channels through different UV layers")
        if len(images) != len(roles):
            return None
        atlas_id = Path(images["albedo"]["path"]).name
        sizes = {tuple(record["size"]) for record in images.values()}
        if len(sizes) != 1:
            errors.append(f"{material.name} has inconsistent atlas channel dimensions")
        if atlas_id in atlases and atlases[atlas_id] != images:
            errors.append(f"{atlas_id} is associated with conflicting atlas maps")
        atlases[atlas_id] = images
        return atlas_id, (next(iter(explicit_uvs)) if explicit_uvs else None), tuple(images["albedo"]["size"])

    lod_reports = {}
    previous_rasters = {}
    cross_lod_overlaps = {}
    for lod in LODS:
        densities = defaultdict(list)
        atlas_densities = defaultdict(list)
        raster = defaultdict(list)
        atlas_sizes = {}
        atlas_border = {}
        invalid = Counter()
        degenerate_objects = Counter()
        missing_objects = set()
        for obj in bpy.data.collections[lod].all_objects:
            if obj.type != "MESH":
                continue
            mesh = obj.data
            mesh.calc_loop_triangles()
            slots = {index: inspect_material(obj.material_slots[index].material)
                     for index in {tri.material_index for tri in mesh.loop_triangles}
                     if index < len(obj.material_slots)}
            active_uv = next((layer for layer in mesh.uv_layers if layer.active_render), mesh.uv_layers.active)
            prepared_uvs = {}
            meters_per_unit = bpy.context.scene.unit_settings.scale_length
            points = [(obj.matrix_world @ vertex.co) * meters_per_unit for vertex in mesh.vertices]
            category = region(obj)
            forearm_weights = cloth_forearm_weights(obj) if category == "cloth" else None
            for tri in mesh.loop_triangles:
                binding = slots.get(tri.material_index)
                if binding is None:
                    missing_objects.add(obj.name)
                    invalid["triangles_without_atlas"] += 1
                    continue
                atlas_id, uv_name, size = binding
                atlas_sizes[atlas_id] = size
                layer = mesh.uv_layers.get(uv_name) if uv_name else active_uv
                if layer is None:
                    missing_objects.add(obj.name)
                    invalid["triangles_without_atlas_uv"] += 1
                    continue
                if layer.name not in prepared_uvs:
                    layer_values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
                    layer.uv.foreach_get("vector", layer_values)
                    prepared_uvs[layer.name] = layer_values.reshape((-1, 2))
                uv = prepared_uvs[layer.name][list(tri.loops)].astype(np.float64)
                if not np.isfinite(uv).all() or uv.min() < -1e-6 or uv.max() > 1 + 1e-6:
                    invalid["invalid_uv_triangles"] += 1
                    continue
                a, b, c = (points[index] for index in tri.vertices)
                area = (b - a).cross(c - a).length * .5
                pixel_area = abs(signed_double_area(uv)) * .5 * math.prod(size)
                if area <= 1e-12:
                    invalid["degenerate_mesh_triangles"] += 1
                    degenerate_objects[obj.name] += 1
                if pixel_area <= 1e-8:
                    invalid["degenerate_uv_triangles"] += 1
                    if area > 1e-12:
                        invalid["nondegenerate_mesh_triangles_with_degenerate_uv"] += 1
                        degenerate_objects[obj.name] += 1
                if pixel_area <= 1e-8:
                    continue
                raster[atlas_id].append(uv)
                border = float(np.min(np.minimum(uv, 1 - uv) * size))
                atlas_border[atlas_id] = min(border, atlas_border.get(atlas_id, math.inf))
                if area <= 1e-12:
                    continue
                triangle_region = category
                if forearm_weights and sum(forearm_weights[index] for index in tri.vertices) >= 1.5:
                    triangle_region = "forearms"
                densities[(triangle_region, atlas_id)].append((area, pixel_area))
                atlas_densities[atlas_id].append((area, pixel_area))
        lod_reports[lod] = {
            "atlas_texel_density": {atlas: density_record(data) for atlas, data in sorted(atlas_densities.items())},
            "texel_density": {f"{category} / {atlas}": density_record(data)
                              for (category, atlas), data in sorted(densities.items())},
            "invalid_triangles": dict(invalid),
            "degenerate_objects": dict(sorted(degenerate_objects.items())),
            "missing_map_or_uv_objects": sorted(missing_objects),
            "atlas_coverage": {}
        }
        for atlas, uv in sorted(raster.items()):
            pixels = raster_overlap(uv, atlas_sizes[atlas])
            coverage = raster_record(pixels)
            coverage["minimum_border_px"] = round(atlas_border[atlas], 4)
            lod_reports[lod]["atlas_coverage"][atlas] = coverage
            if coverage["overlapping_pixel_centers"]:
                errors.append(f"{lod} {atlas} has {coverage['overlapping_pixel_centers']} overlapping pixel centers")
            if lod == LODS[0]:
                previous_rasters[atlas] = np.packbits(pixels > 0)
            elif atlas in previous_rasters:
                shared_pixels = np.bitwise_and(previous_rasters[atlas], np.packbits(pixels > 0))
                cross_lod_overlaps[atlas] = int(np.unpackbits(shared_pixels).sum())
                if cross_lod_overlaps[atlas]:
                    errors.append(f"{atlas} has {cross_lod_overlaps[atlas]} cross-LOD overlapping pixel centers")
        for name in ("triangles_without_atlas", "triangles_without_atlas_uv", "invalid_uv_triangles",
                     "nondegenerate_mesh_triangles_with_degenerate_uv"):
            if invalid[name]:
                errors.append(f"{lod} has {invalid[name]} {name}")
    if lod_reports[LODS[0]]["atlas_coverage"].keys() != lod_reports[LODS[1]]["atlas_coverage"].keys():
        errors.append("LOD0 and LOD1 do not use the same atlas set")
    return {"atlases": atlases, "materials": materials, "lods": lod_reports,
            "cross_lod_overlapping_pixel_centers": cross_lod_overlaps, "errors": errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "juggernaut_v5.blend")
    parser.add_argument("--textured", type=Path, default=ROOT / "juggernaut_v5_textured.blend")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    output = args.output or ROOT / "work" / "bake" / ("qa_source.json" if args.source_only else "qa.json")
    open_scene(args.source.resolve())
    source = scene_snapshot()
    report = {"source": str(args.source.resolve()), "source_sha256": sha256_file(args.source),
              "source_triangles": source["triangles"], "source_counts": source["counts"], "errors": []}
    if not args.source_only:
        open_scene(args.textured.resolve())
        textured = scene_snapshot()
        report.update(textured=str(args.textured.resolve()), textured_sha256=sha256_file(args.textured),
                      textured_triangles=textured["triangles"], textured_counts=textured["counts"],
                      frozen_differences=differences(source, textured), maps=audit_maps())
        if any(report["frozen_differences"].values()):
            report["errors"].append("Frozen scene differences detected")
        if textured["triangles"]["EXO_LOD0"]["mesh"] > 80000:
            report["errors"].append("LOD0 exceeds 80,000 triangles")
        report["errors"].extend(report["maps"]["errors"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"V5 bake QA: {output} ({len(report['errors'])} errors)", flush=True)
    if report["errors"]:
        raise RuntimeError("\n".join(report["errors"][:30]))


if __name__ == "__main__":
    main()








