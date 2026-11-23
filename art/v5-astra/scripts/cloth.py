"""EFT-native articulating uniform, gloves, and lace-up combat footwear."""
from collections import defaultdict
import json
from math import exp
from pathlib import Path

from mathutils import Vector
from mathutils.bvhtree import BVHTree

import bpy

from finish import flat_material

ENTRY = Path(__file__).resolve().parents[1]
SOURCE = ENTRY / "source" / "cloth"

DONORS = (
    ("usec_body", "REF_top", (("Combat shirt", 1.0, 0.72), ("Tactical gloves", 1.0, 1.0))),
    ("pants_usec_commando", "REF_pants", (("Combat trousers", 1.0, 0.63), ("Combat boots", 1.0, 1.0),
                                             ("Thigh sheath", 0.99, 0.33))),
)


GARMENT_FINISHES = {
    "Combat shirt": ((.020, .022, .024), .86, .18, .09),
    "Combat trousers": ((.022, .024, .025), .88, .18, .09),
    "Tactical gloves": ((.030, .031, .031), .74, .24, .03),
    "Combat boots": ((.024, .025, .026), .65, .29, 0.0),
    "Thigh sheath": ((.031, .032, .031), .79, .22, .04),
}


def material(part):
    color, roughness, specular, sheen = GARMENT_FINISHES[part]
    return flat_material(f"V5 | {part}", color, roughness, specular=specular, sheen=sheen)


def islands(asset):
    parents = list(range(len(asset["positions"])))

    def root(vertex):
        while parents[vertex] != vertex:
            vertex = parents[vertex]
        return vertex

    for a, b, c in asset["triangles"]:
        parents[root(b)] = root(a)
        parents[root(c)] = root(a)

    components = defaultdict(list)
    for face in asset["triangles"]:
        components[root(face[0])].append(face)
    return components.values()


def source_groups(source, rig):
    groups = {}
    for vertex in source.data.vertices:
        usable = ((source.vertex_groups[entry.group].name, entry.weight)
                  for entry in vertex.groups
                  if entry.weight > 0 and source.vertex_groups[entry.group].name in rig.data.bones)
        top_four = sorted(usable, key=lambda item: item[1], reverse=True)[:4]
        total = sum(weight for _, weight in top_four)
        if total <= 0:
            raise ValueError(f"No EFT bone weight for {source.name} vertex {vertex.index}")
        groups[tuple(source.matrix_world @ vertex.co)] = tuple(
            (group, weight / total) for group, weight in top_four
        )
    return groups


def boot_vertex(point):
    """Give the outsole deeper sidewalls while keeping its contact patch and ankle axis."""
    x, y, z = point
    sole_top = 0.031
    if z < sole_top:
        z += 0.005 * max(0, min(1, (z + 0.005) / (sole_top + 0.005)))
    else:
        z += 0.005 * max(0, 1 - (z - sole_top) / 0.037)
    return x, y, z


def right_ankle_distance(point):
    x, y, z = point
    return (((x + 0.253) / 0.053) ** 2
            + ((y + 0.043) / 0.063) ** 2
            + ((z - 0.081) / 0.035) ** 2) ** 0.5


def armhole_distance(point):
    x, y, z = point
    front = (((abs(x) - 0.153) / 0.085) ** 2
            + ((y + 0.063) / 0.075) ** 2
            + ((z - 1.432) / 0.129) ** 2) ** 0.5
    rear = (((abs(x) - 0.243) / 0.065) ** 2
            + ((y - 0.005) / 0.054) ** 2
            + ((z - 1.336) / 0.039) ** 2) ** 0.5
    shoulder = (((abs(x) - 0.162) / 0.047) ** 2
                + ((y + 0.027) / 0.063) ** 2
                + ((z - 1.523) / 0.051) ** 2) ** 0.5
    sleeve_back = (((abs(x) - 0.275) / 0.065) ** 2
                   + ((y - 0.022) / 0.101) ** 2
                   + ((z - 1.350) / 0.049) ** 2) ** 0.5
    return min(front, rear, shoulder, sleeve_back)


