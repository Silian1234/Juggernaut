"""Fitted elbow, shoulder, hand, and forearm protection for EFT_Bind."""
import json
import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


from finish import material as shared_material


FINISH = {
    "armor": "plate",
    "rim": "black",
    "edge": "edge",
    "steel": "frame",
    "bolt": "steel",
    "black": "rubber",
    "webbing": "strap",
    "band": "band",
    "yellow": "yellow",
}


def material(key):
    return shared_material(FINISH[key])


class ArmMeshes:
    def __init__(self, lod, collection, rig, side, sleeve):
        self.detailed = lod == 0
        self.collection = collection
        self.rig = rig
        self.sleeve = sleeve
        self.side = side
        self.prefix = f"Base Human{side}"
        self.sign = 1 if side == "L" else -1
        self.objects = []

    def bone(self, name):
        return self.rig.data.bones[self.prefix + name].head_local.copy()

    def mesh(self, name, part, weight, verts, faces, keys, indexes=None, smooth=False):
        name = f"{self.side} {name}"
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], faces)
        for key in keys:
            mesh.materials.append(material(key))
        if indexes:
            for poly, index in zip(mesh.polygons, indexes):
                poly.material_index = index
        if smooth:
            for poly in mesh.polygons:
                poly.use_smooth = len(poly.vertices) == 4
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        obj = bpy.data.objects.new(name, mesh)
        obj["part"] = part
        if part == "arm_frame":
            tag = mesh.attributes.new(name="frame_geometry", type="BOOLEAN", domain="FACE")
            tag.data.foreach_set("value", [True] * len(mesh.polygons))
        self.collection.objects.link(obj)
        if isinstance(weight, str):
            weight = {weight: 1.0}
        if isinstance(weight, dict):
            weight = [weight] * len(verts)
        groups = {}
        for index, weights in enumerate(weight):
            for bone, value in weights.items():
                if bone not in groups:
                    groups[bone] = obj.vertex_groups.new(name=self.prefix + bone)
                groups[bone].add([index], value, "REPLACE")
        mod = obj.modifiers.new("EFT skin", "ARMATURE")
        mod.object = self.rig
        self.objects.append(obj)
        return obj

    def shell(self, name, basis, stations, weight, skin="armor", part="arm_plates",
              curved=False, thickness=.008):
        """Build a clipped shell with a closed backing from cross-sections."""
        fractions = (-1, -.53, 0, .53, 1) if self.detailed else (-1, 0, 1)
        if curved:
            samples = 9 if self.detailed else 5
            fractions = tuple(2 * j / (samples - 1) - 1 for j in range(samples))
        count = len(fractions)
        front = []
        back = []
        for distance, center, half, radius in stations:
            for fraction in fractions:
                angle = center + fraction * half
                point, normal = basis.point(distance, angle, radius)
                front.append(point)
                back.append(point - normal * thickness)
        stride = len(front)
        vertices = front + back
        faces = []
        indexes = []
        for offset in (0, stride):
            for row in range(len(stations) - 1):
                for col in range(count - 1):
                    i = offset + row * count + col
                    corners = (i, i + 1, i + 1 + count, i + count)
                    faces.append(corners)
                    indexes.append(0 if offset == 0 else 1)
        rim = (
            list(range(count))
            + [row * count - 1 for row in range(2, len(stations) + 1)]
            + list(range(stride - 2, stride - count - 1, -1))
            + [row * count for row in range(len(stations) - 2, 0, -1)]
        )
        for i, j in zip(rim, rim[1:] + rim[:1]):
            faces.append((i, j, j + stride, i + stride))
            indexes.append(1)
        edge = {"armor": "edge", "steel": "black", "webbing": "black", "black": "black"}[skin]
        obj = self.mesh(name, part, weight, vertices, faces, [skin, edge], indexes)
        if curved:
            for poly in obj.data.polygons:
                poly.use_smooth = poly.material_index == 0

    def prism(self, name, center, length_dir, normal, length, width, depth, weight,
              skin="steel", part="arm_frame", clip=.004, simplified=False):
        direction = length_dir.normalized()
        normal = (normal - direction * normal.dot(direction)).normalized()
        across = normal.cross(direction)
        a, b = length / 2, width / 2
        c = min(clip, a * .48, b * .48)
        if self.detailed and not simplified:
            outline = [(-a+c,-b), (a-c,-b), (a,-b+c), (a,b-c),
                       (a-c,b), (-a+c,b), (-a,b-c), (-a,-b+c)]
        else:
            outline = [(-a,-b), (a,-b), (a,b), (-a,b)]
        points = [center + direction * x + across * y + normal * z
                  for z in (-depth / 2, depth / 2) for x, y in outline]
        n = len(outline)
        faces = [tuple(range(n)), tuple(range(n, n * 2))]
        faces.extend((j, (j + 1) % n, (j + 1) % n + n, j + n) for j in range(n))
        return self.mesh(name, part, weight, points, faces, [skin, "edge" if skin == "armor" else skin],
                  [1, 0] + [1] * n)

    def rod(self, name, path, radius, weight, skin, sides=8, part="arm_frame"):
        ring = []
        for index, center in enumerate(path):
            previous = path[max(0, index - 1)]
            following = path[min(len(path) - 1, index + 1)]
            tangent = (following - previous).normalized()
            seed = Vector((0, 0, 1))
            if abs(tangent.dot(seed)) > .9:
                seed = Vector((0, 1, 0))
            u = tangent.cross(seed).normalized()
            v = tangent.cross(u)
            ring.extend(center + radius * (u * math.cos(angle) + v * math.sin(angle))
                        for angle in (i * math.tau / sides for i in range(sides)))
        end = sides * (len(path) - 1)
        faces = [tuple(range(sides)), tuple(range(end, end + sides))]
        for step in range(len(path) - 1):
            for k in range(sides):
                a = step * sides + k
                b = step * sides + (k + 1) % sides
                faces.append((a, b, b + sides, a + sides))
        return self.mesh(name, part, weight, ring, faces, [skin], smooth=True)

    def pin(self, name, center, normal, radius, depth, weight, skin="bolt", part="arm_frame"):
        sides = (16 if self.detailed else 10) if radius > .008 else 6
        return self.rod(name, [center - normal * depth * .5, center + normal * depth * .5],
                 radius, weight, skin, sides, part)

    def strap(self, name, basis, distance, width, weight, frame=False):
        # Each band uses two axial loops and a shallow inner liner.
        sides = (24 if self.detailed else 16) if frame else (12 if self.detailed else 8)
        def fitted_point(offset, angle, inset=0):
            p, n = basis.point(distance + offset, angle, 0)
            hit, _, _, radius = self.sleeve.ray_cast(p, n, .125)
            if hit is None:
                radius = .052
            return p + n * (radius + .005 - inset), n

        points = []
        for z, inset in ((-width / 2, 0), (width / 2, 0), (width / 2, .003), (-width / 2, .003)):
            for j in range(sides):
                angle = 360 * j / sides
                points.append(fitted_point(z, angle, inset)[0])
        faces = []
        for step in range(4):
            row = step * sides
            next_row = (step + 1) % 4 * sides
            for j in range(sides):
                k = (j + 1) % sides
                faces.append((row + j, row + k, next_row + k, next_row + j))
        band = self.mesh(name, "arm_frame" if frame else "arm_plates", weight, points, faces,
                  ["steel", "webbing"] if frame else ["band", "webbing"],
                  [0] * sides + [1] * (3 * sides))
        if frame:
            band["frame_node"] = f"wrist.{self.side}"
        p, n = fitted_point(0, 44)
        self.prism(f"{name} tri-glide", p + n * .004, basis.axis, n, width * 1.16, .022,
                   .007, weight, "black", "arm_frame" if frame else "arm_plates")


