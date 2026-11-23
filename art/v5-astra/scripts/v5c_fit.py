"""Correct residual clearance errors on the skin-facing leg armor."""
from collections import defaultdict
from functools import lru_cache
from math import ceil

from mathutils import Vector
from mathutils.bvhtree import BVHTree

from leg_shells import between
from v5c_shin import SHIN_AXES
from v5c_thigh import AXIS


def _edges(face):
    return zip(face, (*face[1:], face[0]))


def _key(a, b):
    return (min(a, b), max(a, b))


def _axis(role, point, side):
    if role == 3:
        return Vector((0, -1, 0))
    if role == 7:
        return Vector((0, 0, 1))
    if role == 15:
        x = .22 - .4 * (point.z - .093)
        return Vector((point.x - side * x, point.y - .025, 0)).normalized()
    x, y = between(AXIS if role in (1, 9, 10, 11) else SHIN_AXES, point.z)
    return Vector((point.x - side * x, point.y - y, 0)).normalized()


@lru_cache(maxsize=None)
def _sample_net(n):
    return tuple((i / n, j / n, (n - i - j) / n)
                 for i in range(n + 1) for j in range(n + 1 - i))


def _measure(tree, point, axis):
    near, normal, _, distance = tree.find_nearest(point)
    signed = distance if (point - near).dot(normal) >= 0 else -distance
    gradient = (point - near).dot(axis) / signed if abs(signed) > 1e-8 else normal.dot(axis)
    return signed, max(.2, gradient)


def _mix_weights(groups, factors):
    mixed = {key: sum(g.get(key, 0) * factor for g, factor in zip(groups, factors))
             for key in set().union(*groups)}
    active = sorted(mixed, key=lambda key: (-mixed[key], key))[:4]
    total = sum(mixed[key] for key in active)
    return {key: mixed[key] / total for key in active if mixed[key] > 0}


def _triangulate(face, side):
    if len(face) == 3:
        return (face,)
    a, b, c, d = face
    return ((a, b, c), (a, c, d)) if side > 0 else ((a, b, d), (b, c, d))



def give_thigh_wall_room(geo, role, outer_faces, inner_faces):
    """Make a localized allowance for cloth peaks below a thigh panel."""
    tree = geo.cuff_fit.index
    clearance, maximum = (.0087, .007) if role == 1 else (.0080, .004)
    points = [Vector(v) for v in geo.vertices]
    inner = {v for i in inner_faces for v in geo.faces[i]}
    outer_shell = [f for f, component in zip(geo.faces, geo.armor_components)
                   if component == role and any(v not in inner for v in f)]
    axes = {v: _axis(role, points[v], geo.side) for f in outer_shell for v in f if v not in inner}
    if not axes:
        return
    displacement = dict.fromkeys(axes, 0.)
    for _ in range(9):
        changed = False
        for face in outer_shell:
            for tri in (*_triangulate(face, geo.side), *_triangulate(face, -geo.side)):
                # The existing back chamfer is adjusted with the back, below.
                if any(v in inner for v in tri):
                    continue
                # The first front lame sits behind the knee nose. Its hem and
                # bevel stay fixed while the upper half clears trouser creases.
                adjustable = [v for v in tri if role == 1 or points[v].z >= .620]
                if not adjustable:
                    continue
                corners = [points[v] + axes[v] * displacement[v] for v in tri]
                divisions = max(2, ceil(max((a - b).length for a, b in _edges(corners)) / .0016))
                worst = (0., None)
                for w in _sample_net(divisions):
                    if not any(a > .02 for v, a in zip(tri, w) if v in adjustable):
                        continue
                    point = sum((p * a for p, a in zip(corners, w)), Vector())
                    direction = sum((axes[v] * a for v, a in zip(tri, w)), Vector())
                    gap, slope = _measure(tree, point, direction)
                    correction = (clearance - gap) / slope
                    if correction > worst[0]:
                        worst = correction, w
                correction, w = worst
                if correction < .00005:
                    continue
                updates = [(v, a) for v, a in zip(tri, w) if v in adjustable and a > .02]
                norm = sum(a * a for _, a in updates)
                for v, a in updates:
                    old = displacement[v]
                    displacement[v] = min(maximum, old + .45 * correction * a / norm)
                    changed |= displacement[v] - old > .00001
        if not changed:
            break
    for v, amount in displacement.items():
        if amount:
            geo.vertices[v] = tuple(points[v] + axes[v] * amount)
    return points, {v: axes[v] * displacement[v] for f in outer_faces for v in f}


def mount_thigh_detail(room, point, side):
    """Carry the side-shield pads with their underlying recess."""
    if room is None:
        return point
    points, displacement = room
    world = Vector((side * point.x, point.y, point.z))
    candidates = sorted(((points[v] - world).length_squared, v) for v in displacement)[:4]
    # Blend the neighboring support displacements across the inset detail.
    total = Vector()
    norm = 0.
    for distance, v in candidates:
        influence = 1 / max(distance, 1e-7)
        total += displacement[v] * influence
        norm += influence
    total /= norm
    total.x *= side
    return point + total


