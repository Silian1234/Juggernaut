"""Tapered front greaves and clasped calf shells, fitted to the worn trousers."""
from functools import lru_cache
from math import cos, radians, sin, sqrt

from mathutils import Vector

from leg_shells import between, coordinates, mount_surface, shell_grid, lerp


GREAVE_BOTTOM = .183
GREAVE_TOP = .469
THICKNESS = .015
SHIN_AXES = (
    (.14, .206, .029),
    (.16, .200, .030), (.18, .198, .036), (.20, .192, .042),
    (.24, .186, .040), (.30, .180, .039), (.36, .174, .030),
    (.40, .171, .019), (.44, .164, .009), (.47, .150, .004), (.49, .143, -.004),
)


def worn_clearance(geo, point, floor, direction):
    """Fit one local radial station to its side of the worn trousers."""
    fit = geo.cuff_fit
    x, y, z = point
    dx, dy = direction
    side = geo.side
    _, _, _, radius = fit.index.ray_cast(Vector((side * x, y, z)),
                                      Vector((side * dx, dy, 0)), .175)
    if radius is None:
        raise ValueError(f"No worn trouser surface at {point}")

    lo, hi = radius, radius + .018
    for _ in range(11):
        trial = (lo + hi) * .5
        d = fit.index.find_nearest(Vector((side * (x + trial * dx), y + trial * dy, z)))[3]
        if d < floor:
            lo = trial
        else:
            hi = trial
    return hi


def worn_sections(geo):
    """Get the exact four orthographic limits at each shell station."""
    fit = geo.cuff_fit
    side = geo.side
    edges = {tuple(sorted((a, b))) for face in fit.faces
             for a, b in zip(face, (*face[1:], face[0]))}
    edges = [(fit.points[a], fit.points[b]) for a, b in edges
             if side * fit.points[a].x > 0 and side * fit.points[b].x > 0
             and max(fit.points[a].z, fit.points[b].z) >= .145
             and min(fit.points[a].z, fit.points[b].z) <= .51
             and fit.points[a].z != fit.points[b].z]
    edges = [(a, b) if a.z < b.z else (b, a) for a, b in edges]

    @lru_cache(maxsize=None)
    def limits(z):
        section = [a.lerp(b, (z - a.z) / (b.z - a.z))
                   for a, b in edges if a.z <= z <= b.z]
        xs = [side * p.x for p in section]
        ys = [p.y for p in section]
        # A coarse longitudinal facet bridges trouser extrema between vertices.
        # Leave extra projection room at the trouser's medial-knee hollow and hem.
        medial = .0185 - .0073 * max(0, min(1, (z - .403) / .022, (.487 - z) / .017))
        lateral = .0179 - .0026 * max(0, min(1, (z - .400) / .025, (.494 - z) / .019))
        front = .0171 - .0034 * max(
            max(0, 1 - abs(z - .201) / .030),
            max(0, 1 - abs(z - .452) / .031),
        )
        return min(xs) - medial, max(xs) + lateral, min(ys) - front, max(ys) + .0194

    return limits


def plate_offset(inner_x, inner_y, dx, dy, limits):
    """Tilt the 15 mm outer offset along the garment contour at extrema."""
    low_x, high_x, low_y, high_y = limits
    target_x = inner_x + THICKNESS * dx
    target_y = inner_y + THICKNESS * dy
    if low_x <= target_x <= high_x and low_y <= target_y <= high_y:
        return dx, dy

    candidates = []
    for bound in (low_x, high_x):
        ax = (bound - inner_x) / THICKNESS
        if abs(ax) <= 1:
            ay = sqrt(1 - ax * ax)
            for y in (ay, -ay):
                if low_y <= inner_y + THICKNESS * y <= high_y:
                    candidates.append((ax, y))
    for bound in (low_y, high_y):
        ay = (bound - inner_y) / THICKNESS
        if abs(ay) <= 1:
            ax = sqrt(1 - ay * ay)
            for x in (ax, -ax):
                if low_x <= inner_x + THICKNESS * x <= high_x:
                    candidates.append((x, ay))
    if candidates:
        return max(candidates, key=lambda axis: axis[0] * dx + axis[1] * dy)
    return dx, dy

