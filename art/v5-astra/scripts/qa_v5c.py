"""Measure the V5C plates in the saved Blender assembly.

Run: blender -b juggernaut_v5.blend --python-exit-code 1 -P scripts/qa_v5c.py -- --help
"""

import argparse
from collections import Counter, defaultdict
from hashlib import file_digest
import json
from math import ceil, cos, pi, sin
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from poses import apply_pose
from qa_feedback import connected_triangle_sets, plane_slice

LEG_ROLES = {
    1: ("thigh_outer", "thigh"),
    3: ("knee_cap", "knee"),
    4: ("shin_greave", "calf"),
    5: ("ankle_cuff", "calf"),
    7: ("instep_cover", "boot"),
    8: ("rear_calf", "calf"),
    9: ("thigh_front_lower", "thigh"),
    10: ("thigh_front_middle", "thigh"),
    11: ("thigh_front_upper", "thigh"),
}
SHOULDER_ROLES = {8: ("shoulder_cap", "sleeve"), 9: ("shoulder_lame", "sleeve")}
VIEWS = {"front": (0, 2), "side": (1, 2)}
THIGH_NAMES = [name for name, region in LEG_ROLES.values() if region == "thigh"]


def mm(value):
    return round(float(value) * 1000, 3)


def axis_bounds(points, axis):
    return min(v[axis] for v in points), max(v[axis] for v in points)


def bvh(points, triangles):
    return BVHTree.FromPolygons(points, triangles, all_triangles=True, epsilon=0)


class Mesh:
    """World-space evaluated triangles, retaining Blender polygon IDs."""

    def __init__(self, obj, graph):
        self.obj = obj
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            self.points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
            self.triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
            self.faces = [triangle.polygon_index for triangle in mesh.loop_triangles]
            self.attributes = {
                name: [item.value for item in attribute.data]
                for name in ("armor_component", "v5c_plate", "v5c_inner", "v5c_outer")
                if (attribute := mesh.attributes.get(name))
                and attribute.domain == "FACE" and attribute.data_type == "INT"
            }
        finally:
            evaluated.to_mesh_clear()

    def tagged(self, tag, role):
        values = self.attributes.get(tag)
        return [tri for tri, face in zip(self.triangles, self.faces)
                if values and values[face] == role]


def clip_polygon(vertices, axis, level):
    """Retain the portion on the positive side of a plane."""
    polygon = []
    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
        da, db = a.dot(axis) - level, b.dot(axis) - level
        if da >= 0:
            polygon.append(a)
        if (da < 0 < db) or (db < 0 < da):
            polygon.append(a.lerp(b, da / (da - db)))
    return polygon


def clipped_triangles(mesh, planes):
    polygons = []
    points, triangles = [], []
    for tri in mesh.triangles:
        polygon = [mesh.points[i] for i in tri]
        for axis, level in planes:
            polygon = clip_polygon(polygon, axis, level)
            if not polygon:
                break
        if len(polygon) >= 3:
            polygons.append(polygon)
            start = len(points)
            points.extend(polygon)
            triangles.extend((start, start + k, start + k + 1)
                             for k in range(1, len(polygon) - 1))
    if not triangles:
        raise ValueError(f"No isolated garment triangles in {mesh.obj.name}")
    return points, triangles


def garment_region(mesh, rig, side, region):
    sign = 1 if side == "L" else -1
    outward, up = Vector((sign, 0, 0)), Vector((0, 0, 1))

    def head(name):
        return rig.matrix_world @ rig.data.bones[f"Base Human{side}{name}"].head_local

    planes = [(outward, 0)]
    if region == "sleeve":
        shoulder, elbow = head("Upperarm"), head("Forearm1")
        proximal = (elbow - shoulder).normalized()
        planes = [(outward, outward.dot(shoulder) - .035),
                  (proximal, proximal.dot(shoulder) - .035),
                  (-proximal, -proximal.dot(elbow) - .020)]
    elif region == "thigh":
        planes += [(up, head("Calf").z - .045), (-up, -head("Thigh1").z - .025)]
    elif region == "calf":
        planes += [(-up, -head("Calf").z - .045)]
    elif region == "knee":
        planes += [(up, head("Calf").z - .130), (-up, -head("Calf").z - .130)]
    return clipped_triangles(mesh, planes), [
        {"normal": list(axis), "signed_offset_m": float(level)} for axis, level in planes
    ]


