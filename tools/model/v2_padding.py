"""Generate the padded EOD coverall, gloves, boots, and stand collar."""
import math
from collections import defaultdict

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform


PREFIX = "Base Human"
COLORS = {
    "fabric": (.105, .107, .063, 1),
    "fabricdark": (.039, .046, .043, 1),
    "strap": (.063, .072, .059, 1),
    "rubber": (.026, .030, .027, 1),
}


def material(family):
    name = "V2_" + family
    result = bpy.data.materials.get(name)
    if result is None:
        result = bpy.data.materials.new(name)
        result.diffuse_color = COLORS[family]
        result.use_nodes = True
        shader = next(node for node in result.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        shader.inputs["Base Color"].default_value = COLORS[family]
        shader.inputs["Roughness"].default_value = .86
    return result


def head(rig, suffix):
    return rig.matrix_world @ rig.data.bones[PREFIX + suffix].head_local


def smoothstep(a, b, value):
    factor = max(0, min(1, (value - a) / (b - a)))
    return factor * factor * (3 - 2 * factor)


def quilt(value, period, seam=.13):
    """Round the crown of each padded channel, with a narrow, pinched seam."""
    phase = abs((value / period + .5) % 1 - .5)
    return smoothstep(0, seam, phase) * (.78 + .22 * math.sin(math.pi * phase))


def mesh_object(name, vertices, faces, collection):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def clean(mesh, smoothing=0, smooth_region=None):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.00009)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    vertices = [v for v in bm.verts if smooth_region is None or smooth_region(v.co)]
    for _ in range(smoothing):
        bmesh.ops.smooth_vert(bm, verts=vertices, factor=.65, use_axis_x=True,
                             use_axis_y=True, use_axis_z=True)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


class Reference:
    def __init__(self, obj):
        mesh = obj.data
        mesh.calc_loop_triangles()
        self.points = [obj.matrix_world @ v.co for v in mesh.vertices]
        self.tris = [tuple(t.vertices) for t in mesh.loop_triangles]
        self.tree = BVHTree.FromPolygons(self.points, self.tris, all_triangles=True)
        self.weights = [
            {obj.vertex_groups[g.group].name: g.weight for g in vertex.groups}
            for vertex in mesh.vertices
        ]

    def skin(self, point):
        hit, _, index, _ = self.tree.find_nearest(point)
        ids = self.tris[index]
        a, b, c = (self.points[i] for i in ids)
        values = barycentric_transform(hit, a, b, c, Vector((1, 0, 0)),
                                       Vector((0, 1, 0)), Vector((0, 0, 1)))
        combined = defaultdict(float)
        for idx, factor in zip(ids, values):
            for group, weight in self.weights[idx].items():
                combined[group] += max(0, factor) * weight
        return combined


def bind(obj, rig, weights):
    names = set(rig.data.bones.keys())
    groups = {}
    for vertex, values in zip(obj.data.vertices, weights):
        influences = sorted(((name, weight) for name, weight in values.items()
                             if name in names and weight > .0001), key=lambda pair: -pair[1])[:4]
        if not influences:
            raise RuntimeError(f"Missing bind weights for {obj.name}: {vertex.index}")
        total = sum(weight for _, weight in influences)
        for name, weight in influences:
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([vertex.index], weight / total, "REPLACE")
    modifier = obj.modifiers.new("EFT skin", "ARMATURE")
    modifier.object = rig
    obj["v2_padding"] = True


def top_padding(point, rig_axes):
    x, y, z = point
    side = 1 if x > 0 else -1
    shoulder, elbow, wrist = rig_axes[side]
    def axial(start, end):
        span = end - start
        return (point - start).dot(span) / span.length
    upper = axial(shoulder, elbow)
    lower = axial(elbow, wrist)
    upper_length = (elbow - shoulder).length
    shoulder_gate = smoothstep(.19, .30, abs(x)) * smoothstep(1.27, 1.43, z)
    sleeve_gate = max(shoulder_gate, 1 - smoothstep(-.23, -.07, y))
    glove = 1 - smoothstep(-.465, -.402, y)
    collar = smoothstep(1.526, 1.610, z) * (1 - smoothstep(.085, .143, abs(x)))
    armpit = (1 - smoothstep(.186, .264, abs(x))) * smoothstep(1.315, 1.376, z)
    armpit *= 1 - smoothstep(1.416, 1.475, z)
    torso = .027 + .014 * quilt(z + .075 * abs(x), .098)
    torso += .009 * (1 - smoothstep(.145, .24, abs(x)))
    torso *= 1 - .58 * armpit
    torso *= 1 - .35 * smoothstep(1.095, 1.058, z)
    elbow_blend = smoothstep(upper_length - .060, upper_length + .036, upper)
    along = (1 - elbow_blend) * upper + elbow_blend * (lower + upper_length)
    elbow_peaks = math.exp(-((lower - .005) / .070) ** 2)
    arm = .023 + (.011 + .004 * elbow_peaks) * quilt(along, .050)
    arm += .007 * (1 - smoothstep(.025, .17, upper))
    arm *= 1 - .61 * (1 - smoothstep(-.425, -.352, y))
    depth = torso * (1 - sleeve_gate) + arm * sleeve_gate
    depth = depth * (1 - glove) + .007 * glove
    return depth * (1 - collar) + .011 * collar


