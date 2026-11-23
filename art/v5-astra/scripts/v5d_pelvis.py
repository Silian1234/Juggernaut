"""V5d pelvic and flank plates fitted to the stock worn undersuit."""
from collections import defaultdict
from math import cos, radians, sin

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from finish import material
from leg_shells import between, lerp


class Garment:
    def __init__(self, obj):
        self.obj = obj
        mesh = obj.data
        mesh.calc_loop_triangles()
        self.vertices = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
        self.triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
        self.tree = BVHTree.FromPolygons(self.vertices, self.triangles, all_triangles=True)
        self.weights = [
            {obj.vertex_groups[group.group].name: group.weight for group in vertex.groups}
            for vertex in mesh.vertices
        ]

    def fitting_ray(self, origin, ray):
        point, normal, index, _ = self.tree.ray_cast(origin, ray)
        if point is None:
            raise ValueError(f"No {self.obj.name} hit from {tuple(origin)} toward {tuple(ray)}")
        return point, normal, index

    def weights_at(self, point, index):
        corners = self.triangles[index]
        axes = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        bary = barycentric_transform(point, *(self.vertices[i] for i in corners), *axes)
        result = defaultdict(float)
        for vertex, weight in zip(corners, bary):
            for name, value in self.weights[vertex].items():
                result[name] += max(0., weight) * value
        strongest = sorted(result.items(), key=lambda item: (-item[1], item[0]))[:4]
        total = sum(value for _, value in strongest)
        return [(name, value / total) for name, value in strongest if value > 0.]


def front_or_rear(side, outward):
    return lambda x, z: (
        Vector((side * x, .35 * outward, z)),
        Vector((0, -outward, 0)),
        Vector((0, outward, 0)),
    )


def flank(side):
    def coordinates(angle, z):
        theta = radians(angle)
        direction = Vector((side * sin(theta), -cos(theta), 0))
        return Vector((0., .026, z)), direction, direction

    return coordinates


def medial(side):
    return lambda y, z: (
        Vector((0, y, z)),
        Vector((side, 0, 0)),
        Vector((-side, 0, 0)),
    )


def plate(collection, rig, garment, lod, label, region, side, width, levels,
          coordinates, thickness, border, *, lift=.010, accent=False, angular=False):
    z0, z1 = levels[0][0], levels[-1][0]
    height = len(levels)
    grid = [(i / (width - 1), row[0]) for row in levels for i in range(width)]
    count = len(grid)
    perimeter = (
        list(range(width))
        + [j * width + width - 1 for j in range(1, height)]
        + list(range(count - 2, count - width - 1, -1))
        + [j * width for j in range(height - 2, 0, -1)]
    )
    vertices, weights = [], []
    basis = []

    def point_at(u, z):
        low, high = between(levels, z)
        return coordinates(lerp(low, high, u), z)

    def sample(u, z):
        origin, ray, outward = point_at(u, z)
        contact, normal, index = garment.fitting_ray(origin, ray)
        return contact, normal, outward, garment.weights_at(contact, index)

    def append(sample_data, depth, u):
        contact, normal, outward, skin = sample_data
        if region == "groin" and side == "C":
            edge = abs(2. * u - 1.)
            depth += (.006 if lod else .005) * edge
            depth += .004 * edge * max(0., 1. - abs(contact.z - 1.) / .046)
        if region == "buttocks" and lod and contact.z < .985:
            depth += .003 * u
        if region == "torso sides":
            # Stand the plate off the frozen cummerbund webbing across the center band.
            band = max(0., min(1., (contact.z - 1.149) / .027, (1.290 - contact.z) / .033))
            depth += .012 * band
        if region == "torso sides" and lod and side == "R":
            depth += .008 * max(0., 1. - abs(contact.z - 1.296) / .034) * u
        vertices.append(contact + outward * (depth / max(.55, normal.dot(outward))))
        weights.append(skin)

    ring = {}
    for i, (u, z) in enumerate(grid):
        if i in perimeter:
            ring[i] = sample(u, z)
            scale_u = .5 * (point_at(0., z)[0] - point_at(1., z)[0]).length
            if angular:
                scale_u = .12
            if i % width in (0, width - 1):
                u = lerp(u, .5, min(.16, border / max(.01, scale_u)))
            z = max(z0 + border, min(z1 - border, z))
        basis.append(sample(u, z))

    for (u, _), sample_data in zip(grid, basis):
        append(sample_data, lift + thickness, u)
    for (u, _), sample_data in zip(grid, basis):
        append(sample_data, lift, u)
    for i in perimeter:
        append(ring[i], lift + thickness - border, grid[i][0])

    faces, slots, inner = [], [], []
    for j in range(height - 1):
        for i in range(width - 1):
            a = j * width + i
            face = (a, a + 1, a + width + 1, a + width)
            faces.extend((face, tuple(p + count for p in reversed(face))))
            slots.extend((2 if accent else 0, 0))
            inner.extend((0, 1))
    ring_count = len(perimeter)
    for j, a in enumerate(perimeter):
        k = (j + 1) % ring_count
        b = perimeter[k]
        outer_a, outer_b = 2 * count + j, 2 * count + k
        faces.extend(((b, a, outer_a, outer_b),
                      (outer_b, outer_a, a + count, b + count)))
        slots.extend((1, 0))
        inner.extend((0, 0))

    a, b, c = (vertices[i] for i in faces[0][:3])
    if (b - a).cross(c - a).dot(basis[0][2]) < 0.:
        faces = [tuple(reversed(face)) for face in faces]

    name = f"V5D Armor | {label} {side} LOD{lod}"
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for key in ("plate", "edge", "frame"):
        mesh.materials.append(material(key))
    for face, slot, facing in zip(mesh.polygons, slots, inner):
        face.material_index = slot
        face.use_smooth = bool(facing or face.index < 2 * (height - 1) * (width - 1))
    mesh.attributes.new("v5d_inner", "INT", "FACE").data.foreach_set("value", inner)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["part"] = "additional_plates"
    obj["v5d_hard"] = True
    obj["region"] = region
    obj["v5d_region"] = label.lower().replace("-", " ").replace(" ", "_")
    obj["side"] = side
    obj["lod"] = lod

    groups = {}
    for i, skin in enumerate(weights):
        for name, value in skin:
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([i], value, "REPLACE")
    deform = obj.modifiers.new("EFT skinning", "ARMATURE")
    deform.object = rig
    # The codpiece bridges two thighs, so preserve its crown during the hinge motion.
    deform.use_deform_preserve_volume = (region == "groin" and side == "C")
    return obj


