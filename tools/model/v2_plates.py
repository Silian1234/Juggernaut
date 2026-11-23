"""Manufactured, rigid plates and joint hardware for the Juggernaut bind scene."""
import math
from functools import lru_cache

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


UP = Vector((0, 0, 1))
FRONT = Vector((0, -1, 0))
OCTAGON = ((-.68, -1), (.68, -1), (1, -.65), (1, .64),
           (.72, 1), (-.72, 1), (-1, .64), (-1, -.65))
BREAST = ((-.60, -1), (.60, -1), (.90, -.69), (1, .28), (.96, .80),
          (.69, 1), (.38, .96), (.24, .77), (-.24, .77),
          (-.38, .96), (-.69, 1), (-.96, .80), (-1, .28), (-.90, -.69))
SHINGLE = ((-.76, -.93), (.76, -.93), (1, -.46), (.94, .67),
           (.67, .97), (-.67, .97), (-.94, .67), (-1, -.46))
GREAVE = ((-.39, -1), (.39, -1), (.63, -.74), (.94, .35),
          (1, .72), (.72, .97), (0, .91), (-.72, .97), (-1, .72), (-.94, .35))
SPAULDER = ((-.75, -.95), (.75, -.95), (1, -.53), (.96, .52),
            (.66, .92), (0, 1), (-.66, .92), (-.96, .52))
KNEE = ((0, -1), (.62, -.83), (.98, -.27), (.91, .54),
        (.63, .88), (0, 1), (-.63, .88), (-.91, .54), (-.98, -.27))


def _bvh(objects):
    points, faces = [], []
    for obj in objects:
        offset = len(points)
        points.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
        obj.data.calc_loop_triangles()
        faces.extend(tuple(offset + i for i in face.vertices) for face in obj.data.loop_triangles)
    return BVHTree.FromPolygons(points, faces, all_triangles=True)


def _rounded(outline, steps, rounding, split_edges):
    points = [Vector(value) for value in outline]
    perimeter = []
    for i, corner in enumerate(points):
        enter = corner.lerp(points[i - 1], rounding)
        leave = corner.lerp(points[(i + 1) % len(points)], rounding)
        for j in range(steps + 1):
            t = j / steps
            perimeter.append(enter.lerp(corner, t).lerp(corner.lerp(leave, t), t))
        next_enter = points[(i + 1) % len(points)].lerp(corner, rounding)
        if split_edges:
            perimeter.append(leave.lerp(next_enter, .5))
    return perimeter


