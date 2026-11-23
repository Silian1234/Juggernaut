"""Rear load frame, removable-cell carrier, and flexible supply lines."""

from bisect import bisect_left
from math import cos, radians, sin, tau

from mathutils import Quaternion, Vector

from v2_plates import OCTAGON, UP, _bvh
from v3_torso import REAR, _bolt, _cell_receiver, _mirrored, _slab


def _panel(a, name, family, center, width, height, depth, bevel, *,
           bone='Spine3', axis=REAR, profile=OCTAGON):
    surface = a.planar(center, axis, UP, width, height)
    return _slab(a, name, bone, family, [surface(u, v, 0) for u, v in profile],
                 Vector(axis), depth, bevel)


def _bridge(a, name, family, low, high, inner, outer, y, depth):
    outline = (
        (-inner, y, low), (inner, y, low), (outer, y - .021, low + .014),
        (outer + .004, y - .027, high - .012), (outer - .012, y - .023, high),
        (-outer + .012, y - .023, high), (-outer - .004, y - .027, high - .012),
        (-outer, y - .021, low + .014),
    )
    return _slab(a, name, 'Spine3', family, outline, REAR, depth, .004, (1, 6))


def _carrier(a):
    _panel(a, 'CassetteSupportTray', 'graphite', (0, .178, 1.305),
           .135, .155, .035, .005)
    _bridge(a, 'LoadFrameYoke', 'graphite', 1.433, 1.494, .071, .176, .191, .043)
    _bridge(a, 'LoadFrameFoot', 'graphite', 1.127, 1.170, .072, .133, .208, .030)
    _panel(a, 'CassetteHeadCasting', 'olive', (0, .219, 1.417), .111, .020, .045, .005)
    _panel(a, 'CassetteLowerCasting', 'olive', (0, .220, 1.151), .111, .021, .048, .006)
    handle = _panel(a, 'CassetteLatchPocket', 'black', (0, .262, 1.422),
                    .034, .010, .006, .0012)
    lock = _panel(a, 'CassetteReleaseLever', 'steel', (.011, .267, 1.422),
                  .022, .006, .006, .0015)
    _bolt(a, 'CassetteLeverPivot', 'Spine3', handle, -.023, .277, 1.422, REAR, .0042)
    _bolt(a, 'CassetteReleasePin', 'Spine3', lock, .022, .274, 1.422, REAR, .0037)
    service = _panel(a, 'CassetteIdentificationPlate', 'steel', (0, .265, 1.149),
                     .040, .012, .005, .001)
    if not a.lod:
        a.decal('CassetteIdentification', 'Spine3', 'dock_service', service,
                (0, .271, 1.149), REAR, .065, .019)


