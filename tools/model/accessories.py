"""Build the Juggernaut's three rigid accessories in Blender 5.3.

Run headless: blender -b --python-exit-code 1 --python tools/model/accessories.py
"""
from collections import defaultdict
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

OUT = Path(__file__).resolve().parents[2] / "art" / "accessories"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_helmet import chart
from v4_helmet import build_helmet

SCENE_COLLECTIONS = ("JUG_HELMET", "JUG_THERMAL", "JUG_CELL")


def material(name, rgb, metal, roughness, grain=0.0, emission=(0, 0, 0), wear=0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    shader = nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*rgb, 1)
    shader.inputs["Metallic"].default_value = metal
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Emission Color"].default_value = (*emission, 1)
    shader.inputs["Emission Strength"].default_value = 1
    if grain:
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 730
        noise.inputs["Detail"].default_value = 2
        tex = nodes.new("ShaderNodeTexCoord")
        links.new(tex.outputs["Object"], noise.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (*(component * 0.73 for component in rgb), 1)
        ramp.color_ramp.elements[1].color = (*(component * 1.21 for component in rgb), 1)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        if wear:
            geometry = nodes.new("ShaderNodeNewGeometry")
            curvature = nodes.new("ShaderNodeMapRange")
            curvature.inputs["From Min"].default_value = 0.505
            curvature.inputs["From Max"].default_value = 0.55
            curvature.inputs["To Max"].default_value = wear
            links.new(geometry.outputs["Pointiness"], curvature.inputs[0])
            mix = nodes.new("ShaderNodeMixRGB")
            mix.inputs[2].default_value = (0.22, 0.24, 0.18, 1)
            links.new(curvature.outputs[0], mix.inputs[0])
            links.new(ramp.outputs["Color"], mix.inputs[1])
            links.new(mix.outputs[0], shader.inputs["Base Color"])
        else:
            links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = .27
        bump.inputs["Distance"].default_value = grain
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    mat["jug_color"] = rgb
    mat["jug_metallic"] = metal
    mat["jug_roughness"] = roughness
    mat["jug_emission"] = emission
    return mat


def move_to_collection(obj, collection):
    for current in tuple(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def bevel(obj, amount, segments=2):
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new("Machined edge radius", "BEVEL")
    modifier.width = amount
    modifier.segments = segments
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    mesh = bmesh.new()
    try:
        mesh.from_mesh(obj.data)
        # The bevel clamps overlapping chamfers by collapsing their shortest
        # edges. Join those coincident corners before exporting triangles.
        bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=0.0000002)
        bmesh.ops.dissolve_degenerate(mesh, edges=list(mesh.edges), dist=0.0000002)
        mesh.to_mesh(obj.data)
        obj.data.update()
    finally:
        mesh.free()
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    modifier = obj.modifiers.new("Weighted face normals", "WEIGHTED_NORMAL")
    modifier.keep_sharp = True
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def surface(collection, name, points, faces, materials, indices=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    for mat in materials:
        mesh.materials.append(mat)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
        if indices is not None:
            polygon.material_index = indices[polygon.index]
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        axis = max(range(3), key=lambda i: abs(polygon.normal[i]))
        u, v = (i for i in range(3) if i != axis)
        for corner in polygon.loop_indices:
            coord = mesh.vertices[mesh.loops[corner].vertex_index].co
            uv.data[corner].uv = (coord[u] * 4, coord[v] * 4)
    return obj


def box(collection, name, location, dimensions, mat, radius=.002, rotation=None,
        bevel_segments=2):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if rotation:
        obj.rotation_euler = rotation
    obj.data.materials.append(mat)
    bevel(obj, radius, bevel_segments)
    move_to_collection(obj, collection)
    return obj


def prism(collection, name, profile, rear_y, front_y, mat, radius=.002, bevel_segments=2):
    """Extrude the supplied clockwise/CCW XZ face between two Y planes."""
    n = len(profile)
    points = [(x, y, z) for y in (rear_y, front_y) for x, z in profile]
    signed = sum(profile[i][0] * profile[(i+1) % n][1] -
                 profile[(i+1) % n][0] * profile[i][1] for i in range(n))
    if signed < 0:
        points = points[:n][::-1] + points[n:][::-1]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces.extend((i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n))
    obj = surface(collection, name, points, faces, [mat])
    bevel(obj, radius, bevel_segments)
    return obj


def spindle(collection, name, location, radius, length, mat, axis=(0, 1, 0),
            segments=24, edge=.001, radius_tip=None, bevel_segments=2):
    bpy.ops.mesh.primitive_cone_add(
        vertices=segments, radius1=radius, radius2=radius if radius_tip is None else radius_tip,
        depth=length, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.rotation_euler = Vector(axis).to_track_quat("Z", "Y").to_euler()
    obj.data.materials.append(mat)
    bevel(obj, edge, bevel_segments)
    move_to_collection(obj, collection)
    return obj


def sensor_mount(collection, m, bevel_segments):
    box(collection, "Helmet вЂ“ sensor saddle", (0, -.112, 1.799),
        (.063, .055, .029), m["seal"], .006, (-.17, 0, 0), bevel_segments)
    box(collection, "Helmet вЂ“ center dovetail", (0, -.139, 1.810),
        (.039, .018, .030), m["bolt"], .003, bevel_segments=bevel_segments)


def project_hard_surface(obj):
    """Project machining textures in six outward-facing local charts."""
    if obj.get("preserve_uv"):
        return
    mesh = obj.data
    points = [vertex.co for vertex in mesh.vertices]
    lo = [min(point[i] for point in points) for i in range(3)]
    width = [max(.000001, max(point[i] for point in points) - lo[i]) for i in range(3)]
    uv = mesh.uv_layers.active
    for face in mesh.polygons:
        axis = max(range(3), key=lambda i: abs(face.normal[i]))
        u, v = ((1, 2), (0, 2), (0, 1))[axis]
        flip = face.normal[axis] < 0 if axis != 1 else face.normal[axis] > 0
        for corner in face.loop_indices:
            point = points[mesh.loops[corner].vertex_index]
            horizontal = (point[u] - lo[u]) / width[u]
            uv.data[corner].uv = (1 - horizontal if flip else horizontal,
                                  (point[v] - lo[v]) / width[v])


def label(collection, name, center, width, height, mat):
    x, y, z = center
    coords = [(0, 0), (1, 0), (1, 1), (0, 1)]
    points = [(x + (u - .5) * width, y, z + (v - .5) * height) for u, v in coords]
    return chart(surface(collection, name, points, [(0, 1, 2, 3)], [mat]), coords)


def red_objective(collection, m):
    """Convex lens with a continuous radial UV chart across the optical surface."""
    cx, cy, cz = .006, -.2285, 1.853
    sides, rings = 48, 17
    points, coords = [(cx, cy - .003, cz)], [(.5, .5)]
    faces = [(0, 1 + j, 1 + (j + 1) % sides) for j in range(sides)]
    for i in range(1, rings + 1):
        rho = i / rings
        for j in range(sides):
            theta = math.tau * j / sides
            x, z = rho * math.cos(theta), rho * math.sin(theta)
            points.append((cx + .0167 * x, cy - .003 * (1 - rho ** 2), cz + .0167 * z))
            coords.append((.5 + .5 * x, .5 + .5 * z))
    for i in range(rings - 1):
        for j in range(sides):
            a, b = 1 + i * sides + j, 1 + i * sides + (j + 1) % sides
            faces.append((a, a + sides, b + sides, b))
    chart(surface(collection, "Thermal вЂ“ convex ruby objective", points, faces, [m["lens"]]),
          coords)


def thermal(collection, m):
    box(collection, "Thermal вЂ“ latch wedge", (0, -.150, 1.820),
        (.043, .025, .030), m["metal"], .004)
    box(collection, "Thermal вЂ“ isolator", (0, -.165, 1.835),
        (.060, .039, .029), m["seal"], .004)
    pod = [(-.047, 1.842), (-.035, 1.828), (.035, 1.828), (.047, 1.841),
           (.047, 1.869), (.032, 1.880), (-.035, 1.880), (-.047, 1.868)]
    prism(collection, "Thermal вЂ“ compact sensor housing", pod, -.112, -.212, m["armor"], .005)
    for side in (-1, 1):
        for index in range(4):
            box(collection, f"Thermal вЂ“ side heat sink {side} {index}",
                (side * .047, -.177 + .012 * index, 1.853), (.006, .005, .026),
                m["seal"], .0015)
    spindle(collection, "Thermal вЂ“ objective bezel", (.006, -.216, 1.853),
            .022, .014, m["seal"], (0, -1, 0), 32, .002)
    spindle(collection, "Thermal вЂ“ lens retainer", (.006, -.223, 1.853),
            .0178, .005, m["metal"], (0, -1, 0), 32, .0009)
    red_objective(collection, m)
    box(collection, "Thermal вЂ“ machined service lid", (0, -.161, 1.877),
        (.065, .060, .009), m["lip"], .003)
    box(collection, "Thermal вЂ“ rear dust cover", (0, -.113, 1.853),
        (.069, .008, .036), m["lip"], .003)
    label(collection, "Thermal вЂ“ warning stencil", (-.028, -.2124, 1.867),
          .022, .010, m["warning"])
    box(collection, "Thermal вЂ“ auxiliary indicator", (-.028, -.215, 1.859),
        (.010, .005, .006), m["mark"], .0015)
    for x in (-.032, .032):
        spindle(collection, "Thermal вЂ“ service fastener", (x, -.213, 1.840),
                .0033, .003, m["bolt"], (0, -1, 0), 8, .0004)


def cell(collection, m):
    box(collection, "Cell вЂ“ structural housing", (0, 0, 0),
        (.104, .070, .195), m["armor"], .009)
    for direction in (-1, 1):
        box(collection, "Cell вЂ“ molded end bumper", (0, 0, direction * .089),
            (.112, .080, .034), m["seal"], .006)
        box(collection, "Cell вЂ“ end bumper wear plate", (0, -.031, direction * .098),
            (.091, .019, .016), m["lip"], .002)
        for x in (-.034, .034):
            spindle(collection, "Cell вЂ“ line fastener", (x, -.041, direction * .092),
                    .004, .004, m["bolt"], (0, -1, 0), 8, .0006)
    box(collection, "Cell вЂ“ terminal block", (0, 0, .108),
        (.059, .041, .011), m["lip"], .0025)
    for i in range(3):
        box(collection, f"Cell вЂ“ recessed brass terminal {i + 1}", ((i - 1) * .017, 0, .113),
            (.009, .024, .003), m["brass"], .001)
    for side in (-1, 1):
        box(collection, "Cell вЂ“ docking shoe", (side * .048, .024, -.005),
            (.018, .016, .137), m["metal"], .004)
        for index in range(6):
            box(collection, "Cell вЂ“ recessed grip rib", (side*.043, -.035, -.046 + .016*index),
                (.014, .008, .008), m["lip"], .002)
    box(collection, "Cell вЂ“ isolation panel", (0, -.035, .004),
        (.060, .009, .132), m["lip"], .005)
    box(collection, "Cell вЂ“ charge meter shroud", (-.005, -.0405, .004),
        (.028, .005, .073), m["seal"], .0035)
    for index in range(5):
        box(collection, f"Cell вЂ“ charge segment {index + 1}", (-.005, -.0435, -.022 + .013 * index),
            (.017, .003, .007), m["charge"] if index == 0 else m["seal"], .0016)
    spindle(collection, "Cell вЂ“ charge check button", (.018, -.040, -.039), .0065, .004,
            m["seal"], (0, -1, 0), 16, .001)
    box(collection, "Cell вЂ“ service latch", (.028, -.038, .049),
        (.015, .011, .021), m["metal"], .003)
    box(collection, "Cell вЂ“ spring lock tab", (.030, -.044, .048),
        (.010, .005, .011), m["mark"], .0015)
    label(collection, "Cell вЂ“ etched charge and voltage plate", (0, -.040, .055),
          .043, .018, m["power"])
    label(collection, "Cell вЂ“ caution inset", (0, -.040, -.050),
          .043, .018, m["caution"])


def vector(v):
    return dict(zip("xyz", [round(component, 7) for component in v]))


def rgba(values):
    return dict(zip("rgba", (*values, 1)))


def export(collection, name, material_order=None):
    objects = [obj for obj in collection.objects if obj.type == "MESH"]
    mats = material_order or list(dict.fromkeys(mat for obj in objects for mat in obj.data.materials))
    material_index = {mat: index for index, mat in enumerate(mats)}
    vertices, normals, uv, submeshes, seen = [], [], [], defaultdict(list), {}
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        for triangle in mesh.loop_triangles:
            material_id = material_index[mesh.materials[triangle.material_index]]
            for loop in triangle.loops:
                point = obj.matrix_world @ mesh.vertices[mesh.loops[loop].vertex_index].co
                normal = (normal_matrix @ mesh.corner_normals[loop].vector).normalized()
                texcoord = mesh.uv_layers.active.data[loop].uv
                key = tuple(round(x, 7) for x in (*point, *normal, *texcoord))
                if key not in seen:
                    seen[key] = len(vertices)
                    vertices.append(vector(point))
                    normals.append(vector(normal))
                    uv.append(vector(texcoord))
                submeshes[material_id].append(seen[key])
    data = {
        "name": name,
        "meshes": [{
            "name": name,
            "positions": vertices,
            "normals": normals,
            "uv": uv,
            "submeshes": [{"indices": submeshes[index], "material": index} for index in sorted(submeshes)],
        }],
        "materials": [{
            "name": mat.name,
            "color": rgba(mat["jug_color"]),
            "metallic": mat["jug_metallic"],
            "smoothness": 1 - mat["jug_roughness"],
            "emission": rgba(mat["jug_emission"]),
        } for mat in mats],
    }
    stats = {
        "triangles": sum(len(indices) for indices in submeshes.values()) // 3,
        "vertices": len(vertices),
        "min": [min(point[axis] for point in vertices) for axis in "xyz"],
        "max": [max(point[axis] for point in vertices) for axis in "xyz"],
        "materials": len(mats),
    }
    (OUT / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf8")
    return stats


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    OUT.mkdir(parents=True, exist_ok=True)
    palette = {
        "armor": material("Olive composite shell", (.027, .025, .023), .30, .69, .0006, wear=.25),
        "face": material("Olive ceramic faceplate", (.039, .034, .028), .36, .67, .0008, wear=.32),
        "lip": material("Graphite armor edging", (.050, .043, .035), .52, .66, .0005, wear=.16),
        "seal": material("Black elastomer", (.011, .012, .013), .08, .73, .0012),
        "gasket": material("Reinforced lower gasket", (.018, .020, .022), .08, .74, .0011),
        "glass": material("Charcoal armored glass", (.005, .006, .007), .35, .37),
        "metal": material("Machined gunmetal", (.084, .088, .091), .66, .55, .0005),
        "bolt": material("Phosphate fasteners", (.045, .047, .047), .67, .53),
        "brass": material("Brass battery terminals", (.405, .270, .092), .73, .37),
        "mark": material("Ocher hardware markings", (.095, .072, .042), .15, .68),
        "lens": material("Ruby sensor coating", (.055, .005, .009), .44, .23),
        "warning": material("Warning Label", (.23, .13, .029), .08, .55),
        "caution": material("Cell Caution Label", (.23, .13, .029), .08, .55),
        "power": material("Power Label", (.085, .099, .070), .12, .54),
        "charge": material("Green charge strips", (.068, .042, .017), .08, .48,
                           emission=(.045, .023, .004)),
    }
    collections = []
    for name in SCENE_COLLECTIONS:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
        collections.append(collection)
    helmet_collection, thermal_collection, cell_collection = collections
    build_helmet(sys.modules[__name__], helmet_collection, palette, False)
    thermal(thermal_collection, palette)
    cell(cell_collection, palette)
    helmet_lod1 = bpy.data.collections.new("JUG_HELMET_LOD1")
    bpy.context.scene.collection.children.link(helmet_lod1)
    build_helmet(sys.modules[__name__], helmet_lod1, palette, True)
    for collection in (*collections, helmet_lod1):
        for obj in collection.objects:
            project_hard_surface(obj)
    bpy.context.view_layer.update()
    stats = {name: export(collection, name) for collection, name in
             zip(collections, ("helmet", "thermal", "cell"))}
    helmet_materials = list(dict.fromkeys(mat for obj in helmet_collection.objects
                                          for mat in obj.data.materials))
    stats["helmet_lod1"] = export(helmet_lod1, "helmet_lod1", helmet_materials)
    if (OUT / "textures" / "rigid_materials.json").is_file():
        from v2_rigid_surface_blender import apply_materials

        apply_materials([*collections, helmet_lod1], OUT / "textures")
    helmet_lod1.hide_render = True
    helmet_lod1.hide_viewport = True
    (OUT / "mesh_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf8")
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "accessories.blend"))


if __name__ == "__main__":
    build()
