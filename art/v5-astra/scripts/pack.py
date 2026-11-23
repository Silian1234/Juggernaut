"""Reference powerpack, chassis rails, and articulated cable runs."""
from math import cos, pi, sin

import bmesh
import bpy
from mathutils import Vector

from finish import flat_material, material


MATERIALS = ("plate", "edge", "frame", "steel", "strap", "rubber", "yellow", "black")
CHEST = "Base HumanSpine3"
WAIST = "Base HumanSpine1"
PELVIS = "Base HumanPelvis"


def pack_finish(key):
    base = material(key)
    shade = {"plate": .68, "edge": .57, "black": .67}.get(key)
    if shade is None:
        return base
    shader = next(node for node in base.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    color = tuple(channel * shade for channel in shader.inputs["Base Color"].default_value[:3])
    return flat_material(f"Powerpack {key}", color, shader.inputs["Roughness"].default_value,
                         shader.inputs["Metallic"].default_value)


def chamfered_outline(width, height, clip):
    x, z = width / 2, height / 2
    if clip == 0:
        return ((-x, -z), (x, -z), (x, z), (-x, z))
    return (
        (-x+clip, -z), (x-clip, -z), (x, -z+clip), (x, z-clip),
        (x-clip, z), (-x+clip, z), (-x, z-clip), (-x, -z+clip),
    )


class PackMesh:
    def __init__(self):
        self.vertices = []
        self.faces = []
        self.materials = []
        self.weights = []
        self.smooth = []

    def face(self, vertices, mat, smooth=False):
        self.faces.append(tuple(vertices))
        self.materials.append(MATERIALS.index(mat))
        self.smooth.append(smooth)

    def ring(self, points, weights):
        start = len(self.vertices)
        self.vertices.extend(points)
        self.weights.extend([weights] * len(points))
        return tuple(range(start, len(self.vertices)))

    def bridge(self, lower, upper, mat, smooth=False):
        for i in range(len(lower)):
            j = (i + 1) % len(lower)
            self.face((lower[i], upper[i], upper[j], lower[j]), mat, smooth)

    def box(self, center, size, clip, mat, bevel=0, weight=None):
        x, y, z = center
        w, d, h = size
        weight = weight or {CHEST: 1}
        slices = [(y-d/2, 0), (y+d/2, 0)]
        if bevel:
            slices = [(y-d/2, bevel), (y-d/2+bevel, 0), (y+d/2-bevel, 0), (y+d/2, bevel)]
        rings = [
            self.ring(
                [(x+a, offset, z+b) for a, b in chamfered_outline(w-2*inset, h-2*inset, max(clip-inset/2, 0))],
                weight,
            )
            for offset, inset in slices
        ]
        self.face(rings[0], mat)
        for i, (lower, upper) in enumerate(zip(rings, rings[1:])):
            border = "edge" if mat == "plate" and bevel and i != 1 else mat
            self.bridge(lower, upper, border)
        self.face(reversed(rings[-1]), mat)

    def tube(self, points, radius, mat, sides, weights=None, smooth=True):
        centers = [Vector(p) for p in points]
        weights = weights or [{CHEST: 1}] * len(centers)
        rings = []
        u = None
        for i, point in enumerate(centers):
            axis = (centers[min(i + 1, len(centers)-1)] - centers[max(i-1, 0)]).normalized()
            if u is None:
                reference = Vector((0, 1, 0)) if abs(axis.y) < 0.8 else Vector((0, 0, 1))
                u = axis.cross(reference).normalized()
            else:
                u = (u - axis * u.dot(axis)).normalized()
            v = u.cross(axis)
            r = radius[i] if isinstance(radius, list) else radius
            ring = [
                point + r * (cos(2*pi*j/sides)*u + sin(2*pi*j/sides)*v)
                for j in range(sides)
            ]
            rings.append(self.ring(ring, weights[i]))
        self.face(rings[0], mat)
        for lower, upper in zip(rings, rings[1:]):
            self.bridge(lower, upper, mat, smooth)
        self.face(reversed(rings[-1]), mat)

    def beam(self, points, width, depth, weights):
        """Square-section forged member with an aligned cross-section at each station."""
        points = [Vector(point) for point in points]
        rings = []
        normal = Vector((0, 1, 0))
        for i, center in enumerate(points):
            axis = (points[min(i + 1, len(points) - 1)]
                    - points[max(i - 1, 0)]).normalized()
            up = (normal - axis * axis.dot(normal)).normalized() * (depth * .5)
            across = axis.cross(up).normalized() * (width * .5)
            rings.append(self.ring([center + x * across + y * up for x, y in
                                    ((-1, -1), (1, -1), (1, 1), (-1, 1))],
                                   weights[i]))
        self.face(rings[0], "frame")
        for a, b in zip(rings, rings[1:]):
            self.bridge(a, b, "frame")
        self.face(reversed(rings[-1]), "frame")

    def turn_about(self, start, center, angle):
        x, y, _ = center
        c, s = cos(angle), sin(angle)
        for i in range(start, len(self.vertices)):
            dx, dy, z = self.vertices[i]
            dx, dy = dx - x, dy - y
            self.vertices[i] = (x + dx * c - dy * s, y + dx * s + dy * c, z)

    def icon(self, y, z, size):
        # A painted warning outline sits flush in the cover's lower field.
        large = [(-size*0.52, -size*0.32), (0, size*0.60), (size*0.52, -size*0.32)]
        outer = self.ring([(x, y, z+b) for x, b in large], {CHEST: 1})
        inner = self.ring([(x*0.69, y, z+b*0.69) for x, b in large], {CHEST: 1})
        for i in range(3):
            j = (i+1) % 3
            self.face((outer[i], outer[j], inner[j], inner[i]), "yellow")
        self.face(self.ring([(-0.0008,y,z-0.001),(0.0008,y,z-0.001),(0.0012,y,z+0.004),(-0.0012,y,z+0.004)], {CHEST: 1}), "yellow")
        self.face(self.ring([(-0.0008,y,z-0.004),(0.0008,y,z-0.004),(0.0008,y,z-0.0026),(-0.0008,y,z-0.0026)], {CHEST: 1}), "yellow")

    def link(self, lod, collection, rig, label, part="upper_frame", node=None):
        name = f"{label} LOD{lod}"
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update()
        for key in MATERIALS:
            mesh.materials.append(pack_finish(key))
        for poly, slot, smooth in zip(mesh.polygons, self.materials, self.smooth):
            poly.material_index = slot
            poly.use_smooth = smooth
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        groups = {}
        for vertex_index, weights in enumerate(self.weights):
            for bone, weight in weights.items():
                if bone not in groups:
                    if bone not in rig.data.bones:
                        raise ValueError(f"Missing powerpack bone {bone}")
                    groups[bone] = obj.vertex_groups.new(name=bone)
                groups[bone].add([vertex_index], weight, "REPLACE")
        mod = obj.modifiers.new("EFT_Bind deformation", "ARMATURE")
        mod.object = rig
        obj.parent = rig
        obj["part"] = part
        if part == "upper_frame":
            tag = mesh.attributes.new(name="frame_geometry", type="BOOLEAN", domain="FACE")
            tag.data.foreach_set("value", [True] * len(mesh.polygons))
        if node:
            obj["frame_node"] = node
        obj["lod"] = lod
        obj["provenance"] = "Original modelling from ref3.png back view and inset"
        return obj


def chassis(mesh, low):
    box = mesh.box
    bevel = 0 if low else 0.003
    for sign in (-1, 1):
        x = sign * 0.105
        box((x, 0.192, 1.384), (0.041, 0.037, 0.352), 0.006, "black", bevel)
        box((x, 0.213, 1.378), (0.030, 0.018, 0.322), 0 if low else 0.004, "black")
        for z in (1.249, 1.427, 1.526):
            box((x, 0.226, z), (0.039, 0.018, 0.031), 0.004, "frame")
    box((0, 0.207, 1.545), (0.233, 0.058, 0.036), 0 if low else 0.011, "frame", bevel)
    box((0, 0.234, 1.552), (0.135, 0.032, 0.022), 0.006, "plate", bevel)


def modules(mesh, low):
    def box(center, size, clip, mat, bevel=0):
        # Broader service enclosures share the same rail clearance at both LODs.
        x, y, z = center
        w, d, h = size
        mesh.box((x * 1.17, y + 0.012, z), (w * 1.17, d, h), clip, mat, bevel)

    bevel = 0 if low else 0.003
    mesh.box((0, 0.229, 1.410), (0.161, 0.087, 0.217), 0.012, "frame", bevel)
    box((0, 0.265, 1.470), (0.111, 0.021, 0.106), 0.008, "plate", bevel)
    box((0, 0.276, 1.491), (0.036, 0.005, 0.025), 0.004, "frame")
    box((0, 0.279, 1.491), (0.027, 0.002, 0.017), 0 if low else 0.003, "black")
    mesh.icon(0.288, 1.451, 0.019)

    # The cartridge below the recess sits proud of the surrounding chassis.
    box((0, 0.260, 1.377), (0.093, 0.013, 0.073), 0 if low else 0.005, "black")
    for sign in (-1, 1):
        box((sign*0.056, 0.264, 1.375), (0.013, 0.021, 0.082), 0.004, "frame")
    box((0, 0.269, 1.339), (0.111, 0.022, 0.014), 0.003, "frame")
    mesh.box((0, 0.242, 1.282), (0.145, 0.080, 0.075), 0.008, "frame", bevel)
    box((0, 0.272, 1.280), (0.099, 0.023, 0.048), 0.005, "black")
    if not low:
        for z in (1.274, 1.286):
            box((0, 0.284, z), (0.072, 0.005, 0.0024), 0, "frame")


def harness(mesh, sign, low):
    def mirrored(points):
        return [(sign*x, y, z) for x, y, z in points]

    def hose(points, weights, radius, finish, fittings):
        path = mirrored(points)
        mesh.tube(path, radius, finish, 5 if low else 7, weights)
        for lo, hi in fittings:
            point = Vector(path[lo])
            collar(mesh, point, Vector(path[hi]) - point, radius * 1.60,
                   radius * 3.5, weights[lo], low)

    chest = {CHEST: 1}
    side = "L" if sign > 0 else "R"
    collar_bone = f"Base Human{side}Collarbone"
    upper_bone = f"Base Human{side}Upperarm"
    collar_only = {collar_bone: 1}
    port = {collar_bone: .33, upper_bone: .67}

    # The black supply line bridges the rail and back of the shoulder enclosure.
    hose([(0.112, .225, 1.472), (.118, .245, 1.489), (.130, .253, 1.527),
          (.147, .244, 1.559), (.162, .217, 1.577), (.165, .195, 1.579)],
         [chest, chest, chest, {CHEST: .50, collar_bone: .50}, collar_only, collar_only],
         .006, "black", ((0, 1), (-1, -2)))

    # The return loop stands clear behind the pauldron, then bends into the
    # upper drive fitting. Both ends follow their own mounting bones.
    x, y, z = (.2863, .1159, 1.4168) if sign > 0 else (.2874, .1165, 1.4170)
    hose([(.212, .182, 1.581), (.228, .196, 1.576), (.249, .211, 1.554),
          (.272, .218, 1.518), (.290, .207, 1.478), (.296, .178, 1.447),
          (.294, .146, 1.429), (x, y, z)],
         [collar_only, collar_only, {collar_bone: .85, upper_bone: .15},
          {collar_bone: .72, upper_bone: .28}, {collar_bone: .55, upper_bone: .45},
          {collar_bone: .40, upper_bone: .60}, port, port],
         .0057, "yellow", ((0, 1), (-1, -2)))

    # The trunk joins the belt manifold; the independent hinge loop begins
    # on the same manifold in lower_frame.py.
    hose([(.112, .225, 1.275), (.119, .242, 1.260), (.136, .243, 1.230),
          (.165, .227, 1.200), (.184, .197, 1.173), (.193, .156, 1.141),
          (.191, .109, 1.116), (.190, .079, 1.098)],
         [chest, chest, {CHEST: .70, WAIST: .30}, {CHEST: .40, WAIST: .60},
          {WAIST: .86, PELVIS: .14}, {WAIST: .50, PELVIS: .50},
          {WAIST: .19, PELVIS: .81}, {PELVIS: 1}],
         .0058, "yellow", ((0, 1),))


def collar(mesh, center, direction, radius, length, weight, low):
    point = Vector(center)
    axis = Vector(direction).normalized()
    profile = [(-.53, .74), (-.30, 1), (.30, 1), (.53, .74)]
    if radius >= .018 and not low:
        profile = [(-.64, .58), (-.40, .58), (-.31, 1), (.31, 1), (.40, .58), (.64, .58)]
    elif low and radius < .018:
        profile = [(-.53, 1), (.53, 1)]
    sides = (10 if radius >= .018 else 6) if not low else (8 if radius >= .018 else 5)
    reference = Vector((0, 0, 1)) if abs(axis.z) < .95 else Vector((0, 1, 0))
    cross = reference.cross(axis).normalized()
    other = axis.cross(cross)
    rings = [mesh.ring([point + axis * length * t + radius * r *
                        (cross * cos(2 * pi * j / sides) + other * sin(2 * pi * j / sides))
                        for j in range(sides)], weight) for t, r in profile]
    mesh.face(rings[0], "steel")
    for i, (a, b) in enumerate(zip(rings, rings[1:])):
        mesh.bridge(a, b, "frame" if i == len(rings) // 2 - 1 else "steel", len(rings) > 2 and i == len(rings) // 2 - 1)
    mesh.face(rings[-1], "steel")


def open_panel(mesh, x, z, y, size, opening, weight, low):
    """Structural plate with a perimeter chamfer and a full depth opening."""
    w, d, h = size
    ow, oh = opening
    lip = .003 if not low else 0
    outer = chamfered_outline(w, h, .008)
    face = chamfered_outline(w - 2 * lip, h - 2 * lip, .006)
    hole = chamfered_outline(ow, oh, .004)
    stations = [(face, -d / 2), (face, d / 2), (hole, d / 2), (hole, -d / 2)]
    if not low:
        stations[1:1] = [(outer, -d / 2 + lip), (outer, d / 2 - lip)]
    rings = [mesh.ring([(x + a, y + center, z + b) for a, b in outline], weight)
             for outline, center in stations]
    for i, (a, b) in enumerate(zip(rings, rings[1:] + rings[:1])):
        mesh.bridge(a, b, "steel" if not low and i in (0, 2, 4) else "frame")


def spine(mesh, low):
    chest = {CHEST: 1.0}
    waist = {WAIST: 1.0}
    pelvis = {PELVIS: 1.0}
    bevel = 0 if low else .003
    mid = (0, .194, 1.238)
    lower = (0, .180, 1.175)
    mesh.beam([(0, .190, 1.550), (0, .192, 1.304), mid],
              .102, .045, [chest, chest, waist])
    mesh.beam([mid, lower, (0, .192, 1.099)], .081, .039, [waist, waist, pelvis])
    mesh.box((0, .190, 1.231), (.087, .038, .039), .006, "frame", bevel, waist)
    mesh.box((0, .188, 1.102), (.100, .036, .053), .008, "frame", bevel, pelvis)
    # Both pack rails seat into the upper, middle and heel crossmembers.
    for z in (1.259, 1.426, 1.527):
        mesh.box((0, .202, z), (.254, .056, .037), .007, "frame", bevel)
        if not low or z == 1.527:
            for sign in (-1, 1):
                collar(mesh, (sign * .101, .225, z), (0, 1, 0), .011, .013, chest, low)
    for sign in (-1, 1):
        x = sign * .081
        open_panel(mesh, x, 1.339, .206, (.063, .037, .153), (.030, .084), chest, True)
        mesh.beam([(x, .210, 1.282), (sign * .056, .213, 1.249),
                   (sign * .020, .206, 1.234)], .025, .020, [chest, chest, waist])
        if not low:
            collar(mesh, (sign * .110, .227, 1.372), (0, 1, 0), .009, .012, chest, low)
    for z, r, weight in ((1.230, .027, waist), (1.104, .023, pelvis)):
        collar(mesh, (0, .205, z), (0, 1, 0), r, .022, weight, low)
    drive_fan(mesh, low, waist)


def drive_fan(mesh, low, weight):
    """Rear-facing impeller in a circular shroud below the pack's heel."""
    height = 1.205
    bevel = 0 if low else .004
    mesh.box((0, .224, height), (.122, .062, .107), .019, "frame", bevel, weight)
    mesh.box((0, .256, height), (.117, .027, .102), .023, "black", bevel, weight)
    sides = 12 if low else 20
    profile = ((.254, .050), (.276, .055), (.295, .055), (.301, .050),
               (.301, .044), (.278, .043), (.254, .044))
    if low:
        profile = ((.254, .050), (.295, .054), (.301, .045), (.254, .044))
    rims = [mesh.ring([(r*cos(2*pi*j/sides), y, height + r*sin(2*pi*j/sides))
                       for j in range(sides)], weight) for y, r in profile]
    for i, (a, b) in enumerate(zip(rims, rims[1:] + rims[:1])):
        mesh.bridge(a, b, "steel" if i == (2 if low else 3) else "frame")
    collar(mesh, (0, .280, height), (0, 1, 0), .014, .028, weight, low)
    count = 5 if low else 8
    for i in range(count):
        theta = 2*pi*i/count
        footprint = ((.010, 0), (.023, .16), (.041, .48), (.040, .69), (.026, .54), (.012, .34))
        blade = [mesh.ring([(r*cos(theta + a), y + .20*r, height + r*sin(theta + a))
                            for r, a in footprint], weight) for y in (.268, .272)]
        mesh.face(blade[0], "frame")
        mesh.bridge(*blade, "frame")
        mesh.face(reversed(blade[-1]), "steel")
    for z in (-.023, .023):
        x = .042
        mesh.beam([(-x, .294, height + z), (0, .298, height + z), (.042, .294, height + z)],
                  .0035, .004, [weight] * 3)
    if not low:
        for x in (-.048, .048):
            for z in (-.038, .038):
                collar(mesh, (x, .267, height + z), (0, 1, 0), .0045, .009, weight, low)


def belt(mesh, low):
    pelvis = {PELVIS: 1.0}
    # Closed waist ring and clamp shoes. Both lug centers match lower_frame.py.
    outline = [(0, -.193), (.127, -.169), (.183, -.116), (.214, -.035),
               (.217, .018), (.209, .061), (.192, .103), (.125, .165), (0, .198)]
    outline += [(-x, y) for x, y in reversed(outline[1:-1])]
    profile = ((1.084, .003), (1.088, 0), (1.115, 0), (1.120, .004),
               (1.120, .015), (1.084, .015))
    if low:
        profile = ((1.084, 0), (1.120, 0), (1.120, .015), (1.084, .015))
    rings = [mesh.ring([(x * (1 - inset / .217), y * (1 - inset / .198), z)
                        for x, y in outline], pelvis) for z, inset in profile]
    for i, (a, b) in enumerate(zip(rings, rings[1:] + rings[:1])):
        mesh.bridge(a, b, "steel" if not low and i in (0, 2) else "frame")

    for sign in (-1, 1):
        mesh.box((sign * .150, -.135, 1.104), (.062, .033, .044), .007, "frame",
                 .003 if not low else 0, pelvis)
        mesh.box((sign * .212, .018, 1.096), (.035, .057, .045), .006, "frame",
                 .003 if not low else 0, pelvis)
        collar(mesh, (sign * .219, .018, 1.096), (sign, 0, 0), .019, .030, pelvis, low)
        collar(mesh, (sign * .190, .079, 1.098), (sign, 0, 0), .013, .028, pelvis, low)
        center = (sign * .145, .142, 1.105)
        start = len(mesh.vertices)
        bevel = 0 if low else .003
        mesh.box(center, (.100, .047, .069), .011, "frame", bevel, pelvis)
        mesh.box((center[0], .165, 1.104), (.079, .017, .050), .008, "steel", bevel, pelvis)
        mesh.box((center[0], .175, 1.106), (.059, .006, .032), .005, "black", 0, pelvis)
        for z in ((1.101, 1.114) if low else (1.099, 1.108, 1.117)):
            mesh.box((center[0], .179, z), (.048, .006, .003), 0, "frame", 0, pelvis)
        if not low:
            for dx in (-.033, .033):
                collar(mesh, (center[0] + dx, .173, 1.108), (0, 1, 0), .0037, .007, pelvis, low)
        mesh.turn_about(start, center, -sign * .72)
        if not low:
            for z in (1.093, 1.114):
                collar(mesh, (sign * .033, -.210, z), (0, -1, 0), .0045, .008, pelvis, low)
    mesh.box((0, -.195, 1.104), (.088, .034, .047), .009, "frame",
             .004 if not low else 0, pelvis)
    open_panel(mesh, 0, 1.104, -.216, (.067, .010, .030), (.044, .013), pelvis, low)
    belt_battery(mesh, low, pelvis)


def belt_battery(mesh, low, weight):
    """Removable belt battery seated in a rear dovetail with exposed eject tabs."""
    bevel = 0 if low else .004
    mesh.box((0, .190, 1.105), (.149, .032, .070), .009, "frame", bevel, weight)
    mesh.box((0, .220, 1.104), (.125, .053, .068), .012, "plate", bevel, weight)
    mesh.box((0, .247, 1.104), (.093, .010, .046), .007, "black", bevel, weight)
    for sign in (-1, 1):
        x = sign * .052
        mesh.box((x, .230, 1.104), (.012, .042, .075), .005, "frame", bevel, weight)
        mesh.box((x, .253, 1.104), (.010, .008, .032), .003, "yellow", 0, weight)
        mesh.box((sign*.024, .253, 1.119), (.026, .005, .005), .001, "steel", 0, weight)
    for x in (-.019, -.005, .009):
        mesh.box((x, .254, 1.102), (.009, .004, .010), .001, "yellow", 0, weight)
    mesh.box((.023, .254, 1.102), (.009, .004, .010), .001, "strap", 0, weight)


def tassets(mesh, low):
    pelvis = {PELVIS: 1.0}
    bevel = 0 if low else .003
    for sign in (-1, 1):
        thigh_bone = f"Base Human{'L' if sign > 0 else 'R'}Thigh1"
        thigh = {thigh_bone: 1.0}
        x, y = sign * .225, -.069
        center = (x, y, 1.048)
        start = len(mesh.vertices)
        mesh.box((x, y + .007, 1.091), (.061, .031, .043), .006, "frame", bevel, pelvis)
        mesh.turn_about(start, center, sign * 1.15)

        # A broad floating hanger follows the hip at the top and the thigh at
        # the attachment plate. The lower plate remains rigid as the hip flexes.
        mesh.beam([(sign * .226, -.072, 1.091), (sign * .243, -.106, 1.040),
                   (sign * .255, -.124, .948)], .045, .016,
                  [pelvis, {PELVIS: .66, thigh_bone: .34}, thigh])
        x, y, z = sign * .253, -.132, .911
        center = (x, y, z)
        start = len(mesh.vertices)
        mesh.box((x, y+.005, z), (.084, .020, .121), .017, "strap", bevel, thigh)
        mesh.box((x, y-.006, z-.003), (.080, .017, .111), .017, "plate", bevel, thigh)
        mesh.box((x, y-.016, z+.003), (.056, .007, .072), .014, "plate", bevel, thigh)
        for dx in (-.025, .025):
            collar(mesh, (x + dx, y - .015, z+.041), (0, -1, 0), .0045, .011, thigh, low)
        mesh.turn_about(start, center, sign * 1.00)


def shoulder(mesh, sign, low):
    chest = {CHEST: 1.0}
    bone = f"Base Human{'L' if sign > 0 else 'R'}Collarbone"
    collar_bone = {bone: 1.0}
    path = [(sign * .062, .200, 1.527), (sign * .104, .195, 1.552),
            (sign * .136, .167, 1.563), (sign * .177, .121, 1.553)]
    mesh.beam(path, .053, .045, [chest, chest, {CHEST: .55, bone: .45}, collar_bone])
    collar(mesh, path[-1], (sign, .22, 0), .024, .046, collar_bone, low)
    collar(mesh, path[1], (0, 1, 0), .022, .026, chest, low)
    bevel = 0 if low else .004
    x = sign * .167
    mesh.box((x, .126, 1.592), (.104, .136, .078), .014, "frame", bevel, collar_bone)
    mesh.box((x, .125, 1.626), (.087, .119, .028), .009, "steel", bevel, collar_bone)
    mesh.box((x, .125, 1.643), (.072, .103, .012), .005, "frame", 0, collar_bone)
    open_panel(mesh, x, 1.598, .197, (.084, .013, .039), (.059, .020), collar_bone, low)
    for j in range(4 if low else 6):
        dx = (j - (1.5 if low else 2.5)) * .009
        mesh.box((x + dx, .197, 1.598), (.004, .012, .022), 0, "steel", 0, collar_bone)
    for dx in (-.035, .035):
        collar(mesh, (x + dx, .067, 1.604), (0, -1, 0), .0055, .016, collar_bone, low)


def housing_details(mesh, low):
    # Retain the original enclosure outline; the stand-off louvre cage has
    # genuinely open windows and the power cartridge has two working catches.
    bevel = .0025 if not low else 0
    fixed = {CHEST: 1.0}
    open_panel(mesh, 0, 1.382, .287, (.118, .014, .081), (.092, .058), fixed, low)
    for i in range(5 if not low else 4):
        z = 1.360 + i * .011
        mesh.beam([(-.050, .286, z), (0, .296, z + .002), (.050, .286, z)],
                  .005, .010, [fixed] * 3)
    for sign in (-1, 1):
        x = sign * .110
        for z in (1.477, 1.311):
            open_panel(mesh, x, z, .245, (.038, .019, .061), (.017, .031), fixed, low)
            mesh.box((x, .259, z - .022), (.025, .016, .012), .004, "steel", bevel)
            collar(mesh, (x, .261, z + .023), (1, 0, 0), .0063, .028, fixed, low)


def build(lod, collection, rig):
    low = lod != 0
    housing = PackMesh()
    modules(housing, low)
    housing_details(housing, low)
    spine_frame = PackMesh()
    chassis(spine_frame, low)
    spine(spine_frame, low)
    ring_frame = PackMesh()
    belt(ring_frame, low)
    waist_armor = PackMesh()
    tassets(waist_armor, low)
    objects = [
        housing.link(lod, collection, rig, "Powerpack cartridge and covers", "pack"),
        spine_frame.link(lod, collection, rig, "Powerpack spine cradle", node="spine"),
        ring_frame.link(lod, collection, rig, "Hip belt ring", node="belt"),
        waist_armor.link(lod, collection, rig, "Belt suspension and hip tassets", "waist_armor"),
    ]
    for sign, side in ((-1, "R"), (1, "L")):
        yoke = PackMesh()
        shoulder(yoke, sign, low)
        objects.append(yoke.link(lod, collection, rig, f"{side} shoulder yoke", node=f"shoulder.{side}"))
        lines = PackMesh()
        harness(lines, sign, low)
        objects.append(lines.link(lod, collection, rig, f"{side} pack hydraulic lines"))
    return objects