def _relieve_back_crossings(geo, role, axes, lower_limits):
    """Close/localize backing corrections that would cut through a rim."""
    import bpy

    by_vertex = defaultdict(list)
    faces = [f for f, component in zip(geo.faces, geo.armor_components) if component == role]
    for i, face in enumerate(faces):
        for v in face:
            by_vertex[v].append(i)
    structural = {i for v in axes for i in by_vertex[v]}
    pending = list(structural)
    while pending:
        for v in faces[pending.pop()]:
            for i in by_vertex[v]:
                if i not in structural:
                    structural.add(i)
                    pending.append(i)
    mesh = bpy.data.meshes.new("V5C fitting triangles")
    try:
        mesh.from_pydata(geo.vertices, [], [faces[i] for i in sorted(structural)])
        mesh.calc_loop_triangles()
        triangles = [tuple(tri.vertices) for tri in mesh.loop_triangles]
    finally:
        bpy.data.meshes.remove(mesh)

    points = [Vector(p) for p in geo.vertices]
    initial = {v: points[v].copy() for v in axes}
    involved = [set(tri) for tri in triangles]

    def collisions():
        tree = BVHTree.FromPolygons(points, triangles, all_triangles=True)
        return [(a, b) for a, b in tree.overlap(tree)
                if a < b and not involved[a] & involved[b]]

    bad = collisions()
    for _ in range(3):
        movable = {}
        for a, b in bad:
            for v in (involved[a] | involved[b]) & axes.keys():
                movable[v] = movable.get(v, 0) + 1
        if not movable:
            break
        previous_count = len(bad)
        for v in sorted(movable, key=lambda v: (-movable[v], v)):
            original = points[v]
            remaining = (original - lower_limits[v]).dot(axes[v])
            if remaining < .00005:
                continue
            best_point, best_pairs = original, bad
            for step in (.00020, .00055, .0012, .0025):
                points[v] = original - axes[v] * min(step, remaining)
                test = collisions()
                if len(test) < len(best_pairs):
                    best_point, best_pairs = points[v], test
                    if not any(v in involved[a] or v in involved[b] for a, b in test):
                        break
            points[v], bad = best_point, best_pairs
        if len(bad) == previous_count:
            break
    for v, p in initial.items():
        if p != points[v]:
            geo.vertices[v] = tuple(points[v])