class Armor:
    def __init__(self, lod, collection, rig, revision="V2"):
        self.lod = lod
        self.collection = collection
        self.rig = rig
        self.prefix = ("EXO1_" if lod else "EXO_") + revision
        self.objects = []
        padding = [obj for obj in collection.objects if obj.get('v2_padding') or obj.get('v3_fabric')]
        clothing = [bpy.data.objects[name] for name in ('REF_top', 'REF_pants')]
        bpy.context.view_layer.update()
        self.surface = _bvh([*clothing, *padding])

    def head(self, name):
        return self.rig.matrix_world @ self.rig.data.bones['Base Human' + name].head_local

    def mesh(self, name, bone, family, vertices, faces, uv, smooth=True):
        mesh = bpy.data.meshes.new(self.prefix + name)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        layer = mesh.uv_layers.new(name='UVMap')
        for loop in mesh.loops:
            layer.data[loop.index].uv = uv[loop.vertex_index]
        for polygon in mesh.polygons:
            polygon.use_smooth = smooth
        obj = bpy.data.objects.new(mesh.name, mesh)
        self.collection.objects.link(obj)
        material = bpy.data.materials.get('V2_' + family)
        if material is None:
            material = bpy.data.materials.new('V2_' + family)
        mesh.materials.append(material)
        group = obj.vertex_groups.new(name='Base Human' + bone)
        group.add(list(range(len(vertices))), 1.0, 'REPLACE')
        obj.parent = self.rig
        obj.modifiers.new('EFT Bind', 'ARMATURE').object = self.rig
        obj['v2_rigid'] = True
        self.objects.append(obj)
        return obj

    def shell(self, name, bone, family, surface, thickness, dome, shape=OCTAGON,
              rounding=.23):
        # Rolled lip on both sides of the laminate; the crown is part of the shell.
        fine = thickness >= .015
        steps = 1 if self.lod or not fine else 2
        contour = _rounded(shape, steps, rounding, split_edges=fine and not self.lod)
        if self.lod:
            levels = ((1, .08), (1, .60), (.874, 1), (.49, 1))
        elif not fine:
            levels = ((.98, .04), (1, .37), (.981, .71), (.872, 1), (.51, 1))
        else:
            levels = ((.68, 0), (.966, .02), (1, .24), (1, .57),
                      (.979, .83), (.894, 1), (.596, 1), (.28, 1))
        vertices, uv, faces = [], [], []
        count = len(contour)

        def vertex(u, v, section):
            rise = dome * max(0, 1 - (.63 * u * u + .43 * v * v))
            vertices.append(surface(u, v, section * thickness + rise))
            uv.append((.5 + u * .44, .5 + v * .44))

        for i, (scale, section) in enumerate(levels):
            for u, v in contour:
                vertex(u * scale, v * scale, section)
            if i:
                self._join(faces, (i - 1) * count, i * count, count)
        back, front = len(vertices), len(vertices) + 1
        vertex(0, 0, 0)
        vertex(0, 0, 1)
        last = (len(levels) - 1) * count
        for i in range(count):
            j = (i + 1) % count
            faces.extend(((j, i, back), (last + i, last + j, front)))
        obj = self.mesh(name, bone, family, vertices, faces, uv)
        if fine:
            # A continuous analytic crown normal avoids bands from the irregular rim tessellation.
            normals = [vertex.normal.copy() for vertex in obj.data.vertices]
            first_crown = (len(levels) - (1 if self.lod else 2)) * count
            for index in (*range(first_crown, len(vertices) - 2), front):
                u, v = ((coordinate - .5) / .44 for coordinate in uv[index])

                def crown(x, y):
                    return surface(x, y, thickness + dome * (1 - .63 * x * x - .43 * y * y))

                horizontal = crown(u + .002, v) - crown(u - .002, v)
                vertical = crown(u, v + .002) - crown(u, v - .002)
                normals[index] = horizontal.cross(vertical).normalized()
            obj.data.normals_split_custom_set_from_vertices(normals)
        if thickness >= .017 and family in {'olive', 'graphite'}:
            edge = 'V2_edge' if family == 'olive' else 'V2_edge_dark'
            material = bpy.data.materials.get(edge) or bpy.data.materials.new(edge)
            obj.data.materials.append(material)
            band = 1 if self.lod else 4
            for polygon in list(obj.data.polygons)[band * count:(band + 1) * count]:
                polygon.material_index = 1
        return obj

    def decal(self, name, bone, family, target, center, axis, width, height):
        surface = self.planar(center, axis, UP, width * .5, height * .5)
        target_surface = _bvh((target,))
        count = 9
        verts, uv, faces = [], [], []
        for j in range(count):
            for i in range(count):
                u, v = i / (count - 1), j / (count - 1)
                point = surface(2 * u - 1, 2 * v - 1, .07)
                hit, normal, _, _ = target_surface.ray_cast(point, -axis, .14)
                if hit is None:
                    raise ValueError(f'{name} extends beyond {target.name}')
                verts.append(hit + normal * .00055)
                uv.append((u, v))
                if i < count - 1 and j < count - 1:
                    k = j * count + i
                    faces.extend(((k, k + 1, k + count + 1), (k, k + count + 1, k + count)))
        obj = self.mesh(name, bone, family, verts, faces, uv)
        obj['v2_swatch_uv'] = True

    @staticmethod
    def _join(faces, previous, current, count):
        for i in range(count):
            j = (i + 1) % count
            faces.append((previous + i, previous + j, current + j, current + i))

    def turning(self, name, bone, family, origin, axis, profile, sides=None):
        origin, axis = Vector(origin), Vector(axis).normalized()
        u = axis.cross(UP if abs(axis.z) < .9 else FRONT).normalized()
        v = axis.cross(u)
        sides = sides or (10 if self.lod else 20)
        vertices, faces, uv = [], [], []
        radius = max(r for r, _ in profile)
        for i, (r, height) in enumerate(profile):
            for j in range(sides):
                angle = j * math.tau / sides
                x, y = math.cos(angle), math.sin(angle)
                vertices.append(origin + axis * height + r * (x * u + y * v))
                uv.append((.5 + .46 * r / radius * x, .5 + .46 * r / radius * y))
            if i:
                self._join(faces, (i - 1) * sides, i * sides, sides)
        faces.append(tuple(reversed(range(sides))))
        faces.append(tuple(range(len(vertices) - sides, len(vertices))))
        self.mesh(name, bone, family, vertices, faces, uv, smooth=sides > 8)

    def fastener(self, name, bone, surface, u, v, height, r=.008, target=None):
        if self.lod:
            return
        x = surface(u + .014, v, height) - surface(u - .014, v, height)
        y = surface(u, v + .014, height) - surface(u, v - .014, height)
        axis = x.cross(y).normalized()
        point = surface(u, v, height)
        if target is not None:
            hit, normal, _, _ = _bvh((target,)).ray_cast(point + axis * .04, -axis, .08)
            if hit is None:
                raise ValueError(f'{name} extends beyond {target.name}')
            axis = normal
            point = hit
        self.turning(name + 'Washer', bone, 'graphite', point, axis,
                     ((r * .81, -.004), (r, -.002), (r * .83, .003)), sides=10)
        self.turning(name + 'Hex', bone, 'steel', point, axis,
                     ((r * .59, .000), (r * .68, .003), (r * .56, .006)), sides=6)

    def planar(self, origin, axis, up, width, height, wrap=0, taper=0):
        origin, axis = Vector(origin), Vector(axis).normalized()
        right = Vector(up).cross(axis).normalized()
        up = axis.cross(right)
        return lambda u, v, d: (origin + right * u * width * (1 + taper * v)
                                + up * v * height + axis * (d - wrap * u * u))

    def arc(self, start, end, axis, half_angle, radii, taper=0, edge_sweep=0):
        start, end, axis = Vector(start), Vector(end), Vector(axis)
        up = (end - start).normalized()
        right = up.cross(axis).normalized()
        axis = right.cross(up)
        angle = math.radians(half_angle)

        def point(u, v, depth):
            theta = u * angle * (1 + taper * v)
            outward = axis * math.cos(theta) + right * math.sin(theta)
            fraction = (v + 1) * .5 + edge_sweep * u * u
            radius = radii[0] * (1 - fraction) + radii[1] * fraction
            return start.lerp(end, fraction) + outward * (depth + radius)

        return point

    def fit_plane(self, origin, axis, up, width, height, wrap=0, limit=.18):
        axis = Vector(axis).normalized()
        plane = self.planar(origin, axis, up, width, height, wrap)

        @lru_cache(maxsize=2048)
        def sampled(i, j):
            target = plane(i / 12, j / 12, 0)
            location, _, _, _ = self.surface.ray_cast(target + axis * limit, -axis, limit + .03)
            return max(0, (location - target).dot(axis) + .007) if location else 0

        def point(u, v, depth):
            a, b = u * 12, v * 12
            i, j = math.floor(a), math.floor(b)
            a, b = a - i, b - j
            rise = (
                sampled(i, j) * (1 - a) * (1 - b) + sampled(i + 1, j) * a * (1 - b)
                + sampled(i, j + 1) * (1 - a) * b + sampled(i + 1, j + 1) * a * b
            )
            return plane(u, v, depth + rise)

        return point


