"""UV-project the approved V5 geometry and export material baker inputs."""
from collections import defaultdict
import json
import math
from pathlib import Path
import re

import bmesh
import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "work" / "bake"
SIZES = {"armor": 4096, "textile": 4096, "frame": 4096, "helmet": 2048}
UV_NAME = "V5_Bake"
SKIN_GROUPS = {"Combat clothing", "Carrier and belt"}
FRAME_GROUPS = {"Power frame", "Backpack"}
HELMET_GROUPS = {"Helmet", "Thermal module"}
HANDS = re.compile(r"knuckle|wrist|gauntlet|glove|bracer|\bhands?\b", re.I)
FIRST_PERSON = re.compile(HANDS.pattern + r"|forearm|sleeve|elbow|upper arm", re.I)


def classify(group, material, name):
    if group in HELMET_GROUPS:
        return "helmet"
    if group == "Combat clothing" or any(
        word in material for word in ("webbing", "Cordura", "Carrier ")
    ):
        return "textile"
    if group in FRAME_GROUPS or "Yellow cable" in material:
        return "frame"
    if group in SKIN_GROUPS and material in {
        "V5 | Steel hardware", "V5 | Dark graphite frame", "V5 | Graphite polymer"
    }:
        return "textile"
    if "Belt suspension" in name and material.startswith("Powerpack"):
        return "frame"
    return "armor"


