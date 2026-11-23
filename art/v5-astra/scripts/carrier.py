"""Fit the black plate carrier and belt to the EFT bind skeleton."""

from collections import Counter
from functools import lru_cache
import json
from math import cos, pi, sin, tau
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from finish import flat_material, material as shared_material

ENTRY = Path(__file__).resolve().parents[1]
CHEST = "Spine3"
WAIST = "Spine2"
HIP = "Pelvis"
FRONT = Vector((0, -1, 0))
BACK = -FRONT
UP = Vector((0, 0, 1))
RIGHT = Vector((1, 0, 0))
RECTANGLE = ((-1, -1), (1, -1), (1, 1), (-1, 1))
CHAMFER = ((-.83, -1), (.83, -1), (1, -.81), (1, .81),
           (.83, 1), (-.83, 1), (-1, .81), (-1, -.81))
YOKE = ((-.92, -1), (0, -1), (.92, -1), (1, -.87), (1, .24),
        (.62, 1), (0, .89), (-.62, 1), (-1, .24), (-1, -.87))
PAINT = ((-.62, -1), (.62, -1), (.94, .39), (1, .75),
         (.86, 1), (-.86, 1), (-1, .75), (-.94, .39))
BREAST_CURVE = ((1.13, -.180), (1.19, -.196), (1.28, -.198), (1.31, -.197),
                (1.34, -.159), (1.39, -.148), (1.43, -.133), (1.51, -.102))
DONOR = "EFT item_equipment_rig_tv110.bundle (CR_tv110_body)"


@lru_cache(maxsize=2)
def donor_parts(lod):
    return json.loads((ENTRY / "source" / "carrier" / f"tv110-lod{lod}.json").read_text())


def interpolate(samples, z):
    for (lo, left), (hi, right) in zip(samples, samples[1:]):
        if z <= hi:
            return left + (right - left) * (z - lo) / (hi - lo)
    return samples[-1][1]


def materials():
    def textile(label, color, roughness=.87):
        return flat_material(f"V5 | Carrier {label}", color, roughness,
                             specular=.22, sheen=.06)

    return {
        "native_black": textile("charcoal plate bag", (.044, .047, .046)),
        "native_olive": textile("dull olive pouches", (.050, .044, .034)),
        "native_belt": textile("smoke belt pouches", (.049, .045, .037)),
        "weave": textile("black Cordura", (.036, .039, .039)),
        "strap": textile("dark nylon webbing", (.042, .043, .038)),
        "loop": textile("black loop field", (.032, .034, .031), .94),
        "pouch": textile("smoke brown pouch canvas", (.047, .040, .032), .90),
        "rim": textile("binding tape", (.052, .054, .047)),
        "thread": textile("gray bartacks", (.084, .079, .065)),
        "poly": shared_material("black"),
        "metal": shared_material("frame"),
        "buckle": shared_material("steel"),
        "paint": shared_material("plate"),
        "edge": shared_material("edge"),
    }


