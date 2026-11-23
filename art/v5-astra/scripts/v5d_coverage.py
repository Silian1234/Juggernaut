"""Measure V5D worn undersuit coverage and optionally render the same hit samples."""

import argparse
from collections import defaultdict
from hashlib import file_digest
import json
from math import ceil
from pathlib import Path
import re
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))

REGIONS = (
    "torso front", "torso back", "torso sides", "shoulders", "upper arm outer",
    "upper arm inner", "forearm outer", "forearm inner", "groin", "buttocks",
    "thigh front", "thigh outer", "thigh inner", "thigh back", "knee front",
    "knee back", "shin", "calf",
)
ARM_PLATES = {
    "Deltoid shell", "Pauldron lower lame", "Outer biceps shell", "Elbow impact cap",
    "Wraparound forearm bracer", "Dorsal glove guard",
}
ARM_HOUSINGS = {
    "Shoulder drive pivot", "Upper arm actuator casing", "Forearm actuator casing",
    "Wrist housing with open inspection window", "Elbow planetary actuator",
    "Shoulder hydraulic distribution block",
}
CARRIER_SHELLS = {"FrontBacker", "RearPlateBag", "GroinPlate"}
HELMET_SHELLS = (
    "FAST | high-cut laminate shell", "Applique | brow brim panel", "Applique | temple brim panel",
    "Applique | forward crown applique", "Applique | aft crown applique",
    "Visor | smoked wraparound face shield", "Mandible | central chin cup",
    "Mandible | articulated jaw arm", "Mandible | jaw insert", "Mandible | chin link ",
    "Side | ear armor",
    "Rear | lower retention yoke", "Rear | nape facing",
)
SOFT_MATERIAL = (
    "webbing", "nylon", "rubber", "cable jacket", "padding", "balaclava", "textile",
    "foam", "gasket", "visor seal",
)
BASE_GARMENTS = ("Combat shirt", "Combat trousers")
MAX_RAY_M = .040
RAY_EPSILON = .000001
FRONT = Vector((0, -1, 0))


def geometry(obj, graph):
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    matrix = evaluated.matrix_world
    points = [matrix @ vertex.co for vertex in mesh.vertices]
    mesh.calc_loop_triangles()
    return evaluated, mesh, points


def qualifying_faces(obj, mesh):
    part = obj.get("part")
    name = re.sub(r"\.\d{3}$", "", obj.name)
    limb_name = name[2:]
    if obj.get("v5d_hard", False):
        chosen = lambda polygon: True
    elif part == "carrier":
        if not any(name == f"V5_Carrier_{shell}_LOD{obj['lod']}" for shell in CARRIER_SHELLS):
            return []
        chosen = lambda polygon: True
    elif part == "leg_plates":
        attribute = mesh.attributes.get("armor_component")
        if attribute is None:
            raise RuntimeError(f"{obj.name} has no armor_component data")
        components = {1, 3, 4, 5, 7, 8, 9, 10, 11, 14, 15}
        chosen = lambda polygon: attribute.data[polygon.index].value in components
    elif part == "leg_frame":
        spans = [span for label, span in json.loads(obj["frame_nodes"]).items()
                 if label.startswith(("can_", "housing_"))]
        chosen = lambda polygon: any(first <= polygon.index < stop for first, stop in spans)
    elif part == "arm_plates" and limb_name in ARM_PLATES:
        chosen = lambda polygon: True
    elif part == "arm_frame" and limb_name in ARM_HOUSINGS:
        chosen = lambda polygon: True
    elif part == "upper_frame" and obj.get("frame_node") in {"spine", "belt", "shoulder.L", "shoulder.R"}:
        chosen = lambda polygon: True
    elif part == "waist_armor":
        chosen = lambda polygon: True
    elif part == "helmet" and name.startswith(HELMET_SHELLS):
        chosen = lambda polygon: True
    else:
        return []
    if part == "carrier":
        return [poly.index for poly in mesh.polygons if chosen(poly)]
    return [
        poly.index for poly in mesh.polygons
        if chosen(poly) and not any(word in mesh.materials[poly.material_index].name.lower()
                                    for word in SOFT_MATERIAL)
    ]


