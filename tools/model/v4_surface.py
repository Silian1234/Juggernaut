"""Bake geometry contact shadows into the three maps consumed by the EFT suit.

Base swatches and the original TV-110 maps occupy the left atlas column.
Selected non-overlapping UV islands get dedicated padded rectangles on the right.
The per-island transform is a positive uniform scale and translation, preserving
native UV seams, tangent orientation and the registration of all three maps.
"""
from dataclasses import dataclass
from math import ceil, cos, pi, sin, sqrt
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import numpy as np

import v2_surface
from v2_surface_maps import SIZE, SWATCHES, TILE, _save_png, _tile


CHANNELS = {"albedo": "exo_dif", "normal": "exo_nrm", "gloss": "exo_gloss"}
DONOR_DIR = Path(__file__).resolve().parents[2] / "art/build/v4-tactical"
PATCH_PAD = 12
LAYOUT_TAG = b"JuggernautLayout\x00v4-walnut-patina-ao"
AO_STRIDE = 4
AO_REACH = .055
MIN_CHART_AREA = .0007
_COLOR_SPEC = {
    # Retain contrast within neutral manganese plates under Tarkov lighting.
    "olive": ((47, 46, 44), 59, "paint"),
    "graphite": ((36, 37, 37), 48, "paint"),
    "steel": ((64, 64, 63), 74, "steel"),
    "edge": ((61, 61, 59), 67, "edge"),
    "edge_dark": ((50, 50, 49), 58, "edge"),
    "strap": ((77, 62, 45), 37, "strap"),
    "tan": ((93, 76, 55), 38, "strap"),
    "rubber": ((27, 27, 27), 39, "rubber"),
}
_RAYS = []
for sample in range(20):
    radius_squared = (sample + .5) / 20
    angle = sample * pi * (3 - sqrt(5))
    radius = sqrt(radius_squared)
    _RAYS.append((radius * cos(angle), radius * sin(angle), sqrt(1 - radius_squared)))


@dataclass
class Chart:
    obj: object
    triangles: np.ndarray
    area: float
    minimum: np.ndarray
    maximum: np.ndarray


def _visibility(bvh, position, normal):
    """Cosine-weighted hemisphere visibility with smooth distance falloff."""
    normal = Vector(normal).normalized()
    tangent = normal.orthogonal().normalized()
    bitangent = normal.cross(tangent)
    origin = Vector(position) + normal * .0008
    shade = 0.0
    for u, v, w in _RAYS:
        direction = tangent * u + bitangent * v + normal * w
        distance = bvh.ray_cast(origin, direction, AO_REACH)[3]
        if distance is not None:
            fade = distance / AO_REACH
            shade += 1 - fade * fade * (3 - 2 * fade)
    return 1 - shade / len(_RAYS)


