"""Angular torso armor and the fixed power-cell receiver for Juggernaut v3."""

from mathutils import Vector
import bpy

from v2_plates import FRONT, OCTAGON, UP


REAR = -FRONT
CHEST = (
    (.027, -.107, 1.462), (.126, -.078, 1.523),
    (.190, -.110, 1.502), (.224, -.124, 1.441),
    (.197, -.111, 1.384), (.051, -.137, 1.357),
    (.025, -.138, 1.388),
)
SCAPULA = (
    (.053, .158, 1.495), (.137, .139, 1.519),
    (.185, .124, 1.472), (.174, .136, 1.408),
    (.124, .148, 1.370), (.074, .160, 1.393),
)
APRON_FRONT = (
    (.060, -.144, 1.051), (.135, -.098, 1.061),
    (.161, -.089, 1.025), (.198, -.098, .953),
    (.172, -.120, .927), (.113, -.148, .920),
    (.099, -.153, .971),
)
APRON_REAR = (
    (.064, .121, 1.057), (.137, .091, 1.063),
    (.169, .089, 1.027), (.196, .092, .961),
    (.172, .118, .936), (.124, .139, .928),
    (.097, .135, .964),
)


def _mirrored(profile, sign):
    return [(sign * x, y, z) for x, y, z in profile]


def _slab(a, name, bone, family, outline, axis, thickness, bevel, crease=None):
    """Make a closed, faceted laminate with a small machined edge break."""
    points = [Vector(point) for point in outline]
    count = len(points)
    center = sum(points, Vector()) / count
    normal = sum(
        ((points[i] - center).cross(points[(i + 1) % count] - center) for i in range(count)),
        Vector(),
    )
    if normal.dot(axis) < 0:
        points.reverse()
        if crease is not None:
            crease = tuple(sorted(count - 1 - index for index in crease))

    facets = [tuple(range(count))]
    if crease is not None:
        first, last = crease
        facets = [tuple(range(first, last + 1)),
                  tuple(range(last, count)) + tuple(range(first + 1))]
    # Both surfaces meeting a fold use the same edge. The farthest vertex
    # from that fold sets the tilt of each face and keeps the cut from
    # introducing an unsupported bulge through the middle of the plate.
    planes = []
    for facet in facets:
        start = points[facet[0]]
        edge = points[facet[-1]] - start
        across = axis.cross(edge)
        far = max(facet[1:-1], key=lambda index: abs((points[index] - start).dot(across)))
        plane = edge.cross(points[far] - start)
        planes.append((start, plane / plane.dot(axis)))

    inset = [(center - point).normalized() * min(bevel, (center - point).length * .28)
             for point in points]
    if a.lod:
        levels = ((0, 0), (0, thickness - bevel), (1, thickness))
    else:
        levels = ((.55, 0), (0, bevel * .55), (0, thickness - bevel), (1, thickness))
    vertices, faces = [], []
    for index, (inset_scale, depth) in enumerate(levels):
        vertices.extend(point + inset_scale * delta + axis * depth
                        for point, delta in zip(points, inset))
        if index:
            a._join(faces, (index - 1) * count, index * count, count)
    ring = len(vertices) - count
    for facet, (start, plane) in zip(facets, planes):
        for index in facet:
            vertex = vertices[ring + index]
            offset = thickness - (vertex - start).dot(plane)
            if crease is not None and index in crease:
                # Move shared endpoints parallel to the fold so the two
                # planes retain the same endpoints after beveling.
                edge = points[crease[1]] - points[crease[0]]
                towards = edge.normalized() * bevel * .72
                vertex = points[index] + (towards if index == crease[0] else -towards)
                vertices[ring + index] = vertex + axis * thickness
            else:
                vertices[ring + index] = vertex + axis * offset
        faces.append(tuple(reversed(facet)))
        faces.append(tuple(ring + index for index in facet))
    right = UP.cross(axis).normalized()
    vertical = axis.cross(right).normalized()
    uv = [(.5 + (point - center).dot(right), .5 + (point - center).dot(vertical))
          for point in vertices]
    obj = a.mesh(name, bone, family, vertices, faces, uv, smooth=False)
    if family in {'olive', 'graphite'}:
        edge_name = 'V2_edge' if family == 'olive' else 'V2_edge_dark'
        obj.data.materials.append(bpy.data.materials.get(edge_name)
                                  or bpy.data.materials.new(edge_name))
        for polygon in obj.data.polygons[(len(levels) - 2) * count:(len(levels) - 1) * count]:
            polygon.material_index = 1
    return obj


def _bolt(a, name, bone, target, x, y, z, axis, radius):
    surface = a.planar((x, y, z), axis, UP, .013, .013)
    a.fastener(name, bone, surface, 0, 0, 0, radius, target=target)


