"""Shared flat-color materials for the geometry review."""

import bpy


FINISHES = {
    "plate": ("Khaki paint", (.078, .066, .046), .71, 0.0),
    "edge": ("Khaki chamfers", (.093, .079, .055), .65, .03),
    "frame": ("Dark graphite frame", (.061, .065, .068), .54, .38),
    "steel": ("Steel hardware", (.115, .118, .120), .50, .57),
    "strap": ("Black nylon webbing", (.026, .027, .025), .84, 0.0),
    "rubber": ("Black molded rubber", (.012, .013, .014), .78, 0.0),
    "yellow": ("Yellow cable jacket", (.63, .34, .031), .57, 0.0),
    "black": ("Graphite polymer", (.028, .030, .031), .61, 0.0),
    "visor": ("Opaque black visor", (.007, .009, .011), .26, .04),
    "fabric": ("Black woven cloth", (.020, .022, .024), .87, 0.0),
    "velcro": ("Black hook and loop", (.034, .035, .032), .94, 0.0),
    "band": ("Black retention webbing", (.022, .023, .021), .87, 0.0),
    "steel_edge": ("Machined steel chamfers", (.153, .157, .158), .44, .65),
    "helmet": ("Graphite helmet laminate", (.039, .041, .043), .70, .04),
}


def flat_material(label, color, roughness, metallic=0.0, *, specular=.28, sheen=0.0):
    """Create a named surface using constant Principled BSDF inputs."""
    existing = bpy.data.materials.get(label)
    if existing is not None:
        return existing

    mat = bpy.data.materials.new(label)
    mat.diffuse_color = (*color, 1.0)
    mat.roughness = roughness
    mat.metallic = metallic
    mat.use_nodes = True
    graph = mat.node_tree
    graph.nodes.clear()
    shader = graph.nodes.new("ShaderNodeBsdfPrincipled")
    output = graph.nodes.new("ShaderNodeOutputMaterial")
    output.location = (340, 0)
    shader.inputs["Base Color"].default_value = mat.diffuse_color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Specular IOR Level"].default_value = specular
    shader.inputs["Sheen Weight"].default_value = sheen
    graph.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return mat


def material(name):
    """Return the shared material for a finish key."""
    key = name.lower()
    label, color, roughness, metallic = FINISHES[key]
    sheen = .08 if key in {"strap", "fabric", "velcro", "band"} else 0.0
    return flat_material(f"V5 | {label}", color, roughness, metallic, sheen=sheen)
