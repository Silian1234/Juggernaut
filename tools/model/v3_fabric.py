"""Build the thin, articulated fabric shell over the EFT fit reference."""

from collections import defaultdict
import math

import bpy
from mathutils import Vector

from v2_padding import (
    PREFIX, Reference, bind, clean, finish_insert, material, mesh_object, set_uv, smoothstep,
)


def _offsets(reference, garment):
    """Offset shared geometric seams together while preserving original skinning."""
    keys = [tuple(round(c, 5) for c in p) for p in reference.points]
    normals = defaultdict(list)
    for triangle in reference.tris:
        a, b, c = (reference.points[i] for i in triangle)
        normal = (b - a).cross(c - a)
        if normal.length_squared < 1e-18:
            continue
        normal.normalize()
        for corner, index in enumerate(triangle):
            p = reference.points[index]
            u = reference.points[triangle[corner - 1]] - p
            v = reference.points[triangle[(corner + 1) % 3]] - p
            angle = u.angle(v, 0.0)
            normals[keys[index]].append((normal, angle))

    result = {}
    for key, faces in normals.items():
        p = Vector(key)
        n = sum((normal * angle for normal, angle in faces), Vector()).normalized()
        if garment == "Jacket":
            glove = 1 - smoothstep(-.448, -.415, p.y)
            collar = (1 - smoothstep(.085, .112, abs(p.x))) * math.exp(-((p.z - 1.605) / .030) ** 2)
            margin = .009 - .004 * glove + .0025 * collar
            ax = abs(p.x)
            armhole = math.exp(-((ax - .157) / .041) ** 2 - ((p.y + .078) / .037) ** 2
                               - ((p.z - 1.392) / .077) ** 2)
            bicep = math.exp(-((ax - .272) / .048) ** 2 - ((p.y + .175) / .042) ** 2
                             - ((p.z - 1.423) / .037) ** 2)
            bicep_lip = math.exp(-((ax - .275) / .029) ** 2 - ((p.y + .173) / .027) ** 2
                                 - ((p.z - 1.424) / .024) ** 2)
            rear_seam = math.exp(-((ax - .229) / .035) ** 2 - ((p.y - .055) / .030) ** 2
                                 - ((p.z - 1.351) / .033) ** 2)
            extra = Vector((math.copysign(.007 * armhole + .006 * bicep + .010 * bicep_lip, p.x),
                            -.020 * armhole - .015 * bicep - .009 * bicep_lip + .004 * rear_seam,
                            .004 * bicep))
        else:
            boot = 1 - smoothstep(.07, .15, p.z)
            margin = .010 - .003 * boot
            knee = math.exp(-((abs(p.x) - .067) / .036) ** 2 - ((p.y - .033) / .051) ** 2
                            - ((p.z - .514) / .054) ** 2)
            extra = Vector((-math.copysign(.013 * knee, p.x), .020 * knee, .009 * knee))
        # A corner moves far enough to cover the original adjacent planes.
        # Clamp near opposing faces such as folds between fingers.
        support = min(normal.dot(n) for normal, _ in faces)
        result[key] = n * (margin / max(.63, support)) + extra
    return [point + result.get(key, Vector()) for point, key in zip(reference.points, keys)]


def _family(garment, point):
    x, y, z = point
    if garment == "Jacket":
        if y < -.412:
            return "fabricdark"
        if z > 1.555 and abs(x) < .103:
            return "fabricdark"
        return "fabric"
    if z < .031:
        return "rubber"
    if z < .136:
        return "fabricdark"
    return "fabric"


