"""Evaluate the competition blend and save numerical pose QA beside the build."""

import argparse
from collections import Counter, defaultdict
from hashlib import file_digest
import json
from math import cos, isfinite, pi, sin
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from poses import BONE, POSES, apply_pose
from qa_feedback import (
    Component, check_inventory, check_materials, drive_geometry, frame_contacts, panel_geometry,
)


ENTRY = Path(__file__).resolve().parents[1]
NATIVE_REFERENCES = ("REF_top", "REF_pants")
SOCKETS = ("mod_nvg", "mod_equipment_001")
DEPTH_TOLERANCE = .003
GRID_STEP = .004
VIEWS = (
    ("front", 0, 0), ("front-left", 45, 0), ("left", 90, 0),
    ("back-left", 135, 0), ("back", 180, 0), ("back-right", 225, 0),
    ("right", 270, 0), ("front-right", 315, 0),
    ("high-front", 22.5, 24), ("high-back", 202.5, 24),
)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=ENTRY / "work" / "qa" / "report.json")
    p.add_argument("--collections", nargs=2, default=("EXO_LOD0", "EXO_LOD1"))
    p.add_argument("--partial", action="store_true")
    p.add_argument("--step", type=float, default=GRID_STEP, help="orthographic ray spacing in metres")
    p.add_argument("--mechanical-only", action="store_true",
                   help="Skip clothing visibility rays and the broad collision inventory")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def near_matrix(a, b, tolerance=1e-6):
    return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4)) < tolerance


def check_native(rig, references, errors):
    source_path = ENTRY / "source" / "base_scene.blend"
    with bpy.data.libraries.load(str(source_path)) as (source, target):
        assert "EFT_Bind" in source.objects
        target.objects = ["EFT_Bind", *NATIVE_REFERENCES]
    source, *witnesses = target.objects
    errors.extend(f"Rest bone differs: {bone.name}" for bone in source.data.bones
                  if bone.name in rig.data.bones and (
                      not near_matrix(rig.data.bones[bone.name].matrix_local, bone.matrix_local)
                      or abs(rig.data.bones[bone.name].length - bone.length) > 1e-6
                      or rig.data.bones[bone.name].use_deform != bone.use_deform
                      or (rig.data.bones[bone.name].parent.name if rig.data.bones[bone.name].parent else None)
                      != (bone.parent.name if bone.parent else None)))
    if set(rig.data.bones.keys()) != set(source.data.bones.keys()) or len(rig.data.bones) != 58:
        errors.append("Rig does not contain the exact 58 native bone names")
    if not near_matrix(source.matrix_world, rig.matrix_world):
        errors.append("Rig world transform differs from native")
    for witness, native in zip(references, witnesses):
        if (not near_matrix(witness.matrix_world, native.matrix_world)
                or len(witness.data.vertices) != len(native.data.vertices)
                or any((a.co - b.co).length > 1e-6 for a, b in zip(witness.data.vertices, native.data.vertices))
                or len(witness.data.polygons) != len(native.data.polygons)
                or any(tuple(a.vertices) != tuple(b.vertices)
                       for a, b in zip(witness.data.polygons, native.data.polygons))):
            errors.append(f"{witness.name}: native witness geometry or transform has changed")
        a_groups, b_groups = list(witness.vertex_groups.keys()), list(native.vertex_groups.keys())
        if a_groups != b_groups or any(
                [(w.group, w.weight) for w in a.groups] != [(w.group, w.weight) for w in b.groups]
                for a, b in zip(witness.data.vertices, native.data.vertices)):
            errors.append(f"{witness.name}: native witness weights have changed")
        bpy.data.objects.remove(native)
    witness_head = next((obj for obj in references if obj.name == "REF_head"), None)
    if witness_head:
        donor = json.loads((ENTRY / "source" / "reference" / "usec_head.json").read_text())
        if (len(witness_head.data.vertices) != len(donor["positions"])
                or any((vertex.co - Vector(point)).length > 1e-6
                       for vertex, point in zip(witness_head.data.vertices, donor["positions"]))
                or len(witness_head.data.polygons) != len(donor["triangles"])
                or any(tuple(face.vertices) != tuple(triangle)
                       for face, triangle in zip(witness_head.data.polygons, donor["triangles"]))):
            errors.append("REF_head: native head witness geometry has changed")
    bpy.data.objects.remove(source)