def build(lod, collection, rig):
    """Add the independent codpiece, medial lames, seat and flank panels."""
    shirt = Garment(collection.all_objects[f"Undersuit | Combat shirt LOD{lod}"])
    trousers = Garment(collection.all_objects[f"Undersuit | Combat trousers LOD{lod}"])
    groin = (
        (.831, -.025, .025), (.852, -.050, .050), (.885, -.078, .078),
        (.927, -.111, .111), (.974, -.104, .104), (1.017, -.090, .090),
        (1.039, -.059, .059), (1.048, -.043, .043),
    )
    seat = (
        (.846, .036, .124), (.864, .019, .156), (.900, .009, .183),
        (.941, .009, .183), (.980, .012, .169), (1.015, .018, .139),
        (1.046, .020, .118), (1.068, .021, .110),
    )
    hip_apron = (
        (.876, 56, 108), (.891, 41, 120), (.915, 39, 120),
        (.946, 43, 117), (.959, 50, 109),
    )
    hip_yoke = (
        (.961, 58, 110), (.974, 50, 123), (1.001, 45, 127),
        (1.024, 47, 136), (1.037, 47, 138), (1.048, 55, 129),
    )
    upper_thigh = (
        (.759, -.121, -.091), (.771, -.130, -.085),
        (.791, -.128, -.085), (.808, -.122, -.091),
        (.822, -.113, -.102),
    )
    sides = (
        (1.133, 75, 103), (1.148, 61, 122), (1.178, 55, 131),
        (1.220, 55, 130), (1.248, 63, 126), (1.269, 73, 122),
        (1.284, 83, 119), (1.292, 93, 110),
    )

    def coarser(rows):
        return rows if lod == 0 else (*rows[:-1:2], rows[-1])

    flank_rows = sides if lod == 0 else (*sides[:2], *sides[3:])
    new = [plate(collection, rig, trousers, lod, "Belt codpiece", "groin", "C",
                 5 if not lod else 4, coarser(groin), front_or_rear(1, -1),
                 .014, .003, lift=.010)]
    for sign, side in ((1, "L"), (-1, "R")):
        new.append(plate(collection, rig, trousers, lod, "Hinged medial lame", "groin",
                         side, 4 if not lod else 3, upper_thigh, medial(sign),
                         .006, .002, lift=(.009 if not lod else .007), accent=True))
        new.append(plate(collection, rig, trousers, lod, "Belt-hung seat shield", "buttocks",
                         side, 5 if not lod else 4, coarser(seat), front_or_rear(sign, 1),
                         .012, .003, lift=(.010 if not lod else .013)))
        for label, rows in (("Lower hip lame", hip_apron), ("Belt hip yoke", hip_yoke)):
            new.append(plate(collection, rig, trousers, lod, label, "hip coverage",
                             side, 7 if not lod else 5, coarser(rows), flank(sign),
                             .010, .003, lift=.010, angular=True))
        new.append(plate(collection, rig, shirt, lod, "Carrier flank shield", "torso sides",
                         side, 5 if not lod else 4, flank_rows, flank(sign),
                         .009, .003, lift=.011, angular=True))
    return new
