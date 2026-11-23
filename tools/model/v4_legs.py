"""Articulated load frame, overlapping lower armor, and split combat boots."""
import math

from mathutils import Vector

from v2_plates import FRONT, OCTAGON, UP, _bvh
from v3_limbs import _chamfered, _limb_axes, _material_slot, _panel


SHOE = ((-.83, -1), (.68, -1), (.94, -.70), (1, -.27),
        (.91, .71), (.67, 1), (-.67, 1), (-.92, .70),
        (-1, -.36), (-.98, -.67))


def _lugs(a, name, bone, point, normal, up, width, height, family, depth):
    plane = a.planar(point, normal, up, width, height)
    return _chamfered(a, name, bone, family, plane, OCTAGON, depth)


def _fastener(a, name, bone, point, axis, radius):
    if not a.lod:
        a.turning(name, bone, "steel", point, axis,
                  ((radius, -.0015), (radius * .69, .0035)), sides=6)


def _rail(a, name, bone, axis, path, family="graphite", depth=.019):
    """A continuous chamfered spar with changing section at each dogleg."""
    vertices, uv, faces = [], [], []
    section = ((-.73, -.5), (.73, -.5), (1, -.23), (1, .23),
               (.73, .5), (-.73, .5), (-1, .23), (-1, -.23))
    count = len(section)
    for index, (point, width) in enumerate(path):
        tangent = path[min(index + 1, len(path) - 1)][0] - path[max(0, index - 1)][0]
        tangent.normalize()
        across = axis.cross(tangent).normalized()
        normal = tangent.cross(across)
        for cross, outward in section:
            vertices.append(point + across * (cross * width) + normal * (outward * depth))
            uv.append(((cross + 1) * .5, index / (len(path) - 1)))
        if index:
            a._join(faces, (index - 1) * count, index * count, count)
    faces.extend((tuple(reversed(range(count))), tuple(range(len(vertices) - count, len(vertices)))))
    obj = a.mesh(name, bone, family, vertices, faces, uv, smooth=False)
    if family == "graphite":
        edge = _material_slot(obj, "edge_dark")
        for polygon in list(obj.data.polygons)[:-2]:
            if polygon.index % count in (3, 5):
                polygon.material_index = edge
    return obj


def _hub(a, name, bone, point, axis, radius, torque_mark=False):
    sides = 10 if a.lod else 20
    a.turning(name + "Housing", bone, "graphite", point, axis,
              ((radius * .83, -.022), (radius, -.015), (radius, .003),
               (radius * .93, .009)), sides=sides)
    a.turning(name + "Bearing", bone, "steel", point, axis,
              ((radius * .83, .006), (radius * .87, .010),
               (radius * .87, .014), (radius * .81, .017)), sides=sides)
    a.turning(name + "AxlePlate", bone, "graphite", point, axis,
              ((radius * .73, .016), (radius * .76, .020),
               (radius * .69, .024)), sides=sides)
    a.turning(name + "AxleHex", bone, "steel", point, axis,
              ((radius * .25, .024), (radius * .26, .028),
               (radius * .19, .033)), sides=6)
    if a.lod:
        return
    tangent = UP.cross(axis)
    for index in range(6 if torque_mark else 4):
        angle = math.tau * index / (6 if torque_mark else 4)
        bolt = point + axis * .023 + radius * .59 * (UP * math.sin(angle) + tangent * math.cos(angle))
        _fastener(a, f"{name}CoverBolt{index}", bone, bolt, axis, .0045)
    if torque_mark:
        # A flush angled witness stripe is clear of the axle fastener.
        direction = (UP + tangent * .80).normalized()
        center = point + axis * .024 + (UP * .018 - tangent * .013)
        _lugs(a, name + "Witness", bone, center, axis, direction,
              .0041, .018, "tan", .0015)


def _clevis(a, name, bone, center, pin, direction, width):
    for flank in (-1, 1):
        point = center + pin * (flank * width)
        _lugs(a, f"{name}Ear{flank}", bone, point, pin * flank, direction,
              width * 1.01, width * 1.33, "graphite", .006)
    a.turning(name + "Pin", bone, "steel", center, pin,
              ((width * .44, -width - .007), (width * .44, width + .008),
               (width * .36, width + .011)), sides=8 if a.lod else 12)


