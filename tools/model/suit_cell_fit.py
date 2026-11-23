"""Read-only fit check for the current power cell in the saved rest scene."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def geometry(objects, transform=None):
    vertices, triangles = [], []
    for obj in objects:
        if obj.type != 'MESH':
            continue
        start = len(vertices)
        vertices.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        obj.data.calc_loop_triangles()
        triangles.extend(tuple(i + start for i in face.vertices)
                         for face in obj.data.loop_triangles)
    if transform:
        vertices = [transform(v) for v in vertices]
    return vertices, BVHTree.FromPolygons(vertices, triangles, all_triangles=True)


def mount(vertex):
    return Vector((-vertex.x, .2695 - vertex.y, 1.28075 + vertex.z))


def main():
    suit = Path(bpy.data.filepath)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accessories', type=Path,
                        default=suit.parents[1] / 'accessories' / 'accessories.blend')
    parser.add_argument('--out', type=Path, help='Optional JSON evidence file.')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    source = args.accessories.resolve()
    with bpy.data.libraries.load(str(source), link=False) as (_, target):
        target.collections = ['JUG_CELL']
    cell = target.collections[0]
    bpy.context.scene.collection.children.link(cell)
    bpy.context.view_layer.update()
    points, cell_surface = geometry(cell.all_objects, mount)
    measurements = {}
    for lod in (0, 1):
        parts = bpy.data.collections[f'EXO_LOD{lod}'].objects
        dock = next(obj for obj in parts if obj.name.endswith('JuggPowerDock'))
        _, dock_surface = geometry((dock,))
        gap = min(dock_surface.find_nearest(point)[3] for point in points)
        crossings = {obj.name: len(cell_surface.overlap(geometry((obj,))[1])) for obj in parts}
        hits = {name: count for name, count in crossings.items() if count}
        measurements[lod] = {'dock': dock.name, 'minimum_sampled_dock_gap_mm': round(gap * 1000, 4),
                             'crossing_triangle_pairs_by_part': hits}
        print(f'LOD{lod}: {len(hits)} parts in surface contact, {gap * 1000:.2f} mm sampled dock gap')
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        report = {
            'suit_blend': suit.name, 'suit_sha256': hashlib.sha256(suit.read_bytes()).hexdigest(),
            'accessories_blend': source.name, 'accessories_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'pose': 'rest', 'battery_mount_center_m': list(mount(Vector((0, 0, 0)))),
            'measurements_by_lod': measurements,
        }
        args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for lod, result in measurements.items():
        hits = result['crossing_triangle_pairs_by_part']
        if hits:
            raise RuntimeError(f'Power cell crosses the LOD{lod} suit: {hits}')


if __name__ == '__main__':
    main()