def armor_tree(objects, graph):
    points, triangles, sources = [], [], []
    counts = {}
    for obj in sorted(objects, key=lambda item: item.name):
        if not obj.get("v5d_hard", False) and obj.get("part") in {None, "cloth", "pack", "thermal"}:
            continue
        evaluated, mesh, coords = geometry(obj, graph)
        try:
            selected = set(qualifying_faces(obj, mesh))
            tris = [tri for tri in mesh.loop_triangles if tri.polygon_index in selected]
            if tris:
                start = len(points)
                points.extend(coords)
                triangles.extend(tuple(index + start for index in tri.vertices) for tri in tris)
                sources.extend([obj.name] * len(tris))
                counts[obj.name] = len(tris)
        finally:
            evaluated.to_mesh_clear()
    if not triangles:
        raise RuntimeError("No qualifying armor triangles")
    return BVHTree.FromPolygons(points, triangles, all_triangles=True), sources, counts


class Anatomy:
    def __init__(self, rig):
        self.bones = {bone.name.removeprefix("Base Human"): rig.matrix_world @ bone.head_local
                      for bone in rig.data.bones if bone.name.startswith("Base Human")}
        self.arms, self.legs = {}, {}
        for side in "LR":
            shoulder, elbow, wrist = [self.bones[side + key]
                                      for key in ("Upperarm", "Forearm1", "Palm")]
            self.arms[side] = shoulder, elbow, wrist
            self.legs[side] = [self.bones[side + key] for key in ("Thigh1", "Calf", "Foot")]

    def excluded_region(self, garment, point, sleeve):
        side = "L" if point.x >= 0 else "R"
        if garment == "Combat trousers":
            _, knee, ankle = self.legs[side]
            if (point - ankle).dot(knee - ankle) < 0:
                return "feet"
        elif sleeve >= .5:
            _, elbow, wrist = self.arms[side]
            if (point - wrist).dot(wrist - elbow) > 0:
                return "hands"
        return None

    def region(self, garment, point, normal, sleeve):
        sign = 1 if point.x >= 0 else -1
        side = "L" if sign == 1 else "R"
        lateral = Vector((sign, 0, 0))
        if garment == "Combat shirt":
            shoulder, elbow, wrist = self.arms[side]
            upper_axis = (elbow - shoulder).normalized()
            along = (point - shoulder).dot(upper_axis)
            if sleeve >= .5:
                if along <= .066:
                    return "shoulders"
                fore_axis = (wrist - elbow).normalized()
                elbow_axis = (upper_axis + fore_axis).normalized()
                upper = (point - elbow).dot(elbow_axis) <= 0
                start, axis = (shoulder, upper_axis) if upper else (elbow, fore_axis)
                radial = point - start
                radial -= axis * radial.dot(axis)
                outer = radial.dot(lateral - axis * lateral.dot(axis)) >= 0
                return ("upper arm " if upper else "forearm ") + ("outer" if outer else "inner")
            if abs(normal.x) > abs(normal.y):
                return "torso sides"
            return "torso front" if normal.y <= 0 else "torso back"

        hip, knee, ankle = self.legs[side]
        if point.z >= hip.z - .081:
            return "groin" if point.y <= self.bones["Pelvis"].y else "buttocks"
        knee_offset = point.z - knee.z
        upper = knee_offset >= 0
        start, stop = (hip, knee) if upper else (knee, ankle)
        center = start.lerp(stop, (point.z - start.z) / (stop.z - start.z))
        radial = point - center
        front = radial.dot(FRONT) >= 0
        if abs(knee_offset) <= .055:
            return "knee front" if front else "knee back"
        if not upper:
            return "shin" if front else "calf"
        if abs(radial.x) > abs(radial.y):
            return "thigh outer" if radial.dot(lateral) >= 0 else "thigh inner"
        return "thigh front" if front else "thigh back"


