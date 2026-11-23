"""TV-110 fabric, harness and radio for the v4 Juggernaut torso."""
from functools import lru_cache
import json
from pathlib import Path

from mathutils import Vector

from v2_plates import FRONT, OCTAGON, UP, _bvh

SOURCE = Path(__file__).resolve().parents[2] / "art/build/v4-tactical"
CHEST = "Spine3"
BEVELED_RECT = ((-.86, -1), (.86, -1), (1, -.86), (1, .86),
                (.86, 1), (-.86, 1), (-1, .86), (-1, -.86))
# Front depth of the unfolded TV-110 plate bag, excluding protruding stitches.
CARRIER_CURVE = ((1.13, -.180), (1.19, -.196), (1.28, -.198), (1.31, -.197),
                 (1.34, -.159), (1.39, -.148), (1.43, -.133), (1.51, -.102))


@lru_cache(maxsize=2)
def donor_parts(lod):
    path = SOURCE / f"tv110-lod{lod}.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing. Run tools/model/v4_tactical_extract.py.")
    return json.loads(path.read_text())


def _donor(a, name, part, transform, bone=CHEST):
    vertices = [transform(*point) for point in part["positions"]]
    uv = [(max(0, min(1, u)), max(0, min(1, v))) for u, v in part["uv"]]
    obj = a.mesh(name, bone, "eft_tactical", vertices, part["triangles"], uv)
    normals = []
    step = .00001
    for (x, y, z), normal in zip(part["positions"], part["normals"]):
        dx = Vector(transform(x + step, y, z)) - Vector(transform(x - step, y, z))
        dy = Vector(transform(x, y + step, z)) - Vector(transform(x, y - step, z))
        dz = Vector(transform(x, y, z + step)) - Vector(transform(x, y, z - step))
        nx, ny, nz = normal
        # Cofactors implement the inverse-transpose transform, including panel warp.
        normals.append((nx * dy.cross(dz) + ny * dz.cross(dx) + nz * dx.cross(dy)).normalized())
    obj.data.normals_split_custom_set_from_vertices(normals)
    obj["v2_atlas_uv"] = True
    obj["v4_donor"] = True
    obj["v4_donor_asset"] = "item_equipment_rig_tv110.bundle"
    return obj


def _plate_bag(x, y, z):
    for (lo, left), (hi, right) in zip(CARRIER_CURVE, CARRIER_CURVE[1:]):
        if z <= hi:
            front = left + (right - left) * (z - lo) / (hi - lo)
            break
    else:
        front = CARRIER_CURVE[-1][1]
    return (x * 1.11, -.194 + .64 * (y - front) + .020 * (abs(x) / .15) ** 3,
            1.193 + .740 * (z - 1.137))


def _pouch_transform(center, source_center, depth, height):
    def transform(x, y, z):
        u = x - source_center
        # The outer pouches follow the shallow curve of the carrier side wall.
        return (1.04 * u + center, depth + .89 * (y + .185) + 1.06 * center * u,
                1.205 + .696 * (z - 1.154) + height)
    return transform


def _utility(x, y, z):
    return (.69 * (x + .127) - .142, .77 * (y + .150) - .154, 1.113 + .73 * (z - 1.117))


def _shell(a, name, family, point, width, height, depth, dome=0, shape=BEVELED_RECT,
           compact=False):
    plane = a.planar(point, FRONT, UP, width * .5, height * .5)
    if compact and not a.lod:
        # Small controls need a chamfer along the silhouette and a flat cap.
        # Their shallow sides are nearly flat at the intended viewing distance.
        levels = ((1, 0), (1, depth * .61), (.85, depth))
        vertices, faces, uv = [], [], []
        count = len(shape)
        for i, (scale, height) in enumerate(levels):
            vertices.extend(plane(scale * u, scale * v, height) for u, v in shape)
            uv.extend((.5 + scale * u * .44, .5 + scale * v * .44) for u, v in shape)
            if i:
                a._join(faces, (i - 1) * count, i * count, count)
        faces.append(tuple(reversed(range(count))))
        faces.append(tuple(range(len(vertices) - count, len(vertices))))
        return a.mesh(name, CHEST, family, vertices, faces, uv, smooth=False)
    return a.shell(name, CHEST, family, plane, depth, dome, shape)