def section(obj, root):
    if value := obj.get("part"):
        return str(value)
    for collection in obj.users_collection:
        if collection != root and obj.name in root.all_objects:
            return collection.name
    name = obj.name.split(" | ")
    return " | ".join(name[:2]).rsplit(" LOD", 1)[0]


def as_xyz(point):
    return [round(component, 4) for component in point]


class Surface:
    def __init__(self, obj, graph):
        self.obj = obj
        self.vertices = []
        self.triangles = []
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            self.vertices = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
            mesh.calc_loop_triangles()
            self.triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
            self.triangle_faces = [triangle.polygon_index for triangle in mesh.loop_triangles]
            armor = mesh.attributes.get("armor_component")
            self.armor_roles = ([value.value for value in armor.data]
                                if armor and armor.domain == "FACE" and armor.data_type == "INT" else [])
        finally:
            evaluated.to_mesh_clear()
        if not all(isfinite(component) for vertex in self.vertices for component in vertex):
            raise ValueError(f"{obj.name} has nonfinite evaluated coordinates")
        self.bvh = BVHTree.FromPolygons(self.vertices, self.triangles, all_triangles=True)

    def center(self, index):
        return sum((self.vertices[i] for i in self.triangles[index]), Vector()) / 3


def merge(surfaces):
    vertices, triangles, lookup = [], [], []
    for surf in surfaces:
        offset = len(vertices)
        vertices.extend(surf.vertices)
        triangles.extend(tuple(index + offset for index in tri) for tri in surf.triangles)
        lookup.extend((surf, index) for index in range(len(surf.triangles)))
    return BVHTree.FromPolygons(vertices, triangles, all_triangles=True), lookup


def check_skin(obj, rig, errors):
    modifiers = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
    if obj.get("part") == "thermal" and not modifiers:
        anchor = obj.parent
        while anchor and anchor.type == "EMPTY" and anchor.name != "mod_nvg":
            anchor = anchor.parent
        if (anchor and anchor.name == "mod_nvg" and anchor.parent == rig
                and anchor.parent_type == "BONE" and anchor.parent_bone == BONE + "Neck"
                and not any(vertex.groups for vertex in obj.data.vertices)):
            return Counter({"rigid_socket": len(obj.data.vertices)})
    if (len(modifiers) != 1 or modifiers[0].object != rig or not modifiers[0].show_viewport
            or not modifiers[0].show_render or not modifiers[0].use_vertex_groups
            or modifiers[0].use_bone_envelopes or modifiers[0].vertex_group):
        errors.append(f"{obj.name}: expected one enabled EFT_Bind armature with vertex groups")
    valid = {group.index for group in obj.vertex_groups
             if group.name in rig.data.bones and rig.data.bones[group.name].use_deform}
    histogram = Counter()
    bad = 0
    for vertex in obj.data.vertices:
        weights = [w for w in vertex.groups if w.weight > 0]
        histogram[len(weights)] += 1
        if (not all(isfinite(w.weight) and 0 <= w.weight <= 1 for w in vertex.groups)
                or not 1 <= len(weights) <= 4
                or any(w.group not in valid for w in weights)
                or abs(sum(w.weight for w in weights) - 1) > 1e-4):
            bad += 1
    if bad:
        errors.append(f"{obj.name}: {bad} vertices have invalid EFT weights")
    return histogram