class ArmBasis:
    def __init__(self, start, end, side, outside=None):
        self.start = start
        self.axis = (end - start).normalized()
        seed = Vector((0, 0, 1)) if outside is None else outside
        self.up = (seed - self.axis * seed.dot(self.axis)).normalized()
        self.cross = self.axis.cross(self.up) * side

    def point(self, distance, angle, radius):
        angle = math.radians(angle)
        normal = self.up * math.cos(angle) + self.cross * math.sin(angle)
        return self.start + self.axis * distance + normal * radius, normal


def fit_shoulder_surface(vertices, faces, surface, upper, limits, radial=False, step=.002):
    """Adjust radial offsets inside each triangle against the fitted surface."""
    directions = []
    for point in vertices:
        delta = point - upper.start
        directions.append((delta - upper.axis * delta.dot(upper.axis)).normalized())

    # Sample the actual triangles. Distribute measured errors to their vertices.
    samples = []
    for face in faces:
        a, b, c = (vertices[i] for i in face)
        steps = max(2, math.ceil(max((b - a).length, (c - b).length, (c - a).length) / step))
        for u in range(steps + 1):
            for v in range(steps + 1 - u):
                weights = ((steps - u - v) / steps, u / steps, v / steps)
                samples.append((face, weights, sum(weight ** 2 for weight in weights)))

    shifts = [0.0] * len(vertices)
    for sweep in range(20):
        for face, weights, norm in (samples if sweep % 2 == 0 else reversed(samples)):
            a, b, c = (vertices[i] for i in face)
            sample = weights[0] * a + weights[1] * b + weights[2] * c
            lower, upper_limit = limits
            if radial:
                local = sample - upper.start
                normal = (local - upper.axis * local.dot(upper.axis)).normalized()
                distance = surface.ray_cast(sample, -normal, .03)[3]
                if distance is None:
                    continue
            else:
                distance = surface.find_nearest(sample)[3]
            correction = min(upper_limit, max(lower, distance)) - distance
            if abs(correction) < .00005:
                continue
            for i, weight in zip(face, weights):
                new_shift = max(-.003, min(.004, shifts[i] + correction * weight * .65 / norm))
                vertices[i] += (new_shift - shifts[i]) * directions[i]
                shifts[i] = new_shift