class Carrier:
    def __init__(self, lod, collection, rig):
        self.lod = lod
        self.collection = collection
        self.rig = rig
        self.materials = materials()
        self.objects = []

    def mesh(self, name, category, bone, family, vertices, faces, uvs, smooth=False):
        name = f"V5_Carrier_{name}_LOD{self.lod}"
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, (), faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        self.collection.objects.link(obj)
        mesh.materials.append(self.materials[family])
        data = mesh.uv_layers.new(name="UVMap").data
        for poly in mesh.polygons:
            poly.use_smooth = smooth
            for index in poly.loop_indices:
                data[index].uv = uvs[mesh.loops[index].vertex_index]
        group = "Base Human" + bone
        if group not in self.rig.data.bones:
            raise KeyError(group)
        obj.vertex_groups.new(name=group).add(list(range(len(vertices))), 1, "REPLACE")
        deform = obj.modifiers.new("EFT Bind", "ARMATURE")
        deform.object = self.rig
        obj["part"] = "carrier"
        obj["subpart"] = category
        obj["lod"] = self.lod
        self.objects.append(obj)
        return obj

    def native(self, name, category, bone, family, donor, transform):
        data = donor_parts(self.lod)[donor]
        vertices = [transform(*p) for p in data["positions"]]
        obj = self.mesh(name, category, bone, family, vertices, data["triangles"], data["uv"], True)
        normals = []
        step = .00001
        for (x, y, z), (nx, ny, nz) in zip(data["positions"], data["normals"]):
            dx = Vector(transform(x + step, y, z)) - Vector(transform(x - step, y, z))
            dy = Vector(transform(x, y + step, z)) - Vector(transform(x, y - step, z))
            dz = Vector(transform(x, y, z + step)) - Vector(transform(x, y, z - step))
            normals.append((nx * dy.cross(dz) + ny * dz.cross(dx) + nz * dx.cross(dy)).normalized())
        obj.data.normals_split_custom_set_from_vertices(normals)
        obj["source_asset"] = DONOR
        return obj

    def shell(self, name, category, bone, family, center, width, height, depth, out=FRONT,
              up=UP, shape=None, crown=0, trim=None, bevel=None, wrap=0):
        center = Vector(center)
        out, up = Vector(out).normalized(), Vector(up).normalized()
        right = up.cross(out).normalized()
        if shape is None:
            shape = RECTANGLE
        if bevel is None:
            bevel = not self.lod and bool(crown or trim)
        levels = ((1, 0), (1, depth * .60), (.95, depth)) if bevel else ((1, 0), (.97, depth))
        n = len(shape)
        verts, faces, uv = [], [], []
        for ring, (scale, d) in enumerate(levels):
            for u, v in shape:
                verts.append(center + right * (u * width * scale * .5)
                             + up * (v * height * scale * .5)
                             + out * (d - wrap * (u * scale) ** 2))
                uv.append((.5 + u * width * scale * 6, .5 + v * height * scale * 6 + .11 * ring))
            if ring:
                join(faces, (ring - 1) * n, ring * n, n)
        faces.append(tuple(reversed(range(n))))
        if crown and not self.lod:
            top = (len(levels) - 1) * n
            for u, v in shape:
                verts.append(center + right * (u * width * .31) + up * (v * height * .31)
                             + out * (depth + crown - wrap * (u * .62) ** 2))
                uv.append((.5 + u * width * 3.72, .5 + v * height * 3.72 + .11 * (len(levels) - 1)))
            join(faces, top, top + n, n)
        faces.append(tuple(range(len(verts) - n, len(verts))))
        obj = self.mesh(name, category, bone, family, verts, faces, uv)
        if trim:
            obj.data.materials.append(self.materials[trim])
            for face in obj.data.polygons[:(len(levels) - 1) * n]:
                face.material_index = 1
        return obj

    def webbing(self, name, category, bone, family, points, width, depth, axis=RIGHT):
        points = [Vector(point) for point in points]
        shape = RECTANGLE
        verts, faces, uv = [], [], []
        span = 0
        for i, point in enumerate(points):
            if i:
                span += (point - points[i - 1]).length
            tangent = (points[min(i + 1, len(points) - 1)] - points[max(0, i - 1)]).normalized()
            right = (axis - axis.dot(tangent) * tangent).normalized()
            thick = tangent.cross(right)
            local_width = width if isinstance(width, (float, int)) else width[i]
            for u, v in shape:
                verts.append(point + right * (u * local_width * .5) + thick * (v * depth * .5))
                uv.append((.5 + u * local_width * 5 + v * .04, span * 11))
            if i:
                join(faces, (i - 1) * len(shape), i * len(shape), len(shape))
        faces.extend((tuple(reversed(range(len(shape)))), tuple(range(len(verts) - len(shape), len(verts)))))
        return self.mesh(name, category, bone, family, verts, faces, uv, smooth=not self.lod)

    def buckle_frame(self, name, category, bone, center, width, height, out=FRONT, up=UP, release=True):
        center, out, up = Vector(center), Vector(out), Vector(up)
        right = up.cross(out)
        verts, faces, uv = [], [], []
        shape = RECTANGLE if self.lod else CHAMFER
        count = len(shape)
        for w, h, d in ((width, height, 0), (width, height, .004),
                        (width - .008, height - .008, .004),
                        (width - .008, height - .008, 0)):
            for u, v in shape:
                verts.append(center + right * (u * w * .5) + up * (v * h * .5) + out * d)
                uv.append(((u + 1) * .5, (v + 1) * .5))
        for ring in range(4):
            join(faces, ring * count, ((ring + 1) % 4) * count, count)
        self.mesh(name + "Frame", category, bone, "buckle", verts, faces, uv)
        self.shell(name + "Crossbar", category, bone, "metal", center + out * .001,
                   width - .004, .0046, .0034, out, up)
        if not self.lod and release:
            for side in (-1, 1):
                self.shell(name + f"Release{side}", category, bone, "poly",
                           center + right * (side * width * .50), .0056, height * .49,
                           .0044, out, up, shape=CHAMFER)

    def ring(self, name, category, bone, family, profile, samples):
        verts, faces, uv = [], [], []
        count = len(profile)
        for index in range(samples):
            theta = tau * index / samples
            for j, (rx, ry, center_y, z) in enumerate(profile):
                verts.append((rx * sin(theta), center_y - ry * cos(theta),
                              z - .009 * cos(theta) + .003 * sin(theta * 3)))
                uv.append((index / samples * 7, j / count))
            join(faces, index * count, ((index + 1) % samples) * count, count)
        faces = [tuple(reversed(face)) for face in faces]
        obj = self.mesh(name, category, bone, family, verts, faces, uv, True)
        uv_layer = obj.data.uv_layers.active.data
        for poly in obj.data.polygons[-count:]:
            for index in poly.loop_indices:
                luv = uv_layer[index].uv
                if luv.x < .01:
                    luv.x = 7
        return obj


