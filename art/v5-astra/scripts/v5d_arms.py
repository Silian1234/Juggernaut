"""Fitted inner armor and articulating elbow lames on the EFT armature."""

from collections import defaultdict
from math import atan2, degrees, exp

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from arms import ArmBasis, ArmMeshes


class Garment:
    """Account for the actual shirt, sleeve cuffs and glove welts in the fit."""

    def __init__(self, objects):
        self.points = []
        self.triangles = []
        self.skin = []
        for obj in objects:
            offset = len(self.points)
            self.points.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
            self.skin.extend({obj.vertex_groups[g.group].name: g.weight for g in v.groups}
                             for v in obj.data.vertices)
            obj.data.calc_loop_triangles()
            self.triangles.extend(tuple(offset + i for i in tri.vertices)
                                  for tri in obj.data.loop_triangles)
        self.tree = BVHTree.FromPolygons(self.points, self.triangles, all_triangles=True)

    def fit(self, start, direction, depth):
        hit = self.tree.ray_cast(start + .161 * direction, -direction, .181)[0]
        if hit is None:
            raise ValueError(f"Missing arm garment at {start!r} along {direction!r}")
        low, high = depth, depth * 2.7
        for _ in range(12):
            distance = (low + high) * .5
            if self.tree.find_nearest(hit + distance * direction)[3] < depth:
                low = distance
            else:
                high = distance
        return hit, hit + high * direction

    def weights(self, hit, arm):
        point, _, index, _ = self.tree.find_nearest(hit)
        tri = self.triangles[index]
        coefficients = barycentric_transform(
            point, *(self.points[i] for i in tri),
            Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        weights = defaultdict(float)
        for index, factor in zip(tri, coefficients):
            for name, weight in self.skin[index].items():
                if name.startswith(arm.prefix):
                    weights[name[len(arm.prefix):]] += max(factor, 0) * weight
        strongest = sorted(weights, key=weights.get, reverse=True)[:4]
        total = sum(weights[name] for name in strongest)
        return {name: weights[name] / total for name in strongest if weights[name] > .0001}


def lerp(a, b, t):
    return a + (b - a) * t


def emit_shell(arm, name, region, rows, columns, surface, garment, skin, finish="armor",
               gap=.0085, thickness=.006):
    """Build nested curved surfaces with a clipped chamfer and a tagged backing."""
    weights, samples = [], []
    for row, v in enumerate(rows):
        for col, u in enumerate(columns):
            origin, direction = surface(u, v)
            hit, backing = garment.fit(origin, direction, gap)
            weights.append(skin(hit))
            rim = row in (0, len(rows) - 1) or col in (0, len(columns) - 1)
            crown = .001 * (1 - u * u)
            front = backing + direction * (thickness - (.0025 if rim else 0) + crown)
            samples.append((origin, direction, backing, front))
    # Fine diagonal cloth wrinkles occasionally rise between the vertices.
    # Nudge the backing along the local radial directions based on its actual triangles.
    stride = len(samples)
    count = len(columns)
    grid = [(i, i + 1, i + count + 1, i + count)
            for row in range(len(rows) - 1) for col in range(count - 1)
            for i in (row * count + col,)]
    shifts = [0.] * stride
    constraints = []
    for q in grid:
        for face in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
            for i in range(5):
                for j in range(5-i):
                    weights_at = ((4-i-j)/4, i/4, j/4)
                    point = sum((samples[k][2] * w for k, w in zip(face, weights_at)), Vector())
                    near, normal, _, distance = garment.tree.find_nearest(point)
                    signed = distance if (point - near).dot(normal) > 0 else -distance
                    constraints.append((face, weights_at, signed))
    for _ in range(10):
        for face, factors, distance in constraints:
            total = distance + sum(shifts[k] * w for k, w in zip(face, factors))
            target = min(.0115, max(.006, total))
            for k, w in zip(face, factors):
                shifts[k] = max(-.004, min(.011, shifts[k] + (target - total) * w * .60))
    points = [sample[layer] + sample[1] * shift
              for layer in (3, 2) for sample, shift in zip(samples, shifts)]
    faces, slots = [], []
    for q in grid:
        is_rim = any(i // count in (0, len(rows) - 1) or i % count in (0, count - 1)
                     for i in q)
        for indices, material in ((q, 1 if is_rim else 0),
                                   (tuple(q[i] + stride for i in (0, 3, 2, 1)), 2)):
            faces.extend(((indices[0], indices[1], indices[2]),
                          (indices[0], indices[2], indices[3])))
            slots.extend((material, material))
    rim = (list(range(count)) + [row * count - 1 for row in range(2, len(rows) + 1)]
           + list(range(stride - 2, stride - count - 1, -1))
           + [row * count for row in range(len(rows) - 2, 0, -1)])
    for i, j in zip(rim, rim[1:] + rim[:1]):
        faces.append((i, j, j + stride, i + stride))
        slots.append(1)
    obj = arm.mesh(name, "additional_plates", weights * 2, points, faces,
                   [finish, "edge" if finish == "armor" else "bolt", "rim"], slots)
    for poly in obj.data.polygons:
        poly.use_smooth = poly.material_index == 0
    backing = obj.data.attributes.new(name="v5d_inner", type="INT", domain="FACE")
    backing.data.foreach_set("value", [int(p.material_index == 2) for p in obj.data.polygons])
    obj["v5d_hard"] = True
    obj["v5d_region"] = obj["region"] = region
    obj["v5d_side"] = obj["side"] = arm.side
    return obj


def cylindrical_plate(arm, name, region, basis, garment, stations, skin, finish="armor",
                      gap=.0085, thickness=.006, narrow=False):
    """A tapered section with clipped corners and a broad debossed outline."""
    detailed = arm.detailed
    columns = (-1, -.87, -.46, 0, .46, .87, 1) if detailed and not narrow else (
               -1, -.72, 0, .72, 1)
    rows = [s[0] for s in stations]

    def surface(u, v):
        _, rear, front = stations[rows.index(v)]
        return basis.point(v, lerp(rear, front, (u + 1) * .5), 0)

    return emit_shell(arm, name, region, rows, columns, surface, garment, skin, finish,
                      gap, thickness)


def relieve_left_biceps(plate, basis):
    """Clear the medial sleeve and round the distal edge away from the elbow fold."""
    for vertex in plate.data.vertices:
        delta = vertex.co - basis.start
        station = delta.dot(basis.axis)
        radial = delta - basis.axis * station
        angle = degrees(atan2(radial.dot(basis.cross), radial.dot(basis.up)))
        medial_relief = exp(-((station - .210) / .054) ** 2 - ((angle - 115) / 44) ** 2)
        elbow_trim = exp(-((station - .248) / .038) ** 2 - ((angle - 55) / 48) ** 2)
        vertex.co += radial.normalized() * (.009 * medial_relief)
        vertex.co -= basis.axis * (.019 * elbow_trim)
    plate.data.update()


def build(lod, collection, rig):
    """Fit each side independently while preserving its original arm frames."""
    def garment(*labels):
        return Garment(o for o in collection.all_objects
                       if o.type == "MESH" and any(label in o.name for label in labels))

    sleeve = garment("Combat shirt", "Sleeve cuffs", "Tactical gloves", "Glove hems")
    glove = garment("Tactical gloves", "Glove hems")
    objects = []
    for side in ("L", "R"):
        arm = ArmMeshes(lod, collection, rig, side, sleeve.tree)
        elbow = arm.bone("Forearm1")
        upper = ArmBasis(arm.bone("Upperarm"), elbow, arm.sign)
        lower = ArmBasis(elbow, arm.bone("Palm"), arm.sign)
        across = (arm.bone("Digit51") - arm.bone("Digit21")) * arm.sign
        end = (arm.bone("Digit21") + arm.bone("Digit51")) * .5
        hand = ArmBasis(arm.bone("Palm"), end, arm.sign,
                        (end - arm.bone("Palm")).cross(across))

        def sleeve_skin(hit):
            return sleeve.weights(hit, arm)

        upper_stations = (
            (.092, 27, 52), (.103, 23, 76), (.141, 12, 122),
            (.176, 11, 146), (.207, 9, 148), (.235, 13, 132),
            (.245, 22, 103))
        fore_stations = (
            (.057, 55, 174), (.062, 48, 188), (.080, 40, 205),
            (.110, 41, 209), (.137, 41, 211), (.160, 42, 207),
            (.176, 46, 191), (.185, 55, 174))
        if lod:
            upper_stations = tuple(upper_stations[i] for i in (0, 1, 3, 5, 6))
            fore_stations = tuple(fore_stations[i] for i in (0, 1, 3, 5, 6, 7))
        biceps = cylindrical_plate(arm, "Biceps inner wrap", "upper_arm_inner", upper, sleeve,
                                   upper_stations, sleeve_skin, gap=.0090, thickness=.0055)
        if side == "L":
            relieve_left_biceps(biceps, upper)
        cylindrical_plate(arm, "Forearm inner wrap", "forearm_inner", lower, sleeve,
                          fore_stations, sleeve_skin, gap=.0092, thickness=.0055)
        cylindrical_plate(arm, "Elbow proximal lame", "elbow_inner", lower, sleeve,
                          ((-.003, 74, 116), (.001, 67, 122), (.008, 64, 129),
                           (.016, 64, 123), (.020, 72, 116)),
                          sleeve_skin, "steel", .013, .0038, narrow=True)
        cylindrical_plate(arm, "Elbow distal lame", "elbow_inner", lower, sleeve,
                          ((.017, 69, 113), (.021, 61, 123), (.034, 53, 137),
                           (.044, 56, 132), (.049, 64, 123)),
                          sleeve_skin, "steel", .0075, .0035, narrow=True)
        posterior = (
            (.077, 203, 228), (.087, 195, 236), (.140, 150, 244),
            (.181, 150, 238), (.227, 149, 242), (.270, 147, 240),
            (.282, 157, 232))
        lateral = (
            (.208, -79, -17), (.217, -86, -8), (.242, -101, 8),
            (.281, -92, -1), (.291, -82, -12))
        lower_edge = (
            (.012, -173, -133), (.023, -167, -121), (.089, -150, -105),
            (.170, -151, -104), (.211, -171, -87), (.218, -160, -99))
        wrist = (
            (.190, 35, 171), (.195, 21, 182), (.225, 51, 176),
            (.231, 68, 163))
        if side == "L":
            # This sleeve ends earlier than its mirror and meets a separate glove mesh.
            lower_edge = (*lower_edge[:4], (.192, -163, -95), (.198, -155, -109))
            wrist = ((.186, 33, 160), (.191, 24, 171), (.209, 47, 173), (.219, 66, 155))
        if lod:
            posterior = tuple(posterior[i] for i in (0, 1, 3, 5, 6))
            lower_edge = tuple(lower_edge[i] for i in (0, 1, 3, 4, 5))
        cylindrical_plate(arm, "Biceps posterior shield", "upper_arm_outer_posterior",
                          upper, sleeve, posterior, sleeve_skin, "steel", .008, .004, narrow=True)
        cylindrical_plate(arm, "Biceps elbow bridge", "upper_arm_outer_distal",
                          upper, sleeve, lateral, sleeve_skin, "armor", .008, .004, narrow=True)
        cylindrical_plate(arm, "Forearm rear spine", "forearm_outer_rear",
                          lower, sleeve, lower_edge, sleeve_skin, "steel", .008, .004, narrow=True)
        cylindrical_plate(arm, "Forearm wrist extension", "forearm_inner_wrist",
                          lower, sleeve, wrist, sleeve_skin, "steel", .008, .004, narrow=True)
        def glove_surface(u, v):
            stations = ((.024, .024), (.029, .035), (.049, .039),
                        (.065, .040), (.084, .042), (.101, .036), (.108, .024))
            width = next(w for d, w in stations if d == v)
            return hand.start + hand.axis * v + hand.cross * u * width, hand.up

        # Keep the native knuckle tiles and refit the separate dorsal shell.
        old = next((o for o in collection.all_objects if
                    o.name.startswith(f"{side} Dorsal glove guard")), None)
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)
        emit_shell(arm, "Dorsal gauntlet plate", "hand_back",
                   (.024, .029, .049, .084, .101, .108) if not lod else
                   (.024, .029, .065, .101, .108),
                   (-1, -.89, -.53, 0, .53, .89, 1) if not lod else (-1, -.77, 0, .77, 1),
                   glove_surface, glove, lambda hit: glove.weights(hit, arm))
        objects.extend(arm.objects)
    return objects