def _rail(a, suffix, sign):
    outline = (
        (.104, .179, 1.143), (.142, .165, 1.151), (.155, .159, 1.192),
        (.165, .160, 1.378), (.172, .157, 1.452), (.155, .160, 1.476),
        (.114, .184, 1.466), (.108, .185, 1.393), (.105, .178, 1.205),
    )
    _slab(a, 'LoadFrameUpright' + suffix, 'Spine3', 'olive',
          _mirrored(outline, sign), REAR, .059, .006, (2, 6))
    flange = _panel(a, 'FrameEndCleat' + suffix, 'edge_dark',
                    (sign * .135, .227, 1.454), .022, .022, .006, .001)
    _bolt(a, 'FrameEndCleatBolt' + suffix, 'Spine3', flange,
          sign * .135, .235, 1.456, REAR, .0065)

    axis = Vector((sign * .30, .954, 0)).normalized()
    outline = (
        (.076, .217, 1.171), (.108, .224, 1.177), (.125, .232, 1.209),
        (.133, .228, 1.349), (.119, .223, 1.401), (.090, .224, 1.412),
        (.076, .227, 1.393),
    )
    _slab(a, 'CassetteRetainer' + suffix, 'Spine3', 'graphite',
          _mirrored(outline, sign), REAR, .050, .004, (2, 5))
    cover = _panel(a, 'CassetteServiceRail' + suffix, 'olive',
                   (sign * .097, .270, 1.287), .016, .104, .012, .003,
                   axis=axis)
    grille = a.planar((sign * .100, .281, 1.288), axis, UP, .013, .058)
    _slab(a, 'CassetteGrilleRecess' + suffix, 'Spine3', 'black',
          [grille(u, v, 0) for u, v in OCTAGON], axis, .0026, .0008)
    vents = 4 if a.lod else 8
    for i in range(vents):
        row = -.81 + 1.62 * i / (vents - 1)
        vane = [grille(u, row + v, d) for u, v, d in
                ((-.83, -.05, .002), (.83, -.05, .002),
                 (.83, .04, .006), (-.83, .04, .006))]
        _slab(a, f'CassetteGrilleVane{suffix}{i}', 'Spine3', 'edge_dark',
              vane, axis, .0023, .00065)
    for i, z in enumerate((1.199, 1.371)):
        _bolt(a, f'CassetteCaptiveScrew{suffix}{i}', 'Spine3', cover,
              sign * .099, .283, z, axis, .0047)

    # Short webbing sections key over the rails; the main belt and shoulder
    # harness continue independently on the body.
    for i, (y, z) in enumerate(((.220, 1.471), (.213, 1.128))):
        _panel(a, f'PackWebbingSeat{suffix}{i}', 'strap',
               (sign * .105, y, z), .016, .025, .012, .003)
        _panel(a, f'PackWebbingTab{suffix}{i}', 'tan',
               (sign * .105, y + .011, z), .013, .021, .003, .001)
        buckle = _panel(a, f'PackWebbingBuckle{suffix}{i}', 'graphite',
                        (sign * .105, y + .013, z - .006), .018, .009, .008, .002)
        _bolt(a, f'PackWebbingKeeper{suffix}{i}', 'Spine3', buckle,
              sign * .105, y + .022, z - .006, REAR, .0037)


def _spine(a):
    for i, (z, y, width, height, bone) in enumerate((
        (1.523, .146, .099, .036, 'Spine3'),
        (1.494, .156, .079, .028, 'Spine3'),
        (1.119, .161, .098, .029, 'Spine2'),
        (1.081, .169, .081, .025, 'Spine2'),
    )):
        profile = ((-.48, -1), (.48, -1), (.94, -.58), (1, .39),
                   (.63, .95), (-.63, .95), (-1, .39), (-.94, -.58))
        base = _panel(a, f'SpineLaminate{i}', 'olive', (0, y, z),
                      width, height, .027, .005, bone=bone, profile=profile)
        _panel(a, f'SpineLaminateKey{i}', 'graphite', (0, y + .025, z + .004),
               width * .36, height * .65, .008, .002, bone=bone)
        for side in (-1, 1):
            _bolt(a, f'SpineLaminateAnchor{i}_{side}', bone, base,
                  side * width * .65, y + .03, z, REAR, .0058)


def _antenna(a):
    shoulder = Vector((.141, .190, 1.466))
    axis = Vector((.14, .06, 1)).normalized()
    carrier = _panel(a, 'PackAntennaBase', 'graphite', (.144, .175, 1.482),
                     .024, .028, .042, .005)
    _bolt(a, 'PackAntennaCarrierBolt', 'Spine3', carrier,
          .143, .216, 1.489, REAR, .0058)
    a.turning('PackAntennaShaftClamp', 'Spine3', 'steel', shoulder, axis,
              ((.013, .018), (.014, .024), (.014, .035), (.009, .041)), sides=10)
    a.turning('PackAntennaCover', 'Spine3', 'rubber', shoulder, axis,
              ((.010, .031), (.011, .040), (.008, .058), (.005, .080)), sides=10)
    a.turning('PackAntennaWhip', 'Spine3', 'graphite', shoulder, axis,
              ((.0047, .078), (.004, .091), (.0025, .200), (.0034, .203),
               (.0032, .208), (.0015, .210)), sides=8)


