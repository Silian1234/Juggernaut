"""Fit tagged hard-shell backings to the final simplified garments."""

from math import ceil

import bpy
from mathutils.geometry import barycentric_transform

from qa_v5c import bvh, triangle_samples
from v5d_calf_motion import SEGMENTS
from v5d_qa import GARMENTS, Mesh, reference_for, roles


LEG_COMPONENTS = {1, 3, 4, 7, 8, 9, 10, 11, 14, 15}
STANDALONE = {
    "anterior_hip_tasset", "hinged_medial_lame",
    "upper_arm_inner", "upper_arm_outer_posterior", "forearm_inner", "hand_back",
}
STEP = .0032
LIMITS = (.0058, .0112)
MAX_TRAVEL = .006


def _sample_net(points, triangles):
    for tri in triangles:
        a, b, c = (points[index] for index in tri)
        count = max(1, ceil(max((a - b).length, (a - c).length, (b - c).length) / STEP))
        for i in range(count + 1):
            for j in range(count + 1 - i):
                yield tri, ((count - i - j) / count, i / count, j / count)


def _gap(tree, point):
    nearest, normal, _, distance = tree.find_nearest(point)
    return (distance if (point - nearest).dot(normal) >= 0 else -distance), normal


def _error(tree, points, triangles):
    return sum(max(.005 - gap, gap - .012, 0) ** 2
               for point in triangle_samples(points, triangles, STEP)
               for gap, _ in (_gap(tree, point),))


def _crossings(points, triangles):
    tree = bvh(points, triangles)
    return {(a, b) for a, b in tree.overlap(tree)
            if a < b and set(triangles[a]).isdisjoint(triangles[b])}


def _usable_geometry(before, after, triangles):
    for a, b, c in triangles:
        original = (before[b] - before[a]).cross(before[c] - before[a])
        adjusted = (after[b] - after[a]).cross(after[c] - after[a])
        if original.dot(adjusted) < .18 * original.length_squared:
            return False
    return not (_crossings(after, triangles) - _crossings(before, triangles))


def _clamp(value):
    return min(1.0, max(0.0, value))


def _travel_limits(plate, before, indices):
    component = plate.component
    mesh = plate.mesh
    lugs = mesh.tagged("armor_component", {1: 12, 4: 13}.get(component, -1))
    lug_tree = bvh(before, lugs) if lugs else None
    limits = {}
    hem = None
    if component in {3, 9}:
        hem = (max if component == 3 else min)(before[i].z for i in indices)
    for i in indices:
        point = before[i]
        factor = 1.0
        if lug_tree:
            _, _, _, distance = lug_tree.find_nearest(point)
            factor *= _clamp((distance - .009) / .018)
        if component == 8:
            _, upper = SEGMENTS[0]
            factor *= _clamp((upper - point.z - .017) / .018)
        if hem is not None:
            # Preserve the mating edge shared by the thigh hem and knee crown.
            factor *= _clamp((abs(hem - point.z) - .009) / .018)
        limits[i] = factor * MAX_TRAVEL
    return limits


def _adjustment(plate, target):
    before, body = plate.geometry
    inner = plate.inner
    inside = {i for tri in inner for i in tri}
    garment = bvh(*target)
    original_error = _error(garment, before, inner)
    if original_error < 1e-10:
        return {}

    directions = {i: _gap(garment, before[i])[1] for i in inside}
    travel = _travel_limits(plate, before, inside)
    shift = dict.fromkeys(inside, 0.0)
    points = before[:]
    samples = list(_sample_net(before, inner))
    lower, upper = LIMITS
    for pass_index in range(20):
        for tri, weights in (reversed(samples) if pass_index % 2 else samples):
            a, b, c = tri
            u, v, w = weights
            gap, normal = _gap(garment, points[a] * u + points[b] * v + points[c] * w)
            correction = min(upper, max(lower, gap)) - gap
            if abs(correction) < .00004:
                continue
            slope = [weight * max(0, directions[i].dot(normal)) for i, weight in zip(tri, weights)]
            step = correction * .5 / max(.15, sum(component ** 2 for component in slope))
            for i, component in zip(tri, slope):
                shift[i] = max(-travel[i], min(travel[i], shift[i] + component * step))
                points[i] = before[i] + directions[i] * shift[i]

    backing = bvh(before, inner)
    offsets = {i: points[i] - before[i] for i in inside}
    for i in sorted({i for tri in body for i in tri} - inside):
        nearest, _, face, _ = backing.find_nearest(before[i])
        a, b, c = inner[face]
        offsets[i] = barycentric_transform(
            nearest, before[a], before[b], before[c], offsets[a], offsets[b], offsets[c])

    # The original offset field can run across a sharp fold or a narrow rolled lip.
    # Keep the strongest scale that preserves winding and introduces no crossings.
    for scale in (1, .75, .5, .25):
        result = before[:]
        for i, displacement in offsets.items():
            result[i] = before[i] + displacement * scale
        if _usable_geometry(before, result, body) and _error(garment, result, inner) < original_error * .95:
            return {i: displacement * scale for i, displacement in offsets.items()}
    return {}


def fit(lod, collection, rig):
    """Conform the worn assembly without adding faces or changing the deformation weights."""
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    garment_objects = {label: next(obj for obj in collection.all_objects if stem in obj.name)
                       for label, stem in GARMENTS.items()}
    garments = {label: Mesh(obj, graph) for label, obj in garment_objects.items()}
    changed = []
    for obj in collection.all_objects:
        if obj.type != "MESH":
            continue
        if obj.get("part") != "leg_plates" and not obj.data.attributes.get("v5d_inner"):
            continue
        mesh = Mesh(obj, graph)
        offsets = {}
        for plate in roles(mesh):
            if plate.component not in LEG_COMPONENTS and plate.role not in STANDALONE:
                continue
            # Coarse greaves and cuffs distort at the ankle in deep crouch.
            if lod == 1 and plate.component == 4:
                continue
            # Preserve the interlocking tiers of the two retracting calf segments.
            if plate.component == 8 and obj["calf_segment"] != 0:
                continue
            if lod == 1 and plate.side == "L" and plate.role == "anterior_hip_tasset":
                continue
            if lod == 1 and plate.side == "R" and plate.role in {"upper_arm_inner", "hinged_medial_lame"}:
                continue
            if not plate.inner:
                continue
            reference, _ = reference_for(plate, garments, rig)
            offsets.update(_adjustment(plate, reference))
        if not offsets:
            continue
        inverse = obj.matrix_world.inverted().to_3x3()
        keys = obj.data.shape_keys
        layers = [key.data for key in keys.key_blocks] if keys else [obj.data.vertices]
        for layer in layers:
            for index, offset in offsets.items():
                layer[index].co += inverse @ offset
        obj.data.update()
        changed.append(obj)
    return changed
