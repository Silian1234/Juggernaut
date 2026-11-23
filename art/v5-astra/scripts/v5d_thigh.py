"""Fitted posterior and medial thigh shells and floating popliteal lames."""

import math

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from finish import material
from leg_shells import between
from legs import TrouserSkin
from v5c_thigh import AXIS


def _section(panel, u, v):
    corner = max(0, (abs(2 * u - 1) - .66) / .34)
    if panel == "thigh_back":
        low, high = .628 + .014 * corner, .845 - .007 * corner - .055 * u**4
        left, right = 145 + 5 * (1 - v)**3, 227 - 3 * (1 - v)**3
    elif panel == "thigh_inner":
        low, high = .558 + .013 * corner, .749 + .050 * abs(2 * u - 1)**2 - .006 * corner
        left, right = 231 + 3 * (1 - v)**3, 320 - 4 * (1 - v)**3
    elif panel == "knee_back_upper":
        low, high = .545 + .006 * corner, .617 - .012 * corner
        left, right = 156 + 5 * (1 - v), 212 - 5 * (1 - v)
    elif panel == "knee_back_outer":
        low, high = .448 + .020 * corner, .563 - .020 * corner
        left, right = 123 + 6 * (1 - v), 154 - 2 * v
    elif panel == "knee_back_inner":
        low, high = .449 + .015 * corner, .549 - .010 * corner
        left, right = 216 + 4 * v, 265 - 5 * (1 - v)
    else:
        low, high = .451 + .007 * corner, .548 - .012 * corner
        left, right = 158 + 7 * (1 - v), 209 - 6 * (1 - v)
    return math.radians(left + (right - left) * u), low + (high - low) * v


def _fitting_surface(trousers, rig, side):
    # The native trouser skin is already baked into a rest-pose authored mesh.
    # Narrow the ray queries to one leg to avoid hitting the opposite inseam.
    fit = TrouserSkin(trousers, rig)
    faces = [face for face in fit.faces
             if sum(fit.points[i].x * side for i in face) > 0]
    return fit, BVHTree.FromPolygons(fit.points, faces, all_triangles=True)


def _sample(tree, side, angle, z, gap):
    x, y = between(AXIS, z)
    center = Vector((side * x, y, z))
    direction = Vector((side * math.sin(angle), -math.cos(angle), 0))
    # Start inside one's own leg. An inward query started beyond the crotch
    # can mistake the surface of the other leg for this leg's medial seam.
    contact, _, _, _ = tree.ray_cast(center, direction, .15)
    if contact is None:
        contact, _, _, _ = tree.ray_cast(center + direction * .15, -direction, .175)
    for offset in (.012, .026, .043, .060, .078, .096):
        if contact is not None:
            break
        shifted = center + Vector((side * offset, 0, 0))
        contact, _, _, _ = tree.ray_cast(shifted, direction, .17)
    if contact is None:
        raise ValueError(f"No trouser surface for side {side}, angle {math.degrees(angle):.1f}, z={z:.4f}")
    low, high = 0, .028
    for _ in range(12):
        distance = (low + high) * .5
        _, _, _, clearance = tree.find_nearest(contact + direction * distance)
        if clearance < gap:
            low = distance
        else:
            high = distance
    return contact + direction * high, direction, contact


