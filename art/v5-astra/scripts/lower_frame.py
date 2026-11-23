"""Armored drive housings and hydraulic service lines for the EFT leg rig."""

import math

from mathutils import Vector

from legs import CALF, FOOT, OUT, THIGH, cut_box


PELVIS = {"Base HumanPelvis": 1.0}
UPPER = {"Thigh1": 1.0}
LOWER = {"Thigh2": 1.0}

BELT_LUG = (.209, .018, 1.096)
BELT_PORT = (.190, .079, 1.098)
HIP_PIN = (.299, -.0045194, .9622123)
THIGH_SPLICE = (.321, -.0220907, .7364197)
KNEE_PIN = (.322, -.0396617, .5106257)
SHIN_SPLICE = (.315, .000, .313)
ANKLE_PIN = (.334, .0558251, .0633801)


def shifted(point, x=0., y=0., z=0.):
    return Vector(point) + Vector((x, y, z))


def box(geo, a, b, width, depth, skin, door=False, vents=0, finish="gunmetal"):
    """A closed casting with a chamfered outer face and a milled access pocket."""
    a, b = Vector(a), Vector(b)
    direction = b - a
    projected = Vector((0, direction.y, direction.z))
    tangent = projected.normalized()
    cross = tangent.cross(OUT)
    half_w, half_l = width / 2, projected.length / 2
    center = (a + b) / 2
    front = depth / 2

    def project(u, v, x):
        return center + u * cross + v * tangent + (x + v * direction.x / projected.length) * OUT

    def rim(w, l, corner, x):
        return geo.add((project(u, v, x) for u, v in cut_box(w, l, corner)), [], skin, finish)

    corner = min(.012, half_w * .38, half_l * .32)
    bevel = min(.004, half_l * .20)
    base = rim(half_w - bevel, half_l - bevel, corner, -front)
    wall = rim(half_w, half_l, corner, front - bevel)
    crown = rim(half_w - bevel, half_l - bevel, corner, front)
    geo.record(tuple(base + i for i in reversed(range(8))), finish)
    if geo.lod:
        geo.join(base, wall, 8, finish)
    else:
        backing = rim(half_w, half_l, corner, -front + bevel)
        geo.join(base, backing, 8, "steel_edge")
        geo.join(backing, wall, 8, finish)
    geo.join(wall, crown, 8, "steel_edge")

    if door:
        w = half_w - .009
        l = half_l - (.022 if vents else .010)
        pocket = rim(w, l, .005, front)
        floor = rim(w - .001, l - .001, .004, front - .004)
        cover = rim(w - .003, l - .003, .004, front - .0018)
        geo.join(crown, pocket, 8, finish)
        geo.join(pocket, floor, 8, "dark")
        geo.join(floor, cover, 8, "steel_edge")
        crown = cover

    geo.record(tuple(crown + i for i in range(8)), finish)
    primary_end = len(geo.faces)
    if door:
        for u, v in ((-w + .005, -l + .009), (w - .005, l - .009)) if geo.lod else (
                (-w + .005, -l + .009), (w - .005, -l + .009),
                (-w + .005, l - .009), (w - .005, l - .009)):
            screw(geo, project(u, v, front - .0018), .0031, skin)

        if vents:
            direction_sign = -1 if tangent.z < 0 else 1
            for row in range(2 if geo.lod else vents):
                v = direction_sign * (half_l - .012 - row * .0048)

                def slot(u, dv, h):
                    return project(u, v + dv, front + .001 + h)

                low_box(geo, slot, w * .56, .0016, .002, skin, "dark")
    return primary_end


def low_box(geo, project, width, length, depth, skin, surface):
    """Compact trapezoid for vent inserts and traction blocks."""
    rectangle = ((-width, -length), (width, -length), (width, length), (-width, length))
    low = geo.add((project(u, v, -depth) for u, v in rectangle), [(3, 2, 1, 0)], skin, surface)
    high = geo.add((project(.86 * u, .78 * v, 0) for u, v in rectangle), [(0, 1, 2, 3)], skin, surface)
    geo.join(low, high, 4, surface)