def check_mounts(rig, surfaces, errors, partial):
    thermal = [surf for surf in surfaces if str(surf.obj.get("part", "")).lower() == "thermal"]
    helmet = [surf for surf in surfaces if str(surf.obj.get("part", "")).lower() == "helmet"]
    mounts = {}
    for name in SOCKETS:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "EMPTY":
            if not partial:
                errors.append(f"Missing mount empty {name}")
            continue
        origin = obj.matrix_world.translation
        if obj.parent != rig or obj.parent_type != "BONE" or obj.parent_bone != BONE + "Neck":
            errors.append(f"{name} does not follow EFT_Bind neck")
        if not all(isfinite(value) for row in obj.matrix_world for value in row) or abs(obj.matrix_world.determinant()) < 1e-6:
            errors.append(f"{name} has invalid transform")
        neck = rig.matrix_world @ rig.pose.bones[BONE + "Neck"].matrix
        offset = neck.inverted_safe() @ obj.matrix_world
        record = {"position_m": as_xyz(origin), "parent_bone": obj.parent_bone,
                  "neutral_neck_offset": [list(row) for row in offset]}
        for label, items in (("helmet", helmet), ("thermal", thermal if name == "mod_nvg" else [])):
            if items:
                closest = min((surf.bvh.find_nearest(origin)[3], surf.obj.name) for surf in items)
                record[label + "_surface_cm"] = round(closest[0] * 100, 2)
                record[label + "_nearest_object"] = closest[1]
                if closest[0] > .08:
                    errors.append(f"{name} is far from {label} surface: {closest[0]:.3f} m")
        if not partial:
            seats = [surf for surf in helmet if surf.obj.get("mount_seat") == name]
            if name == "mod_nvg":
                seats.extend(surf for surf in helmet if surf.obj.name.startswith(
                    ("Shroud | open rectangular receiver", "Shroud | chamfered mounting backplate"))
                    and surf not in seats)
            if seats:
                seat_distance = min(surf.bvh.find_nearest(origin)[3] for surf in seats)
                record["mount_seat_surface_mm"] = round(seat_distance * 1000, 2)
                if seat_distance > .015:
                    errors.append(f"{name}: socket origin is more than 15 mm from physical seat")
            else:
                errors.append(f"{name}: expected an identifiable physical mount seat")
            if name == "mod_nvg":
                tongues = [surf for surf in thermal if surf.obj.name.startswith("Thermal | dovetail tongue")]
                contacts = []
                for tongue in tongues:
                    a = Component(tongue, tongue.triangles)
                    for seat in seats:
                        b = Component(seat, seat.triangles)
                        if contact := a.contact(b):
                            contacts.append({"thermal": a.name, "seat": b.name, **contact})
                record["thermal_to_seat_contacts"] = contacts
                if not contacts:
                    errors.append(f"{name}: thermal dovetail has no evaluated surface contact with its shroud")
        mounts[name] = record
    return mounts


def sample_visibility(rig, reference, equipment, step):
    reference_tree, lookup = merge(reference)
    equipment_tree, _ = merge(equipment)
    vertices = [v for surf in reference for v in surf.vertices]
    head = rig.pose.bones[BONE + "Neck"].head
    bind_neck_z = rig.data.bones[BONE + "Neck"].head_local.z
    palms = [rig.pose.bones[BONE + side + "Palm"].head for side in ("L", "R")]
    feet = [rig.pose.bones[BONE + side + "Foot"].head for side in ("L", "R")]
    original = {surf.obj.name: [surf.obj.matrix_world @ v.co for v in surf.obj.data.vertices]
                for surf in reference}
    result = {}
    for name, azimuth, elevation in VIEWS:
        a, e = azimuth * pi / 180, elevation * pi / 180
        direction = Vector((sin(a) * cos(e), -cos(a) * cos(e), sin(e)))
        right = Vector((cos(a), sin(a), 0))
        up = direction.cross(right)
        horizontal = [v.dot(right) for v in vertices]
        vertical = [v.dot(up) for v in vertices]
        count = Counter()
        examples = defaultdict(list)
        protrusion = defaultdict(float)
        source_vertices = defaultdict(set)
        rest_points = defaultdict(list)
        left, bottom = min(horizontal), min(vertical)
        width = int((max(horizontal) - left) / step) + 1
        height = int((max(vertical) - bottom) / step) + 1
        for i in range(width):
            for j in range(height):
                origin = (direction * 4 + right * (left + (i + .5) * step)
                          + up * (bottom + (j + .5) * step))
                point, _, index, base_distance = reference_tree.ray_cast(origin, -direction)
                if point is None:
                    continue
                surf, triangle_index = lookup[index]
                region = surf.obj.name
                if region == "REF_top":
                    if min((point - palm).length for palm in palms) < .205:
                        region = "native wrist/hands"
                    elif (point - head).length < .14 and abs(point.x - head.x) < .085:
                        region = "native neck opening"
                    else:
                        region = "native jacket/sleeves"
                elif region == "REF_pants":
                    region = ("native lower hem/boots"
                              if min((point - foot).length for foot in feet) < .245
                              else "native trousers")
                count["reference samples"] += 1
                _, _, _, distance = equipment_tree.ray_cast(origin, -direction)
                if distance is None or base_distance + DEPTH_TOLERANCE < distance:
                    triangle = surf.triangles[triangle_index]
                    bind_point = barycentric_transform(
                        point, *(surf.vertices[v] for v in triangle),
                        *(original[surf.obj.name][v] for v in triangle))
                    if region == "REF_head":
                        region = "native jaw/throat" if bind_point.z < bind_neck_z + .09 else "native head/face"
                    key = region + (" (silhouette)" if distance is None else " (ahead of model)")
                    count[key] += 1
                    examples[key].append(point.copy())
                    source_vertices[key].update(triangle)
                    rest_points[key].append(bind_point)
                    if distance is not None:
                        protrusion[key] = max(protrusion[key], distance - base_distance)
        result[name] = {**count, "regions_m": {
            key: {"min": as_xyz(Vector([min(v[i] for v in locations) for i in range(3)])),
                  "max": as_xyz(Vector([max(v[i] for v in locations) for i in range(3)])),
                  "maximum_depth_m": round(protrusion[key], 4) if protrusion[key] else None,
                  "bind_min": as_xyz(Vector([min(v[i] for v in rest_points[key]) for i in range(3)])),
                  "bind_max": as_xyz(Vector([max(v[i] for v in rest_points[key]) for i in range(3)])),
                  "source_vertex_indices": sorted(source_vertices[key])}
            for key, locations in examples.items()}}
    return result