def _oblique(a, suffix, sign, index, inner_z, outer_z, inner_x, outer_x, inner_y, outer_y, bone):
    # The long upper line sweeps up over the ribs. The shortened lower edge
    # stays clear of the next segment through flexion.
    half_height = .023 if index < 2 else .018
    outline = (
        (inner_x, inner_y, inner_z + half_height),
        (outer_x - .014, outer_y - .010, outer_z + half_height),
        (outer_x, outer_y, outer_z + .006),
        (outer_x - .010, outer_y - .008, outer_z - half_height),
        (inner_x + .008, inner_y + .001, inner_z - half_height),
    )
    name = f'ObliqueLame{suffix}{index}'
    plate = _slab(a, name, bone, 'olive', _mirrored(outline, sign), FRONT,
                  .022 if index < 2 else .017, .005 if index < 2 else .0035)
    _bolt(a, name + 'Anchor', bone, plate, sign * (outer_x - .022), outer_y - .027,
          outer_z, FRONT, .0048)


def _belt(a, sign, suffix):
    for rear, profile in (
        (False, ((.021, -.153, 1.058), (.084, -.139, 1.064),
                 (.142, -.099, 1.081), (.163, -.062, 1.087))),
        (True, ((.021, .127, 1.064), (.087, .117, 1.070),
                (.143, .088, 1.085), (.163, .046, 1.087))),
    ):
        axis = REAR if rear else FRONT
        outline = [(x, y, z - .015) for x, y, z in profile]
        outline += [(x, y, z + .015) for x, y, z in reversed(profile)]
        side = 'Rear' if rear else 'Front'
        _slab(a, 'WaistWebbing' + side + suffix, 'Pelvis', 'strap',
              _mirrored(outline, sign), axis, .009, .002, (1, 6))
    axis = Vector((sign, 0, 0))
    outline = [(sign * .163, y, z) for y, z in
               ((-.067, 1.074), (.046, 1.074), (.055, 1.083),
                (.041, 1.104), (-.054, 1.104), (-.071, 1.094))]
    _slab(a, 'WaistSideCleat' + suffix, 'Pelvis', 'graphite', outline, axis, .016, .003)


def _vent(a, sign, suffix):
    # Sloping seat ties the scapula to the collar while leaving the neck open.
    axis = Vector((sign * .22, .59, .78)).normalized()
    seat = a.planar((sign * .121, .110, 1.531), axis, UP, .044, .033)
    housing = ((-.94, -.87), (.78, -.96), (1, -.62), (1, .70),
               (.77, 1), (-.73, .95), (-1, .62), (-1, -.64))
    _slab(a, 'ScapularVentSeat' + suffix, 'Spine3', 'graphite',
          [seat(u, v, 0) for u, v in housing], axis, .019, .004)
    _slab(a, 'ScapularVentRecess' + suffix, 'Spine3', 'black',
          [seat(u * .76, v * .73, .018) for u, v in housing], axis, .0025, .001)
    slats = (-.49, -.17, .15, .47) if not a.lod else (-.38, 0, .38)
    for index, v in enumerate(slats):
        _slab(a, f'ScapularVentVane{suffix}{index}', 'Spine3', 'steel',
              [seat(u, v + w, h) for u, w, h in
               ((-.75, -.054, .020), (.75, -.054, .020),
                (.75, .054, .023), (-.75, .054, .023))], axis, .004, .001)


def _shoulder_bridge(a, sign, suffix):
    # A folded return runs from the pectoral lug to the scapular vent seat.
    # The raised center is outside the neck turn envelope.
    axis = Vector((sign * .12, -.08, .99)).normalized()
    profile = (
        (.101, -.083, 1.512), (.139, -.088, 1.516),
        (.175, -.009, 1.543), (.160, .104, 1.528),
        (.145, .123, 1.516), (.106, .110, 1.524),
        (.116, -.008, 1.546),
    )
    _slab(a, 'ClavicleLoadBridge' + suffix, 'Spine3', 'graphite',
          _mirrored(profile, sign), axis, .013, .003, (2, 6))
    liner_axis = Vector((sign * .10, -.36, .93)).normalized()
    # The narrow transverse slats sit below the crown of the front ramp.
    liner = a.planar((sign * .132, -.052, 1.540), liner_axis, UP, .023, .022)
    _slab(a, 'ClavicleVentRecess' + suffix, 'Spine3', 'black',
          [liner(u, v, 0) for u, v in OCTAGON], liner_axis, .003, .001)
    for index, v in enumerate((-.54, 0, .54) if not a.lod else (-.42, .42)):
        vane = [liner(u, v + h, d) for u, h, d in
                ((-.80, -.086, .002), (.80, -.086, .002),
                 (.80, .086, .005), (-.80, .086, .005))]
        _slab(a, f'ClavicleVentVane{suffix}{index}', 'Spine3', 'edge_dark', vane,
              liner_axis, .002, .0006)