def outward_offsets(asset, stem, lod):
    """Create a seam-compatible overlayer with added articulation clearance."""
    clearance = 0.006 if lod == 0 else 0.0105
    if stem == "usec_body":
        reinforcements = (
            ((-0.359, -0.108, 1.462), 0.041, 0.011),
            ((0.225, 0.034, 1.338), 0.051, 0.005 * lod),
            ((0.105, -0.080, 1.470), 0.060, 0.005 * lod),
            ((-0.413, -0.419, 1.355), 0.033, 0.007 * lod),
        )
    else:
        reinforcements = (
            ((-0.074, 0.036, 0.515), 0.072, 0.013),
            ((0.075, 0.048, 0.531), 0.051, 0.009 * lod),
            ((0.235, 0.032, 0.511), 0.048, 0.011),
            ((-0.262, -0.039, 0.081), 0.025, 0.005 * lod),
            ((0.121, 0.105, 0.895), 0.075, 0.008 * lod),
            ((0.000, 0.068, 0.837), 0.066, 0.005 * lod),
            ((-0.132, -0.113, 0.553), 0.060, 0.006 * lod),
            ((-0.101, -0.111, 1.025), 0.064, 0.004 * lod),
        )
    directional = (
        (
            ((-0.414, -0.416, 1.360), 0.027, (-0.003 * lod, 0.005 * lod, 0.0)),
        )
        if stem == "usec_body" else (
            ((-0.073, 0.044, 0.522), 0.061, (0.022, -0.014, -0.010)),
            ((0.079, 0.054, 0.534), 0.060, (-0.023 * lod, -0.015 * lod, -0.010 * lod)),
            ((0.0, -0.132, 1.016), 0.11, (0.0, -0.017 * lod, 0.0)),

        )
    )
    normals = defaultdict(lambda: Vector((0, 0, 0)))
    for point, normal in zip(asset["positions"], asset["normals"]):
        normals[tuple(point)] += Vector(normal)
    offsets = {}
    for point, direction in normals.items():
        local = Vector(point)
        extra = sum(height * exp(-((local - Vector(center)).length / radius) ** 2)
                    for center, radius, height in reinforcements)
        offset = direction.normalized() * (clearance + extra)
        for center, radius, shift in directional:
            offset += Vector(shift) * exp(-((local - Vector(center)).length / radius) ** 2)
        if stem == "usec_body":
            distance = armhole_distance(point)
            blend = max(0.0, min(1.0, (distance - 0.88) / 0.39))
            offset = offset.lerp(direction.normalized() * 0.00065, 1 - blend)
        elif lod == 1:
            ankle = right_ankle_distance(point)
            blend = max(0.0, min(1.0, (ankle - 0.86) / 0.54))
            offset = offset.lerp(direction.normalized() * 0.0008, 1 - blend)
        offsets[point] = offset
    return offsets


def construct(part, lod, ratio, collection, rig, asset, faces, weights, offsets):
    indices = sorted({index for face in faces for index in face})
    remap = {original: index for index, original in enumerate(indices)}
    surface = [asset["positions"][index] for index in indices]
    def envelope(point):
        # Only the fingers need additional clearance. Keep the glove and sleeve
        # at the same offset around their shared cuff boundary.
        hand_clearance = max(0.0, min(1.0, (-point[1] - 0.43) / 0.12))
        return Vector(point) + offsets[tuple(point)] * (1.0 + 0.32 * hand_clearance)

    vertices = [envelope(point) for point in surface]
    if part == "Combat boots":
        vertices = [boot_vertex(point) for point in vertices]
        if lod == 1:
            for i, point in enumerate(surface):
                close_fit = max(0.0, min(1.0, (1.2 - right_ankle_distance(point)) / 0.35))
                adjusted = Vector(vertices[i])
                adjusted.z = adjusted.z * (1 - close_fit) + (point[2] + 0.0002) * close_fit
                vertices[i] = adjusted
    label = f"Undersuit | {part} LOD{lod}"
    mesh = bpy.data.meshes.new(label)
    mesh.from_pydata(vertices, [], [[remap[index] for index in face] for face in faces])
    mesh.update()

    uv = mesh.uv_layers.new(name="EFT UV0")
    uv.uv.foreach_set("vector", [coord for loop in mesh.loops
                                 for coord in asset["uv"][indices[loop.vertex_index]]])
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    mesh.normals_split_custom_set_from_vertices([asset["normals"][index] for index in indices])
    mesh.materials.append(material(part))
    obj = bpy.data.objects.new(label, mesh)
    collection.objects.link(obj)

    groups = {}
    for vertex_index, point in enumerate(surface):
        for name, weight in weights[tuple(point)]:
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([vertex_index], weight, "REPLACE")

    if ratio < 1:
        # Weld the UV-split donor vertices before reduction so it stays watertight
        # across UV seams once it bends. The corner UV values remain distinct.
        weld = obj.modifiers.new("Join coincident donor seams", "WELD")
        weld.merge_threshold = 0.000002
        reduce = obj.modifiers.new("Reduce geometry", "DECIMATE")
        reduce.ratio = ratio
        reduce.use_collapse_triangulate = True
        protect_name = "Simplifiable garment panels"
        if part in {"Combat shirt", "Combat trousers"}:
            protected_distance = armhole_distance if part == "Combat shirt" else right_ankle_distance
            protect = obj.vertex_groups.new(name=protect_name)
            protect.add([i for i, point in enumerate(surface) if protected_distance(point) > 1.17],
                        1, "REPLACE")
            reduce.vertex_group = protect.name
        graph = bpy.context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(graph),
                                               preserve_all_data_layers=True, depsgraph=graph)
        old = obj.data
        obj.modifiers.clear()
        obj.data = mesh
        bpy.data.meshes.remove(old)
        group = obj.vertex_groups.get(protect_name)
        if group is not None:
            obj.vertex_groups.remove(group)

    for vertex in obj.data.vertices:
        usable = sorted((group.weight, group.group) for group in vertex.groups if group.weight > 0)
        top = usable[-4:]
        total = sum(weight for weight, _ in top)
        if total <= 0:
            raise ValueError(f"No EFT bone weight for {obj.name} vertex {vertex.index}")
        for _, group in usable[:-4]:
            obj.vertex_groups[group].remove([vertex.index])
        for weight, group in top:
            obj.vertex_groups[group].add([vertex.index], weight / total, "REPLACE")

    armature = obj.modifiers.new("EFT skinning", "ARMATURE")
    armature.object = rig
    return obj


