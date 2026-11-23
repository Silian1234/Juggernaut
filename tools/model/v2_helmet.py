"""Rounded EOD helmet surfaces in the validated Juggernaut head coordinates."""

from bisect import bisect_right
from math import cos, pi, sin, tau

from mathutils import Vector


# Each section defines height, width, forward depth and rear depth from the
# attachment frame. The crown contracts above the thermal dovetail.
SHELL = (
    (1.647, .073, .109, .100),
    (1.655, .098, .140, .109),
    (1.674, .118, .178, .117),
    (1.702, .130, .197, .122),
    (1.733, .134, .196, .123),
    (1.760, .139, .185, .124),
    (1.782, .139, .178, .123),
    (1.804, .135, .153, .106),
    (1.825, .123, .130, .090),
    (1.845, .109, .107, .081),
    (1.866, .090, .080, .071),
    (1.884, .066, .061, .056),
    (1.895, .036, .033, .029),
    (1.900, .010, .010, .009),
)


def section(z):
    i = min(len(SHELL) - 2, max(0, bisect_right(SHELL, (z, float("inf"))) - 1))
    a, b = SHELL[i:i + 2]
    prev, following = SHELL[max(0, i - 1)], SHELL[min(len(SHELL) - 1, i + 2)]
    height = b[0] - a[0]
    u = (z - a[0]) / height
    ease = u * u * (3 - 2 * u)
    return tuple(
        x * (1 - ease) + y * ease
        + height * (u * (1 - u) ** 2 * (y - p) / (b[0] - prev[0])
                    - u * u * (1 - u) * (n - x) / (following[0] - a[0]))
        for p, x, y, n in zip(prev[1:], a[1:], b[1:], following[1:])
    )


def shell_point(theta, z, offset=0):
    width, front, rear = section(z)
    angle_cos, angle_sin = cos(theta), sin(theta)
    x = (width + offset) * angle_sin
    depth = front if angle_cos >= 0 else rear
    y = .018 - (depth + offset) * angle_cos
    # The outer sweep is full at the brow, while the cup sockets under
    # the brow retain the validated inner RAC envelope.
    allowance = (.0875 + max(0, abs(y - .017) - .072) * .59
                 + max(0, z - 1.766) * 1.50)
    soften = max(0, .020 - abs(abs(x) - allowance))
    x = min(abs(x), allowance) - soften * soften / .080
    return (x if angle_sin >= 0 else -x, y, z)


def chart(obj, coords, unwrap=False):
    """Set per-corner UVs so the longitudinal seam does not span the image."""
    uv = obj.data.uv_layers.active
    for face in obj.data.polygons:
        points = [coords[obj.data.loops[corner].vertex_index] for corner in face.loop_indices]
        wraps = unwrap and max(u for u, v in points) - min(u for u, v in points) > .5
        for corner, (u, v) in zip(face.loop_indices, points):
            uv.data[corner].uv = (u + 1 if wraps and u < .5 else u, v)
    obj["preserve_uv"] = True
    return obj


def ring_mesh(surface, collection, name, sections, material, sides, point, cap=False):
    points = [point(tau * (j / sides - .5), value) for value in sections for j in range(sides)]
    faces = []
    for i in range(len(sections) - 1):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            faces.append((a, b, b + sides, a + sides))
    coords = [(j / sides, i / (len(sections) - 1))
              for i in range(len(sections)) for j in range(sides)]
    if cap:
        first = len(points) - sides
        center = len(points)
        points.append((0, .0175, 1.9005))
        faces.extend((first + j, first + (j + 1) % sides, center) for j in range(sides))
        coords.append((.5, 1))
    obj = chart(surface(collection, name, points, faces, [material]), coords, unwrap=True)
    if cap:
        for face in list(obj.data.polygons)[-sides:]:
            for corner in face.loop_indices:
                vector = obj.data.vertices[obj.data.loops[corner].vertex_index].co
                obj.data.uv_layers.active.data[corner].uv = (.5 + 45 * vector.x,
                                                            .5 + 45 * (vector.y - .0175))
    return obj