def rasterize(points, triangles, axes, origin, shape, step):
    """Orthographic occupied pixel centers from the union of projected triangles."""
    coordinates = (np.array([[p[i] for i in axes] for p in points]) - origin) / step
    mask = np.zeros(shape, dtype=bool)
    # Roundoff from Blender's float32 vertices should not drop a grid-aligned edge.
    edge_epsilon = 1e-6 / step
    for tri in triangles:
        a, b, c = coordinates[list(tri)]
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < 1e-10:
            continue
        u0, v0 = np.maximum(np.ceil(np.minimum(np.minimum(a, b), c) - edge_epsilon).astype(int), 0)
        u1, v1 = np.minimum(np.floor(np.maximum(np.maximum(a, b), c) + edge_epsilon).astype(int),
                            np.array([shape[1] - 1, shape[0] - 1]))
        if u0 > u1 or v0 > v1:
            continue
        u = np.arange(u0, u1 + 1)[None, :]
        v = np.arange(v0, v1 + 1)[:, None]
        inside = True
        for start, end in [(a, b), (b, c), (c, a)]:
            d = end - start
            edge = d[0] * (v - start[1]) - d[1] * (u - start[0])
            tolerance = edge_epsilon * np.hypot(*d)
            inside = inside & (edge >= -tolerance if area > 0 else edge <= tolerance)
        mask[v0:v1 + 1, u0:u1 + 1] |= inside
    return mask


def projected_masks(geometries, axes, step):
    bounds = []
    for points, triangles in geometries:
        relevant = {i for tri in triangles for i in tri}
        bounds.extend([points[i][axis] for axis in axes] for i in relevant)
    low = np.floor(np.min(bounds, axis=0) / step) - 2
    high = np.ceil(np.max(bounds, axis=0) / step) + 2
    shape = tuple((high - low + 1).astype(int)[::-1])
    origin = low * step
    return origin, [rasterize(points, triangles, axes, origin, shape, step)
                    for points, triangles in geometries]


def contour(mask):
    # Border padding in projected_masks ensures no wraparound contact.
    interior = mask.copy()
    for axis in (0, 1):
        for direction in (-1, 1):
            interior &= np.roll(mask, direction, axis=axis)
    return mask & ~interior


def contour_distance(reference, target, origin, step):
    exterior = np.argwhere(contour(target) & ~reference)
    if not len(exterior):
        return {"max_mm": 0.0, "worst_uv_m": None}
    edge = np.argwhere(contour(reference))
    if not len(edge):
        raise ValueError("Empty reference silhouette")
    tree = KDTree(len(edge))
    for i, (v, u) in enumerate(edge):
        tree.insert((float(u), float(v), 0), i)
    tree.balance()
    distance, u, v = max((tree.find((float(u), float(v), 0))[2], int(u), int(v))
                         for v, u in exterior)
    return {"max_mm": mm(distance * step),
            "worst_uv_m": [round(float(axis), 5) for axis in origin + np.array([u, v]) * step]}


def overshoot(garment, plate, axes, step):
    origin, (reference, target) = projected_masks((garment, plate), axes, step)
    return contour_distance(reference, target, origin, step)


def wearer_tree(meshes):
    points, triangles, offsets = [], [], {}
    for mesh in meshes:
        offset = len(points)
        offsets[id(mesh.points)] = offset
        points.extend(mesh.points)
        triangles.extend(tuple(i + offset for i in tri) for tri in mesh.triangles)
    return bvh(points, triangles), triangles, offsets