class GarmentDetails:
    """Build raised trim against the actual garment surface at the requested LOD."""

    def __init__(self, garment):
        self.garment = garment
        self.mesh = garment.data
        self.mesh.calc_loop_triangles()
        self.triangles = [tuple(tri.vertices) for tri in self.mesh.loop_triangles]
        self.tree = BVHTree.FromPolygons([vertex.co for vertex in self.mesh.vertices],
                                         self.triangles, all_triangles=True)
        self.vertices = []
        self.faces = []
        self.skin = []

    def project(self, point, outward, reach):
        return self.tree.ray_cast(point + outward * reach, -outward, 2 * reach)

    def add_vertex(self, hit, height, outward, use_face_normal=True):
        position, normal, index, _ = hit
        a, b, c = [self.mesh.vertices[i] for i in self.triangles[index]]
        ab = b.co - a.co
        ac = c.co - a.co
        cross = ab.cross(ac)
        area = cross.length_squared
        v = (position - a.co).cross(ac).dot(cross) / area
        w = ab.cross(position - a.co).dot(cross) / area
        groups = defaultdict(float)
        for vertex, factor in zip((a, b, c), (1 - v - w, v, w)):
            for group in vertex.groups:
                groups[group.group] += group.weight * max(0, factor)
        self.skin.append(sorted(groups.items(), key=lambda pair: pair[1], reverse=True)[:4])
        use_face_normal = use_face_normal and normal.dot(outward) > .25
        self.vertices.append(position + (normal if use_face_normal else outward) * height)

    def band(self, center, axis, profile, radius):
        """Cut each cloth triangle at the welt boundaries before lifting it."""
        for index, triangle in enumerate(self.triangles):
            corners = [self.mesh.vertices[i].co for i in triangle]
            signed = [(point - center).dot(axis) for point in corners]
            if min(signed) >= profile[-1][0] or max(signed) <= profile[0][0]:
                continue
            radial = sum((point - center - axis * height for point, height in zip(corners, signed)),
                         Vector()) / 3
            if radial.length >= radius:
                continue
            face = list(zip(corners, signed))
            for (low, base), (high, top) in zip(profile, profile[1:]):
                segment = clip_band(clip_band(face, low, 1), high, -1)
                if len(segment) < 3:
                    continue
                first = len(self.vertices)
                for point, level in segment:
                    outward = (point - center - axis * level).normalized()
                    height = base + (top - base) * (level - low) / (high - low)
                    self.add_vertex((point, outward, index, None), height, outward, use_face_normal=False)
                for j in range(1, len(segment) - 1):
                    self.faces.append((first, first + j, first + j + 1))

    def trim(self, stations, profile, reach=.065):
        """Sweep a low chamfered welt. Its shoulders are embedded in the donor."""
        rows = [[self.project(point + across * offset, outward, reach) for offset, _ in profile]
                for point, across, outward in stations]
        if any(hit[0] is None for row in rows for hit in row):
            return False
        start = len(self.vertices)
        width = len(profile)
        for i, ((_, _, outward), row) in enumerate(zip(stations, rows)):
            for hit, (_, height) in zip(row, profile):
                if i in (0, len(stations) - 1):
                    height = min(height, -.00035)
                self.add_vertex(hit, height, outward)
        for i in range(len(stations) - 1):
            a = start + i * width
            b = a + width
            for j in range(width - 1):
                self.faces.append((a + j, a + j + 1, b + j + 1, b + j))
        return True

    def make_object(self, label, collection, rig, color, roughness):
        if not self.faces:
            return None
        mesh = bpy.data.meshes.new(label)
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update()
        # The winding of radial and mirrored trims differs. Orient each strip
        # from its donor, keeping the two chamfers consistently lit.
        for polygon in mesh.polygons:
            _, normal, _, _ = self.tree.find_nearest(polygon.center)
            if normal.dot(polygon.normal) < 0:
                polygon.flip()
        mesh.update()
        mesh.materials.append(flat_material(label.split(" LOD")[0], color, roughness, specular=.24))
        obj = bpy.data.objects.new(label, mesh)
        collection.objects.link(obj)
        groups = {}
        for index, weights in enumerate(self.skin):
            total = sum(weight for _, weight in weights)
            for group, weight in weights:
                if group not in groups:
                    groups[group] = obj.vertex_groups.new(name=self.garment.vertex_groups[group].name)
                groups[group].add([index], weight / total, "REPLACE")
        obj.modifiers.new("EFT skinning", "ARMATURE").object = rig
        return obj