def _surface_grid(panel, lod, tree, side):
    shape = {
        "thigh_back": (8, 6) if lod == 0 else (6, 5),
        "thigh_inner": (8, 6) if lod == 0 else (6, 5),
        "knee_back_upper": (6, 3) if lod == 0 else (5, 3),
        "knee_back_lower": (6, 3) if lod == 0 else (5, 3),
        "knee_back_outer": (5, 4) if lod == 0 else (4, 3),
        "knee_back_inner": (5, 4) if lod == 0 else (4, 3),
    }
    columns, rows = shape[panel]
    cells = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            i = row * columns + column
            cells.extend(((i, i + 1, i + columns + 1), (i, i + columns + 1, i + columns)))

    points, directions, supports = [], [], []
    for row in range(rows):
        for column in range(columns):
            angle, z = _section(panel, column / (columns - 1), row / (rows - 1))
            # Arrange the joints like scales in neutral extension.
            gap = .0076
            if panel == "knee_back_inner":
                gap += .0015
            if panel == "knee_back_upper":
                gap += .005 * (1 - row / (rows - 1))**2
            if panel == "knee_back_lower":
                gap -= .0015 * (row / (rows - 1))**2
            point, axis, support = _sample(tree, side, angle, z, gap)
            points.append(point)
            directions.append(axis)
            supports.append(support)

    # Clear fold peaks between loft sections by correcting the triangulated
    # back surface, rather than only checking clearance at the sample vertices.
    net = ((.5, .5, 0), (0, .5, .5), (.5, 0, .5), (1/3, 1/3, 1/3),
           (.6, .2, .2), (.2, .6, .2), (.2, .2, .6))
    for _ in range(4):
        for face in cells:
            for factors in net:
                sample = sum((points[i] * w for i, w in zip(face, factors)), Vector())
                closest, normal, _, gap = tree.find_nearest(sample)
                if (sample - closest).dot(normal) < 0:
                    gap = -gap
                if gap >= .0062:
                    continue
                factor_sum = sum(w * w for w in factors)
                for i, w in zip(face, factors):
                    room = max(0, .018 - (points[i] - supports[i]).length)
                    shift = (.0062 - gap) * w / (factor_sum * max(.42, directions[i].dot(normal)))
                    points[i] += directions[i] * min(.7 * shift, room)

    ring = (list(range(columns))
            + [row * columns + columns - 1 for row in range(1, rows)]
            + list(range(rows * columns - 2, (rows - 1) * columns - 1, -1))
            + [row * columns for row in range(rows - 2, 0, -1)])
    return points, directions, supports, cells, ring, columns


def _weights(panel, fit, support, label):
    native = fit.weights(support)
    prefix = f"Base Human{label}"
    if panel.startswith("thigh"):
        return native
    if panel == "knee_back_upper":
        compliance = .90
        rigid = {prefix + "Thigh1": .60, prefix + "Thigh2": .40}
    elif panel == "knee_back_lower":
        compliance = .68
        rigid = {prefix + "Calf": 1.0}
    else:
        return native
    weights = {bone: weight * compliance for bone, weight in native.items()}
    for bone, weight in rigid.items():
        weights[bone] = weights.get(bone, 0) + (1 - compliance) * weight
    strongest = sorted(weights.items(), key=lambda item: -item[1])[:4]
    total = sum(weight for _, weight in strongest)
    return {bone: weight / total for bone, weight in strongest}


def _deep_flex_clearance(obj, panel, rig, label, lod):
    """Retract the rear plates from the compressed knee fold past 45 degrees."""
    offsets = {
        "thigh_back": {"L": (0, .027, .104), "R": (0, .014, .092)},
        "knee_back_upper": {"L": (.022, -.013, -.004), "R": (.008, -.017, .004)},
        "knee_back_lower": {"L": (.008, .004, -.045), "R": (0, .004, -.013)},
        "knee_back_outer": {"L": (.054, 0, 0), "R": (-.036, -.036, 0)},
        "knee_back_inner": {"L": (-.018, 0, -.045), "R": (.018, 0, -.036)},
    }
    offset = Vector(offsets[panel][label])
    if offset.length_squared == 0:
        return
    obj.shape_key_add(name="Bind")
    posed = obj.shape_key_add(name="Deep-flex clearance")
    hem = min(v.co.z for v in obj.data.vertices)
    fit_coarse_fold = lod == 1 and label == "L" and panel == "knee_back_upper"
    for rest, target in zip(obj.data.vertices, posed.data):
        weight = 1.0
        if panel == "thigh_back":
            # The upper seat stays under its suspension brackets as the
            # lower edge retracts into the available space behind the thigh.
            weight = max(0, (.790 - rest.co.z) / (.790 - hem))
        target.co = rest.co + offset * weight
        if fit_coarse_fold:
            # The coarser shell tips diagonally as it slides past the knee fold.
            medial_weight = min(1.0, max(0.0, (.158 - rest.co.x - offset.x) / .050))
            lateral = Vector((-.00529, -.00292, -.00749))
            medial = Vector((.00506, -.00044, .00209))
            target.co += lateral.lerp(medial, medial_weight)
    _flex_driver(posed, rig, label, "max(0, min(1, (0.93 - abs(q)) / 0.20))")
    if panel == "knee_back_lower":
        slide = obj.shape_key_add(name="Stride clearance")
        for rest, target in zip(obj.data.vertices, slide.data):
            target.co = rest.co - Vector((0, 0, .012))
        _flex_driver(slide, rig, label,
                     "max(0, min(1, (1 - abs(q)) / 0.009, (abs(q) - 0.86) / 0.06))")