def access_door(geo):
    """Outboard service lid with a forward flange and a recessed vent bank."""
    outline = ((-.051, -.071), (.031, -.071), (.044, -.058),
               (.044, .055), (.031, .071), (-.043, .071),
               (-.060, .054), (-.060, -.051))

    def project(u, v, depth):
        # Fold the projecting front edge back toward the housing core.
        fold = max(0., -.035 - u) * .42
        return (.391 - .159 * v - fold + depth,
                .017 + u - .205 * v, .205 + v)

    def profile(scale, depth):
        return geo.add((project(scale * u, scale * v, depth) for u, v in outline),
                       [], CALF, "gunmetal")

    layers = [profile(.98, -.021), profile(1., -.004), profile(.94, 0.),
              profile(.79, 0.), profile(.76, -.004), profile(.72, -.002)]
    geo.record(tuple(layers[0] + i for i in reversed(range(8))), "gunmetal")
    for start, end, finish in zip(layers, layers[1:],
                                  ("gunmetal", "steel_edge", "gunmetal", "dark", "steel_edge")):
        geo.join(start, end, 8, finish)
    # Bridge the door skin to the rectangular vent field without a cover face.
    xmin, xmax = -.036, .016
    levels = (-.026, -.018, -.014, -.006, -.002, .006, .010, .026)
    left = geo.add((project(xmin, v, -.002) for v in levels), [], CALF, "gunmetal")
    right = geo.add((project(xmax, v, -.002) for v in levels), [], CALF, "gunmetal")
    lip = [layers[-1] + i for i in range(8)]
    end = len(levels) - 1
    geo.record((lip[7], lip[0], lip[1], lip[2], right, left), "gunmetal")
    geo.record((lip[2], lip[3], *(right+i for i in reversed(range(len(levels))))), "gunmetal")
    geo.record((lip[3], lip[4], lip[5], lip[6], left+end, right+end), "gunmetal")
    geo.record((lip[6], lip[7], *(left+i for i in range(len(levels)))), "gunmetal")

    # The dark pockets have a floor and return walls below the machined lid.
    for row, (lo, hi) in enumerate(zip(levels, levels[1:])):
        field = (left+row, right+row, right+row+1, left+row+1)
        if row % 2 == 0:
            geo.record(field, "gunmetal")
        else:
            inner = ((xmin+.006, lo+.0006), (xmax-.009, lo+.0006),
                     (xmax-.009, hi-.0006), (xmin+.006, hi-.0006))
            rim = geo.add((project(u, z, -.002) for u, z in inner), [], CALF, "gunmetal")
            floor = geo.add((project(u, z, -.006) for u, z in inner), [], CALF, "dark")
            for i, first in enumerate(field):
                j = (i + 1) % 4
                geo.record((first, field[j], rim+j, rim+i), "gunmetal")
            geo.join(rim, floor, 4, "dark")
            geo.record(tuple(floor + i for i in range(4)), "dark")
    for v in ((-.039, .039) if not geo.lod else (.038,)):
        for u in (-.030, .024):
            screw(geo, project(u, v, -.0023), .0038, CALF)

def screw(geo, point, radius, skin):
    if geo.lod:
        geo.disc(shifted(point, x=.0006), OUT, radius, .0017, skin, "steel", 5)
    else:
        screw_head(geo, point, radius, skin)


def screw_head(geo, point, radius, skin):
    """Six-sided stamped head and a recessed socket."""
    rings = [
        geo.add((shifted(point, x, radius * scale * math.cos(math.tau*i/6),
                         radius * scale * math.sin(math.tau*i/6)) for i in range(6)),
                [], skin, material)
        for x, scale, material in ((0, 1., "steel"), (.0018, .8, "steel"),
                                   (.0018, .32, "steel"), (.0005, .32, "dark"))
    ]
    for first, end, material in zip(rings, rings[1:], ("steel_edge", "steel", "dark")):
        geo.join(first, end, 6, material)
    geo.record(tuple(rings[-1] + i for i in range(6)), "dark")