def shoulder_panel(arm, upper, sleeve, name, role, profile, gap, hinge):
    """Make a fitted clipped panel with an inset face and a closed inner surface."""
    dense_cap = role == 8 and not arm.detailed
    columns = (7 if arm.detailed else 5) if role == 8 else 6
    if dense_cap:
        columns = 6
    rows = (9 if role == 8 else 8) if arm.detailed else 6
    first, last, rear, front, clip = profile

    def sleeve_radius(distance, angle):
        origin, normal = upper.point(distance, angle, 0)
        _, _, _, radius = sleeve.ray_cast(origin, normal, .150)
        if radius is None:
            raise ValueError(f"No sleeve under {name} at {distance:.3f} m, {angle:.1f} degrees")
        return radius

    def surface(distance, angle, offset):
        # Broad offsets bridge the deepest local folds without a lumpy exterior.
        crown_folds = ((.093, 8, .017, 18, .0024), (.070, -9, .014, 14, .0017))
        lame_folds = ((.136, -31, .018, 14, .0028),)
        allowance = sum(
            lift * math.exp(-((distance - z) / z_width) ** 2 - ((angle - a) / a_width) ** 2)
            for z, a, z_width, a_width, lift in (crown_folds if role == 8 else lame_folds)
        )
        return upper.point(distance, angle, sleeve_radius(distance, angle) + gap + offset + allowance)[0]

    coordinates = []
    axial_fractions = sorted({*(i / (rows - 1) for i in range(rows)),
                              clip / (last - first), 1 - clip / (last - first)})
    for fraction in axial_fractions:
        distance = first + fraction * (last - first)
        # The straight sections and corner clips are drawn in the unwrapped plate.
        top_clip = 7 * max(0, 1 - (distance - first) / clip)
        bottom_clip = 12 * max(0, 1 - (last - distance) / clip)
        notch = top_clip + bottom_clip
        for col in range(columns):
            angle = rear + notch + (front - rear - 2 * notch) * col / (columns - 1)
            coordinates.append((distance, angle))

    count = len(coordinates)
    rim = (list(range(columns))
           + list(range(2 * columns - 1, count, columns))
           + list(range(count - 2, count - columns - 1, -1))
           + list(range(count - 2 * columns, 0, -columns)))
    middle = (first + last) / 2
    center = (rear + front) / 2

    def contour(coordinate, axial_inset, angular_inset, depth):
        distance, angle = coordinate
        distance = middle + (distance - middle) * (1 - 2 * axial_inset / (last - first))
        angle = center + (angle - center) * (1 - 2 * angular_inset / (front - rear))
        return surface(distance, angle, depth)

    # An inset polygonal face and two raised perimeter terraces follow the
    # reference pauldron. All are continuous parts of the solid shell.
    inset = (.009, 7.0) if role == 8 else (.005, 4.0)
    edges = len(rim)
    vertices = [contour(coordinate, *inset, .0155) for coordinate in coordinates]
    vertices.extend(contour(coordinates[i], inset[0] - .0015, inset[1] - 1, .017)
                    for i in rim)
    vertices.extend(contour(coordinates[i], .002, 1.4, .017) for i in rim)
    vertices.extend(surface(*coordinates[i], .0145) for i in rim)
    back_start = len(vertices)
    vertices.extend(surface(*coordinate, 0) for coordinate in coordinates)
    faces = []
    for row in range(len(axial_fractions) - 1):
        for col in range(columns - 1):
            i = row * columns + col
            faces.append((i, i + 1, i + columns + 1, i + columns))
    front_faces = []
    backing_faces = []
    for a, b, c, d in faces:
        front_faces.extend(((a, b, c), (a, c, d)))
        backing_faces.extend(((back_start + a, back_start + c, back_start + b),
                              (back_start + a, back_start + d, back_start + c)))
    # Derive the exterior from the fitted backing so folds do not change the
    # stock thickness where the front and rear sampling grids are staggered.
    backing = vertices[back_start:]
    gap_step = .001 if dense_cap else .002
    fit_shoulder_surface(backing, [tuple(i - back_start for i in face) for face in backing_faces],
                         sleeve, upper, (.0055, .01125), step=gap_step)
    vertices[back_start:] = backing
    backing_tree = BVHTree.FromPolygons(
        backing, [tuple(i - back_start for i in face) for face in backing_faces], all_triangles=True)

    def conform(point, depth):
        local = point - upper.start
        origin = upper.start + upper.axis * local.dot(upper.axis)
        normal = (point - origin).normalized()
        hit, _, _, _ = backing_tree.ray_cast(origin, normal, .150)
        return hit + normal * depth if hit is not None else point

    front_surface = [conform(point, .0175) for point in vertices[:count]]
    fit_shoulder_surface(front_surface, front_faces, backing_tree, upper, (.0153, .0197), radial=True, step=gap_step)
    vertices[:count] = front_surface
    front_tree = BVHTree.FromPolygons(front_surface, front_faces, all_triangles=True)
    for ring_index, depth in enumerate((.019, .019, .0165)):
        start = count + edges * ring_index
        for j, outline_index in enumerate(rim):
            point = vertices[start + j]
            if ring_index == 2:
                normal = (point - backing[outline_index]).normalized()
                vertices[start + j] = backing[outline_index] + normal * depth
            else:
                vertices[start + j] = conform(point, depth)

    faces = front_faces + backing_faces
    face_count = len(front_faces)
    inner_count = len(backing_faces)
    # The first two rings carry the step and raised lip. The third ring breaks
    # the outer edge, and the last one joins the lip to the backing.
    for j, i in enumerate(rim):
        k = (j + 1) % edges
        faces.append((i, rim[k], count + k, count + j))
        for ring in (0, 1):
            offset = count + ring * edges
            faces.append((offset + j, offset + k, offset + edges + k, offset + edges + j))
        offset = count + 2 * edges
        faces.append((offset + j, offset + k, back_start + rim[k], back_start + i))

    def skin(point):
        distance = (point - upper.start).dot(upper.axis)
        blend = .39 * max(0, min(1, (.057 - distance) / .068)) if hinge else 0
        return {"Upperarm": 1 - blend, "Collarbone": blend} if blend else {"Upperarm": 1.0}

    # Graphite on the returned edge makes the recessed khaki face and its
    # narrow outer lip legible under the same flat finish as the thigh frame.
    edge_faces = []
    for j, source in enumerate(rim):
        neighbor = rim[(j + 1) % edges]
        axial = (coordinates[source][0] + coordinates[neighbor][0]) * .5
        angle = (coordinates[source][1] + coordinates[neighbor][1]) * .5
        dark_return = role == 8 and (angle > center or axial > middle)
        edge_faces.extend((2, 2 if dark_return else 0, 1, 2))
    panel = arm.mesh(name, "arm_plates", [skin(point) for point in vertices], vertices, faces,
                     ["armor", "edge", "rim"], [0] * face_count + [2] * inner_count + edge_faces)
    panel.data.attributes.new("v5c_plate", "INT", "FACE").data.foreach_set(
        "value", [role] * len(faces))
    panel.data.attributes.new("v5c_inner", "INT", "FACE").data.foreach_set(
        "value", [0] * face_count + [role] * inner_count + [0] * (4 * edges))

    panel.data.attributes.new("v5c_outer", "INT", "FACE").data.foreach_set(
        "value", [role] * face_count + [0] * (len(faces) - face_count))
    panel["v5c_radial_axis"] = json.dumps([list(upper.start), list(upper.axis)])
    panel["v5c_nominal_depth_mm"] = 17.5
    # Only the broad faces are shaded together. The edge and chamfer stay crisp.
    for poly in panel.data.polygons:
        poly.use_smooth = poly.index < face_count + inner_count
    for angle in (rear + 14, front - 14):
        distance = first + (last - first) * .78
        origin, normal = upper.point(distance, angle, 0)
        point, _, _, _ = front_tree.ray_cast(origin, normal, .150)
        if point is None:
            continue
        arm.pin(f"{name} screw", point + normal * .0005, normal, .0042, .003,
                skin(point), "bolt", "arm_plates")


