"""Check V5C's protected scene data and posed fit against the frozen V5B blend."""

import argparse
from collections import Counter, defaultdict
from hashlib import file_digest, sha256
from itertools import combinations, pairwise
import json
from pathlib import Path
import re
import sys

import bpy
from mathutils import Matrix
from mathutils.bvhtree import BVHTree

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from poses import POSES, apply_pose
from qa import Surface, check_mounts, check_native, check_skin, collision_record, layer_collections
from qa import near_matrix, sample_visibility, visibility_totals
from qa_feedback import CONTACT_LIMIT, LOWER_CHAIN, UPPER_CHAIN
from qa_feedback import check_inventory, check_materials, frame_components
from qa_feedback import Component, connected_triangle_sets, leg_connections
from qa_feedback import BRACKETS, closest_contact, contact_path, side_of


ENTRY = Path(__file__).resolve().parents[1]
WORK = ENTRY / "work" / "v5c"
WITNESSES = ("REF_top", "REF_pants", "REF_head")
LOD_NAMES = ("EXO_LOD0", "EXO_LOD1")
SHOULDER = re.compile(
    r"^[LR] ((Deltoid shell|Pauldron lower lame)( screw)?|Padded shoulder liner"
    r"|Flush armor rivet 0[1-4])(\.\d{3})?$"
)
LEG_ROLES = {
    0: "details and mounts", 1: "thigh shell", 3: "knee cap", 4: "shin greave",
    5: "ankle cuff", 6: "outsole", 7: "instep cover", 8: "calf plate",
    9: "upper thigh lame", 10: "middle thigh lame", 11: "lower thigh lame",
    12: "thigh mounting lugs", 13: "shin mounting lugs",
}


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def fingerprint(value):
    return sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def matrix(value):
    return [list(row) for row in value]


def modified(obj):
    return obj.get("part") == "leg_plates" or shoulder_assembly(obj)


def shoulder_assembly(obj):
    return obj.get("part") == "arm_plates" and bool(SHOULDER.fullmatch(obj.name))


def material_signature(material):
    if material is None:
        return None
    tree = material.node_tree
    nodes = []
    if tree:
        for node in sorted(tree.nodes, key=lambda node: node.bl_idname):
            sockets = []
            for socket in node.inputs:
                if hasattr(socket, "default_value"):
                    value = socket.default_value
                    sockets.append((socket.identifier, list(value) if hasattr(value, "__len__") else value))
            nodes.append((node.bl_idname, sockets))
    return [material.name, list(material.diffuse_color), material.roughness,
            material.metallic, nodes, sorted(
                (link.from_node.bl_idname, link.from_socket.identifier,
                 link.to_node.bl_idname, link.to_socket.identifier) for link in tree.links
            ) if tree else None]


def weights_signature(obj, indices):
    return [sorted((obj.vertex_groups[w.group].name, w.weight)
                   for w in obj.data.vertices[index].groups) for index in indices]


def mesh_signature(obj):
    mesh = obj.data
    return {
        "vertices": [list(vertex.co) for vertex in mesh.vertices],
        "edges": [(list(edge.vertices), edge.use_edge_sharp) for edge in mesh.edges],
        "polygons": [(list(face.vertices), face.material_index, face.use_smooth)
                     for face in mesh.polygons],
        "uv_layers": {layer.name: [list(loop.vector) for loop in layer.uv] for layer in mesh.uv_layers},
        "integer_face_roles": {attribute.name: [item.value for item in attribute.data]
                               for attribute in mesh.attributes
                               if attribute.domain == "FACE" and attribute.data_type == "INT"},
        "vertex_groups": sorted((group.name, group.lock_weight) for group in obj.vertex_groups),
        "weights": weights_signature(obj, range(len(mesh.vertices))),
        "materials": [material_signature(slot.material) for slot in obj.material_slots],
    }


def outsole_signature(obj):
    mesh = obj.data
    roles = mesh.attributes.get("armor_component")
    if not roles:
        return None
    faces = [face for face in mesh.polygons if roles.data[face.index].value == 6]
    if not faces:
        return None
    indices = sorted({index for face in faces for index in face.vertices})
    local = {index: i for i, index in enumerate(indices)}
    return {
        "vertices": [list(mesh.vertices[index].co) for index in indices],
        "faces": [(tuple(local[index] for index in face.vertices), face.use_smooth,
                   material_signature(obj.material_slots[face.material_index].material))
                  for face in faces],
        "weights": weights_signature(obj, indices),
    }


