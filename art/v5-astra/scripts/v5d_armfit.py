"""Contour the existing hard-arm shells to the actual combat-shirt sleeves."""

from math import atan2, ceil, cos, radians, sin

from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from arms import ArmBasis
from poses import BONE


SHELLS = {
    "Pauldron lower lame": ("Upperarm", "Forearm1", .0085),
    "Outer biceps shell": ("Upperarm", "Forearm1", .0085),
    "Elbow impact cap": ("Forearm1", "Palm", .0085),
    "Wraparound forearm bracer": ("Forearm1", "Palm", .0085),
    "Elbow cap liner": ("Forearm1", "Palm", .0058),
}


def sleeve_tree(shirt, side):
    groups = {g.index for g in shirt.vertex_groups
              if g.name.startswith(BONE + side) and "arm" in g.name.lower()}
    support = [sum(g.weight for g in v.groups if g.group in groups)
               for v in shirt.data.vertices]
    shirt.data.calc_loop_triangles()
    triangles = [tuple(t.vertices) for t in shirt.data.loop_triangles
                 if sum(support[i] for i in t.vertices) >= 1.5]
    return BVHTree.FromPolygons([shirt.matrix_world @ v.co for v in shirt.data.vertices],
                                triangles, all_triangles=True)


def ray(point, start, axis):
    delta = point - start
    origin = start + axis * axis.dot(delta)
    return origin, (point - origin).normalized()


def signed_gap(surface, point):
    nearest, normal, _, distance = surface.find_nearest(point)
    return distance if (point - nearest).dot(normal) >= 0 else -distance


def radial_fit(surface, origin, direction, gap):
    hit = surface.ray_cast(origin + direction * .145, -direction, .155)[0]
    if hit is None:
        hit, normal, _, _ = surface.find_nearest(origin + direction * .055)
        return hit + normal * gap
    lower, upper = gap, 3 * gap
    for _ in range(10):
        middle = (lower + upper) * .5
        if signed_gap(surface, hit + direction * middle) < gap:
            lower = middle
        else:
            upper = middle
    return hit + direction * upper


def refine_backing(points, directions, triangles, garment, target):
    """Bound the gap over the tessellated backing, including wrinkles between vertices."""
    nets = []
    for tri in triangles:
        a, b, c = [points[i] for i in tri]
        n = ceil(max((a - b).length, (a - c).length, (b - c).length) / .0035)
        for j in range(n + 1):
            for k in range(n + 1 - j):
                w = ((n - j - k) / n, j / n, k / n)
                nets.append((tri, w, sum(f * f for f in w)))
    allowance = .0018 if target > .007 else .0015
    initial = {i: points[i].copy() for tri in triangles for i in tri}
    for iteration in range(32):
        for (ia, ib, ic), weights, norm in (nets if iteration % 2 == 0 else reversed(nets)):
            a, b, c = weights
            sample = points[ia] * a + points[ib] * b + points[ic] * c
            nearest, normal, _, distance = garment.find_nearest(sample)
            delta = sample - nearest
            sign = 1 if delta.dot(normal) >= 0 else -1
            gap = sign * distance
            correction = min(target + allowance, max(target - allowance, gap)) - gap
            if abs(correction) > .00003:
                gradient = sign * delta.normalized() if distance > .00001 else normal
                ids = (ia, ib, ic)
                influence = [w * gradient.dot(directions[i]) for i, w in zip(ids, weights)]
                energy = max(.16 * norm, sum(weight * weight for weight in influence))
                for i, weight in zip(ids, influence):
                    offset = (points[i] - initial[i]).dot(directions[i])
                    move = max(-.010, min(.010, offset + correction * weight * .56 / energy))
                    points[i] = initial[i] + directions[i] * move


def backing_faces(mesh, directions):
    """Use inherited panel tags or the continuous inward-facing grid of a molded shell."""
    if tag := mesh.attributes.get("v5c_inner"):
        return [p for p in mesh.polygons if tag.data[p.index].value]
    faces = []
    for polygon in mesh.polygons:
        outward = sum((directions[i] for i in polygon.vertices), Vector()).normalized()
        # The rim connects the two grids at the same radial station.
        if polygon.material_index == 1 and polygon.normal.dot(outward) < -.35:
            faces.append(polygon)
    return faces


