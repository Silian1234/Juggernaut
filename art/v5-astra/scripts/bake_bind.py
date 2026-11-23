"""Rebind spec/gloss materials on the frozen textured V5d scene.

Run from any directory with Blender in background mode:
  blender -b --python-exit-code 1 --python art/v5-astra/scripts/bake_bind.py
"""

from array import array
from hashlib import sha256
import json
from pathlib import Path
import struct

import bpy


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "bake"
FROZEN_LAYOUT = WORK / "layout.blend"
SLOTS = WORK / "atlas_slots.json"
DESTINATION = ROOT / "juggernaut_v5_textured.blend"
UV_NAME = "V5_Bake"
ATLASES = ("armor", "textile", "frame", "helmet")
MAPS = {
    "albedo": ("Base Color · sRGB", "sRGB", (6,)),
    "normal": ("Tangent Normal · +Y", "Non-Color", (2,)),
    "specgloss": ("Specular RGB · Smoothness A", "Non-Color", (6,)),
}


def map_path(atlas, channel):
    return ROOT / "textures" / "v5d" / f"{atlas}_{channel}.png"


def material_name(atlas):
    return f"V5d Atlas | {atlas.capitalize()}"


def image_texture(nodes, links, uv, atlas, channel, y):
    label, space, _ = MAPS[channel]
    path = map_path(atlas, channel)
    image = bpy.data.images.load(str(path), check_existing=True)
    image.colorspace_settings.name = space
    if channel in {"albedo", "specgloss"}:
        image.alpha_mode = "CHANNEL_PACKED"
    image.filepath_raw = bpy.path.relpath(str(path), start=str(ROOT))
    node = nodes.new("ShaderNodeTexImage")
    node.name = f"Atlas {channel}"
    node.label = label
    node.image = image
    node.interpolation = "Linear"
    node.extension = "EXTEND"
    node.location = (-570, y)
    links.new(uv.outputs["UV"], node.inputs["Vector"])
    return node


def atlas_material(atlas):
    material = bpy.data.materials[material_name(atlas)]
    graph = material.node_tree
    nodes, links = graph.nodes, graph.links
    nodes.clear()
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = UV_NAME
    uv.location = (-830, 230)

    albedo = image_texture(nodes, links, uv, atlas, "albedo", 730)
    normal = image_texture(nodes, links, uv, atlas, "normal", 385)
    spec = image_texture(nodes, links, uv, atlas, "specgloss", 40)

    tangent = nodes.new("ShaderNodeNormalMap")
    tangent.space = "TANGENT"
    tangent.uv_map = UV_NAME
    tangent.location = (-210, 400)
    links.new(normal.outputs["Color"], tangent.inputs["Color"])

    roughness = nodes.new("ShaderNodeMath")
    roughness.label = "Roughness = 1 − Smoothness"
    roughness.operation = "SUBTRACT"
    roughness.use_clamp = True
    roughness.inputs[0].default_value = 1.0
    roughness.location = (-210, 110)
    links.new(spec.outputs["Alpha"], roughness.inputs[1])
    reflection = nodes.new("ShaderNodeBsdfMetallic")
    reflection.name = "Specular RGB Fresnel"
    reflection.label = "GGX reflection with RGB F0"
    reflection.distribution = "GGX"
    reflection.fresnel_type = "F82"
    # Cycles F82 with a white edge tint is the unmodified Schlick Fresnel curve.
    reflection.inputs["Edge Tint"].default_value = (1.0, 1.0, 1.0, 1.0)
    reflection.location = (940, 250)
    links.new(spec.outputs["Color"], reflection.inputs["Base Color"])
    links.new(roughness.outputs[0], reflection.inputs["Roughness"])
    links.new(tangent.outputs["Normal"], reflection.inputs["Normal"])

    def math_node(label, operation, location, first, second):
        node = nodes.new("ShaderNodeMath")
        node.label = label
        node.operation = operation
        node.location = location
        for socket, value in zip(node.inputs, (first, second)):
            if isinstance(value, float):
                socket.default_value = value
            else:
                links.new(value, socket)
        return node.outputs[0]

    # Schlick diffuse budget: (1 - max(F0)) * (1 - (1 - NdotV)^5).
    # The microfacet specular lobe evaluates Fresnel at the half-vector itself.
    f0 = nodes.new("ShaderNodeSeparateColor")
    f0.mode = "HSV"
    f0.label = "Max of RGB F0"
    f0.location = (-230, -160)
    links.new(spec.outputs["Color"], f0.inputs["Color"])
    diffuse_budget = math_node("1 - max(F0)", "SUBTRACT", (10, -140),
                               1.0, f0.outputs[2])

    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-460, -375)
    angle = nodes.new("ShaderNodeVectorMath")
    angle.operation = "DOT_PRODUCT"
    angle.label = "Normal dot view"
    angle.location = (-230, -370)
    links.new(tangent.outputs["Normal"], angle.inputs[0])
    links.new(geometry.outputs["Incoming"], angle.inputs[1])
    grazing = math_node("1 - cos(view angle)", "SUBTRACT", (10, -360),
                        1.0, angle.outputs["Value"])
    grazing.node.use_clamp = True
    schlick = math_node("Grazing Fresnel", "POWER", (210, -360), grazing, 5.0)
    transmission = math_node("View remittance", "SUBTRACT", (410, -360),
                             1.0, schlick)
    diffuse_weight = math_node("Remaining diffuse energy", "MULTIPLY", (610, -160),
                               diffuse_budget, transmission)

    diffuse_color = nodes.new("ShaderNodeVectorMath")
    diffuse_color.operation = "SCALE"
    diffuse_color.label = "Albedo scaled by diffuse energy"
    diffuse_color.location = (810, 730)
    links.new(albedo.outputs["Color"], diffuse_color.inputs[0])
    links.new(diffuse_weight, diffuse_color.inputs["Scale"])

    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.name = "Energy Limited Diffuse"
    diffuse.location = (1030, 730)
    links.new(diffuse_color.outputs["Vector"], diffuse.inputs["Color"])
    links.new(tangent.outputs["Normal"], diffuse.inputs["Normal"])

    surface = nodes.new("ShaderNodeAddShader")
    surface.location = (1250, 410)
    links.new(diffuse.outputs["BSDF"], surface.inputs[0])
    links.new(reflection.outputs["BSDF"], surface.inputs[1])
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (1470, 410)
    links.new(surface.outputs[0], output.inputs["Surface"])
    return material