def _piston(a, name, bone, start, end, pin, radius):
    axis = (end - start).normalized()
    length = (end - start).length
    sides = 8 if a.lod else 14
    a.turning(name + "Barrel", bone, "black", start, axis,
              ((radius * .71, .008), (radius, .018),
               (radius, length * .59), (radius * .87, length * .65)), sides=sides)
    a.turning(name + "SealNut", bone, "steel", start, axis,
              ((radius * .98, length * .59), (radius * 1.04, length * .61),
               (radius * 1.04, length * .66), (radius * .74, length * .68)),
              sides=8 if a.lod else 12)
    a.turning(name + "ChromeRod", bone, "steel", start, axis,
              ((radius * .43, length * .66), (radius * .43, length - .012),
               (radius * .63, length - .007), (radius * .63, length)), sides=sides)
    _clevis(a, name + "Head", bone, start, pin, axis, radius * .81)
    _clevis(a, name + "RodEnd", bone, end, pin, axis, radius * .72)


def _hose(a, name, bone, axis, control, radius):
    steps, sides = (8, 6) if a.lod else (13, 10)
    start, p, q, end = control
    vertices, uv, faces = [], [], []
    for index in range(steps + 1):
        t = index / steps
        s = 1 - t
        center = s**3 * start + 3*s*s*t * p + 3*s*t*t * q + t**3 * end
        tangent = (s*s * (p - start) + 2*s*t * (q - p) + t*t * (end - q)).normalized()
        across = axis.cross(tangent).normalized()
        normal = tangent.cross(across)
        for side in range(sides):
            angle = math.tau * side / sides
            vertices.append(center + radius * (across * math.cos(angle) + normal * math.sin(angle)))
            uv.append((side / sides, t))
        if index:
            a._join(faces, (index - 1) * sides, index * sides, sides)
    faces.extend((tuple(reversed(range(sides))), tuple(range(len(vertices) - sides, len(vertices)))))
    a.mesh(name, bone, "rubber", vertices, faces, uv)
    for index, (point, direction) in enumerate(((start, p - start), (end, q - end))):
        a.turning(f"{name}Union{index}", bone, "steel", point, direction,
                  ((radius * 1.9, -.006), (radius * 1.9, .004),
                   (radius * 1.36, .010)), sides=8 if a.lod else 12)


def _band(a, name, bone, start, end, fraction, width, nominal, sign):
    up, right, front = _limb_axes(start, end, (sign, 0, 0))
    center = start.lerp(end, fraction)
    count = 18 if a.lod else 32
    vertices, faces, uv = [], [], []
    buckle = None
    for row, (depth, height) in enumerate(((0, -.5), (.005, -.5), (.005, .5), (0, .5))):
        for index in range(count):
            angle = math.tau * index / count
            axis = front * math.cos(angle) + right * math.sin(angle)
            probe = center + axis * (nominal + .048)
            hit, _, _, _ = a.surface.ray_cast(probe, -axis, .092)
            radius = nominal if hit is None else max(nominal - .018, (hit - center).dot(axis) + .006)
            # Keep paired medial webbing clear of the centerline in the bind pose.
            point = center + axis * (radius + depth) + up * (height * width)
            point.x = sign * max(sign * point.x, .012 + depth)
            vertices.append(point)
            uv.append(((.03, 0, 1, .97)[row], index / count))
            if row == 1 and index == round(count * (.17 if sign > 0 else .83)):
                buckle = (center + axis * (radius + .003), axis)
        if row:
            a._join(faces, (row - 1) * count, row * count, count)
    a._join(faces, 3 * count, 0, count)
    band = a.mesh(name, bone, "tan", vertices, faces, uv, smooth=False)
    band["v2_swatch_uv"] = True
    layer = band.data.uv_layers.active
    for polygon in list(band.data.polygons)[count - 1::count]:
        for index in polygon.loop_indices:
            if layer.data[index].uv.y == 0:
                layer.data[index].uv.y = 1
    point, axis = buckle
    _lugs(a, name + "Lock", bone, point, axis, up, .021, width * .53, "graphite", .009)
    _lugs(a, name + "Release", bone, point + axis * .008, axis, up,
          .009, width * .36, "steel", .005)
    if not a.lod:
        _fastener(a, name + "BuckleRivet", bone, point + axis * .009 + up.cross(axis) * .014, axis, .0037)


