"""Assign physically scaled surface UVs and a shared EXO shader to suit meshes.

Set object["v2_swatch_uv"] on a mesh to supply normalized 0–1 UVs per family.
Set object["v2_atlas_uv"] only for meshes whose UVs already target this atlas.
"""
from pathlib import Path
import struct
import zlib

import numpy as np

from v2_surface_maps import INNER, LAYOUT_TAG, PAD, SIZE, SWATCHES, TILE, generate

_TEXTURES = Path(__file__).resolve().parents[2] / "art" / "suit" / "textures"
_MATERIAL = "Juggernaut v3 atlas"
_SLOTS = {"albedo": "exo_dif", "normal": "exo_nrm", "gloss": "exo_gloss"}


def texture_paths():
    return {channel: _TEXTURES / f"{stem}.png" for channel, stem in _SLOTS.items()}


def family_name(material_name):
    key = material_name.casefold().removeprefix("v2_").split(".")[0]
    if key not in SWATCHES:
        raise ValueError(f"Unknown v2 surface family {material_name!r}")
    return key


def swatch_uv(family, u, v):
    tx, ty = SWATCHES[family_name(family)][:2]
    return ((tx * TILE + PAD + .5 + u * (INNER - 1)) / SIZE,
            (ty * TILE + PAD + .5 + v * (INNER - 1)) / SIZE)


def _atlas_exists(path):
    if not path.is_file():
        return False
    with path.open("rb") as stream:
        header = stream.read(96)
    return (len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n"
            and struct.unpack(">II", header[16:24]) == (SIZE, SIZE)
            and LAYOUT_TAG in header[33:])


def ensure_textures():
    paths = texture_paths()
    if not all(_atlas_exists(path) for path in paths.values()):
        generate(paths.values())
    return paths


def atlas_material(name=_MATERIAL, metallic=0.0, paths=None):
    import bpy

    paths = ensure_textures() if paths is None else paths
    material = bpy.data.materials.get(name)
    if material is not None and material.get("v2_atlas"):
        return material
    if material is None:
        material = bpy.data.materials.new(name)
    material.diffuse_color = (.036, .034, .033, 1)
    material.use_nodes = True
    material.node_tree.nodes.clear()
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (125, 240)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Specular IOR Level"].default_value = .34
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (430, 240)
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    for offset, (channel, path) in enumerate(paths.items()):
        image = bpy.data.images.load(str(path), check_existing=True)
        image.colorspace_settings.name = "sRGB" if channel == "albedo" else "Non-Color"
        # Embedded files support opening the .blend elsewhere. The original PNGs
        # are also kept so the offline Unity build can use the same source maps.
        if not image.packed_file:
            image.pack()
        image.filepath = f"//textures/{path.name}"
        sampler = nodes.new("ShaderNodeTexImage")
        sampler.label = channel.capitalize()
        sampler.image = image
        sampler.location = (-650, 245 - 280 * offset)
        if channel == "albedo":
            links.new(sampler.outputs["Color"], shader.inputs["Base Color"])
        elif channel == "normal":
            normal = nodes.new("ShaderNodeNormalMap")
            normal.location = (-230, -35)
            normal.inputs["Strength"].default_value = 1
            links.new(sampler.outputs["Color"], normal.inputs["Color"])
            links.new(normal.outputs["Normal"], shader.inputs["Normal"])
        else:
            invert = nodes.new("ShaderNodeMath")
            invert.operation = "SUBTRACT"
            invert.inputs[0].default_value = 1
            invert.location = (-230, -315)
            links.new(sampler.outputs["Color"], invert.inputs[1])
            links.new(invert.outputs[0], shader.inputs["Roughness"])
    material["v2_atlas"] = True
    return material


def _face_projection(normal):
    # Projection u cross v always points out of the selected piece. Keeping v
    # vertical on steep faces aligns fabric, scratches and seams with the body.
    axis = int(np.argmax(np.abs(normal)))
    positive = normal[axis] >= 0
    if axis == 0:
        return 1, 2, 1 if positive else -1
    if axis == 1:
        return 0, 2, -1 if positive else 1
    return 0, 1, 1 if positive else -1


