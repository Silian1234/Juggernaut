"""Fit the buried lower-lame flange behind the knee without altering the silhouette."""
from collections import defaultdict
from math import ceil

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import numpy as np

PITCH = .0007
CLEARANCE_MIN = .00522
CLEARANCE_MAX = .01175
ROLES = (3, 9)


def triangle_samples(points, triangles, spacing):
    for tri in triangles:
        a, b, c = (points[v] for v in tri)
        n = max(1, ceil(max((b-a).length, (c-b).length, (a-c).length) / spacing))
        u, v = (b-a) / n, (c-a) / n
        for i in range(n+1):
            for j in range(n-i+1):
                yield a + u*i + v*j

def projection_terms(points, tri, p):
    a, b, c = (points[v] for v in tri)
    dx, dz = p.x - a.x, p.z - a.z
    ux, uz = b.x - a.x, b.z - a.z
    vx, vz = c.x - a.x, c.z - a.z
    determinant = ux * vz - uz * vx
    if abs(determinant) < 1e-10:
        return {}
    u, v = (dx * vz - dz * vx) / determinant, (ux * dz - uz * dx) / determinant
    return dict(zip(tri, (1-u-v, u, v)))


def y_for_gap(tree, p, goal):
    # Clearance measurements use the same 3D nearest triangle as the verifier.
    near, n, _, gap = tree.find_nearest(p)
    signed = gap if (p - near).dot(n) >= 0 else -gap
    if abs(goal - signed) < 1e-7:
        return p.y
    low, high = p.y - .014, p.y + .014
    x, z = p.x, p.z
    for _ in range(12):
        y = (low + high) / 2
        q = Vector((x, y, z))
        near, n, _, gap = tree.find_nearest(q)
        if (q-near).dot(n) > 0 and gap > goal:
            low = y
        else:
            high = y
    return (low + high) / 2



def overlap_2d(points, a, b):
    """Convex intersection of two triangles projected onto X/Z."""
    ax = [Vector((points[v].x, points[v].z)) for v in a]
    bx = [Vector((points[v].x, points[v].z)) for v in b]
    if any(max(p[k] for p in ax) < min(p[k] for p in bx)
           or max(p[k] for p in bx) < min(p[k] for p in ax) for k in range(2)):
        return ()
    if (bx[1] - bx[0]).cross(bx[2] - bx[0]) < 0:
        bx.reverse()
    for u, v in zip(bx, bx[1:] + bx[:1]):
        result = []
        for p, q in zip(ax, ax[1:] + ax[:1]):
            d, e = (v-u).cross(p-u), (v-u).cross(q-u)
            if d >= 0:
                result.append(p)
            if (d < 0 < e) or (e < 0 < d):
                result.append(p.lerp(q, d/(d-e)))
        ax = result
        if len(ax) < 3:
            return ()
    area = sum(p.cross(q) for p,q in zip(ax,ax[1:]+ax[:1]))
    return tuple(Vector((p.x, 0, p.y)) for p in ax) if abs(area) > 1e-11 else ()

