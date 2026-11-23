"""Read the saved suit and measure skinning, atlas, and six poses in Blender."""
import json
import os
import sys
from itertools import combinations
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

SOURCE = Path(os.environ.get('JUGGERNAUT_EXO_SOURCE', 'C:/SPT/_fullbody_armor/exoskeleton/gpt'))
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))

import armor_check
import review
from validate import uv_stats



def geometry(obj, deps):
    vertices, triangles = review._mesh(obj, deps)
    return vertices, BVHTree.FromPolygons(vertices, triangles, all_triangles=True)


def structure(sets):
    rig = bpy.data.objects['EFT_Bind']
    errors = armor_check.rig_errors(rig)
    parts = {}
    uvs = []
    for lod, meshes in sets.items():
        prefix = ('EXO_', 'EXO1_')[lod]
        for obj in meshes:
            if not obj.name.startswith(prefix):
                errors.append(obj.name + ' unexpected name')
            mesh = obj.data
            if [mat.name for mat in mesh.materials] != ['exo_mat']:
                errors.append(obj.name + ' material mismatch')
            if len(obj.modifiers) != 1 or obj.modifiers[0].type != 'ARMATURE' or obj.modifiers[0].object != rig:
                errors.append(obj.name + ' armature binding mismatch')
            if any(len(face.vertices) > 4 or face.area <= 1e-12 for face in mesh.polygons):
                errors.append(obj.name + ' invalid polygon')
            max_influences = 0
            used_bones = set()
            for vertex in mesh.vertices:
                groups = [grp for grp in vertex.groups if grp.weight > 0]
                max_influences = max(max_influences, len(groups))
                used_bones.update(obj.vertex_groups[grp.group].name for grp in groups)
                if not 1 <= len(groups) <= 4 or abs(sum(grp.weight for grp in groups) - 1) > 1e-5:
                    errors.append(f'{obj.name} invalid weights on vertex {vertex.index}')
            unknown_bones = used_bones.difference(rig.data.bones.keys())
            if unknown_bones or (obj.get('juggernaut_shell') and max_influences != 1):
                errors.append(obj.name + ' unknown bone or nonrigid shell weights')
            mesh.calc_loop_triangles()
            # Both LODs are packed into one mutually disjoint UV atlas.
            layer = mesh.uv_layers.active.data
            uvs.extend([tuple(layer[i].uv) for i in tri.loops] for tri in mesh.loop_triangles)
            parts[obj.name] = {
                'lod': lod, 'triangles': len(mesh.loop_triangles),
                'bones': sorted(used_bones), 'max_influences': max_influences,
            }
    uv = uv_stats(uvs)
    if any(v for k, v in uv.items() if k != 'triangle_area_percent'):
        errors.append(f'Invalid UV atlas: {uv}')
    maps = {}
    material = bpy.data.materials['exo_mat']
    for node in material.node_tree.nodes:
        if node.type != 'TEX_IMAGE':
            continue
        image = node.image
        path = Path(bpy.path.abspath(image.filepath))
        maps[path.name] = {'size': list(image.size), 'color_space': image.colorspace_settings.name}
        if not path.is_file() or not image.filepath.replace(chr(92), '/').startswith('//textures/') or list(image.size) != [2048, 2048]:
            errors.append('Missing or invalid texture ' + str(path))
    if set(maps) != {'exo_dif.png', 'exo_nrm.png', 'exo_gloss.png'}:
        errors.append('Expected three atlas PNGs')
    return {'parts': parts, 'uv': uv, 'textures': maps, 'errors': errors,
            'bones_compared': len(rig.data.bones), 'saved_pose': rig.data.pose_position}


def clothing_report(parts, garments, deps):
    meshes = {obj.name: geometry(obj, deps) for obj in parts}
    clothing = {}
    added_clearance = {}
    for obj in parts:
        vertices, shell = meshes[obj.name]
        for tag, garment in garments.items():
            overlap = shell.overlap(garment)
            if overlap:
                clothing.setdefault(obj.name, {})[tag] = len(overlap)
        if obj.get('juggernaut_shell'):
            gap = [min(garment.find_nearest(v)[3] for garment in garments.values()) for v in vertices]
            added_clearance[obj.name] = {'min_vertex_mm': round(min(gap) * 1000, 2),
                                         'max_vertex_mm': round(max(gap) * 1000, 2)}
    pairs = {}
    for a, b in combinations(parts, 2):
        if not (a.get('juggernaut_shell') or b.get('juggernaut_shell')):
            continue
        if not (a.get('juggernaut_shell') or a.get('t3a_armor')):
            continue
        if not (b.get('juggernaut_shell') or b.get('t3a_armor')):
            continue
        overlap = meshes[a.name][1].overlap(meshes[b.name][1])
        if overlap:
            pairs[a.name + ' / ' + b.name] = len(overlap)
    return {'clothing_crossing_pairs': clothing, 'new_shell_vertex_clearance': added_clearance,
            'plate_contacts': pairs}


def main():
    sets = {lod: sorted(bpy.data.collections[f'EXO_LOD{lod}'].objects, key=lambda o: o.name)
            for lod in (0, 1)}
    report = structure(sets)
    for lod in sets:
        armor_check.make_visible(bpy.data.collections[f'EXO_LOD{lod}'])
    report['poses'] = {}
    report['neck_yaw'] = {}
    refs = [bpy.data.objects[name] for name in ('REF_top', 'REF_pants')]
    for ref in refs:
        ref.hide_viewport = False
        ref.hide_set(False)
    try:
        for pose in review.POSES:
            review.set_pose(pose)
            deps = bpy.context.evaluated_depsgraph_get()
            garments = {ob.name: geometry(ob, deps)[1] for ob in refs}
            report['poses'][pose] = {lod: clothing_report(parts, garments, deps)
                                     for lod, parts in sets.items()}
        for angle in range(-75, 76, 5):
            review.set_pose('rest')
            review._rotate('Base HumanNeck', Vector((0, 0, 1)), angle)
            deps = bpy.context.evaluated_depsgraph_get()
            _, jacket = geometry(refs[0], deps)
            report['neck_yaw'][angle] = {
                obj.name: {'crossings': len(shell.overlap(jacket)),
                           'min_vertex_mm': round(min(jacket.find_nearest(v)[3] for v in vertices) * 1000, 2)}
                for objects in sets.values() for obj in objects if any(tag in obj.name.lower() for tag in ('gorget', 'collar'))
                for vertices, shell in (geometry(obj, deps),)
            }
    finally:
        review.restore_pose()
    path = Path(bpy.data.filepath).parent / 'suit_qa.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Written', path)
    print('Structure errors:', report['errors'])
    for pose, by_lod in report['poses'].items():
        print(pose, {lod: result['clothing_crossing_pairs'] for lod, result in by_lod.items()})
    if report['errors']:
        raise RuntimeError('Suit structural audit failed.')
    if any(result['clothing_crossing_pairs'] for by_lod in report['poses'].values() for result in by_lod.values()):
        raise RuntimeError('Clothing crossings detected.')
    if any(results['crossings'] for by_part in report['neck_yaw'].values() for results in by_part.values()):
        raise RuntimeError('Collar crossings detected.')


if __name__ == '__main__':
    main()