def join(faces, a, b, count):
    for offset in range(count):
        following = (offset + 1) % count
        faces.append((a + offset, a + following, b + following, b + offset))


def sew_molle(a, name, category, bone, points, directions, width, bartacks=None):
    """Sink the strap into the bag at each sewn divide and raise each pass."""
    route = []
    for left, right, normal, following in zip(points, points[1:], directions, directions[1:]):
        left, right = Vector(left), Vector(right)
        normal, following = Vector(normal), Vector(following)
        if not route:
            route.append(left - normal * .0009)
        # Each pass hangs between two sewn anchors. A single midpoint keeps the
        # aperture and the strip thickness; the short spans do not need two ridges.
        crown = ((.50, .0046),)
        for t, raised in crown:
            route.append(left.lerp(right, t) + normal.lerp(following, t) * raised)
        route.append(right - following * .0009)
    a.webbing(name, category, bone, "strap", route, width, .0032, UP)
    if not a.lod:
        if bartacks is None:
            bartacks = sorted({*range(0, len(points), 2), len(points) - 1})
        for i in bartacks:
            position, out = points[i], directions[i]
            a.shell(f"{name}Bartack{i}", category, bone, "thread",
                    Vector(position) + Vector(out) * .0008, .0016, width * .78, .0010, out)


def loop_field(a):
    """A flush, bias-cut loop panel with a gently bowed textile face."""
    def position(u, v):
        s = 2 * u - 1
        return Vector((.129 * s * (.97 + .03 * sin(pi * v)),
                       -.181 + .031 * v + .014 * s * s - .0035 * sin(pi * v) * (1 - s * s),
                       1.374 + .094 * v + .004 * s * s * (1 - 2 * v) + .0012 * sin(4 * pi * u + v)))

    verts, uv, faces = [], [], []
    columns = 7 if not a.lod else 5
    rows = 5 if not a.lod else 3
    for row in range(rows):
        v = row / (rows - 1)
        for col in range(columns):
            u = col / (columns - 1)
            verts.append(position(u, v))
            uv.append((u, v))
            if row and col:
                index = row * columns + col
                faces.append((index - columns - 1, index - columns, index, index - 1))
    a.mesh("SewnLoopField", "front plate bag", CHEST, "loop", verts, faces, uv, smooth=True)
    edges = (
        ("Lower", [(i / (columns - 1), 0) for i in range(columns)], UP),
        ("Upper", [(i / (columns - 1), 1) for i in range(columns)], UP),
        ("Left", [(0, i / (rows - 1)) for i in range(rows)], RIGHT),
        ("Right", [(1, i / (rows - 1)) for i in range(rows)], RIGHT),
    )
    for name, anchors, axis in edges:
        a.webbing("LoopField" + name + "Binding", "front plate bag", CHEST, "rim",
                  [position(*uv) for uv in anchors], .0048, .0032, axis)