def lower_padding(point):
    x, y, z = point
    boot = 1 - smoothstep(.153, .232, z)
    knee = math.exp(-((z - .510) / .103) ** 2)
    crotch = 1 - smoothstep(.033, .105, abs(x))
    inner = crotch * (1 - smoothstep(.880, .950, z))
    band = (1 - knee) * quilt(z - .13 * abs(y), .098) + knee * quilt(z - .13 * abs(y), .042)
    volume = (.027 + (.012 + .004 * knee) * band) * (1 - .60 * inner)
    boot_volume = .010 + .004 * quilt(z + .12 * y, .039)
    sole_trim = smoothstep(-.002, .025, z)
    return volume * (1 - boot) + boot_volume * boot * (.55 + .45 * sole_trim)


def remeshed_envelope(name, ref, reference, depth, lod, collection):
    sample = mesh_object(name, reference.points, reference.tris, collection)
    clean(sample.data)
    bpy.context.view_layer.objects.active = sample
    sample.data.remesh_voxel_size = .0056 if lod == 0 else .008
    sample.data.use_remesh_preserve_volume = True
    bpy.ops.object.voxel_remesh()
    clean(sample.data, 6 if lod == 0 else 4)
    world = [vertex.co.copy() for vertex in sample.data.vertices]
    normals = [vertex.normal.copy() for vertex in sample.data.vertices]
    for vertex, point, direction in zip(sample.data.vertices, world, normals):
        _, _, _, distance = reference.tree.find_nearest(point)
        floor = min(distance, .0065)
        vertex.co = point + direction * (depth(point) + floor)
    sample.data.update()
    bpy.ops.object.voxel_remesh()
    cloth = (lambda p: p.y > -.421 and p.z < 1.56) if ref == "REF_top" else (lambda p: p.z > .17)
    clean(sample.data, 16 if lod == 0 else 11, smooth_region=cloth)
    clean(sample.data, 1)
    modifier = sample.modifiers.new("Tailored mesh reduction", "DECIMATE")
    modifier.ratio = (.054 if lod == 0 else .040) if ref == "REF_top" else (.047 if lod == 0 else .041)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    clean(sample.data)
    if ref == "REF_top":
        reinforce_top(sample.data)
    return sample


def reinforce_top(mesh):
    """Ease the throat, lower armhole, and inner sleeve for articulation."""
    for vertex in mesh.vertices:
        x, y, z = vertex.co
        throat = .009 * math.exp(-((z - 1.535) / .033) ** 2 - (x / .066) ** 2)
        throat *= 1 - smoothstep(-.045, .015, y)
        armhole = math.exp(-((abs(x) - .168) / .057) ** 2 - ((z - 1.346) / .079) ** 2)
        armhole *= math.exp(-((y + .090) / .064) ** 2)
        sleeve = math.exp(-((abs(x) - .243) / .066) ** 2 - ((z - 1.419) / .058) ** 2)
        sleeve *= math.exp(-((y + .176) / .066) ** 2)
        armhole_lip = math.exp(-((abs(x) - .155) / .037) ** 2 - ((z - 1.381) / .041) ** 2)
        armhole_lip *= math.exp(-((y + .098) / .049) ** 2)
        vertex.co.x += math.copysign(.012 * armhole + .006 * armhole_lip, x)
        vertex.co.y -= throat + .021 * armhole + .012 * sleeve + .009 * armhole_lip
    mesh.update()