def _loop_field(a, carrier):
    """Fit an unmarked loop patch to the curve of the woven carrier."""
    surface = _bvh([carrier])

    def plane(u, v, depth):
        point = Vector((u * .049, -.228, 1.402 + v * .024))
        hit, _, _, _ = surface.ray_cast(point, -FRONT, .10)
        if hit is None:
            raise ValueError("TV-110 loop patch extends off the upper carrier")
        return hit + FRONT * depth

    a.shell("CarrierLoopBinding", CHEST, "strap", plane, .004, .001, BEVELED_RECT)
    a.shell("CarrierLoopField", CHEST, "fabricdark",
            lambda u, v, d: plane(.9 * u, .83 * v, .004 + d), .0018, 0, BEVELED_RECT)


def _webbing(a, name, family, path, width, depth, bone=CHEST):
    """Sweep a woven, rounded rectangular tape through the fastener path."""
    points = [Vector(point) for point in path]
    contour = OCTAGON if not a.lod else ((-1, -1), (1, -1), (1, 1), (-1, 1))
    vertices, uv, faces = [], [], []
    size = len(contour)
    for i, center in enumerate(points):
        tangent = points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]
        tangent.normalize()
        right = Vector((1, 0, 0))
        right = (right - right.dot(tangent) * tangent).normalized()
        normal = tangent.cross(right)
        for x, z in contour:
            vertices.append(center + x * width * .5 * right + z * depth * .5 * normal)
            uv.append(((x + 1) * .5, i / (len(points) - 1)))
        if i:
            a._join(faces, (i - 1) * size, i * size, size)
    faces.append(tuple(reversed(range(size))))
    faces.append(tuple(range(len(vertices) - size, len(vertices))))
    obj = a.mesh(name, bone, family, vertices, faces, uv)
    if family in {"tan", "strap"}:
        obj["v2_swatch_uv"] = True
    return obj