def _fit_surfaces(points, groups, cloth):
    original = [p.copy() for p in points]
    body, inner = dict(), dict()
    for role, (outer, backing) in groups.items():
        body[role], inner[role] = outer, backing
    role9 = {v for t in body[9] for v in t}
    role3 = {v for t in inner[3] for v in t}
    variable_bounds = {}
    for v in sorted(role9 | role3):
        p = points[v]
        if v in role9 and .590 < p.z < .623:
            factor = min(1., max(0, (.626-p.z) / .012))
            variable_bounds[v] = (-.006*factor, .0028*factor)
        if v in role3 and p.z > .582:
            factor = min(1., max(0, (p.z-.580) / .010))
            variable_bounds[v] = (-.0030*factor, .001*factor)

    constraints = []
    def add(terms, limit):
        if not terms:
            return
        offset = sum(original[v].y * f for v, f in terms.items())
        coeffs = [(v, f) for v, f in terms.items() if v in variable_bounds and abs(f) > .01]
        if coeffs:
            constraints.append((coeffs, limit - offset))

    for role in ROLES:
        for tri in inner[role]:
            if not (set(tri) & variable_bounds.keys()):
                continue
            for point in triangle_samples(original, (tri,), .0014):
                terms = projection_terms(original, tri, point)
                add(terms, y_for_gap(cloth, point, CLEARANCE_MIN))
                add({v: -f for v, f in terms.items()}, -y_for_gap(cloth, point, CLEARANCE_MAX))

    xmin = min(points[v].x for v in role9)
    xmax = max(points[v].x for v in role9)
    trees = {role: BVHTree.FromPolygons(points, body[role], all_triangles=True) for role in ROLES}

    def hit(role, x, z, front=True):
        y = -.28 if front else .04
        direction = Vector((0, 1 if front else -1, 0))
        pos, _, i, _ = trees[role].ray_cast(Vector((x, y, z)), direction, .45)
        return (pos, projection_terms(points, body[role][i], pos)) if pos else (None, {})

    def diff(positive, negative):
        coefficients = dict(positive)
        for v, f in negative.items():
            coefficients[v] = coefficients.get(v, 0.) - f
        return coefficients

    for x in np.arange(xmin, xmax, PITCH):
        for z in np.arange(.590, .613, PITCH):
            a, af = hit(9, x, z)
            if not a:
                continue
            backing, ab = hit(9, x, z, False)
            if not backing:
                continue
            # Keep 0.8mm of the hidden lamellar shell except at true bevel tips.
            thickness = backing.y - a.y
            if thickness > .00025:
                add(diff(af, ab), -min(.0008, thickness*.6))
            b, kb = hit(3, x, z, False)
            if b:
                add(diff(kb, af), -.00035)
                front, kf = hit(3, x, z)
                if front:
                    thickness = b.y - front.y
                    if thickness > .0003:
                        add(diff(kf, kb), -min(.0008, thickness*.55))

    # Preserve the original signed order of each overlapping facet when the
    # rim has multiple layers along the same projected line.
    for role in ROLES:
        facets = [t for t in body[role] if min(points[v].z for v in t) < .602
                  and max(points[v].z for v in t) > .590 and set(t).intersection(variable_bounds)]
        for i, a in enumerate(facets):
            for b in facets[i+1:]:
                if set(a).intersection(b):
                    continue
                polygon = overlap_2d(points, a, b)
                if not polygon:
                    continue
                centroid = sum(polygon, Vector()) / len(polygon)
                order = diff(projection_terms(original, a, centroid), projection_terms(original, b, centroid))
                if sum(original[v].y * w for v,w in order.items()) > 0:
                    a_terms, b_terms = b, a
                else:
                    a_terms, b_terms = a, b
                for point in polygon:
                    terms = diff(projection_terms(original, a_terms, point), projection_terms(original, b_terms, point))
                    signed_depth = sum(original[v].y * w for v,w in terms.items())
                    if signed_depth < -1e-7:
                        add(terms, -min(.00018, -.45 * signed_depth))
    values = {v: 0. for v in variable_bounds}
    rng = np.random.default_rng(2976)
    for _ in range(190):
        worst = 0.
        for j in rng.permutation(len(constraints)):
            terms, limit = constraints[j]
            residual = sum(values[v] * w for v,w in terms) - limit
            if residual <= .000001:
                continue
            worst = max(worst, residual)
            free = [(v, w) for v,w in terms
                    if (w > 0 and values[v] > variable_bounds[v][0])
                    or (w < 0 and values[v] < variable_bounds[v][1])]
            norm = sum(w*w for v,w in free)
            for v,w in free:
                lo, hi = variable_bounds[v]
                values[v] = max(lo, min(hi, values[v] - .4 * residual * w / norm))
        if worst < .00003:
            break
    for v, distance in values.items():
        points[v].y += distance



def mate(geo):
    """Adjust only the hem and knee backing after the final clearance fit."""
    if geo.lod == 0 and geo.side < 0:
        return
    points = [Vector(p) for p in geo.vertices]
    groups = {}
    for role in ROLES:
        tagged = set(geo.inner_faces[role])
        component = [i for i, r in enumerate(geo.armor_components) if r == role]
        by_vertex = defaultdict(list)
        for i in component:
            for v in geo.faces[i]:
                by_vertex[v].append(i)
        # The attached clips share a material role but are separate islands.
        structural = set(tagged)
        pending = list(tagged)
        while pending:
            for v in geo.faces[pending.pop()]:
                for i in by_vertex[v]:
                    if i not in structural:
                        structural.add(i)
                        pending.append(i)
        indices = sorted(structural)
        mesh = bpy.data.meshes.new("Knee and lower-lame fitting triangles")
        try:
            mesh.from_pydata(geo.vertices, [], [geo.faces[i] for i in indices])
            mesh.calc_loop_triangles()
            body = [tuple(t.vertices) for t in mesh.loop_triangles]
            inner = sorted(tuple(t.vertices) for t in mesh.loop_triangles
                           if indices[t.polygon_index] in tagged)
        finally:
            bpy.data.meshes.remove(mesh)
        groups[role] = body, inner
    _fit_surfaces(points, groups, geo.cuff_fit.index)
    for i, p in enumerate(points):
        if p.y != geo.vertices[i][1]:
            geo.vertices[i] = (geo.vertices[i][0], p.y, geo.vertices[i][2])