def armor(arm, upper, lower, hand, shoulder_sleeve):
    upper_bone = "Upperarm"
    elbow_bone = "Forearm1"
    fore_bone = "Forearm2"
    palm_bone = "Palm"
    arm.shell("Padded shoulder liner", upper, (
        (-.016, -29, 20, .075), (.024, -27, 30, .079),
        (.061, -26, 30, .081), (.098, -24, 22, .077)),
        upper_bone, "webbing", curved=True, thickness=.004)
    shoulder_panel(arm, upper, shoulder_sleeve, "Deltoid shell", 8,
                   (-.028, .101, -70, 20, .014), .0105, hinge=True)
    shoulder_panel(arm, upper, shoulder_sleeve, "Pauldron lower lame", 9,
                   (.103, .168, -62, 10, .012), .0095, hinge=False)
    arm.shell("Outer biceps shell", upper, (
        (.173, -43, 31, .105), (.182, -43, 51, .108),
        (.200, -43, 47, .111), (.212, -43, 31, .112)),
        upper_bone, curved=True, thickness=.012)
    arm.strap("Biceps retention band", upper, .213, .018, upper_bone)

    arm.shell("Elbow cap liner", lower, (
        (.002, -12, 30, .095), (.015, -12, 52, .102),
        (.033, -10, 48, .102), (.053, -10, 34, .090)),
        elbow_bone, "black", curved=True)
    arm.shell("Elbow impact cap", lower, (
        (.004, -17, 23, .124), (.012, -17, 42, .134),
        (.033, -11, 47, .123), (.046, -10, 34, .105)),
        elbow_bone, curved=True, thickness=.013)

    arm.shell("Wraparound forearm bracer", lower, (
        (.052, -33, 46, .104), (.070, -35, 70, .111),
        (.151, -33, 70, .094), (.190, -31, 63, .083),
        (.206, -29, 45, .079)), fore_bone, curved=True, thickness=.013)
    arm.strap("Forearm retention band", lower, .110, .017, fore_bone)
    arm.strap("Wrist frame cuff", lower, .231, .025, "Forearm3", frame=True)

    arm.shell("Dorsal glove guard", hand, (
        (.010, 0, 35, .044), (.029, 0, 49, .045),
        (.082, 1, 58, .047), (.106, 1, 41, .044)), palm_bone, "steel")
    for digit in range(2, 6):
        start = arm.bone(f"Digit{digit}1")
        end = arm.bone(f"Digit{digit}2")
        axis = (end - start).normalized()
        outward = hand.up
        width = .024 if digit <= 3 else .020 if digit == 4 else .016
        arm.prism(f"Knuckle tile {digit}", start + axis * .012 + outward * .017,
                  axis, outward, .028, width * 1.10, .008, f"Digit{digit}1", "steel", "arm_plates")
        if arm.detailed:
            arm.prism(f"Finger impact rib {digit}", start.lerp(end, .68) + outward * .013,
                      axis, outward, .016, width * .88, .005, f"Digit{digit}1",
                      "steel", "arm_plates", simplified=True)
    if arm.detailed:
        studs = [
            (lower, .071, -55, .111, fore_bone), (lower, .072, -2, .110, fore_bone),
        ]
        for i, (basis, distance, angle, radius, bone) in enumerate(studs, start=5):
            p, n = basis.point(distance, angle, radius + .001)
            arm.pin(f"Flush armor rivet {i:02}", p, n, .003, .0035, bone,
                    "bolt", "arm_plates")