def _boot_bottom(a, name, bone, center, halfspan_y, z, family, height, width):
    plane = a.planar(Vector((center.x, center.y, z)), UP, Vector((0, 1, 0)), width, halfspan_y)
    _chamfered(a, name, bone, family, plane, SHOE, height, edge=family == "graphite")


def _boot(a, side, lateral, ankle, toe, clevis_center):
    foot, tip = side + "Foot", side + "Toe"
    forward = FRONT
    rear = Vector((toe.x, .019, 0))
    fore = Vector((toe.x, -.149, 0))
    for name, bone, center, span, width in (
        ("Heel", foot, rear, .112, .091), ("Toe", tip, fore, .057, .094),
    ):
        _boot_bottom(a, name + "Outsole" + side, bone, center, span, -.015, "rubber", .034, width)
        _boot_bottom(a, name + "Midsole" + side, bone, center, span, .011, "graphite", .020, width)
        if not a.lod:
            stations = (-.64, .12, .64) if bone == foot else (-.57, .17, .58)
            for number, station in enumerate(stations):
                for flank in (-1, 1):
                    position = Vector((center.x + flank * width * .86, center.y + span * station, -.021))
                    longitudinal = Vector((flank * .27, 1, 0))
                    _lugs(a, f"{name}Tread{side}{number}{flank}", bone, position, UP, longitudinal,
                          .013, .014, "black", .031)
                position = Vector((center.x, center.y + span * station, -.020))
                _lugs(a, f"{name}Chevron{side}{number}", bone, position, UP,
                      Vector((.55 if number % 2 else -.55, 1, 0)),
                      .034, .013, "black", .012)

    for flank in (-1, 1):
        normal = lateral * flank + UP * .14
        point = rear + lateral * (flank * .066) + UP * .064
        plane = a.planar(point, normal, UP, .104, .049)
        outline = ((-.72, -.96), (.75, -.96), (1, -.50), (.90, .26),
                   (.61, .82), (.22, 1), (-.51, .92), (-.88, .55), (-1, -.36))
        _chamfered(a, f"BootQuarter{side}{flank}", foot, "graphite", plane, outline, .023)
        _lugs(a, f"BootHeelRail{side}{flank}", foot, point + normal * .020 - UP * .017,
              normal, UP, .078, .013, "olive", .012)
    _lugs(a, "BootHeelCounter" + side, foot, rear + Vector((0, .095, .062)),
          (0, 1, .17), UP, .068, .041, "olive", .024)
    _lugs(a, "BootAnkleTongue" + side, foot, (toe.x, -.040, .105),
          (0, -.45, 1), UP, .067, .040, "graphite", .023)
    for number, (y, z, width, length) in enumerate(((-.114, .075, .071, .021),
                                                     (-.144, .073, .082, .032),
                                                     (-.181, .054, .070, .021))):
        normal = Vector((0, -.27 if number < 2 else -.68, 1)).normalized()
        point = Vector((toe.x, y, z))
        _chamfered(a, f"BootToeArmor{side}{number}", tip, "olive",
                   a.planar(point, normal, UP, width, length, wrap=.014),
                   OCTAGON, .020 if number < 2 else .017)
        for flank in (-1, 1):
            _fastener(a, f"ToeRivet{side}{number}{flank}", tip,
                      point + Vector((flank * width * .62, 0, 0)) + normal * .014, normal, .005)
    bumper = a.planar((toe.x, -.194, .034), forward, UP, .083, .019, wrap=.019)
    _chamfered(a, "BootToeBumper" + side, tip, "graphite", bumper,
               ((-.68, -1), (.68, -1), (1, -.30), (.82, .34), (.51, 1),
                (-.51, 1), (-.82, .34), (-1, -.30)), .018)
    if not a.lod:
        _lugs(a, "ToeImpactRidge" + side, tip, (toe.x, -.159, .086),
              (0, -.38, 1), UP, .036, .019, "graphite", .009)

    # Both branches belong to Foot and meet over the instep. The drive end is Calf
    # weighted and meets the outer branch concentrically at the native Foot joint.
    for flank in (-1, 1):
        path = [
            (Vector((toe.x, .070, .037)) + lateral * (flank * .074), .020),
            ((clevis_center if flank > 0 else ankle - lateral * .063) -
             lateral * (flank * .006), .028),
            (Vector((toe.x, .001, .087)) + lateral * (flank * .077), .023),
            (Vector((toe.x, -.031, .112)) + lateral * (flank * .052), .017),
        ]
        _rail(a, f"StirrupSide{side}{flank}", foot, lateral * flank, path, depth=.025)
        _fastener(a, f"StirrupMidlug{side}{flank}", foot,
                  path[2][0] + lateral * (flank * .012), lateral * flank, .010)
    _lugs(a, "StirrupBridge" + side, foot, (toe.x, -.031, .112),
          (0, -.28, 1), UP, .056, .017, "graphite", .016)


