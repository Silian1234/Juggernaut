"""Reduce fitted leg sheets while keeping their rims and original skin samples."""
from collections import Counter, defaultdict
from heapq import heappop, heappush
from itertools import pairwise, product

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree


SEAM_CHORD_TOLERANCE = .00028
QUADRIC_TOLERANCE = .0012
NORMAL_OFFSET_LIMIT = .0025
CREASE_COSINE = .65
MIN_COLLAPSED_NORMAL_COSINE = .5
COLLISION_CELL_SIZE = .012


def _edges(face):
    return (tuple(sorted(edge)) for edge in pairwise((*face, face[0])))


def _triangulation(geo):
    mesh = bpy.data.meshes.new("Leg reduction scratch")
    try:
        mesh.from_pydata(geo.vertices, [], geo.faces)
        mesh.calc_loop_triangles()
        by_face = defaultdict(list)
        for triangle in mesh.loop_triangles:
            by_face[triangle.polygon_index].append(tuple(triangle.vertices))
        return by_face
    finally:
        bpy.data.meshes.remove(mesh)


class _ShellCollisions:
    """Index nearby triangles so each collapse can check its replacement fan."""

    def __init__(self, points):
        self.points = points
        self.cells = defaultdict(set)
        self.membership = {}

    def triangle_cells(self, triangle, component):
        points = self.points[list(triangle)]
        lo = np.floor(points.min(axis=0) / COLLISION_CELL_SIZE).astype(int)
        hi = np.floor(points.max(axis=0) / COLLISION_CELL_SIZE).astype(int)
        ranges = [range(a, b + 1) for a, b in zip(lo, hi)]
        return tuple((component, x, y, z) for x, y, z in product(*ranges))

    def insert(self, index, cells):
        self.membership[index] = cells
        for cell in cells:
            self.cells[cell].add(index)

    def remove(self, index):
        for cell in self.membership.pop(index):
            self.cells[cell].remove(index)

    def would_cross(self, triangles, removed, replacements, replacement_cells):
        nearby = {i for cells in replacement_cells.values()
                  for cell in cells for i in self.cells.get(cell, ())} - removed
        local = [*replacements.values(), *(triangles[i] for i in sorted(nearby))]
        vertices = sorted({v for triangle in local for v in triangle})
        indices = {v: i for i, v in enumerate(vertices)}
        tree = BVHTree.FromPolygons(self.points[vertices].tolist(),
                                   [tuple(indices[v] for v in triangle) for triangle in local],
                                   all_triangles=True)
        faces = [set(triangle) for triangle in local]
        return any(a < b and a < len(replacements) and faces[a].isdisjoint(faces[b])
                   for a, b in tree.overlap(tree))


