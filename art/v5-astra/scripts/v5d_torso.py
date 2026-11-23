"""Close the gaps above and below the carrier with fitted torso inserts."""

from math import cos, radians, sin

import bpy
from mathutils import Vector

from v5d_pelvis import Garment, front_or_rear, plate


def waist_ray(angle, z):
    theta = radians(angle)
    direction = Vector((sin(theta), -cos(theta), 0.0))
    return Vector((0.0, -.018, z)), direction, direction


def collar_ray(angle, z):
    theta = radians(angle)
    direction = Vector((sin(theta), -cos(theta), 0.0))
    return Vector((0.0, .071 + .32 * (z - 1.60), z)), direction, direction


def shoulder_ray(sign):
    def coordinates(y, x):
        return Vector((sign * x, y, 1.8)), Vector((0, 0, -1)), Vector((0, 0, 1))

    return coordinates


def match_shell_diagonals(obj, width, height, *, chamfer=True):
    """Triangulate paired skins consistently across the same surface grid."""
    source = obj.data
    points = [vertex.co.copy() for vertex in source.vertices]
    faces, material_slots, inner_tags, smoothing = [], [], [], []
    surface_count = 2 * (width - 1) * (height - 1)
    outer_face = ()
    count = width * height
    for polygon in source.polygons:
        quad = tuple(polygon.vertices)
        if not chamfer and polygon.index >= surface_count:
            if not polygon.material_index:
                continue
            # Wrap the edge directly from the front skin to the backing.
            start = next(i for i in range(4) if quad[i] < count <= quad[i - 1])
            a, b = quad[start], quad[(start + 1) % 4]
            quad = a, b, b + count, a + count
        if polygon.index < surface_count and polygon.index % 2:
            # The backing uses the same diagonal with opposite winding.
            a, b, c, d = outer_face
            triangles = ((c + count, b + count, a + count),
                         (d + count, c + count, a + count))
        else:
            a, b, c, d = quad
            triangles = ((a, b, c), (a, c, d))
            outer_face = quad
        faces.extend(triangles)
        material_slots.extend((polygon.material_index,) * 2)
        inner_tags.extend((int(polygon.index < surface_count and polygon.index % 2),) * 2)
        smoothing.extend((polygon.use_smooth,) * 2)
    if not chamfer:
        points = points[:2 * count]
    mesh = bpy.data.meshes.new(source.name + " triangles")
    mesh.from_pydata(points, [], faces)
    mesh.update()
    for material in source.materials:
        mesh.materials.append(material)
    for face, slot, smooth in zip(mesh.polygons, material_slots, smoothing):
        face.material_index = slot
        face.use_smooth = smooth
    mesh.attributes.new("v5d_inner", "INT", "FACE").data.foreach_set("value", inner_tags)
    # Vertex-group weights belong to the mesh vertices and need a transfer.
    weights = [[(item.group, item.weight) for item in vertex.groups]
               for vertex in list(source.vertices)[:len(points)]]
    group_names = [group.name for group in obj.vertex_groups]
    obj.data = mesh
    skin_groups = [obj.vertex_groups.new(name=name) for name in group_names]
    for i, groups in enumerate(weights):
        for group, value in groups:
            skin_groups[group].add([i], value, "REPLACE")
    bpy.data.meshes.remove(source)


