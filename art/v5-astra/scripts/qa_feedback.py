"""Independent scene, armor and drivetrain checks for the V5b review."""

from collections import defaultdict
from hashlib import sha256
from itertools import pairwise, combinations
import json
from math import cos, hypot, isfinite, pi, sin

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


CONTACT_LIMIT = .001
LOWER_CHAIN = ("belt", "hip_shoe", "hip", "thigh_1", "thigh_splice",
               "thigh_2", "knee", "shin_1", "shin_splice", "shin_2", "ankle", "stirrup")
UPPER_CHAIN = ("spine", "shoulder", "upper_arm", "elbow", "forearm", "wrist")
PANELS = {
    1: "thigh_shell", 3: "knee_cap", 4: "shin_greave",
    5: "ankle_cuff", 6: "outsole", 7: "instep_cover",
}


def check_inventory(scene, collections, references, errors, partial):
    worn = [{obj.name for obj in root.all_objects if obj.type == "MESH"} for root in collections]
    witnesses = {obj.name for obj in references}
    meshes = {obj.name for obj in scene.objects if obj.type == "MESH"}
    unknown = meshes - witnesses - set.union(*worn)
    overlap = worn[0] & worn[1]
    if unknown:
        errors.append(f"Unclassified meshes in the scene: {sorted(unknown)}")
    if overlap:
        errors.append(f"Meshes shared between LOD collections: {sorted(overlap)}")
    if not partial and witnesses != {"REF_top", "REF_pants", "REF_head"}:
        errors.append(f"Missing native body witnesses: {sorted(witnesses)}")
    for index, root in enumerate(collections):
        inactive = {obj.name for obj in root.all_objects if obj.type == "MESH" and obj.hide_render}
        if inactive:
            errors.append(f"{root.name}: render-hidden wearer meshes: {sorted(inactive)}")
        if not partial and bool(index) != root.hide_render:
            errors.append(f"{root.name}: expected only LOD0 active in the canonical blend")
    for obj in references:
        active = not obj.hide_render and all(not coll.hide_render for coll in obj.users_collection)
        if not active:
            errors.append(f"{obj.name} native witness is unavailable to render")
    return {"native_witnesses": sorted(witnesses), "unclassified": sorted(unknown),
            "shared_lod_meshes": sorted(overlap), "worn_mesh_counts": [len(items) for items in worn]}


def check_materials(scene, errors):
    owners = defaultdict(set)
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        for face in obj.data.polygons:
            index = face.material_index
            material = obj.material_slots[index].material if index < len(obj.material_slots) else None
            if material:
                owners[material.name].add(obj.name)
            else:
                owners[None].add(obj.name)
    if None in owners:
        errors.append(f"Missing material on mesh faces: {sorted(owners.pop(None))}")
    materials = {}
    for name, models in sorted(owners.items()):
        mat = bpy.data.materials[name]
        tree = mat.node_tree
        if not mat.use_nodes or tree is None or len(tree.nodes) != 2 or len(tree.links) != 1:
            errors.append(f"{name}: expected one constant Principled shader linked to one output")
            continue
        link = tree.links[0]
        shader = link.from_node
        if (shader.type != "BSDF_PRINCIPLED" or link.to_node.type != "OUTPUT_MATERIAL"
                or link.to_socket.name != "Surface" or not link.to_node.is_active_output):
            errors.append(f"{name}: surface is not a constant Principled BSDF")
            continue
        rgba = list(shader.inputs["Base Color"].default_value)
        values = {key: shader.inputs[key].default_value
                  for key in ("Roughness", "Metallic", "Alpha", "Transmission Weight")}
        if not all(isfinite(value) for value in (*rgba, *values.values())):
            errors.append(f"{name}: nonfinite constant material values")
        if values["Alpha"] != 1 or values["Transmission Weight"] != 0:
            errors.append(f"{name}: expected an opaque material")
        materials[name] = {"color_linear_rgba": rgba, "inputs": values, "meshes": sorted(models)}
    image_nodes = []
    for group in bpy.data.node_groups:
        image_nodes.extend(f"{group.name}/{node.name}" for node in group.nodes
                           if node.type in {"TEX_IMAGE", "TEX_ENVIRONMENT", "NORMAL_MAP"})
    for material in bpy.data.materials:
        if material.node_tree:
            image_nodes.extend(f"{material.name}/{node.name}" for node in material.node_tree.nodes
                               if node.type in {"TEX_IMAGE", "TEX_ENVIRONMENT", "NORMAL_MAP"})
    if scene.world and scene.world.node_tree:
        image_nodes.extend(f"World/{node.name}" for node in scene.world.node_tree.nodes
                           if node.type in {"TEX_IMAGE", "TEX_ENVIRONMENT"})
    images = sorted(img.name for img in bpy.data.images
                    if img.type != "RENDER_RESULT" and img.name != "Viewer Node")
    if images or image_nodes:
        errors.append(f"Unexpected image data or map nodes: {images + image_nodes}")
    if any(layer.material_override for layer in scene.view_layers):
        errors.append("Scene contains a render material override")
    return {"surfaces": materials, "images": images, "map_nodes": image_nodes}