def edge_weights(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.normal_update()
    result = {}
    for edge in bm.edges:
        key = tuple(sorted(vertex.index for vertex in edge.verts))
        if edge.is_manifold:
            angle = edge.calc_face_angle_signed(0)
            result[key] = min(1, max(0, (angle - math.radians(9)) / math.radians(34)))
        elif edge.is_boundary:
            result[key] = 0.35
    bm.free()
    return result


class Source:
    def __init__(self, obj, group, lod):
        self.obj = obj
        self.lod = lod
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        self.mesh = obj.data
        original_uv = self.mesh.uv_layers.active
        self.original_uv = ([tuple(item.vector) for item in original_uv.uv]
                            if original_uv else None)
        self.uv = self.mesh.uv_layers.get(UV_NAME) or self.mesh.uv_layers.new(
            name=UV_NAME, do_init=False
        )
        self.mesh.uv_layers.active = self.uv
        self.uv.active_render = True
        self.face_atlas = []
        self.face_chart = np.full(len(self.mesh.polygons), -1, dtype=np.int32)
        self.material = []
        for polygon in self.mesh.polygons:
            name = obj.material_slots[polygon.material_index].material.name
            self.material.append(name)
            self.face_atlas.append(classify(group, name, obj.name))

    def positions(self):
        return np.array([self.obj.matrix_world @ v.co for v in self.mesh.vertices])

    def triangles(self, object_id, material_ids):
        self.mesh.calc_loop_triangles()
        has_tangents = all(p.loop_total <= 4 for p in self.mesh.polygons)
        if has_tangents:
            self.mesh.calc_tangents(uvmap=UV_NAME)
        normal_matrix = self.obj.matrix_world.to_3x3().inverted().transposed()
        tangent_matrix = self.obj.matrix_world.to_3x3()
        determinant_sign = 1 if tangent_matrix.determinant() > 0 else -1
        normal = [
            (normal_matrix @ corner.vector).normalized()
            for corner in self.mesh.corner_normals
        ]
        tangents = [
            (*((tangent_matrix @ loop.tangent).normalized()), loop.bitangent_sign * determinant_sign)
            for loop in self.mesh.loops
        ] if has_tangents else None
        points = self.positions()
        uv = [tuple(item.vector) for item in self.uv.uv]
        edges = edge_weights(self.mesh)
        for tri in self.mesh.loop_triangles:
            polygon = tri.polygon_index
            loops = list(tri.loops)
            vertices = list(tri.vertices)
            weights = [
                edges.get(tuple(sorted((vertices[(i + 1) % 3], vertices[(i + 2) % 3]))), 0)
                for i in range(3)
            ]
            triangle_uv = np.array([uv[i] for i in loops])
            if tangents is None:
                pp = points[vertices]
                xyz1, xyz2 = pp[1:] - pp[0]
                (u1, v1), (u2, v2) = triangle_uv[1:] - triangle_uv[0]
                det = u1 * v2 - u2 * v1
                sign = 1 if det >= 0 else -1
                tangent = sign * (xyz1 * v2 - xyz2 * v1)
                ts = []
                for i in loops:
                    n = np.array(normal[i])
                    t = tangent - n * np.dot(tangent, n)
                    length = np.linalg.norm(t)
                    ts.append((*(t / length if length > 0 else t), sign))
            else:
                ts = [tangents[i] for i in loops]
            yield self.face_atlas[polygon], (
                triangle_uv,
                points[vertices],
                [normal[i] for i in loops],
                ts,
                material_ids[self.material[polygon]],
                object_id,
                weights,
                self.lod,
                self.face_chart[polygon],
                polygon,
                [self.original_uv[i] for i in loops] if self.original_uv else [(-1, -1)] * 3,
            )
        if has_tangents:
            self.mesh.free_tangents()


def uv_components(mesh, coords):
    parents = list(range(len(mesh.polygons)))
    seen = {}

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for polygon in mesh.polygons:
        loops = list(polygon.loop_indices)
        for first, second in zip(loops, loops[1:] + loops[:1]):
            endpoints = sorted((
                (mesh.loops[first].vertex_index, *coords[first]),
                (mesh.loops[second].vertex_index, *coords[second]),
            ))
            key = tuple(endpoints)
            if key in seen:
                parents[root(polygon.index)] = root(seen[key])
            else:
                seen[key] = polygon.index
    names = {}
    return [names.setdefault(root(i), len(names)) for i in range(len(parents))]


def project(atlas, sources, cuts, regularized):
    verts, faces, source_faces = [], [], []
    for source in sources:
        selected = [i for i, name in enumerate(source.face_atlas) if name == atlas]
        if not selected:
            continue
        positions = source.positions()
        boost = 1.0
        if FIRST_PERSON.search(source.obj.name):
            boost = 2.60
        if HANDS.search(source.obj.name):
            boost = 2.90
        lod_scale = 0.65 if source.lod else 1.0
        center = positions.mean(axis=0)
        positions = center + boost * lod_scale * (positions - center)
        offset = len(verts)
        verts.extend(positions)
        for index in selected:
            polygon = source.mesh.polygons[index]
            key = (source.obj.name, index)
            if key in cuts:
                face = list(range(len(verts), len(verts) + polygon.loop_total))
                points = positions[list(polygon.vertices)]
                if key in regularized or polygon.area < 1e-10:
                    axis = points[np.argmax(np.linalg.norm(points - points[0], axis=1))] - points[0]
                    side = np.cross(axis, (0, 0, 1))
                    if np.linalg.norm(side) < 1e-12:
                        side = np.cross(axis, (0, 1, 0))
                    if np.linalg.norm(side) > 1e-12:
                        side /= np.linalg.norm(side)
                        amplitude = max(np.linalg.norm(axis), .001)
                        direction = axis / np.linalg.norm(axis)
                        origin = points.mean(axis=0)
                        angles = np.arange(len(points)) * 2 * np.pi / len(points)
                        points = origin + amplitude * (np.cos(angles[:, None]) * direction
                                                     + .20 * np.sin(angles[:, None]) * side)
                local_normal = np.cross(points[1] - points[0], points[2] - points[0])
                if key not in regularized and polygon.area >= 1e-10:
                    local_normal = source.obj.matrix_world.to_3x3().inverted().transposed() @ polygon.normal
                if np.linalg.norm(local_normal) > 1e-12:
                    rotation = Vector(local_normal).rotation_difference(Vector((0, 0, 1)))
                    points = [rotation @ Vector(point - points[0]) for point in points]
                verts.extend(points)
                faces.append(face)
            else:
                faces.append([v + offset for v in polygon.vertices])
            source_faces.append((source, index))
    mesh = bpy.data.meshes.new(f"Scratch {atlas}")
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=math.radians(55),
        margin_method="FRACTION",
        island_margin=4 / SIZES[atlas],
        area_weight=0.3,
        correct_aspect=False,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    coords = [tuple(value.vector) for value in mesh.uv_layers.active.uv]
    charts = uv_components(mesh, coords)
    for polygon, (source, original_id), chart in zip(mesh.polygons, source_faces, charts):
        original = source.mesh.polygons[original_id]
        for i, j in zip(polygon.loop_indices, original.loop_indices):
            source.uv.uv[j].vector = coords[i]
        source.face_chart[original_id] = chart
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    return len(set(charts))


def triangle_area(triangles):
    first = triangles[:, 1] - triangles[:, 0]
    second = triangles[:, 2] - triangles[:, 0]
    if triangles.shape[-1] == 2:
        return np.abs(first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]) / 2
    return np.linalg.norm(np.cross(first, second), axis=1) / 2