def fabric_partitions(sample, ref):
    """Partition the continuous coverall while sharing normals across fabric changes."""
    mesh = sample.data
    by_material = defaultdict(list)
    for polygon in mesh.polygons:
        point = polygon.center
        x, y, z = point
        if ref == "REF_top":
            if y < -.416:
                family = "fabricdark"
            elif abs(x) < .103 and z > 1.569:
                family = "fabricdark"
            else:
                family = "fabric"
        elif z < .034 or (z < .064 and y < -.080):
            family = "rubber"
        elif z < .190:
            family = "fabricdark"
        else:
            family = "fabric"
        by_material[family].append(tuple(polygon.vertices))
    return by_material


def set_uv(obj):
    """Use a cloth-oriented projection on faces with sharp pattern turns."""
    layer = obj.data.uv_layers.new(name="UVMap")
    for polygon in obj.data.polygons:
        n = polygon.normal
        dominant = max(range(3), key=lambda axis: abs(n[axis]))
        axes = ((1, 2), (0, 2), (0, 1))[dominant]
        for loop in polygon.loop_indices:
            co = obj.data.vertices[obj.data.loops[loop].vertex_index].co
            layer.data[loop].uv = (co[axes[0]] * .70 + .5, co[axes[1]] * .51 + .18)


def jacket_skin(reference, point, anchors):
    """Carry the armhole and sleeve lining with their reference anchor bones."""
    x, y, z = point
    result = reference.skin(point)
    for donor, center, span, plateau in anchors[1 if x >= 0 else -1]:
        falloff = sum(((coord - mid) / radius) ** 2
                      for coord, mid, radius in zip((abs(x), y, z), center, span))
        blend = math.exp(-max(0, falloff - plateau))
        if blend < .003:
            continue
        result = {bone: result.get(bone, 0) * (1 - blend) + donor.get(bone, 0) * blend
                  for bone in result.keys() | donor.keys()}
    return result