def _hose_curve(controls):
    """Sample a Catmull-Rom path, then reparameterize by arc length."""
    points = []
    for i, (start, end) in enumerate(zip(controls, controls[1:])):
        start_tangent = (end - controls[max(i - 1, 0)]) * .5
        end_tangent = (controls[min(i + 2, len(controls) - 1)] - start) * .5
        for step in range(16):
            t = step / 16
            displacement = end - start
            points.append(start + displacement * (3 * t**2 - 2 * t**3)
                          + start_tangent * (t**3 - 2 * t**2 + t)
                          + end_tangent * (t**3 - t**2))
    points.append(controls[-1])
    distance = [0.0]
    for index in range(1, len(points)):
        distance.append(distance[-1] + (points[index] - points[index - 1]).length)

    def sample(fraction):
        target = distance[-1] * min(max(fraction, 0), 1)
        j = max(1, bisect_left(distance, target))
        return points[j - 1].lerp(points[j],
                                   (target - distance[j - 1]) / (distance[j] - distance[j - 1]))

    return sample


def _coupling(a, name, bone, point, axis, small=False):
    r = .020 if small else .024
    a.turning(name + 'Boot', bone, 'rubber', point, axis,
              ((r * .96, -.017), (r, -.010), (r * .92, .002),
               (r * .81, .016)), sides=10 if a.lod else 14)
    a.turning(name + 'Crimp', bone, 'steel', point, axis,
              ((r * .83, -.008), (r * 1.10, -.006), (r * 1.10, .006),
               (r, .010)), sides=8 if a.lod else 12)
    a.turning(name + 'Nut', bone, 'graphite', point, axis,
              ((r, -.020), (r * 1.19, -.016), (r * 1.19, -.007),
               (r, -.005)), sides=6)


def _shoulder_socket(a, suffix, bone, anchor, hose_axis, rearward):
    # Place the seat against the actual finished lames in bind coordinates.
    lames = tuple(obj for obj in a.objects if obj.name.endswith((
        'ShoulderRoof' + suffix, 'ShoulderMiddleLame' + suffix,
        'ShoulderLowerLame' + suffix,
    )))
    nut_center = anchor - hose_axis * .012
    hit, normal, _, _ = _bvh(lames).ray_cast(nut_center + rearward * .060,
                                            -rearward, .175)
    if hit is None:
        raise ValueError(f'Shoulder supply socket {suffix} misses the armor lames')
    if normal.dot(rearward) < 0:
        normal.negate()

    _panel(a, 'ShoulderSupplyMount' + suffix, 'graphite',
           hit - normal * .009, .033, .024, .019, .003, bone=bone, axis=normal)
    neck = nut_center - hit
    length = neck.length
    a.turning('ShoulderSupplySocket' + suffix, bone, 'edge_dark', hit, neck,
              ((.021, -.006), (.023, .008), (.020, length * .70),
               (.017, length + .009)), sides=8 if a.lod else 10)
    across = UP.cross(normal).normalized()
    for side in (-1, 1):
        center = hit + normal * .008 + across * (side * .026)
        a.turning(f'ShoulderSupplyMountBolt{suffix}{side}', bone, 'steel', center, normal,
                  ((.0057, -.001), (.0057, .002), (.0046, .004)), sides=6)