def sample_grid(count):
    for i in range(count):
        for j in range(count - i):
            yield ((i, j), (i + 1, j), (i, j + 1))
            if i + j < count - 1:
                yield ((i + 1, j), (i + 1, j + 1), (i, j + 1))


def measure(garment, obj, graph, anatomy, tree, sources, step, heatmap):
    totals = defaultdict(lambda: [0.0, 0.0, 0])
    hits = defaultdict(float)
    surfaces = ([], [], [], [])
    evaluated, mesh, points = geometry(obj, graph)
    try:
        normal_matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
        normals = [normal_matrix @ item.vector for item in mesh.corner_normals]
        sleeve_groups = {group.index for group in obj.vertex_groups
                         if any(key in group.name for key in ("Upperarm", "Forearm", "Palm"))}
        sleeves = [sum(group.weight for group in vertex.groups if group.group in sleeve_groups)
                   for vertex in mesh.vertices]
        full_area = 0.0
        excluded = defaultdict(float)
        degenerate = 0
        for tri in mesh.loop_triangles:
            a, b, c = [points[i] for i in tri.vertices]
            normal = (b - a).cross(c - a)
            area = .5 * normal.length
            if area == 0:
                degenerate += 1
                continue
            full_area += area
            normal.normalize()
            na, nb, nc = [normals[i] for i in tri.loops]
            sa, sb, sc = [sleeves[i] for i in tri.vertices]
            count = max(1, ceil(max((b - a).length, (c - a).length, (c - b).length) / step))
            share = area / (count * count)
            delta_b, delta_c = (b - a) / count, (c - a) / count
            grid_points = {}
            if heatmap:
                for i in range(count + 1):
                    for j in range(count + 1 - i):
                        grid_points[i, j] = len(surfaces[0])
                        surfaces[0].append(a + i * delta_b + j * delta_c)
                        surfaces[3].append((na + (nb - na) * (i / count)
                                            + (nc - na) * (j / count)).normalized())
            for indices in sample_grid(count):
                i = sum(index[0] for index in indices) / 3
                j = sum(index[1] for index in indices) / 3
                point = a + i * delta_b + j * delta_c
                ray = (na + (nb - na) * (i / count) + (nc - na) * (j / count)).normalized()
                if ray.dot(normal) <= 0:
                    ray = normal
                sleeve = sa + (sb - sa) * (i / count) + (sc - sa) * (j / count)
                excluded_region = anatomy.excluded_region(garment, point, sleeve)
                if excluded_region:
                    excluded[excluded_region] += share
                    continue
                region = anatomy.region(garment, point, ray, sleeve)
                _, _, hit_index, _ = tree.ray_cast(point + RAY_EPSILON * ray, ray, MAX_RAY_M - RAY_EPSILON)
                record = totals[region]
                record[0] += share
                record[2] += 1
                if hit_index is not None:
                    record[1] += share
                    hits[sources[hit_index]] += share
                if heatmap:
                    surfaces[1].append(tuple(grid_points[index] for index in indices))
                    surfaces[2].append(hit_index is None)
        measured_area = sum(region[0] for region in totals.values())
        if abs(measured_area + sum(excluded.values()) - full_area) > 1e-8:
            raise RuntimeError(f"Region area does not match {obj.name} mesh area")
        return totals, hits, surfaces, {
            "object": obj.name,
            "triangles": len(mesh.loop_triangles),
            "degenerate_triangles": degenerate,
            "mesh_area_m2": full_area,
            "measured_area_m2": measured_area,
            "excluded_area_m2": dict(excluded),
        }
    finally:
        evaluated.to_mesh_clear()


