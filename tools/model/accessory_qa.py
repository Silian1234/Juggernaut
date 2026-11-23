"""Check helmet-to-gorget clearance on the rest suit and at head yaw angles.

Use Blender 5.3 headless; this loads the final suit and accessory sources.
Pass -- --rac-reference PATH --fast-reference PATH to also check headset fit.
Reference inputs are donor renderer-local positions and indexed triangle groups.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


ART = Path(__file__).resolve().parents[2] / "art"
# Exact EFT 40743 Head world position from skeleton.bundle and player.bundle,
# with the Blender axis conversion and root offset measured against Neck and Spine3.
HEAD_PIVOT = Vector((-.00062798, .02180314, 1.65807902))
RAC_WIDTH = 1.26
RAC_OFFSET = Vector((0, .045, .005))
RAC_PITCH = 16


def get_triangles(objects, include=None):
    vertices, triangles = [], []
    for obj in objects:
        data = obj.data
        data.calc_loop_triangles()
        if include is not None:
            mapped = {}
            for face in data.loop_triangles:
                if not include(obj, face):
                    continue
                for index in face.vertices:
                    if index not in mapped:
                        mapped[index] = len(vertices)
                        vertices.append(obj.matrix_world @ data.vertices[index].co)
                triangles.append(tuple(mapped[index] for index in face.vertices))
            continue
        offset = len(vertices)
        vertices.extend(obj.matrix_world @ point.co for point in data.vertices)
        triangles.extend(tuple(offset + index for index in face.vertices)
                         for face in data.loop_triangles)
    return vertices, triangles


def soft_helmet_face(obj, face):
    return obj.data.materials[face.material_index].name.startswith("Reinforced lower gasket")


def soft_collar_face(obj, _face):
    return any(tag in obj.name.lower() for tag in ("neckgasket", "neckhood", "padding_neck"))


def bvh_for(geometry):
    return BVHTree.FromPolygons(*geometry, all_triangles=True)


def sample_distance(points, tree):
    return min(tree.find_nearest(point)[3] for point in points)


def measure_yaw(head, armor, collar_tree):
    metrics = {}
    for angle in range(-75, 76, 5):
        rotation = Matrix.Rotation(math.radians(angle), 3, "Z")
        rotated = [HEAD_PIVOT + rotation @ (point - HEAD_PIVOT) for point in head[0]]
        head_tree = bvh_for((rotated, head[1]))
        metrics[angle] = {
            "intersecting_triangle_pairs": len(head_tree.overlap(collar_tree)),
            "nearest_vertex_surface_mm": round(min(sample_distance(rotated, collar_tree),
                                                  sample_distance(armor[0], head_tree)) * 1000, 3),
        }
    return metrics


def donor_triangles(source, width=1.0, offset=Vector((0, 0, 0)), pitch=0):
    serialized = json.loads(source.read_text(encoding="utf8"))
    rotation = Matrix.Rotation(math.radians(pitch), 3, "X")
    vertices = [HEAD_PIVOT + offset + rotation @ Vector((-x * width, y, z))
                for x, y, z in serialized["positions"]]
    triangles = [tuple(indices[i:i + 3]) for indices in serialized["submeshes"]
                 for i in range(0, len(indices), 3)]
    return vertices, triangles


def rac_components(vertices, triangles):
    """Group actual RAC triangles by connectivity across exported UV seams."""
    links = list(range(len(vertices)))

    def root(index):
        while index != links[index]:
            links[index] = links[links[index]]
            index = links[index]
        return index

    same_position = {}
    for index, point in enumerate(vertices):
        key = tuple(round(value, 5) for value in point)
        links[index] = same_position.setdefault(key, index)
    for a, b, c in triangles:
        anchor = root(a)
        links[root(b)] = anchor
        links[root(c)] = anchor
    parts = {}
    for face in triangles:
        parts.setdefault(root(face[0]), []).append(face)
    return parts.values()


def rac_flexible_contacts(pieces, rac):
    """Locate fabric contacts in the actual donor geometry."""
    vertices, triangles = rac
    contacts = {}
    for faces in rac_components(vertices, triangles):
        points = [vertices[index] for index in {index for face in faces for index in face}]
        limits = [[min(p[axis] for p in points), max(p[axis] for p in points)] for axis in range(3)]
        group_tree = bvh_for((vertices, faces))
        for name, geometry in pieces.items():
            if not geometry[1]:
                continue
            pairs = bvh_for(geometry).overlap(group_tree)
            if not pairs:
                continue
            candidates = {vertex for face, _ in pairs for vertex in geometry[1][face]}
            distances = []
            for vertex in candidates:
                point = geometry[0][vertex]
                hit, normal, _, distance = group_tree.find_nearest(point)
                # Donor vertices are reflected when converted to Blender space.
                # The reflected index winding points inwards.
                if hit is not None and normal.dot(point - hit) > 0:
                    distances.append(distance)
            bounds = [[round(low * 1000, 2), round(high * 1000, 2)] for low, high in limits]
            contacts.setdefault(name, []).append({
                "donor_component_triangles": len(faces),
                "donor_component_xyz_bounds_mm": bounds,
                "triangle_pairs": len(pairs),
                "max_sampled_fabric_vertex_depth_mm": round(max(distances, default=0) * 1000, 3),
            })
    return contacts


def measure_rac(rac_reference, fast_reference, helmet, soft_helmet, armor, collar_tree):
    native_rac = bvh_for(donor_triangles(rac_reference))
    fast_helmet = bvh_for(donor_triangles(fast_reference))
    fitted_rac = donor_triangles(rac_reference, RAC_WIDTH, RAC_OFFSET, RAC_PITCH)
    fitted_tree = bvh_for(fitted_rac)
    headset_fit = {}
    for lod, geo in helmet.items():
        helmet_tree = bvh_for(geo)
        headset_fit[lod] = {
            "native_mount_pairs": len(helmet_tree.overlap(native_rac)),
            "fitted_mount_pairs": len(helmet_tree.overlap(fitted_tree)),
            "fitted_nearest_vertex_surface_mm": round(
                min(sample_distance(geo[0], fitted_tree),
                    sample_distance(fitted_rac[0], helmet_tree)) * 1000, 3),
            "fitted_soft_contacts_by_part_and_donor_component": rac_flexible_contacts(
                soft_helmet[lod], fitted_rac),
        }
    return {
        "method": "Static exact donor mounting frame, with native equipped FAST+RAC as the baseline",
        "fast_native_rac_intersecting_triangle_pairs": len(fast_helmet.overlap(native_rac)),
        "fitted_blender_x_width_factor": RAC_WIDTH,
        "fitted_blender_offset": list(RAC_OFFSET),
        "fitted_blender_x_pitch_deg": RAC_PITCH,
        "headset_to_helmet": headset_fit,
        "headset_to_collar_yaw_degrees": measure_yaw(fitted_rac, armor, collar_tree),
    }


def thermal_mount_fit(thermal_parts, helmet_collections):
    """Record mounting overlap separately from interference on visible parts."""
    thermal_trees = {obj.name: bvh_for(get_triangles([obj])) for obj in thermal_parts}
    seating_thermal = ("latch wedge", "isolator")
    seating_helmet = ("sensor saddle", "center dovetail")
    results = {}
    for collection in helmet_collections:
        contact, interference = {}, {}
        for obj in collection.objects:
            tree = bvh_for(get_triangles([obj]))
            for name, thermal_tree in thermal_trees.items():
                pairs = len(tree.overlap(thermal_tree))
                if pairs:
                    result = (contact if any(part in name for part in seating_thermal)
                              and any(part in obj.name for part in seating_helmet)
                              else interference)
                    result[f"{name} / {obj.name}"] = pairs
        results[collection.name] = {"seating_contacts": contact,
                                    "other_intersections": interference}
    return results


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rac-reference", type=Path)
    parser.add_argument("--fast-reference", type=Path)
    parser.add_argument("--suit", type=Path, default=ART / "suit" / "suit.blend")
    parser.add_argument("--output", type=Path, default=ART / "accessories")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if (args.rac_reference is None) != (args.fast_reference is None):
        parser.error("supply both the RAC and the FAST donor references")
    suit_source = args.suit.resolve()
    accessory_source = ART / "accessories" / "accessories.blend"
    sources = {
        str(source.relative_to(ART) if source.is_relative_to(ART) else source):
            hashlib.sha256(source.read_bytes()).hexdigest()
        for source in (suit_source, accessory_source)
    }
    bpy.ops.wm.open_mainfile(filepath=str(suit_source))
    suit_collection = bpy.data.collections.get("JUG_LOD0") or next(
        collection for collection in bpy.data.collections
        if "LOD0" in collection.name and any("gorget" in obj.name.lower()
                                             for obj in collection.objects))
    def collar_objects(collection):
        return [obj for obj in collection.objects if obj.type == "MESH"
                and any(tag in obj.name.lower()
                        for tag in ("gorget", "juggcollar", "padding_neck", "neckgasket", "neckhood"))]

    collar_parts = collar_objects(suit_collection)
    if not collar_parts:
        raise ValueError("Could not find Juggernaut LOD0 collar meshes")
    with bpy.data.libraries.load(str(accessory_source), link=False) as (_, target):
        target.collections = ["JUG_HELMET", "JUG_HELMET_LOD1", "JUG_THERMAL"]
    for collection in target.collections:
        bpy.context.scene.collection.children.link(collection)
        collection.hide_viewport = False
    bpy.context.view_layer.update()
    armor = get_triangles(collar_parts, lambda obj, face: not soft_collar_face(obj, face))
    cloth = get_triangles(collar_parts, soft_collar_face)
    collar_tree = bvh_for(armor)
    helmet, soft_helmet = {}, {}
    for name, collection in zip(("LOD0", "LOD1"), target.collections):
        objects = [obj for obj in collection.objects if obj.type == "MESH"]
        helmet[name] = get_triangles(objects, lambda obj, face: not soft_helmet_face(obj, face))
        soft_helmet[name] = {obj.name: get_triangles([obj], soft_helmet_face) for obj in objects
                             if any(mat.name.startswith("Reinforced lower gasket")
                                    for mat in obj.data.materials)}
    thermal = thermal_mount_fit(target.collections[2].objects, target.collections[:2])
    measurements = {name: measure_yaw(geo, armor, collar_tree) for name, geo in helmet.items()}
    low_parts = collar_objects(bpy.data.collections["EXO_LOD1"])
    if not low_parts:
        raise ValueError("Missing LOD1 collar meshes")
    low_collar = get_triangles(low_parts, lambda obj, face: not soft_collar_face(obj, face))
    low_cloth = get_triangles(low_parts, soft_collar_face)
    low_tree = bvh_for(low_collar)
    low_measurements = {name: measure_yaw(geo, low_collar, low_tree) for name, geo in helmet.items()}
    soft_measurements = {}
    for lod, pieces in soft_helmet.items():
        collar, rigid_tree, liner = (
            (armor, collar_tree, cloth) if lod == "LOD0" else (low_collar, low_tree, low_cloth))
        liner_tree = bvh_for(liner) if liner[1] else None
        soft_measurements[lod] = {
            name: {
                "soft_helmet_to_rigid_collar": measure_yaw(geo, collar, rigid_tree),
                "soft_helmet_to_soft_collar": measure_yaw(geo, liner, liner_tree) if liner_tree else {},
            }
            for name, geo in pieces.items() if geo[1]
        }
        if liner_tree:
            soft_measurements[lod]["rigid_helmet_to_soft_collar"] = measure_yaw(helmet[lod], liner, liner_tree)
    results = {
        "source_sha256": sources,
        "world_head_pivot": list(HEAD_PIVOT),
        "method": "BVH triangle overlap plus nearest vertex-to-surface distance, rigid head yaw with suit in rest pose",
        "collar_parts": [obj.name for obj in collar_parts],
        "yaw_degrees_by_lod": measurements,
        "yaw_against_suit_lod1": low_measurements,
        "soft_collar_contacts_by_lod": soft_measurements,
        "thermal_mount_by_lod": thermal,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "collar_qa.json").write_text(json.dumps(results, indent=2), encoding="utf8")
    matching = {"0": measurements["LOD0"], "1": low_measurements["LOD1"]}
    matching_dest = ART / "suit" if args.suit.resolve() == ART / "suit" / "suit.blend" else args.output
    (matching_dest / "suit_helmet_qa.json").write_text(json.dumps(matching, indent=2), encoding="utf8")
    errors = []
    if any(row["intersecting_triangle_pairs"] for group in (measurements, low_measurements)
           for lod in group.values() for row in lod.values()):
        errors.append("The helmet intersects the collar")
    if any(row["other_intersections"] or not row["seating_contacts"] for row in thermal.values()):
        errors.append("Unexpected thermal-to-helmet fit")
    if args.rac_reference:
        rac = measure_rac(args.rac_reference, args.fast_reference, helmet, soft_helmet, armor, collar_tree)
        fitted_rac = donor_triangles(args.rac_reference, RAC_WIDTH, RAC_OFFSET, RAC_PITCH)
        rac["headset_to_collar_lod1_yaw_degrees"] = measure_yaw(fitted_rac, low_collar, low_tree)
        rac["headset_to_fabric_collar_yaw_degrees"] = {
            lod: measure_yaw(fitted_rac, liner, bvh_for(liner))
            for lod, liner in (("LOD0", cloth), ("LOD1", low_cloth)) if liner[1]
        }
        rac["source_sha256"] = sources
        (args.output / "rac_fit_qa.json").write_text(
            json.dumps(rac, indent=2), encoding="utf8")
        print("RAC QA", rac["headset_to_helmet"], "FAST baseline",
              rac["fast_native_rac_intersecting_triangle_pairs"])
        rac_yaw = rac["headset_to_collar_yaw_degrees"]
        print("RAC to collar QA", min(row["nearest_vertex_surface_mm"] for row in rac_yaw.values()),
              "mm min sampled distance and",
              sum(row["intersecting_triangle_pairs"] for row in rac_yaw.values()), "intersecting pairs")
        if (any(row["fitted_mount_pairs"] for row in rac["headset_to_helmet"].values())
                or any(row["intersecting_triangle_pairs"]
                       for lod in (rac_yaw, rac["headset_to_collar_lod1_yaw_degrees"])
                       for row in lod.values())):
            errors.append("The RAC headset intersects its helmet or collar")
    for lod, yaw in measurements.items():
        print("Collar QA", lod, "rest", yaw[0],
              "worst angle", min(yaw, key=lambda angle: yaw[angle]["nearest_vertex_surface_mm"]),
              "intersecting pairs across yaw range", sum(metrics["intersecting_triangle_pairs"]
                                                        for metrics in yaw.values()))
    if errors:
        raise ValueError(". ".join(errors))


if __name__ == "__main__":
    run()