def verify_pngs():
    for atlas in ATLASES:
        sizes = set()
        for channel, (_, _, types) in MAPS.items():
            path = map_path(atlas, channel)
            with path.open("rb") as stream:
                header = stream.read(29)
            if header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
                raise ValueError(f"{path}: invalid PNG header")
            width, height, depth, color_type = struct.unpack(">IIBB", header[16:26])
            if width != height or width not in (2048, 4096) or depth != 8 or color_type not in types:
                raise ValueError(f"{path}: unexpected atlas dimensions or channel layout")
            sizes.add(width)
        if len(sizes) != 1:
            raise ValueError(f"{atlas}: material channels use different atlas dimensions")
        print(f"V5d {atlas} atlas PNG {sizes.pop()} px")


def geometry_digest():
    """Fingerprint authored positions, winding, split normals, UVs, weights and rig binds."""
    digest = sha256()

    def update_rows(collection, attr, typecode, width):
        values = array(typecode, [0]) * (width * len(collection))
        collection.foreach_get(attr, values)
        digest.update(values.tobytes())

    for obj in sorted(bpy.data.objects, key=lambda data: data.name):
        if obj.type != "MESH":
            continue
        mesh = obj.data
        digest.update(obj.name.encode("utf8"))
        digest.update(repr((tuple(map(tuple, obj.matrix_world)),
                            obj.parent.name if obj.parent else None,
                            tuple(group.name for group in obj.vertex_groups),
                            tuple((m.name, m.object.name if m.object else None)
                                  for m in obj.modifiers if m.type == "ARMATURE"))).encode("utf8"))
        update_rows(mesh.vertices, "co", "f", 3)
        update_rows(mesh.edges, "vertices", "i", 2)
        update_rows(mesh.loops, "vertex_index", "i", 1)
        update_rows(mesh.loops, "edge_index", "i", 1)
        update_rows(mesh.polygons, "loop_start", "i", 1)
        update_rows(mesh.polygons, "loop_total", "i", 1)
        update_rows(mesh.polygons, "material_index", "i", 1)
        update_rows(mesh.corner_normals, "vector", "f", 3)
        for uv in mesh.uv_layers:
            digest.update(uv.name.encode("utf8"))
            update_rows(uv.uv, "vector", "f", 2)
        for vertex in mesh.vertices:
            digest.update(struct.pack("<I", len(vertex.groups)))
            for assignment in vertex.groups:
                digest.update(struct.pack("<If", assignment.group, assignment.weight))
    for armature in sorted(bpy.data.armatures, key=lambda data: data.name):
        for bone in armature.bones:
            digest.update(repr((bone.name, tuple(map(tuple, bone.matrix_local)),
                                bone.parent.name if bone.parent else None)).encode("utf8"))
    return digest.hexdigest()