def summarize(area, covered, count):
    return {"area_m2": area, "covered_area_m2": covered, "samples": count,
            "coverage_percent": 100 * covered / area if area else None}


def render_heatmap(surfaces, destination, samples):
    from finish import flat_material
    from render import Studio, configure_work_paths, view_bounds
    import numpy as np

    destination = destination.resolve()
    configure_work_paths()
    scene = bpy.context.scene
    for obj in scene.objects:
        if obj.type in {"MESH", "CURVE", "FONT", "LIGHT"}:
            obj.hide_render = True
    covered = flat_material("Covered by hard shell", (.27, .29, .30), .86)
    uncovered = flat_material("Uncovered undersuit", (.44, .006, .004), .86)
    points = []
    offset = max(abs(v.x) for vertices, _, _, _ in surfaces for v in vertices) + .045
    for side, angle in ((-offset, 0), (offset, 3.141592653589793)):
        rotation = Matrix.Rotation(angle, 3, "Z")
        for idx, (vertices, faces, misses, normals) in enumerate(surfaces):
            coords = [rotation @ v + Vector((side, 0, 0)) for v in vertices]
            mesh = bpy.data.meshes.new(f"Coverage sample mesh {idx}")
            mesh.from_pydata(coords, [], faces)
            mesh.update()
            mesh.materials.append(covered)
            mesh.materials.append(uncovered)
            mesh.polygons.foreach_set("material_index", misses)
            mesh.polygons.foreach_set("use_smooth", [True] * len(faces))
            mesh.normals_split_custom_set_from_vertices([rotation @ v for v in normals])
            obj = bpy.data.objects.new(mesh.name, mesh)
            scene.collection.objects.link(obj)
            used = {index for face in faces for index in face}
            points.extend(coords[index] for index in used)
    points = np.array(points)
    orientation, low, high = view_bounds(points, (0, -1, .025))
    studio = Studio(scene, samples, "OPTIX")
    studio.render(destination.resolve(), (1120, 1200), orientation, (low + high) * .5,
                  max((high - low)[1], (high - low)[0] * 1200 / 1120) * 1.08,
                  points[:, 2].min(), Vector((0, 0, points[:, 2].mean())))


def enable_layers(view_layer):
    view_layer.exclude = False
    for child in view_layer.children:
        enable_layers(child)


def garment_name(garment, lod):
    return f"Undersuit | {garment} LOD{lod}"


def source_identity(path):
    with path.open("rb") as stream:
        return {"file": path.name, "sha256": file_digest(stream, "sha256").hexdigest()}


def reference_garments(path):
    names = [garment_name(garment, lod) for lod in range(2) for garment in BASE_GARMENTS]
    with bpy.data.libraries.load(str(path), link=False) as (source, loaded):
        missing = set(names).difference(source.objects)
        if missing:
            raise RuntimeError(f"Missing reference garments in {path}: {sorted(missing)}")
        loaded.objects = list(names)

    witnesses = bpy.data.collections.new("Coverage denominator witnesses")
    bpy.context.scene.collection.children.link(witnesses)
    for obj in loaded.objects:
        witnesses.objects.link(obj)
        obj.hide_render = True
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object:
                modifier.object.data.pose_position = "REST"
    return dict(zip(names, loaded.objects))


