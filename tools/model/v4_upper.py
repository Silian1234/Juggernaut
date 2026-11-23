"""V4 load shell, overlapping shoulder lames and articulated upper limbs."""

from collections import defaultdict
from math import radians

from mathutils import Quaternion, Vector

from v2_plates import FRONT, OCTAGON, UP, _hub
from v3_limbs import (
    _chamfered, _dorsal_patch, _fastener, _limb_axes, _material_slot,
    _panel, _piston, _radius,
)
from v3_torso import _mirrored, _slab


REAR = -FRONT
CHEST = (
    (.008, -.151, 1.445), (.058, -.149, 1.479), (.106, -.125, 1.522),
    (.164, -.092, 1.518), (.210, -.095, 1.462), (.205, -.096, 1.391),
    (.172, -.122, 1.309), (.104, -.151, 1.291), (.012, -.151, 1.314),
)
SCAPULA = (
    (.009, .151, 1.498), (.073, .154, 1.529), (.135, .144, 1.535),
    (.191, .132, 1.478), (.198, .138, 1.411), (.159, .148, 1.310),
    (.084, .152, 1.295), (.008, .149, 1.323),
)
def _profile(a, name, bone, profile, sign, axis, depth, bevel, family, crease=None):
    return _slab(a, name, bone, family, _mirrored(profile, sign), axis,
                 depth, bevel, crease)


def _tile(a, name, bone, origin, axis, width, height, depth, family,
          *, incline=UP, outline=OCTAGON, wrap=0, taper=0):
    plane = a.planar(origin, axis, incline, width, height, wrap, taper)
    return _chamfered(a, name, bone, family, plane, outline, depth)


def _wrap(a, name, bone, rows, depth, family, *, rear=False):
    """Build a waist plate across the front or back with an integral side return."""
    axis = REAR if rear else FRONT
    stops = (-1, -.78, -.43, 0, .43, .78, 1)
    # Fold the sides into the rib line on the same breaklines on every row.
    shoulders = (.061, .023, .006, 0, .006, .023, .061)
    grid = []
    for z, y, width, sweep in rows:
        grid.append([Vector((u * width, y - axis.y * offset, z + sweep * abs(u)))
                     for u, offset in zip(stops, shoulders)])
    return _skin(a, name, bone, family, grid, axis, depth, .0045)


def _shade_lame(mesh, columns, rows, ridge_row=None):
    """Blend normal directions within the pressed faces, leaving the rim sharp."""
    face_count = 2 * (columns - 1) * (rows - 1)
    normals = defaultdict(Vector)
    sectors = []
    for polygon in list(mesh.polygons)[:face_count]:
        row = polygon.index // (2 * (columns - 1))
        inside = polygon.index % 2
        eave = ridge_row is not None and row >= ridge_row
        sector = (inside, eave)
        sectors.append(sector)
        polygon.use_smooth = True
        for vertex in polygon.vertices:
            normals[sector, vertex] += polygon.normal * polygon.area

    corner_normals = [(0.0, 0.0, 0.0)] * len(mesh.loops)
    for polygon in mesh.polygons:
        for loop in polygon.loop_indices:
            if polygon.index < face_count:
                vertex = mesh.loops[loop].vertex_index
                sector = sectors[polygon.index]
                corner_normals[loop] = normals[sector, vertex].normalized()
            else:
                corner_normals[loop] = polygon.normal
    mesh.normals_split_custom_set(corner_normals)


