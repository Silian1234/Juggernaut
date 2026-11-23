"""Build the render-only vanilla PMC from extracted EFT geometry and maps."""
import json

import bpy
from mathutils import Matrix


def material_from_maps(directory, stem):
    material = bpy.data.materials.new(f"EFT vanilla {stem}")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    shader.inputs["Specular IOR Level"].default_value = .29
    if stem == "usec_head":
        shader.inputs["Subsurface Weight"].default_value = .07
        shader.inputs["Subsurface Scale"].default_value = .006

    def texture(suffix, data=False):
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(str(directory / f"{stem}_{suffix}.png"))
        if data:
            node.image.colorspace_settings.name = "Non-Color"
        return node

    albedo = texture("d")
    # The EFT diffuse alpha stores a material mask. Skin and clothes are opaque.
    albedo.image.alpha_mode = "CHANNEL_PACKED"
    tree.links.new(albedo.outputs["Color"], shader.inputs["Base Color"])
    gloss = texture("g", data=True)
    roughness = tree.nodes.new("ShaderNodeMapRange")
    roughness.inputs["To Min"].default_value = .91 if stem != "usec_head" else .78
    roughness.inputs["To Max"].default_value = .46
    tree.links.new(gloss.outputs["Color"], roughness.inputs["Value"])
    tree.links.new(roughness.outputs["Result"], shader.inputs["Roughness"])
    normal = tree.nodes.new("ShaderNodeNormalMap")
    normal.inputs["Strength"].default_value = .66
    tree.links.new(texture("n", data=True).outputs["Color"], normal.inputs["Color"])
    tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
    return material


def transfer_native_weights(source, target, armature):
    """The scene REF meshes contain the same Unity vertices in a different order."""
    transform = source.matrix_world
    weights = {}
    for vertex in source.data.vertices:
        point = tuple(transform @ vertex.co)
        weights[point] = [(entry.group, entry.weight) for entry in vertex.groups
                          if entry.weight > 0]
    for group in source.vertex_groups:
        target.vertex_groups.new(name=group.name)
    for vertex in target.data.vertices:
        for group, weight in weights[tuple(vertex.co)]:
            target.vertex_groups[group].add([vertex.index], weight, "REPLACE")
    modifier = target.modifiers.new("EFT skinning", "ARMATURE")
    modifier.object = armature


def mesh_from_donor(scene, directory, stem):
    asset = json.loads((directory / f"{stem}.json").read_text(encoding="utf8"))
    mesh = bpy.data.meshes.new(f"PMC {stem}")
    mesh.from_pydata(asset["positions"], [], asset["triangles"])
    mesh.update()
    layer = mesh.uv_layers.new(name="EFT UV0")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    layer.uv.foreach_set("vector", [coord for loop in mesh.loops
                                    for coord in asset["uv"][loop.vertex_index]])
    mesh.normals_split_custom_set_from_vertices(asset["normals"])
    mesh.materials.append(material_from_maps(directory, stem))
    obj = bpy.data.objects.new(mesh.name, mesh)
    scene.collection.objects.link(obj)
    return obj


def load_pmc(scene, directory, armature):
    clothing = []
    for stem, source_name in (("usec_body", "REF_top"), ("pants_usec_commando", "REF_pants")):
        donor = mesh_from_donor(scene, directory, stem)
        transfer_native_weights(bpy.data.objects[source_name], donor, armature)
        clothing.append(donor)
    head = mesh_from_donor(scene, directory, "usec_head")
    return clothing, head


def snapshot_pmc(scene, meshes):
    """Freeze the shared presentation pose before spacing the two figures apart."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    copies = []
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True,
                                              depsgraph=depsgraph)
        copy = bpy.data.objects.new(f"Scale comparison {obj.name}", mesh)
        scene.collection.objects.link(copy)
        copy.matrix_world = Matrix(evaluated.matrix_world)
        copies.append(copy)
    return copies