def reduce(geo, max_triangles):
    """Mutate a leg-plate Geometry and return its final triangle count."""
    count = sum(len(face) - 2 for face in geo.faces)
    if count <= max_triangles:
        return count

    points = np.asarray(geo.vertices)
    homogenized = np.column_stack((points, np.ones(len(points))))
    quadrics = np.zeros((len(points), 4, 4))
    areas = np.zeros(len(points))
    inner = {face for faces in geo.inner_faces.values() for face in faces}
    face_tags = [
        (component, material, smooth, i in inner)
        for i, (component, material, smooth) in enumerate(
            zip(geo.armor_components, geo.surfaces, geo.smooth))
    ]
    edge_faces = defaultdict(list)
    normals = []
    for i, face in enumerate(geo.faces):
        for edge in _edges(face):
            edge_faces[edge].append(i)
        a, b, c = points[list(face[:3])]
        normal = np.cross(b - a, c - a)
        magnitude = np.linalg.norm(normal)
        normals.append(normal / magnitude if magnitude > 1e-12 else normal)

    structural = set(inner)
    pending = list(inner)
    while pending:
        i = pending.pop()
        for edge in _edges(geo.faces[i]):
            for neighbor in edge_faces[edge]:
                if neighbor not in structural and face_tags[neighbor][0] == face_tags[i][0]:
                    structural.add(neighbor)
                    pending.append(neighbor)

    locked = set()
    seams = defaultdict(dict)
    seam_samples = {}
    for edge, adjacent in edge_faces.items():
        if len(adjacent) != 2 or edge in geo.sharp_edges:
            locked.update(edge)
            continue
        tag_a, tag_b = (face_tags[i] for i in adjacent)
        if tag_a != tag_b or normals[adjacent[0]] @ normals[adjacent[1]] < CREASE_COSINE:
            a, b = edge
            signature = frozenset((tag_a, tag_b))
            seams[a][b] = signature
            seams[b][a] = signature
            seam_samples[edge] = [a, b]
    for vertex, links in seams.items():
        if len(links) != 2 or len(set(links.values())) != 1:
            locked.add(vertex)
    for i, face in enumerate(geo.faces):
        if i not in structural or geo.armor_components[i] in (0, 6) or i in geo.band_coordinates:
            locked.update(face)
    # Keep the measured endpoints of every component's thickness range.
    used = {v for face in geo.faces for v in face}
    def thickness(pair):
        a, b = pair
        delta = points[a] - points[b]
        return delta @ delta

    for flat in geo.depth_pairs.values():
        pairs = [(a, b) for a, b in zip(flat[::2], flat[1::2]) if a in used and b in used]
        if pairs:
            locked.update(min(pairs, key=thickness))
            locked.update(max(pairs, key=thickness))

    triangles = {}
    origins = {}
    incident = defaultdict(set)
    source_triangles = {}
    collisions = _ShellCollisions(points)
    for source, tessellation in _triangulation(geo).items():
        source_triangles[source] = []
        for triangle in tessellation:
            index = len(triangles)
            triangles[index] = triangle
            origins[index] = source
            source_triangles[source].append(index)
            component = geo.armor_components[source]
            collisions.insert(index, collisions.triangle_cells(triangle, component))
            a, b, c = points[list(triangle)]
            normal = np.cross(b - a, c - a)
            area = np.linalg.norm(normal)
            if area > 1e-12:
                normal /= area
                plane = np.append(normal, -normal @ a)
                quadric = area * np.outer(plane, plane)
                for vertex in triangle:
                    quadrics[vertex] += quadric
                    areas[vertex] += area
            for vertex in triangle:
                incident[vertex].add(index)

    queue = []
    version = Counter()

    def neighbors(vertex):
        return {other for i in incident[vertex] for other in triangles[i]
                if other != vertex}

    def seam_merge(remove, keep):
        links = seams.get(remove)
        if not links:
            return None
        if keep not in links:
            return False
        other = next(v for v in links if v != keep)
        if other in seams[keep]:
            return False
        samples = (seam_samples[tuple(sorted((remove, keep)))]
                   + seam_samples[tuple(sorted((remove, other)))])
        start = points[keep]
        segment = points[other] - start
        length = segment @ segment
        if length <= 1e-16:
            return False
        offsets = points[samples] - start
        fraction = np.clip(offsets @ segment / length, 0, 1)
        error = offsets - fraction[:, None] * segment
        if np.max(np.linalg.norm(error, axis=1)) > SEAM_CHORD_TOLERANCE:
            return False
        return other, samples, links[keep]

    def enqueue(remove, keep):
        if remove in locked or not incident[remove]:
            return
        if seams.get(remove) and keep not in seams[remove]:
            return
        q = quadrics[remove] + quadrics[keep]
        p = homogenized[keep]
        area = areas[remove] + areas[keep]
        if area:
            error = max(0., (p @ q @ p) / area)
            if error <= QUADRIC_TOLERANCE ** 2:
                heappush(queue, (error, remove, keep, version[remove], version[keep]))

    for vertex in sorted(incident):
        for other in sorted(neighbors(vertex)):
            enqueue(vertex, other)

    changed = set()
    while queue and count > max_triangles:
        _, remove, keep, rv, kv = heappop(queue)
        if version[remove] != rv or version[keep] != kv:
            continue
        seam = seam_merge(remove, keep)
        if seam is False:
            continue
        ring = set(incident[remove])
        common = ring & incident[keep]
        if len(common) != 2:
            continue
        opposite = {v for i in common for v in triangles[i] if v not in (remove, keep)}
        if neighbors(remove) & neighbors(keep) != opposite:
            continue
        replacements = {}
        remaining = {frozenset(triangles[i]) for i in incident[keep] - common}
        for i in ring - common:
            old = triangles[i]
            new = tuple(keep if v == remove else v for v in old)
            key = frozenset(new)
            if key in remaining:
                break
            remaining.add(key)
            a, b, c = points[list(old)]
            old_normal = np.cross(b - a, c - a)
            a, b, c = points[list(new)]
            new_normal = np.cross(b - a, c - a)
            old_area = np.linalg.norm(old_normal)
            new_area = np.linalg.norm(new_normal)
            if (new_area < 1e-10
                    or old_normal @ new_normal <= MIN_COLLAPSED_NORMAL_COSINE * old_area * new_area):
                break
            # Limit local movement along the original normal on sharp curvature.
            displacement = points[keep] - points[remove]
            if abs(old_normal @ displacement) > NORMAL_OFFSET_LIMIT * old_area:
                break
            replacements[i] = new
        else:
            replacement_cells = {
                i: collisions.triangle_cells(triangle, geo.armor_components[origins[i]])
                for i, triangle in replacements.items()
            }
            if collisions.would_cross(triangles, ring, replacements, replacement_cells):
                continue
            affected = neighbors(remove) | neighbors(keep) | {remove, keep}
            for i in ring:
                collisions.remove(i)
                changed.add(origins[i])
                for v in triangles[i]:
                    incident[v].remove(i)
                if i in replacements:
                    triangles[i] = replacements[i]
                    collisions.insert(i, replacement_cells[i])
                    for v in triangles[i]:
                        incident[v].add(i)
                else:
                    del triangles[i]
            if seam:
                other, samples, signature = seam
                del seams[keep][remove], seams[other][remove], seams[remove]
                seams[keep][other] = seams[other][keep] = signature
                del seam_samples[tuple(sorted((remove, keep)))]
                del seam_samples[tuple(sorted((remove, other)))]
                seam_samples[tuple(sorted((keep, other)))] = samples
            quadrics[keep] += quadrics[remove]
            areas[keep] += areas[remove]
            count -= 2
            for v in affected:
                version[v] += 1
            for v in sorted(affected):
                for other in sorted(neighbors(v)):
                    enqueue(v, other)
                    if other not in affected:
                        enqueue(other, v)

    if changed:
        _compact(geo, triangles, source_triangles, changed)
    return count


