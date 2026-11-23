"""Faceted composite helmet in the Juggernaut head attachment frame.

Front is -Y. LODs share the crown stations, armored aperture and attachment
surfaces. Only sampling density, bevel segments and small hardware change.
"""
from math import cos, floor, pi, sin, tau

from v2_helmet import chart, shell_point as cleared_rac_envelope
from v3_helmet_cowl import head_cowl


# Heights, half-widths and brow/nape depths of the structural liner. The
# forming stations are shared by both LODs to preserve the silhouette.
CROWN = (
    (1.653, .076, .090, .084),
    (1.660, .087, .116, .100),
    (1.685, .105, .137, .118),
    (1.728, .119, .155, .130),
    (1.760, .133, .155, .131),
    (1.787, .143, .149, .129),
    (1.809, .138, .116, .107),
    (1.837, .137, .108, .085),
    (1.867, .130, .091, .073),
    (1.902, .111, .067, .056),
    (1.920, .084, .045, .045),
    (1.927, .057, .033, .040),
    (1.9275, .043, .027, .035),
)

# The top and bottom of the glass use the same stations as the brow and cheek
# plates. The center key extends below the two wings.
APERTURE = (
    # x, front Y, sill Z, roof Z
    (0, -.177, 1.702, 1.766),
    (.012, -.177, 1.702, 1.766),
    (.022, -.177, 1.706, 1.770),
    (.052, -.172, 1.728, 1.785),
    (.086, -.156, 1.761, 1.797),
    (.104, -.143, 1.779, 1.800),
    (.110, -.134, 1.787, 1.795),
)


def interpolate(a, b, t):
    return a + (b - a) * t


def liner_point(theta, value):
    z, width, front, rear = value
    sin_angle, cos_angle = sin(theta), cos(theta)
    x = width * abs(sin_angle) ** .80
    y = .018 - (front if cos_angle >= 0 else rear) * (
        abs(cos_angle) ** .82 if cos_angle >= 0 else -abs(cos_angle) ** .82)
    # Retain open pockets for the fitted RAC cup and rear headset arms.
    clearance = (.087 + max(0, abs(y - .017) - .073) * .57
                 + max(0, z - 1.769) * 1.17)
    # Closed ear sections follow the donor ears inside the RAC cup clearance.
    ear = max(0, min(1, (z - 1.651) / .040, (1.760 - z) / .027))
    ear *= max(0, min(1, (y + .056) / .030, (.074 - y) / .032))
    clearance += .0145 * ear
    shoulder = max(0, .011 - abs(x - clearance))
    x = min(x, clearance) - shoulder ** 2 / .044
    # The rear temple channel inherits the measured RAC attachment envelope.
    # Blend through the channel shoulders above and below the headset arms.
    if cos_angle < 0 and 1.735 < z < 1.918:
        hx, hy, _ = cleared_rac_envelope(theta, min(z, 1.884))
        pocket = min(1, -cos_angle * 3, (z - 1.735) / .020, (1.918 - z) / .066)
        x = interpolate(x, min(x, abs(hx) - .003), pocket)
        y = interpolate(y, min(y, hy - .004), pocket)
    return (x if sin_angle >= 0 else -x, y, z)


def crown_point(theta, value):
    """Form the upper shell on flat transverse chords with a soft shoulder."""
    z = value[0]
    original = liner_point(theta, value)
    fold = max(0, min(1, (z - 1.799) / .042))
    if not fold:
        return original
    interval = tau / 12
    start = (floor(theta / interval + .5) - .5) * interval
    a = liner_point(start, value)
    b = liner_point(start + interval, value)
    t = (theta - start) / interval
    x = interpolate(a[0], b[0], t)
    y = interpolate(a[1], b[1], t)
    return (interpolate(original[0], x, fold),
            interpolate(original[1], y, fold), z)