def _access(a, name, bone, target, center, normal, width, height, face="olive"):
    """Inset backing and removable cover fitted against the shell's breaklines."""
    if a.lod:
        return
    plane = a.planar(center, normal, UP, width, height)
    surface = _bvh((target,))

    def point(u, v, depth):
        probe = plane(u, v, 0)
        hit, _, _, _ = surface.ray_cast(probe + normal * .15, -normal, .30)
        if hit is None:
            raise ValueError(f"{name} exceeds its shell")
        return hit + normal * (depth - .001)

    cover_shape = ((-.80, -.79), (.32, -.79), (.69, -.46), (.79, .42),
                   (.53, .74), (-.54, .74), (-.82, .33), (-.82, -.43))

    def insert(suffix, family, outline, depth):
        # Trace the plate breaklines through the center of each cap as well as its rim.
        vertices, uv, faces = [], [], []
        count = len(outline)
        for row, (scale, offset) in enumerate(((.96, 0), (1, .003), (.91, .006))):
            for u, v in outline:
                vertices.append(point(u * scale, v * scale, depth + offset))
                uv.append((.5 + u * .46, .5 + v * .46))
            if row:
                a._join(faces, (row - 1) * count, row * count, count)
        rear, front = len(vertices), len(vertices) + 1
        vertices.extend((point(0, 0, depth), point(0, 0, depth + .006)))
        uv.extend(((.5, .5), (.5, .5)))
        for index in range(count):
            neighbor = (index + 1) % count
            faces.append((neighbor, index, rear))
            faces.append((2 * count + index, 2 * count + neighbor, front))
        a.mesh(name + suffix, bone, family, vertices, faces, uv, smooth=False)

    insert("Seat", "black", OCTAGON, 0)
    cover_depth = .009 if face == "olive" else .005
    insert("Cover", face, cover_shape, cover_depth)
    for index, v in enumerate((-.24, .28)):
        if face == "olive":
            u_pos, v_pos = -.03, v
            halfwidth, halfheight = width * .53, .0021
        else:
            u_pos, v_pos = v, -.01
            halfwidth, halfheight = .0019, height * (.53 if index == 0 else .38)
        seam = a.planar(point(u_pos, v_pos, cover_depth + .006), normal, UP, halfwidth, halfheight)
        outline = ((-1, -.68), (.64, -1), (1, .61), (-.69, 1))
        _chamfered(a, f"{name}Seam{index}", bone, "black", seam, outline, .002)
    _fastener(a, name + "Dog", bone, point(-.50, -.49, cover_depth + .006), normal, .0045)