def measure_lod(lod, garments, graph, anatomy, tree, sources, step, heatmap):
    totals = {region: [0.0, 0.0, 0] for region in REGIONS}
    hit_total = defaultdict(float)
    garment_records = []
    surfaces = []
    for garment in BASE_GARMENTS:
        name = garment_name(garment, lod)
        counts, hits, surface, record = measure(
            garment, garments[name], graph, anatomy, tree, sources, step, heatmap)
        record["source_object"] = name
        garment_records.append(record)
        for name, values in counts.items():
            for idx, amount in enumerate(values):
                totals[name][idx] += amount
        for name, area in hits.items():
            hit_total[name] += area
        if heatmap:
            surfaces.append(surface)
    result = summarize(*(sum(bucket[idx] for bucket in totals.values()) for idx in range(3)))
    return {
        "total": result,
        "regions": {region: summarize(*values) for region, values in totals.items()},
        "garments": garment_records,
        "covered_area_m2_by_first_hit_object": dict(sorted(hit_total.items())),
    }, surfaces

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--heatmap", type=Path)
    parser.add_argument("--reference-garments", type=Path,
                        help="Also ray-test using the original garments from this baseline blend")
    parser.add_argument("--step-mm", type=float, default=7.5)
    parser.add_argument("--render-samples", type=int, default=32)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if args.step_mm <= 0:
        parser.error("--step-mm must be positive")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rig = bpy.data.objects["EFT_Bind"]
    rig.data.pose_position = "REST"
    reference_path = args.reference_garments.resolve() if args.reference_garments else None
    references = reference_garments(reference_path) if reference_path else None
    enable_layers(bpy.context.view_layer.layer_collection)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    anatomy = Anatomy(rig)
    report = {
        **source_identity(Path(bpy.data.filepath)),
        "max_ray_m": MAX_RAY_M,
        "max_sample_edge_m": args.step_mm / 1000,
        "pose": "bind rest",
        "denominator": "All evaluated base combat-shirt and trouser surfaces including the neck, "
                       "excluding any garment samples anatomically past the wrist or ankle. "
                       "Head, glove, boot, sheath and raised trim meshes are separate objects.",
        "exclusions": "The wrist plane is normal to the elbow-to-wrist bind axis. The ankle plane "
                      "is normal to the knee-to-ankle bind axis. The report includes excluded "
                      "hand and foot area from each base garment.",
        "target_definition": "Hard plate faces, dedicated frame casing/housing faces, rigid helmet "
                             "shells and the two structural plate carrier envelopes. Soft face "
                             "materials, pouches, harness and hoses are excluded. Backpack omitted.",
        "classification": "Sleeve by interpolated arm skin weights, shoulder/elbow by bind arm joint "
                          "planes, torso by outward horizontal normal, pelvis by hip height, knee "
                          "by 55 mm above/below the joint, and leg direction by local bone center.",
        "sampling": "Equal-area subtriangles at or below the maximum sample edge length; centroid "
                    "rays use barycentrically interpolated outward corner normals. Heatmap uses "
                    "the exact same subtriangles and hit results.",
        "lods": {},
    }
    if references:
        report["reference_garments"] = {
            **source_identity(reference_path),
            "description": "Same submitted armor and rule, using the original matching-LOD garments.",
            "lods": {},
        }
    render_surfaces = []
    step = args.step_mm / 1000
    for lod in (0, 1):
        label = f"LOD{lod}"
        objects = {obj.name: obj for obj in bpy.data.collections[f"EXO_{label}"].all_objects
                   if obj.type == "MESH"}
        tree, sources, targets = armor_tree(objects.values(), graph)
        result, surfaces = measure_lod(lod, objects, graph, anatomy, tree, sources, step,
                                       lod == 0 and bool(args.heatmap))
        result["target_triangles_by_object"] = targets
        report["lods"][label] = result
        render_surfaces.extend(surfaces)
        stats = result["total"]
        print(f"{label}: {stats['coverage_percent']:.3f}% via {stats['samples']:,} rays", flush=True)
        if references:
            result, _ = measure_lod(lod, references, graph, anatomy, tree, sources, step, False)
            report["reference_garments"]["lods"][label] = result
            stats = result["total"]
            print(f"{label} fixed baseline garments: {stats['coverage_percent']:.3f}% "
                  f"via {stats['samples']:,} rays", flush=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.heatmap:
        args.heatmap.parent.mkdir(parents=True, exist_ok=True)
        render_heatmap(render_surfaces, args.heatmap, args.render_samples)


if __name__ == "__main__":
    main()