def object_attachment(obj):
    return {
        "world_matrix": matrix(obj.matrix_world),
        "parent_inverse": matrix(obj.matrix_parent_inverse),
        "matrix_basis": matrix(obj.matrix_basis),
        "parent": [obj.parent.name if obj.parent else None, obj.parent_type, obj.parent_bone],
        "scene_membership": sorted(collection.name for collection in obj.users_collection),
        "visibility": [obj.hide_render, obj.hide_viewport, obj.hide_get()],
        "modifiers": [(mod.name, mod.type, mod.show_viewport, mod.show_render,
                       [mod.object.name if mod.object else None, mod.vertex_group,
                        mod.use_vertex_groups, mod.use_bone_envelopes,
                        mod.use_deform_preserve_volume] if mod.type == "ARMATURE" else None)
                      for mod in obj.modifiers],
    }


def object_signature(obj):
    fields = object_attachment(obj)
    if obj.type == "MESH":
        fields.update(mesh_signature(obj))
        fields["frame_tags"] = [obj.get("frame_node"), obj.get("frame_nodes")]
    if obj.type == "ARMATURE":
        fields["rest_bones"] = [(bone.name, bone.parent.name if bone.parent else None,
                                 matrix(bone.matrix_local), list(bone.head_local),
                                 list(bone.tail_local), bone.length, bone.use_deform, bone.use_connect,
                                 bone.inherit_scale, bone.use_inherit_rotation, bone.use_local_location)
                                for bone in obj.data.bones]
        fields["saved_pose"] = [obj.data.pose_position, bpy.context.scene.frame_current,
                                [(bone.name, matrix(bone.matrix_basis), list(bone.constraints.keys()))
                                 for bone in obj.pose.bones],
                                obj.animation_data.action.name
                                if obj.animation_data and obj.animation_data.action else None]
    return {key: fingerprint(value) for key, value in fields.items()}


def protected_inventory(scene):
    result = {}
    for obj in sorted(scene.objects, key=lambda item: item.name):
        if not modified(obj):
            result[obj.name] = object_signature(obj)
        elif obj.get("part") == "leg_plates" and (data := outsole_signature(obj)):
            result[obj.name + " :: role 6 outsole"] = {
                key: fingerprint(value) for key, value in {**data, **object_attachment(obj)}.items()
            }
    return result


def shoulder_inventory(scene):
    return {obj.name: object_signature(obj) for obj in scene.objects if shoulder_assembly(obj)}


def compare_protected(baseline, current):
    return {
        "missing": sorted(baseline.keys() - current.keys()),
        "added": sorted(current.keys() - baseline.keys()),
        "changed": {key: sorted(field for field in baseline[key].keys() | current[key].keys()
                                if baseline[key].get(field) != current[key].get(field))
                    for key in sorted(baseline.keys() & current)
                    if baseline[key] != current[key]},
        "unchanged_count": sum(baseline[key] == current[key] for key in baseline.keys() & current),
    }


def drive_contacts(nodes):
    chains = [(chain[0], *(f"{name}.{side}" for name in chain[1:]))
              for chain in (UPPER_CHAIN, LOWER_CHAIN) for side in ("L", "R")]
    interfaces = list(dict.fromkeys([("spine", "belt"), *(edge for chain in chains for edge in pairwise(chain))]))
    adjacency = defaultdict(set)

    def connect(a, i, b, j):
        if not nodes[a][i].contact(nodes[b][j]):
            return 0
        adjacency[(a, i)].add((b, j))
        adjacency[(b, j)].add((a, i))
        return 1

    for name, islands in nodes.items():
        for i, j in combinations(range(len(islands)), 2):
            connect(name, i, name, j)
    gaps = []
    counts = {}
    for a, b in interfaces:
        count = sum(connect(a, i, b, j) for i in range(len(nodes[a])) for j in range(len(nodes[b])))
        label = f"{a} -> {b}"
        counts[label] = count
        if not count:
            gaps.append(label)
    terminals = {chain[-1] for chain in chains}
    routes = []
    for index in range(len(nodes["spine"])):
        pending = [("spine", index)]
        visited = set(pending)
        while pending:
            for item in adjacency[pending.pop()] - visited:
                visited.add(item)
                pending.append(item)
        routes.append(sorted(terminals & {name for name, _ in visited}))
    return {"contact_threshold_mm": CONTACT_LIMIT * 1000, "contact_counts": counts, "gaps": gaps,
            "spine_reached_terminals": routes, "continuous": any(set(route) == terminals for route in routes)}


