"""Low, replaceable ballistic shell for the A-01 helmet, with -Y forward."""
from math import cos, exp, sin, tau

from mathutils import Vector

from v2_helmet import chart
from v3_helmet import CROWN as FITTED_CROWN
from v3_helmet import interpolate, laminate, liner_point, rear_access_panel, rings
from v3_helmet_cowl import PROFILES as COWL_PROFILES
from v3_helmet_cowl import head_cowl


# The lower liner preserves the measured head and RAC envelope. The last five
# stations form the rolled shoulder, flat roof and blunt rear of the new shell.
SHELL = (*FITTED_CROWN[:6],
         (1.809, .134, .115, .105),
         (1.825, .132, .114, .095),
         (1.846, .120, .105, .084),
         (1.863, .096, .085, .074),
         (1.872, .073, .062, .062),
         (1.873, .054, .046, .047))

# Each row is X, Y, visor sill, visor roof. Cheek and brow cover the ends.
WINDOW = (
    (0, -.173, 1.682, 1.754),
    (.014, -.173, 1.680, 1.755),
    (.028, -.173, 1.707, 1.755),
    (.055, -.169, 1.711, 1.755),
    (.088, -.155, 1.739, 1.756),
    (.104, -.140, 1.746, 1.756),
    (.111, -.129, 1.749, 1.754),
)

BROW = (
    (0, -.185, 1.748), (.044, -.183, 1.748),
    (.087, -.169, 1.750), (.113, -.146, 1.759),
    (.126, -.104, 1.777), (.124, -.076, 1.807),
    (.107, -.067, 1.840), (.083, -.089, 1.859),
    (.054, -.105, 1.857), (.045, -.103, 1.840),
    (.042, -.103, 1.807), (.029, -.140, 1.797), (0, -.143, 1.795),
)

CHEEK = (
    (.014, -.177, 1.680), (.026, -.182, 1.714),
    (.061, -.180, 1.719), (.094, -.164, 1.743),
    (.119, -.122, 1.765), (.128, -.085, 1.762),
    (.121, -.070, 1.707), (.104, -.099, 1.675),
    (.074, -.123, 1.653), (.040, -.156, 1.650),
)


def section(z):
    for lower, upper in zip(SHELL, SHELL[1:]):
        if lower[0] <= z <= upper[0]:
            t = (z - lower[0]) / (upper[0] - lower[0])
            return tuple(interpolate(a, b, t) for a, b in zip(lower, upper))
    raise ValueError(f"Shell has no section at {z}")