def _flex_driver(shape, rig, label, expression):
    driver = shape.driver_add("value").driver
    flex = driver.variables.new()
    flex.name = "q"
    flex.type = "TRANSFORMS"
    flex.targets[0].id = rig
    flex.targets[0].bone_target = f"Base Human{label}Calf"
    flex.targets[0].transform_space = "LOCAL_SPACE"
    flex.targets[0].rotation_mode = "QUATERNION"
    flex.targets[0].transform_type = "ROT_W"
    driver.expression = expression

def _emit(panel, name, side, lod, collection, rig, fit, tree):
    points, directions, supports, cells, ring, columns = _surface_grid(panel, lod, tree, side)
    count = len(points)
    thickness = .006 if panel.startswith("knee") else .009
    width = [min(thickness, max(.0027, .0187 - (point - support).length))
             for point, support in zip(points, supports)]
    if panel == "knee_back_lower":
        width = [w * (1 - .60 * (i // columns) / (len(points) // columns - 1))
                 for i, w in enumerate(width)]
    front = [point + w * axis for point, axis, w in zip(points, directions, width)]
    outer_points = [p.copy() for p in front]
    bevel = []
    slots = {i: j for j, i in enumerate(ring)}
    for j, i in enumerate(ring):
        before = outer_points[ring[j - 1]]
        after = outer_points[ring[(j + 1) % len(ring)]]
        neighbors = (front[i - columns] if i >= count - columns else
                     front[i + columns] if i < columns else
                     front[i + (1 if i % columns == 0 else -1)])
        # Start the chamfer inside the rim, keeping the gentler front radius.
        tangent = (neighbors - front[i]).normalized()
        inside = tangent - (after - before).normalized().dot(tangent) * (after - before).normalized()
        bevel.append(front[i] - directions[i] * min(.0025, width[i] * .6))
        front[i] += inside.normalized() * .0023

    outer = list(cells)
    inner = [tuple(count + i for i in reversed(face)) for face in cells]
    walls = []
    for j, a in enumerate(ring):
        b = ring[(j + 1) % len(ring)]
        ab, bb = 2 * count + slots[a], 2 * count + slots[b]
        walls.extend(((a, ab, bb), (a, bb, b), (ab, count + a, count + b), (ab, count + b, bb)))
    faces = outer + inner + walls
    if side < 0:
        faces = [tuple(reversed(face)) for face in faces]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(front + points + bevel, [], faces)
    mesh.update()
    mesh.materials.append(material("black" if panel.startswith("knee") else "plate"))
    mesh.materials.append(material("edge"))
    for index, face in enumerate(mesh.polygons):
        face.use_smooth = index < len(outer)
        face.material_index = int(index >= 2 * len(cells))
    inside = mesh.attributes.new("v5d_inner", "INT", "FACE")
    inside.data.foreach_set("value", [0] * len(outer) + [1] * len(inner) + [0] * len(walls))
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["part"] = "additional_plates"
    obj["v5d_hard"] = True
    obj["v5d_region"] = "knee_back" if panel.startswith("knee") else panel
    obj["v5d_side"] = "L" if side > 0 else "R"
    for index, support in enumerate(supports):
        vertices = [index, index + count]
        if index in slots:
            vertices.append(2 * count + slots[index])
        for name, weight in _weights(panel, fit, support, obj["v5d_side"]).items():
            group = obj.vertex_groups.get(name)
            if group is None:
                group = obj.vertex_groups.new(name=name)
            group.add(vertices, weight, "REPLACE")
    obj.modifiers.new("EFT skin", "ARMATURE").object = rig
    if panel != "thigh_inner":
        _deep_flex_clearance(obj, panel, rig, obj["v5d_side"], lod)
    return obj


def build(lod, collection, rig):
    """Add four independently skinned shells to each trouser leg."""
    trousers = next(obj for obj in collection.all_objects
                    if obj.name.startswith(f"Undersuit | Combat trousers LOD{lod}"))
    panels = {"thigh_back": "Hamstring shell", "thigh_inner": "Adductor shell",
              "knee_back_upper": "Popliteal upper lame", "knee_back_lower": "Popliteal lower lame",
              "knee_back_outer": "Lateral knee skirt", "knee_back_inner": "Medial knee skirt"}
    objects = []
    for side, label in ((1, "L"), (-1, "R")):
        fit, tree = _fitting_surface(trousers, rig, side)
        for panel, title in panels.items():
            name = f"V5d | {title} {label} LOD{lod}"
            objects.append(_emit(panel, name, side, lod, collection, rig, fit, tree))
    return objects




