def _plates(a, side, sign, hip, knee, ankle):
    thigh, calf = side + "Thigh1", side + "Calf"
    diagonal = (sign * .37, -1, 0)
    _panel(a, "HipTasset" + side, thigh, "olive", hip, knee, diagonal,
           ((.21, 1 * sign, 24, .128), (.27, 4 * sign, 39, .139),
            (.39, 4 * sign, 40, .142), (.51, 5 * sign, 31, .134)), .039,
           fit=.042, anchors=((1, 1), (3, 2)))
    thigh_plate = _panel(a, "ThighMain" + side, thigh, "graphite", hip, knee, diagonal,
           ((.455, 6 * sign, 31, .131), (.51, 6 * sign, 46, .132),
            (.63, 9 * sign, 46, .115), (.72, 11 * sign, 34, .109),
            (.76, 7 * sign, 19, .103)), .037, fit=.034, anchors=((1, 1), (3, 2)))
    normal = Vector((sign * .15, -1, .02)).normalized()
    _access(a, "ThighService" + side, thigh, thigh_plate,
            hip.lerp(knee, .585) + Vector((sign * .024, 0, 0)),
            normal, .032, .033)
    _panel(a, "ThighCuff" + side, thigh, "olive", hip, knee, diagonal,
           ((.693, 8 * sign, 32, .103), (.74, 8 * sign, 44, .103),
            (.825, 6 * sign, 40, .093), (.864, 6 * sign, 24, .093)),
           .027, fit=.031, anchors=((2, 1),))
    _panel(a, "HamstringArmor" + side, thigh, "graphite", hip, knee, (sign * .31, 1, 0),
           ((.267, 0, 25, .133), (.34, 0, 47, .134), (.459, -2 * sign, 40, .129),
            (.508, -4 * sign, 29, .119), (.55, -9 * sign, 19, .115)),
           .026, fit=.034, anchors=((1, 1), (3, -2)))
    _panel(a, "KneeShield" + side, calf, "olive", knee, ankle, FRONT,
           ((-.12, 0, 27, .101), (-.075, 0, 49, .106), (.024, 0, 62, .100),
            (.13, 0, 51, .096), (.182, 0, 29, .084)), .041,
           fit=.032, anchors=((1, 1), (1, -2), (3, 2)))
    shin_plate = _panel(a, "ShinShell" + side, calf, "graphite", knee, ankle, FRONT,
           ((.126, 0, 29, .072), (.196, 0, 55, .075), (.42, 2 * sign, 57, .081),
            (.575, 2 * sign, 46, .088), (.642, 0, 32, .089)), .034,
           fit=.032, anchors=((1, 1), (3, 2)))
    normal = Vector((sign * .27, -1, -.17)).normalized()
    _access(a, "ShinService" + side, calf, shin_plate, knee.lerp(ankle, .432) + Vector((sign * .036, 0, 0)),
            normal, .016, .051, face="edge_dark")
    _panel(a, "LowerShinLap" + side, calf, "olive", knee, ankle, FRONT,
           ((.592, 2 * sign, 31, .082), (.641, 2 * sign, 48, .085),
            (.735, 0, 43, .089), (.777, 0, 30, .091)), .029,
           fit=.031, anchors=((2, 1),))
    _panel(a, "CalfArmor" + side, calf, "graphite", knee, ankle, (sign * .30, 1, 0),
           ((.283, 0, 26, .127), (.352, 0, 47, .130), (.515, 0, 51, .122),
            (.642, 0, 42, .110), (.711, 0, 28, .093)), .027,
           fit=.038, anchors=((1, 1), (3, 2)))
    _panel(a, "GaiterArmor" + side, calf, "graphite", knee, ankle, (sign * .15, 1, 0),
           ((.741, 0, 29, .091), (.787, 0, 58, .084),
            (.877, 0, 56, .079), (.925, 0, 37, .076)), .023,
           fit=.033, anchors=((2, 1),))