def visible_projection(garment, plate, wearer, view, side, step):
    axes = VIEWS[view]
    origin, (ref, target) = projected_masks((garment, plate), axes, step)
    tree, tris, offsets = wearer
    points, structural = plate
    offset = offsets[id(points)]
    own = {tuple(i + offset for i in tri) for tri in structural}
    visible = np.zeros_like(target)
    depth_axis = 1 if view == "front" else 0
    direction = Vector((0, 0, 0))
    direction[depth_axis] = 1 if view == "front" or side == "R" else -1
    ray = Vector((0, 0, 0))
    ray[depth_axis] = -direction[depth_axis] * 3
    for v, u in np.argwhere(target):
        ray[axes[0]] = origin[0] + u * step
        ray[axes[1]] = origin[1] + v * step
        _, _, triangle, _ = tree.ray_cast(ray, direction)
        if triangle is not None and tris[triangle] in own:
            visible[v, u] = True
    cells = np.count_nonzero(target)
    exposed = np.count_nonzero(visible)
    return {"visible_area_mm2": round(exposed * (step * 1000) ** 2, 2),
            "physical_projected_area_mm2": round(cells * (step * 1000) ** 2, 2),
            "visible_fraction": round(exposed / cells, 4) if cells else None,
            "visible_contour_overshoot": contour_distance(ref, visible, origin, step)}


def surface_gap(points, triangles, target, step):
    """Sample barycentric nets over the true skin-facing triangles."""
    target_tree = bvh(*target)
    inner = bvh(points, triangles)
    crossings = inner.overlap(target_tree)
    low, high = (float("inf"), None, None), (-1, None, None)
    below_normal = count = 0
    for point in triangle_samples(points, triangles, step):
        nearest, normal, _, distance = target_tree.find_nearest(point)
        if nearest is None:
            raise ValueError("Empty garment BVH")
        if distance < low[0]:
            low = distance, point, nearest
        if distance > high[0]:
            high = distance, point, nearest
        below_normal += (point - nearest).dot(normal) < -.0005
        count += 1
    minimum = 0.0 if crossings else low[0]
    return {"min_mm": mm(minimum), "max_mm": mm(high[0]),
            "unsigned_min_bound_mm": [mm(max(0, minimum - step)), mm(minimum)],
            "unsigned_max_bound_mm": [mm(high[0]), mm(high[0] + step)],
            "sample_min_mm": mm(low[0]), "samples": count,
            "sample_min_xyz_m": list(low[1]), "sample_max_xyz_m": list(high[1]),
            "garment_at_sample_min_xyz_m": list(low[2]), "garment_at_sample_max_xyz_m": list(high[2]),
            "intersecting_triangle_pairs": len(crossings), "below_local_normal_samples": below_normal}


def triangle_samples(points, triangles, step):
    for tri in triangles:
        a, b, c = (points[i] for i in tri)
        divisions = max(1, ceil(max((b - a).length, (c - b).length, (a - c).length) / step))
        db, dc = (b - a) / divisions, (c - a) / divisions
        for i in range(divisions + 1):
            start = a + db * i
            for j in range(divisions + 1 - i):
                yield start + dc * j


def topology(points, triangles):
    edges, direction = Counter(), Counter()
    links = defaultdict(list)
    degenerate = 0
    for a, b, c in triangles:
        degenerate += (points[b] - points[a]).cross(points[c] - points[a]).length < 1e-10
        for u, v in ((a, b), (b, c), (c, a)):
            edge = tuple(sorted((u, v)))
            edges[edge] += 1
            direction[edge] += 1 if u < v else -1
        for corner, neighbors in ((a, (b, c)), (b, (c, a)), (c, (a, b))):
            links[corner].append(neighbors)

    disconnected_links = 0
    for opposite_edges in links.values():
        fans = defaultdict(set)
        for start, end in opposite_edges:
            fans[start].add(end)
            fans[end].add(start)
        pending = [next(iter(fans))]
        visited = set(pending)
        while pending:
            adjacent = fans[pending.pop()] - visited
            visited.update(adjacent)
            pending.extend(adjacent)
        disconnected_links += len(visited) != len(fans)
    return {"connected_islands": len(list(connected_triangle_sets(triangles))),
            "boundary_edges": sum(n == 1 for n in edges.values()),
            "non_manifold_edges": sum(n > 2 for n in edges.values()),
            "non_manifold_vertex_fans": disconnected_links,
            "inconsistent_winding_edges": sum(n == 2 and direction[edge] != 0
                                               for edge, n in edges.items()),
            "degenerate_triangles": degenerate}