def mix_weights(start, end, t):
    return {bone: start.get(bone, 0) * (1 - t) + end.get(bone, 0) * t
            for bone in start.keys() | end.keys()}


def drive_case(arm, name, a, b, normal, width, depth, weight, node, window=False):
    """One machined housing with distinct flanges, gasket and recessed cover."""
    axis = (b - a).normalized()
    across = axis.cross(normal).normalized()
    out = across.cross(axis).normalized()
    center = (a + b) * .5
    length = (b - a).length

    def outline(x, y, bevel):
        return ((-x + bevel, -y), (x - bevel, -y), (x, -y + bevel), (x, y - bevel),
                (x - bevel, y), (-x + bevel, y), (-x, y - bevel), (-x, -y + bevel))

    x, y = length * .5, width * .5
    clip = min(x * .25, y * .32)
    lip = .0035
    rings = [
        (x-lip, y-lip, clip, -.50, 1),
        (x, y, clip, -.35, 0),
        (x, y, clip, .08, 0),
        (x-lip, y-lip, clip, .22, 1),
        (x-lip, y-lip, clip, .29, 2),
        (x-lip-.001, y-lip-.001, clip, .41, 0),
        (x-2*lip, y-2*lip, clip, .50, 1),
        (x*(.59 if window else .77), y*(.51 if window else .66), clip*.60, .50, 1),
        (x*(.56 if window else .72), y*(.45 if window else .61), clip*.60, .35, 2),
    ]
    if window:
        rings.append((x*.56, y*.45, clip*.60, -.50, 2))
    if not arm.detailed:
        rings = [rings[i] for i in ((0, 1, 5, 6, 7, 8, 9) if window else (0, 1, 5, 6, 7, 8))]
    vertices = [
        center + axis * u + across * v + out * height * depth
        for rx, ry, bevel, height, _ in rings
        for u, v in outline(rx, ry, bevel)
    ]
    faces, material_ids = [], []
    for row in range(len(rings) if window else len(rings)-1):
        i = row*8
        k = ((row+1) % len(rings))*8
        for col in range(8):
            next_col = (col + 1) % 8
            faces.append((i+col, i+next_col, k+next_col, k+col))
            material_ids.append(rings[row][4])
    if not window:
        faces += [tuple(range(8)), tuple(range(len(vertices)-8, len(vertices)))]
        material_ids += [1, 0]
    housing = arm.mesh(name, "arm_frame", weight, vertices, faces,
                       ["steel", "bolt", "black"], material_ids)
    housing["frame_node"] = f"{node}.{arm.side}"

    def add_hardware(obj):
        obj["frame_node"] = housing["frame_node"]

    if arm.detailed and node in {"upper_arm", "forearm", "wrist"}:
        for u in (-x*.87, x*.87):
            for v in (-y*.61, y*.61):
                add_hardware(arm.pin(f"{name} captive screw", center + axis*u + across*v
                                     + out*(depth*.50+.001), out, .0028, .003, weight))
        if not window:
            for j in range(-1, 2):
                grille = center + axis*(.17*length + j*.0046) + out*(depth*.35+.001)
                add_hardware(arm.prism(f"{name} ventilation slot", grille, across, out,
                                       width*.30, .0019, .002, weight, "black", simplified=True))
    return housing