def fitted_profile(geo, angle_limits, elevation, thickness, crease=None, lap=None):
    limits = worn_sections(geo)
    @lru_cache(maxsize=None)
    def radial(u, v):
        z = elevation(u, v)
        x, y = between(SHIN_AXES, z)
        theta = radians(lerp(*angle_limits, u))
        dx, dy = sin(theta), -cos(theta)
        origin = (x, y, z)
        direction = (dx, dy)
        r = worn_clearance(geo, origin, .0075 if not geo.lod else .0088, direction)
        px, py = x + r * dx, y + r * dy
        ax, ay = plate_offset(px, py, dx, dy, limits(z))
        return px, py, z, ax, ay

    def project(u, v, depth):
        x, y, z, dx, dy = radial(u, v)
        r = (THICKNESS + depth) * thickness(u, v) / THICKNESS
        if crease is not None:
            r -= crease(u, v) * max(0, (depth + THICKNESS) / THICKNESS)
        if lap is not None:
            r *= 1 - lap(u, v)
        return Vector((x + r * dx, y + r * dy, z))

    return project


def greave_skin(geo, p):
    # Follow the garment near the articulations, retaining the frame's
    # calf-driven skin at its two fixed lateral seats.
    from legs import blend_skin

    x, y, z = p
    lateral = max(0, min(1, (x - .216) / .026))
    near_seat = max(
        max(0, 1 - abs(z - height) / .039) * max(0, 1 - abs(y - depth) / .040)
        for depth, height in ((.017, .394), (.031, .188))
    )
    return blend_skin(geo, p, {"Calf": 1.0}, .98 * (1 - lateral * near_seat))


def relax_clearance(geo, grid_size, inner, skin):
    """Correct coarse facets between the garment-fitted vertices."""
    positions = {i: Vector(geo.vertices[i]) for f in inner for i in geo.faces[f]}
    # Keep the fitted deep-set lap aligned with its thin edge chamfer.
    locked = {i for i, point in positions.items()
              if (Vector(geo.vertices[i - grid_size]) - point).length < .007}
    axes = {}
    for i, point in positions.items():
        center_x, center_y = between(SHIN_AXES, point.z)
        axes[i] = Vector((point.x - geo.side * center_x, point.y - center_y, 0)).normalized()

    samples = []
    for index in inner:
        a, b, c, d = geo.faces[index]
        samples.extend(((a, b), (b, c), (c, d), (d, a),
                        (a, c), (b, d),
                        (a, b, c), (a, c, d), (a, b, d), (b, c, d)))
    samples = list(dict.fromkeys(tuple(sorted(sample)) for sample in samples))
    samples.extend((index,) for index in positions)
    nearest = geo.cuff_fit.index.find_nearest

    for _ in range(19):
        for indices in samples:
            position = sum((positions[i] for i in indices), Vector()) / len(indices)
            closest, normal, _, distance = nearest(position)
            distance = distance if (position - closest).dot(normal) >= 0 else -distance
            low, high = .0057, .0112
            error = max(low - distance, min(0, high - distance))
            if abs(error) <= .00004:
                continue
            # This conservatively limits each correction on a locally steep fold.
            for i in indices:
                if i in locked:
                    continue
                strength = max(.45, axes[i].dot(normal))
                positions[i] += axes[i] * (.44 * error / strength)

    limits = worn_sections(geo)
    for i, position in positions.items():
        if i in locked:
            continue
        front = i - grid_size
        thickness = (Vector(geo.vertices[front]) - Vector(geo.vertices[i])).length
        geo.vertices[i] = tuple(position)
        x, y, z = geo.side * position.x, position.y, position.z
        axis = axes[i]
        dx, dy = plate_offset(x, y, geo.side * axis.x, axis.y, limits(z))
        geo.vertices[front] = (geo.side * (x + thickness * dx), y + thickness * dy, z)
        for j in (front, i):
            px, py, pz = geo.vertices[j]
            geo.weights[j] = skin((geo.side * px, py, pz))


def fitted_shell(geo, project, columns, rows, skin, slots=()):
    """Emit a loft and record the actual back sheet for clearance measurement."""
    first_vertex, first_face = len(geo.vertices), len(geo.faces)
    grid_size = len(columns) * len(rows)
    faces = shell_grid(geo, project, columns, rows, skin, THICKNESS, slots=slots)
    if not hasattr(geo, "inner_faces"):
        geo.inner_faces = {}
    back = first_vertex + grid_size
    geo.inner_faces[geo.armor_component] = [
        index for index in range(first_face, len(geo.faces))
        if all(back <= v < back + grid_size for v in geo.faces[index])
    ]
    relax_clearance(geo, grid_size, geo.inner_faces[geo.armor_component], skin)
    return faces