def plane_slice(vertices, triangles, axis, level):
    points = []
    # A transverse plane can be world aligned or have a supplied longitudinal normal.
    coordinates = [point[axis] if isinstance(axis, int) else point.dot(axis)
                   for point in vertices]
    for triangle in triangles:
        a, b, c = triangle
        for start, end in ((a, b), (b, c), (c, a)):
            first, last = coordinates[start], coordinates[end]
            if first == level:
                points.append(vertices[start])
            elif first < level < last or last < level < first:
                points.append(vertices[start].lerp(vertices[end], (level - first) / (last - first)))
    return points


def tagged_armor(surfaces):
    result = defaultdict(dict)
    for surface in surfaces:
        if surface.obj.get("part") != "leg_plates" or not surface.armor_roles:
            continue
        side = side_of(surface)
        for role in PANELS:
            result[side][role] = (surface, [
                tri for tri, face in zip(surface.triangles, surface.triangle_faces)
                if surface.armor_roles[face] == role
            ])
    return result


def side_of(surface):
    return surface.obj.get("leg_side") or next(
        (side for side in ("L", "R") if f"_{side}_" in surface.obj.name), "?")


def shell_profile(component, trousers, side, fraction=.50):
    low, high = component.low[2], component.high[2]
    mid = low + (high - low) * fraction
    sign = 1 if side == "L" else -1
    section = [point for trouser in trousers for point in
               plane_slice(trouser.vertices, trouser.triangles, 2, mid) if sign * point.x > 0]
    if not section:
        return None
    center = Vector((*((min(v[axis] for v in section) + max(v[axis] for v in section)) * .5
                       for axis in (0, 1)), mid))
    count = 1440
    coverage = []
    for index in range(count):
        angle = 2 * pi * index / count
        direction = Vector((sign * sin(angle), -cos(angle), 0))
        coverage.append(component.tree.ray_cast(center, direction, .5)[0] is not None)
    used = sum(coverage)
    # Angle convention is anatomical and shared by both legs.
    return {"center_m": list(center), "ray_step_deg": 360 / count,
            "covered_angle_deg": 360 * used / count,
            "angular_runs": sum(hit and not coverage[i-1] for i, hit in enumerate(coverage)),
            "front": coverage[0], "outer": coverage[count // 4],
            "back": coverage[count // 2], "inner": coverage[3 * count // 4]}


def panel_geometry(surfaces, rig, lod, errors):
    measurements = {}
    armor = tagged_armor(surfaces)
    trousers = [surf for surf in surfaces if surf.obj.name.startswith("Undersuit | Combat trousers")]
    for side in ("L", "R"):
        for role, label in PANELS.items():
            key = f"{label}.{side}"
            if role not in armor[side] or not armor[side][role][1]:
                errors.append(f"LOD{lod}: missing evaluated triangles for {key}")
                continue
            surface, triangles = armor[side][role]
            islands = list(connected_triangle_sets(triangles))
            # Details can share the role. The structural plate is the largest connected island.
            body = max(islands, key=len)
            component = Component(surface, body)
            low, high = component.low[2], component.high[2]
            span = high - low
            geometry = ([tuple(vertex) for vertex in component.points], component.triangles)
            fingerprint = sha256(json.dumps(geometry, separators=(",", ":")).encode()).hexdigest()
            record = {"mesh": surface.obj.name, "triangles": len(triangles),
                      "evaluated_principal_mesh_sha256": fingerprint,
                      "principal_island_triangles": len(body), "islands": len(islands),
                      "principal_surface_closed": component.closed,
                      "height_mm": round(span * 1000, 2),
                      "vertical_bounds_m": [round(low, 5), round(high, 5)]}
            measurements[key] = record
            pairs = list(surface.obj.get(f"panel_depth_pairs_{role}", ()))
            if role in (1, 4, 5, 7):
                indices = {index for tri in triangles for index in tri}
                if not pairs or len(pairs) % 2 or any(index not in indices for index in pairs):
                    errors.append(f"LOD{lod} {key}: missing valid plate thickness pairs")
                else:
                    depths = [(surface.vertices[b] - surface.vertices[a]).length
                              for a, b in zip(pairs[::2], pairs[1::2])]
                    record.update(min_depth_mm=round(min(depths) * 1000, 2),
                                  max_depth_mm=round(max(depths) * 1000, 2),
                                  depth_pairs=len(depths))
                    if min(depths) < .0119 or max(depths) > .0201:
                        errors.append(f"LOD{lod} {key}: measured plate depth outside 12-20 mm")
            if role == 3:
                # Measure the closed base and crown at the panel center.
                x = (component.low[0] + component.high[0]) * .5
                z = (low + high) * .5
                direction = Vector((0, 1, 0))
                hits = ray_hits(component, Vector((x, component.low[1] - .01, z)), direction)
                if len(hits) == 2:
                    depth = (hits[1] - hits[0]).length
                    record["center_depth_mm"] = round(depth * 1000, 2)
                    if not .0119 <= depth <= .0201:
                        errors.append(f"LOD{lod} {key}: central cap depth outside 12-20 mm")
                else:
                    errors.append(f"LOD{lod} {key}: center ray did not find a closed cap")
            if role not in (1, 4):
                continue
            profile = shell_profile(component, trousers, side)
            record["mid_section"] = profile
            if profile is None:
                errors.append(f"LOD{lod} {key}: missing trouser cross section")
                continue
            continuous = profile["angular_runs"] == 1
            if role == 1:
                # A vent can open the middle ray ring in LOD1. Keep the raw
                # section and corroborate its structural envelope nearby.
                neighbor_sections = [shell_profile(component, trousers, side, fraction)
                                     for fraction in (.40, .45, .55, .60)]
                record["adjacent_sections"] = neighbor_sections
                if not any(177 <= section["covered_angle_deg"] <= 203 and
                           section["angular_runs"] == 1 and section["front"] and
                           section["outer"] and not section["inner"]
                           for section in [profile, *neighbor_sections] if section):
                    errors.append(f"LOD{lod} {key}: missing contiguous front-and-outer wrap near 180-200 deg")
            if role == 4:
                if not (continuous and profile["front"] and profile["outer"]
                        and profile["inner"] and not profile["back"]):
                    errors.append(f"LOD{lod} {key}: expected contiguous front and bilateral side coverage, got {profile}")
                widths = []
                for fraction in (.22, .78):
                    points = plane_slice(surface.vertices, body, 2, low + span * fraction)
                    widths.append(max(v.x for v in points) - min(v.x for v in points))
                record["lower_upper_width_mm"] = [round(width * 1000, 2) for width in widths]
                calf_name, ankle_name = f"Base Human{side}Calf", f"Base Human{side}Foot"
                knee_z = (rig.matrix_world @ rig.data.bones[calf_name].head_local).z
                ankle_z = (rig.matrix_world @ rig.data.bones[ankle_name].head_local).z
                record["knee_to_top_mm"] = round((knee_z - high) * 1000, 2)
                record["bottom_to_ankle_mm"] = round((low - ankle_z) * 1000, 2)
                record["anatomical_shin_span_ratio"] = round(span / (knee_z - ankle_z), 3)
                if widths[1] <= widths[0]:
                    errors.append(f"LOD{lod} {key}: greave should taper towards the ankle")
        if not all(f"{part}.{side}" in measurements
                   for part in ("thigh_shell", "knee_cap", "shin_greave", "ankle_cuff")):
            continue
        thigh = measurements[f"thigh_shell.{side}"]
        knee = measurements[f"knee_cap.{side}"]
        shin = measurements[f"shin_greave.{side}"]
        cuff = measurements[f"ankle_cuff.{side}"]
        overlap = knee["vertical_bounds_m"][1] - thigh["vertical_bounds_m"][0]
        shin_to_knee = knee["vertical_bounds_m"][0] - shin["vertical_bounds_m"][1]
        shin_to_cuff = shin["vertical_bounds_m"][0] - cuff["vertical_bounds_m"][1]
        thigh["knee_cap_vertical_overlap_mm"] = round(overlap * 1000, 2)
        shin["knee_cap_to_greave_gap_mm"] = round(shin_to_knee * 1000, 2)
        shin["greave_to_ankle_cuff_gap_mm"] = round(shin_to_cuff * 1000, 2)
        if overlap <= 0:
            errors.append(f"LOD{lod}: thigh shell lower edge does not overlap knee cap on {side}")
        if max(shin_to_knee, shin_to_cuff) > .025:
            errors.append(f"LOD{lod}: greave does not reach from below knee cap to ankle cuff on {side}")
    return measurements


class Component:
    """An evaluated mesh island within one tagged mechanical node."""

    def __init__(self, surface, triangles):
        self.name = surface.obj.name
        vertices = sorted({i for tri in triangles for i in tri})
        self.points = [surface.vertices[index] for index in vertices]
        indices = {index: offset for offset, index in enumerate(vertices)}
        local_triangles = [tuple(indices[index] for index in tri) for tri in triangles]
        self.triangles = local_triangles
        self.tree = BVHTree.FromPolygons(self.points, local_triangles, all_triangles=True)
        incidence = defaultdict(int)
        for a, b, c in local_triangles:
            for edge in ((a, b), (b, c), (c, a)):
                incidence[tuple(sorted(edge))] += 1
        self.closed = all(count == 2 for count in incidence.values())
        self.low = tuple(min(v[axis] for v in self.points) for axis in range(3))
        self.high = tuple(max(v[axis] for v in self.points) for axis in range(3))

    def contact(self, other, limit=CONTACT_LIMIT):
        if any(max(lo - hi_other, lo_other - hi) > limit for lo, hi, lo_other, hi_other
               in zip(self.low, self.high, other.low, other.high)):
            return None
        overlap = self.tree.overlap(other.tree)
        if overlap:
            return {"method": "triangle_overlap", "gap_mm": 0, "triangle_pairs": len(overlap)}
        nearest = limit
        point_pair = None
        for points, tree, reverse in ((self.points, other.tree, False),
                                      (other.points, self.tree, True)):
            for point in points:
                hit, _, _, gap = tree.find_nearest(point, nearest)
                if gap is not None and gap <= nearest:
                    nearest = gap
                    point_pair = (hit, point) if reverse else (point, hit)
        if point_pair:
            return {"method": "bidirectional_vertex_to_triangle", "gap_mm": round(nearest * 1000, 4),
                    "points_m": [[round(value, 5) for value in point] for point in point_pair]}
        return None


def connected_triangle_sets(triangles):
    adjacent = defaultdict(list)
    for index, triangle in enumerate(triangles):
        for vertex in triangle:
            adjacent[vertex].append(index)
    remaining = set(range(len(triangles)))
    while remaining:
        stack = [remaining.pop()]
        island = []
        while stack:
            triangle = triangles[stack.pop()]
            island.append(triangle)
            for vertex in triangle:
                for neighbor in adjacent.pop(vertex, ()):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
        yield island


def frame_components(surfaces, *, dimensions=False):
    components = defaultdict(list)
    for surface in surfaces:
        node = surface.obj.get("frame_node") if not dimensions else None
        tags = surface.obj.get("frame_nodes")
        if node:
            components[str(node)].extend(Component(surface, island)
                                         for island in connected_triangle_sets(surface.triangles))
        if tags:
            for name, ranges in json.loads(tags).items():
                is_dimension = name.startswith(("housing_", "can_", "boot_platform."))
                if is_dimension != dimensions:
                    continue
                if ranges and isinstance(ranges[0], int):
                    ranges = [ranges]
                faces = {face for first, end in ranges for face in range(first, end)}
                triangles = [tri for tri, face in zip(surface.triangles, surface.triangle_faces) if face in faces]
                components[name].extend(Component(surface, island)
                                        for island in connected_triangle_sets(triangles))
    return components


BRACKETS = {
    "thigh_bracket_825": (1, "thigh_1"),
    "thigh_bracket_660": (1, "thigh_2"),
    "shin_bracket_394": (4, "shin_1"),
    "shin_bracket_180": (4, "shin_2"),
}
HARD_DRIVE = (
    "hip_shoe", "hip", "thigh_1", "thigh_splice", "thigh_2", "knee",
    "shin_1", "shin_splice", "shin_2", "ankle",
)
PENETRATION_EPSILON = .00002


def ray_hits(component, origin, direction):
    hits = []
    while True:
        hit, _, _, _ = component.tree.ray_cast(origin, direction)
        if hit is None:
            return hits
        hits.append(hit)
        origin = hit + direction * PENETRATION_EPSILON


def inside_closed(component, point):
    if not component.closed or not all(
            lo + PENETRATION_EPSILON < value < hi - PENETRATION_EPSILON
            for value, lo, hi in zip(point, component.low, component.high)):
        return False
    if component.tree.find_nearest(point)[3] <= PENETRATION_EPSILON:
        return False
    inside_votes = 0
    for vector in ((1, .287, .169), (.219, 1, -.347), (-.413, .379, 1)):
        direction = Vector(vector).normalized()
        inside_votes += len(ray_hits(component, point, direction)) % 2
    return inside_votes >= 2


def penetration(left, right):
    if any(max(lo - hi_other, lo_other - hi) > 0 for lo, hi, lo_other, hi_other
           in zip(left.low, left.high, right.low, right.high)):
        return None
    crossing = left.tree.overlap(right.tree)
    if crossing:
        armor_tri, drive_tri = crossing[0]
        left_center = sum((left.points[i] for i in left.triangles[armor_tri]), Vector()) / 3
        right_center = sum((right.points[i] for i in right.triangles[drive_tri]), Vector()) / 3
        return {"triangle_pairs": len(crossing), "method": "evaluated_triangle_overlap",
                "triangle_centers_m": [[round(value, 5) for value in center]
                                       for center in (left_center, right_center)]}
    # Disjoint closed surfaces can still overlap by complete containment.
    for inner, outer in ((left, right), (right, left)):
        if all(outer.low[axis] <= inner.low[axis] and inner.high[axis] <= outer.high[axis]
               for axis in range(3)) and inside_closed(outer, inner.points[0]):
            return {"triangle_pairs": 0, "method": "closed_island_containment"}
    return None


def closest_contact(left, right, limit=.05):
    return min((hit for a in left for b in right if (hit := a.contact(b, limit))),
               key=lambda hit: hit["gap_mm"], default=None)


def contact_path(brackets, shell, housing):
    shell_hits = [closest_contact([part], shell, CONTACT_LIMIT) for part in brackets]
    housing_hits = [closest_contact([part], housing, CONTACT_LIMIT) for part in brackets]
    pending = [i for i, contact in enumerate(shell_hits) if contact]
    target = {i for i, contact in enumerate(housing_hits) if contact}
    visited = set(pending)
    while pending:
        i = pending.pop()
        if i in target:
            return True
        for j, other in enumerate(brackets):
            if j not in visited and brackets[i].contact(other):
                visited.add(j)
                pending.append(j)
    return False


def leg_connections(surfaces, nodes, lod, pose, errors):
    prefix = f"LOD{lod} {pose}"
    armor = tagged_armor(surfaces)
    contacts, collisions = {}, []
    for side in ("L", "R"):
        side_nodes = {name: nodes.get(f"{name}.{side}", []) for name in
                      (*HARD_DRIVE, *BRACKETS, "stirrup")}
        roles = {}
        for role, (surface, faces) in armor[side].items():
            islands = list(connected_triangle_sets(faces))
            roles[role] = [Component(surface, island)
                           for island in sorted(islands, key=len, reverse=True)]
        for bracket, (role, housing) in BRACKETS.items():
            key = f"{bracket}.{side}"
            faces = roles.get(role, [])[:1]
            brackets = side_nodes[bracket]
            mates = {"shell": closest_contact(brackets, faces),
                     "housing": closest_contact(brackets, side_nodes[housing])}
            path = contact_path(brackets, faces, side_nodes[housing])
            contacts[key] = {**mates, "connected_path": path}
            if not path and all(mate and mate["gap_mm"] <= CONTACT_LIMIT * 1000 for mate in mates.values()):
                errors.append(f"{prefix}: shell and housing contact separate islands of {key}")
            for part, mate in mates.items():
                if mate is None or mate["gap_mm"] > CONTACT_LIMIT * 1000:
                    errors.append(f"{prefix}: missing bracket-to-{part} contact for {key} ({mate})")
        for role in (1, 3, 4, 5, 7):
            for drive_side in ("L", "R"):
                for name in HARD_DRIVE:
                    drive = f"{name}.{drive_side}"
                    hits = [hit for shell in roles.get(role, []) for item in nodes.get(drive, [])
                            if (hit := penetration(shell, item))]
                    if hits:
                        pair = {"side": side, "armor": PANELS[role], "drive": drive, "hits": hits}
                        collisions.append(pair)
                        errors.append(f"{prefix}: hard drive intersects {PANELS[role]}.{side}: {drive}")
        mate = closest_contact(roles.get(6, []), side_nodes["stirrup"])
        contacts[f"outsole_to_stirrup.{side}"] = mate
        if mate is None or mate["gap_mm"] > CONTACT_LIMIT * 1000:
            errors.append(f"{prefix}: missing outsole-to-platform contact on {side}")
    return {"bracket_and_outsole_contacts": contacts, "hard_drive_penetrations": collisions}


def drive_geometry(surfaces, lod, errors):
    parts = frame_components(surfaces, dimensions=True)
    measurements = {}
    boot = next((item for item in surfaces if item.obj.name.startswith("Undersuit | Combat boots")), None)
    for side in ("L", "R"):
        labels = {"housing_thigh_1": (.050, .070, .040, .050),
                  "housing_thigh_2": (.050, .070, .040, .050),
                  "housing_shin_1": (.050, .070, .040, .050),
                  "housing_shin_2": (.050, .070, .040, .050),
                  "housing_shin_splice": (.050, .070, .040, .050),
                  "can_hip": (.100, .120), "can_knee": (.080, .090),
                  "can_ankle": (.055, .065), "boot_platform": ()}
        for label, limits in labels.items():
            key = f"{label}.{side}"
            islands = parts.get(key, [])
            if not islands:
                errors.append(f"LOD{lod}: missing evaluated drive dimensions for {key}")
                continue
            # The drive labels isolate the main casing, ring or load plate from cosmetic fixtures.
            points = [v for island in islands for v in island.points]
            mins, maxs = ([fn(v[i] for v in points) for i in range(3)] for fn in (min, max))
            x_span = maxs[0] - mins[0]
            if label.startswith("housing_"):
                # Find the casing's short side in the sagittal plane.
                # Measure depth in central slices so casing rake does not inflate X extent.
                def width_at(angle):
                    side_axis = Vector((0, cos(angle), sin(angle)))
                    projections = [v.dot(side_axis) for v in points]
                    return max(projections) - min(projections)

                angle, span = min(((step * pi / 360, width_at(step * pi / 360))
                                   for step in range(360)), key=lambda pair: pair[1])
                long_axis = Vector((0, -sin(angle), cos(angle)))
                stations = [v.dot(long_axis) for v in points]
                lo, hi = min(stations), max(stations)
                depths = []
                for fraction in (.20, .50, .80):
                    level = lo + (hi - lo) * fraction
                    section = [v for island in islands for v in
                               plane_slice(island.points, island.triangles, long_axis, level)]
                    depths.append(max(v.x for v in section) - min(v.x for v in section))
                depth = max(depths)
                measurements[key] = {"width_mm": round(span * 1000, 2),
                                     "depth_mm": round(depth * 1000, 2),
                                     "depth_sections_mm": [round(d * 1000, 2) for d in depths],
                                     "total_lateral_extent_mm": round(x_span * 1000, 2)}
                if not (limits[0] - .002 <= span <= limits[1] + .002
                        and limits[2] - .002 <= depth <= limits[3] + .002):
                    errors.append(f"LOD{lod} {key}: measured housing size {measurements[key]} outside nominal width and depth")
            elif label.startswith("can_"):
                # Cap axis is transverse. Measure max chord in side view.
                diameter = max(hypot(a.y - b.y, a.z - b.z) for a in points for b in points)
                measurements[key] = {"diameter_mm": round(diameter * 1000, 2)}
                if not limits[0] <= diameter <= limits[1]:
                    errors.append(f"LOD{lod} {key}: measured actuator diameter {diameter*1000:.2f} mm")
            elif boot:
                sign = 1 if side == "L" else -1
                boots = [v for v in boot.vertices if sign * v.x > 0]
                boot_width = max(v.x for v in boots) - min(v.x for v in boots)
                boot_bottom = min(v.z for v in boots)
                measurements[key] = {"platform_width_mm": round(x_span * 1000, 2),
                                     "boot_width_mm": round(boot_width * 1000, 2),
                                     "platform_depth_mm": round((maxs[1] - mins[1]) * 1000, 2),
                                     "platform_thickness_mm": round((maxs[2] - mins[2]) * 1000, 2),
                                     "platform_top_to_boot_bottom_mm": round((maxs[2] - boot_bottom)*1000, 2)}
                if x_span <= boot_width or not mins[2] < boot_bottom or maxs[2] > boot_bottom + .015:
                    errors.append(f"LOD{lod} {key}: expected wider-than-boot platform under the sole ({measurements[key]})")
            else:
                errors.append(f"LOD{lod} {key}: missing boot surface")
    return measurements


def fit_pair(left, right):
    return {"nearest_sample_within_250_mm": closest_contact(left, right, .25),
            "penetrations": [hit for a in left for b in right if (hit := penetration(a, b))]}


def adjacent_armor_fit(surfaces, lod, pose, errors):
    """Measure tasset/thigh and bracer/casing fit separately from lower-drive gates."""
    armor = tagged_armor(surfaces)
    waist = [item for item in surfaces if item.obj.get("part") == "waist_armor"]
    fit = {}
    for side in ("L", "R"):
        sign = 1 if side == "L" else -1
        thigh = armor[side].get(1)
        tassets = []
        for surface in waist:
            slots = [i for i, slot in enumerate(surface.obj.material_slots)
                     if slot.material and slot.material.name in {"Powerpack plate", "Powerpack edge"}]
            triangles = [tri for tri, face in zip(surface.triangles, surface.triangle_faces)
                         if surface.obj.data.polygons[face].material_index in slots
                         and all(surface.obj.data.vertices[i].co.x * sign > 0 for i in tri)]
            tassets.extend(Component(surface, island) for island in connected_triangle_sets(triangles))
        if thigh and thigh[1] and tassets:
            thigh_faces = max(connected_triangle_sets(thigh[1]), key=len)
            fit[f"hip_tasset_to_thigh_shell.{side}"] = fit_pair(
                tassets, [Component(thigh[0], thigh_faces)])
        else:
            errors.append(f"LOD{lod} {pose}: missing tasset or thigh fit mesh on {side}")
        bracer = next((item for item in surfaces
                       if item.obj.name.startswith(f"{side} Wraparound forearm bracer")), None)
        casing = next((item for item in surfaces
                       if item.obj.name.startswith(f"{side} Forearm actuator casing")), None)
        if bracer and casing:
            fit[f"forearm_bracer_to_forearm_casing.{side}"] = fit_pair(
                [Component(bracer, island) for island in connected_triangle_sets(bracer.triangles)],
                [Component(casing, island) for island in connected_triangle_sets(casing.triangles)])
        else:
            errors.append(f"LOD{lod} {pose}: missing forearm fit mesh on {side}")
    for label, record in fit.items():
        if record["penetrations"]:
            errors.append(f"LOD{lod} {pose}: evaluated armor fit intersection for {label}")
    return fit


def frame_contacts(surfaces, lod, pose, errors):
    nodes = frame_components(surfaces)
    prefix = f"LOD{lod} {pose}"
    chains = [(chain[0], *(f"{node}.{side}" for node in chain[1:]))
              for chain in (UPPER_CHAIN, LOWER_CHAIN) for side in ("L", "R")]
    interfaces = list(dict.fromkeys([("spine", "belt"), *(edge for chain in chains for edge in pairwise(chain))]))
    expected = {name for edge in interfaces for name in edge}
    missing = sorted(expected - {name for name, islands in nodes.items() if islands})
    if missing:
        errors.append(f"{prefix}: missing tagged mechanical nodes: {', '.join(missing)}")
    adjacency = defaultdict(set)
    interface_details = {}

    def connect(a, i, b, j):
        left, right = nodes[a][i], nodes[b][j]
        contact = left.contact(right)
        if contact:
            adjacency[(a, i)].add((b, j))
            adjacency[(b, j)].add((a, i))
            return {"islands": [i, j], "meshes": [left.name, right.name], **contact}
        return None

    for name, islands in nodes.items():
        for i, j in combinations(range(len(islands)), 2):
            connect(name, i, name, j)
    for a, b in interfaces:
        contacts = [hit for i in range(len(nodes[a])) for j in range(len(nodes[b]))
                    if (hit := connect(a, i, b, j))]
        record = {"contacts": contacts}
        if not contacts and a not in missing and b not in missing:
            evidence = [hit for left in nodes[a] for right in nodes[b]
                        if (hit := left.contact(right, .10))]
            closest = min(evidence, key=lambda hit: hit["gap_mm"], default=None)
            record["closest_sample_within_100_mm"] = closest
            distance = f"{closest['gap_mm']:g} mm" if closest else "> 100 mm"
            errors.append(f"{prefix}: no evaluated surface contact between {a} and {b} (sampled gap {distance})")
        interface_details[f"{a} -> {b}"] = record

    terminals = {chain[-1] for chain in chains}
    reaches = []
    for index in range(len(nodes["spine"])):
        pending = [("spine", index)]
        visited = set(pending)
        while pending:
            for neighbor in adjacency[pending.pop()] - visited:
                visited.add(neighbor)
                pending.append(neighbor)
        reaches.append(sorted(terminals & {name for name, _ in visited}))
    if not any(set(endpoints) == terminals for endpoints in reaches):
        errors.append(f"{prefix}: no single spine island reaches both wrists and both stirrups")
    return {"max_contact_gap_mm": CONTACT_LIMIT * 1000, "interfaces": interface_details,
            "islands_per_node": {name: len(items) for name, items in sorted(nodes.items())},
            "spine_reached_terminals": reaches,
            "leg_mating_surfaces": leg_connections(surfaces, nodes, lod, pose, errors),
            "adjacent_armor_fit": adjacent_armor_fit(surfaces, lod, pose, errors)}