def _compact(geo, triangles, source_triangles, changed):
    faces, surfaces, smooth, components = [], [], [], []
    inner_faces = defaultdict(list)
    inner = {face for indices in geo.inner_faces.values() for face in indices}
    band_coordinates = {}
    for i, original in enumerate(geo.faces):
        replacements = (
            [triangles[t] for t in source_triangles[i] if t in triangles]
            if i in changed else [original]
        )
        for face in replacements:
            if i in inner:
                inner_faces[geo.armor_components[i]].append(len(faces))
            if i in geo.band_coordinates:
                band_coordinates[len(faces)] = geo.band_coordinates[i]
            faces.append(face)
            surfaces.append(geo.surfaces[i])
            smooth.append(geo.smooth[i])
            components.append(geo.armor_components[i])

    # Keep unused source vertices belonging to unchanged details and slot grids.
    removed = {v for i in changed for v in geo.faces[i]} - {v for face in faces for v in face}
    survivors = [v for v in range(len(geo.vertices)) if v not in removed]
    remap = {v: i for i, v in enumerate(survivors)}
    geo.vertices = [geo.vertices[v] for v in survivors]
    geo.weights = [geo.weights[v] for v in survivors]
    geo.faces = [tuple(remap[v] for v in face) for face in faces]
    geo.surfaces, geo.smooth, geo.armor_components = surfaces, smooth, components
    geo.band_coordinates = band_coordinates
    geo.inner_faces = dict(inner_faces)
    geo.sharp_edges = {tuple(sorted((remap[a], remap[b]))) for a, b in geo.sharp_edges}
    used = {v for face in geo.faces for v in face}
    geo.depth_pairs = {
        component: [remap[v] for a, b in zip(flat[::2], flat[1::2])
                    if a in remap and b in remap and remap[a] in used and remap[b] in used
                    for v in (a, b)]
        for component, flat in geo.depth_pairs.items()
    }