def visibility_totals(views):
    totals = Counter()
    for view in views.values():
        totals.update({key: n for key, n in view.items() if key != "regions_m"})
    reference = totals.pop("reference samples", 0)
    exposed = sum(totals.values())
    return {"reference_samples": reference, "exposed_samples": exposed,
            "exposed_percent": round(100 * exposed / reference, 5),
            "exposed_regions": dict(totals)}

def collision_record(a, b):
    pairs = a.bvh.overlap(b.bvh)
    if not pairs:
        return None
    points = [a.center(index) for index in sorted({i for i, _ in pairs})]
    return {"pair": [a.obj.name, b.obj.name], "crossing_triangle_pairs": len(pairs),
            "min_m": as_xyz(Vector([min(v[i] for v in points) for i in range(3)])),
            "max_m": as_xyz(Vector([max(v[i] for v in points) for i in range(3)]))}


def intersections(surfaces, root):
    soft_labels = ("undersuit", "jacket", "trouser", "combat boot", "gaiter", "glove")
    soft, hardware = [], []
    for surf in surfaces:
        name = f"{section(surf.obj, root)} {surf.obj.name}".lower()
        (soft if any(label in name for label in soft_labels) else hardware).append(surf)
    cloth_contacts, hardware_contacts = [], []
    for i, item in enumerate(hardware):
        for base in soft:
            if contact := collision_record(item, base):
                cloth_contacts.append(contact)
        for other in hardware[i + 1:]:
            if contact := collision_record(item, other):
                hardware_contacts.append(contact)
    return {"equipment_to_cloth": cloth_contacts, "equipment_to_equipment": hardware_contacts}


def pose_landmarks(rig):
    suffixes = ("Pelvis", "Spine3", "Neck", "LCalf", "RCalf", "LFoot", "RFoot",
                "LToe", "RToe", "LUpperarm", "RUpperarm", "LPalm", "RPalm")
    return {name: as_xyz(rig.matrix_world @ rig.pose.bones[BONE + name].head)
            for name in suffixes}