def welt(half_width, relief):
    return ((-half_width, -.0012), (-half_width * .68, relief),
            (half_width * .68, relief), (half_width, -.0012))


def clip_band(face, boundary, sign):
    clipped = []
    for i, (point, level) in enumerate(face):
        prev_point, prev_level = face[i - 1]
        inside = (level - boundary) * sign > 0
        prev_inside = (prev_level - boundary) * sign > 0
        if inside != prev_inside:
            amount = (boundary - prev_level) / (level - prev_level)
            clipped.append((prev_point.lerp(point, amount), boundary))
        if inside:
            clipped.append((point, level))
    return clipped


def path_stations(points, outward):
    return [(point, (points[min(i + 1, len(points) - 1)] - points[max(0, i - 1)])
                    .cross(outward).normalized(), outward)
            for i, point in enumerate(points)]


def glove_trim(builder, lod, rig):
    for side in ("L", "R"):
        prefix = f"Base Human{side}"
        palm = rig.data.bones[prefix + "Palm"].head_local
        forearm = rig.data.bones[prefix + "Forearm3"].head_local
        axis = (palm - forearm).normalized()
        # A gauntlet hem over the glove cuff, following the elliptic wrist.
        center = palm + axis * .023
        profile = welt(.008, .0025) if lod == 0 else ((-.008, -.001), (0, .0025), (.008, -.001))
        builder.band(center, axis, profile, .065)

        for digit in range(2, 6):
            knuckle = rig.data.bones[prefix + f"Digit{digit}1"].head_local
            upper = rig.data.bones[prefix + f"Digit{digit}2"].head_local
            # The dorsal surface rolls toward the outside of the pinky.
            sign = 1 if side == "L" else -1
            outward = Vector((sign * (.33 + .26 * (digit - 2)), 0, .8)).normalized()
            fractions = (.05, .13, .24, .37) if lod == 0 else (.05, .18, .32)
            points = [knuckle.lerp(upper, fraction) for fraction in fractions]
            builder.trim(path_stations(points, outward), welt(.0052, .0028), .032)


def sleeve_trim(builder, lod, rig):
    for side in ("L", "R"):
        prefix = f"Base Human{side}"
        first = rig.data.bones[prefix + "Forearm2"].head_local
        last = rig.data.bones[prefix + "Forearm3"].head_local
        axis = (last - first).normalized()
        # Low overlapping cuff band at the distal end of the shirt sleeve.
        center = last - axis * .025
        profile = welt(.009, .0021) if lod == 0 else ((-.009, -.001), (0, .0021), (.009, -.001))
        builder.band(center, axis, profile, .080)


def trouser_trim(builder, lod):
    for sign in (-1, 1):
        outward = Vector((-.7 * sign, .7, 0)).normalized()
        # Separate inseam sections leave the strongest knee fold free.
        for top, bottom, top_x, bottom_x, top_y, bottom_y in (
            (.785, .660, .101, .105, .056, .062),
            (.463, .268, .158, .173, .059, .055),
        ):
            count = 9 if lod == 0 else 5
            start = Vector((sign * top_x, top_y, top))
            end = Vector((sign * bottom_x, bottom_y, bottom))
            points = [start.lerp(end, i / (count - 1)) for i in range(count)]
            builder.trim(path_stations(points, outward), welt(.0034, .0016), .075)