def breast(a):
    def fit(x, y, z):
        front = interpolate(BREAST_CURVE, z)
        return (1.05 * x, -.164 + .79 * (y - front) + .036 * (abs(x) / .15) ** 2
                + .039 * max(0, (z - 1.40) / .105), 1.151 + .89 * (z - 1.137))

    front_bag = a.native("FrontPlateBag", "front plate bag", CHEST, "native_black", "carrier", fit)
    backer = a.shell("FrontBacker", "front plate bag", CHEST, "weave", (0, -.138, 1.291),
                     .305, .276, .029, shape=CHAMFER, crown=.007, wrap=.030, trim="weave")
    yoke_up = Vector((0, .34, .94)).normalized()
    a.shell("FrontYoke", "front plate bag", CHEST, "weave", (0, -.137, 1.424),
            .280, .160, .017, RIGHT.cross(yoke_up), yoke_up, shape=YOKE, wrap=.018)
    loop_field(a)
    for sign, side in ((-1, "R"), (1, "L")):
        a.webbing(f"ChestEdgeTape{side}", "front plate bag", CHEST, "strap",
                  [(sign * x, y, z) for x, y, z in ((.138, -.135, 1.273), (.141, -.143, 1.336),
                   (.136, -.149, 1.382), (.134, -.137, 1.438), (.125, -.117, 1.459))],
                  .014, .0026)
    bag_surfaces = [BVHTree.FromPolygons([v.co for v in obj.data.vertices],
                                        [p.vertices[:] for p in obj.data.polygons])
                    for obj in (front_bag, backer)]
    heights = (1.173, 1.246, 1.349) if a.lod else (1.173, 1.215, 1.257, 1.300, 1.349)
    for i, height in enumerate(heights):
        points = []
        for x in (-.137, -.097, -.059, -.020, .020, .059, .097, .137):
            hits = [surface.ray_cast((x, -.28, height), BACK)[0] for surface in bag_surfaces]
            points.append(min((point for point in hits if point is not None), key=lambda point: point.y))
        sew_molle(a, f"FrontMolleWeb{i}", "front plate bag", CHEST, points,
                  [FRONT] * len(points), .017, (0, 7) if i < 4 else None)
    rear_bag = a.shell("RearPlateBag", "rear plate bag", CHEST, "weave", (0, .132, 1.354),
                        .286, .280, .028, out=BACK, shape=CHAMFER, crown=.008, trim="rim")
    rear_surface = BVHTree.FromPolygons([v.co for v in rear_bag.data.vertices],
                                        [p.vertices[:] for p in rear_bag.data.polygons])
    for i, height in enumerate((1.255, 1.283, 1.312, 1.425, 1.458)):
        if a.lod and i in (1, 3):
            continue
        points = [rear_surface.ray_cast((x, .23, height), FRONT)[0]
                  for x in (-.120, -.071, 0, .071, .120)]
        if all(point is not None for point in points):
            a.webbing(f"RearWebbing{i}", "rear plate bag", CHEST, "strap",
                      [point + BACK * .0010 for point in points], .017, .0038, UP)