def torso(a):
    chest = a.planar((0, -.203, 1.415), FRONT, UP, .222, .154, .060, .08)
    a.shell('Breastplate', 'Spine3', 'olive', chest, .032, .032, BREAST)
    # The padded carrier is thick through the sternum and rolls into the sides.
    # Its front nests into the ballistic plate and its rear seats on the jacket.
    # The coarser rear fan needs a little extra clearance from the reference jacket.
    carrier_relief = .010 if a.lod else 0
    chest_carrier = lambda u, v, d: chest(u * .95, v * .92, d - .059 + carrier_relief)
    a.shell('BreastplateTraumaPad', 'Spine3', 'fabricdark', chest_carrier,
            .055 - carrier_relief, .041, BREAST)
    inset = lambda u, v, z: chest(u * .70, v * .55 + .10, z + .047)
    liner = a.shell('BreastplateLiner', 'Spine3', 'olive', inset, .015, .010, BREAST)
    a.decal('ChestIdentification', 'Spine3', 'chest_id', liner, (0, -.280, 1.433),
            FRONT, .100, .040)
    for j, (u, v) in enumerate(((-.78, .57), (.78, .57), (-.64, -.67), (.64, -.67))):
        a.fastener('BreastPlateAnchor' + str(j), 'Spine3', chest, u, v, .050, .010)
    # Raised shoulders of the neckline leave a U-shaped opening for neck motion.
    yoke = a.fit_plane((0, -.086, 1.543), FRONT, UP, .164, .049, .041, .11)
    a.shell('GorgetFront', 'Spine3', 'graphite', yoke, .021, .010, BREAST)
    rear_yoke = a.fit_plane((0, .143, 1.544), -FRONT, UP, .156, .048, .032, .12)
    a.shell('GorgetRear', 'Spine3', 'graphite', rear_yoke, .022, .009, BREAST)
    back = a.planar((0, .184, 1.428), -FRONT, UP, .220, .123, .062)
    a.shell('ScapularShell', 'Spine3', 'olive', back, .026, .010, BREAST)

    for i, (z, width, y, bone) in enumerate((
        (1.258, .174, -.168, 'Spine3'), (1.207, .181, -.169, 'Spine2'),
        (1.155, .175, -.156, 'Spine2'), (1.102, .168, -.143, 'Spine1'),
    )):
        plate = a.planar((0, y - .025, z), FRONT, UP, width, .037, .045)
        a.shell('AbdominalLame' + str(i), bone, 'olive' if i < 3 else 'graphite',
                plate, .020, .016, SHINGLE)
        for j, u in enumerate((-.67, .67)):
            a.fastener(f'AbdominalPin{i}{j}', bone, plate, u, -.29, .033, .006)

    rim = a.arc((0, .032, 1.544), (0, .032, 1.649), -FRONT,
                65, (.156, .149), taper=-.05, edge_sweep=-.10)
    a.shell('RaisedRearGorget', 'Spine3', 'graphite', rim, .021, .009, SPAULDER)
    for suffix, sign in (('L', 1), ('R', -1)):
        side = Vector((sign, 0, 0))
        carrier_strap = a.arc((0, .019, 1.302), (0, .019, 1.336),
                              (sign * .66, -.75, 0), 31, (.236, .255), taper=.01)
        a.shell('ChestCarrierRestraint' + suffix, 'Spine3', 'strap', carrier_strap,
                .008, .004, SHINGLE)
        side_yoke = a.arc((0, .026, 1.565), (0, .026, 1.624), (sign, .08, 0),
                          66, (.169, .145), taper=-.12, edge_sweep=-.04)

        def collar(u, v, depth):
            cup_relief = .007 * (1 - u * u) * ((v + 1) * .5) ** 2
            return side_yoke(u, v, depth) - UP * cup_relief

        a.shell('RaisedSideGorget' + suffix, 'Spine3', 'olive', collar, .021, .010, SPAULDER)
        bridge = lambda u, v, d: Vector((
            sign * (.195 + .015 * (1 - v * v)) + .032 * u,
            -.027 + .137 * v,
            1.57 + .049 * (1 - v * v) + .060 * v + d,
        ))
        a.shell('ShoulderLoadWebbing' + suffix, 'Spine3', 'strap', bridge, .012, .004)
        bridge_tag = a.planar((sign * .193, -.158, 1.514), (sign * .18, -.82, .54),
                              UP, .028, .035, .006)
        a.shell('ShoulderHarnessAnchor' + suffix, 'Spine3', 'graphite', bridge_tag,
                .017, .007, SHINGLE)
        a.fastener('ShoulderHarnessStud' + suffix, 'Spine3', bridge_tag, 0, .27, .022, .009)
        wing = a.fit_plane((sign * .147, .151, 1.400), (sign * .50, .86, .10), UP,
                           .084, .116, .034, .14)
        a.shell('ScapularWing' + suffix, 'Spine3', 'olive', wing, .027, .012, BREAST)
        for i, z in enumerate((1.283, 1.238, 1.178, 1.119)):
            start_r, end_r = ((.204, .221), (.202, .214), (.200, .209), (.204, .208))[i]
            top = .021 if i == 0 else .037
            flank = a.arc((0, .041, z - .037), (0, .041, z + top), side, 53,
                          (start_r, end_r), taper=.08)
            bone = ('Spine3', 'Spine2', 'Spine2', 'Spine1')[i]
            a.shell(f'FlankLame{suffix}{i}', bone, 'graphite' if i == 3 else 'olive',
                    flank, .021, .012, SHINGLE)
            a.fastener(f'FlankRivet{suffix}{i}', bone, flank, .24, -.45, .031, .007)
        for i, z in enumerate((1.024, .967)):
            apron = a.arc((0, .02, z - .048), (0, .029, z + .043),
                          (.72 * sign, -.7, 0), 45, (.213, .225), taper=.07,
                          edge_sweep=.08)
            a.shell(f'FrontFauld{suffix}{i}', 'Pelvis', 'olive', apron, .022, .010, SHINGLE)
            rear = a.arc((0, .021, z - .047), (0, .024, z + .042),
                         (.59 * sign, .81, 0), 52, (.188, .191), taper=.10)
            a.shell(f'RearFauld{suffix}{i}', 'Pelvis', 'olive', rear, .023, .012, SHINGLE)
        belt = a.arc((0, .015, 1.029), (0, .015, 1.069), side, 76, (.225, .224))
        a.shell('HipWebbing' + suffix, 'Pelvis', 'strap', belt, .007, .002)
        latch = a.fit_plane((sign * .095, -.181, 1.054), (sign * .26, -.96, 0), UP,
                            .026, .025, .004, .095)
        a.shell('BeltLatch' + suffix, 'Pelvis', 'steel', latch, .018, .004)