def rolled_edge(points, coords, faces, columns, rows, inset):
    """Close the exposed plate perimeter inside the load-bearing shell."""
    n = columns + 1
    boundary = [
        *range(n),
        *(i * n + columns for i in range(1, rows + 1)),
        *(rows * n + j for j in range(columns - 1, -1, -1)),
        *(i * n for i in range(rows - 1, 0, -1)),
    ]
    first = len(points)
    for original in boundary:
        x, y, z = points[original]
        u, v = coords[original]
        # The seam lies against the shell, so preserve relative bevel scale
        # while keeping the side-wall texture coordinates nondegenerate.
        points.append((x * .94, y + inset, z))
        coords.append((.5 + (u - .5) * .96, .5 + (v - .5) * .96))
    for i, a in enumerate(boundary):
        j = (i + 1) % len(boundary)
        faces.append((a, first + i, first + j, boundary[j]))


def wrap(surface, collection, name, material, columns, rows, theta_limit, center_z,
         height, profile, depth):
    """Form a convex laminate on the helmet with a rounded perimeter."""
    points, coords, faces = [], [], []
    for i in range(rows + 1):
        v = i / rows
        for j in range(columns + 1):
            u = j / columns
            theta = theta_limit * (2 * u - 1) * (1 - .16 * abs(2 * v - 1) ** 8)
            z = center_z + (v - .5) * height * (1 - .31 * abs(2 * u - 1) ** 7) + profile(theta)
            points.append(shell_point(theta, z, depth(u, v)))
            coords.append((u, v))
    for i in range(rows):
        for j in range(columns):
            a = i * (columns + 1) + j
            faces.append((a, a + 1, a + columns + 2, a + columns + 1))
    rolled_edge(points, coords, faces, columns, rows, .007)
    return chart(surface(collection, name, points, faces, [material]), coords)


def visor(surface, collection, m, columns, low_detail):
    """The lens and frame share an edge, with separate material slots and UVs."""
    spans = (0, .10, .19, .30, .50, .71, .83, .92, 1) if low_detail else (
        0, .055, .12, .19, .30, .39, .50, .61, .71, .83, .90, .95, 1)
    points, coords, faces, indices = [], [], [], []
    for v in spans:
        for j in range(columns + 1):
            u = j / columns
            across = 2 * u - 1
            middle = sin(pi * v)
            theta = 1.02 * across * (.95 + .05 * middle)
            profile = .006 * (1 - cos(theta * 2.2))
            z = 1.756 + (v - .5) * .038 * (1 - .54 * abs(across) ** 7) + profile
            edge = min(1, j / 2, (columns - j) / 2)
            sill = .008 * sin(pi * v) ** .47
            lip = .009 * max(0, 1 - abs(v - .86) / .17)
            depth = .0001 + edge * (sill + lip)
            points.append(shell_point(theta, z, depth))
            coords.append((u, v))
    glass_rows = (3, 4) if low_detail else (4, 5, 6, 7)
    for i in range(len(spans) - 1):
        for j in range(columns):
            a = i * (columns + 1) + j
            faces.append((a, a + 1, a + columns + 2, a + columns + 1))
            outer_column = min(j, columns - 1 - j)
            if i in glass_rows and outer_column >= 2:
                indices.append(2)
            elif i in (min(glass_rows) - 1, max(glass_rows) + 1) and outer_column >= 1:
                indices.append(1)
            else:
                indices.append(0)
    rolled_edge(points, coords, faces, columns, len(spans) - 1, .006)
    indices.extend([0] * (len(faces) - len(indices)))
    obj = surface(collection, "Helmet - armored glass and sealed brow frame", points,
                  faces, [m["lip"], m["seal"], m["glass"]], indices)
    return chart(obj, coords)