def magazine_row(a):
    group = "chest pouches"
    for i, (x, y, z) in enumerate((
        (-.083, -.148, 1.176), (.001, -.160, 1.174), (.085, -.150, 1.178),
    )):
        def p(u, v, h):
            return Vector((x + u, y - v + u * x * 2.2, z + h))

        # A flattened rear wall and shaped side gussets let the pouch bulge
        # outwards while the attachment still meets the curved plate bag.
        profiles = ((.004, .029, .006, .036), (.012, .035, .006, .045),
                    (.043, .037, .006, .052), (.091, .037, .006, .052),
                    (.131, .036, .006, .048), (.143, .033, .005, .041))
        if a.lod:
            profiles = (profiles[0], profiles[1], profiles[3], profiles[-1])
        verts, uv, faces = [], [], []
        for row, (h, half_width, back, front) in enumerate(profiles):
            for u, v in reversed(CHAMFER):
                verts.append(p(u * half_width, (front - back) * .5 + v * (front + back) * .5, h))
                uv.append(((u + 1) * .5, h / .15))
            if row:
                join(faces, (row - 1) * 8, row * 8, 8)
        faces.extend((tuple(reversed(range(8))), tuple(range(len(verts) - 8, len(verts)))))
        a.mesh(f"MagazinePouch{i}", group, CHEST, "pouch", verts, faces, uv, smooth=True)

        flap = ((.000, .139, .065), (.026, .153, .073), (.043, .150, .075),
                (.053, .141, .075), (.057, .121, .073), (.057, .100, .069), (.056, .091, .058))
        body_edge = ((.033, .036, .012), (.035, .043, .043), (.035, .043, .091), (.034, .038, .131))
        neck = flap if not a.lod else (flap[0], flap[1], flap[3], flap[4], flap[-1])
        a.webbing(f"MagazineFoldedFlap{i}", group, CHEST, "native_olive",
                  [p(0, v, h) for v, h, _ in neck], [width for _, _, width in neck], .0052)
        for side in (-1, 1):
            a.webbing(f"MagazineFlapBinding{i}_{side}", group, CHEST, "rim",
                      [p(side * (w * .5 - .001), v + .0008, h + .0015) for v, h, w in neck],
                      .0035, .0030)
            if not a.lod:
                a.webbing(f"MagazineGussetSeam{i}_{side}", group, CHEST, "rim",
                          [p(side * u, v, h) for u, v, h in body_edge], .003, .0030)
            weave = ((-.006, .140), (-.009, .118), (.002, .108), (.002, .099),
                     (-.008, .081), (.003, .065), (-.009, .046), (.003, .028), (.002, .015))
            if a.lod:
                weave = weave[::2]
            a.webbing(f"MagazineMolleTail{i}_{side}", group, CHEST, "strap",
                      [p(side * .021, v, h) for v, h in weave], .017, .0035)
        a.webbing(f"MagazineLowerFlapFold{i}", group, CHEST, "rim",
                  [p(u, .058, h) for u, h in ((-.029, .093), (-.022, .090),
                                             (0, .089), (.022, .090), (.029, .093))],
                  .0042, .0032, UP)
        closure = ((.061, .109), (.061, .086), (.061, .078), (.067, .069),
                   (.061, .060), (.062, .047), (.056, .033), (.056, .023))
        if a.lod:
            closure = closure[::2] + (closure[-1],)
        a.webbing(f"MagazineClosureTab{i}", group, CHEST, "strap",
                  [p(0, v, h) for v, h in closure], .019, .0044)
        a.buckle_frame(f"MagazineSlide{i}", group, CHEST, p(0, .063, .071), .030, .027)
        a.shell(f"MagazinePullEnd{i}", group, CHEST, "rim", p(0, .058, .025), .020, .008, .003)
        if not a.lod:
            for j, h in enumerate((.103, .106, .032, .035)):
                a.shell(f"MagazineTabBartack{i}_{j}", group, CHEST, "thread", p(0, .063, h),
                        .015, .0012, .0012)


def harness(a):
    for side, suffix in ((1, "L"), (-1, "R")):
        route = [
            (side * x, y, z) for x, y, z in (
                (.129, -.153, 1.375), (.129, -.149, 1.423), (.125, -.122, 1.457),
                (.126, -.094, 1.487), (.132, -.060, 1.521), (.140, -.025, 1.545),
                (.145, .015, 1.557), (.145, .058, 1.567), (.142, .094, 1.559),
                (.130, .121, 1.544), (.114, .143, 1.501), (.097, .156, 1.471),
                (.083, .163, 1.421),
            )
        ]
        a.webbing(f"ShoulderHarness{suffix}", "shoulder harness", CHEST, "strap",
                  route if not a.lod else route[::2], .033, .008)
        a.webbing(f"ShoulderPad{suffix}", "shoulder harness", CHEST, "weave",
                  route[4:10] if not a.lod else route[4:10:2], .044, .017)
        if not a.lod:
            for strip in (-1, 1):
                seam = [(x + .0175 * strip, y, z + .009) for x, y, z in route[4:10]]
                a.webbing(f"ShoulderBinding{suffix}_{strip}", "shoulder harness", CHEST,
                          "rim", seam, .0021, .0022)
        up = (Vector(route[4]) - Vector(route[2])).normalized()
        out = RIGHT.cross(up).normalized()
        center = Vector(route[3]) + out * .007
        a.buckle_frame(f"ShoulderBuckle{suffix}", "shoulder harness", CHEST,
                       center, .043, .036, out, up)
        threading = ((-.055, -.006), (-.026, -.005), (-.014, .001),
                     (-.005, .002), (0, .006), (.005, .005), (.014, .001), (.040, -.004))
        a.webbing(f"ShoulderBuckleThreadedTail{suffix}", "shoulder harness", CHEST, "strap",
                  [center + up * along + out * offset for along, offset in threading], .028, .0036)
        for index, along in enumerate((-.038, -.025, .033)):
            a.shell(f"ShoulderTailKeeper{suffix}{index}", "shoulder harness", CHEST,
                    "rim", center + up * along - out * .003, .032, .005, .003, out, up)
        a.shell(f"CarrierFlankTab{suffix}", "shoulder harness", CHEST, "poly",
                (side * .118, -.154, 1.324), .023, .030, .007, shape=CHAMFER)