def leg(a, side, sign=None):
    """Build one leg. The optional sign follows the established v3 convention."""
    if sign is None:
        sign = 1 if side == "L" else -1
    hip, knee, ankle, toe = (a.head(side + name) for name in ("Thigh1", "Calf", "Foot", "Toe"))
    thigh, calf, foot = side + "Thigh1", side + "Calf", side + "Foot"
    lateral = Vector((sign, 0, 0))
    aft = -FRONT

    _plates(a, side, sign, hip, knee, ankle)
    _band(a, "ThighWebbing" + side, thigh, hip, knee, .669, .041, .113, sign)
    _band(a, "KneeWebbing" + side, calf, knee, ankle, .105, .040, .102, sign)
    _band(a, "AnkleWebbing" + side, calf, knee, ankle, .795, .035, .080, sign)

    hip_mount = hip.lerp(knee, .213) + lateral * .165 + aft * .018
    knee_hinge = FRONT.cross(ankle - knee).normalized() * sign
    knee_axle = knee + knee_hinge * .144
    ankle_axle = ankle + lateral * .105

    _hub(a, "HipGear" + side, thigh, hip_mount, lateral, .047)
    _hub(a, "KneeGear" + side, calf, knee_axle, knee_hinge, .058, torque_mark=True)
    _hub(a, "AnkleGear" + side, foot, ankle_axle, lateral, .032)
    _hub(a, "KneeMedialBearing" + side, calf, knee - knee_hinge * .101, -knee_hinge, .031)

    # The thigh spars and knee counterplate rotate together around the knee center.
    a.turning("KneeFixedRace" + side, thigh, "graphite", knee_axle - lateral * .032, lateral,
              ((.048, -.014), (.055, -.007), (.055, .009), (.049, .013)), sides=12 if a.lod else 20)
    for branch in (-1, 1):
        y = aft * branch
        upper_path = [
            (hip_mount - lateral * .019 + y * .026, .019),
            (hip.lerp(knee, .37) + lateral * .171 + y * .048 + aft * .014, .020),
            (hip.lerp(knee, .65) + lateral * .153 + y * .045 + aft * .028, .016),
            (knee_axle - knee_hinge * .043 + y * .030 + UP * .057, .018),
            (knee_axle - knee_hinge * .043 + y * .022 + UP * .029, .022),
        ]
        _rail(a, f"ThighSpar{side}{branch}", thigh, lateral, upper_path, depth=.028)
        _rail(a, f"ThighSparWearStrip{side}{branch}", thigh, lateral,
              [(p + lateral * .015, w * .49) for p, w in upper_path[1:3]]
              + [(upper_path[2][0].lerp(upper_path[3][0], .54) + lateral * .015, .008)],
              family="edge_dark", depth=.006)
        lower_path = [
            (knee_axle - lateral * .018 + y * .035 - UP * .030, .021),
            (knee.lerp(ankle, .26) + lateral * .129 + y * .044 + aft * .036, .019),
            (knee.lerp(ankle, .55) + lateral * .116 + y * .045 + aft * .027, .015),
            (knee.lerp(ankle, .83) + lateral * .105 + y * .026 + aft * .018, .022),
            (ankle_axle - lateral * .013 + y * .018 + UP * .016, .023),
        ]
        _rail(a, f"ShinSpar{side}{branch}", calf, lateral, lower_path, depth=.026)
        _rail(a, f"ShinSparWearStrip{side}{branch}", calf, lateral,
              [(p + lateral * .014, w * .43) for p, w in lower_path[1:4]],
              family="edge_dark", depth=.006)

    for index, (bone, point, depth) in enumerate((
        (thigh, hip.lerp(knee, .51) + lateral * .144 + aft * .016, .032),
        (thigh, hip.lerp(knee, .78) + lateral * .137 + aft * .025, .021),
        (calf, knee.lerp(ankle, .35) + lateral * .113 + aft * .027, .022),
        (calf, knee.lerp(ankle, .78) + lateral * .092 + aft * .018, .028),
    )):
        _lugs(a, f"SparCrossBrace{side}{index}", bone, point, lateral, UP,
              .068 if index < 3 else .049, .028, "graphite", depth)
        for branch in (-1, 1):
            _fastener(a, f"BraceScrew{side}{index}{branch}", bone,
                      point + lateral * depth + aft * (.032 * branch), lateral, .006)

    thigh_drive_start = hip_mount + aft * .035 + lateral * .026 - UP * .045
    thigh_drive_end = knee_axle + aft * .061 + lateral * .016 + UP * .054
    _piston(a, "ThighCylinder" + side, thigh, thigh_drive_start, thigh_drive_end, lateral, .017)
    shin_drive_start = knee_axle + lateral * .032 - UP * .050 + aft * .010
    shin_drive_end = ankle_axle + lateral * .021 + UP * .029 + aft * .023
    _piston(a, "ShinCylinder" + side, calf, shin_drive_end, shin_drive_start, lateral, .020)

    shin_cable_start = knee_axle - UP * .039 + aft * .052
    shin_cable_end = ankle_axle + UP * .068 + aft * .040
    _hose(a, "RearShinServiceLoop" + side, calf, lateral,
          (shin_cable_start, shin_cable_start + aft * .071 - UP * .059,
           shin_cable_end + aft * .095 + UP * .119, shin_cable_end), .0058)
    thigh_cable_start = hip_mount - lateral * .018 + aft * .035
    thigh_cable_end = thigh_drive_end - lateral * .042 + aft * .012
    _hose(a, "RearThighServiceLoop" + side, thigh, lateral,
          (thigh_cable_start, thigh_cable_start + aft * .110 - UP * .065,
           thigh_cable_end + aft * .086 + UP * .108, thigh_cable_end), .0065)
    _boot(a, side, lateral, ankle, toe, ankle_axle)