def dock(a):
    # The fit report fixes this receiver and the standalone cell in Blender world space.
    # Preserve the original contact faces and dimensions, free space, and insertion axis.
    shapes = (
        ((0, .217, 1.285), .092, .119, ((1, -.004), (1, .004), (.94, .012))),
        ((-.073, .229, 1.285), .009, .107, ((1, -.005), (1, .025), (.87, .029))),
        ((.073, .229, 1.285), .009, .107, ((1, -.005), (1, .025), (.87, .029))),
        ((0, .23, 1.165), .055, .010, ((1, -.008), (.86, .020))),
    )
    vertices, faces, uv = [], [], []
    for origin, width, height, levels in shapes:
        plane = a.planar(origin, -FRONT, UP, width, height)
        first = len(vertices)
        for j, (scale, d) in enumerate(levels):
            for u, v in OCTAGON:
                vertices.append(plane(u * scale, v * scale, d))
                uv.append((.5 + u * scale * .45, .5 + v * scale * .45))
            if j:
                a._join(faces, first + (j - 1) * 8, first + j * 8, 8)
        faces.append(tuple(reversed(range(first, first + 8))))
        faces.append(tuple(range(len(vertices) - 8, len(vertices))))
    obj = a.mesh('JuggPowerDock', 'Spine3', 'steel', vertices, faces, uv, smooth=False)
    obj['cell_socket_center_m'] = (0, .272, 1.285)
    obj['cell_world_translation_m'] = (0, .2695, 1.28075)
    obj['cell_world_yaw_degrees'] = 180.0

    backplane = a.planar((0, .184, 1.285), -FRONT, UP, .144, .171, .021)
    a.shell('PowerPackArmoredBacking', 'Spine3', 'graphite', backplane, .023, .003, SHINGLE)
    top = a.planar((0, .244, 1.452), -FRONT, UP, .134, .037, .019)
    crown = a.shell('PowerPackCrown', 'Spine3', 'olive', top, .028, .008, SHINGLE)
    a.decal('ReceiverServiceMarking', 'Spine3', 'dock_service', crown, (0, .279, 1.452),
            -FRONT, .096, .040)
    lower = a.planar((0, .225, 1.12), -FRONT, UP, .136, .028, .020)
    a.shell('PowerPackSump', 'Spine3', 'olive', lower, .029, .008, SHINGLE)
    for suffix, sign in (('L', 1), ('R', -1)):
        skirt = a.planar((sign * .143, .229, 1.280), (sign * .80, .60, 0), UP,
                         .054, .164, .026)
        a.shell('PowerPackShoulder' + suffix, 'Spine3', 'graphite', skirt, .028, .009, SHINGLE)
        casing = a.planar((sign * .132, .234, 1.282), (sign * .22, .97, 0), UP,
                          .035, .166, .010)
        a.shell('PowerPackRailHousing' + suffix, 'Spine3', 'graphite', casing, .028, .014)
        cover = lambda u, v, d: casing(u * .82, v * .78, d + .032)
        a.shell('PowerPackRailArmor' + suffix, 'Spine3', 'olive', cover, .017, .006)
        for index, v in enumerate((-.78, .81)):
            a.fastener(f'PackRailScrew{suffix}{index}', 'Spine3', casing, 0, v, .039)
        for i in range(3 if a.lod else 6):
            x = sign * .128
            exhaust = a.planar((x, .286, 1.235 + i * (.026 if a.lod else .015)), -FRONT, UP,
                               .021, .0045, .006)
            a.shell(f'PackLouver{suffix}{i}', 'Spine3', 'steel', exhaust, .007, .002)
    locator = a.planar((.105, .283, 1.432), -FRONT, UP, .012, .005, .002)
    a.shell('ReceiverLockIndicator', 'Spine3', 'red', locator, .005, 0)