def _harness(a, sign, suffix, structure):
    path = (
        (.083, -.196, 1.417), (.087, -.190, 1.441), (.094, -.180, 1.470),
        (.107, -.168, 1.500), (.123, -.142, 1.524), (.134, -.103, 1.549),
        (.140, -.069, 1.574), (.141, -.038, 1.582), (.140, -.005, 1.584),
        (.137, .042, 1.577), (.129, .092, 1.565), (.124, .130, 1.550),
        (.119, .163, 1.522), (.111, .181, 1.482), (.108, .191, 1.448),
    )
    fitted = []
    for i, (x, y, z) in enumerate(path):
        p = Vector((sign * x, y, z))
        if structure is not None and 1 < i < 13:
            outward = FRONT if i < 6 else UP if i < 11 else -FRONT
            for shift in (-.020, 0, .020):
                origin = p + Vector((shift, 0, 0)) + outward * .085
                hit, _, _, _ = structure.ray_cast(origin, -outward, .090)
                if hit is not None:
                    p += outward * max(0, (hit - p).dot(outward) + .007)
        fitted.append(p)
    _webbing(a, "CarrierHarness" + suffix, "tan", fitted, .033, .008)
    padded = [point + UP * .004 for point in fitted[6:12]]
    _webbing(a, "CarrierPaddedShoulder" + suffix, "strap", padded, .044, .013)
    for i, offset in enumerate((-.0175, .0175)):
        seam = [point + Vector((offset, 0, .006)) for point in padded]
        _webbing(a, f"CarrierShoulderBinding{suffix}{i}", "seam", seam, .0028, .0022)
    # Tri-glide follows the same incline as the sitting webbing.
    center = fitted[2].lerp(fitted[3], .66)
    up = (fitted[3] - fitted[2]).normalized()
    right = (Vector((1, 0, 0)) - up.x * up).normalized()
    out = right.cross(up)
    base = center + out * .007
    for i, offset in enumerate((-.013, 0, .013)):
        plane = a.planar(base + up * offset, out, up, .021, .003)
        a.shell(f"CarrierAdjusterBar{suffix}{i}", CHEST, "graphite", plane, .005, 0)
    for i, offset in enumerate((-.0185, .0185)):
        side = base + right * offset
        plane = a.planar(side, out, up, .003, .015)
        a.shell(f"CarrierAdjusterRail{suffix}{i}", CHEST, "graphite", plane, .005, 0)
    sewn_return = [fitted[1].lerp(fitted[2], t) + out * .0045 for t in (.26, .59, .85, 1)]
    _webbing(a, "CarrierSewnReturn" + suffix, "strap", sewn_return, .024, .004)
    if not a.lod:
        for i in range(3):
            point = sewn_return[1].lerp(sewn_return[-1], i * .22) + out * .002
            plane = a.planar(point, out, up, .008, .00045)
            a.shell(f"CarrierReturnBartack{suffix}{i}", CHEST, "seam", plane, .0007, 0)
    lower = [(sign * .123, -.180, 1.239), (sign * .168, -.138, 1.237),
             (sign * .190, -.078, 1.235), (sign * .196, .010, 1.236),
             (sign * .188, .076, 1.238), (sign * .163, .129, 1.243),
             (sign * .126, .160, 1.246)]
    # These girdle straps cross the sides, with a separate transverse section.
    points = [Vector(point) for point in lower]
    verts, faces, uv = [], [], []
    for i, center in enumerate(points):
        along = points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]
        outward = UP.cross(along).normalized() * -sign
        ordered = OCTAGON if sign == 1 else tuple(reversed(OCTAGON))
        for u, v in ordered:
            verts.append(center + UP * u * .015 + outward * v * .0032)
            uv.append(((u + 1) * .5, i / (len(points) - 1)))
        if i:
            a._join(faces, (i - 1) * 8, i * 8, 8)
    faces.extend((tuple(reversed(range(8))), tuple(range(len(verts) - 8, len(verts)))))
    girdle = a.mesh("CarrierGirdle" + suffix, CHEST, "strap", verts, faces, uv)
    girdle["v2_swatch_uv"] = True


def _keeper(a, index, center, depth):
    # The fold-over cover and tape underneath are from the native pouch.
    # A polymer adjuster with a central return gives each unit a tactile closure.
    x = center - .001
    y = depth - .058
    z = 1.261 + (.002 if index == 2 else 0)
    _webbing(a, f"CarrierPouchKeeper{index}", "tan",
             ((x, y + .006, z + .021), (x, y + .005, z + .012),
              (x, y - .001, z - .002), (x, y - .001, z - .019)), .022, .004)
    _shell(a, f"CarrierPouchClosure{index}", "black", (x, y - .004, z), .028, .024, .006)
    _shell(a, f"CarrierPouchLug{index}", "graphite",
           (x, y - .010, z - .005), .020, .0042, .0025, compact=True)
    _shell(a, f"CarrierPouchBar{index}", "graphite",
           (x, y - .010, z + .006), .020, .005, .0025)