def bearing(arm, name, point, normal, radius, weight, joint):
    """One turned bearing with integral flanges and opposed shaft heads."""
    large = radius > .020
    sides = (20 if large else 10) if arm.detailed else (10 if large else 6)
    profile = (
        (-.033, .55, 1), (-.027, .55, 0), (-.027, .76, 1),
        (-.017, .94, 0), (.015, 1, 0), (.024, .87, 1),
        (.025, .58, 0), (.029, .57, 0), (.029, .33, 1), (.034, .33, 1),
    )
    if not arm.detailed or not large:
        profile = tuple(profile[i] for i in (0, 2, 3, 4, 5, 8, 9))
    else:
        profile = tuple(profile[i] for i in (0, 2, 3, 4, 5, 7, 8, 9))
    u = normal.cross(Vector((0, 0, 1))).normalized()
    v = normal.cross(u).normalized()
    circle = [u * math.cos(theta) + v * math.sin(theta)
              for theta in (j * math.tau / sides for j in range(sides))]
    vertices = [point + normal * z + direction * radius * r
                for z, r, _ in profile for direction in circle]
    faces = [tuple(reversed(range(sides)))]
    slots = [1]
    for row in range(len(profile) - 1):
        a, b = row * sides, (row + 1) * sides
        for j in range(sides):
            k = (j + 1) % sides
            faces.append((a + j, a + k, b + k, b + j))
            slots.append(profile[row + 1][2])
    faces.append(tuple(range(len(vertices) - sides, len(vertices))))
    slots.append(1)
    part = arm.mesh(name, "arm_frame", weight, vertices, faces, ["steel", "bolt"], slots)
    node = {"shoulder_crown": "shoulder",
            "upper_arm_splice": "upper_arm", "forearm_splice": "forearm"}.get(joint, joint)
    part["frame_node"] = f"{node}.{arm.side}"
    if arm.detailed and large:
        for j in range(6):
            theta = j * math.tau / 6
            bolt = point + (u * math.cos(theta) + v * math.sin(theta)) * radius * .72
            screw = arm.pin(f"{name} socket bolt {j + 1}", bolt + normal * .026,
                            normal, .0026, .004, weight)
            screw["frame_node"] = part["frame_node"]