def main():
    args = parser()
    if args.step <= 0 or not isfinite(args.step):
        raise ValueError("Ray spacing must be positive and finite")
    errors = []
    rig = bpy.context.scene.objects["EFT_Bind"]
    ref = [bpy.context.scene.objects[name] for name in NATIVE_REFERENCES]
    native_head = bpy.context.scene.objects.get("REF_head")
    if native_head:
        ref.append(native_head)
    collections = [bpy.data.collections[name] for name in args.collections]
    materials = check_materials(bpy.context.scene, errors)
    check_native(rig, ref, errors)
    inventory = check_inventory(bpy.context.scene, collections, ref, errors, args.partial)
    if not args.partial and any(not near_matrix(b.matrix_basis, Matrix.Identity(4))
                                for b in rig.pose.bones):
        errors.append("Canonical blend opened outside the bind pose")
    for collection in (*collections, *(c for o in ref for c in o.users_collection)):
        collection.hide_viewport = False
    for layer in layer_collections(bpy.context.view_layer.layer_collection):
        layer.exclude = False
        layer.hide_viewport = False
    for obj in ref:
        obj.hide_set(False)
        obj.hide_viewport = False
    with Path(bpy.data.filepath).open("rb") as packed_blend:
        digest = file_digest(packed_blend, "sha256").hexdigest()
    scene = bpy.context.scene
    renderer = {"engine": scene.render.engine, "cycles_device": scene.cycles.device}
    if not args.partial and (renderer["engine"], renderer["cycles_device"]) != ("CYCLES", "GPU"):
        errors.append("Saved scene does not configure Cycles for GPU rendering")
    report = {"blend": str(bpy.data.filepath), "sha256": digest, "blender": bpy.app.version_string,
              "bone_count": len(rig.data.bones),
              "constant_materials": materials, "mesh_inventory": inventory,
              "saved_render_configuration": renderer, "errors": errors, "lods": {},
              "sampling": {"spacing_m": args.step, "depth_tolerance_m": DEPTH_TOLERANCE,
                           "native_head_mesh_available": bool(native_head), "views": len(VIEWS),
                           "intersection_note": "Triangle crossing pairs include intended seams and embedded attachments. Compare location and count across poses."}}
    for lod, root in enumerate(collections):
        objects = sorted((obj for obj in root.all_objects if obj.type == "MESH"), key=lambda obj: obj.name)
        for obj in objects:
            obj.hide_set(False)
            obj.hide_viewport = False
        histogram = Counter()
        for obj in objects:
            histogram.update(check_skin(obj, rig, errors))
        details = {"weight_histogram": histogram, "poses": {}}
        report["lods"][f"LOD{lod}"] = details
        for pose in POSES:
            apply_pose(rig, pose)
            graph = bpy.context.evaluated_depsgraph_get()
            surfaces = [Surface(obj, graph) for obj in objects]
            if pose == "rest":
                parts = Counter()
                for surf in surfaces:
                    parts[section(surf.obj, root)] += len(surf.triangles)
                details["parts"] = dict(sorted(parts.items()))
                subparts = Counter()
                for surf in surfaces:
                    group = surf.obj.get("subpart")
                    if group:
                        subparts[f"{section(surf.obj, root)} / {group}"] += len(surf.triangles)
                details["subparts"] = dict(sorted(subparts.items()))
                details["meshes"] = {surf.obj.name: len(surf.triangles) for surf in surfaces}
                details["triangles"] = sum(parts.values())
                if not args.partial:
                    details["leg_panel_geometry"] = panel_geometry(surfaces, rig, lod, errors)
                    details["leg_drive_geometry"] = drive_geometry(surfaces, lod, errors)
            pose_record = {"bone_positions_m": pose_landmarks(rig)}
            if not args.partial:
                pose_record["frame_contacts"] = frame_contacts(surfaces, lod, pose, errors)
            if not args.mechanical_only:
                visibility = sample_visibility(rig, [Surface(obj, graph) for obj in ref], surfaces, args.step)
                totals = visibility_totals(visibility)
                if not args.partial and totals["exposed_samples"]:
                    errors.append(f"LOD{lod} {pose}: {totals['exposed_samples']} native exposure samples")
                pose_record.update(visibility=visibility,
                                   visibility_totals=totals,
                                   intersections=intersections(surfaces, root))
            mounts = check_mounts(rig, surfaces, errors, args.partial)
            if pose != "rest":
                for name, record in mounts.items():
                    neutral = details["poses"]["rest"]["mounts"][name]["neutral_neck_offset"]
                    if not near_matrix(record["neutral_neck_offset"], neutral):
                        errors.append(f"{name} drifted off its Neck-relative transform in LOD{lod} {pose}")
            pose_record["mounts"] = mounts
            details["poses"][pose] = pose_record
            print(f"QA LOD{lod} {pose} evaluated {len(objects)} meshes", flush=True)
    tri0, tri1 = [report["lods"][f"LOD{i}"]["triangles"] for i in range(2)]
    if tri0 > 80000:
        errors.append(f"LOD0 triangle cap exceeded: {tri0}")
    if not args.partial:
        for i in range(2):
            if not any(part.lower() == "thermal" for part in report["lods"][f"LOD{i}"]["parts"]):
                errors.append(f"LOD{i} evaluated mesh budget is missing thermal")
    ratio = tri1 / tri0 if tri0 else 0
    if not args.partial and not 36000 <= tri1 <= 44000:
        errors.append(f"LOD1 should be within 10% of 40,000 triangles, got {tri1}")
    report["lod1_ratio"] = round(ratio, 4)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"QA report {args.out}, triangle counts {tri0}/{tri1}, errors {len(errors)}")
    if errors:
        raise RuntimeError("\n".join(errors))


def layer_collections(layer):
    yield layer
    for child in layer.children:
        yield from layer_collections(child)


if __name__ == "__main__":
    main()











