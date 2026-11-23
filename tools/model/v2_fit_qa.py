"""Audit exterior coverage and articulated-shell contacts without saving the scene.

Run with Blender: blender -b art/suit/suit.blend --python-exit-code 1
    --python tools/model/v2_fit_qa.py -- --out art/suit/v2_qa.json
Run the same script on v1 and EXO T3a for comparable pose/view results.
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

SOURCE = Path(os.environ.get('JUGGERNAUT_EXO_SOURCE', 'C:/SPT/_fullbody_armor/exoskeleton/gpt'))
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))
import armor_check
import review

VIEWS = {
    'front': (0, -1, 0), 'front_left': (1, -1, 0), 'left': (1, 0, 0),
    'back_left': (1, 1, 0), 'back': (0, 1, 0), 'back_right': (-1, 1, 0),
    'right': (-1, 0, 0), 'front_right': (-1, -1, 0), 'upper_front': (0, -1, .5),
    'upper_back': (0, 1, .5),
}
PROOF_VIEWS = ('front', 'front_left', 'front_right', 'left', 'back', 'right', 'upper_front')
OPENING_RIM_DEPTH = .018
MIN_CONTACT_DEPTH_MM = 2.0


def object_set(lod):
    collection = bpy.data.collections[f'EXO_LOD{lod}']
    armor_check.make_visible(collection)
    return sorted(collection.all_objects, key=lambda obj: obj.name)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def structure(objects):
    errors = armor_check.rig_errors(review.ARM)
    parts = {}
    dominant = {}
    for lod, meshes in objects.items():
        for obj in meshes:
            mesh = obj.data
            mesh.calc_loop_triangles()
            bindings = [mod.object for mod in obj.modifiers if mod.type == 'ARMATURE']
            if bindings != [review.ARM]:
                errors.append(f'{obj.name} armature modifier does not bind to EFT_Bind')
            used = Counter()
            influences = Counter()
            invalid = 0
            for vertex in mesh.vertices:
                weights = [group for group in vertex.groups if group.weight > 0]
                influences[len(weights)] += 1
                if not 1 <= len(weights) <= 4 or abs(sum(group.weight for group in weights) - 1) > 1e-5:
                    invalid += 1
                for group in weights:
                    used[obj.vertex_groups[group.group].name] += group.weight
            if invalid:
                errors.append(f'{obj.name} has {invalid} vertices with invalid weights')
            unknown = sorted(set(used).difference(review.ARM.data.bones.keys()))
            if unknown:
                errors.append(f'{obj.name} uses unknown bones: {unknown}')
            if used:
                dominant[obj.name] = used.most_common(1)[0][0]
            if not mesh.uv_layers.active:
                errors.append(f'{obj.name} is missing UVs')
            else:
                layer = mesh.uv_layers.active.data
                if any(not math.isfinite(v) for loop in layer for v in loop.uv):
                    errors.append(f'{obj.name} has nonfinite UV coordinates')
            degenerate = sum(face.area <= 1e-12 for face in mesh.polygons)
            if degenerate:
                errors.append(f'{obj.name} has {degenerate} degenerate polygons')
            parts[obj.name] = {
                'lod': lod, 'vertices': len(mesh.vertices), 'triangles': len(mesh.loop_triangles),
                'bones': sorted(used), 'influence_histogram': dict(sorted(influences.items())),
            }
    data = {
        'source_bind_scene_sha256': digest(SOURCE / 'base_scene.blend'),
        'bones_compared': len(review.ARM.data.bones),
        'saved_pose': review.ARM.data.pose_position, 'errors': errors, 'parts': parts,
        'triangles_by_lod': {lod: sum(parts[obj.name]['triangles'] for obj in meshes)
                             for lod, meshes in objects.items()},
    }
    return data, dominant


def audit_export(path, source_triangles):
    source_path = Path(__file__).resolve().parents[2] / 'art' / 'suit' / 'eft_bindposes.json'
    source_groups = json.loads(source_path.read_text(encoding='utf-8'))
    source_binds = {name: bind for group in source_groups.values()
                    for name, bind in group['bind'].items()}
    export_bytes = path.read_bytes()
    exported = json.loads(export_bytes)
    bones = exported['bones']
    errors = []
    if len({bone['name'] for bone in bones}) != len(bones):
        errors.append('Unity export contains duplicate bones')
    max_bind_error = 0
    for bone in bones:
        source = source_binds.get(bone['name'])
        if not source or source['path'] != bone['path']:
            errors.append(f'Invalid Unity bind bone or path: {bone["name"]}')
            continue
        bindpose = np.array(bone['bindpose']).reshape(4, 4).T
        world = np.array(source['world'])
        residual = float(np.max(np.abs(bindpose @ world - np.eye(4))))
        if not math.isfinite(residual) or residual > 1e-6:
            errors.append(f'Invalid Unity inverse bind matrix: {bone["name"]}')
        max_bind_error = max(max_bind_error, residual)
    lods = {}
    if len(exported['lods']) != len(source_triangles):
        errors.append('Unity export LOD count differs from Blender')
    for lod, mesh in enumerate(exported['lods']):
        vertices = len(mesh['v']) // 3
        triangles = len(mesh['t']) // 3
        expected = {'v': vertices * 3, 'n': vertices * 3, 'uv': vertices * 2,
                    'bi': vertices * 4, 'bw': vertices * 4, 't': triangles * 3}
        if any(len(mesh[key]) != size for key, size in expected.items()):
            errors.append(f'Unity export LOD{lod} has inconsistent mesh stream sizes')
            continue
        if triangles != source_triangles.get(lod):
            errors.append(f'Unity export LOD{lod} triangle count differs from Blender')
        if not vertices or not triangles or min(mesh['t']) < 0 or max(mesh['t']) >= vertices:
            errors.append(f'Unity export LOD{lod} has invalid triangle indices')
        weights = np.array(mesh['bw']).reshape(vertices, 4)
        indices = np.array(mesh['bi']).reshape(vertices, 4)
        influence_counts = np.count_nonzero(weights > 0, axis=1)
        used_indices = indices[weights > 0]
        if (np.any(~np.isfinite(weights)) or np.any(weights < 0)
                or np.any(np.abs(weights.sum(axis=1) - 1) > 1e-6)
                or np.any(influence_counts < 1) or np.any(used_indices < 0)
                or np.any(used_indices >= len(bones))):
            errors.append(f'Unity export LOD{lod} has invalid bone weights or indices')
        lods[lod] = {'vertices': vertices, 'triangles': triangles,
                     'influence_histogram': {i: int(np.count_nonzero(influence_counts == i))
                                             for i in range(1, 5)}}
    return {
        'file': path.name, 'sha256': hashlib.sha256(export_bytes).hexdigest(),
        'eft_reference_sha256': digest(source_path),
        'bindposes_compared': len(bones), 'max_bind_identity_error': max_bind_error,
        'lods': lods, 'errors': errors,
    }


def combine(meshes):
    vertices, triangles = [], []
    for points, faces in meshes:
        offset = len(vertices)
        vertices.extend(points)
        triangles.extend(tuple(offset + index for index in tri) for tri in faces)
    return vertices, triangles


def vertex_region(name):
    suffix = name.removeprefix('Base Human')
    for token, zone in (
        ('Upperarm', 'upper_arm'), ('Forearm', 'forearm'), ('Digit', 'glove'),
        ('Palm', 'glove'), ('Thigh', 'thigh'), ('Calf', 'calf'),
        ('Foot', 'boot'), ('Toe', 'boot'), ('Collarbone', 'shoulder'),
    ):
        if token in suffix:
            return zone + '_' + suffix[0]
    return {'Neck': 'collar', 'Pelvis': 'pelvis'}.get(suffix, 'torso')


def garment_regions(refs, rest):
    labels, rim = [], []
    for obj in refs:
        points, triangles = rest[obj.name]
        zones = []
        for vertex in obj.data.vertices:
            totals = Counter()
            for weight in vertex.groups:
                name = obj.vertex_groups[weight.group].name
                totals[vertex_region(name)] += weight.weight
            zones.append(totals)
        collar_vertices = [i for i, totals in enumerate(zones) if totals['collar'] > .5]
        collar_top = max((points[i].z for i in collar_vertices), default=0)
        for tri in triangles:
            totals = sum((zones[i] for i in tri), Counter())
            zone = totals.most_common(1)[0][0]
            labels.append(zone)
            rim.append([zones[i]['collar'] > .5 and points[i].z >= collar_top - OPENING_RIM_DEPTH
                        for i in tri])
    return labels, rim


def coverage(garment, suits, points, labels, rim, direction, pitch, crop=None):
    direction = Vector(direction).normalized()
    horizontal = Vector((0, 0, 1)).cross(direction).normalized()
    vertical = direction.cross(horizontal)
    h = [p.dot(horizontal) for p in crop or points]
    v = [p.dot(vertical) for p in crop or points]
    left_cell = math.floor((min(h) - .01) / pitch)
    right_cell = math.ceil((max(h) + .01) / pitch)
    bottom_cell = math.floor((min(v) - .01) / pitch)
    top_cell = math.ceil((max(v) + .01) / pitch)
    width, height = right_cell - left_cell, top_cell - bottom_cell
    left, top = left_cell * pitch, top_cell * pitch
    towards_camera = max(p.dot(direction) for p in points) + .05
    corner = direction * towards_camera + horizontal * (left + pitch / 2) + vertical * (top - pitch / 2)
    ray = -direction
    sampled = Counter()
    visible = [Counter() for _ in suits]
    centers = [defaultdict(lambda: Vector((0, 0, 0))) for _ in suits]
    masks = [np.zeros((height, width), dtype=np.uint8) for _ in suits]
    for row in range(height):
        first = corner - vertical * (row * pitch)
        for col in range(width):
            origin = first + horizontal * (col * pitch)
            hit, _, face, distance = garment.ray_cast(origin, ray)
            zone = labels[face] if face is not None else None
            excluded = zone == 'collar' and all(rim[face])
            if zone and not excluded:
                sampled[zone] += 1
            for lod, suit in enumerate(suits):
                _, _, _, suit_distance = suit.ray_cast(origin, ray)
                if zone and (suit_distance is None or distance < suit_distance - .00005):
                    masks[lod][row, col] = 3 if excluded else 2
                    key = 'head_opening_rim' if excluded else zone
                    visible[lod][key] += 1
                    centers[lod][key] += hit
                elif suit_distance is not None:
                    masks[lod][row, col] = 1
    views = []
    for counts, sums in zip(visible, centers):
        opening = counts['head_opening_rim']
        numer = sum(counts.values()) - opening
        denom = sum(sampled.values())
        views.append({
            'garment_pixels': denom, 'visible_pixels': numer, 'opening_rim_visible_pixels': opening,
            'visible_percent': round(100 * numer / denom, 3) if denom else None,
            'projected_visible_cm2': round(numer * pitch ** 2 * 10_000, 3),
            'by_region': {
                label: {'garment_pixels': sampled[label], 'visible_pixels': counts[label],
                        'visible_center_world_m': [round(value / counts[label], 4) for value in sums[label]]
                        if counts[label] else None}
                for label in sorted(sampled)
            },
        })
    return views, masks


def posed_geometry(refs, objects):
    deps = bpy.context.evaluated_depsgraph_get()
    geometry = {obj.name: review._mesh(obj, deps) for obj in refs + objects[0] + objects[1]}
    body = combine(geometry[obj.name] for obj in refs)
    trees = [armor_check.mesh_tree(*combine(geometry[obj.name] for obj in objects[lod])) for lod in objects]
    garment = armor_check.mesh_tree(*body)
    points = body[0] + [point for obj in objects[0] + objects[1] for point in geometry[obj.name][0]]
    return geometry, body, trees, garment, points


def collar_turns(refs, objects, labels, rim, pitch):
    results = {}
    directions = ('front', 'back', 'left', 'right', 'upper_front', 'upper_back')
    parts = {
        lod: [obj.name for obj in meshes if any(token in obj.name.lower() for token in ('collar', 'gorget'))
              and is_hard_shell(obj)]
        for lod, meshes in objects.items()
    }
    for degrees in (-75, -45, 0, 45, 75):
        review.set_pose('rest')
        review._rotate('Base HumanNeck', Vector((0, 0, 1)), degrees)
        geometry, body, trees, garment, points = posed_geometry(refs, objects)
        collar = {index for face, zone in zip(body[1], labels)
                  if zone == 'collar' for index in face}
        crop = [body[0][index] for index in collar]
        views = {}
        for view in directions:
            rows, _ = coverage(garment, trees, points, labels, rim, VIEWS[view], pitch, crop=crop)
            views[view] = {lod: {'collar': row['by_region'].get('collar'),
                                  'opening_rim_visible_pixels': row['opening_rim_visible_pixels']}
                           for lod, row in enumerate(rows)}
        top = armor_check.mesh_tree(*geometry['REF_top'])
        jacket_contact = {}
        for lod, names in parts.items():
            jacket_contact[lod] = {}
            for name in names:
                vertices, triangles = geometry[name]
                collar_tree = armor_check.mesh_tree(vertices, triangles)
                jacket_contact[lod][name] = {
                    'crossing_triangle_pairs': len(collar_tree.overlap(top)),
                    'minimum_vertex_distance_mm': round(min(top.find_nearest(v)[3] for v in vertices) * 1000, 3),
                }
        results[degrees] = {'views': views, 'rigid_gorget_vs_reference_jacket': jacket_contact}
    return {'rigid_parts': parts, 'samples_by_degrees': results}


def is_hard_shell(obj):
    return (obj.get('juggernaut_hard_shell') or obj.get('v2_rigid')
            or obj.get('juggernaut_shell') or armor_check.is_armor(obj))


def shell_candidates(objects, dominant):
    return {obj.name: dominant[obj.name] for obj in objects if is_hard_shell(obj) and obj.name in dominant}


def shell_pair_count(shells):
    bone_counts = Counter(shells.values())
    return math.comb(len(shells), 2) - sum(math.comb(count, 2) for count in bone_counts.values())


def bounds(vertices):
    points = np.asarray(vertices, dtype=np.float64)
    return points.min(axis=0), points.max(axis=0)


def broadphase(shells, geometry):
    boxes = {name: bounds(geometry[name][0]) for name in shells}
    active = []
    for name in sorted(boxes, key=lambda name: (boxes[name][0][0], name)):
        lower, upper = boxes[name]
        active = [other for other in active if boxes[other][1][0] >= lower[0]]
        for other in active:
            if shells[name] == shells[other]:
                continue
            other_lower, other_upper = boxes[other]
            if np.all(lower[1:] <= other_upper[1:]) and np.all(other_lower[1:] <= upper[1:]):
                yield tuple(sorted((name, other)))
        active.append(name)


def shell_contacts(shells, geometry):
    meshes = {}

    def tree(name):
        if name not in meshes:
            meshes[name] = armor_check.mesh_tree(*geometry[name])
        return meshes[name]

    output = {}
    pairs = sorted(broadphase(shells, geometry))
    for a, b in pairs:
        mesh_a, mesh_b = tree(a), tree(b)
        overlaps = mesh_a.overlap(mesh_b)
        if not overlaps:
            continue
        ids_a, ids_b = zip(*overlaps)
        depth = [armor_check.contact_depth(geometry[a], set(ids_a), mesh_b),
                 armor_check.contact_depth(geometry[b], set(ids_b), mesh_a)]
        if max(value or 0 for value in depth) >= MIN_CONTACT_DEPTH_MM:
            output[f'{a} / {b}'] = {'crossing_triangle_pairs': len(overlaps),
                                      'sampled_penetration_mm': depth}
    return output, len(pairs)


def summarize(data):
    summary = {}
    for pose, lods in data['poses'].items():
        summary[pose] = {}
        for lod, report in lods.items():
            views = report['views']
            row = {
                'garment_rays': sum(view['garment_pixels'] for view in views.values()),
                'visible_rays': sum(view['visible_pixels'] for view in views.values()),
                'opening_rim_visible_rays': sum(view['opening_rim_visible_pixels'] for view in views.values()),
                'visible_percent': report['visible_percent_across_projections'],
                'worst_view': max(views, key=lambda view: views[view]['visible_percent']),
            }
            if 'shell_contacts' in report:
                rest = data['poses']['rest'][lod]['shell_contacts']
                contacts = report['shell_contacts']
                def depth(pair):
                    return max((value or 0 for value in pair['sampled_penetration_mm']), default=0)
                added = sorted(set(contacts) - set(rest), key=lambda name: -depth(contacts[name]))
                worsened = sorted(set(contacts) & set(rest),
                                  key=lambda name: -(depth(contacts[name]) - depth(rest[name])))
                row.update({
                    'shell_pairs_at_least_2_mm': len(contacts),
                    'pairs_only_above_threshold_in_pose': len(added),
                    'deepest_added_contacts_mm': [[name, depth(contacts[name])] for name in added[:5]],
                    'largest_depth_increases_mm': [
                        [name, depth(rest[name]), depth(contacts[name])]
                        for name in worsened[:5] if depth(contacts[name]) - depth(rest[name]) >= 2
                    ],
                })
            summary[pose][lod] = row
    return summary


def aggregate(summary):
    totals = {}
    for lod in next(iter(summary.values())):
        rows = [lods[lod] for lods in summary.values()]
        denom = sum(row['garment_rays'] for row in rows)
        exposed = sum(row['visible_rays'] for row in rows)
        totals[lod] = {'garment_rays': denom, 'visible_rays': exposed,
                       'visible_percent': round(100 * exposed / denom, 5),
                       'opening_rim_visible_rays': sum(row['opening_rim_visible_rays'] for row in rows)}
    return totals


def draw_png(path, rows, bin_size):
    def pool(mask):
        height, width = mask.shape
        padded = np.pad(mask, ((0, (-height) % bin_size), (0, (-width) % bin_size)))
        return padded.reshape(padded.shape[0] // bin_size, bin_size,
                              padded.shape[1] // bin_size, bin_size).max(axis=(1, 3))

    rows = [[pool(mask) for mask in row] for row in rows]
    width = max(mask.shape[1] for row in rows for mask in row)
    height = max(mask.shape[0] for row in rows for mask in row)
    # Dark background, matte suit, magenta exposed source garment, cyan head opening rim.
    colors = np.array(((17, 20, 24), (125, 132, 139), (255, 45, 130), (54, 199, 216)),
                      dtype=np.uint8)
    canvas = np.zeros((len(rows) * (height + 4), len(rows[0]) * (width + 4)), dtype=np.uint8)
    for row, panels in enumerate(rows):
        for col, mask in enumerate(panels):
            h, w = mask.shape
            y = row * (height + 4) + height - h
            x = col * (width + 4) + (width - w) // 2
            canvas[y:y + h, x:x + w] = mask
    rgb = colors[canvas]
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    ihdr = struct.pack('>IIBBBBB', rgb.shape[1], rgb.shape[0], 8, 2, 0, 0, 0)
    cells = b''.join(b'\0' + row.tobytes() for row in rgb)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
                     chunk(b'IDAT', zlib.compress(cells)) + chunk(b'IEND', b''))


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--pitch-mm', default=4, type=float)
    parser.add_argument('--proof', type=Path, help='PNG coverage sheet for LOD0')
    parser.add_argument('--compare', type=Path, action='append', default=[], help='Previously audited comparison JSON')
    parser.add_argument('--export', type=Path, help='Unity mesh JSON exported from this scene')
    parser.add_argument('--no-contacts', action='store_true', help='Skip contacts in coverage-only iterations')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.pitch_mm <= 0:
        parser.error('--pitch-mm must be positive')
    blend = Path(bpy.data.filepath).resolve()
    objects = {lod: object_set(lod) for lod in (0, 1)}
    refs = [bpy.data.objects[name] for name in ('REF_top', 'REF_pants')]
    for obj in refs:
        obj.hide_viewport = False
        obj.hide_set(False)
    audit, dominant = structure(objects)
    candidates = {lod: shell_candidates(meshes, dominant) for lod, meshes in objects.items()}
    data = {
        'blend': blend.name, 'blend_sha256': digest(blend),
        'method': {
            'projection': 'Orthographic first-hit BVH rays on a world-aligned grid over opaque two-sided triangles; garment visible when nearest with a 0.05 mm tie tolerance favoring suit',
            'coverage_denominator': 'First-hit projected REF_top and REF_pants pixels with armor absent',
            'head_opening_mask': 'Triangles with all vertices neck-weight dominant (>0.5) and within the top 18 mm of those vertices in rest space. Other collar points count.',
            'coverage_regions': 'Reference garment triangle labels by summed original bone weights',
            'pitch_mm': args.pitch_mm, 'pose_order': list(review.POSES),
            'proof_panel_columns': list(PROOF_VIEWS),
            'proof_pixel_pitch_mm': args.pitch_mm * max(1, math.ceil(4 / args.pitch_mm)),
            'proof_colors': {'suit': '#7d848b', 'exposed_reference': '#ff2d82', 'head_opening_rim': '#36c7d8'},
            'collar_turns': 'Neck rotations about world Z from rest with six projected views cropped to the posed neck region. Jacket crossing counts describe rigid gorget contact independent of exterior visibility.',
            'contacts': 'Selected rigid armor objects with distinct dominant bones and overlapping posed bounds. Crossing triangles with at least 2 mm sampled depth confirmed by multi-direction parity. Compare rest with posed values to identify movement-induced contact.',
            'uv': 'Checks finite UV coordinates. Intentional shared texture regions allowed.',
        },
        'reference_fingerprints': {obj.name: armor_check.frame_fingerprint(obj) for obj in refs},
        'structure': audit, 'contact_shell_objects': {lod: sorted(shells) for lod, shells in candidates.items()},
        'contact_candidate_pairs': {lod: shell_pair_count(shells) for lod, shells in candidates.items()},
        'poses': {},
    }
    if args.export:
        data['unity_export'] = audit_export(args.export, audit['triangles_by_lod'])
    panels = []
    try:
        review.set_pose('rest')
        deps = bpy.context.evaluated_depsgraph_get()
        rest = {obj.name: review._mesh(obj, deps) for obj in refs}
        labels, rim = garment_regions(refs, rest)
        for pose in review.POSES:
            review.set_pose(pose)
            geometry, _, trees, garment, points = posed_geometry(refs, objects)
            report = {lod: {'views': {}} for lod in objects}
            mask_row = {}
            for view, direction in VIEWS.items():
                results, masks = coverage(garment, trees, points, labels, rim, direction, args.pitch_mm / 1000)
                for lod in objects:
                    report[lod]['views'][view] = results[lod]
                if view in PROOF_VIEWS:
                    mask_row[view] = masks[0]
            panels.append([mask_row[view] for view in PROOF_VIEWS])
            for lod in objects:
                views = report[lod]['views']
                report[lod]['visible_percent_across_projections'] = round(
                    100 * sum(row['visible_pixels'] for row in views.values()) /
                    sum(row['garment_pixels'] for row in views.values()), 3)
                if not args.no_contacts:
                    contacts, contact_pair_count = shell_contacts(candidates[lod], geometry)
                    report[lod]['shell_contacts'] = contacts
                    report[lod]['contact_pairs_with_overlapping_bounds'] = contact_pair_count
                print(pose, f'LOD{lod}', report[lod]['visible_percent_across_projections'], flush=True)
            data['poses'][pose] = report
        data['collar_turns'] = collar_turns(refs, objects, labels, rim, args.pitch_mm / 1000)
    finally:
        review.restore_pose()
    for path in args.compare:
        other = json.loads(path.read_text(encoding='utf-8'))
        if data['reference_fingerprints'] != other['reference_fingerprints']:
            raise ValueError(f'Reference garment identity differs in {path}')
        if data['method']['pitch_mm'] != other['method']['pitch_mm']:
            raise ValueError(f'Ray pitch differs in {path}')
        data.setdefault('comparison', {})[path.stem] = {
            'blend_sha256': other['blend_sha256'],
            'aggregate': aggregate(other.get('summary') or summarize(other)),
            'visible_percent_across_projections': {
                pose: {str(lod): result['visible_percent_across_projections']
                       for lod, result in rows.items()} for pose, rows in other['poses'].items()
            },
        }
    summary = summarize(data)
    data = {'aggregate': aggregate(summary), 'summary': summary, **data}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    save_json(args.out, data)
    if args.proof:
        args.proof.parent.mkdir(parents=True, exist_ok=True)
        draw_png(args.proof, panels, max(1, math.ceil(4 / args.pitch_mm)))
    errors = audit['errors'] + data.get('unity_export', {}).get('errors', [])
    print('Structural errors:', errors, flush=True)
    if errors:
        raise RuntimeError('Suit structure audit failed')


if __name__ == '__main__':
    main()