def build_helmet(api, collection, m, low_detail):
    surface, box, spindle = api.surface, api.box, api.spindle
    sides, stacks = (36, 24) if low_detail else (72, 47)
    segments, bevels = (10, 1) if low_detail else (20, 3)
    divisions = [SHELL[0][0] + (SHELL[-1][0] - SHELL[0][0]) * i / stacks
                 for i in range(stacks + 1)]
    ring_mesh(surface, collection, "Helmet - continuous composite crown", divisions,
              m["armor"], sides, shell_point, cap=True)

    def mantle_point(theta, t):
        side, front = abs(sin(theta)), max(0, cos(theta))
        return ((.073 + t * (.014 + .010 * front)) * sin(theta),
                .018 - (.081 + t * (.021 + .015 * front)) * cos(theta),
                1.6425 + t * .026 + .002 * side + .005 * front)

    mantle_sections = 6 if low_detail else 12
    ring_mesh(surface, collection, "Helmet - overlapping neck mantle",
              [i / mantle_sections for i in range(mantle_sections + 1)],
              m["gasket"], sides, mantle_point)
    ring_mesh(surface, collection, "Helmet - neck roll",
              (.12, .23, .31, .36), m["seal"], sides,
              lambda theta, t: (lambda p: (p[0] + .003 * sin(theta),
                                           p[1] - .003 * cos(theta), p[2]))(mantle_point(theta, t)))

    columns, rows = (22, 5) if low_detail else (44, 11)
    visor(surface, collection, m, columns, low_detail)
    wrap(surface, collection, "Helmet - convex ceramic lower faceplate", m["face"],
         columns, rows + 4, 1.24, 1.694, .095,
         lambda theta: .015 * sin(theta) ** 2,
         lambda u, v: .0018 + .010 * sin(pi * u) ** .6 * sin(pi * v) ** .7)
    wrap(surface, collection, "Helmet - chin laminate edge", m["lip"], columns, rows,
         1.08, 1.667, .014, lambda theta: .014 * sin(theta) ** 2,
         lambda u, v: .003 + .006 * sin(pi * v) * sin(pi * u) ** .6)

    # Rear laminate follows the main shell, ending below the headset yoke.
    points, coords, faces = [], [], []
    rear_columns = 22 if low_detail else 42
    for i, bulge in enumerate((.002, .003, .005, .005, .003, .002)):
        v = i / 5
        for j in range(rear_columns + 1):
            u = j / rear_columns
            theta = pi + (2 * u - 1) * (.55 + .20 * sin(pi * v))
            z = 1.660 + v * .058 + .007 * abs(2 * u - 1) ** 2
            points.append(shell_point(theta, z, .001 + bulge * sin(pi * u) ** .5))
            coords.append((u, v))
    for i in range(5):
        for j in range(rear_columns):
            a = i * (rear_columns + 1) + j
            faces.append((a, a + 1, a + rear_columns + 2, a + rear_columns + 1))
    rolled_edge(points, coords, faces, rear_columns, 5, -.006)
    chart(surface(collection, "Helmet - laminated nape impact plate", points, faces, [m["lip"]]),
          coords)

    for side in (-1, 1):
        for index, (theta, z, depth) in enumerate(((.65, 1.702, .010),
                                                   (.76, 1.692, .009),
                                                   (.72, 1.718, .010))):
            if low_detail and index:
                continue
            direction = Vector((side * sin(theta), -cos(theta), 0))
            center = shell_point(side * theta, z, depth)
            spindle(collection, f"Helmet - cheek lock {side}/{index}", center, .0039, .006,
                    m["bolt"], direction, 8, .0006, bevel_segments=bevels)
        for index in range(2 if low_detail else 4):
            theta = side * (.34 + .074 * index)
            center = shell_point(theta, 1.684 + .002 * index, .011)
            box(collection, f"Helmet - chin intake recess {side}/{index}", center,
                (.007, .0045, .014), m["seal"], .0015, (0, side * -.23, theta), bevels)

        box(collection, f"Helmet - temple hinge fairing {side}", (side * .072, -.014, 1.712),
            (.038, .062, .054), m["lip"], .011, (.09, 0, side * .07), bevels)
        spindle(collection, f"Helmet - flush hinge nut {side}", (side * .089, -.019, 1.712),
                .023, .006, m["metal"], (side, 0, 0), segments, .0012, bevel_segments=bevels)
        spindle(collection, f"Helmet - hinge spindle {side}", (side * .092, -.019, 1.712),
                .010, .004, m["bolt"], (side, 0, 0), segments, .00065, bevel_segments=bevels)
        box(collection, f"Helmet - rear neck anchor {side}", (side * .043, .108, 1.660),
            (.024, .025, .040), m["lip"], .005, (-.20, 0, side * -.29), bevels)
    api.sensor_mount(collection, m, bevels)