def nonadjacent_surface_crossings(tree, triangles):
    vertices = [set(tri) for tri in triangles]
    return sum(a < b and vertices[a].isdisjoint(vertices[b]) for a, b in tree.overlap(tree))


def indices_of(geometry):
    return {i for tri in geometry[1] for i in tri}


def points_of(geometry):
    return [geometry[0][i] for i in sorted(indices_of(geometry))]


def thickness(mesh, role, body, inner, step):
    outer = mesh.tagged("v5c_outer", role)
    if outer and (axis_raw := mesh.obj.get("v5c_radial_axis")):
        center, axis = map(Vector, json.loads(axis_raw))
        axis.normalize()
        tree = bvh(mesh.points, inner)
        distances, missed = [], 0
        for point in triangle_samples(mesh.points, outer, step):
            delta = point - center
            inward = (axis * delta.dot(axis) - delta).normalized()
            hit, _, _, distance = tree.ray_cast(point, inward, .100)
            if hit is None:
                missed += 1
            else:
                distances.append(distance)
        if distances:
            return {"min_mm": mm(min(distances)), "max_mm": mm(max(distances)),
                    "method": "radial ray from tagged outer field to tagged inner field",
                    "rays": len(distances), "missed_rays": missed}
    flat = mesh.obj.get(f"panel_depth_pairs_{role}")
    if flat is not None:
        flat = list(flat)
        pairs = list(zip(flat[::2], flat[1::2]))
    elif raw := mesh.obj.get("v5c_depth_pairs"):
        pairs = json.loads(raw)
    else:
        return None
    used = indices_of(body)
    valid = [(a, b) for a, b in pairs if a in used and b in used]
    if not valid:
        return None
    distances = [(mesh.points[a] - mesh.points[b]).length for a, b in valid]
    return {"min_mm": mm(min(distances)), "max_mm": mm(max(distances)),
            "method": "builder-corresponding inner and outer structural vertex distances",
            "pairs": len(valid), "discarded_pairs": len(pairs) - len(valid)}


def front_depth_pair(front, under, step):
    origin, (face, substrate) = projected_masks((front, under), VIEWS["front"], step)
    overlap = np.argwhere(face & substrate)
    fore_bottom, fore_top = axis_bounds(points_of(front), 2)
    under_bottom, under_top = axis_bounds(points_of(under), 2)
    vertical = mm(min(fore_top, under_top) - max(fore_bottom, under_bottom))
    front_tree, under_tree = bvh(*front), bvh(*under)
    crossings = len(front_tree.overlap(under_tree))
    if not len(overlap):
        return {"overlap_area_mm2": 0.0, "vertical_overlap_mm": vertical,
                "front_depth_delta_mm": None, "frontmost_fraction": None, "rays": 0, "missed_rays": 0,
                "intersecting_triangle_pairs": crossings}
    ystart = min(axis_bounds(points_of(surface), 1)[0] for surface in (front, under)) - .05
    direction = Vector((0, 1, 0))
    depth, missed = [], 0
    for v, u in overlap:
        start = Vector((origin[0] + u * step, ystart, origin[1] + v * step))
        front_hit = front_tree.ray_cast(start, direction)[0]
        under_hit = under_tree.ray_cast(start, direction)[0]
        if front_hit is None or under_hit is None:
            missed += 1
        else:
            depth.append(under_hit.y - front_hit.y)
    return {"overlap_area_mm2": round(len(overlap) * (step * 1000) ** 2, 2),
            "vertical_overlap_mm": vertical,
            "front_depth_delta_mm": [mm(min(depth)), mm(max(depth))] if depth else None,
            "frontmost_fraction": round(sum(d >= 0 for d in depth) / len(depth), 4) if depth else None,
            "rays": len(depth), "missed_rays": missed,
            "intersecting_triangle_pairs": crossings}


