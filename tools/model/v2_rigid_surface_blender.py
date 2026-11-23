"""Apply the exported accessory texture sets in a Blender scene."""
import json
from pathlib import Path

import bpy


def apply_materials(collections, tex_dir):
    tex_dir = Path(tex_dir)
    manifest = json.loads((tex_dir / "rigid_materials.json").read_text(encoding="utf-8"))
    materials = {m for collection in collections for obj in collection.objects
                 if obj.type == "MESH" for m in obj.data.materials if m}
    for material in materials:
        maps = manifest[material.name]
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (630, 80)
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        shader.location = (340, 80)
        shader.inputs["Metallic"].default_value = material["jug_metallic"]
        shader.inputs["Emission Color"].default_value = (*material["jug_emission"], 1)
        shader.inputs["Emission Strength"].default_value = 1
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])

        albedo = nodes.new("ShaderNodeTexImage")
        albedo.location = (-530, 260)
        albedo.label = "Albedo and gloss"
        albedo.image = bpy.data.images.load(str(tex_dir / maps["albedo"]), check_existing=True)
        albedo.image.alpha_mode = "CHANNEL_PACKED"
        albedo.image.pack()
        links.new(albedo.outputs["Color"], shader.inputs["Base Color"])

        invert_roughness = nodes.new("ShaderNodeMath")
        invert_roughness.operation = "SUBTRACT"
        invert_roughness.inputs[0].default_value = 1
        invert_roughness.location = (-100, 220)
        links.new(albedo.outputs["Alpha"], invert_roughness.inputs[1])
        links.new(invert_roughness.outputs[0], shader.inputs["Roughness"])

        normals = nodes.new("ShaderNodeTexImage")
        normals.location = (-530, -80)
        normals.label = "Tangent normals"
        normals.image = bpy.data.images.load(str(tex_dir / maps["normal"]), check_existing=True)
        normals.image.colorspace_settings.name = "Non-Color"
        normals.image.pack()
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (-100, -80)
        links.new(normals.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])

        gloss = nodes.new("ShaderNodeTexImage")
        gloss.location = (-530, -390)
        gloss.label = "Specular response"
        gloss.image = bpy.data.images.load(str(tex_dir / maps["gloss"]), check_existing=True)
        gloss.image.colorspace_settings.name = "Non-Color"
        gloss.image.alpha_mode = "CHANNEL_PACKED"
        gloss.image.pack()
        links.new(gloss.outputs["Color"], shader.inputs["Specular IOR Level"])