def _garment(prefix, garment, source, lod, collection, rig):
    reference = Reference(source)
    vertices = _offsets(reference, garment)
    obj = mesh_object(prefix + "_" + garment, vertices, reference.tris, collection)
    # Voxelize a temporary fit envelope to generate the garment topology. The
    # temporary triangulation is used only for transferring EFT weights.
    clean(obj.data)
    donor = mesh_object(prefix + "_FitWitness", vertices, reference.tris, collection)
    bind(donor, rig, reference.weights)
    guide = Reference(donor)
    bpy.context.view_layer.objects.active = obj
    obj.data.remesh_voxel_size = .0034 if lod == 0 else .004
    obj.data.use_remesh_preserve_volume = True
    bpy.ops.object.voxel_remesh()
    clean(obj.data, 2)
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new("Tailored fabric topology", "DECIMATE")
    modifier.ratio = (.040 if lod == 0 else .036) if garment == "Jacket" else (.031 if lod == 0 else .027)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    clean(obj.data)
    weights = []
    for vertex in obj.data.vertices:
        p = vertex.co
        influences = guide.skin(p)
        side = "L" if p.x >= 0 else "R"
        if garment == "Jacket":
            armhole = math.exp(-((abs(p.x) - .175) / .037) ** 2 - ((p.y + .105) / .044) ** 2
                               - ((p.z - 1.387) / .070) ** 2)
            arm = PREFIX + side + "Upperarm"
            moved = influences[arm] * .68 * armhole
            influences[arm] -= moved
            influences[PREFIX + "Spine3"] += moved
            bicep = math.exp(-((abs(p.x) - .255) / .034) ** 2 - ((p.y + .183) / .035) ** 2
                             - ((p.z - 1.429) / .037) ** 2)
            forearm = PREFIX + side + "Forearm1"
            moved = influences[forearm] * .48 * bicep
            influences[forearm] -= moved
            influences[arm] += moved
        else:
            back_knee = math.exp(-((abs(p.x) - .057) / .052) ** 2 - ((p.y - .060) / .050) ** 2
                                 - ((p.z - .526) / .056) ** 2)
            calf = PREFIX + side + "Calf"
            moved = influences[calf] * .52 * back_knee
            influences[calf] -= moved
            influences[PREFIX + side + "Thigh1"] += moved
        weights.append(influences)
        if garment == "Jacket":
            # The felt insert above the elbow carries the sleeve over the
            # compression crease when the forearm is raised.
            flex = math.exp(-((abs(p.x) - .285) / .026) ** 2 - ((p.y + .220) / .029) ** 2
                            - ((p.z - 1.434) / .026) ** 2)
            p += Vector((math.copysign(.004 * flex, p.x), -.006 * flex, .008 * flex))
    obj.data.update()
    mesh = donor.data
    bpy.data.objects.remove(donor, do_unlink=True)
    bpy.data.meshes.remove(mesh)

    families = ("fabric", "fabricdark", "rubber")
    for family in families:
        obj.data.materials.append(material(family))
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
        polygon.material_index = families.index(_family(garment, polygon.center))
    set_uv(obj)
    bind(obj, rig, weights)
    obj["v3_fabric"] = True
    return obj


def _gasket(prefix, lod, collection, rig):
    """Build a tapered stretch collar that can overlap the helmet fabric seal."""
    count = 48 if lod == 0 else 36
    # The upper hem stays on the neck, and the lower radius flares into the
    # chest and shoulder textile. Front radius is greater for the throat.
    rings = (
        (1.540, .109, .104, .117), (1.558, .104, .101, .107),
        (1.580, .097, .101, .088), (1.600, .093, .107, .077),
        (1.620, .089, .092, .072), (1.641, .083, .082, .069),
        (1.645, .081, .080, .067), (1.642, .077, .076, .063),
        (1.541, .097, .090, .104),
    )
    pivot_x, pivot_y = -.00062798, .02180314
    vertices = []
    faces = []
    for z, side_radius, front_radius, rear_radius in rings:
        for step in range(count):
            angle = math.tau * step / count
            cosine = math.cos(angle)
            depth = front_radius if cosine >= 0 else rear_radius
            vertices.append((pivot_x + side_radius * math.sin(angle), pivot_y - depth * cosine, z))
    for ring in range(len(rings)):
        next_ring = (ring + 1) % len(rings)
        for i in range(count):
            j = (i + 1) % count
            faces.append((ring * count + i, ring * count + j,
                          next_ring * count + j, next_ring * count + i))
    obj = mesh_object(prefix + "_NeckGasket", vertices, faces, collection)
    obj.data.materials.append(material("fabricdark"))
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    set_uv(obj)
    weights = []
    for _, _, z in vertices:
        neck = smoothstep(1.552, 1.609, z)
        weights.append({PREFIX + "Spine3": 1 - neck, PREFIX + "Neck": neck})
    bind(obj, rig, weights)
    obj["v3_fabric"] = True
    return obj


def _gussets(prefix, lod, collection, rig):
    """Doubled inner sleeve fabric isolated from the high compression fold."""
    guide = Reference(bpy.data.objects["REF_top"])
    patches = []
    for side in (-1, 1):
        center = Vector((side * .274, -.168, 1.437))
        count = 24 if lod == 0 else 16
        rest = [center]
        positions = [center + Vector((0, -.019, .002))]
        faces = []
        for row, ring in enumerate((.48, 1)):
            for i in range(count):
                angle = math.tau * i / count
                x, z = math.cos(angle), math.sin(angle)
                co = center + Vector((x * .024 * ring, -.004 * z * ring, z * .020 * ring))
                rest.append(co)
                depth = .017 if row == 0 else .008
                positions.append(co + Vector((0, -depth, .002)))
        for i in range(count):
            a, b = i + 1, (i + 1) % count + 1
            faces.extend(((0, a, b), (a, a + count, b + count, b)))
        obj = mesh_object(prefix + "_BicepGusset" + ("L" if side > 0 else "R"), positions, faces, collection)
        patches.append(finish_insert(obj, "fabric", rig, (guide.skin(point) for point in rest)))
    return patches


def build(lod, collection, rig):
    """Return the fitted fabric, glove and boot surfaces for the given LOD."""
    prefix = ("EXO_V3Fabric", "EXO1_V3Fabric")[lod]
    jacket = _garment(prefix, "Jacket", bpy.data.objects["REF_top"], lod, collection, rig)
    trousers = _garment(prefix, "Trousers", bpy.data.objects["REF_pants"], lod, collection, rig)
    return [jacket, trousers, _gasket(prefix, lod, collection, rig), *_gussets(prefix, lod, collection, rig)]