def _radio(a):
    x, y, z = .141, -.192, 1.401
    _shell(a, "RadioPaddedHolster", "tan", (x, y + .013, z - .034), .070, .088, .030, .003)
    _shell(a, "RadioShell", "black", (x, y, z), .058, .118, .035, .0012)
    _shell(a, "RadioBezel", "graphite", (x, y - .035, z + .001), .049, .102, .003)
    _shell(a, "RadioScreenGasket", "black", (x, y - .038, z + .030), .042, .023, .002,
           compact=True)
    _shell(a, "RadioScreen", "marking", (x, y - .040, z + .030), .035, .016, .001)
    axis = Vector((.035, .07, .997)).normalized()
    a.turning("RadioAntennaBase", CHEST, "black", (x + .015, y - .017, z + .058), axis,
              ((.0066, 0), (.0072, .004), (.0072, .018), (.0045, .025)), sides=8 if a.lod else 14)
    a.turning("RadioFlexibleWhip", CHEST, "rubber", (x + .015, y - .017, z + .078), axis,
              ((.0042, 0), (.0031, .033), (.0021, .111), (.0018, .145),
               (.0027, .146), (.0026, .153), (.0014, .155)), sides=6 if a.lod else 10)
    a.turning("RadioVolumeKnob", CHEST, "rubber", (x - .014, y - .017, z + .057), UP,
              ((.007, 0), (.008, .003), (.008, .010), (.0067, .013)), sides=8 if a.lod else 16)
    _shell(a, "RadioTransmitSwitch", "red", (x - .026, y - .021, z + .012), .009, .019, .004,
           compact=True)
    # Keys share one mesh. Each key has a bevel and an inset shaped cap.
    vertices, faces, uv = [], [], []
    shape = OCTAGON if not a.lod else ((-1, -1), (1, -1), (1, 1), (-1, 1))
    sizes = ((1, 0), (1, .0013), (.79, .0024)) if not a.lod else ((1, 0), (.82, .0022))
    count = len(shape)
    for row in range(4):
        for col in range(3):
            start = len(vertices)
            cx, cz = x + (col - 1) * .0125, z + .008 - row * .012
            for i, (scale, depth) in enumerate(sizes):
                vertices.extend((cx + u * .0047 * scale, y - .038 - depth,
                                 cz + v * .0036 * scale) for u, v in shape)
                uv.extend((.5 + u * .43, .5 + v * .43) for u, v in shape)
                if i:
                    a._join(faces, start + (i - 1) * count, start + i * count, count)
            faces.append(tuple(range(len(vertices) - count, len(vertices))))
    a.mesh("RadioKeypad", CHEST, "rubber", vertices, faces, uv, smooth=False)


def _waist_tool_pouch(a, part):
    def place(x, y, z):
        u = x - .10
        return (.145 + .80 * u - .20 * (y + .174),
                -.158 + .54 * (y + .174) + .45 * u,
                1.060 + .62 * (z - 1.162))

    _donor(a, "TV110BeltToolPouch", part, place, "Pelvis")
    for i, x in enumerate((.131, .160)):
        _webbing(a, f"BeltToolPouchLoop{i}", "strap",
                 ((x, -.134, 1.088), (x, -.142, 1.099),
                  (x, -.157, 1.102), (x, -.165, 1.096),
                  (x, -.167, 1.082), (x, -.165, 1.066)),
                 .012, .0035, "Pelvis")


def tactical(a):
    """Add the v4 chest gear to an Armor builder on its corresponding LOD."""
    structure_parts = [obj for obj in a.objects
                       if any(word in obj.name for word in ("ChestCasting", "FrontGorget",
                                                             "GorgetShoulderSaddle", "BridgeLug",
                                                             "ScapularCasting"))]
    structure = _bvh(structure_parts) if structure_parts else None
    parts = donor_parts(a.lod)
    carrier = _donor(a, "TV110Carrier", parts["carrier"], _plate_bag)
    _loop_field(a, carrier)
    for index, (source, original_x, x, y, height) in enumerate((
        ("left", -.071, -.104, -.190, -.003),
        ("right", .023, -.006, -.194, 0),
        ("left", -.071, .095, -.191, .002),
    )):
        _donor(a, f"TV110FoldedPouch{index}", parts[source],
               _pouch_transform(x, original_x, y, height))
        _keeper(a, index, x, y)
    _donor(a, "TV110Utility", parts["utility"], _utility)
    _waist_tool_pouch(a, parts["tool"])
    for sign, suffix in ((1, "L"), (-1, "R")):
        _harness(a, sign, suffix, structure)
    _radio(a)