def bracer_station(station):
    original = (.052, .070, .151, .190, .206)
    fitted = (.058, .084, .110, .136, .162)
    segment = next((i for i in range(3) if station < original[i + 1]), 3)
    fraction = (station - original[segment]) / (original[segment + 1] - original[segment])
    return fitted[segment] + fraction * (fitted[segment + 1] - fitted[segment])


def fit_shell(obj, garment, basis, label, gap, lod):
    start, axis = basis.start, basis.axis
    mesh = obj.data
    before = [obj.matrix_world @ v.co for v in mesh.vertices]
    local = [ray(p, start, axis) for p in before]
    fit_local = local[:]
    if label == "Wraparound forearm bracer":
        fit_local = []
        for origin, direction in local:
            station = (origin - start).dot(axis)
            angle = atan2(direction.dot(basis.cross), direction.dot(basis.up))
            mapped = angle * (.72 if obj.name.startswith("L ") else .82) + .045
            fit_local.append((start + axis * bracer_station(station),
                              basis.up * cos(mapped) + basis.cross * sin(mapped)))
    elif label in ("Elbow impact cap", "Elbow cap liner"):
        lift = (.008 if lod == 0 else (.0115 if obj.name.startswith("L ") else .0125))
        if label == "Elbow impact cap":
            fit_local = [ray(p - basis.up * lift, start, axis) for p in before]
            for i, (origin, radial) in enumerate(fit_local):
                angle = atan2(radial.dot(basis.cross), radial.dot(basis.up))
                angle *= .84
                fit_local[i] = origin, basis.up * cos(angle) + basis.cross * sin(angle)
        fit_local = [(origin + axis * .009, radial) for origin, radial in fit_local]
    directions = [direction for _, direction in fit_local]
    stride = len(before) // 2
    paired_shell = label != "Pauldron lower lame" and len(before) in (40, 50, 72, 90)
    if paired_shell:
        inner_faces = [p for p in mesh.polygons if all(i >= stride for i in p.vertices)]
    else:
        inner_faces = backing_faces(mesh, [direction for _, direction in local])
    inner_ids = {i for p in inner_faces for i in p.vertices}
    faces = {p.index for p in inner_faces}
    if not faces:
        raise ValueError(f"Missing inward-facing triangles on {obj.name}")
    if not mesh.attributes.get("v5c_inner") and label != "Elbow cap liner":
        tag = mesh.attributes.new(name="v5c_inner", type="INT", domain="FACE")
        tag.data.foreach_set("value", [int(p.index in faces) for p in mesh.polygons])
    front_faces = [p.index for p in mesh.polygons if p.material_index == 0]
    mesh.calc_loop_triangles()
    inner_triangles = [tuple(t.vertices) for t in mesh.loop_triangles if t.polygon_index in faces]
    front_triangles = [tuple(t.vertices) for t in mesh.loop_triangles if t.polygon_index in front_faces]

    points = before[:]
    for i in inner_ids:
        points[i] = radial_fit(garment, *fit_local[i], gap)
    refine_backing(points, directions, inner_triangles, garment, gap)
    new_back = BVHTree.FromPolygons(points, inner_triangles, all_triangles=True)
    old_back = BVHTree.FromPolygons(before, inner_triangles, all_triangles=True)
    for i, (origin, direction) in enumerate(fit_local):
        if i in inner_ids:
            continue
        paired = i + stride
        if paired_shell:
            stock = {"Elbow cap liner": .004, "Wraparound forearm bracer": .0062}.get(label, .007)
            points[i] = points[paired] + direction * stock
            continue
        new_hit = new_back.ray_cast(origin, direction, .160)[0]
        old_origin, old_direction = local[i]
        old_hit = old_back.ray_cast(old_origin, old_direction, .160)[0]
        if new_hit is None or old_hit is None:
            # Rim coordinates may lie exactly on the open BVH boundary.
            backup = min(inner_ids, key=lambda k: (before[k] - before[i]).length_squared)
            if new_hit is None:
                new_hit = origin + direction * (points[backup] - origin).dot(direction)
            if old_hit is None:
                old_hit = old_origin + old_direction * (before[backup] - old_origin).dot(old_direction)
        thickness = (before[i] - old_hit).dot(old_direction)
        if label == "Pauldron lower lame":
            thickness *= .43
        if label == "Elbow cap liner":
            thickness *= .38
        maximum = .0062 if label == "Wraparound forearm bracer" else .008
        points[i] = new_hit + direction * max(.002, min(maximum, thickness))
    inverse = obj.matrix_world.inverted()
    for v, point in zip(mesh.vertices, points):
        v.co = inverse @ point
    mesh.update()
    return (BVHTree.FromPolygons(before, front_triangles, all_triangles=True),
            BVHTree.FromPolygons(points, front_triangles, all_triangles=True))