def rings(api, collection, name, rows, material, sides, point, cap=False, ear_material=None):
    points = [point(tau * (j / sides - .5), value)
              for value in rows for j in range(sides)]
    coords = [(j / sides, i / (len(rows) - 1))
              for i in range(len(rows)) for j in range(sides)]
    faces = []
    sections = []
    for station in range(len(rows) - 1):
        for j in range(sides):
            a, b = station * sides + j, station * sides + (j + 1) % sides
            face = (a, b, b + sides, a + sides)
            if cap and eyepiece_relief(points, face):
                continue
            faces.append(face)
            sections.append((station, j))
    if cap:
        top = len(points) - sides
        center = len(points)
        points.append((0, .022, rows[-1][0]))
        coords.append((.5, 1))
        faces.extend((top + j, top + (j + 1) % sides, center) for j in range(sides))
    materials = [material]
    indices = None
    if ear_material:
        materials.append(ear_material)
        indices = []
        for face in faces[:len(sections)]:
            lower = points[face[0]][2]
            upper = points[face[2]][2]
            j = face[0] % sides
            theta = abs(tau * ((j + .5) / sides - .5))
            ear = lower < 1.750 and upper > 1.657 and 1.00 < theta < 2.04
            indices.append(int(ear))
        indices.extend([0] * sides)
    obj = chart(api.surface(collection, name, points, faces, materials, indices), coords, unwrap=True)
    if cap:
        for face in list(obj.data.polygons)[-sides:]:
            for corner in face.loop_indices:
                vertex = obj.data.vertices[obj.data.loops[corner].vertex_index].co
                obj.data.uv_layers.active.data[corner].uv = (.5 + vertex.x * 12, .5 + (vertex.y - .027) * 12)
    mesh = obj.data
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    if cap:
        # Break the shading only at the upper crown's formed creases. Surface
        # patches between creases share normals with their neighboring rings.
        strip = sides // 12
        normals = []
        face_by_section = {section: i for i, section in enumerate(sections)}
        for face in mesh.polygons:
            if face.index >= len(sections):
                normals.extend([face.normal] * len(face.vertices))
                continue
            row, column = sections[face.index]
            for corner, vertex in enumerate(face.vertices):
                if row < len(rows) - 1 and rows[row][0] >= 1.833:
                    delta = -1 if corner in (0, 3) else 1
                    near_column = column + delta
                    layer = row - 1 if corner < 2 else row + 1
                    common = [face.normal]
                    vertical = face_by_section.get((layer, column))
                    horizontal = face_by_section.get((row, near_column % sides))
                    if vertical is not None and rows[layer][0] >= 1.817:
                        common.append(mesh.polygons[vertical].normal)
                    same_land = (near_column + strip // 2) // strip == (column + strip // 2) // strip
                    if same_land and horizontal is not None:
                        common.append(mesh.polygons[horizontal].normal)
                    normal = sum(common[1:], common[0].copy()).normalized()
                else:
                    normal = mesh.vertices[vertex].normal
                normals.append(normal)
        mesh.normals_split_custom_set(normals)
    return obj


def eyepiece_relief(points, face):
    """Leave a clear horizontal optical path from each eye to the smoked pane."""
    a, b, upper, _ = (points[index] for index in face)
    center = abs((a[0] + b[0]) * .5)
    return a[1] < 0 and 1.713 <= a[2] and upper[2] <= 1.744 and .008 <= center <= .058


def laminate(api, collection, name, perimeter, center, materials, bevels, side=1, thickness=.011,
             retreat=(0, 1, 0)):
    """Build a pressed armor plate with a sloped border and a recessed return."""
    n = len(perimeter)
    points = []
    for depth, fraction in ((thickness, .99), (0, 1), (-.002, .86)):
        for vertex in perimeter:
            point = [interpolate(origin, coord, fraction) + depth * direction
                     for origin, coord, direction in zip(center, vertex, retreat)]
            point[0] *= side
            points.append(point)
    points.append((side * center[0], center[1], center[2]))
    faces, indices = [tuple(range(n - 1, -1, -1))], [0]
    for j in range(n):
        k = (j + 1) % n
        faces.extend(((j, k, k + n, j + n),
                      (j + n, k + n, k + 2 * n, j + 2 * n),
                      (j + 2 * n, k + 2 * n, len(points) - 1)))
        indices.extend((0, 1, 0))
    if side < 0:
        faces = [face[::-1] for face in faces]
    obj = api.surface(collection, name, points, faces, materials, indices)
    # Front facing profiles are folded to fit the crown, so recalculate their
    # winding and the near-vertical side plate winding on the complete shell.
    import bmesh

    mesh = bmesh.new()
    try:
        mesh.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
        mesh.to_mesh(obj.data)
        obj.data.update()
    finally:
        mesh.free()
    api.bevel(obj, .00065, bevels)
    return obj


def aperture(api, collection, m, low_detail):
    """Continuous smoked glass with a short, straight-sided center drop."""
    positive = []
    samples = 1 if low_detail else 5
    for a, b in zip(APERTURE, APERTURE[1:]):
        positive.extend(tuple(interpolate(p, q, j / samples) for p, q in zip(a, b))
                        for j in range(samples))
    positive.append(APERTURE[-1])
    columns = [(-x, y, low, high) for x, y, low, high in reversed(positive[1:])] + positive
    rows = 3 if low_detail else 10
    points, coords = [], []
    for i in range(rows + 1):
        t = i / rows
        for x, y, low, high in columns:
            points.append((x, y - .002 * sin(pi * t), interpolate(low - .0025, high, t)))
            coords.append((.5 + x / .220, t))
    n = len(columns)
    faces = [(i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j)
             for i in range(rows) for j in range(n - 1)]
    chart(api.surface(collection, "Helmet - smoked key-slot visor", points, faces, [m["glass"]]), coords)


def brow(api, collection, m, bevels):
    for side in (-1, 1):
        laminate(api, collection, f"Helmet - folded brow shield {side}", (
            (.0, -.186, 1.767), (.018, -.186, 1.768), (.054, -.180, 1.785),
            (.094, -.164, 1.801), (.113, -.146, 1.805), (.119, -.129, 1.809),
            (.108, -.108, 1.850), (.071, -.119, 1.856), (.044, -.122, 1.838),
            (.028, -.133, 1.796), (0, -.139, 1.794),
        ), (.061, -.152, 1.814), (m["armor"], m["lip"]), bevels, side)


def crown_value(z):
    for lower, upper in zip(CROWN, CROWN[1:]):
        if lower[0] <= z <= upper[0]:
            t = (z - lower[0]) / (upper[0] - lower[0])
            return tuple(interpolate(a, b, t) for a, b in zip(lower, upper))
    raise ValueError(f"Height {z} is outside the crown")


def shell_feature(theta, z, offset):
    x, y, _ = crown_point(theta, crown_value(z))
    return (x + offset * sin(theta), y - offset * cos(theta), z)


def rear_access_panel(api, collection, m, bevels):
    points = [shell_feature(theta, z, .006) for theta, z in (
        (2.67, 1.716), (2.75, 1.741), (2.97, 1.749), (pi, 1.749),
        (3.31, 1.749), (3.53, 1.741), (3.61, 1.716), (3.49, 1.689),
        (3.30, 1.687), (pi, 1.687), (2.98, 1.687), (2.79, 1.689),
    )]
    laminate(api, collection, "Helmet - supported nape access cover", points,
             shell_feature(pi, 1.720, .010), (m["face"], m["lip"]), bevels,
             thickness=.017, retreat=(0, -1, 0))


def crown_service_seams(api, collection, m, low_detail):
    """Swept dark tool channels on the truncated side lands."""
    segments = 3 if low_detail else 6
    for side in (-1, 1):
        for i in range(2 if low_detail else 3):
            start = side * (.82 + i * .125)
            end = start + side * .092
            upper = 1.899 - i * .002
            lower = 1.869 - i * .003
            points = []
            for row in range(segments + 1):
                for column in range(segments + 1):
                    u, v = column / segments, row / segments
                    bottom = lower + .003 * u
                    top = upper - .005 * (1 - u)
                    points.append(shell_feature(interpolate(start, end, u),
                                                interpolate(bottom, top, v), .0012))
            stride = segments + 1
            faces = []
            for row in range(segments):
                for column in range(segments):
                    k = row * stride + column
                    face = (k, k + 1, k + stride + 1, k + stride)
                    faces.append(face if side > 0 else face[::-1])
            api.surface(collection, f"Helmet - crown service channel {side}/{i}",
                        points, faces, [m["seal"]])


def build_helmet(api, collection, m, low_detail):
    sides = 48 if low_detail else 96
    bevels = 1 if low_detail else 3
    divisions = 1 if low_detail else 3
    rows = [tuple(interpolate(p, q, i / divisions) for p, q in zip(a, b))
            for a, b in zip(CROWN, CROWN[1:]) for i in range(divisions)] + [CROWN[-1]]
    rows.extend(crown_value(z) for z in (1.713, 1.724, 1.735, 1.744))
    rows.sort()
    rings(api, collection, "Helmet - graphite ballistic crown", rows, m["armor"],
          sides, crown_point, cap=True, ear_material=m["gasket"])
    rings(api, collection, "Helmet - laminated rotation gasket",
          (0, .16, .28, .46, .63, .79, 1), m["gasket"], sides,
          lambda theta, t: ((.075 + .015 * t) * sin(theta),
                            .018 - (.073 + .030 * t) * cos(theta),
                            1.644 + .018 * t + .004 * abs(sin(theta))))
    head_cowl(api, collection, m, low_detail)
    aperture(api, collection, m, low_detail)
    brow(api, collection, m, bevels)
    rear_access_panel(api, collection, m, bevels)
    crown_service_seams(api, collection, m, low_detail)

    for side in (-1, 1):
        laminate(api, collection, f"Helmet - sloped cheek shield {side}", (
            (.013, -.184, 1.694), (.025, -.183, 1.708), (.054, -.177, 1.728),
            (.090, -.160, 1.763), (.108, -.148, 1.784), (.119, -.127, 1.800),
            (.124, -.088, 1.786), (.114, -.074, 1.748), (.102, -.086, 1.708),
            (.060, -.132, 1.672), (.028, -.152, 1.668),
        ), (.074, -.168, 1.711), (m["face"], m["lip"]), bevels, side)
        for index, (x, y, z) in enumerate(((.063, -.175, 1.719),
                                           (.033, -.159, 1.687), (.093, -.138, 1.811))):
            if low_detail and index != 0:
                continue
            api.spindle(collection, f"Helmet - retained screw {side}/{index}", (side * x, y, z),
                        .0032, .004, m["bolt"], (side * .32, -1, .18), 10, .0005,
                        bevel_segments=bevels)
        for index in range(1 if low_detail else 3):
            api.box(collection, f"Helmet - black temple louver {side}/{index}",
                    (side * (.114 - .002 * index), -.089 + .002 * index, 1.766 - .007 * index),
                    (.006, .024, .004), m["seal"], .0007, (.15, side * -.13, side * -.2), bevels)

    laminate(api, collection, "Helmet - central chin keel", (
        (-.032, -.160, 1.668), (.032, -.160, 1.668), (.030, -.183, 1.690),
        (.014, -.186, 1.700), (-.014, -.186, 1.700), (-.030, -.183, 1.690),
    ), (0, -.184, 1.684), (m["face"], m["lip"]), bevels, thickness=.033)
    api.sensor_mount(collection, m, bevels)