def _hose(a, suffix, sign):
    bone = suffix + 'Upperarm'
    # Match the shoulder armor's presentation geometry when placing its rigid fitting.
    shoulder = a.head(bone)
    direction = a.head(suffix + 'Forearm1') - shoulder
    swing = Quaternion(direction.cross(-UP).normalized(), radians(36))
    sweep = Quaternion(Vector((1, 0, 0)), radians(23))
    inverse = (sweep @ swing).inverted()

    def arm_point(x, y, z):
        return shoulder + inverse @ (Vector((sign * x, y, z)) - shoulder)

    anchor = arm_point(.307, .198, 1.447)
    controls = [Vector((sign * x, y, z)) for x, y, z in (
        (.128, .252, 1.197), (.163, .255, 1.205), (.196, .259, 1.251),
        (.195, .256, 1.341), (.185, .237, 1.441), (.195, .209, 1.508),
        (.228, .229, 1.530), (.288, .232, 1.517), (.318, .207, 1.490),
    )]
    controls.append(anchor)
    sample = _hose_curve(controls)

    sides = 10 if a.lod else 12
    ribs = 18 if a.lod else 34
    radius_pattern = (.014, .019) if a.lod else (.0135, .019, .018)
    count = ribs * len(radius_pattern)
    vertices, faces, uv, weights = [], [], [], []
    for ring in range(count + 1):
        fraction = ring / count
        center = sample(fraction)
        axis = (sample(fraction + .003) - sample(fraction - .003)).normalized()
        right = REAR.cross(axis).normalized()
        normal = axis.cross(right)
        taper = 1 - .18 * fraction
        radius = radius_pattern[ring % len(radius_pattern)] * taper
        # Begin blending above the harness cleat and finish before the arm's fitting.
        blend = min(max((fraction - .58) / .32, 0), 1)
        weight = blend * blend * (3 - 2 * blend)
        weights.append(weight)
        for side in range(sides):
            angle = tau * side / sides
            vertices.append(center + radius * (right * cos(angle) + normal * sin(angle)))
            uv.append((side / sides, fraction))
        if ring:
            a._join(faces, (ring - 1) * sides, ring * sides, sides)
    faces.append(tuple(reversed(range(sides))))
    faces.append(tuple(range(count * sides, (count + 1) * sides)))
    hose = a.mesh('PowerSupplyBellows' + suffix, 'Spine3', 'rubber', vertices, faces, uv)
    del hose['v2_rigid']
    trunk = hose.vertex_groups[0]
    arm = hose.vertex_groups.new(name='Base Human' + bone)
    for ring, weight in enumerate(weights):
        indices = list(range(ring * sides, (ring + 1) * sides))
        if weight == 1:
            trunk.remove(indices)
        elif weight:
            trunk.add(indices, 1 - weight, 'REPLACE')
        if weight:
            arm.add(indices, weight, 'REPLACE')
    _panel(a, 'CassetteManifold' + suffix, 'graphite',
           (sign * .123, .221, 1.194), .019, .024, .044, .004)
    _coupling(a, 'PackSupplyFitting' + suffix, 'Spine3', sample(0),
              (sample(.02) - sample(0)).normalized())
    shoulder = sample(.51)
    axis = (sample(.52) - sample(.50)).normalized()
    a.turning('HoseRestraintBand' + suffix, 'Spine3', 'edge_dark', shoulder, axis,
              ((.020, -.010), (.022, -.008), (.022, .008), (.020, .010)),
              sides=10 if a.lod else 14)
    clamp = _panel(a, 'HoseRestraintCleat' + suffix, 'graphite',
                   (shoulder.x - sign * .026, shoulder.y - .036, shoulder.z),
                   .026, .012, .023, .003)
    _bolt(a, 'HoseRestraintBolt' + suffix, 'Spine3', clamp,
          shoulder.x - sign * .037, shoulder.y - .011, shoulder.z, REAR, .0047)
    arm_axis = (sample(.98) - sample(1)).normalized()
    _coupling(a, 'ShoulderSupplyFitting' + suffix, bone, anchor, arm_axis, small=True)
    _shoulder_socket(a, suffix, bone, anchor, arm_axis, inverse @ REAR)


def back(a):
    """Build the original power-cell interface and the v4 exosuit back around it."""
    _cell_receiver(a)
    _carrier(a)
    _spine(a)
    _antenna(a)
    for suffix, sign in (('L', 1), ('R', -1)):
        _rail(a, suffix, sign)
        _hose(a, suffix, sign)