def collar(a):
    a.ring("LowPaddedCollar", "neck guard", CHEST, "weave",
           ((.102, .115, .023, 1.514), (.106, .111, .024, 1.545),
            (.092, .099, .025, 1.592), (.083, .090, .026, 1.603),
            (.073, .078, .026, 1.596), (.078, .082, .024, 1.543),
            (.084, .092, .023, 1.516)), 16 if not a.lod else 12)
    a.ring("CollarTopBinding", "neck guard", CHEST, "rim",
           ((.084, .092, .026, 1.599), (.082, .091, .026, 1.604),
            (.075, .081, .026, 1.603), (.073, .080, .026, 1.598)),
           16 if not a.lod else 12)
    a.shell("FrontCollarOverlap", "neck guard", CHEST, "strap", (0, -.087, 1.546),
            .102, .047, .008, shape=CHAMFER, crown=.004)
    a.shell("FrontCollarFastener", "neck guard", CHEST, "poly", (0, -.098, 1.553),
            .071, .029, .009, shape=CHAMFER, trim="metal")
    a.shell("CollarLoopPatch", "neck guard", CHEST, "weave", (0, -.107, 1.553),
            .056, .017, .0015)
    a.ring("CollarLowerBinding", "neck guard", CHEST, "rim",
           ((.101, .114, .023, 1.516), (.104, .116, .023, 1.519),
            (.104, .115, .023, 1.523), (.099, .109, .023, 1.520)),
           20 if not a.lod else 12)
    for side in (-1, 1):
        out = Vector((side * .61, -.79, 0))
        a.shell(f"CollarOverlapBacking{side}", "neck guard", CHEST, "rim",
                (side * .056, -.067, 1.553), .046, .057, .006, out,
                shape=CHAMFER, crown=.002)
        a.buckle_frame(f"CollarSideAdjuster{side}", "neck guard", CHEST,
                       (side * .063, -.075, 1.551), .022, .032, out)
        a.webbing(f"CollarAdjusterTail{side}", "neck guard", CHEST, "strap",
                  [Vector((side * .065, -.078, 1.552)) + out * d + UP * h
                   for h, d in ((-.021, -.003), (-.010, .001), (0, .006), (.011, .002), (.018, -.003))],
                  .013, .0032, UP.cross(out))


def cummerbund(a):
    a.ring("PaddedCummerbund", "cummerbund", WAIST, "weave",
           ((.171, .149, .005, 1.169), (.184, .153, .005, 1.181),
            (.185, .153, .008, 1.263), (.174, .140, .008, 1.282),
            (.159, .128, .008, 1.268), (.158, .127, .008, 1.181)),
           16 if not a.lod else 12)
    for side, suffix in ((1, "L"), (-1, "R")):
        for index, z in enumerate((1.187, 1.218, 1.247)):
            if a.lod and index == 1:
                continue
            angles = (56, 68, 80, 92, 104, 116, 128)
            normals = [Vector((side * sin(pi * theta / 180), -cos(pi * theta / 180), 0))
                       for theta in angles]
            points = [(direction.x * .181, direction.y * .150 + .006,
                       z + direction.y * .009) for direction in normals]
            sew_molle(a, f"CummerbundMolle{suffix}{index}", "cummerbund", WAIST,
                      points, normals, .018)
        out = Vector((side * .93, -.37, 0))
        a.shell(f"CummerbundSideLatch{suffix}", "cummerbund", WAIST, "poly",
                (side * .172, -.068, 1.219), .052, .070, .010, out)
        a.shell(f"CummerbundSideLatchInset{suffix}", "cummerbund", WAIST, "metal",
                (side * .182, -.072, 1.218), .018, .045, .0035, out)