def _hub(a, name, bone, origin, axis, radius):
    profile = ((radius * .80, -.015), (radius, -.010), (radius, .009),
               (radius * .92, .015), (radius * .69, .020))
    a.turning(name + 'Housing', bone, 'graphite', origin, axis, profile)
    a.turning(name + 'Rotor', bone, 'steel', origin, axis,
              ((radius * .63, .019), (radius * .68, .022), (radius * .53, .026)))
    a.turning(name + 'Axle', bone, 'graphite', origin, axis,
              ((radius * .33, .025), (radius * .40, .028), (radius * .31, .032)),
              sides=8 if a.lod else 12)


def arm(a, side, sign):
    bone = lambda name: side + name
    head = lambda name: a.head(bone(name))
    shoulder, elbow, wrist = head('Upperarm'), head('Forearm1'), head('Palm')
    palm = head('Digit31')
    side_axis = Vector((sign, 0, 0))
    crown_axis = Vector((sign * .75, .25, .66)).normalized()
    pauldron = a.arc(shoulder.lerp(elbow, .44), shoulder.lerp(elbow, -.17), crown_axis,
                     92, (.132, .124), taper=-.07, edge_sweep=-.06)
    a.shell('ShoulderBowl' + side, bone('Upperarm'), 'olive', pauldron, .030, .020, SPAULDER)
    mask = lambda u, v, depth: pauldron(u * .70, v * .68 + .12, depth + .043)
    a.shell('ShoulderCap' + side, bone('Upperarm'), 'olive', mask, .018, .010, SPAULDER)
    for i, (lo, hi) in enumerate(((.73, .41), (.84, .65))):
        lame = a.arc(shoulder.lerp(elbow, lo), shoulder.lerp(elbow, hi), (sign, -.07, .34),
                     85, (.107, .118), taper=.10)
        a.shell(f'UpperArmLame{side}{i}', bone('Upperarm'), 'olive',
                lame, .024, .011, SHINGLE)
        for j, u in enumerate((-.65, .65)):
            a.fastener(f'ArmLaminateRivet{side}{i}{j}', bone('Upperarm'), lame, u, .33, .032, .007)
    band = a.arc(shoulder.lerp(elbow, .73), shoulder.lerp(elbow, .81), (sign * -.33, -.66, -.59),
                 75, (.098, .096), taper=.03)
    a.shell('UpperArmHarness' + side, bone('Upperarm'), 'strap', band, .008, .003)
    axis = (side_axis + UP * .10).normalized()
    _hub(a, 'ElbowJoint' + side, bone('Forearm1'), elbow + axis * .104, axis, .042)
    wrist_axis = Vector((sign * .82, -.10, .54))
    gauntlet = a.arc(wrist.lerp(elbow, .12), wrist.lerp(elbow, .78), wrist_axis,
                     93, (.089, .103), taper=.07)
    a.shell('Vambrace' + side, bone('Forearm1'), 'olive', gauntlet, .027, .014, GREAVE)
    forearm_top = lambda u, v, d: gauntlet(u * .53, v * .67 + .06, d + .035)
    a.shell('VambraceKeel' + side, bone('Forearm1'), 'graphite', forearm_top, .015, .008, KNEE)
    cuff = a.arc(wrist.lerp(elbow, .045), wrist.lerp(elbow, .21), wrist_axis,
                 111, (.095, .103), taper=.08)
    a.shell('WristCuff' + side, bone('Forearm3'), 'graphite', cuff, .017, .008)
    glove = a.fit_plane(wrist.lerp(palm, .58) + wrist_axis.normalized() * .030,
                        wrist_axis, wrist - palm, .048, .053, .012, .071)
    a.shell('Gauntlet' + side, bone('Palm'), 'olive', glove, .017, .007, SHINGLE)
    for digit in range(2, 6):
        root, joint = head(f'Digit{digit}1'), head(f'Digit{digit}2')
        knuckle = a.fit_plane(root.lerp(joint, .32) + wrist_axis.normalized() * .013,
                              wrist_axis, root - joint, .010, .018, .004, .055)
        a.shell(f'Knuckle{side}{digit}', bone(f'Digit{digit}1'), 'graphite', knuckle, .008, .003)