def torso(a):
    for suffix, sign in (('L', 1), ('R', -1)):
        plate = _slab(a, 'PectoralPlate' + suffix, 'Spine3', 'olive',
                      _mirrored(CHEST, sign), FRONT, .034, .007, (3, 6))
        for index, (x, y, z) in enumerate(((.128, -.143, 1.500), (.045, -.173, 1.412),
                                           (.162, -.154, 1.429))):
            _bolt(a, f'PectoralAnchor{suffix}{index}', 'Spine3', plate,
                  sign * x, y, z, FRONT, .0057)
        _slab(a, 'ScapularPlate' + suffix, 'Spine3', 'olive', _mirrored(SCAPULA, sign),
              REAR, .030, .006, (1, 4))
        _vent(a, sign, suffix)
        _shoulder_bridge(a, sign, suffix)
        # A diagonal load saddle carries the outer pectoral into the ribs.
        # It leaves bare cloth between the saddle, obliques, and waist.
        rib_axis = Vector((sign * .74, -.67, 0)).normalized()
        rib = ((.167, -.101, 1.319), (.202, -.094, 1.347),
               (.210, -.085, 1.396), (.178, -.114, 1.395),
               (.157, -.115, 1.358))
        _slab(a, 'PectoralRibSaddle' + suffix, 'Spine3', 'graphite',
              _mirrored(rib, sign), rib_axis, .017, .004, (0, 2))

        for index, row in enumerate((
            (1.313, 1.361, .030, .157, -.154, -.124, 'Spine3'),
            (1.238, 1.288, .033, .149, -.155, -.116, 'Spine2'),
            (1.167, 1.212, .038, .133, -.153, -.115, 'Spine1'),
        )):
            _oblique(a, suffix, sign, index, *row)

        _belt(a, sign, suffix)
        for side, outline, axis in (
            ('Front', APRON_FRONT, FRONT),
            ('Rear', APRON_REAR, REAR),
        ):
            bone = suffix + 'Thigh1'
            plate = _slab(a, 'HipApron' + side + suffix, bone, 'olive',
                          _mirrored(outline, sign), axis, .026, .005, (1, 4))
            _bolt(a, 'ApronAnchor' + side + suffix, bone, plate,
                  sign * .104, -.155 if side == 'Front' else .135, 1.034, axis, .0059)

        # The shallow flange keys under the pectoral and cross-shoulder
        # bridge. The stepped inner crest faces the chin opening.
        collar_axis = Vector((sign * .13, -.98, .13)).normalized()
        collar = (
            (.014, -.111, 1.486), (.058, -.105, 1.490),
            (.126, -.080, 1.516), (.132, -.062, 1.539),
            (.100, -.073, 1.557), (.075, -.098, 1.576),
            (.060, -.120, 1.598), (.040, -.123, 1.596),
            (.033, -.119, 1.582), (.013, -.121, 1.570),
        )
        _slab(a, 'GorgetFront' + suffix, 'Spine3', 'graphite',
              _mirrored(collar, sign), collar_axis, .015, .003, (4, 9))

    _slab(a, 'GorgetRear', 'Spine3', 'graphite',
          [(-.083, .123, 1.537), (.083, .123, 1.537), (.089, .118, 1.574),
           (.057, .106, 1.603), (.032, .108, 1.595), (-.032, .108, 1.595),
           (-.057, .106, 1.603), (-.089, .118, 1.574)], REAR, .019, .004)
    # The centerline knuckles key into the pectoral seam and end above the waist.
    for index, (lo, hi, radius, y, bone) in enumerate((
        (1.396, 1.460, .019, -.137, 'Spine3'),
        (1.333, 1.390, .017, -.151, 'Spine3'),
        (1.265, 1.326, .016, -.152, 'Spine2'),
    )):
        outline = [(-radius * .44, y, lo), (radius * .44, y, lo),
                   (radius, y + .007, lo + .018), (radius * .89, y + .011, hi - .008),
                   (radius * .52, y + .012, hi), (-radius * .52, y + .012, hi),
                   (-radius * .89, y + .011, hi - .008), (-radius, y + .007, lo + .018)]
        _slab(a, f'SternalKey{index}', bone, 'graphite', outline, FRONT, .021, .003)
    plane = a.planar((0, -.153, 1.058), FRONT, UP, .036, .020)
    _slab(a, 'WaistBuckle', 'Pelvis', 'graphite', [plane(u, v, 0) for u, v in OCTAGON],
          FRONT, .016, .004)
    rear_waist = a.planar((0, .126, 1.064), REAR, UP, .030, .015)
    _slab(a, 'RearWaistKeeper', 'Pelvis', 'graphite',
          [rear_waist(u, v, 0) for u, v in OCTAGON], REAR, .010, .003)
    for sign in (-1, 1):
        x = .021 * sign
        _slab(a, f'WaistBuckleKeep{sign}', 'Pelvis', 'steel',
              [(x + u * .004, -.169, 1.058 + v * .013) for u, v in OCTAGON],
              FRONT, .002, .0006)