def _atlas_mesh(obj, material):
    mesh = obj.data
    if obj.get("v2_atlas_uv"):
        if not mesh.uv_layers.active:
            raise ValueError(f"{obj.name} declares atlas UVs and has no active UV layer")
    else:
        families = {}
        override = obj.get("v2_family")
        for polygon in mesh.polygons:
            index = polygon.material_index
            if index in families:
                continue
            slot = obj.material_slots[index].material if index < len(obj.material_slots) else None
            family = override or (slot.name if slot is not None else "fabricdark")
            try:
                families[index] = family_name(family)
            except ValueError as error:
                raise ValueError(f"{obj.name}: {error}") from error
        existing = mesh.uv_layers.active
        uv = existing or mesh.uv_layers.new(name="UVMap")
        if obj.get("v2_swatch_uv"):
            for polygon in mesh.polygons:
                key = families[polygon.material_index]
                for index in polygon.loop_indices:
                    u, v = uv.data[index].uv
                    if not (-.001 <= u <= 1.001 and -.001 <= v <= 1.001):
                        raise ValueError(f"{obj.name}: custom swatch UV exceeds its tile")
                    uv.data[index].uv = swatch_uv(key, u, v)
        else:
            _project_mesh(obj, uv, families)
    if material is not None:
        set_material(obj, material)
    obj["v2_atlas_uv"] = True


def set_material(obj, material):
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for slot in obj.material_slots:
        slot.link = "DATA"
        slot.material = material
    for polygon in obj.data.polygons:
        polygon.material_index = 0


def _project_mesh(obj, uv, families):
    mesh = obj.data
    coordinate = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coordinate)
    mw = np.asarray(obj.matrix_world, dtype=np.float32)
    try:
        axes = np.linalg.inv(mw[:3, :3]).T
    except np.linalg.LinAlgError as error:
        raise ValueError(f"{obj.name}: cannot project UVs through singular transform") from error
    points = coordinate.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    loop_vertex = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertex)
    groups = {}
    for polygon in mesh.polygons:
        key = families[polygon.material_index]
        axis_u, axis_v, u_sign = _face_projection(axes @ polygon.normal)
        groups.setdefault((key, axis_u, axis_v, u_sign), []).extend(polygon.loop_indices)

    results = np.empty((len(mesh.loops), 2), dtype=np.float32)
    part = obj.name.split(".")[0].replace("EXO1_V2", "EXO_V2", 1).replace("_LOD1", "_LOD0", 1)
    for (key, axis_u, axis_v, u_sign), indices in groups.items():
        work = points[loop_vertex[indices]][:, (axis_u, axis_v)]
        work[:, 0] *= u_sign
        minimum = work.min(axis=0)
        work -= minimum
        extent = work.max(axis=0)
        span = max(float(np.max(extent)) * 1.005, SWATCHES[key][2])
        seed = zlib.crc32(f"{part}:{key}:{axis_u}:{u_sign}".encode())
        unit = np.array(((seed & 65535) / 65535, (seed >> 16) / 65535))
        coords = work / span + (1 - extent / span) * unit
        u0, v0 = swatch_uv(key, 0, 0)
        results[indices] = (u0, v0) + coords * ((INNER - 1) / SIZE)
    uv.data.foreach_set("uv", results.ravel())


def finalize(collections, *, uv_only=False):
    """Finalize one or more Blender collections. Return the source atlas paths."""
    import bpy

    material = None if uv_only else atlas_material()
    objects = {}
    for collection in collections:
        if isinstance(collection, str):
            collection = bpy.data.collections[collection]
        for obj in collection.all_objects:
            if obj.type == "MESH" and len(obj.data.polygons):
                objects[obj.name] = obj
    bpy.context.view_layer.update()
    for name, obj in sorted(objects.items()):
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        _atlas_mesh(obj, material)
    print(f"EXO atlas UVs: {len(objects)} meshes, {len(SWATCHES)} surface families", flush=True)
    return texture_paths()


if __name__ == "__main__":
    generate(texture_paths().values())