def split_envelope(sample, ref, reference, collection, rig):
    positions = [v.co.copy() for v in sample.data.vertices]
    normals = [v.normal.copy() for v in sample.data.vertices]
    if ref == "REF_top":
        anchors = {
            sign: (
                (reference.skin(Vector((sign * .142, -.081, 1.347))),
                 (.165, -.109, 1.355), (.056, .063, .085), .57),
                (reference.skin(Vector((sign * .248, -.161, 1.421))),
                 (.256, -.189, 1.451), (.056, .050, .065), .08),
            ) for sign in (-1, 1)
        }
        skin = [jacket_skin(reference, point, anchors) for point in positions]
    else:
        skin = [reference.skin(point) for point in positions]
    output = []
    for family, faces in sorted(fabric_partitions(sample, ref).items()):
        ids = sorted({index for face in faces for index in face})
        mapping = {source: target for target, source in enumerate(ids)}
        obj = mesh_object(sample.name + "_" + family, [positions[i] for i in ids],
                          [tuple(mapping[i] for i in face) for face in faces], collection)
        for face in obj.data.polygons:
            face.use_smooth = True
        obj.data.normals_split_custom_set_from_vertices([normals[i] for i in ids])
        obj.data.materials.append(material(family))
        set_uv(obj)
        bind(obj, rig, (skin[i] for i in ids))
        output.append(obj)
    mesh = sample.data
    bpy.data.objects.remove(sample, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    return output



def finish_insert(obj, family, rig, weights):
    for face in obj.data.polygons:
        face.use_smooth = True
    obj.data.materials.append(material(family))
    set_uv(obj)
    bind(obj, rig, weights)
    return obj


def padding_tree(objects):
    points, faces = [], []
    for obj in objects:
        obj.data.calc_loop_triangles()
        offset = len(points)
        points.extend(v.co.copy() for v in obj.data.vertices)
        faces.extend(tuple(offset + i for i in tri.vertices) for tri in obj.data.loop_triangles)
    return BVHTree.FromPolygons(points, faces, all_triangles=True)


def piping(name, guide, direction, width, depth, tree, reference, collection, rig):
    """Round flat piping along a fitted fabric seam."""
    fitted = []
    for anchor in guide:
        point, normal, _, _ = tree.ray_cast(anchor + direction * .50, -direction, .80)
        if point is not None:
            fitted.append((point, normal))
    vertices = []
    faces = []
    for i, (point, normal) in enumerate(fitted):
        tangent = fitted[min(len(fitted) - 1, i + 1)][0] - fitted[max(0, i - 1)][0]
        across = tangent.cross(normal).normalized()
        # Finish with a blunt sewn-in end.
        taper = .68 if i in (0, len(fitted) - 1) else 1
        for offset, lift in ((-1, .14), (-.64, .83), (0, 1), (.64, .83), (1, .14)):
            vertices.append(point + across * (offset * width * taper) + normal * (lift * depth))
        if i:
            for side in range(4):
                a = (i - 1) * 5 + side
                faces.append((a, a + 5, a + 6, a + 1))
    if not faces:
        return None
    obj = mesh_object(name, vertices, faces, collection)
    return finish_insert(obj, "strap", rig, (reference.skin(p) for p in vertices))


def trims(prefix, ref, shell, reference, lod, collection, rig):
    tree = padding_tree(shell)
    front = Vector((0, -1, 0))
    paths = []
    if ref == "REF_top":
        count = 34 if lod == 0 else 16
        paths.append(("Placket",
                      [Vector((.005, -.10, 1.056 + .485 * i / count)) for i in range(count + 1)],
                      front, .010, .005))
        for side in (-1, 1):
            count = 20 if lod == 0 else 10
            paths.append(("LowerJacketSeam" + str(side),
                          [Vector((side * (.089 + .012 * math.sin(i / count * math.pi)), -.09,
                                   1.080 + .231 * i / count)) for i in range(count + 1)],
                          front, .0030, .0025))
    else:
        for side in (-1, 1):
            count = 28 if lod == 0 else 11
            facing = Vector((side * .55, -.83, 0)).normalized()
            center = [head(rig, ("L" if side > 0 else "R") + bone)
                      for bone in ("Calf", "Foot")]
            paths.append(("ShinSeam" + str(side),
                          [Vector((center[0].x * (1 - i / count) + center[1].x * i / count + side * .035,
                                   -.031, .466 - .271 * i / count)) for i in range(count + 1)],
                          facing, .0034, .003))
    return [insert for suffix, guide, direction, width, depth in paths
            if (insert := piping(prefix + "_" + suffix, guide, direction, width, depth,
                                 tree, reference, collection, rig)) is not None]
def bellows(name, collection, rig, lod):
    """Sewn neck bellows with a beveled edge that fits inside the helmet sweep."""
    segments = 36 if lod == 0 else 24
    sections = (
        (1.540, .123, .108), (1.549, .123, .107), (1.565, .103, .097),
        (1.577, .097, .092), (1.584, .088, .084), (1.592, .090, .086),
        (1.602, .087, .084), (1.608, .082, .080), (1.615, .085, .082),
        (1.627, .084, .082), (1.634, .079, .078), (1.635, .072, .072),
        (1.625, .071, .071), (1.540, .072, .073),
    )
    vertices = []
    for z, x_radius, y_radius in sections:
        for index in range(segments):
            angle = math.tau * index / segments
            cosine, sine = math.cos(angle), math.sin(angle)
            vertices.append((x_radius * cosine, .040 + y_radius * sine, z + .005 * sine))
    faces = []
    for ring in range(len(sections)):
        following = (ring + 1) % len(sections)
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((ring * segments + i, ring * segments + j, following * segments + j,
                          following * segments + i))
    obj = mesh_object(name, vertices, faces, collection)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.data.materials.append(material("fabricdark"))
    set_uv(obj)
    weights = []
    for v in obj.data.vertices:
        blend = smoothstep(1.548, 1.610, v.co.z)
        weights.append({PREFIX + "Spine3": 1 - blend, PREFIX + "Neck": blend})
    bind(obj, rig, weights)
    return obj


def build(lod, collection, rig):
    """Return the generated coverall meshes for the requested LOD."""
    prefix = ("EXO_", "EXO1_")[lod] + "V2Padding"
    axes = {sign: tuple(head(rig, side + joint) for joint in ("Upperarm", "Forearm1", "Palm"))
            for sign, side in ((1, "L"), (-1, "R"))}
    output = []
    for ref, suffix, depth in (("REF_top", "_Jacket", lambda p: top_padding(p, axes)),
                               ("REF_pants", "_Trousers", lower_padding)):
        reference = Reference(bpy.data.objects[ref])
        sample = remeshed_envelope(prefix + suffix, ref, reference, depth, lod, collection)
        shell = split_envelope(sample, ref, reference, collection, rig)
        output.extend(shell)
        output.extend(trims(prefix, ref, shell, reference, lod, collection, rig))
    output.append(bellows(prefix + "_Neck", collection, rig, lod))
    return output