def build(geo):
    """Wrap the tibia in a tapered greave with a fitted ankle and open vents."""
    geo.armor_component = 4

    def elevation(u, v):
        edge = min(u, 1 - u)
        wing = (.017 if u > .50 else .004) * min(1, max(0, (abs(2 * u - 1) - .20) / .60))
        upper_corner = .018 * max(0, 1 - edge / .13)
        t = (v - GREAVE_BOTTOM) / (GREAVE_TOP - GREAVE_BOTTOM)
        knee_relief = .008 * max(0, 1 - abs(u - .50) / .24)
        medial_relief = .030 * max(0, 1 - u / .31)
        # The front hem crosses the ankle above the trouser cuff fold.
        # Its lower side ears leave a seat for the stock shin frame bracket.
        front_hem = .012 * max(0, min(1, (edge - .11) / .16))
        return v + t * (wing - upper_corner - knee_relief - medial_relief) + (1 - t) * front_hem

    def thickness(u, v):
        # Thin the distal casting without thinning the vent walls or knee wings.
        return .010 + .005 * max(0, min(1, (v - .216) / .122))

    def crease(u, v):
        # The forward face breaks into the flanks along shallow longitudinal folds.
        strength = max(0, 1 - min(abs(u - .35), abs(u - .65)) / .028)
        return .0015 * strength * max(0, min(1, (.416 - v) / .040))

    def lap(u, v):
        width = max(0, min(1, 1 - (abs(u - .50) - .105) / .145))
        height = max(0, min(1, (v - .436) / .018))
        return .91 * width * height

    project = fitted_profile(geo, (-103, 111), elevation, thickness, crease, lap)
    # Shared slot columns avoid multiplying all longitudinal stations.
    slots = tuple((.419, .564, z, z + .005) for z in (.409, .421, .433))
    angles = [0, .09, .19, .31, .49, .65, .79, .90, 1]
    levels = [GREAVE_BOTTOM, .205, .226, .252, .283, .322, .354, .384,
              .445, GREAVE_TOP]
    cols = coordinates(angles, True, False, slots=slots)
    if geo.lod:
        levels = [GREAVE_BOTTOM, .208, .230, .262, .298, .337, .375, .447, GREAVE_TOP]
    rows = coordinates(levels, False, False, slots=slots)
    skin = lambda p: greave_skin(geo, p)
    faces = fitted_shell(geo, project, cols, rows, skin, slots)
    mount = mount_surface(geo, faces)
    nominal = project(.735, .356, 0)
    normal = (nominal - project(.735, .356, -.005)).normalized()
    seat = Vector(mount(nominal.y, nominal.z)) - .0012 * normal
    geo.disc(seat, normal, .0037, .0022, skin, "steel", 6)
    rear_guard(geo)
    geo.armor_component = 0
    return mount



def rear_guard(geo):
    """Follow the calf with a clipped shell and a short popliteal relief."""
    geo.armor_component = 8
    bottom, top = .151, .441

    def elevation(u, v):
        side = abs(2 * u - 1)
        t = (v - bottom) / (top - bottom)
        corners = .028 * max(0, (side - .57) / .43)
        notch = .027 * min(1, max(0, (.91 - side) / .55))
        return v + (1 - t) * corners - t * notch

    def thickness(u, v):
        rise = max(0, min(1, (v - .215) / .090))
        relief = max(0, min(1, (v - .350) / .065))
        ankle = max(0, min(1, (v - bottom) / .048))
        return .0070 + .0015 * ankle + .0035 * rise - .0025 * relief

    project = fitted_profile(geo, (125, 240), elevation, thickness)
    columns = [0, .14, .29, .44, .58, .72, .86, 1]
    levels = [bottom, .177, .216, .253, .288, .325, .354, .382, .410, top]
    if geo.lod:
        columns = [0, .16, .34, .53, .72, .86, 1]
        levels = [bottom, .185, .219, .264, .301, .338, .374, .409, top]
    fitted_shell(geo, project, columns, levels, lambda p: greave_skin(geo, p))