def elbow_relief(obj, rig, side, basis):
    """Let the impact cap and its liner follow the forearm during flexion."""
    obj.shape_key_add(name="Basis", from_mix=False)
    relief = obj.shape_key_add(name="Elbow fold relief", from_mix=False)
    inverse = obj.matrix_world.inverted().to_3x3()
    for vertex in relief.data:
        _, outward = ray(obj.matrix_world @ vertex.co, basis.start, basis.axis)
        vertex.co += inverse @ (basis.axis * .014 + outward * .016)
    driver = relief.driver_add("value").driver
    driver.type = "SCRIPTED"
    variable = driver.variables.new()
    variable.name = "bend"
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = rig
    target.bone_target = BONE + side + "Forearm1"
    target.transform_type = "ROT_Z"
    target.transform_space = "LOCAL_SPACE"
    target.rotation_mode = "XYZ"
    driver.expression = "min(1, max(0, (bend - 0.02) / 0.25))"


def extend_medial_lame(collection, rig):
    """Continue the proximal left elbow edge into the last exposed fold rail."""
    obj = next(obj for obj in collection.all_objects
               if obj.name.startswith("L Elbow proximal lame"))
    elbow = rig.matrix_world @ rig.data.bones[BONE + "LForearm1"].head_local
    wrist = rig.matrix_world @ rig.data.bones[BONE + "LPalm"].head_local
    axis = (wrist - elbow).normalized()
    retreat = obj.matrix_world.inverted().to_3x3() @ (-axis * .004)
    for vertex in obj.data.vertices:
        station = (obj.matrix_world @ vertex.co - elbow).dot(axis)
        vertex.co += retreat * max(0, min(1, (.017 - station) / .014))
    obj.data.update()


def fit(lod, collection, rig):
    """Fit both arm shells and carry the lower-lame screws onto the fitted crown."""
    shirt = next(o for o in collection.all_objects if "Combat shirt" in o.name)
    extend_medial_lame(collection, rig)
    for side in ("L", "R"):
        objects = {obj.name.split(".")[0][2:]: obj for obj in collection.all_objects
                   if obj.name.startswith(side + " ") and obj.get("part") == "arm_plates"}
        garment = sleeve_tree(shirt, side)
        for label, (start_bone, end_bone, gap) in SHELLS.items():
            start, end = [rig.matrix_world @ rig.data.bones[BONE + side + bone].head_local
                          for bone in (start_bone, end_bone)]
            basis = ArmBasis(start, end, 1 if side == "L" else -1)
            axis = basis.axis
            old, new = fit_shell(objects[label], garment, basis, label, gap, lod)
            if label in ("Elbow impact cap", "Elbow cap liner"):
                elbow_relief(objects[label], rig, side, basis)
            if label != "Pauldron lower lame":
                continue
            for screw in collection.all_objects:
                if not screw.name.startswith(f"{side} {label} screw"):
                    continue
                center = sum((screw.matrix_world @ v.co for v in screw.data.vertices), Vector())
                center /= len(screw.data.vertices)
                origin, direction = ray(center, start, axis)
                old_hit = old.ray_cast(origin, direction, .160)[0]
                new_hit = new.ray_cast(origin, direction, .160)[0]
                if old_hit is None or new_hit is None:
                    continue
                offset = screw.matrix_world.inverted().to_3x3() @ (new_hit - old_hit)
                for vertex in screw.data.vertices:
                    vertex.co += offset
                screw.data.update()