def shell_point(theta, value):
    fitted = liner_point(theta, value)
    amount = max(0, min(1, (value[0] - 1.786) / .040))
    # Leave the rear-quarter headset channel in the established fit frame.
    amount *= min(1, max(0, cos(theta) + .35))
    step = tau / 12
    start = int(theta // step) * step
    a, b = liner_point(start, value), liner_point(start + step, value)
    chord = tuple(interpolate(x, y, (theta - start) / step) for x, y in zip(a, b))
    return tuple(interpolate(x, y, amount) for x, y in zip(fitted, chord))


def pane(api, collection, m):
    columns = [(-x, y, sill, roof) for x, y, sill, roof in reversed(WINDOW[1:])]
    columns.extend(WINDOW)
    points = [(x, y, z) for x, y, sill, roof in columns for z in (sill, roof)]
    coords = [(.5 + x / .222, float(i % 2)) for i, (x, _, _) in enumerate(points)]
    obj = api.surface(collection, "Helmet - recessed smoked T visor", points,
                      [(i, i + 2, i + 3, i + 1) for i in range(0, len(points) - 2, 2)],
                      [m["glass"]])
    chart(obj, coords)


def gaiter_folds(api, collection, m, low_detail):
    """Add overlapping, tapering fabric folds over the fitted lower seal."""
    x, y = -.00062798, .02180314
    span = 24 if low_detail else 36
    for index, height in enumerate((1.593, 1.609, 1.626, 1.643)):
        points = []
        for dz, rise in ((-.005, -.002), (-.002, .0023), (.001, .0042), (.006, -.0015)):
            for step in range(span + 1):
                theta = (step / span - .5) * 4.36
                station = abs(theta) * 24 / tau
                sector = int(station)
                u = station - sector
                # Drape through the chin and let the flanks taper under the
                # side seals instead of leaving raised seams over the ears.
                z = height + dz + .009 * (1 - cos(theta)) + .003 * sin(theta + index)
                for (za, ra), (zb, rb) in zip(COWL_PROFILES, COWL_PROFILES[1:]):
                    if za <= z <= zb:
                        low = interpolate(ra[sector], ra[sector + 1], u)
                        high = interpolate(rb[sector], rb[sector + 1], u)
                        radius = interpolate(low, high, (z - za) / (zb - za))
                        break
                else:
                    raise ValueError("Gaiter fold extends outside the fitted jaw seal")
                radius -= .018 * exp(-((z - 1.598) / .011) ** 2 - ((station * 15 - 34) / 13) ** 2)
                radius += rise * sin(step * .5 * tau / span)
                points.append((x + radius * sin(theta), y - radius * cos(theta), z))
        stride = span + 1
        faces = [(n, n + 1, n + stride + 1, n + stride)
                 for row in range(3) for i in range(span) for n in (row * stride + i,)]
        api.surface(collection, f"Helmet - draped gaiter fold {index}", points, faces, [m["gasket"]])


def bar(api, collection, name, start, stop, radius, mat, sides, bevels, tip=None):
    a, b = Vector(start), Vector(stop)
    api.spindle(collection, name, (a + b) / 2, radius, (b - a).length,
                mat, b - a, sides, .0004, radius_tip=tip, bevel_segments=bevels)


def antenna(api, collection, m, bevels, low_detail):
    a = Vector((.106, -.057, 1.828))
    b = Vector((.108, -.047, 1.850))
    c = Vector((.113, -.031, 1.889))
    segments = 8 if low_detail else 12
    bar(api, collection, "Helmet - antenna feedthrough", a, a.lerp(b, .54),
        .008, m["bolt"], segments, bevels)
    bar(api, collection, "Helmet - antenna spring core", a, b,
        .004, m["seal"], segments, bevels)
    axis = (b - a).normalized()
    for index in range(3 if low_detail else 5):
        base = a.lerp(b, .46 + index * (.16 if low_detail else .09))
        bar(api, collection, f"Helmet - spring ring {index}", base, base + axis * .0018,
            .0053, m["metal"], segments, bevels)
    bar(api, collection, "Helmet - canted antenna", b, c, .0040,
        m["seal"], segments, bevels, tip=.0022)
    bar(api, collection, "Helmet - antenna tip", c.lerp(b, .055),
        c + (c - b).normalized() * .0030, .0027, m["seal"], segments, bevels)


def pod(api, collection, m, side, bevels, low_detail):
    # Front-of-ear case stays clear of the donor cups and rear headset arms.
    outline = ((.097, -.110, 1.770), (.121, -.108, 1.784),
               (.130, -.083, 1.822), (.116, -.056, 1.832),
               (.116, -.041, 1.815), (.119, -.050, 1.786),
               (.120, -.073, 1.768))
    laminate(api, collection, f"Helmet - side sensor pod {side}", outline,
             (.139, -.078, 1.799), (m["armor"], m["lip"]), bevels, side,
             thickness=.020, retreat=(-1, 0, 0))
    axis = (side, -.1, 0.15)
    center = (side * .133, -.083, 1.801)
    segments = 8 if low_detail else 16
    api.spindle(collection, f"Helmet - pod connector flange {side}", center,
                .013, .005, m["bolt"], axis, segments, .001, bevel_segments=bevels)
    api.spindle(collection, f"Helmet - pod captive cover {side}", (side * .137, *center[1:]),
                .0085, .005, m["seal"], axis, segments, .001, bevel_segments=bevels)
    for index in range(2 if low_detail else 4):
        api.box(collection, f"Helmet - pod intake grille {side}/{index}",
                (side * (.117 - index * .0015), -.060 + .003 * index, 1.806 - .005 * index),
                (.004, .013, .0027), m["seal"], .0005, (0, side * .13, side * .10), bevels)


def jaw_vents(api, collection, m, side, bevels, low_detail):
    for index in range(2 if low_detail else 4):
        y = -.086 - .007 * index
        z = 1.729 - .004 * index
        x = .124 - .0030 * index
        api.box(collection, f"Helmet - jaw grille {side}/{index}", (side * x, y, z),
                (.004, .0043, .013), m["seal"], .00065,
                (.23, -.16 * side, -.28 * side), bevels)


def nape_hardware(api, collection, m, bevels, low_detail):
    for side in (-1, 1):
        axis = (side * .18, 1, 0)
        for i, (y, z) in enumerate(((.151, 1.704), (.143, 1.731))):
            api.spindle(collection, f"Helmet - nape cover screw {side}/{i}",
                        (side * .032, y, z), .0031, .004, m["bolt"], axis,
                        8, .00045, bevel_segments=bevels)
        rail = ((.110, -.062, 1.806), (.118, -.051, 1.833),
                (.115, -.016, 1.842), (.114, .002, 1.826),
                (.119, -.008, 1.812), (.120, -.040, 1.800))
        laminate(api, collection, f"Helmet - side service rail {side}", rail,
                 (.122, -.033, 1.821), (m["face"], m["lip"]), bevels, side,
                 thickness=.014, retreat=(-1, 0, 0))
        if not low_detail:
            for index in range(2):
                api.spindle(collection, f"Helmet - service rail screw {side}/{index}",
                            (side * (.123 - .003 * index), -.035 + .017 * index,
                             1.821 + .003 * index), .0028, .004, m["bolt"], (side, 0, 0),
                            8, .00045, bevel_segments=bevels)


def build_helmet(api, collection, m, low_detail):
    sides = 48 if low_detail else 72
    bevels = 1 if low_detail else 2
    divisions = 1 if low_detail else 2
    rows = [tuple(interpolate(p, q, i / divisions) for p, q in zip(a, b))
            for a, b in zip(SHELL, SHELL[1:]) for i in range(divisions)] + [SHELL[-1]]
    # Snap forming and optical stations to one row at a shared height.
    stations = {round(row[0], 6): row for row in rows}
    stations.update((z, section(z)) for z in (1.713, 1.724, 1.735, 1.744))
    rows = [stations[z] for z in sorted(stations)]
    rings(api, collection, "Helmet - formed inner shell and roof", rows, m["armor"],
          sides, shell_point, cap=True, ear_material=m["gasket"])
    rings(api, collection, "Helmet - rotation gasket",
          (0, .16, .28, .46, .63, .79, 1), m["gasket"], sides,
          lambda theta, t: ((.075 + .015 * t) * sin(theta),
                            .018 - (.073 + .030 * t) * cos(theta),
                            1.644 + .018 * t + .004 * abs(sin(theta))))
    head_cowl(api, collection, m, low_detail)
    gaiter_folds(api, collection, m, low_detail)
    pane(api, collection, m)
    for side in (-1, 1):
        laminate(api, collection, f"Helmet - angular blast brow {side}", BROW,
                 (.067, -.137, 1.813), (m["armor"], m["armor"]), bevels, side,
                 thickness=.008)
        laminate(api, collection, f"Helmet - folded jaw plate {side}", CHEEK,
                 (.078, -.176, 1.692), (m["face"], m["lip"]), bevels, side,
                 thickness=.018)
        pod(api, collection, m, side, bevels, low_detail)
        jaw_vents(api, collection, m, side, bevels, low_detail)
        fasteners = ((.046, -.166, 1.694), (.080, -.1705, 1.724), (.090, -.093, 1.843))
        for index, (x, y, z) in enumerate(fasteners):
            if low_detail and index > 0:
                continue
            api.spindle(collection, f"Helmet - flush armor fastener {side}/{index}",
                        (side * x, y, z), .0029, .0031, m["bolt"],
                        (side * .39, -1, .24), 8, .00045, bevel_segments=bevels)
    laminate(api, collection, "Helmet - chin bridge", (
        (-.050, -.152, 1.654), (-.016, -.175, 1.681), (.016, -.175, 1.681),
        (.050, -.152, 1.654), (.036, -.145, 1.644), (-.036, -.145, 1.644),
    ), (0, -.176, 1.658), (m["face"], m["lip"]), bevels, thickness=.019)
    laminate(api, collection, "Helmet - roof access flange", (
        (-.069, -.035, 1.868), (-.050, -.057, 1.870), (.050, -.057, 1.870),
        (.069, -.035, 1.868), (.058, .058, 1.869), (.042, .076, 1.861),
        (-.042, .076, 1.861), (-.058, .058, 1.869),
    ), (0, .009, 1.876), (m["face"], m["lip"]), bevels,
             thickness=.007, retreat=(0, 0, -1))
    rear_access_panel(api, collection, m, bevels)
    nape_hardware(api, collection, m, bevels, low_detail)
    antenna(api, collection, m, bevels, low_detail)
    api.sensor_mount(collection, m, bevels)