def _half_tile(tile):
    summed = tile[0::2, 0::2].astype(np.uint16)
    summed += tile[1::2, 0::2]
    summed += tile[0::2, 1::2]
    summed += tile[1::2, 1::2]
    return ((summed + 2) // 4)[::-1]


def _generated_sources():
    sources = [np.full((SIZE // 2, SIZE // 2, 3), 255, dtype=np.uint8) for _ in CHANNELS]
    half = TILE // 2
    for name, spec in SWATCHES.items():
        x, y = (coordinate * half for coordinate in spec[:2])
        spec = (*spec[:3], *_COLOR_SPEC.get(name, spec[3:]))
        for atlas, tile in zip(sources, _tile(name, spec, weathered=True)):
            atlas[y:y+half, x:x+half] = _half_tile(tile)
    return sources


def _read_source(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        width, height = image.size[:]
        if width <= 0 or height <= 0:
            raise ValueError(f"Cannot open native suit map {path}")
        values = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(values)
        return np.round(values.reshape(height, width, 4)[..., :3] * 255).astype(np.uint8)
    finally:
        bpy.data.images.remove(image)


def _sample(image, x, y):
    """Sample bottom-up pixels at normalized UVs with clamped addressing."""
    height, width = image.shape[:2]
    x = np.clip(x * width - .5, 0, width - 1)
    y = np.clip(y * height - .5, 0, height - 1)
    left = x.astype(np.int32)
    bottom = y.astype(np.int32)
    right = np.minimum(left + 1, width - 1)
    top = np.minimum(bottom + 1, height - 1)
    dx = (x - left)[None, :, None]
    dy = (y - bottom)[:, None, None]
    lower = image[bottom[:, None], left] * (1 - dx) + image[bottom[:, None], right] * dx
    upper = image[top[:, None], left] * (1 - dx) + image[top[:, None], right] * dx
    return np.round(lower * (1 - dy) + upper * dy).astype(np.uint8)


def _geometry(obj):
    mesh = obj.data
    active = mesh.uv_layers.active
    if active is None:
        raise ValueError(f"{obj.name} is missing its atlas UVs")
    mesh.calc_loop_triangles()
    matrix = np.array(obj.matrix_world, dtype=np.float32)
    coords = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    mesh.vertices.foreach_get("co", coords.ravel())
    coords = coords @ matrix[:3, :3].T + matrix[:3, 3]
    tri_loops = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", tri_loops.ravel())
    verts = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", verts)
    uv = np.empty((len(mesh.loops), 2), dtype=np.float32)
    active.data.foreach_get("uv", uv.ravel())
    corners = np.empty((len(mesh.loops), 3), dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", corners.ravel())
    corners = corners @ np.linalg.inv(matrix[:3, :3])
    return coords, tri_loops, verts, uv, corners


def _charts(obj, geometry):
    coords, triangles, verts, uv, _ = geometry
    # Triangles are joined by the pair of UV vertices on each shared edge.
    uv_key = np.rint(uv * 1_000_000).astype(np.int32)
    uvs = [(int(vertex), *point) for vertex, point in zip(verts, uv_key)]
    parents = list(range(len(triangles)))

    def find(index):
        while index != parents[index]:
            index = parents[index]
        return index

    edges = {}
    for index, (a, b, c) in enumerate(triangles):
        for i, j in ((a, b), (b, c), (c, a)):
            edge = tuple(sorted((uvs[i], uvs[j])))
            previous = edges.setdefault(edge, index)
            root, other = find(index), find(previous)
            if root != other:
                parents[max(root, other)] = min(root, other)
    islands = {}
    for index in range(len(triangles)):
        islands.setdefault(find(index), []).append(index)
    points = coords[verts[triangles]]
    cross = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    areas = np.linalg.norm(cross, axis=-1) * .5
    for indices in islands.values():
        area = float(np.sum(areas[indices]))
        if area < MIN_CHART_AREA:
            continue
        samples = uv[triangles[indices]]
        minimum = samples.min(axis=(0, 1))
        maximum = samples.max(axis=(0, 1))
        if np.any(maximum - minimum < .0001):
            continue
        yield Chart(obj, np.asarray(indices), area, minimum, maximum)


def _scene_bvh(collection, geometries):
    points = []
    triangles = []
    for obj in collection.all_objects:
        if obj.name not in geometries or obj.get("v4_ao_ignore"):
            continue
        coord, tri_loops, verts, _, _ = geometries[obj.name]
        # Thin printed overlays should neither shade themselves nor fully shadow
        # the underlying armor face when their coplanar decal receives the bake.
        if obj.get("v2_swatch_uv") and any(
            tag in obj.name.casefold() for tag in ("stamp", "decal", "label", "marking")
        ):
            continue
        triangles.extend((verts[tri_loops] + len(points)).tolist())
        points.extend(coord.tolist())
    return BVHTree.FromPolygons(points, triangles, all_triangles=True)


def _take_rectangle(free, width, height):
    candidates = [(w * h, index) for index, (_, _, w, h) in enumerate(free)
                  if width <= w and height <= h]
    if not candidates:
        return None
    _, index = min(candidates)
    x, y, w, h = free.pop(index)
    if w - width > h - height:
        additions = [(x + width, y, w - width, h), (x, y + height, width, h - height)]
    else:
        additions = [(x + width, y, w - width, height), (x, y + height, w, h - height)]
    free.extend(rect for rect in additions if min(rect[2:]) >= 2 * PATCH_PAD + AO_STRIDE)
    return x, y


def _raster_chart(chart, geometry, width, height, scale):
    coords, tris, verts, uv, corner_normals = geometry
    covered = np.zeros((height, width), dtype=bool)
    positions = np.empty((height, width, 3), dtype=np.float32)
    normals = np.empty_like(positions)
    overlap = 0
    for loops in tris[chart.triangles]:
        a, b, c = (uv[loops] - chart.minimum) * (scale / AO_STRIDE)
        ab, ac = b - a, c - a
        denominator = ab[0] * ac[1] - ab[1] * ac[0]
        if abs(denominator) < 1e-8:
            continue
        x0, y0 = np.maximum(np.floor(np.minimum(np.minimum(a, b), c)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(np.maximum(np.maximum(a, b), c)).astype(int), (width, height))
        yy, xx = np.mgrid[y0:y1, x0:x1]
        px, py = xx + .5 - a[0], yy + .5 - a[1]
        b_weight = (px * ac[1] - py * ac[0]) / denominator
        c_weight = (ab[0] * py - ab[1] * px) / denominator
        a_weight = 1 - b_weight - c_weight
        inside = (a_weight >= -1e-5) & (b_weight >= -1e-5) & (c_weight >= -1e-5)
        previous = covered[yy, xx]
        overlap += np.count_nonzero(previous & inside & (a_weight > .03)
                                   & (b_weight > .03) & (c_weight > .03))
        yy, xx = yy[inside], xx[inside]
        if yy.size == 0:
            continue
        weights = np.stack((a_weight[inside], b_weight[inside], c_weight[inside]), axis=-1)
        positions[yy, xx] = weights @ coords[verts[loops]]
        normals[yy, xx] = weights @ corner_normals[loops]
        covered[yy, xx] = True
    return covered, positions, normals, overlap


def _patch_ao(chart, geometry, bvh, width, height, scale):
    coarse_width = ceil(width / AO_STRIDE)
    coarse_height = ceil(height / AO_STRIDE)
    covered, positions, normals, overlap = _raster_chart(
        chart, geometry, coarse_width, coarse_height, scale,
    )
    count = np.count_nonzero(covered)
    if count == 0 or overlap > max(2, count * .025):
        return None
    pixels = np.ones((coarse_height + 6, coarse_width + 6), dtype=np.float32)
    mask = np.zeros_like(pixels, dtype=bool)
    core = (slice(3, 3 + coarse_height), slice(3, 3 + coarse_width))
    pixels[core][covered] = [
        _visibility(bvh, position, normal)
        for position, normal in zip(positions[covered], normals[covered])
    ]
    mask[core] = covered
    # Dilate occupied texels to keep bilinear samples and EFT mip texels clean
    # around irregular chart edges. Rolls are clipped at the patch boundaries.
    for _ in range(5):
        source_mask = mask.copy()
        for axis, direction in ((0, 1), (0, -1), (1, 1), (1, -1)):
            targets = np.roll(source_mask, direction, axis=axis) & ~mask
            border = [slice(None), slice(None)]
            border[axis] = 0 if direction > 0 else -1
            targets[tuple(border)] = False
            pixels[targets] = np.roll(pixels, direction, axis=axis)[targets]
            mask[targets] = True
    x = (np.arange(width + 2 * PATCH_PAD) + .5) / (AO_STRIDE * pixels.shape[1])
    y = (np.arange(height + 2 * PATCH_PAD) + .5) / (AO_STRIDE * pixels.shape[0])
    return _sample(np.round(pixels[..., None] * 255).astype(np.uint8), x, y)[..., 0]


def _chart_scale(chart, is_donor, lod):
    # The source images contain detail down to a nominal 2K atlas for built
    # parts and 1K for the donor. Raise resolution for large focal armor.
    source_scale = 1024 if is_donor else 2200
    extent = chart.maximum - chart.minimum
    cap = 512 / max(extent)
    return min(cap, source_scale * (1 if lod == 0 else .72))


def finalize(collections, texture_dir):
    """Build and assign a shared atlas from the v2 or preserved donor UVs."""
    texture_dir = Path(texture_dir).resolve()
    texture_dir.mkdir(parents=True, exist_ok=True)
    collections = [bpy.data.collections[c] if isinstance(c, str) else c for c in collections]
    object_sets = [[obj for obj in collection.all_objects
                    if obj.type == "MESH" and len(obj.data.polygons)] for collection in collections]
    objects = {obj.name: obj for group in object_sets for obj in group}
    if not objects:
        raise ValueError("Cannot bake the empty EXO suit")
    if any(obj.get("v4_atlas_uv") for obj in objects.values()):
        raise ValueError("Run the v4 atlas bake from a fresh pre-atlas suit build")
    bpy.context.view_layer.update()
    geometries = {name: _geometry(obj) for name, obj in objects.items()}
    generated = _generated_sources()
    chrome_names = {name for name in objects if "ChromeRod" in name}
    chrome = [_half_tile(pixels) for pixels in _tile(
        "chrome", (*SWATCHES["steel"][:3], (132, 133, 134), 120, "steel")
    )] if chrome_names else []
    # This dedicated tile sits in the free area beside the 1K native maps.
    chrome_x, chrome_y, chrome_size = 1536, 2048, TILE // 2
    donors = {obj.name for obj in objects.values() if obj.get("v4_donor")}
    native = [_read_source(DONOR_DIR / f"tv110-{channel}.png") for channel in CHANNELS] if donors else []
    if native and (any(image.shape != native[0].shape for image in native)
                   or max(native[0].shape[:2]) > SIZE // 2 - 2 * PATCH_PAD):
        raise ValueError("The native EFT tactical maps must share dimensions and fit in the atlas")
    if native and chrome and native[0].shape[1] + 2 * PATCH_PAD > chrome_x:
        raise ValueError("The tactical maps exceed the space reserved beside chrome")
    atlas = [np.empty((SIZE, SIZE, 3), dtype=np.uint8) for _ in CHANNELS]
    ao = np.full((SIZE, SIZE), 255, dtype=np.uint8)
    for index, (target, source) in enumerate(zip(atlas, generated)):
        target[:] = ((33, 33, 33), (128, 128, 255), (41, 41, 41))[index]
        target[:SIZE//2, :SIZE//2] = source
        if native:
            image = native[index]
            height, width = image.shape[:2]
            padded = np.pad(image, ((PATCH_PAD, PATCH_PAD), (PATCH_PAD, PATCH_PAD), (0, 0)),
                            mode="edge")
            target[SIZE//2:SIZE//2+padded.shape[0], :padded.shape[1]] = padded
        if chrome:
            target[chrome_y:chrome_y+chrome_size, chrome_x:chrome_x+chrome_size] = chrome[index]
    output_uv = {name: geometry[3].copy() for name, geometry in geometries.items()}
    for name, uv in output_uv.items():
        if name in donors:
            uv[:] = (uv * (width, height) + (PATCH_PAD, SIZE // 2 + PATCH_PAD)) / SIZE
        elif name in chrome_names:
            uv[:] = ((uv * 4 - SWATCHES["steel"][:2]) * chrome_size
                     + (chrome_x, chrome_y)) / SIZE
        else:
            uv *= .5
    free = [(SIZE // 2, 0, SIZE // 2, SIZE)]
    print(f"EXO v4 AO: {len(objects)} meshes, {len(donors)} native tactical", flush=True)
    # Spend the first half of the available chart area on visible LOD0. Keep
    # ample space for LOD1 rather than applying its stronger/different overlaps
    # to the same atlas texels at a different viewing distance.
    per_lod = []
    for lod, (collection, group) in enumerate(zip(collections, object_sets)):
        bvh = _scene_bvh(collection, geometries)
        charts = [chart for obj in group for chart in _charts(obj, geometries[obj.name])]
        charts.sort(key=lambda chart: (-chart.area, chart.obj.name))
        occupied = 0
        patched = 0
        skipped_overlap = 0
        skipped_space = 0
        for chart in charts:
            name = chart.obj.name
            is_donor = name in donors
            source = native if is_donor else chrome if name in chrome_names else generated
            scale = _chart_scale(chart, is_donor, lod)
            inner_width, inner_height = np.maximum(1, np.ceil(
                (chart.maximum - chart.minimum) * scale).astype(int))
            patch_width, patch_height = inner_width + 2 * PATCH_PAD, inner_height + 2 * PATCH_PAD
            patch_area = patch_width * patch_height
            if lod == 0 and occupied + patch_area > SIZE * SIZE * .30:
                skipped_space += 1
                continue
            trial = free.copy()
            location = _take_rectangle(trial, patch_width, patch_height)
            if location is None:
                skipped_space += 1
                continue
            geometry = geometries[name]
            shadow = _patch_ao(chart, geometry, bvh, inner_width, inner_height, scale)
            if shadow is None:
                skipped_overlap += 1
                continue
            x, y = location
            free = trial
            occupied += patch_area
            patched += 1
            x_source = chart.minimum[0] + (np.arange(patch_width) + .5 - PATCH_PAD) / scale
            y_source = chart.minimum[1] + (np.arange(patch_height) + .5 - PATCH_PAD) / scale
            if name in chrome_names:
                tx, ty = SWATCHES["steel"][:2]
                x_source = x_source * 4 - tx
                y_source = y_source * 4 - ty
            rect = np.s_[y:y+patch_height, x:x+patch_width]
            for index, (target, material) in enumerate(zip(atlas, source)):
                samples = _sample(material, x_source, y_source)
                if index == 0:
                    # EFT's material has no AO binding. Multiply diffuse in
                    # linear color while retaining some unoccluded fill.
                    attenuation = (.38 + .62 * shadow.astype(np.float32) / 255) ** (1 / 2.2)
                    samples = np.round(samples * attenuation[..., None]).astype(np.uint8)
                target[rect] = samples
            ao[rect] = shadow
            loops = np.unique(geometry[1][chart.triangles])
            output_uv[name][loops] = ((geometry[3][loops] - chart.minimum) * scale
                                      + (x + PATCH_PAD, y + PATCH_PAD)) / SIZE
        per_lod.append(patched)
        print(f"EXO v4 AO {collection.name}: {patched}/{len(charts)} islands, "
              f"{occupied:,} patch pixels, {skipped_overlap} overlapping or subpixel, "
              f"{skipped_space} on the shared swatch", flush=True)
    if not all(per_lod) or np.count_nonzero(ao < 225) < 100:
        raise ValueError("EXO v4 bake produced insufficient geometry occlusion")
    paths = {channel: texture_dir / f"{stem}.png" for channel, stem in CHANNELS.items()}
    for path, image in zip(paths.values(), atlas):
        _save_png(path, image[::-1], LAYOUT_TAG)
    _save_png(texture_dir / "exo_ao.png", np.repeat(ao[::-1, :, None], 3, axis=-1), LAYOUT_TAG)
    print(f"EXO v4 AO: {np.count_nonzero(ao < 225):,} shadowed pixels, "
          f"minimum visibility {ao.min()/255:.3f}", flush=True)
    material = v2_surface.atlas_material("Juggernaut v4 atlas", paths=paths)
    for name, uv in output_uv.items():
        obj = objects[name]
        obj.data.uv_layers.active.data.foreach_set("uv", uv.ravel())
        v2_surface.set_material(obj, material)
        obj["v4_atlas_uv"] = True
    return paths
