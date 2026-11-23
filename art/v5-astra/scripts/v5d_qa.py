"""Audit geometry, attachment, skinning and pose contacts of the saved V5D assembly."""
import argparse
from collections import Counter
from itertools import combinations
import json
from math import ceil, cos, radians, sin
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

ENTRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENTRY / "scripts"))
from poses import BONE, apply_pose
from qa import check_skin, near_matrix, layer_collections, pose_landmarks, SOCKETS
from qa_feedback import frame_components, plane_slice
from qa_frozen import (
    LOD_NAMES, compare_protected, digest, drive_contacts, fingerprint, lug_attachment_fit,
    object_signature, outsole_signature,
)
from qa_v5c import (
    LEG_ROLES, SHOULDER_ROLES, VIEWS, axis_bounds, bvh, clipped_triangles,
    connected_triangle_sets, garment_region, mm, nonadjacent_surface_crossings,
    overshoot, points_of, side_of, surface_gap, thickness, topology, wrap_and_taper,
)

BASELINE_HASH = "cc499155b83141574aad0b6ea2de5912bc465457c3f1bc71d53f9363f4bac072"
QA_POSES = ("rest", "walk", "crouch", "crouch_deep", "arms_raised", "arms_forward")
PROTECTED = {"arm_frame", "leg_frame", "upper_frame", "waist_armor", "carrier", "pack", "helmet", "thermal"}
ARM_ROLES = {
    "Outer biceps shell": ("upper_arm_outer", "upper_arm"),
    "Wraparound forearm bracer": ("forearm_outer", "forearm"),
    "Elbow impact cap": ("elbow_outer", "elbow"),
    "Dorsal glove guard": ("hand_old", "hand"),
}
EXTENDED_LEG_ROLES = {**LEG_ROLES, 14: ("heel_guard", "boot"), 15: ("achilles_guard", "ankle")}
GARMENTS = {
    "shirt": "Combat shirt", "trousers": "Combat trousers", "boot": "Combat boots",
    "hand": "Tactical gloves", "sleeve_cuff": "Sleeve cuffs",
}
XYZ = tuple(Vector(v) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
DEPTH_LIMIT = .010
INTERIOR_RAYS = tuple(Vector(v).normalized() for v in ((1, .287, .169), (.219, 1, -.347)))


class Mesh:
    """Retain evaluated surface vertices, triangles, and polygon-derived role tags."""

    def __init__(self, obj, graph):
        self.obj = obj
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            self.points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
            self.triangles = [tuple(tri.vertices) for tri in mesh.loop_triangles]
            self.triangle_faces = [tri.polygon_index for tri in mesh.loop_triangles]
            material_names = [mat.name if mat else "unassigned" for mat in mesh.materials]
            self.face_materials = [material_names[poly.material_index] if material_names else "unassigned"
                                   for poly in mesh.polygons]
            self.attributes = {
                name: [item.value for item in attr.data]
                for name in ("armor_component", "v5c_plate", "v5c_inner", "v5c_outer", "v5d_inner")
                if (attr := mesh.attributes.get(name)) and attr.domain == "FACE" and attr.data_type == "INT"
            }
        finally:
            evaluated.to_mesh_clear()
        self.vertices = self.points
        self.armor_roles = self.attributes.get("armor_component", [])

    def tagged(self, tag, role=None):
        values = self.attributes.get(tag)
        if not values:
            return []
        return [tri for tri, face in zip(self.triangles, self.triangle_faces)
                if (values[face] == role if role is not None else values[face] > 0)]

    @property
    def geometry(self):
        return self.points, self.triangles


class Plate:
    def __init__(self, mesh, role, region, side, triangles, inner, component=None):
        self.mesh = mesh
        self.role = role
        self.region = region
        self.side = side
        self.key = f"{role}.{side} | {mesh.obj.name}"
        self.inner = inner
        self.component = component
        if inner:
            inner_vertices = {i for tri in inner for i in tri}
            triangles = [tri for island in connected_triangle_sets(triangles)
                         if any(inner_vertices.intersection(tri) for tri in island) for tri in island]
        self.geometry = mesh.points, triangles
        self.tree = bvh(*self.geometry)


def plate_region(role):
    if role.startswith("thigh"):
        return "thigh"
    if role.startswith("knee"):
        return "knee"
    if any(word in role for word in ("calf", "greave", "cuff", "shin")):
        return "calf"
    if any(word in role for word in ("boot", "instep", "heel")):
        return "boot"
    if "thigh" in role:
        return "thigh"
    if "hand" in role or "gauntlet" in role:
        return "hand"
    if "forearm" in role:
        return "forearm"
    if "upper_arm" in role or "biceps" in role:
        return "upper_arm"
    if "elbow" in role:
        return "elbow"
    if any(word in role for word in ("flank", "torso", "armpit", "shoulder", "clavicle",
                                     "scapular", "collar", "abdominal", "lumbar")):
        return "torso"
    return "pelvis"


def garment_label(region):
    if region in ("boot", "hand"):
        return region
    if region in ("torso", "sleeve", "elbow", "upper_arm", "forearm"):
        return "shirt"
    return "trousers"


def roles(mesh):
    obj = mesh.obj
    part = obj.get("part")
    side = obj.get("v5d_side") or obj.get("side") or side_of(mesh) or "C"
    if part == "leg_plates":
        for role_id, (label, region) in EXTENDED_LEG_ROLES.items():
            if triangles := mesh.tagged("armor_component", role_id):
                if role_id == 8 and "calf_segment" in obj:
                    segment = int(obj["calf_segment"])
                    label = ("rear_calf_lower", "rear_calf_middle", "rear_calf_upper")[segment]
                inner = mesh.tagged("v5c_inner", role_id)
                if not inner:
                    backing = set(mesh.tagged("v5d_inner"))
                    inner = [tri for tri in triangles if tri in backing]
                yield Plate(mesh, label, region, side, triangles, inner, component=role_id)
        known = set(EXTENDED_LEG_ROLES) | {0, 2, 6, 12, 13}
        for role_id in sorted(set(mesh.attributes.get("armor_component", [])) - known):
            triangles = mesh.tagged("armor_component", role_id)
            backing = set(mesh.tagged("v5d_inner"))
            inner = mesh.tagged("v5c_inner", role_id) or [tri for tri in triangles if tri in backing]
            yield Plate(mesh, f"leg_role_{role_id}", "boot", side, triangles, inner, component=role_id)
    elif obj.get("v5d_hard") or mesh.tagged("v5d_inner"):
        label = str(obj.get("v5d_region", obj.get("region", obj.name))).lower().replace(" ", "_")
        anatomy = str(obj.get("region", label)).lower().replace(" ", "_")
        yield Plate(mesh, label, plate_region(anatomy), side, mesh.triangles, mesh.tagged("v5d_inner"))
    elif part == "arm_plates":
        for role_id, (label, region) in SHOULDER_ROLES.items():
            if triangles := mesh.tagged("v5c_plate", role_id):
                yield Plate(mesh, label, region, side, triangles, mesh.tagged("v5c_inner", role_id))
        stem = obj.name[2:].split(".")[0]
        if stem in ARM_ROLES:
            label, region = ARM_ROLES[stem]
            inner = mesh.tagged("v5c_inner") or mesh.tagged("v5d_inner")
            yield Plate(mesh, label, region, side, mesh.triangles, inner)


def merge(geometries):
    points, triangles = [], []
    for local_points, local_triangles in geometries:
        remap = {}
        for triangle in local_triangles:
            for i in triangle:
                if i not in remap:
                    remap[i] = len(points)
                    points.append(local_points[i])
            triangles.append(tuple(remap[i] for i in triangle))
    return points, triangles


def joint(rig, side, suffix, posed=False):
    bone = (rig.pose.bones if posed else rig.data.bones)[BONE + side + suffix]
    return rig.matrix_world @ (bone.head if posed else bone.head_local)


def limb_triangles(mesh, side):
    groups = {group.index for group in mesh.obj.vertex_groups
              if group.name.startswith(BONE + side) and any(
                  key in group.name for key in ("Upperarm", "Forearm", "Palm", "Digit"))}
    sleeve = [sum(weight.weight for weight in vertex.groups if weight.group in groups)
              for vertex in mesh.obj.data.vertices]
    return [triangle for triangle in mesh.triangles if sum(sleeve[i] for i in triangle) >= 1.50]


def arm_reference(mesh, rig, side, region):
    shoulder, elbow, wrist = [joint(rig, side, suffix) for suffix in ("Upperarm", "Forearm1", "Palm")]
    start, end = {
        "upper_arm": (shoulder, elbow), "elbow": (shoulder.lerp(elbow, .73), elbow.lerp(wrist, .28)),
        "forearm": (elbow, wrist), "hand": (elbow, wrist + (wrist - elbow) * .50),
    }[region]
    axis = (end - start).normalized()
    sleeve_mesh = SimpleNamespace(points=mesh.points, triangles=limb_triangles(mesh, side), obj=mesh.obj)
    return clipped_triangles(sleeve_mesh, [(axis, axis.dot(start) - .035), (-axis, -axis.dot(end) - .030)])


def bare_silhouette(garment, plate, axis, step):
    local_geometry = []
    lateral = XYZ[1].cross(axis).normalized()
    if not lateral.length:
        lateral = XYZ[0]
    depth = axis.cross(lateral).normalized()
    for points, triangles in (garment, plate):
        local_geometry.append(([Vector((p.dot(lateral), p.dot(depth), p.dot(axis))) for p in points],
                               triangles))
    projection = {name: overshoot(*local_geometry, axes, step) for name, axes in VIEWS.items()}
    projection["axis_world"] = list(axis)
    return projection


def reference_for(plate, garments, rig):
    region, side = plate.region, plate.side
    mesh = garments[garment_label(region)]
    if region in ("upper_arm", "forearm", "elbow", "hand"):
        start, end = ("Upperarm", "Forearm1") if region == "upper_arm" else ("Forearm1", "Palm")
        axis = (joint(rig, side, end) - joint(rig, side, start)).normalized()
        return arm_reference(mesh, rig, side, region), axis
    if region == "ankle":
        geometry = merge(garment_region(garments[label], rig, side, region)[0]
                         for label in ("trousers", "boot"))
        return geometry, XYZ[2]
    if region in ("thigh", "knee", "calf", "boot", "sleeve") and side in ("L", "R"):
        return garment_region(mesh, rig, side, region)[0], XYZ[2]
    return mesh.geometry, XYZ[2]


def inspect_plate(plate, garments, rig, args):
    reference, axis = reference_for(plate, garments, rig)
    silhouette_reference = reference
    if plate.region in {"upper_arm", "elbow", "forearm", "hand"}:
        sleeve_layers = (garments[label] for label in ("shirt", "sleeve_cuff", "hand"))
        silhouette_reference = merge((mesh.points, limb_triangles(mesh, plate.side)) for mesh in sleeve_layers)
        if plate.role == "forearm_inner_wrist":
            reference = silhouette_reference
    points = points_of(plate.geometry)
    extent = [mm(maximum - minimum) for minimum, maximum in (axis_bounds(points, i) for i in range(3))]
    topo = topology(*plate.geometry)
    topo["nonadjacent_triangle_crossings"] = nonadjacent_surface_crossings(plate.tree, plate.geometry[1])
    closed = not any(value for key, value in topo.items() if key != "connected_islands")
    structural = set(plate.geometry[1])
    material_counts = Counter(plate.mesh.face_materials[face] for tri, face in zip(
        plate.mesh.triangles, plate.mesh.triangle_faces) if tri in structural)
    record = {
        "region": plate.region, "side": plate.side, "size_xyz_mm": extent,
        "role": plate.role, "triangles": len(plate.geometry[1]), "inner_triangles": len(plate.inner),
        "material_triangles": dict(material_counts), "component_tag": plate.component,
        "topology": topo, "closed_consistent_nondegenerate_body": closed,
        "clearance_status": "untagged backing" if not plate.inner else "measured",
        "garment": garments[garment_label(plate.region)].obj.name,
        "contour_overshoot": bare_silhouette(silhouette_reference, plate.geometry, axis, args.projection_step),
    }
    if plate.inner:
        gap = surface_gap(plate.mesh.points, plate.inner, reference, args.gap_step)
        record["gap"] = gap
        record["gap_5_to_12_mm"] = (5 <= gap["min_mm"] and gap["max_mm"] <= 12
                                    and not gap["below_local_normal_samples"])
        if plate.region == "boot":
            record["v5c_boot_gap_3_to_8_mm"] = (3 <= gap["min_mm"] and gap["max_mm"] <= 8
                                                and not gap["below_local_normal_samples"])
        if plate.component is not None:
            record["structural_thickness"] = thickness(plate.mesh, plate.component, plate.geometry,
                                                        plate.inner, args.gap_step)
    record["contour_20_mm"] = all(record["contour_overshoot"][name]["max_mm"] <= 20 for name in VIEWS)
    if plate.role == "knee_cap":
        lo, hi = axis_bounds(points, 1)
        x, z = (sum(axis_bounds(points, index)) / 2 for index in (0, 2))
        front = plate.tree.ray_cast(Vector((x, lo - .01, z)), XYZ[1])[0]
        back = plate.tree.ray_cast(Vector((x, hi + .01, z)), -XYZ[1])[0]
        record["center_depth_mm"] = mm(back.y - front.y) if front and back else None
    return record


def garment_contact(plate, name, tree, step):
    pairs = plate.tree.overlap(tree)
    worst = 0
    deep = 0
    count = 0
    deep_area = 0
    inward_area = 0
    interior_area = 0
    interior_depth = 0
    landmark = None
    points, triangles = plate.geometry
    for point, area in weighted_surface_samples(points, triangles, step):
        location, normal, _, distance = tree.find_nearest(point, .075)
        if location is None:
            continue
        count += 1
        depth = distance if (point - location).dot(normal) < -.0001 else 0
        deep += depth >= DEPTH_LIMIT
        deep_area += area if depth >= DEPTH_LIMIT else 0
        inward_area += area if depth > 0 else 0
        if depth >= DEPTH_LIMIT and has_odd_surface_parity(tree, point, bidirectional=True):
            interior_area += area
            interior_depth = max(interior_depth, depth)
        if depth > worst:
            worst, landmark = depth, list(point)
    if not pairs and worst < DEPTH_LIMIT:
        return None
    return {"plate": plate.key, "garment": name, "intersecting_triangle_pairs": len(pairs),
            "max_local_inward_distance_mm": mm(worst), "samples_at_least_10_mm_inward": deep,
            "estimated_armor_area_10_mm_inward_mm2": round(deep_area * 1e6, 2),
            "estimated_armor_area_inside_garment_mm2": round(inward_area * 1e6, 2),
            "intersection_and_deep_samples": bool(pairs and deep),
            "parity_corroborated_depth_mm": mm(interior_depth),
            "parity_corroborated_area_10_mm_inward_mm2": round(interior_area * 1e6, 2),
            "near_garment_surface_samples": count, "worst_world_xyz_m": landmark}


def weighted_surface_samples(points, triangles, step):
    """Use centroids of equal-area subtriangles so samples compare across LODs."""
    for tri in triangles:
        a, b, c = (points[i] for i in tri)
        ab, ac = b - a, c - a
        divisions = max(1, ceil(max(ab.length, ac.length, (c - b).length) / step))
        unit_area = ab.cross(ac).length / (2 * divisions * divisions)
        ab /= divisions
        ac /= divisions
        for i in range(divisions):
            for j in range(divisions - i):
                origin = a + i * ab + j * ac
                yield origin + (ab + ac) / 3, unit_area
                if i + j < divisions - 1:
                    yield origin + (ab + ac) * (2 / 3), unit_area


def plate_contact(first, second, step):
    crossing = first.tree.overlap(second.tree)
    if not crossing:
        return None
    inward_depth, inward_area = [], []
    for side, (source, target) in enumerate(((first, second), (second, first))):
        points, triangles = source.geometry
        near_triangles = [triangles[index] for index in sorted({pair[side] for pair in crossing})]
        depth, area = 0, 0
        for point, weight in weighted_surface_samples(points, near_triangles, step):
            _, _, _, distance = target.tree.find_nearest(point)
            if distance > .0001 and has_odd_surface_parity(target.tree, point):
                depth = max(depth, distance)
                area += weight
        inward_depth.append(mm(depth))
        inward_area.append(round(area * 1e6, 2))
    return {"plates": [first.key, second.key], "triangle_pairs": len(crossing),
            "inward_depth_on_crossing_triangles_mm": inward_depth,
            "inward_area_on_crossing_triangles_mm2": inward_area}


def has_odd_surface_parity(tree, point, bidirectional=False):
    """Require odd intersection parity along oblique test directions."""
    rays = (*INTERIOR_RAYS, *(-ray for ray in INTERIOR_RAYS)) if bidirectional else INTERIOR_RAYS
    for ray in rays:
        origin = point
        count = 0
        while (hit := tree.ray_cast(origin, ray)[0]) is not None:
            count += 1
            origin = hit + ray * .00002
        if count % 2 == 0:
            return False
    return True


def translate_geometry(geometry, origin, first, second, axis):
    points, tris = geometry
    points = [p - origin for p in points]
    return [Vector((p.dot(first), p.dot(second), p.dot(axis))) for p in points], tris


def wrap_profile(plates, garments, rig, region, side):
    if region in {"upper_arm", "forearm"}:
        segment = ("Upperarm", "Forearm1") if region == "upper_arm" else ("Forearm1", "Palm")
        start, end = (joint(rig, side, suffix) for suffix in segment)
        axis = (start - end).normalized()
        first = XYZ[1].cross(axis).normalized()
        second = axis.cross(first).normalized()
        geometry = translate_geometry(merge(p.geometry for p in plates), end, first, second, axis)
        cloth = translate_geometry(arm_reference(garments["shirt"], rig, side, region),
                                   end, first, second, axis)
    else:
        geometry = merge(p.geometry for p in plates)
        cloth = garment_region(garments["trousers"], rig, side, region)[0]
    return wrap_and_taper(geometry, cloth)


def fold_width(tree, armor, center, axis, normal, low, high, reach=.17):
    """Measure the longest longitudinal stretch of exposed cloth on three rays."""
    step = .002
    axis = axis.normalized()
    normal = (normal - axis * axis.dot(normal)).normalized()
    lateral = axis.cross(normal)
    rails = []
    for angle in (-20, 0, 20):
        angle_rad = radians(angle)
        outward = normal * cos(angle_rad) + lateral * sin(angle_rad)
        exposed = []
        for index in range(round((high - low) / step) + 1):
            station = low + index * step
            start = center + axis * station
            point, skin_normal, _, _ = tree.ray_cast(start, outward, reach)
            if point is None or skin_normal.dot(outward) < .15:
                point, skin_normal, _, _ = tree.ray_cast(start + reach * outward, -outward, reach)
            if point is None or skin_normal.dot(outward) < .15:
                exposed.append(None)
                continue
            hit = armor.ray_cast(point + skin_normal * .0001, skin_normal, .040)[0]
            exposed.append(hit is None)
        runs, start = [], None
        for sample, uncovered in enumerate([*exposed, None]):
            if uncovered and start is None:
                start = sample
            if not uncovered and start is not None:
                runs.append((start, sample - 1))
                start = None
        valid = sum(sample is not None for sample in exposed)
        longest = max(runs, key=lambda run: run[1] - run[0], default=None)
        rails.append({"angle_deg": angle, "valid_samples": valid,
                      "max_uncovered_axis_width_mm": (
                          mm((longest[1] - longest[0] + 1) * step) if longest else (0 if valid else None)),
                      "open_to_window_edge": bool(longest and (longest[0] == 0 or longest[1] == len(exposed) - 1)),
                      "longest_run_axis_start_end_mm": (
                          [mm(low + index * step) for index in longest] if longest else None)})
    values = [rail["max_uncovered_axis_width_mm"] for rail in rails
              if rail["max_uncovered_axis_width_mm"] is not None]
    return {"sample_step_mm": mm(step), "ray_limit_mm": 40, "rail_runs": rails,
            "largest_sampled_uncovered_width_mm": max(values) if values else None}


def joint_gaps(collection, garments, rig):
    # Include qualifying frame, carrier and helmet faces in the same surface test
    # as the coverage audit. The measured station remains tied to the bare garment.
    from v5d_coverage import armor_tree
    graph = bpy.context.evaluated_depsgraph_get()
    armor, _, _ = armor_tree(collection.all_objects, graph)
    trees = {name: bvh(*mesh.geometry) for name, mesh in garments.items()}
    report = {}
    for side, sign in (("L", 1), ("R", -1)):
        shoulder, elbow, wrist, hip, knee, ankle = [
            joint(rig, side, suffix) for suffix in
            ("Upperarm", "Forearm1", "Palm", "Thigh1", "Calf", "Foot")]
        forearm = (wrist - elbow).normalized()
        dorsal = (XYZ[2] - forearm * XYZ[2].dot(forearm)).normalized()
        # The medial fold lies in the transverse direction of the native sleeve.
        elbow_inward = forearm.cross(dorsal) * sign
        report[f"inner_elbow.{side}"] = fold_width(trees["shirt"], armor, elbow, forearm,
                                                    elbow_inward, -.062, .062)
        report[f"knee_back.{side}"] = fold_width(trees["trousers"], armor, knee, hip - ankle,
                                                 XYZ[1], -.075, .075)
        flank = Vector((0, shoulder.y, shoulder.z - .095))
        report[f"armpit.{side}"] = fold_width(trees["shirt"], armor, flank, XYZ[2],
                                               XYZ[0] * sign, -.070, .070, reach=.30)
    garment = garments["trousers"]
    midline = plane_slice(*garment.geometry, 0, 0)
    if midline:
        saddle = min(midline, key=lambda point: point.z)
        for name, direction in (("front", -XYZ[1]), ("back", XYZ[1])):
            report[f"crotch_seam.{name}"] = fold_width(trees["trousers"], armor, saddle, XYZ[2],
                                                        direction, -.024, .085)
    return report


def details(plates, garments, rig):
    result = {}
    for side in ("L", "R"):
        side_plates = [plate for plate in plates if plate.side == side]
        side_record = result[side] = {}
        for region, target in (("thigh", 300), ("calf", 320), ("forearm", 300), ("upper_arm", None)):
            members = [plate for plate in side_plates if plate.region == region
                       and plate.role != "ankle_cuff"]
            if members:
                side_record[region] = {"target_deg": target, "roles": [plate.role for plate in members],
                                       "sections": wrap_profile(members, garments, rig, region, side)}
                if region == "forearm":
                    main_bracer = [plate for plate in members
                                   if plate.role in {"forearm_outer", "forearm_inner"}]
                    if main_bracer:
                        side_record[region]["main_bracer_sections"] = wrap_profile(
                            main_bracer, garments, rig, region, side)
        if greaves := [plate for plate in side_plates if plate.role == "shin_greave"]:
            sections = wrap_profile(greaves, garments, rig, "calf", side)
            side_record["greave_taper"] = {"sections": sections, "top_minus_bottom_width_mm":
                round(sections[-1]["plate_width_mm"] - sections[0]["plate_width_mm"], 3)
                if len(sections) >= 2 else None}
    return result


def frozen_inventory():
    scene = bpy.context.scene
    full, attachment = {}, {}
    for obj in scene.objects:
        if obj.get("part") in PROTECTED or obj.type in {"ARMATURE", "EMPTY"} or obj.name.startswith("REF_"):
            full[obj.name] = object_signature(obj)
        if obj.get("part") == "leg_plates" and (outsole := outsole_signature(obj)):
            attachment[obj.name + " :: outsole"] = {key: fingerprint(value) for key, value in outsole.items()}
    return full, attachment


def neutral_socket_offsets(rig):
    neck = rig.matrix_world @ rig.pose.bones[BONE + "Neck"].matrix
    return {name: [list(row) for row in neck.inverted_safe() @ bpy.data.objects[name].matrix_world]
            for name in SOCKETS}


def audit_lod(collection, rig, args, errors):
    objects = sorted((obj for obj in collection.all_objects if obj.type == "MESH"), key=lambda obj: obj.name)
    skins = {}
    for obj in objects:
        if obj.get("part") not in PROTECTED:
            skins[obj.name] = dict(check_skin(obj, rig, errors))
    record = {"triangles_by_part": {}, "weights_by_object": skins, "poses": {}}
    socket_reference = None
    for pose in QA_POSES:
        apply_pose(rig, pose)
        graph = bpy.context.evaluated_depsgraph_get()
        meshes = [Mesh(obj, graph) for obj in objects
                  if pose == "rest" or obj.get("part") not in PROTECTED
                  or obj.get("frame_node") or obj.get("frame_nodes")]
        garments = {key: next(mesh for mesh in meshes if label in mesh.obj.name)
                    for key, label in GARMENTS.items()}
        plates = [plate for mesh in meshes for plate in roles(mesh)]
        socket_offsets = neutral_socket_offsets(rig)
        if socket_reference is None:
            socket_reference = socket_offsets
        moved = [name for name in SOCKETS
                 if not near_matrix(Matrix(socket_offsets[name]), Matrix(socket_reference[name]))]
        if moved:
            errors.append(f"{collection.name}/{pose}: neck-relative offsets changed for {moved}")
        if pose == "rest":
            triangles = Counter()
            for mesh in meshes:
                triangles[str(mesh.obj.get("part", "untagged"))] += len(mesh.triangles)
            record["triangles_by_part"] = dict(sorted(triangles.items()))
            record["triangles"] = sum(triangles.values())
            record["roles"] = {plate.key: inspect_plate(plate, garments, rig, args) for plate in plates}
            record["wrap_and_taper"] = details(plates, garments, rig)
            record["joint_gap_axis_widths"] = joint_gaps(collection, garments, rig)
        garment_trees = {name: bvh(*mesh.geometry) for name, mesh in garments.items()}
        native_trees = {
            label: bvh(*Mesh(bpy.context.scene.objects[label], graph).geometry)
            for label in ("REF_top", "REF_pants")
        } if args.native_contacts else {}
        body_contacts = []
        native_contacts = []
        for plate in plates:
            names = [garment_label(plate.region)]
            if plate.region == "hand":
                names += ["shirt"]
            elif plate.region in {"thigh", "pelvis", "torso", "sleeve", "upper_arm", "elbow", "forearm"}:
                names = ["shirt", "trousers"]
            elif plate.region in {"boot", "calf", "ankle"}:
                names = ["boot", "trousers"]
            for name in names:
                if contact := garment_contact(plate, name, garment_trees[name], args.contact_step):
                    body_contacts.append(contact)
            if native_trees:
                label = "REF_top" if garment_label(plate.region) in {"shirt", "hand"} else "REF_pants"
                if contact := garment_contact(plate, label, native_trees[label], args.contact_step):
                    native_contacts.append(contact)
        body_contacts.sort(key=lambda hit: hit["max_local_inward_distance_mm"], reverse=True)
        native_contacts.sort(key=lambda hit: hit["max_local_inward_distance_mm"], reverse=True)
        plate_contacts = [contact for first, second in combinations(plates, 2)
                          if (contact := plate_contact(first, second, args.contact_step))]
        nodes = frame_components(meshes)
        drive = drive_contacts(nodes)
        lug_paths = lug_attachment_fit(meshes, nodes)
        if not drive["continuous"]:
            errors.append(f"{collection.name}/{pose}: frame drivetrain disconnected")
        if len(lug_paths) != 8 or not all(record["connected_path"] for record in lug_paths.values()):
            errors.append(f"{collection.name}/{pose}: expected eight connected plate mounting paths")
        record["poses"][pose] = {
            "garment_contacts": body_contacts, "native_reference_contacts": native_contacts,
            "plate_contacts": plate_contacts,
            "socket_neck_offsets": socket_offsets, "pose_landmarks_m": pose_landmarks(rig),
            "exoskeleton_drive": drive, "leg_plate_lug_paths": lug_paths,
        }
        print(f"{collection.name} {pose}: {len(plates)} roles, {len(body_contacts)} garment contacts, "
              f"{len(plate_contacts)} plate contacts", flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ENTRY / "work/v5d/baseline.blend")
    parser.add_argument("--out", type=Path, default=ENTRY / "work/v5d/qa.json")
    parser.add_argument("--gap-step", type=float, default=.003)
    parser.add_argument("--projection-step", type=float, default=.001)
    parser.add_argument("--contact-step", type=float, default=.004)
    parser.add_argument("--strict", action="store_true", help="Write the report, then fail on integrity findings.")
    parser.add_argument("--native-contacts", action="store_true",
                        help="Also test armor against the original native garment reference.")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if min(args.gap_step, args.projection_step, args.contact_step) <= 0:
        parser.error("Sampling steps must be positive.")
    if not args.out.resolve().is_relative_to(ENTRY):
        parser.error("Keep audit output inside the entry.")
    candidate = Path(bpy.data.filepath)
    candidate_hash = digest(candidate)
    if digest(args.baseline) != BASELINE_HASH:
        raise RuntimeError("Unexpected V5C baseline hash")
    current, current_outsole = frozen_inventory()
    rig = bpy.context.scene.objects["EFT_Bind"]
    report = {
        "blend": str(candidate), "sha256": candidate_hash, "baseline_sha256": BASELINE_HASH,
        "bind_pose_saved": all(near_matrix(bone.matrix_basis, Matrix.Identity(4)) for bone in rig.pose.bones),
        "render": {"engine": bpy.context.scene.render.engine, "device": bpy.context.scene.cycles.device},
        "sample_step_mm": {"gap": mm(args.gap_step), "silhouette": mm(args.projection_step),
                           "pose_contact": mm(args.contact_step)},
        "native_reference_contacts_enabled": args.native_contacts,
        "pose_contact_method": "Evaluated triangles and barycentric samples. Inward distance uses nearest garment "
                               "triangle's outward normal. An open seam or concave fold can make the sign ambiguous. "
                               "Four oblique ray parities provide stricter corroboration, but folds and openings can "
                               "also give false negatives. Reported coordinates support visual review. Plate overlap "
                               "includes designed contacts.",
        "integrity_findings": [], "lods": {},
    }
    bpy.ops.wm.open_mainfile(filepath=str(args.baseline.resolve()))
    original, original_outsole = frozen_inventory()
    report["frozen_comparison"] = compare_protected(original, current)
    report["outsole_comparison"] = compare_protected(original_outsole, current_outsole)
    bpy.ops.wm.open_mainfile(filepath=str(candidate))
    rig = bpy.context.scene.objects["EFT_Bind"]
    for layer in layer_collections(bpy.context.view_layer.layer_collection):
        layer.exclude = False
        layer.hide_viewport = False
        layer.collection.hide_viewport = False
    for obj in bpy.context.scene.objects:
        obj.hide_set(False)
        obj.hide_viewport = False
    errors = report["integrity_findings"]
    frozen = report["frozen_comparison"]
    if any(frozen[name] for name in ("missing", "added", "changed")):
        errors.append("Frozen V5C assembly differs")
    soles = report["outsole_comparison"]
    expected_soles = {f"LegArmour_{side}_LOD{lod} :: outsole"
                      for side in ("L", "R") for lod in (0, 1)}
    expected_fields = {"faces", "vertices", "weights"}
    report["outsole_topology_budget_changes"] = {
        key: fields for key, fields in soles["changed"].items()
        if key in expected_soles and set(fields) <= expected_fields
    }
    if (soles["missing"] or soles["added"]
            or soles["changed"].keys() != report["outsole_topology_budget_changes"].keys()):
        errors.append("Unexpected V5C outsole differences")
    if not report["bind_pose_saved"] or rig.data.pose_position != "REST":
        errors.append("Assembly is not saved in the expected V5C bind state")
    if report["render"] != {"engine": "CYCLES", "device": "GPU"}:
        errors.append("Saved render engine or device differs from Cycles GPU")
    for name in LOD_NAMES:
        report["lods"][name] = audit_lod(bpy.data.collections[name], rig, args, errors)
    lod0, lod1 = (report["lods"][name]["triangles"] for name in LOD_NAMES)
    report["lod1_to_lod0_ratio"] = round(lod1 / lod0, 5)
    if lod0 > 80_000:
        errors.append("LOD0 exceeds 80,000 triangles")
    if digest(candidate) != candidate_hash or digest(args.baseline) != BASELINE_HASH:
        raise RuntimeError("Audited files changed during QA")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Audit saved to {args.out}. LOD totals {lod0:,} / {lod1:,}. Findings: {len(errors)}", flush=True)
    if args.strict and errors:
        raise RuntimeError("\n".join(errors))


if __name__ == "__main__":
    main()