def straight_greave_bottom(geometry, step):
    origin, (mask,) = projected_masks((geometry,), VIEWS["front"], step)
    occupied = np.argwhere(mask)
    low_row = np.min(occupied[:, 0])
    # Ignore intentional clipped corners. Find the low-edge span 5 mm above
    # the lowest pixel and check how far the bottom rises in its central 70%.
    station = low_row + max(1, round(.005 / step))
    span = np.flatnonzero(mask[min(station, mask.shape[0] - 1)])
    if len(span) < 4:
        return None
    trim = round(len(span) * .15)
    central = span[trim:len(span) - trim]
    edge_rows = [int(np.flatnonzero(mask[:, u])[0]) for u in central]
    return {"central_columns": len(central),
            "height_bounds_mm": [mm(origin[1] + row * step) for row in (min(edge_rows), max(edge_rows))],
            "vertical_variation_mm": mm((max(edge_rows) - min(edge_rows)) * step)}


def wrap_and_taper(plate, garment):
    plate_tree = bvh(*plate)
    plate_points = points_of(plate)
    lo, hi = axis_bounds(plate_points, 2)
    sections = []
    for fraction in (.20, .50, .80):
        z = lo + fraction * (hi - lo)
        cloth_slice = plane_slice(*garment, 2, z)
        shell_slice = plane_slice(*plate, 2, z)
        if not cloth_slice or not shell_slice:
            continue
        origin = Vector((sum(axis_bounds(cloth_slice, 0)) / 2,
                         sum(axis_bounds(cloth_slice, 1)) / 2, z))
        count = 1440
        hits, radii = [], []
        for i in range(count):
            angle = 2 * pi * i / count
            direction = Vector((sin(angle), -cos(angle), 0))
            hit, _, _, distance = plate_tree.ray_cast(origin, direction, .5)
            hits.append(hit is not None)
            if hit is not None:
                radii.append(distance)
        cloth_width = np.ptp([point.x for point in cloth_slice])
        shell_width = np.ptp([point.x for point in shell_slice])
        sections.append({"z_m": round(z, 6), "fraction_from_bottom": fraction,
                         "garment_section_center_xyz_m": list(origin),
                         "covered_angle_deg": sum(hits) * 360 / count,
                         "first_hit_radius_mm": [mm(min(radii)), mm(max(radii))] if radii else None,
                         "angular_runs": sum(hit and not hits[i - 1] for i, hit in enumerate(hits)),
                         "front": hits[0], "positive_x": hits[count // 4],
                         "back": hits[count // 2], "negative_x": hits[3 * count // 4],
                         "plate_width_mm": mm(shell_width), "limb_width_mm": mm(cloth_width),
                         "width_ratio": round(float(shell_width / cloth_width), 4) if cloth_width else None})
    return sections


def mirrored_error(left, right):
    def offset(source, target):
        tree = bvh(*target)
        return max(tree.find_nearest(Vector((-v.x, v.y, v.z)))[3]
                   for v in points_of(source))

    return mm(max(offset(left, right), offset(right, left)))


def side_of(mesh):
    side = mesh.obj.get("leg_side")
    if side in ("L", "R"):
        return side
    name = mesh.obj.name
    for side in ("L", "R"):
        if name.startswith(f"{side} ") or f"_{side}_" in name:
            return side
    return None


def role_spec(mesh):
    if "v5c_plate" in mesh.attributes and mesh.obj.get("part") != "leg_plates":
        return "v5c_plate", SHOULDER_ROLES
    return "armor_component", LEG_ROLES


def plate_record(mesh, label, region, role, triangles, garment, args):
    islands = list(connected_triangle_sets(triangles))
    inner = mesh.tagged("v5c_inner", role)
    if not inner:
        raise ValueError("Missing v5c_inner FACE tag")
    # Attached hardware can share armor_component. Retain all structural islands
    # identified by true inner faces and count all tagged triangles separately.
    inner_vertices = {i for tri in inner for i in tri}
    structural = [tri for island in islands
                  if any(i in inner_vertices for tri in island for i in tri)
                  for tri in island]
    if len(set(inner) - set(structural)):
        raise ValueError("Inner face tags fall outside structural plate")
    geometry = mesh.points, structural
    vertices = points_of(geometry)
    extent = [mm(hi - lo) for lo, hi in (axis_bounds(vertices, axis) for axis in range(3))]
    gap = surface_gap(mesh.points, inner, garment, args.gap_step)
    clearance = [3, 8] if region == "boot" else [5, 12]
    projections = {view: overshoot(garment, geometry, axes, args.projection_step)
                   for view, axes in VIEWS.items()}
    limit = 35 if region == "sleeve" else 20
    thickness_record = thickness(mesh, role, geometry, inner, args.gap_step)
    topo = topology(*geometry)
    body_tree = bvh(*geometry)
    topo["nonadjacent_triangle_crossings"] = nonadjacent_surface_crossings(body_tree, structural)
    record = {"mesh": mesh.obj.name, "role": role, "size_xyz_mm": extent,
              "triangles": len(structural), "inner_triangles": len(inner),
              "other_tagged_triangles": len(triangles) - len(structural),
              "gap_mm": gap, "gap_limits_mm": clearance,
              "sampled_gap_pass": clearance[0] <= gap["min_mm"] <= gap["max_mm"] <= clearance[1]
              and not gap["intersecting_triangle_pairs"] and not gap["below_local_normal_samples"],
              "contour_overshoot": projections, "contour_limit_mm": limit,
              "sampled_contour_pass": all(v["max_mm"] <= limit for v in projections.values()),
              "thickness_mm": thickness_record, "topology": topo,
              "closed_consistent_nondegenerate_body": not any(
                  topo[key] for key in ("boundary_edges", "non_manifold_edges",
                                        "non_manifold_vertex_fans",
                                        "inconsistent_winding_edges", "degenerate_triangles",
                                        "nonadjacent_triangle_crossings")),
              "structural_crossing_pairs_with_garment": len(body_tree.overlap(bvh(*garment)))}
    if region == "sleeve":
        outer = mesh.tagged("v5c_outer", role) or structural
        sleeve = bvh(*garment)
        record["outer_field_nearest_sleeve_max_mm"] = mm(max(
            sleeve.find_nearest(point)[3] for point in triangle_samples(mesh.points, outer, args.gap_step)))
        record["sampled_sleeve_standoff_pass"] = record["outer_field_nearest_sleeve_max_mm"] <= 35
    if label in {"thigh_outer", "shin_greave", "rear_calf", "ankle_cuff"}:
        record["wrap_sections"] = wrap_and_taper(geometry, garment)
    if label == "shin_greave":
        record["front_projected_bottom_edge"] = straight_greave_bottom(geometry, args.projection_step)
    if label == "knee_cap":
        center_x = sum(axis_bounds(vertices, 0)) * .5
        center_z = sum(axis_bounds(vertices, 2)) * .5
        start = Vector((center_x, axis_bounds(vertices, 1)[0] - .01, center_z))
        direction = Vector((0, 1, 0))
        tree = bvh(*geometry)
        front = tree.ray_cast(start, direction)[0]
        back = tree.ray_cast(start + Vector((0, extent[1] / 1000 + .02, 0)), -direction)[0]
        record["center_depth_mm"] = mm(back.y - front.y) if front and back else None
        cloth_start = start.copy()
        cloth_start.y = min(start.y, axis_bounds(garment[0], 1)[0] - .01)
        cloth_front = bvh(*garment).ray_cast(cloth_start, direction)[0]
        record["center_forward_projection_over_trousers_mm"] = (
            mm(cloth_front.y - front.y) if front and cloth_front else None)
    return geometry, record


def report_lod(root, rig, args, errors):
    graph = bpy.context.evaluated_depsgraph_get()
    meshes = [Mesh(obj, graph) for obj in root.all_objects if obj.type == "MESH"]
    garments = {}
    trousers = next(mesh for mesh in meshes if mesh.obj.name.startswith("Undersuit | Combat trousers LOD"))
    midline = plane_slice(trousers.points, trousers.triangles, 0, 0)
    crotch = min(midline, key=lambda point: point.z) if midline else None
    for region, name in {"thigh": "trousers", "calf": "trousers", "knee": "trousers",
                         "boot": "boots", "sleeve": "shirt"}.items():
        garment = next(mesh for mesh in meshes
                       if mesh.obj.name.startswith(f"Undersuit | Combat {name} LOD"))
        for side in ("L", "R"):
            geometry, planes = garment_region(garment, rig, side, region)
            garments[region, side] = (geometry, {"mesh": garment.obj.name, "isolation_planes": planes,
                                                  "triangles": len(geometry[1])})

    plates, geometry = {}, {}
    for mesh in meshes:
        side = side_of(mesh)
        if side is None:
            continue
        tag, roles = role_spec(mesh)
        for role, (label, region) in roles.items():
            if not (triangles := mesh.tagged(tag, role)):
                continue
            key = f"{label}.{side}"
            reference, reference_info = garments[region, side]
            try:
                geometry[key], plates[key] = plate_record(mesh, label, region, role, triangles,
                                                          reference, args)
                plates[key]["worn_reference"] = reference_info
            except ValueError as error:
                errors.append(f"{root.name}/{key}: {error}")

    wearer = wearer_tree(meshes)
    checks = {}
    symmetry = {}
    for label, _ in (*LEG_ROLES.values(), *SHOULDER_ROLES.values()):
        left, right = (f"{label}.{side}" for side in ("L", "R"))
        if left in geometry and right in geometry:
            symmetry[label] = {"mirror_sampled_max_mm": mirrored_error(geometry[left], geometry[right]),
                               "matched_triangle_count": plates[left]["triangles"] == plates[right]["triangles"]}
        elif label != "rear_calf" or left in geometry or right in geometry:
            for key in (left, right):
                if key not in geometry:
                    errors.append(f"{root.name}/{key}: plate unavailable")
    for side in ("L", "R"):
        parts = {name: geometry[key] for key in geometry
                 if key.endswith(f".{side}") for name in [key.rsplit(".", 1)[0]]}
        result = checks[side] = {}
        for label in THIGH_NAMES:
            if label in parts:
                reference = garments["thigh", side][0]
                plates[f"{label}.{side}"]["visible_projection"] = {
                    view: visible_projection(reference, parts[label], wearer, view, side,
                                             args.projection_step)
                    for view in VIEWS
                }
        if all(label in parts for label in THIGH_NAMES):
            reference = garments["thigh", side][0]
            points = parts["thigh_outer"][0]
            if all(parts[label][0] is points for label in THIGH_NAMES):
                assembly = points, [tri for label in THIGH_NAMES for tri in parts[label][1]]
                result["whole_thigh_wrap_sections"] = wrap_and_taper(assembly, reference)
                if crotch is not None:
                    nearest, _, _, distance = bvh(*assembly).find_nearest(crotch)
                    result["crotch_clearance"] = {"min_mm": mm(distance), "landmark_xyz_m": list(crotch),
                                                  "nearest_armor_xyz_m": list(nearest)}
        if all(name in parts for name in ("shin_greave", "ankle_cuff")):
            greave_base = axis_bounds(points_of(parts["shin_greave"]), 2)[0]
            cuff_top = axis_bounds(points_of(parts["ankle_cuff"]), 2)[1]
            result["greave_bottom_to_cuff_top_vertical_mm"] = mm(greave_base - cuff_top)
        if "knee_cap" in parts:
            for label in ("shin_greave", *THIGH_NAMES):
                if label in parts:
                    result[f"knee_over_{label}"] = front_depth_pair(
                        parts["knee_cap"], parts[label], args.projection_step)
    return {"triangles": sum(len(mesh.triangles) for mesh in meshes),
            "plates": dict(sorted(plates.items())), "adjacency": checks, "symmetry": symmetry}


def show_layers(layer):
    layer.exclude = False
    layer.hide_viewport = False
    for child in list(layer.children):
        show_layers(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "v5c" / "QA.json")
    parser.add_argument("--gap-step", type=float, default=.001, help="max inner surface sample edge in metres")
    parser.add_argument("--projection-step", type=float, default=.0005, help="projected raster pitch in metres")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if min(args.gap_step, args.projection_step) <= 0:
        parser.error("sampling pitches must be positive")

    for collection in list(bpy.data.collections):
        collection.hide_viewport = False
    show_layers(bpy.context.view_layer.layer_collection)
    rig = bpy.data.objects["EFT_Bind"]
    apply_pose(rig, "rest")
    with Path(bpy.data.filepath).open("rb") as source:
        digest = file_digest(source, "sha256").hexdigest()
    report = {"blend": bpy.data.filepath, "sha256": digest, "pose": "rest", "lods": {}, "errors": [],
              "method": {
                  "gap_step_mm": mm(args.gap_step),
                  "gap": ("Nearest distance to actual evaluated garment triangles, sampled on a barycentric "
                          "net over tagged skin-facing triangles. The unsigned maximum is at most one mesh "
                          "step greater than its sample and the minimum at most one step smaller. An "
                          "exact BVH triangle intersection sets the minimum to zero. Local normal signs "
                          "flag likely inward samples on open garments and are not a volume test."),
                  "projection_pitch_mm": mm(args.projection_step),
                  "projection": ("Orthographic front XZ and side YZ triangle unions on a common raster. "
                                 "Maximum Euclidean distance from exterior plate contour pixels to the "
                                 "nearest isolated garment contour pixel; subpixel features can be missed. "
                                 "The plate contour uses structural body triangles only."),
                  "visible_thigh": ("Orthographic first-hit rays on matching LOD geometry measured from "
                                    "front -Y or anatomical exterior X. Subject to occlusion from clothing, "
                                    "frame, hardware and adjacent plates in that LOD."),
                  "garment": ("Matching worn LOD base garment meshes. Clipped triangles preserve the "
                              "actual garment shape. Ipsilateral trousers are clipped around the relevant "
                              "joint with 45 mm knee overlap for thigh and calf, a 130 mm region each way "
                              "for knee, sleeve deltoid isolated with lateral and humeral planes, and boot "
                              "isolated by sagittal plane. Separate trim and laces are excluded."),
                  "wrap": ("World-Z slices through each plate. Rays sweep from the center of each same "
                           "height garment cross-section, 0 degrees toward front (-Y)."),
                  "crotch": ("Nearest thigh assembly surface to the lowest point of the worn trousers' "
                              "intersection with the anatomical sagittal plane X=0."),
                  "knee_overlap": ("Common front projection raster area. From -Y, positive front depth delta "
                                   "means knee armor is in front of the adjacent plate along that ray."),
                  "symmetry": ("Bidirectional nearest-surface distance between reflected vertices and the "
                               "opposite side structural triangles, mirrored across world X=0."),
              }}
    for lod in range(2):
        root = bpy.data.collections[f"EXO_LOD{lod}"]
        for obj in list(root.all_objects):
            obj.hide_set(False)
            obj.hide_viewport = False
        bpy.context.view_layer.update()
        report["lods"][f"LOD{lod}"] = report_lod(root, rig, args, report["errors"])
        print(f"V5C QA LOD{lod}: {len(report['lods'][f'LOD{lod}']['plates'])} measured plates", flush=True)
    count0, count1 = (report["lods"][f"LOD{i}"]["triangles"] for i in range(2))
    report["lod1_lod0_ratio"] = round(count1 / count0, 4) if count0 else None
    report["lod0_budget_pass"] = count0 <= 80000
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"V5C QA {args.out} | triangles {count0}/{count1} | {len(report['errors'])} missing measurements")
    if report["errors"]:
        raise RuntimeError("\n".join(report["errors"]))


if __name__ == "__main__":
    main()