def belt(a):
    first = len(a.objects)
    samples = 16 if not a.lod else 12
    a.ring("PaddedBattleBelt", "padded battle belt", HIP, "weave",
           ((.168, .146, -.010, 1.032), (.182, .154, -.011, 1.042),
            (.186, .156, -.008, 1.107), (.176, .147, -.008, 1.120),
            (.162, .134, -.008, 1.111), (.159, .136, -.010, 1.044)), samples)
    a.ring("BattleBeltOuterWebbing", "padded battle belt", HIP, "strap",
           ((.184, .160, -.009, 1.052), (.191, .161, -.009, 1.057),
            (.194, .164, -.009, 1.092), (.188, .161, -.009, 1.097)), samples)
    belt_group = "padded battle belt"
    a.shell("BattleBeltBuckle", belt_group, HIP, "poly", (0, -.173, 1.076),
            .072, .037, .014, shape=CHAMFER, bevel=True)
    a.shell("BattleBeltRelease", belt_group, HIP, "metal", (0, -.187, 1.076),
            .036, .023, .004, shape=CHAMFER)
    for side, suffix in ((1, "L"), (-1, "R")):
        a.buckle_frame(f"BattleBeltSlot{suffix}", belt_group, HIP,
                       (side * .049, -.172, 1.076), .037, .042)
        a.webbing(f"BattleBeltSlotTail{suffix}", belt_group, HIP, "strap",
                  [(side * x, y, 1.076) for x, y in ((.032, -.174), (.044, -.177),
                   (.054, -.177), (.065, -.167), (.096, -.151))], .031, .0036, UP)
        for i, theta in enumerate((.56, .92)):
            cx, cy = .187 * sin(theta) * side, -.010 - .161 * cos(theta)
            direction = Vector((sin(theta) * side, -cos(theta), 0))
            a.shell(f"FrontBeltKeeper{suffix}{i}", "padded battle belt", HIP, "strap",
                    (cx, cy, 1.077), .016, .048, .008, direction)
        for index, z in enumerate((1.046, 1.100)):
            angles = (.40, .61, .82, 1.03, 1.24, 1.45, 1.66, 1.87)
            if a.lod:
                angles = angles[::2] + (angles[-1],)
            route = [(side * .183 * sin(theta), -.010 - .155 * cos(theta),
                      z - .009 * cos(theta)) for theta in angles]
            a.webbing(f"BeltBinding{suffix}{index}", belt_group, HIP, "rim",
                      route, .0043, .0031, UP)
        out = Vector((side * .90, .44, 0)).normalized()
        a.shell(f"HipHoseReceiver{suffix}", "padded battle belt", HIP, "poly",
                (side * .165, .070, 1.097), .022, .028, .028, out)

    # The front of the padded belt can fold with the abdomen. The back and
    # side anchors continue to follow the pelvis and its hose couplings.
    for obj in a.objects[first:]:
        pelvis = obj.vertex_groups[0]
        spine = obj.vertex_groups.new(name="Base Human" + WAIST)
        for vertex in obj.data.vertices:
            amount = .44 * min(1, max(0, (-vertex.co.y - .070) / .052))
            if amount:
                pelvis.add([vertex.index], 1 - amount, "REPLACE")
                spine.add([vertex.index], amount, "REPLACE")

    for name, source, position, angle, sx, sy, sz, source_x, source_z, material in (
        ("FrontLeftPouch", "tool", (-.160, -.100, 1.030), -.56, .77, .72, .64, .0995, 1.162, "native_belt"),
        ("FrontRightPouch", "tool", (.162, -.101, 1.029), .59, .79, .70, .66, .0995, 1.162, "native_olive"),
        ("RearLeftPouch", "tool", (-.114, .126, 1.000), -2.63, 1.09, .99, .95, .0995, 1.162, "native_belt"),
        ("RearUtilityPouch", "left", (.002, .148, 1.001), pi, 1.54, .93, .747, -.0715, 1.154, "native_belt"),
        ("RearRightPouch", "tool", (.120, .126, 1.001), 2.63, 1.09, .99, .93, .0995, 1.162, "native_belt"),
    ):
        x, y, z = position
        r, s = cos(angle), sin(angle)

        def fit(px, py, pz):
            u, v = (px - source_x) * sx, (py + .180) * sy
            return (x + r * u - s * v, y + s * u + r * v, z + (pz - source_z) * sz)

        pouch = a.native(name, "belt pouches", HIP, material, source, fit)
        out = Vector((s, -r, 0))
        if source == "tool":
            # These donor pieces include the folded flap and webbing. Give the
            # shortened pockets a closed inner bag beneath that native flap.
            rear = name.startswith("Rear")
            inner = Vector((x, y, z + (.053 if rear else .051)))
            a.shell(name + "Body", "belt pouches", HIP, material, inner - out * (.012 if rear else .004),
                    .052 if rear else .041, .106 if rear else .076, .045 if rear else .032, out,
                    shape=CHAMFER, bevel=not a.lod)
        group = "belt pouches"
        bag = BVHTree.FromPolygons([vertex.co for vertex in pouch.data.vertices],
                                   [poly.vertices[:] for poly in pouch.data.polygons])
        origin = Vector((x, y, z))
        right = UP.cross(out)

        def surface(height, lateral):
            base = origin + UP * height + right * lateral
            hit = bag.ray_cast(base + out * .090, -out)[0]
            return hit if hit is not None else base + out * (.029 if name.startswith("Front") else .039)

        level = .096 if name == "RearUtilityPouch" else (.059 if name.startswith("Front") else .081)
        center = surface(level, 0) + out * .002
        a.buckle_frame(name + "Buckle", group, HIP, center, .026, .026, out,
                       release=name == "RearUtilityPouch")
        a.webbing(name + "BuckleTail", group, HIP, "strap",
                  [surface(level + h, 0) + out * d for h, d in
                   ((-.026, .0025), (-.013, .0025), (0, .008), (.011, .0032), (.026, .0025))],
                  .015, .0032, right)
        if name.startswith("Rear"):
            spread = .040 if source == "left" else .021
            for side in (-1, 1):
                a.webbing(name + f"Keeper{side}", group, HIP, "rim",
                          [origin + right * (side * spread) + out * d + UP * h for h, d in
                           ((.059, -.004), (.085, -.012), (.106, -.010), (.121, .003), (.111, .013))],
                          .013, .0044, right)
                a.webbing(name + f"FlapBinding{side}", group, HIP, "rim",
                          [surface(level + h, side * spread) + out * .0015 for h in
                           (-.010, .004, .019, .034, .044)],
                          .0032, .0033, right)