def leg(a, side, sign):
    bone = lambda name: side + name
    head = lambda name: a.head(bone(name))
    hip, knee, ankle, toe = head('Thigh1'), head('Calf'), head('Foot'), head('Toe')
    side_axis = Vector((sign, 0, 0))
    front_out = Vector((sign * .22, -1, 0))
    thigh = a.arc(hip.lerp(knee, .79), hip.lerp(knee, .21), (sign * .58, -.81, 0),
                  51, (.129, .161), taper=-.06, edge_sweep=.055)
    cuisses = a.shell('Cuisses' + side, bone('Thigh1'), 'olive', thigh, .029, .021, GREAVE)
    upper_thigh = a.arc(hip.lerp(knee, .31), hip.lerp(knee, .069), (sign * .88, -.58, 0),
                        62, (.193, .178), taper=.03)
    a.shell('HipTasset' + side, bone('Thigh1'), 'olive', upper_thigh, .027, .016, SPAULDER)
    thigh_side = a.arc(hip.lerp(knee, .63), hip.lerp(knee, .28), (sign * .99, .38, 0),
                       55, (.150, .161), taper=.06)
    a.shell('HipDriveArmor' + side, bone('Thigh1'), 'graphite', thigh_side, .025, .012, SHINGLE)
    rear_band = a.arc(hip.lerp(knee, .56), hip.lerp(knee, .49), -FRONT,
                      63, (.152, .159), taper=.06)
    a.shell('ThighHarness' + side, bone('Thigh1'), 'strap', rear_band, .007, .003)
    for j, x in enumerate((-.50, .50)):
        a.fastener(f'CuissesScrew{side}{j}', bone('Thigh1'), thigh, x, -.54, .044, .009,
                   target=cuisses)
    hinge = knee + side_axis * .122 + Vector((0, .012, 0))
    _hub(a, 'KneeJoint' + side, bone('Calf'), hinge, side_axis, .049)
    poleyn = a.arc(knee.lerp(ankle, .15), knee.lerp(ankle, -.13), front_out,
                   68, (.107, .120), taper=-.13)
    a.shell('Poleyn' + side, bone('Calf'), 'olive', poleyn, .032, .023, KNEE)
    strike = lambda u, v, depth: poleyn(u * .63, v * .55 + .12, depth + .046)
    a.shell('PoleynCrown' + side, bone('Calf'), 'olive', strike, .018, .010, KNEE)
    shin = a.arc(knee.lerp(ankle, .854), knee.lerp(ankle, .145), front_out,
                 97, (.134, .137), taper=.07, edge_sweep=.03)
    greave = a.shell('Greave' + side, bone('Calf'), 'olive', shin, .029, .017, GREAVE)
    ridge = lambda u, v, d: shin(u * .45, v * .72 + .03, d + .041)
    a.shell('GreaveKeel' + side, bone('Calf'), 'olive', ridge, .016, .010, GREAVE)
    rear = a.arc(knee.lerp(ankle, .89), knee.lerp(ankle, .49), (sign * .48, .88, 0),
                 76, (.106, .139), taper=.10)
    a.shell('CalfDriveCover' + side, bone('Calf'), 'graphite', rear, .026, .013, GREAVE)
    for j, u in enumerate((-.71, .71)):
        a.fastener(f'GreaveScrew{side}{j}', bone('Calf'), shin, u, .50, .040, .008,
                   target=greave)
    ankle_hub = ankle + side_axis * .091 + Vector((0, .006, .032))
    _hub(a, 'AnkleJoint' + side, bone('Foot'), ankle_hub, side_axis, .035)
    heel = a.arc((ankle.x, .024, .013), (ankle.x, .044, .103), -FRONT,
                 103, (.111, .104), taper=.10)
    a.shell('HeelCounter' + side, bone('Foot'), 'graphite', heel, .024, .009, SPAULDER)
    boot_flank = a.planar((sign * .309, -.061, .048), side_axis, UP, .120, .039, .014)
    a.shell('ArmoredBootQuarter' + side, bone('Foot'), 'graphite', boot_flank,
            .020, .009, SHINGLE)
    for i, (y, z, h, w, owner) in enumerate((
        (-.093, .150, .036, .064, 'Foot'),
        (-.136, .117, .036, .064, 'Foot'),
        (-.161, .076, .049, .065, 'Toe'),
    )):
        cap = a.planar((toe.x, y, z), (0, -.38 - .14 * i, 1), -FRONT, w, h, .014)
        a.shell(f'Sabaton{side}{i}', bone(owner), 'olive', cap, .022, .017, SPAULDER)
        if i != 0:
            for j, u in enumerate((-.69, .69)):
                a.fastener(f'BootRivet{side}{i}{j}', bone(owner), cap, u, .21, .035, .007)


def build(lod, collection, rig):
    """Build one LOD over the padded envelope using the original EFT rest bones."""
    armor = Armor(lod, collection, rig)
    torso(armor)
    dock(armor)
    for side, sign in (('L', 1), ('R', -1)):
        arm(armor, side, sign)
        leg(armor, side, sign)
    return armor.objects