def frame(arm, upper, lower):
    collar = {"Collarbone": 1.0}
    humerus = {"Upperarm": 1.0}
    forearm = {"Forearm2": 1.0}
    wrist = {"Forearm3": 1.0}
    shoulder_skin = {"Collarbone": .33, "Upperarm": .67}
    elbow_joint = {"Upperarm": .50, "Forearm1": .50}
    shoulder, shoulder_n = upper.point(.033, -114, .165)
    elbow, elbow_n = lower.point(-.001, -101, .115)
    yoke = Vector((arm.sign * .177, .121, 1.553))

    # A slotted shoulder swing link follows the collar at the back-frame port.
    yoke_axis = (shoulder - yoke).normalized()
    swing = drive_case(arm, "Shoulder swing link", yoke + yoke_axis * .008,
                       shoulder - yoke_axis * .011, shoulder_n, .036, .024,
                       shoulder_skin, "shoulder", window=True)
    for vertex in swing.data.vertices:
        t = max(0.0, min(1.0, (vertex.co - yoke).dot(yoke_axis) / (shoulder-yoke).length))
        # Lift the exposed centre of the link away from the pauldron sweep.
        vertex.co += Vector((arm.sign*.028, .032, .012)) * math.sin(math.pi*t)
        for name, value in mix_weights(collar, shoulder_skin, t).items():
            group = swing.vertex_groups.get(arm.prefix + name)
            group.add([vertex.index], value, "REPLACE")
    swing.data.update()
    bearing(arm, "Shoulder drive pivot", shoulder, shoulder_n, .039, shoulder_skin, "shoulder")

    upper_a, upper_n = upper.point(.086, -113, .150)
    upper_b, _ = upper.point(.256, -106, .119)
    drive_case(arm, "Upper arm actuator casing", upper_a, upper_b, upper_n, .069,
               .044, humerus, "upper_arm")
    fore_a, fore_n = lower.point(.047, -93, .138)
    fore_b, _ = lower.point(.191, -93, .106)
    drive_case(arm, "Forearm actuator casing", fore_a, fore_b, fore_n, .063,
               .041, forearm, "forearm")
    cuff_a, cuff_n = lower.point(.196, -96, .108)
    cuff_b, _ = lower.point(.247, -96, .086)
    drive_case(arm, "Wrist housing with open inspection window", cuff_a, cuff_b,
               cuff_n, .060, .030, wrist, "wrist", window=True)
    bearing(arm, "Elbow planetary actuator", elbow, elbow_n, .043, elbow_joint, "elbow")

    def support(name, basis, distance, angle, radius, depth, weight, node):
        point, normal = basis.point(distance, angle, radius)
        mount = arm.prism(name, point, basis.axis, normal, .021, .032, depth,
                          weight, "steel", clip=.003)
        mount["frame_node"] = f"{node}.{arm.side}"

    support("Deltoid rail saddle", upper, .108, -112, .115, .029, humerus, "upper_arm")
    support("Biceps rail saddle", upper, .217, -104, .093, .030, humerus, "upper_arm")
    support("Bracer upper rail foot", lower, .082, -93, .111, .016, forearm, "forearm")
    support("Bracer lower rail foot", lower, .165, -93, .092, .013, forearm, "forearm")
    support("Cuff socket bridge", lower, .232, -96, .063, .027, wrist, "wrist")

    def drive_shaft(name, a, b, direction, weights, node):
        shaft = arm.prism(name, (a+b)*.5, b-a, direction, (b-a).length, .024, .018,
                          weights[0], "steel", clip=.003, simplified=True)
        shaft["frame_node"] = f"{node}.{arm.side}"
        span = (b-a).length_squared
        for vertex in shaft.data.vertices:
            t = max(0, min(1, (vertex.co-a).dot(b-a)/span))
            for key, value in mix_weights(*weights, t).items():
                name = arm.prefix + key
                group = shaft.vertex_groups.get(name) or shaft.vertex_groups.new(name=name)
                group.add([vertex.index], value, "REPLACE")

    drive_shaft("Shoulder pivot torque clevis", shoulder, upper_a.lerp(upper_b, .18),
                shoulder_n, (shoulder_skin, humerus), "shoulder")
    drive_shaft("Elbow upper torque clevis", upper_b.lerp(upper_a, .10), elbow,
                elbow_n, (humerus, elbow_joint), "elbow")
    drive_shaft("Elbow lower torque clevis", elbow, fore_a.lerp(fore_b, .16),
                elbow_n, (elbow_joint, forearm), "elbow")
    drive_shaft("Wrist torque clevis", fore_b.lerp(fore_a, .15), cuff_a.lerp(cuff_b, .27),
                cuff_n, (forearm, wrist), "wrist")
    port, port_n = upper.point(.044, -112, .152)
    pad = arm.prism("Shoulder hydraulic distribution block", port + Vector((0,-.008,.008)),
                    upper.axis, port_n, .041, .032, .030, shoulder_skin, clip=.004)
    pad["frame_node"] = f"shoulder.{arm.side}"

    def service_loop(name, controls, end_weights, radius, skin, node):
        """Sample a cubic hose centreline and preserve twist throughout the loop."""
        start, rise, fall, finish = controls
        samples = 10 if arm.detailed else 8
        sides = 8 if arm.detailed else 6
        ts = [j / (samples-1) for j in range(samples)]
        path = [(1-t)**3*start + 3*(1-t)**2*t*rise + 3*(1-t)*t*t*fall + t**3*finish for t in ts]
        weights = [mix_weights(*end_weights, t*t*(3-2*t)) for t in ts]
        hose = arm.rod(name, path, radius, [weight for weight in weights for _ in range(sides)],
                      skin, sides)
        hose["frame_node"] = f"{node}.{arm.side}"
        for label, anchor, tangent, weight in (
            ("inlet", start, (rise-start).normalized(), end_weights[0]),
            ("outlet", finish, (fall-finish).normalized(), end_weights[1]),
        ):
            # One hex-sided union carries the shoulder, wrench flats and boot.
            profile = ((-.010, 1.62, 0), (-.003, 1.43, 1), (.007, 1.43, 1),
                       (.009, 1.26, 2), (.015, 1.07, 2))
            if not arm.detailed:
                profile = (profile[0], profile[1], profile[2], profile[-1])
            u = tangent.cross(Vector((0, 0, 1))).normalized()
            v = tangent.cross(u)
            directions = [u*math.cos(j*math.tau/6) + v*math.sin(j*math.tau/6)
                          for j in range(6)]
            vertices = [anchor + tangent*x + direction*r*radius
                        for x, r, _ in profile for direction in directions]
            faces = [tuple(range(6))]
            ids = [0]
            for row in range(len(profile)-1):
                for col in range(6):
                    j = (col+1) % 6
                    base = row*6
                    faces.append((base+col, base+j, base+6+j, base+6+col))
                    ids.append(profile[row+1][2])
            faces.append(tuple(range(len(vertices)-6, len(vertices))))
            ids.append(2)
            fitting = arm.mesh(f"{name} {label} bulkhead", "arm_frame", weight, vertices,
                               faces, ["steel", "bolt", "black"], ids)
            fitting["frame_node"] = hose["frame_node"]

    # Both service loops leave independent ports; their bights stay on the rear of the elbow.
    for name, offset, extension, radius, skin in (
        ("Elbow hydraulic pressure loop", .018, .066, .0062, "yellow"),
        ("Elbow electrical return loop", -.009, .102, .0083, "black"),
    ):
        p, _ = upper.point(.241 + offset*.2, -120, .129+offset)
        q, _ = lower.point(.079 + offset, -124, .130+offset)
        rear = Vector((arm.sign*.53, .73, -.43))
        service_loop(name, (p, p+rear*extension-upper.axis*.015,
                            q+rear*extension-lower.axis*.018, q),
                     (humerus, forearm), radius, skin, "elbow")

    shoulder_port, _ = upper.point(.121, -111, .139)
    cuff_port, _ = lower.point(.228, -114, .102)
    fore_port, _ = lower.point(.163, -112, .129)
    service_loop("Wrist black service loop",
                 (fore_port, fore_port+fore_n*.040, cuff_port+cuff_n*.041, cuff_port),
                 (forearm, wrist), .0063, "black", "wrist")
    carrier_port, _ = upper.point(.044, -112, .152)
    service_loop("Shoulder black service loop",
                 (carrier_port, carrier_port+shoulder_n*.050,
                  shoulder_port+upper_n*.032, shoulder_port),
                 (shoulder_skin, humerus), .007, "black", "shoulder")