def groin(a):
    first = len(a.objects)
    for i, x in enumerate((-.061, .061)):
        a.webbing(f"GroinPlateHanger{i}", "groin plate", HIP, "strap",
                  ((x, -.153, 1.084), (x, -.166, 1.054), (x, -.168, 1.026)),
                  .032, .006)
    a.shell("GroinPlateTextileBacker", "groin plate", HIP, "weave", (0, -.166, .989),
            .216, .127, .017, shape=PAINT)
    a.shell("GroinPlate", "groin plate", HIP, "paint", (0, -.182, .989),
            .212, .120, .012, shape=PAINT, crown=.003, trim="edge")
    for i, (x, z) in enumerate(((-.080, 1.035), (.080, 1.035), (-.052, .942), (.052, .942))):
        a.shell(f"GroinPlateStud{i}", "groin plate", HIP, "metal", (x, -.193, z),
                .0082, .0082, .003, shape=CHAMFER)
    # The suspended plate swings up with the thighs. The upper ends of the
    # flexible hangers stay attached just behind the buckle.
    for obj in a.objects[first:]:
        pelvis = obj.vertex_groups[0]
        thighs = tuple(obj.vertex_groups.new(name=f"Base Human{side}Thigh1") for side in ("L", "R"))
        for vertex in obj.data.vertices:
            amount = .83 * min(1, max(0, (1.083 - vertex.co.z) / .056)) if "Hanger" in obj.name else .83
            pelvis.add([vertex.index], 1 - amount, "REPLACE")
            if amount:
                for thigh in thighs:
                    thigh.add([vertex.index], amount * .5, "REPLACE")


def build(lod, collection, rig):
    """Return every carrier object for a single LOD."""
    carrier = Carrier(lod, collection, rig)
    breast(carrier)
    magazine_row(carrier)
    harness(carrier)
    collar(carrier)
    cummerbund(carrier)
    belt(carrier)
    groin(carrier)
    return carrier.objects


def triangle_counts(objects):
    counts = Counter()
    for obj in objects:
        obj.data.calc_loop_triangles()
        counts[obj["subpart"]] += len(obj.data.loop_triangles)
    return dict(counts)