def _refine_role(geo, role, inner, budget):
    tree = (geo.boot_fit if role == 7 else geo.cuff_fit).index
    low, high = (.00505, .0090) if role == 7 else (.00565, .01135)
    points = [Vector(v) for v in geo.vertices]
    source = {i: geo.faces[i] for i in inner}
    vertices = {v for face in source.values() for v in face}
    # Include the back chamfer and vent edges when calculating safe travel toward
    # the fixed exterior. They contain no original outer vertices in the fit.
    targets = [f for i, f in enumerate(geo.faces)
               if i not in source and geo.armor_components[i] == role]
    exterior = BVHTree.FromPolygons(points, targets)
    axes, limits, shift = {}, {}, {}

    def append(index):
        p = points[index]
        direction = _axis(role, p, geo.side)
        hit, _, _, outer = exterior.ray_cast(p + direction * .00015, direction, .045)
        axes[index] = direction
        # Reserve material between the fitted back and the sculpted front.
        # Near the rim, use the actual first edge or face above the back.
        reserve = .0012 if role == 4 else .0014
        travel = .00012 if role == 4 and geo.lod else 0.
        if hit is not None:
            travel = max(travel, outer + .00015 - reserve)
        limits[index] = (-.009, travel)
        shift[index] = 0.

    for v in sorted(vertices):
        append(v)

    for index, face in tuple(source.items()):
        source[index] = list(_triangulate(face, geo.side))

    def current(v):
        return points[v] + axes[v] * shift[v]

    def sample(tri, spacing):
        corners = [current(v) for v in tri]
        count = max(2, ceil(max((a - b).length for a, b in _edges(corners)) / spacing))
        for w in _sample_net(count):
            p = corners[0] * w[0] + corners[1] * w[1] + corners[2] * w[2]
            axis = axes[tri[0]] * w[0] + axes[tri[1]] * w[1] + axes[tri[2]] * w[2]
            value, slope = _measure(tree, p, axis)
            error = max(low - value, min(0., high - value))
            yield abs(error), error / slope, w

    inserted = {}
    for iteration in range(5):
        for _ in range(9 if iteration == 0 else 7):
            maximal = 0.
            for triangles in source.values():
                for tri in triangles:
                    spacing = .0018 if iteration >= 3 else .0035
                    worst = sorted(sample(tri, spacing), reverse=True)[:4]
                    for violation, error, w in worst:
                        maximal = max(maximal, violation)
                        if violation < .00008:
                            break
                        free = [(v, weight) for v, weight in zip(tri, w)
                                if weight > .025 and (shift[v] < limits[v][1] if error > 0
                                                       else shift[v] > limits[v][0])]
                        divisor = sum(weight * weight for _, weight in free)
                        for v, weight in free:
                            bottom, top = limits[v]
                            correction = .22 * error * weight / divisor
                            shift[v] = min(top, max(bottom, shift[v] + correction))
            if maximal < .00008:
                break
        if iteration == 4 or budget < 2:
            break

        candidates = {}
        centers = {}
        incidents = defaultdict(set)
        for index, triangles in source.items():
            for tri in triangles:
                for a, b in _edges(tri):
                    incidents[_key(a, b)].add(index)
                violation, _, w = max(sample(tri, .003))
                if violation < .00040:
                    continue
                if min(w) >= .13:
                    centers[tri] = violation, index, w
                    continue
                # Prioritize the longest edge near the worst point. Preserve the
                # original topology elsewhere, including the exterior and slot walls.
                edge = max(_edges(range(3)),
                           key=lambda ij: (w[ij[0]] + w[ij[1]]) *
                           (points[tri[ij[0]]] - points[tri[ij[1]]]).length)
                a, b = (tri[e] for e in edge)
                if (points[a] - points[b]).length > .004:
                    k = _key(a, b)
                    candidates[k] = max(candidates.get(k, 0.), violation)
        if not candidates and not centers:
            break
        quota = max(1, budget // (2 * (4 - iteration)))

        def new_vertex(vertices, factors):
            m = len(points)
            p = sum((current(v) * f for v, f in zip(vertices, factors)), Vector())
            points.append(p)
            geo.vertices.append(tuple(p))
            geo.weights.append(_mix_weights([geo.weights[v] for v in vertices], factors))
            append(m)
            return m

        # Split neighboring triangles along a shared edge, or add an interior
        # vertex near a local peak without touching the neighboring triangles.
        ordered = sorted([*candidates.items(), *((tri, data[0]) for tri, data in centers.items())],
                         key=lambda item: -item[1])
        for edge, _ in ordered[:quota]:
            if len(edge) == 3:
                _, index, w = centers[edge]
                if edge in source[index]:
                    m = new_vertex(edge, w)
                    source[index].remove(edge)
                    source[index].extend((a, b, m) for a, b in _edges(edge))
                    budget -= 2
                continue
            a, b = edge
            m = new_vertex(edge, (.5, .5))
            inserted[edge] = m
            for index in sorted(incidents[_key(a, b)]):
                replacement = []
                for tri in source[index]:
                    for u, v in _edges(tri):
                        if _key(u, v) == _key(a, b):
                            other = next(k for k in tri if k not in (a, b))
                            replacement.extend(((u, m, other), (m, v, other)))
                            break
                    else:
                        replacement.append(tri)
                source[index] = replacement
            budget -= 2

    for v in shift:
        if shift[v]:
            geo.vertices[v] = tuple(current(v))

    replacements = dict(source)
    # Split the corresponding back edge of the closing wall when the support
    # point lies on the perimeter. Keep the wall's outer edge and face IDs.
    def split_wall(tri):
        for a, b in _edges(tri):
            if (mid := inserted.get(_key(a, b))) is not None:
                opposite = next(v for v in tri if v not in (a, b))
                return split_wall((a, mid, opposite)) + split_wall((mid, b, opposite))
        return [tri]

    for i, face in enumerate(geo.faces):
        if (i in source or geo.armor_components[i] != role
                or not any(_key(a, b) in inserted for a, b in _edges(face))):
            continue
        replacements[i] = [piece for tri in _triangulate(face, geo.side)
                           for piece in split_wall(tri)]
    for i, triangles in sorted(replacements.items()):
        geo.faces[i] = triangles[0]
        for tri in triangles[1:]:
            if i in source:
                inner.append(len(geo.faces))
            geo.faces.append(tri)
            geo.surfaces.append(geo.surfaces[i])
            geo.smooth.append(geo.smooth[i])
            geo.armor_components.append(role)

    _relieve_back_crossings(geo, role, axes,
                           {v: points[v] + axes[v] * max(limits[v][0], shift[v] - .0025)
                            for v in axes})


def refine(geo):
    """Fit the back sheets to the matching worn trousers and boot triangles."""
    for role, inner in geo.inner_faces.items():
        budget = {1: 148, 3: 44, 4: 60, 5: 24, 7: 24, 8: 36,
                  9: 30, 10: 30, 11: 44, 15: 26}.get(role, 0)
        if geo.lod:
            budget += {1: 42, 8: 36}.get(role, 0)
        if budget and inner:
            _refine_role(geo, role, inner, budget)