def _skin(a, name, bone, family, grid, axis, depth, bevel, *,
          place=None, bolts=(), clearance=None, pressed=False, ridge_row=None):
    """Build a closed folded laminate with a single bevel around the silhouette."""
    columns, rows = len(grid[0]), len(grid)
    surface = [point for row in grid for point in row]
    count = len(surface)
    directions = [Vector(axis).normalized()] * count
    exterior = []
    for i, point in enumerate(surface):
        r, c = divmod(i, columns)
        inset = Vector()
        if r in (0, rows - 1):
            neighbor = surface[i + columns if r == 0 else i - columns]
            inset += (neighbor - point).normalized() * bevel
        if c in (0, columns - 1):
            neighbor = surface[i + 1 if c == 0 else i - 1]
            inset += (neighbor - point).normalized() * bevel
        exterior.append(point + directions[i] * depth + inset)

    edge = (
        list(range(columns))
        + [r * columns + columns - 1 for r in range(1, rows)]
        + [(rows - 1) * columns + c for c in reversed(range(columns - 1))]
        + [r * columns for r in reversed(range(1, rows - 1))]
    )
    backing = surface
    if clearance:
        backing = [point + direction * clearance(point)
                   for point, direction in zip(surface, directions)]
    vertices = backing + exterior + [
        surface[i] + directions[i] * (depth - bevel) for i in edge
    ]
    uv = [(i % columns / (columns - 1), 1 - i // columns / (rows - 1))
          for i in range(count)]
    uv = uv + uv + [uv[i] for i in edge]
    faces = []
    for r in range(rows - 1):
        for c in range(columns - 1):
            i = r * columns + c
            quad = (i, i + 1, i + columns + 1, i + columns)
            faces.append(tuple(reversed(quad)))
            faces.append(tuple(count + j for j in quad))
    bevel_faces = []
    for j, i in enumerate(edge):
        k = (j + 1) % len(edge)
        other = edge[k]
        band, next_band = 2 * count + j, 2 * count + k
        faces.append((i, other, next_band, band))
        bevel_faces.append(len(faces))
        faces.append((band, next_band, count + other, count + i))
    if (surface[1] - surface[0]).cross(surface[columns] - surface[0]).dot(axis) < 0:
        faces = [tuple(reversed(face)) for face in faces]

    obj = a.mesh(name, bone, family,
                 [place(point) for point in vertices] if place else vertices,
                 faces, uv, smooth=False)
    if pressed:
        _shade_lame(obj.data, columns, rows, ridge_row)
    edge_slot = _material_slot(obj, "edge" if family == "olive" else "edge_dark")
    for index in bevel_faces:
        obj.data.polygons[index].material_index = edge_slot
    for k, (r, c) in enumerate(bolts):
        i = r * columns + c
        corners = [exterior[j] for j in (i, i + 1, i + columns + 1, i + columns)]
        point = (corners[0].lerp(corners[1], .57) + corners[3].lerp(corners[2], .57)) * .5
        normal = (corners[1] - corners[0]).cross(corners[3] - corners[0]).normalized()
        if normal.dot(axis) < 0:
            normal.negate()
        if place:
            anchor = place(point)
            normal = (place(point + normal) - anchor).normalized()
        else:
            anchor = point
        _fastener(a, f"{name}Rivet{k}", bone, anchor, normal, .0057)
    return obj


def _gorget(a):
    # One drawn throat plate with a low center and raised curved corner returns.
    front = [
        [(-.126, -.051, 1.617), (-.109, -.110, 1.621), (-.061, -.153, 1.604),
         (0, -.169, 1.582), (.061, -.153, 1.604), (.109, -.110, 1.621),
         (.126, -.051, 1.617)],
        [(-.128, -.064, 1.590), (-.104, -.122, 1.594), (-.056, -.149, 1.575),
         (0, -.162, 1.553), (.056, -.149, 1.575), (.104, -.122, 1.594),
         (.128, -.064, 1.590)],
        [(-.139, -.075, 1.551), (-.107, -.106, 1.540), (-.059, -.120, 1.521),
         (0, -.138, 1.504), (.059, -.120, 1.521), (.107, -.106, 1.540),
         (.139, -.075, 1.551)],
    ]
    _skin(a, "FrontGorget", "Spine3", "graphite",
          [[Vector(point) for point in row] for row in front],
          Vector((0, -.97, .18)), .013, .003)
    # The left skirt sits lower and farther out through the RAC boom's sweep.
    def mic_relief(point):
        lateral = .015 * max(.10, min(1, (point.y + .080) / .070))
        drop = .030 * max(.35, min(1, (point.y + .105) / .080))
        return point + Vector((lateral, 0, -drop))

    for side, sign in (("L", 1), ("R", -1)):
        side_grid = [
            [(.124, -.061, 1.619), (.121, -.014, 1.629),
             (.113, .040, 1.623), (.093, .094, 1.603)],
            [(.123, -.073, 1.589), (.120, -.018, 1.604),
             (.113, .049, 1.602), (.096, .105, 1.584)],
            [(.128, -.078, 1.558), (.125, -.014, 1.570),
             (.120, .053, 1.570), (.099, .109, 1.559)],
        ]
        _skin(a, "SideGorgetCheek" + side, "Spine3", "graphite",
              [[Vector((sign * x, y, z)) for x, y, z in row] for row in side_grid],
              Vector((sign * .98, 0, .17)), .010, .003,
              place=mic_relief if side == "L" else None)
    _tile(a, "RearGorget", "Spine3", (0, .130, 1.558), (0, .95, .31),
          .094, .046, .021, "graphite", wrap=.018, taper=-.16)


def _abdominal_latches(a):
    # Each chevron rides on a wider articulation liner. Small offset latch
    # tongues distinguish the tiers without obscuring the abdominal bend.
    for i, (hi, y, width, bone) in enumerate((
        (1.210, -.173, .127, "Spine2"),
        (1.177, -.171, .122, "Spine1"),
        (1.145, -.165, .113, "Spine1"),
    )):
        _wrap(a, f"AbdomenChevron{i}", bone, (
            (hi, y + .007, width * .90, .019),
            (hi - .008, y, width, .022),
            (hi - .023, y - .002, width * .97, .022),
            (hi - .029, y + .002, width * .81, .018),
        ), .011, "graphite")
        for side, sign in (("L", 1), ("R", -1)):
            origin = (width * sign * .66, y + .002, hi - .006)
            axis = Vector((sign * .32, -.95, .02))
            incline = Vector((sign * -.18, 0, 1))
            _tile(a, f"AbdomenLatch{side}{i}", bone, origin, axis,
                  .016, .007, .004, "edge_dark", incline=incline)


def torso(a):
    """Broad chest and back shells with a separate lower armor stack."""
    for side, sign in (("L", 1), ("R", -1)):
        _profile(a, "ChestCasting" + side, "Spine3", CHEST, sign, FRONT,
                 .026, .006, "graphite", (3, 8))
        _profile(a, "ScapularCasting" + side, "Spine3", SCAPULA, sign, REAR,
                 .025, .005, "graphite", (2, 6))

        side_axis = Vector((sign * .97, -.25, 0)).normalized()
        for i, (x, z, span, length, bone) in enumerate((
            (.163, 1.402, .090, .044, "Spine3"),
            (.149, 1.322, .089, .044, "Spine3"),
            (.145, 1.247, .100, .043, "Spine2"),
            (.143, 1.181, .090, .041, "Spine2"),
        )):
            origin = (sign * x, -.003, z)
            _tile(a, f"RibReturn{side}{i}", bone, origin, side_axis,
                  span, length, .015, "graphite", wrap=.009, taper=.12)

        bridge_axis = Vector((sign * .25, .04, .97)).normalized()
        _tile(a, "GorgetShoulderSaddle" + side, "Spine3", (sign * .137, .018, 1.538),
              bridge_axis, .052, .094, .026, "graphite", incline=FRONT, wrap=.008)
        for i, (y, z) in enumerate(((-.102, 1.499), (.096, 1.505))):
            pin_axis = FRONT if y < 0 else REAR
            deck = (sign * .171, y + pin_axis.y * .018, z)
            _tile(a, f"BridgeLug{side}{i}", "Spine3", deck, pin_axis,
                  .025, .018, .013, "steel")
            _fastener(a, f"BridgePin{side}{i}", "Spine3",
                      Vector(deck) + pin_axis * .013, pin_axis, .008)

        thigh = side + "Thigh1"
        hip = ((.059, -.139, 1.044), (.129, -.104, 1.060), (.170, -.079, 1.035),
               (.204, -.085, .949), (.179, -.118, .910), (.119, -.156, .912),
               (.092, -.155, .957))
        _profile(a, "HipApronFront" + side, thigh, hip, sign, FRONT,
                 .026, .006, "graphite", (1, 4))
        _profile(a, "HipApronRear" + side, thigh,
                 [(x, -y * .90, z) for x, y, z in hip], sign, REAR,
                 .023, .005, "graphite", (1, 4))
        _tile(a, "BeltEndCasting" + side, "Pelvis", (sign * .151, .011, 1.083),
              (sign, 0, 0), .094, .026, .021, "graphite", wrap=.025)
        for i, y in enumerate((-.066, .047)):
            _tile(a, f"BeltAnchor{side}{i}", "Pelvis", (sign * .163, y, 1.087),
                  side_axis, .015, .015, .008, "steel")

    _wrap(a, "SternumLiner", "Spine3", (
        (1.477, -.145, .118, .008), (1.427, -.159, .171, .010),
        (1.356, -.160, .168, .002), (1.289, -.154, .158, -.004),
    ), .014, "graphite")
    _wrap(a, "UpperAbdomen", "Spine2", (
        (1.323, -.153, .147, .024), (1.296, -.161, .164, .021),
        (1.232, -.156, .153, .019), (1.211, -.153, .129, .020),
    ), .021, "graphite")
    _wrap(a, "MiddleAbdomen", "Spine2", (
        (1.240, -.148, .138, .016), (1.221, -.151, .151, .019),
        (1.175, -.153, .135, .017), (1.155, -.147, .111, .019),
    ), .019, "graphite")
    _wrap(a, "LowerAbdomen", "Spine1", (
        (1.180, -.142, .125, .009), (1.151, -.146, .146, .016),
        (1.111, -.146, .139, .015), (1.085, -.140, .112, .020),
    ), .019, "graphite")
    _wrap(a, "BeltFrontCasting", "Pelvis", (
        (1.089, -.147, .177, .014), (1.075, -.152, .178, .013),
        (1.065, -.150, .177, .003), (1.057, -.139, .158, -.003),
    ), .022, "graphite")
    _wrap(a, "BeltRearCasting", "Pelvis", (
        (1.101, .136, .176, .006), (1.081, .144, .170, .006),
        (1.058, .144, .170, .011), (1.044, .134, .158, .018),
    ), .018, "graphite", rear=True)
    for i, (lo, hi, bone) in enumerate((
        (1.268, 1.373, "Spine3"), (1.197, 1.277, "Spine2"),
        (1.125, 1.207, "Spine2"), (1.077, 1.133, "Spine1"),
    )):
        _wrap(a, f"PosteriorLoadLame{i}", bone, (
            (hi, .134, .138, .028), (hi - .025, .146, .171, .012),
            (lo + .015, .143, .163, .012), (lo, .141, .131, .010),
        ), .021, "graphite", rear=True)

    _gorget(a)
    _abdominal_latches(a)
    _tile(a, "BeltLock", "Pelvis", (0, -.172, 1.074), FRONT,
          .042, .015, .010, "graphite")
    _tile(a, "BeltLockFace", "Pelvis", (0, -.181, 1.074), FRONT,
          .029, .009, .004, "edge_dark")
    groin = [(-.071, -.123, 1.053), (.071, -.123, 1.053),
             (.078, -.130, 1.011), (.053, -.147, .939), (.031, -.147, .899),
             (-.031, -.147, .899), (-.053, -.147, .939), (-.078, -.130, 1.011)]
    _slab(a, "GroinFoundation", "Pelvis", "graphite", groin, FRONT, .023, .005)
    shield = [(-.047, -.147, 1.027), (.047, -.147, 1.027),
              (.061, -.145, 1.010), (.035, -.168, .910), (.024, -.165, .890),
              (-.024, -.165, .890), (-.035, -.168, .910), (-.061, -.145, 1.010)]
    _slab(a, "GroinShield", "Pelvis", "graphite", shield, FRONT, .018, .005)
    for i, x in enumerate((-.036, .036)):
        _fastener(a, f"GroinPin{i}", "Pelvis", Vector((x, -.166, 1.014)), FRONT, .0064)


def _shoulder(a, side, sign, bone, shoulder, elbow):
    # Shape the overlapping lames in the neutral presentation pose, then return
    # them to the native reference bind coordinates using the same rotation.
    down = Vector((0, 0, -1))
    swing = Quaternion((elbow - shoulder).cross(down).normalized(), radians(36))
    sweep = Quaternion(Vector((1, 0, 0)), radians(23))
    inverse = (sweep @ swing).inverted()

    def place(point):
        return shoulder + inverse @ (point - shoulder)

    def fit_left_roof(point):
        position = place(point)
        relief = max(0, min(1, (.283 - position.x) / .075))
        return position + Vector((.030, 0, -.020)) * relief


    # Row fields give crown projection, height, fore/aft span and the fall at
    # either edge. These are die breaklines, including the cropped ends.
    profiles = (
        ("ShoulderLowerLame", (
            (.261, 1.459, .114, .056), (.307, 1.458, .138, .065),
            (.374, 1.422, .144, .080), (.396, 1.386, .113, .072),
        ), .028, Vector((sign * .90, 0, .43)), "graphite"),
        ("ShoulderMiddleLame", (
            (.225, 1.495, .113, .042), (.270, 1.497, .143, .053),
            (.359, 1.469, .151, .076), (.399, 1.426, .118, .067),
        ), .031, Vector((sign * .79, 0, .61)), "graphite"),
        ("ShoulderRoof", (
            (.151, 1.548, .092, .031), (.197, 1.562, .117, .039),
            (.289, 1.544, .152, .074), (.364, 1.510, .137, .081),
            (.386, 1.481, .109, .064),
        ), .033, Vector((sign * .46, 0, .89)), "graphite"),
    )
    steps = (-1, -.57, 0, .57, 1) if a.lod else (-1, -.74, -.42, 0, .42, .74, 1)
    for name, profile, thickness, axis, family in profiles:
        grid = [
            [Vector((sign * (x - .040 * abs(u) ** 1.65),
                     .018 + length * u, z - fall * abs(u) ** 1.4))
             for u in steps] for x, z, length, fall in profile
        ]
        bolts = ((1, 0), (1, len(steps) - 2),
                 (len(profile) - 2, 0), (len(profile) - 2, len(steps) - 2))
        def interior_clearance(point):
            front = max(0, 1 - abs(point.y + .043) / .117)
            flare = max(0, min(1, (abs(point.x) - .260) / .113))
            return min(.020, thickness - .009) * front * flare
        mapper = fit_left_roof if side == "L" and name == "ShoulderRoof" else place
        _skin(a, name + side, bone, family, grid, axis, thickness, .007,
              place=mapper, bolts=bolts,
              clearance=interior_clearance if name != "ShoulderRoof" else None,
              pressed=True, ridge_row=3 if name == "ShoulderRoof" else None)

    for i, (y, axis) in enumerate(((-.081, FRONT), (.126, REAR))):
        origin = place(Vector((sign * .204, y, 1.505)))
        if side == "L" and i == 0:
            origin += Vector((.020, 0, -.015))
        direction = inverse @ axis
        _tile(a, f"ShoulderMount{side}{i}", bone, origin, direction, .039, .034,
              .024, "graphite", incline=inverse @ UP)
        _hub(a, f"ShoulderMountPivot{side}{i}", bone, origin + direction * .018,
             direction, .021)

def arm(a, side):
    """Bind each end of the armor stack to its native EFT arm segment."""
    sign = 1 if side == "L" else -1

    def head(part):
        return a.head(side + part)

    shoulder, elbow, wrist, palm = (head(name) for name in (
        "Upperarm", "Forearm1", "Palm", "Digit31"
    ))
    upper, lower, hand = side + "Upperarm", side + "Forearm1", side + "Palm"
    outer = Vector((sign, .08, .37))
    dorsal = Vector((sign, -.19, .73))
    _shoulder(a, side, sign, upper, shoulder, elbow)

    _panel(a, "UpperArmBicepsArmor" + side, upper, "graphite",
           shoulder, elbow, (sign * .63, -1, .09),
           ((.29, -4 * sign, 21, .111), (.39, 0, 30, .112),
            (.60, 5 * sign, 32, .103), (.71, 10 * sign, 18, .098)),
           .022, fit=.029, anchors=((1, 1), (1, -2)))
    _panel(a, "UpperArmTricepsArmor" + side, upper, "graphite",
           shoulder, elbow, (sign * .25, .97, -.23),
           ((.25, -7 * sign, 21, .119), (.39, -7 * sign, 27, .116),
            (.51, -5 * sign, 25, .107), (.602, 2 * sign, 15, .102)),
           .022, fit=.029, anchors=((1, 1), (1, -2)))
    _panel(a, "UpperArmWebCinch" + side, upper, "graphite", shoulder, elbow, outer,
           ((.717, 0, 83, .104), (.751, 0, 89, .105), (.807, 0, 82, .103)),
           .012, fit=.024)

    pad_axis = Vector((sign * .65, .75, -.47))
    _panel(a, "ElbowCup" + side, lower, "graphite", elbow, wrist, pad_axis,
           ((-.195, 0, 20, .109), (-.108, 0, 37, .109),
            (.065, 0, 39, .100), (.170, 0, 22, .094)),
           .021, fit=.030, anchors=((1, 1), (1, -2)))
    axis = _limb_axes(elbow, wrist, (sign, .42, .09))[2]
    pivot = elbow + axis * _radius(a, elbow, axis, .112, .033)
    _hub(a, "ElbowDrive" + side, lower, pivot, axis, .039)
    _tile(a, "ElbowYoke" + side, upper, pivot - axis * .016, axis,
          .032, .046, .017, "steel", incline=shoulder - elbow)
    lug = shoulder.lerp(elbow, .68) + axis * .109
    _piston(a, "ElbowLink" + side, upper, lug, pivot - axis * .012, .010)
    _fastener(a, "ElbowPivotCenter" + side, lower, pivot + axis * .022, axis, .012)

    _panel(a, "VambraceProximalCuff" + side, lower, "graphite", elbow, wrist, dorsal,
           ((.088, -3 * sign, 35, .106), (.16, -2 * sign, 64, .113),
            (.306, 9 * sign, 62, .109), (.385, 11 * sign, 49, .105)),
           .026, fit=.028, anchors=((1, 1), (1, -2)))
    _panel(a, "VambraceCentralOuter" + side, lower, "graphite", elbow, wrist, dorsal,
           ((.285, 38 * sign, 21, .103), (.39, 38 * sign, 35, .102),
            (.619, 40 * sign, 31, .095), (.839, 43 * sign, 20, .083)),
           .026, fit=.028, anchors=((1, 1), (2, -2)))
    _panel(a, "VambraceCentralForward" + side, lower, "graphite", elbow, wrist, dorsal,
           ((.282, -34 * sign, 21, .104), (.393, -33 * sign, 27, .102),
            (.603, -30 * sign, 27, .094), (.803, -28 * sign, 21, .085)),
           .026, fit=.028, anchors=((1, 1), (2, -2)))
    _panel(a, "VambraceSpineSeal" + side, lower, "graphite", elbow, wrist, dorsal,
           ((.340, 2 * sign, 14, .103), (.506, 2 * sign, 16, .096),
            (.738, 4 * sign, 14, .088), (.827, 5 * sign, 12, .079)),
           .009, fit=.027)
    _panel(a, "VambraceCounterplate" + side, lower, "graphite", elbow, wrist, -dorsal,
           ((.205, 1 * sign, 22, .090), (.319, 2 * sign, 61, .086),
            (.621, 3 * sign, 59, .071), (.849, 3 * sign, 51, .059)),
           .015, fit=.027, anchors=((1, 1), (2, -2)))
    _panel(a, "VambraceDistalClamp" + side, lower, "graphite", elbow, wrist, dorsal,
           ((.719, 3 * sign, 58, .094), (.767, 4 * sign, 65, .086),
            (.856, 7 * sign, 58, .077), (.894, 7 * sign, 46, .074)),
           .018, fit=.026, anchors=((1, 1), (1, -2)))
    _panel(a, "WristSeal" + side, side + "Forearm3", "graphite", elbow, wrist, outer,
           ((.900, 0, 74, .067), (.929, 0, 79, .070), (1.003, 0, 72, .060)),
           .009, fit=.024)

    _dorsal_patch(a, "DorsalPalmArmor" + side, hand, wrist, palm, dorsal,
                  .044, .043, .040, .012)
    _dorsal_patch(a, "KnuckleBar" + side, hand, wrist.lerp(palm, .58), palm, dorsal,
                  .046, .015, .044, .015)
    for digit in range(1, 6):
        for joint in range(1, 3):
            first, second = f"Digit{digit}{joint}", f"Digit{digit}{joint + 1}"
            start, end = head(first), head(second)
            span = (end - start).length
            width = (.0115 if digit in (1, 2, 3) else .0093) - .0015 * (joint - 1)
            _dorsal_patch(a, f"FingerGuard{side}{digit}{joint}", side + first,
                          start, end, dorsal, width, span * .45,
                          width + (.004 if joint == 1 else .002), .007)