def export(sources, charts):
    materials = sorted({name for source in sources for name in source.material})
    material_ids = {name: i for i, name in enumerate(materials)}
    object_names = [source.obj.name for source in sources]
    groups = defaultdict(list)
    for i, source in enumerate(sources):
        for atlas, row in source.triangles(i, material_ids):
            groups[atlas].append(row)
    stats = {}
    names = ("uv", "pos", "normals", "tangent", "mat", "obj", "edge", "lod", "island", "polygon", "source_uv")
    types = (np.float32, np.float32, np.float32, np.float32, np.int32, np.int32,
             np.float32, np.int8, np.int32, np.int32, np.float32)
    for atlas, rows in groups.items():
        size = SIZES[atlas]
        arrays = {name: np.asarray(column, dtype=dtype)
                  for name, column, dtype in zip(names, zip(*rows), types)}
        uv = arrays["uv"]
        position_area = triangle_area(arrays["pos"])
        pixel_area = triangle_area(uv.astype(np.float64)) * size**2
        assert np.isfinite(uv).all() and 0 <= uv.min() <= uv.max() <= 1
        assert arrays["island"].min() >= 0
        layouts = {}
        for lod in (0, 1):
            mask = arrays["lod"] == lod
            fp = np.array([bool(FIRST_PERSON.search(object_names[i])) for i in arrays["obj"]])
            layouts[str(lod)] = {
                "triangles": int(mask.sum()),
                "world_area_m2": float(position_area[mask].sum()),
                "uv_coverage_pct": float(pixel_area[mask].sum() / size**2 * 100),
            }
            hands = np.array([bool(HANDS.search(object_names[i])) for i in arrays["obj"]])
            for label, region in (("density_px_per_m", mask), ("first_person_px_per_m", mask & fp),
                                  ("hands_px_per_m", mask & hands)):
                if np.any(region):
                    layouts[str(lod)][label] = float(
                        math.sqrt(pixel_area[region].sum() / position_area[region].sum())
                    )
        stats[atlas] = {
            "size": size, "charts": charts[atlas], "lod": layouts,
            "zero_uv_area_triangles": int((pixel_area < 1e-8).sum()),
            "min_border_px": float(min(uv.min(), 1 - uv.max()) * size),
        }
        np.savez_compressed(
            OUTPUT / f"{atlas}.npz", **arrays, chart=arrays["island"],
            resolution=np.int32(size), material_names=np.array(materials),
            object_names=np.array(object_names),
        )
        print(atlas, stats[atlas], flush=True)
    (OUTPUT / "layout_stats.json").write_text(json.dumps(stats, indent=2) + "\n")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    sources = []
    for collection in bpy.data.collections:
        if " · LOD" not in collection.name:
            continue
        group, lod = collection.name.rsplit(" · LOD", 1)
        for obj in sorted(collection.objects, key=lambda item: item.name):
            if obj.type == "MESH":
                sources.append(Source(obj, group, int(lod)))
    print(f"Projecting {len(sources)} source meshes", flush=True)
    rules = ROOT / "source" / "bake"
    cuts = {tuple(pair) for pair in json.loads((rules / "uv_cuts.json").read_text())}
    regularized = {tuple(pair) for pair in json.loads((rules / "uv_regularized.json").read_text())}
    charts = {}
    for atlas in SIZES:
        charts[atlas] = project(atlas, sources, cuts, regularized)
        print(f"{atlas}: {charts[atlas]} charts", flush=True)
    slots = {
        source.obj.name: {p.material_index: source.face_atlas[p.index]
                          for p in source.mesh.polygons}
        for source in sources
    }
    (OUTPUT / "atlas_slots.json").write_text(json.dumps(slots, indent=2) + "\n")
    export(sources, charts)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "layout.blend"))


if __name__ == "__main__":
    main()