def build(lod, collection, rig):
    """Build independent upper, lumbar and shoulder inserts with shirt weights."""
    shirt = Garment(collection.all_objects[f"Undersuit | Combat shirt LOD{lod}"])
    # Radial waist outlines store height and left/right azimuth in degrees.
    abdominal = (
        (1.101, -73, 73), (1.106, -80, 80), (1.132, -75, 75),
        (1.166, -61, 61), (1.213, -59, 59), (1.265, -68, 68),
        (1.311, -88, 88), (1.338, -82, 82),
    )
    lumbar = (
        (1.104, 102, 258), (1.132, 109, 251), (1.161, 109, 251),
        (1.204, 123, 237), (1.266, 126, 234), (1.306, 116, 244),
        (1.341, 105, 255),
    )
    # Front and rear yokes use horizontal spans at each height.
    chest = (
        (1.296, -.141, .141), (1.336, -.156, .156), (1.370, -.163, .163),
        (1.419, -.144, .144), (1.464, -.150, .150), (1.495, -.134, .134),
        (1.521, -.123, .123),
        (1.533, -.103, .103),
    )
    back = (
        (1.325, -.164, .164), (1.370, -.196, .196), (1.420, -.207, .207),
        (1.489, -.212, .212), (1.528, -.198, .198),
        (1.562, -.111, .111), (1.583, -.078, .078),
    )
    # The shoulder saddle spans front-to-back at each lateral station.
    shoulder = (
        (.111, -.032, .105), (.119, -.044, .114), (.132, -.050, .116),
        (.154, -.058, .118),
        (.210, -.061, .088), (.231, -.054, .061),
    )

    collar = (
        (1.583, -.055, .055), (1.590, -.060, .060),
        (1.597, -.052, .052), (1.603, -.041, .041), (1.608, -.028, .028),
    )
    nape = (
        (1.578, 105, 255), (1.594, 94, 266),
        (1.611, 93, 267), (1.632, 98, 262),
    )

    side_return = (
        (1.121, 62, 108), (1.135, 56, 115), (1.153, 51, 88),
        (1.185, 48, 75), (1.215, 47, 72), (1.246, 48, 77), (1.263, 58, 82),
    )
    side_rib = (
        (1.255, 61, 87), (1.277, 57, 104), (1.302, 56, 116),
        (1.317, 62, 115), (1.328, 67, 114),
    )
    collar_wing = (
        (1.573, 72, 99), (1.586, 67, 104), (1.599, 56, 105),
        (1.615, 48, 107), (1.630, 51, 105), (1.640, 63, 96),
    )
    axillary = (
        (1.346, .157, .188), (1.362, .164, .200),
        (1.380, .174, .218), (1.398, .180, .222), (1.407, .188, .220),
    )
    throat = (
        (1.525, -.085, .085), (1.534, -.087, .087), (1.544, -.091, .091),
        (1.555, -.093, .093), (1.566, -.091, .091), (1.576, -.083, .083),
        (1.587, -.066, .066),
    )

    def insert(label, region, side, width, rows, ray, shell, setback, depth):
        # Keep the front neck rows in LOD1 to follow the sharp shirt neckline.
        if lod and label not in ("Collar front lame", "Throat bib"):
            rows = tuple(rows[index] for index in sorted({0, *range(1, len(rows) - 1, 2),
                                                           len(rows) - 1}))
        width = max(3, width - lod * 2)
        obj = plate(collection, rig, shirt, lod, label, region, side, width,
                    rows, ray, shell, setback, lift=depth)
        match_shell_diagonals(obj, width, len(rows), chamfer=side == "C" and ray not in (waist_ray, collar_ray))
        obj["v5d_region"] = "torso_" + obj["v5d_region"]
        return obj

    shells = [
        insert("Abdominal insert", "torso front", "C", 7, abdominal, waist_ray,
               .008, .003, .010),
        insert("Lumbar insert", "torso back", "C", 7, lumbar, waist_ray,
               .009, .003, .008 + lod * .006),
        insert("Clavicle shield", "torso front", "C", 7, chest, front_or_rear(1, -1),
               .008, .003, .012 + .002 * (1 - lod)),
        insert("Scapular shield", "torso back", "C", 7, back, front_or_rear(1, 1),
               .008, .003, .008 + lod * .005),
    ]
    shells.extend((
        insert("Collar front lame", "torso front", "C", 6, collar, front_or_rear(1, -1),
               .006, .0025, .010 + lod * .002),
        insert("Collar nape lame", "torso back", "C", 5, nape, collar_ray,
               .006, .0025, .008),
    ))
    shells.append(insert("Throat bib", "torso front", "C", 7, throat,
                         front_or_rear(1, -1), .005, .002, .010))
    for sign, side in ((1, "L"), (-1, "R")):
        def lateral_ray(angle, z):
            return waist_ray(sign * angle, z)

        def lateral_neck_ray(angle, z):
            return collar_ray(sign * angle, z)

        shells.extend((
            insert("Axillary lame", "torso sides", side, 4, axillary, front_or_rear(sign, 1),
                   .005, .002, .008),
            insert("Neck return", "torso sides", side, 6, collar_wing, lateral_neck_ray,
                   .004, .002, .011),
            insert("Lower rib return", "torso sides", side, 6, side_return, lateral_ray,
                   .005, .002, .009),
            insert("Upper rib lame", "torso sides", side, 6, side_rib, lateral_ray,
                   .005, .002, .010),
        ))
        shells.append(insert("Shoulder saddle", "shoulders", side, 5, shoulder,
                             shoulder_ray(sign), .007, .0025, .008 + lod * .003))
    return shells