def boot_trim(builder, lod):
    up = Vector((0, 0, 1))
    for sign in (-1, 1):
        # The frame stirrup passes behind this lace bed at y=-.098.
        front, rear = -.150, -.110
        points = [Vector((sign * .227, y, z)) for y, z in
                  ((-.161, .077), (-.153, .080), (-.140, .082), (-.125, .085), (-.110, .087))]
        builder.trim(path_stations(points, up), welt(.023, .0015), .034)
        for edge in (-1, 1):
            start = Vector((sign * .228 + edge * .021, front, .080))
            end = Vector((sign * .225 + edge * .027, rear, .088))
            count = 8 if lod == 0 else 5
            points = [start.lerp(end, i / (count - 1)) for i in range(count)]
            builder.trim(path_stations(points, up), welt(.0055, .0028), .034)
        count = 4 if lod == 0 else 3
        for i in range(count):
            y = front + .004 + i * .027 / (count - 1)
            x = sign * .227
            a = Vector((x - .021, y, .079))
            b = Vector((x + .021, y + .004 * (-1) ** i, .079))
            steps = 6 if lod == 0 else 4
            points = [a.lerp(b, j / steps) for j in range(steps + 1)]
            builder.trim(path_stations(points, up), welt(.003, .0042), .034)

        # A heel counter flange wraps the heel, above the external sole.
        count = 13 if lod == 0 else 7
        points = [Vector((sign * .197 + .035 * t, .08, .034 + .008 * (1 - t * t)))
                  for t in (2 * i / (count - 1) - 1 for i in range(count))]
        builder.trim(path_stations(points, Vector((0, 1, 0))), welt(.0045, .0024), .065)


def details(build_trim, garment, lod, collection, rig, label, color, roughness):
    builder = GarmentDetails(garment)
    build_trim(builder)
    return builder.make_object(f"Undersuit | {label} LOD{lod}", collection, rig, color, roughness)


def parts(stem, asset):
    """Separate clothing, footwear, gloves, and the close-fitting thigh sheath."""
    clothing, accessories, sheath = [], [], []
    for faces in islands(asset):
        points = [asset["positions"][index] for face in faces for index in face]
        if stem == "usec_body":
            target = accessories if (max(y for _, y, _ in points) < -0.33
                                     and max(z for _, _, z in points) < 1.48) else clothing
        elif max(z for _, _, z in points) < 0.1:
            target = accessories
        elif len(faces) >= 1000 or min(z for _, _, z in points) >= 1.05:
            target = clothing
        else:
            target = sheath
        target.extend(faces)
    return (clothing, accessories) if stem == "usec_body" else (clothing, accessories, sheath)


def build(lod, collection, rig):
    """Build both clothing donors into the target collection at the requested LOD."""
    if lod not in (0, 1):
        raise ValueError(f"Unsupported undersuit LOD {lod}")
    meshes = []
    trim = {
        "Combat shirt": (lambda builder: sleeve_trim(builder, lod, rig),
                         "Sleeve cuffs", (.029, .030, .031), .83),
        "Tactical gloves": (lambda builder: glove_trim(builder, lod, rig),
                            "Glove hems and knuckle welts", (.041, .042, .042), .76),
        "Combat trousers": (lambda builder: trouser_trim(builder, lod),
                            "Trouser inseams", (.034, .035, .036), .88),
        "Combat boots": (lambda builder: boot_trim(builder, lod),
                         "Boot laces and heel counters", (.040, .041, .042), .71),
    }
    for stem, source_name, records in DONORS:
        asset = json.loads((SOURCE / f"{stem}.json").read_text(encoding="utf8"))
        weights = source_groups(bpy.data.objects[source_name], rig)
        offsets = outward_offsets(asset, stem, lod)
        for record, faces in zip(records, parts(stem, asset)):
            part, lod0_ratio, lod1_ratio = record
            ratio = lod0_ratio if lod == 0 else lod1_ratio
            garment = construct(part, lod, ratio, collection, rig, asset, faces, weights, offsets)
            meshes.append(garment)
            if part in trim:
                build_trim, label, color, roughness = trim[part]
                mesh = details(build_trim, garment, lod, collection, rig, label, color, roughness)
                if mesh:
                    meshes.append(mesh)
    return meshes