def build(lod, collection, rig):
    """Build both arm assemblies; the caller owns the LOD collection."""
    template = bpy.data.objects["REF_top"]
    sleeve = BVHTree.FromPolygons(
        [template.matrix_world @ vertex.co for vertex in template.data.vertices],
        [tuple(poly.vertices) for poly in template.data.polygons],
    )
    shirt = collection.objects.get(f"Undersuit | Combat shirt LOD{lod}")
    shoulder_sleeve = BVHTree.FromPolygons(
        [shirt.matrix_world @ vertex.co for vertex in shirt.data.vertices],
        [tuple(poly.vertices) for poly in shirt.data.polygons],
    ) if shirt else sleeve
    objects = []
    for side in ("L", "R"):
        arm = ArmMeshes(lod, collection, rig, side, sleeve)
        upper = ArmBasis(arm.bone("Upperarm"), arm.bone("Forearm1"), arm.sign)
        lower = ArmBasis(arm.bone("Forearm1"), arm.bone("Palm"), arm.sign)
        across = (arm.bone("Digit51") - arm.bone("Digit21")) * arm.sign
        end = (arm.bone("Digit21") + arm.bone("Digit51")) * .5
        normal = (end - arm.bone("Palm")).cross(across)
        hand = ArmBasis(arm.bone("Palm"), end, arm.sign, normal.normalized())
        armor(arm, upper, lower, hand, shoulder_sleeve)
        frame(arm, upper, lower)
        objects.extend(arm.objects)
    return objects