class LegSection(Surface):
    """Label the triangles of one role within a consolidated leg mesh."""

    def __init__(self, surface, role, triangles):
        self.obj = surface.obj
        self.role = role
        self.vertices = surface.vertices
        self.triangles = triangles
        self.bvh = BVHTree.FromPolygons(self.vertices, triangles, all_triangles=True)


def leg_sections(surface):
    if not surface.armor_roles:
        return []
    by_role = defaultdict(list)
    for triangle, face in zip(surface.triangles, surface.triangle_faces):
        by_role[surface.armor_roles[face]].append(triangle)
    return [LegSection(surface, role, triangles) for role, triangles in sorted(by_role.items())]


def surface_label(surface):
    if isinstance(surface, LegSection):
        return f"{surface.obj.name} / {LEG_ROLES.get(surface.role, surface.role)}"
    return surface.obj.name


def lug_attachment_fit(surfaces, nodes):
    report = {}
    for surface in surfaces:
        if surface.obj.get("part") != "leg_plates":
            continue
        side = side_of(surface)
        role_sections = {section.role: section for section in leg_sections(surface)}
        for lug_role, shell_role in ((12, 1), (13, 4)):
            lug_section = role_sections.get(lug_role)
            if lug_section is None:
                continue
            # The generator emits the upper bracket lug before the lower one.
            lug_islands = sorted(connected_triangle_sets(lug_section.triangles),
                                 key=lambda island: min(index for triangle in island for index in triangle))
            shells = []
            if shell := role_sections.get(shell_role):
                largest = max(connected_triangle_sets(shell.triangles), key=len)
                shells = [Component(shell, largest)]
            bracket_names = [name for name, (role, _) in BRACKETS.items() if role == shell_role]
            if len(lug_islands) != len(bracket_names):
                report[f"{LEG_ROLES[lug_role]}.{side}"] = {
                    "connected_path": False, "lug_islands": len(lug_islands),
                    "expected_lug_islands": len(bracket_names),
                }
                continue
            for bracket, island in zip(bracket_names, lug_islands):
                key = f"{bracket}.{side}"
                lug = Component(lug_section, island)
                brackets = nodes.get(key, [])
                housing = nodes.get(f"{BRACKETS[bracket][1]}.{side}", [])
                shell_mate = closest_contact([lug], shells, .15)
                report[key] = {
                    "housing_to_bracket": closest_contact(housing, brackets, .15),
                    "bracket_to_lug": closest_contact(brackets, [lug], .15),
                    "lug_to_principal_shell": shell_mate,
                    "connected_path": (
                        bool(shell_mate and shell_mate["gap_mm"] <= CONTACT_LIMIT * 1000)
                        and contact_path(brackets, [lug], housing)
                    ),
                }
    return report


def amended(surface):
    if isinstance(surface, LegSection):
        return surface.role != 6
    return modified(surface.obj)


def pose_contacts(surfaces):
    """Use evaluated surface intersections. Contact alone cannot classify an attachment."""
    collisions = defaultdict(list)
    sections = [section for surface in surfaces for section in (
        leg_sections(surface) if surface.obj.get("part") == "leg_plates" and surface.armor_roles else (surface,)
    )]
    for a, b in combinations(sections, 2):
        if not (amended(a) or amended(b)):
            continue
        collision = collision_record(a, b)
        if collision:
            collision["pair"] = [surface_label(a), surface_label(b)]
            if a.obj.name in WITNESSES or b.obj.name in WITNESSES:
                kind = "native_witness"
            elif a.obj.get("part") == "cloth" or b.obj.get("part") == "cloth":
                kind = "undersuit"
            elif a.obj.get("part") in ("arm_frame", "leg_frame", "upper_frame") or (
                    b.obj.get("part") in ("arm_frame", "leg_frame", "upper_frame")):
                kind = "frame"
            else:
                kind = "other_equipment"
            collisions[kind].append(collision)
    return dict(collisions)