def wheel(geo, center, profile, skin, count):
    """Turned joint housing whose profile steps down into the rotor."""
    rings = [
        geo.add(
            (shifted(center, x, radius * math.cos(math.tau * i / count),
                     radius * math.sin(math.tau * i / count)) for i in range(count)),
            [], skin, material,
        )
        for x, radius, material in profile
    ]
    geo.record(tuple(rings[0] + i for i in reversed(range(count))), profile[0][2])
    for first, end, (_, _, material) in zip(rings, rings[1:], profile[1:]):
        geo.join(first, end, count, material, True)
    geo.record(tuple(rings[-1] + i for i in range(count)), profile[-1][2])


def actuator(geo, center, radius, driver, driven, bolt_count):
    count = 10 if geo.lod else 16
    wheel(geo, center, ((-.032, radius * .74, "gunmetal"),
                        (-.003, radius * .96, "gunmetal"),
                        (.002, radius * .82, "dark")), driven, count)
    wheel(geo, center, ((-.016, radius * .76, "dark"),
                        (-.006, radius * .91, "steel_edge"),
                        (.001, radius, "gunmetal"),
                        (.020, radius * .89, "steel_edge"),
                        (.0175, radius * .77, "dark"),
                        (.019, radius * .63, "gunmetal"),
                        (.025, radius * .25, "steel_edge")), driver, count)
    primary_end = len(geo.faces)
    bolt_count = max(4, bolt_count // 2) if geo.lod else bolt_count
    for i in range(bolt_count):
        angle = math.tau * (i + .5) / bolt_count
        screw(geo, shifted(center, .020, .735 * radius * math.cos(angle),
                           .735 * radius * math.sin(angle)), min(.0041, radius * .12), driver)
    screw(geo, shifted(center, x=.025), radius * .12, driver)
    return primary_end


def coupler(geo):
    """Compact enclosed spindle joining the two thigh castings."""
    count = 8 if geo.lod else 12
    radius = .028
    wheel(geo, THIGH_SPLICE, ((-.026, radius * .79, "gunmetal"),
                              (-.018, radius, "gunmetal"),
                              (-.004, radius * .96, "steel_edge")), LOWER, count)
    wheel(geo, THIGH_SPLICE, ((-.008, radius * .84, "gunmetal"),
                              (.004, radius, "gunmetal"),
                              (.016, radius * .86, "steel_edge"),
                              (.016, radius * .59, "dark"),
                              (.019, radius * .52, "gunmetal")), UPPER, count)
    screw(geo, shifted(THIGH_SPLICE, x=.019), .0054, UPPER)

def fitting(geo, point, toward, skin, radius):
    center = Vector(point)
    axis = (Vector(toward) - center).normalized()
    geo.disc(center - .002 * axis, axis, radius * 1.7, .012, skin, "gunmetal", 6)
    geo.disc(center + .007 * axis, axis, radius * 1.25, .009, skin, "steel_edge", 6)
    if not geo.lod:
        for distance in (.013,):
            geo.disc(center + distance * axis, axis, radius * 1.14, .003, skin, "steel", 8)


def service(geo, points, driver, driven, radius=.0055, material="yellow"):
    """Smooth, unsupported part of a hydraulic jumper between its metal sockets."""
    points = [Vector(point) for point in points]
    steps = 10 if geo.lod else 14

    def spline(t):
        n = len(points) - 1
        i = min(n - 1, int(t * n))
        u = t * n - i
        a, b = points[i], points[i + 1]
        da = (b - points[max(i - 1, 0)]) / 2
        db = (points[min(i + 2, n)] - a) / 2
        return (1 + 2*u) * (1-u)**2 * a + u * (1-u)**2 * da + u*u * (3-2*u) * b + u*u * (u-1) * db

    rings = []
    count = 5 if geo.lod else 6
    last_up = None
    for i in range(steps + 1):
        t = i / steps
        point = spline(t)
        axis = (spline(min(t + .002, 1.)) - spline(max(t - .002, 0.))).normalized()
        reference = last_up if last_up is not None else Vector((1., 0., 0.))
        orthogonal = reference - axis * axis.dot(reference)
        if orthogonal.length_squared < .001:
            orthogonal = Vector((0., 1., 0.)) - axis * axis.y
        up = orthogonal.normalized()
        last_up = up
        side = axis.cross(up)
        blend = max(0., min(1., (t - .10) / .80))
        skin = {bone: (1 - blend) * driver.get(bone, 0.) + blend * driven.get(bone, 0.)
                for bone in driver.keys() | driven.keys()}
        rings.append(geo.add((point + radius * (math.cos(math.tau * j / count) * up
                                               + math.sin(math.tau * j / count) * side)
                              for j in range(count)), [], skin, material))
    geo.record(tuple(rings[0] + i for i in reversed(range(count))), material)
    for first, end in zip(rings, rings[1:]):
        geo.join(first, end, count, material, True)
    geo.record(tuple(rings[-1] + i for i in range(count)), material)
    fitting(geo, points[0], points[1], driver, radius)
    fitting(geo, points[-1], points[-2], driven, radius)


def bracket(geo, shell, center, housing_x, skin):
    """Fit the spreader plate to the actual shell, then bridge to the drive."""
    y, z = center
    outline = cut_box(.016, .013, .004)

    def mount(u, v, h):
        x, py, pz = shell(y + u, z + v)
        return x + .004 + h, py, pz

    geo.shell(outline, mount, skin, "gunmetal", .0055, .0018)

    def bridge(u, v, h):
        x, py, pz = mount(u, v, -.001)
        blend = (h + .019) / .019
        return x + (housing_x - x) * blend, py, pz

    geo.shell(cut_box(.011, .010, .0035), bridge, skin, "gunmetal", .019, .003)
    if not geo.lod:
        screw(geo, mount(.012, .005, 0.), .003, skin)


def platform(geo):
    """Full-width load plate, with a scalloped traction edge around the boot."""
    outline = ((.160, -.133), (.177, -.176), (.203, -.193), (.254, -.193),
               (.291, -.183), (.309, -.151), (.319, -.103), (.318, -.050),
               (.300, -.002), (.289, .049), (.287, .101), (.254, .128),
               (.199, .136), (.159, .121), (.131, .087), (.136, .035),
               (.150, -.006), (.152, -.055), (.152, -.098))
    layers = ((-.041, .945, "rubber"), (-.037, 1., "rubber"),
              (-.022, 1., "gunmetal"), (-.011, 1., "steel_edge"),
              (-.008, .966, "gunmetal"))
    if geo.lod:
        layers = (layers[0], layers[2], layers[4])
    rings = [geo.add(((.220 + (x - .220) * scale, -.030 + (y + .030) * scale, z)
                     for x, y in outline), [], FOOT, finish)
             for z, scale, finish in layers]
    count = len(outline)
    geo.record(tuple(rings[0] + j for j in reversed(range(count))), "rubber")
    for a, b, (_, _, finish) in zip(rings, rings[1:], layers[1:]):
        geo.join(a, b, count, finish)
    geo.record(tuple(rings[-1] + j for j in range(count)), "gunmetal")

    for i, point in enumerate(outline):
        if i in (4, 7, 9, 11, 14, 17) or (geo.lod and i % 2):
            continue
        start, end = Vector(point), Vector(outline[(i + 1) % count])
        center = (start + end) * .5
        along = (end - start).normalized()
        cross = Vector((-along.y, along.x))

        def rib(u, v, h):
            offset = center + along * u + cross * v
            return offset.x, offset.y, -.015 + h

        low_box(geo, rib, min(.012, (end - start).length * .30), .006, .012, FOOT, "rubber")

    primary_end = len(geo.faces)
    box(geo, shifted(ANKLE_PIN, x=-.012, z=.005),
        (.310, .063, -.029), .063, .046, FOOT, True)
    box(geo, (.302, .079, .009), (.298, -.064, .002),
        .039, .027, FOOT, True)
    return primary_end


def make_frame(geo, fitting_source=None):
    """Assemble the continuous pelvic-to-outsole drive and independent service lines."""
    geo.frame_nodes = {}
    side = "L" if geo.side > 0 else "R"

    def load_path(node, builder, *args):
        start = len(geo.faces)
        primary_end = builder(geo, *args)
        geo.frame_nodes[f"{node}.{side}"] = [start, len(geo.faces)]
        if node.startswith(("thigh_", "shin_")) and builder is box:
            geo.frame_nodes[f"housing_{node}.{side}"] = [start, primary_end]
        elif node in ("hip", "knee", "ankle"):
            geo.frame_nodes[f"can_{node}.{side}"] = [start, primary_end]
        elif node == "stirrup":
            geo.frame_nodes[f"boot_platform.{side}"] = [start, primary_end]

    # Shorter terminal necks preserve joint sweep in the deep crouch.
    load_path("hip_shoe", box, BELT_LUG, shifted(HIP_PIN, x=-.013, z=.026), .058, .043, PELVIS, True)
    load_path("hip", actuator, HIP_PIN, .055, PELVIS, UPPER, 10)
    load_path("thigh_1", box, shifted(HIP_PIN, x=.007, y=-.011, z=-.025),
              shifted(THIGH_SPLICE, x=-.002, z=.018), .068, .047, UPPER, True, 4)
    load_path("thigh_splice", coupler)
    load_path("thigh_2", box, shifted(THIGH_SPLICE, x=.011, z=-.014),
              shifted(KNEE_PIN, x=.012, y=-.004, z=.028), .064, .047, LOWER, True)
    load_path("knee", actuator, KNEE_PIN, .043, LOWER, CALF, 8)
    load_path("shin_1", box, shifted(KNEE_PIN, x=-.008, y=.008, z=-.025),
              shifted(SHIN_SPLICE, x=-.004, z=.018), .065, .046, CALF, True, 4)
    load_path("shin_splice", box, shifted(SHIN_SPLICE, z=.026),
              shifted(SHIN_SPLICE, z=-.033), .058, .041, CALF, True)
    load_path("shin_2", box, shifted(SHIN_SPLICE, x=.027, z=-.017),
              shifted(ANKLE_PIN, x=.037, y=-.011, z=.018), .069, .049, CALF)
    load_path("shin_access_door", access_door)
    load_path("ankle", actuator, ANKLE_PIN, .031, CALF, FOOT, 6)
    load_path("stirrup", platform)

    mounts = getattr(fitting_source, "mounts", {})
    for part, y, z, housing_x, skin in (
            ("thigh", -.018, .825, .297, THIGH),
            ("thigh", -.018, .660, .312, THIGH),
            ("shin", .017, .394, .298, CALF),
            ("shin", .031, .180, .341, CALF)):
        if part in mounts:
            mount_z = z + .008 if z < .20 else z
            load_path(f"{part}_bracket_{round(1000*z)}", bracket,
                      mounts[part], (y, mount_z), housing_x, skin)

    service(geo, (BELT_PORT, (.239, .103, 1.117), (.285, .100, 1.091),
                  (.304, .081, 1.040), (.310, .033, 1.001)),
            PELVIS, UPPER)
    service(geo, ((.305, .015, .875), (.324, .064, .866),
                  (.335, .083, .814), (.340, .075, .765), (.324, .005, .743)),
            UPPER, LOWER, .0075, "rubber")
    service(geo, ((.338, -.007, .568), (.334, .025, .558),
                  (.353, .023, .509), (.352, .027, .457), (.317, .005, .449)),
            LOWER, CALF)
    service(geo, ((.338, -.019, .555), (.355, -.022, .551),
                  (.377, -.013, .506), (.374, .001, .457), (.313, .009, .434)),
            LOWER, CALF, .0075, "rubber")
    service(geo, ((.324, .031, .316), (.335, .075, .297),
                  (.338, .098, .237), (.325, .093, .181), (.345, .059, .154)),
            CALF, CALF, .007, "rubber")
    service(geo, ((.349, .063, .142), (.338, .105, .115),
                  (.341, .127, .070), (.312, .136, .018), (.246, .126, -.005),
                  (.182, .124, -.004)),
            CALF, FOOT)
    service(geo, ((.357, .062, .112), (.366, .082, .095),
                  (.367, .098, .054), (.339, .119, .020), (.301, .091, .015)),
            CALF, FOOT, .007, "rubber")














