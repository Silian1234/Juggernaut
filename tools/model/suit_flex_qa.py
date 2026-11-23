"""Quantify all deep-flex triangle intersections in both suit LODs."""
import json
import os
import sys
from itertools import combinations
from pathlib import Path

import bpy

SOURCE = Path(os.environ.get('JUGGERNAUT_EXO_SOURCE', 'C:/SPT/_fullbody_armor/exoskeleton/gpt'))
DEST = Path(__file__).resolve().parents[2] / 'art' / 'suit'
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))

import armor_check
import review


def metrics(obj, other, geometry, trees):
    crossings = trees[obj.name].overlap(trees[other.name])
    if not crossings:
        return None
    triangles_a, triangles_b = zip(*crossings)
    return {
        'parts': [obj.name, other.name],
        'crossing_triangle_pairs': len(crossings),
        'max_sampled_inside_mm_by_part': [
            armor_check.contact_depth(geometry[obj.name], set(triangles_a), trees[other.name]),
            armor_check.contact_depth(geometry[other.name], set(triangles_b), trees[obj.name]),
        ],
    }


def main():
    is_source = Path(bpy.data.filepath).name == 'exo_t3a.blend'
    report = {}
    sets = {lod: list(bpy.data.collections[f'EXO_LOD{lod}'].objects) for lod in (0, 1)}
    refs = [bpy.data.objects[n] for n in ('REF_top', 'REF_pants')]
    for lod in sets:
        armor_check.make_visible(bpy.data.collections[f'EXO_LOD{lod}'])
    for ref in refs:
        ref.hide_viewport = False
        ref.hide_set(False)
    try:
        for pose in ('rest', 'crouch', 'knee120'):
            review.set_pose(pose)
            deps = bpy.context.evaluated_depsgraph_get()
            geometry = {obj.name: review._mesh(obj, deps)
                        for obj in refs + sets[0] + sets[1]}
            trees = {name: armor_check.mesh_tree(*value) for name, value in geometry.items()}
            report[pose] = {}
            for lod, objects in sets.items():
                clothing = [entry for obj in objects for ref in refs
                            if (entry := metrics(obj, ref, geometry, trees))]
                armor = [entry for obj, other in combinations(objects, 2)
                         if (entry := metrics(obj, other, geometry, trees))]
                report[pose][lod] = {'clothing_vs_suit': clothing, 'all_suit_pairs': armor}
                count = sum(row['crossing_triangle_pairs'] for row in clothing)
                maximum = max((entry['max_sampled_inside_mm_by_part'][0] or 0
                               for entry in clothing), default=0)
                print(f'{pose} LOD{lod}: clothing crossings={count}, '
                      f'sampled shell depth={maximum} mm, suit object pairs={len(armor)}')
    finally:
        review.restore_pose()
    out = DEST / ('suit_flex_exo_t3a.json' if is_source else 'suit_flex_qa.json')
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