def inspect_plate_topology(surfaces):
    results = {}
    for surface in surfaces:
        if not modified(surface.obj):
            continue
        sections = leg_sections(surface) if surface.armor_roles else [surface]
        for section in sections:
            if not amended(section) or isinstance(section, LegSection) and section.role == 0:
                continue
            islands = sorted(connected_triangle_sets(section.triangles), key=len, reverse=True)
            open_islands = [len(island) for island in islands if not Component(section, island).closed]
            degenerate = sum((section.vertices[b] - section.vertices[a]).cross(
                section.vertices[c] - section.vertices[a]).length < 1e-10 for a, b, c in section.triangles)
            results[surface_label(section)] = {
                "island_triangles": [len(island) for island in islands],
                "open_or_nonmanifold_island_triangles": open_islands,
                "degenerate_triangles": degenerate,
            }
    return results


def build_report(path, step):
    scene = bpy.context.scene
    rig = scene.objects["EFT_Bind"]
    ref = [scene.objects[name] for name in WITNESSES]
    lods = [bpy.data.collections[name] for name in LOD_NAMES]
    errors = []
    report = {
        "blend": str(path),
        "sha256": digest(path),
        "native_reference_objects": list(WITNESSES),
        "native_witness_render_layers": {
            layer.name: sorted(obj.name for obj in ref if obj.name in layer.objects and not obj.hide_render)
            for layer in scene.view_layers if layer.use
        },
        "render": {"engine": scene.render.engine, "cycles_device": scene.cycles.device},
        "protected": protected_inventory(scene),
        "amended_shoulders": shoulder_inventory(scene),
        "inventory": check_inventory(scene, lods, ref, errors, partial=False),
        "materials": check_materials(scene, errors),
        "lods": {},
        "errors": errors,
    }
    if any(not near_matrix(bone.matrix_basis, Matrix.Identity(4)) for bone in rig.pose.bones):
        errors.append("Saved armature outside bind pose")
    if report["render"] != {"engine": "CYCLES", "cycles_device": "GPU"}:
        errors.append("Saved renderer is not Cycles GPU")
    if not any(witnesses == sorted(WITNESSES)
               for witnesses in report["native_witness_render_layers"].values()):
        errors.append("No enabled view layer includes all three original render witnesses")
    check_native(rig, ref, errors)
    for layer in layer_collections(bpy.context.view_layer.layer_collection):
        layer.exclude = False
        layer.hide_viewport = False
        layer.collection.hide_viewport = False
    for obj in scene.objects:
        obj.hide_set(False)
        obj.hide_viewport = False
    for lod in lods:
        objects = sorted((obj for obj in lod.all_objects if obj.type == "MESH"), key=lambda obj: obj.name)
        histogram = Counter()
        for obj in objects:
            histogram.update(check_skin(obj, rig, errors))
        records = {}
        report["lods"][lod.name] = {"poses": records, "weights_by_influence_count": dict(histogram)}
        for pose in POSES:
            apply_pose(rig, pose)
            graph = bpy.context.evaluated_depsgraph_get()
            surfaces = [Surface(obj, graph) for obj in objects]
            witnesses = [Surface(obj, graph) for obj in ref]
            mounts = check_mounts(rig, surfaces, errors, partial=False)
            if pose != "rest":
                for name, record in mounts.items():
                    if not near_matrix(record["neutral_neck_offset"],
                                       records["rest"]["mounts"][name]["neutral_neck_offset"]):
                        errors.append(f"{lod.name} {pose}: {name} moved off Neck-relative transform")
            coverage = sample_visibility(rig, witnesses, surfaces, step)
            nodes = frame_components(surfaces)
            drive = drive_contacts(nodes)
            mount_findings = []
            armor_mounts = leg_connections(surfaces, nodes, int(lod.name[-1]), pose, mount_findings)
            if lug_fit := lug_attachment_fit(surfaces, nodes):
                armor_mounts["lug_paths"] = lug_fit
                mount_findings = [note for note in mount_findings
                                  if "bracket-to-shell" not in note and "separate islands" not in note]
                mount_findings.extend(
                    f"{lod.name} {pose}: disconnected housing → bracket → lug → shell for {name}"
                    for name, info in lug_fit.items() if not info["connected_path"]
                )
                expected_lug_paths = {f"{bracket}.{side}" for bracket in BRACKETS for side in ("L", "R")}
                mount_findings.extend(f"{lod.name} {pose}: missing lug path record for {name}"
                                      for name in sorted(expected_lug_paths - lug_fit.keys()))
            if drive["gaps"] or not drive["continuous"]:
                errors.append(f"{lod.name} {pose}: drivetrain contact graph break {drive['gaps']}")
            records[pose] = {
                "drive": drive, "witness_coverage": visibility_totals(coverage),
                "witness_views": {view: counts for view, counts in coverage.items()
                                  if counts["regions_m"]},
                "contacts": pose_contacts([*surfaces, *witnesses]), "mounts": mounts,
                "armor_attachment_fit": armor_mounts, "armor_attachment_findings": mount_findings,
            }
            if pose == "rest":
                report["lods"][lod.name]["triangles"] = sum(len(s.triangles) for s in surfaces)
                topology = inspect_plate_topology(surfaces)
                report["lods"][lod.name]["plate_topology"] = topology
                for label, record in topology.items():
                    if record["open_or_nonmanifold_island_triangles"] or record["degenerate_triangles"]:
                        errors.append(f"{lod.name}: open, nonmanifold, or degenerate geometry in {label}")
            print(f"{path.name} {lod.name} {pose}: drive {'OK' if drive['continuous'] else 'FAIL'}, "
                  f"native rays exposed {records[pose]['witness_coverage']['exposed_samples']}", flush=True)
    lod0, lod1 = (report["lods"][name]["triangles"] for name in LOD_NAMES)
    report["lod1_to_lod0_ratio"] = round(lod1 / lod0, 5)
    if lod0 > 80_000:
        errors.append("LOD0 exceeds 80,000 triangles")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=WORK / "baseline.blend")
    parser.add_argument("--out", type=Path, default=WORK / "qa_frozen.json")
    parser.add_argument("--step", type=float, default=.006, help="Witness ray spacing in metres")
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if args.step <= 0 or not args.out.resolve().is_relative_to(ENTRY):
        parser.error("Use a positive step and keep output inside the entry.")
    main_path = Path(bpy.data.filepath)
    baseline_path = args.baseline.resolve()
    expected_baseline_hash = (WORK / "baseline.sha256").read_text().strip()
    if digest(baseline_path) != expected_baseline_hash:
        raise RuntimeError("Baseline snapshot hash mismatch")

    def measure(path):
        if args.static_only:
            return {"blend": str(path), "sha256": digest(path),
                    "protected": protected_inventory(bpy.context.scene),
                    "amended_shoulders": shoulder_inventory(bpy.context.scene), "errors": []}
        return build_report(path, args.step)

    revised = measure(main_path)
    bpy.ops.wm.open_mainfile(filepath=str(baseline_path))
    baseline = measure(baseline_path)
    if digest(main_path) != revised["sha256"] or digest(baseline_path) != expected_baseline_hash:
        raise RuntimeError("An audited .blend changed during QA")
    diff = compare_protected(baseline.pop("protected"), revised.pop("protected"))
    shoulder_changes = compare_protected(baseline.pop("amended_shoulders"), revised.pop("amended_shoulders"))
    report = {"revised": revised, "baseline": baseline, "protected_comparison": diff,
              "amended_shoulder_assembly": shoulder_changes,
              "witness_sampling": {"step_m": args.step, "views": 10, "depth_tolerance_m": .003,
                                   "measure": "Orthographic rays against evaluated original clothing and head"},
              "contact_measure": "Triangle crossings include intended attachments. Check regions and poses."}
    if not args.static_only:
        report["witness_exposure_delta_samples"] = {
            lod: {pose: revised["lods"][lod]["poses"][pose]["witness_coverage"]["exposed_samples"]
                  - baseline["lods"][lod]["poses"][pose]["witness_coverage"]["exposed_samples"]
                  for pose in POSES} for lod in LOD_NAMES
        }
        for lod, poses in report["witness_exposure_delta_samples"].items():
            for pose, delta in poses.items():
                if delta > 0:
                    revised["errors"].append(f"{lod} {pose}: {delta} new visible native witness rays")
    if diff["missing"] or diff["added"] or diff["changed"]:
        revised["errors"].append("Protected scene differs from baseline")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"QA {args.out}: {diff['unchanged_count']} protected objects/regions unchanged", flush=True)
    if revised["errors"]:
        raise RuntimeError("\n".join(revised["errors"]))


if __name__ == "__main__":
    main()