def _fastener_exterior(obj):
    mesh = obj.data
    points = [obj.matrix_world @ v.co for v in mesh.vertices]
    mesh.calc_loop_triangles()
    triangles = [tuple(tri.vertices) for tri in mesh.loop_triangles
                 if mesh.polygons[tri.polygon_index].material_index == 0]
    return points, triangles, BVHTree.FromPolygons(points, triangles, all_triangles=True)


def _follow_shell_shape(obj, shell, face, barycentric):
    keys = shell.data.shape_keys
    if not keys:
        return
    obj.shape_key_add(name="Basis", from_mix=False)
    matrix = obj.matrix_world.inverted().to_3x3() @ shell.matrix_world.to_3x3()
    for source in keys.key_blocks[1:]:
        corrective = obj.shape_key_add(name=source.name, from_mix=False)
        move = sum(((source.data[i].co - source.relative_key.data[i].co) * w
                    for i, w in zip(face, barycentric)), Vector())
        for vertex in corrective.data:
            vertex.co += matrix @ move
        original = next(fc.driver for fc in keys.animation_data.drivers
                        if fc.data_path == source.path_from_id("value"))
        driver = corrective.driver_add("value").driver
        driver.type = original.type
        for source_var in original.variables:
            var = driver.variables.new()
            var.name, var.type = source_var.name, source_var.type
            for target, src in zip(var.targets, source_var.targets):
                target.id = src.id
                target.bone_target = src.bone_target
                target.transform_type = src.transform_type
                target.transform_space = src.transform_space
                target.rotation_mode = src.rotation_mode
        driver.expression = original.expression


def seat_fasteners(lod, collection, rig):
    """Seat inherited armor rivets and screws on the final posed shell geometry."""
    for side in ("L", "R"):
        sign = 1 if side == "L" else -1
        def joint(name):
            return rig.matrix_world @ rig.data.bones[BONE + side + name].head_local

        targets = [
            ("Deltoid shell", "Deltoid shell screw", ArmBasis(joint("Upperarm"), joint("Forearm1"), sign)),
            ("Wraparound forearm bracer", "Flush armor rivet", ArmBasis(joint("Forearm1"), joint("Palm"), sign)),
        ]
        for label, prefix, basis in targets:
            shell = next(obj for obj in collection.all_objects if obj.name.split(".")[0] == f"{side} {label}")
            points, triangles, surface = _fastener_exterior(shell)
            for obj in collection.all_objects:
                if obj.get("part") != "arm_plates" or not obj.name.startswith(f"{side} {prefix}"):
                    continue
                vertices = [obj.matrix_world @ v.co for v in obj.data.vertices]
                center = sum(vertices, Vector()) / len(vertices)
                origin, radial = ray(center, basis.start, basis.axis)
                toward = radial.copy()
                if label == "Wraparound forearm bracer":
                    angle = atan2(radial.dot(basis.cross), radial.dot(basis.up))
                    mapped = angle * (.72 if side == "L" else .82) + .045
                    if obj.name.split(".")[0].endswith("05"):
                        mapped += radians(6)
                    station = (origin - basis.start).dot(basis.axis)
                    origin = basis.start + basis.axis * bracer_station(station)
                    toward = basis.up * cos(mapped) + basis.cross * sin(mapped)
                hit, normal, index, _ = surface.ray_cast(origin, toward, .180)
                if hit is None:
                    hit, normal, index, _ = surface.find_nearest(center)
                if normal.dot(toward) < 0:
                    normal.negate()
                rotation = radial.rotation_difference(normal)
                inverse = obj.matrix_world.inverted()
                seat = hit + normal * .0003
                faces = triangles[index]
                barycentric = barycentric_transform(hit, *(points[i] for i in faces),
                                                    Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
                for vertex, before in zip(obj.data.vertices, vertices):
                    vertex.co = inverse @ (seat + rotation @ (before - center))
                obj.data.update()
                _follow_shell_shape(obj, shell, faces, barycentric)