def uv_layer_state():
    return {
        mesh.name: (mesh.uv_layers.active_index, tuple(
            (uv.name, uv.active_render, uv.active_clone) for uv in mesh.uv_layers
        ))
        for mesh in bpy.data.meshes if mesh.users
    }


def verify_saved(slots, expected_digest, expected_uv_state):
    if geometry_digest() != expected_digest or uv_layer_state() != expected_uv_state:
        raise RuntimeError("Geometry, UVs, face slots or skinning changed while binding atlases")
    for name, mapping in slots.items():
        obj = bpy.data.objects[name]
        if not obj.data.uv_layers[UV_NAME].active_render:
            raise RuntimeError(f"{name}: unexpected render UV layer")
        for index, atlas in mapping.items():
            material = obj.material_slots[int(index)].material
            if material is None or material.name != material_name(atlas):
                raise RuntimeError(f"{name}: missing {atlas} material in slot {index}")
    for atlas in ATLASES:
        material = bpy.data.materials[material_name(atlas)]
        nodes = material.node_tree.nodes
        if {node.name for node in nodes if node.type == "TEX_IMAGE"} != {
            f"Atlas {channel}" for channel in MAPS
        }:
            raise RuntimeError(f"{atlas}: unexpected image texture nodes")
        spec = nodes["Atlas specgloss"]
        reflection = nodes["Specular RGB Fresnel"]
        f0 = reflection.inputs["Base Color"].links[0]
        gloss = reflection.inputs["Roughness"].links[0].from_node
        if (f0.from_socket != spec.outputs["Color"] or reflection.fresnel_type != "F82"
                or gloss.operation != "SUBTRACT" or gloss.inputs[0].default_value != 1.0
                or gloss.inputs[1].links[0].from_socket != spec.outputs["Alpha"]
                or spec.image.alpha_mode != "CHANNEL_PACKED"):
            raise RuntimeError(f"{atlas}: unexpected spec/gloss shader link")
        for channel, (_, space, _) in MAPS.items():
            image = nodes[f"Atlas {channel}"].image
            expected = map_path(atlas, channel)
            link = "//" + expected.relative_to(ROOT).as_posix()
            observed = Path(bpy.path.abspath(image.filepath)).resolve()
            if (image.filepath.replace("\\", "/") != link or observed != expected
                    or image.packed_file or image.colorspace_settings.name != space
                    or not all(image.size)):
                raise RuntimeError(f"{atlas}: invalid saved {channel} image link {image.filepath}")


def main():
    verify_pngs()
    slots = json.loads(SLOTS.read_text(encoding="utf-8"))
    if {atlas for mapping in slots.values() for atlas in mapping.values()} != set(ATLASES):
        raise ValueError("Slot manifest atlas names do not match the material contract")
    bpy.ops.wm.open_mainfile(filepath=str(FROZEN_LAYOUT))
    frozen_digest = geometry_digest()
    bpy.ops.wm.open_mainfile(filepath=str(DESTINATION))
    before = geometry_digest()
    uv_state = uv_layer_state()
    if before != frozen_digest:
        raise RuntimeError(f"Textured scene {before} diverges from frozen layout {frozen_digest}")
    for atlas in ATLASES:
        atlas_material(atlas)
        unused = bpy.data.images.get(f"{atlas}_metallic.png")
        if unused and not unused.users:
            bpy.data.images.remove(unused)

    bpy.context.preferences.filepaths.save_version = 0
    staged = DESTINATION.with_name(f".{DESTINATION.stem}.pending.blend")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(staged), relative_remap=True, compress=True)
        bpy.ops.wm.open_mainfile(filepath=str(staged))
        verify_saved(slots, before, uv_state)
        staged.replace(DESTINATION)
    finally:
        staged.unlink(missing_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(DESTINATION))
    verify_saved(slots, before, uv_state)
    print(f"V5d verified {len(slots)} meshes and {sum(map(len, slots.values()))} slots")
    print(f"V5d frozen geometry, all UVs, and skinning: {before}")
    print(f"V5d reopened {DESTINATION.name} with {len(ATLASES) * len(MAPS)} relative image links")


if __name__ == "__main__":
    main()