def _cell_receiver(a):
    # Freeze the verified contact contours, insertion axis, and standalone
    # cell transform. Exterior pack plates are independent of these surfaces.
    shapes = (
        ((0, .217, 1.285), .092, .119, ((1, -.004), (1, .004), (.94, .012))),
        ((-.073, .229, 1.285), .009, .107, ((1, -.005), (1, .025), (.87, .029))),
        ((.073, .229, 1.285), .009, .107, ((1, -.005), (1, .025), (.87, .029))),
        ((0, .23, 1.165), .055, .010, ((1, -.008), (.86, .020))),
    )
    vertices, faces, uv = [], [], []
    for origin, width, height, levels in shapes:
        plane = a.planar(origin, REAR, UP, width, height)
        first = len(vertices)
        for j, (scale, depth) in enumerate(levels):
            for u, v in OCTAGON:
                vertices.append(plane(u * scale, v * scale, depth))
                uv.append((.5 + u * scale * .45, .5 + v * scale * .45))
            if j:
                a._join(faces, first + (j - 1) * 8, first + j * 8, 8)
        faces.append(tuple(reversed(range(first, first + 8))))
        faces.append(tuple(range(len(vertices) - 8, len(vertices))))
    obj = a.mesh('JuggPowerDock', 'Spine3', 'steel', vertices, faces, uv, smooth=False)
    obj['cell_socket_center_m'] = (0, .272, 1.285)
    obj['cell_world_translation_m'] = (0, .2695, 1.28075)
    obj['cell_world_yaw_degrees'] = 180.0


def dock(a):
    _cell_receiver(a)
    # The carrier is narrow. The angular bridge lands in the shell flanks;
    # service access is open behind the original slide and terminal block.
    _slab(a, 'PowerPackBacking', 'Spine3', 'graphite',
          [(-.075, .144, 1.132), (.075, .144, 1.132), (.103, .175, 1.171),
           (.103, .179, 1.388), (.072, .169, 1.436), (-.072, .169, 1.436),
           (-.103, .179, 1.388), (-.103, .175, 1.171)], REAR, .039, .005, (1, 4))
    _slab(a, 'PowerPackCrossmember', 'Spine3', 'graphite',
          [(-.146, .173, 1.410), (-.079, .208, 1.398), (.079, .208, 1.398),
           (.146, .173, 1.410), (.152, .170, 1.435), (.075, .209, 1.430),
           (-.075, .209, 1.430), (-.152, .170, 1.435)], REAR, .027, .004)
    clasp = a.planar((0, .233, 1.417), REAR, UP, .036, .009)
    _slab(a, 'PowerPackUpperClasp', 'Spine3', 'steel', [clasp(u, v, 0) for u, v in OCTAGON],
          REAR, .008, .002)
    _slab(a, 'PowerPackSump', 'Spine3', 'olive',
          [(-.070, .196, 1.133), (.070, .196, 1.133), (.089, .204, 1.146),
           (.064, .214, 1.168), (-.064, .214, 1.168), (-.089, .204, 1.146)],
          REAR, .025, .004)
    for suffix, sign in (('L', 1), ('R', -1)):
        rail = ((.080, .222, 1.167), (.098, .204, 1.181), (.109, .198, 1.323),
                (.102, .207, 1.405), (.090, .216, 1.413), (.079, .219, 1.390))
        armor = _slab(a, 'PowerPackRailArmor' + suffix, 'Spine3', 'olive',
                      _mirrored(rail, sign), REAR, .029, .004, (1, 4))
        for index, z in enumerate((1.198, 1.378)):
            _bolt(a, f'PowerPackRailAnchor{suffix}{index}', 'Spine3', armor,
                  sign * .090, .246, z, REAR, .0044)

        vent_axis = Vector((sign * .64, .76, 0)).normalized()
        vent = a.planar((sign * .105, .231, 1.306), vent_axis, UP, .009, .030)
        _slab(a, 'PackRailVentRecess' + suffix, 'Spine3', 'black',
              [vent(u, v, 0) for u, v in OCTAGON], vent_axis, .003, .001)
        for index, v in enumerate((-.51, 0, .51) if not a.lod else (-.37, .37)):
            vane = [vent(u, v + h, d) for u, h, d in
                    ((-.83, -.105, .002), (.83, -.105, .002),
                     (.83, .09, .005), (-.83, .09, .005))]
            _slab(a, f'PackRailVentVane{suffix}{index}', 'Spine3', 'steel', vane,
                  vent_axis, .0025, .0008)
