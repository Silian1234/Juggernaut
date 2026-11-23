"""Rasterize V5d UV triangles into Blender/EFT texture atlases."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[1]
SIZES = {"armor": 4096, "textile": 4096, "frame": 4096, "helmet": 2048}
PAD = 8
TILE_ROWS = 96
RELIEF_GAIN = {"armor": 1.58, "textile": 1.1, "frame": 1.65, "helmet": 1.35}
MAX_NORMAL_SLOPE = 0.78
# Leave room for the RGB8 round trip at the upper slope bound.
ENCODE_SLOPE = 0.765
STAGING = ROOT / "work" / "bake_v5b"


def normalize(vector):
    return vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), 1e-12)


def cross2(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def barycentric(x, y, steps, det, orig):
    delta_x = x - orig[..., 0]
    delta_y = y - orig[..., 1]
    first = (delta_x * steps[..., 1, 1] - delta_y * steps[..., 1, 0]) / det
    second = (delta_y * steps[..., 0, 0] - delta_x * steps[..., 0, 1]) / det
    return np.stack((1 - first - second, first, second), axis=-1)


def rasterize(uv, size):
    origin = uv[:, 0].astype(np.float64) * size
    steps = (uv[:, 1:].astype(np.float64) * size) - origin[:, None, :]
    det = cross2(steps[:, 0], steps[:, 1])
    pixels = uv * size - 0.5
    lo = np.maximum(np.ceil(pixels.min(axis=1) - 1e-6).astype(int), 0)
    hi = np.minimum(np.floor(pixels.max(axis=1) + 1e-6).astype(int), size - 1)
    labels = np.full((size, size), -1, dtype=np.int32)
    overlap = 0
    for face in np.flatnonzero((np.abs(det) > 1e-8) & np.all(hi >= lo, axis=1)):
        x0, y0 = lo[face]
        x1, y1 = hi[face] + 1
        x = np.arange(x0, x1)[None, :] + 0.5
        y = np.arange(y0, y1)[:, None] + 0.5
        weights = barycentric(x, y, steps[face], det[face], origin[face])
        inside = np.all(weights >= -1e-7, axis=-1)
        region = labels[y0:y1, x0:x1]
        collision_y, collision_x = np.nonzero((region >= 0) & np.all(weights > 1e-6, axis=-1))
        if collision_y.size:
            previous = region[collision_y, collision_x]
            previous_weights = barycentric(
                collision_x + x0 + 0.5, collision_y + y0 + 0.5,
                steps[previous], det[previous], origin[previous],
            )
            overlap += int(np.count_nonzero(np.all(previous_weights > 1e-6, axis=-1)))
        region[inside & (region < 0)] = face
    return labels, origin.astype(np.float32), steps.astype(np.float32), det.astype(np.float32), overlap


def seed_subpixel_islands(uv, det, charts, labels):
    """Give an island below centre-sampling resolution a valid padding source."""
    sampled = np.unique(labels[labels >= 0])
    missing = np.setdiff1d(charts, charts[sampled])
    size = len(labels)
    seeded = 0
    for chart in missing:
        faces = np.flatnonzero(charts == chart)
        face = faces[np.argmax(np.abs(det[faces]))]
        if abs(det[face]) <= 1e-8:
            continue
        center = uv[face].mean(axis=0) * size - 0.5
        xi, yi = np.round(center).astype(int)
        xx, yy = np.meshgrid(
            np.arange(max(0, xi - 2), min(size, xi + 3)),
            np.arange(max(0, yi - 2), min(size, yi + 3)),
        )
        distance = (xx - center[0]) ** 2 + (yy - center[1]) ** 2
        distance[labels[yy, xx] >= 0] = np.inf
        nearest = np.unravel_index(np.argmin(distance), distance.shape)
        if np.isfinite(distance[nearest]):
            labels[yy[nearest], xx[nearest]] = face
            seeded += 1
    return seeded, len(missing) - seeded


def smoothstep(value):
    t = np.clip(value, 0, 1)
    return t * t * (3 - 2 * t)


def geometry_masks(face, weights, pos, point, geometry):
    convex = np.zeros(len(face), dtype=np.float32)
    concave = np.zeros_like(convex)
    distance = np.full_like(convex, np.inf)
    for corner in range(3):
        convex_strength = geometry["convex_edges"][face, corner]
        concave_strength = geometry["concave_edges"][face, corner]
        active = (convex_strength > 0) | (concave_strength > 0)
        p0 = pos[face[active], (corner + 1) % 3]
        direction = pos[face[active], (corner + 2) % 3] - p0
        delta = point[active] - p0
        factor = np.einsum("ni,ni->n", delta, direction) / np.maximum(
            np.einsum("ni,ni->n", direction, direction), 1e-16,
        )
        width = np.linalg.norm(delta - np.clip(factor, 0, 1)[:, None] * direction, axis=1)
        convex_weight = convex_strength[active]
        concave_weight = concave_strength[active]
        near_convex = (convex_weight > 0) & (width < 0.004)
        distance[active] = np.minimum(distance[active], np.where(near_convex, width, np.inf))
        convex[active] = np.maximum(convex[active], convex_weight * (1 - smoothstep(width / 0.0032)))
        concave[active] = np.maximum(concave[active], concave_weight * (1 - smoothstep(width / 0.0045)))

    def interpolate(key):
        return np.einsum("ni,ni->n", weights, geometry[key][face])

    def interpolate_with_center(key):
        vertices = geometry[f"vertex_{key}"][face]
        linear = np.einsum("ni,ni->n", weights, vertices)
        center_correction = 27 * weights.prod(axis=1) * (geometry[f"center_{key}"][face] - vertices.mean(axis=1))
        return np.clip(linear + center_correction, 0, 1)

    broad_curve = 0.17 * interpolate("vertex_signed_curvature")
    convex = np.maximum(convex, broad_curve)
    concave = np.maximum(concave, -broad_curve)
    return distance, {
        "ao": interpolate_with_center("ao"),
        "convex": convex,
        "concave": concave,
        "contact": interpolate_with_center("contact"),
        "position_height": np.clip(interpolate("vertex_height"), 0, 1),
    }


def read_geometry_masks(path, triangles):
    with np.load(path, allow_pickle=False) as source:
        geometry = {}
        for key in (
            "convex_edges", "concave_edges", "vertex_signed_curvature",
            "vertex_ao", "center_ao", "vertex_contact", "center_contact", "vertex_height",
        ):
            values = np.asarray(source[key], dtype=np.float32)
            shape = (triangles,) if key.startswith("center_") else (triangles, 3)
            minimum = -1 if key == "vertex_signed_curvature" else 0
            if values.shape != shape or not np.isfinite(values).all() or np.any(values < minimum) or np.any(values > 1):
                raise ValueError(f"{path}: invalid {key}")
            geometry[key] = values
    return geometry


def to_u8(value):
    return np.rint(np.clip(value, 0, 1) * 255).astype(np.uint8)


def sample_rows(y0, y1, labels, origin, steps, det):
    y, x = np.nonzero(labels[y0:y1] >= 0)
    y += y0
    face = labels[y, x]
    x_center = x.astype(np.float32) + 0.5
    y_center = y.astype(np.float32) + 0.5
    weights = barycentric(x_center, y_center, steps[face], det[face], origin[face])
    # A subpixel island seed can lie just outside its representative triangle.
    weights = np.maximum(weights, 0)
    weights /= weights.sum(axis=1, keepdims=True)
    return y, x, face, weights.astype(np.float32)


def gradient(height, charts, labels, y, x, dy, dx):
    size = height.shape[0]
    yl, xl = np.maximum(y - dy, 0), np.maximum(x - dx, 0)
    yr, xr = np.minimum(y + dy, size - 1), np.minimum(x + dx, size - 1)
    chart = charts[labels[y, x]]
    left, right = labels[yl, xl], labels[yr, xr]
    left_valid = (left >= 0) & (charts[left] == chart) & ((yl != y) | (xl != x))
    right_valid = (right >= 0) & (charts[right] == chart) & ((yr != y) | (xr != x))
    center = height[y, x]
    lower = np.where(left_valid, height[yl, xl], center)
    upper = np.where(right_valid, height[yr, xr], center)
    return (upper - lower) / np.maximum(left_valid.astype(np.float32) + right_valid, 1)


def uv_derivatives(positions, steps, det):
    delta_1 = positions[:, 1] - positions[:, 0]
    delta_2 = positions[:, 2] - positions[:, 0]
    denom = np.where(np.abs(det) > 1e-8, det, 1)[:, None]
    dpdu = (delta_1 * steps[:, 1, 1, None] - delta_2 * steps[:, 0, 1, None]) / denom
    dpdv = (delta_2 * steps[:, 0, 0, None] - delta_1 * steps[:, 1, 0, None]) / denom
    return dpdu, dpdv


def tangent_normal(pu, pv, normal, hu, hv, loop_tangent=None):
    has_loop = np.zeros(len(pu), dtype=bool)
    tangent_axis = pu
    if loop_tangent is not None:
        has_loop = np.linalg.norm(loop_tangent[:, :3], axis=1) > 1e-6
        tangent_axis = np.where(has_loop[:, None], loop_tangent[:, :3], pu)
    normal_component = np.einsum("ni,ni->n", tangent_axis, normal)
    tangent = normalize(tangent_axis - normal * normal_component[:, None])
    bitangent = np.cross(normal, tangent)
    sign = np.einsum("ni,ni->n", pv, bitangent)
    if loop_tangent is not None:
        sign = np.where(has_loop, loop_tangent[:, 3], sign)
    bitangent = np.where(sign[:, None] < 0, -bitangent, bitangent)
    u_t = np.einsum("ni,ni->n", pu, tangent)
    u_b = np.einsum("ni,ni->n", pu, bitangent)
    v_t = np.einsum("ni,ni->n", pv, tangent)
    v_b = np.einsum("ni,ni->n", pv, bitangent)
    # Measure both physical texel steps in the sampled shading plane. A
    # sliver's short singular axis must not magnify roundoff into a false bump.
    det = u_t * v_b - u_b * v_t
    u_length = u_t * u_t + u_b * u_b
    v_length = v_t * v_t + v_b * v_b
    uv_dot = u_t * v_t + u_b * v_b
    major = np.sqrt((u_length + v_length + np.hypot(u_length - v_length, 2 * uv_dot)) * 0.5)
    minor = np.abs(det) / np.maximum(major, 1e-12)
    floor = np.maximum(0.000025, major * 0.032)
    reliability = smoothstep((minor - floor) / floor)
    valid = (reliability > 0) & np.isfinite(major)
    h_t = np.divide(hu * v_b - hv * u_b, det, out=np.zeros_like(hu), where=valid)
    h_b = np.divide(hv * u_t - hu * v_t, det, out=np.zeros_like(hv), where=valid)
    h_t *= reliability
    h_b *= reliability
    slope = np.hypot(h_t, h_b)
    gain = ENCODE_SLOPE / np.maximum(slope, ENCODE_SLOPE)
    return normalize(np.stack((-h_t * gain, -h_b * gain, np.ones_like(h_t)), axis=1)), reliability


def dilate(labels, maps, padding):
    if padding < 1:
        return
    size = len(labels)
    # EDT tiles include the entire distance threshold around each strip.
    for start in range(0, size, TILE_ROWS):
        stop = min(start + TILE_ROWS, size)
        base, end = max(start - padding, 0), min(stop + padding, size)
        background = labels[base:end] < 0
        if background.all():
            continue
        distance, indices = distance_transform_edt(background, return_indices=True)
        local = slice(start - base, stop - base)
        y, x = np.nonzero(background[local] & (distance[local] <= padding))
        src_y, src_x = indices[:, y + start - base, x]
        for pixels in maps.values():
            pixels[y + start, x] = pixels[src_y + base, src_x]


def save_maps(maps, destination, atlas):
    destination.mkdir(parents=True, exist_ok=True)
    for name, pixels in maps.items():
        path = destination / f"{atlas}_{name}.png"
        temp = destination / f".{atlas}_{name}.tmp"
        Image.fromarray(pixels[::-1]).save(temp, format="PNG", compress_level=3)
        temp.replace(path)


def audit_normals(pixels):
    """Check all RGB8 pixels, including unused texels and the island dilation."""
    bad = 0
    max_slope = max_length_error = 0.0
    for start in range(0, len(pixels), TILE_ROWS):
        xyz = pixels[start:start + TILE_ROWS].astype(np.float32) / 127.5 - 1
        xy = np.hypot(xyz[..., 0], xyz[..., 1])
        z = xyz[..., 2]
        slope = xy / np.maximum(z, 1e-8)
        length_error = np.abs(np.hypot(xy, z) - 1)
        bad += int(np.count_nonzero((z <= 0) | (slope > MAX_NORMAL_SLOPE) | (length_error > 0.007)))
        max_slope = max(max_slope, float(slope.max()))
        max_length_error = max(max_length_error, float(length_error.max()))
    if bad:
        raise ValueError(f"{bad:,} texels fail the RGB8 unit length or slope audit")
    return {
        "tested_pixels": int(pixels.shape[0] * pixels.shape[1]),
        "invalid_pixels": bad,
        "allowed_max_slope": MAX_NORMAL_SLOPE,
        "max_encoded_slope": max_slope,
        "max_unit_length_error": max_length_error,
    }


def byte_distribution(values):
    histogram = np.bincount(values, minlength=256)
    return {
        "min": round(float(values.min()) / 255, 6),
        "mean": round(float(values.mean()) / 255, 6),
        "max": round(float(values.max()) / 255, 6),
        "histogram": histogram.tolist(),
    }


def save_categories(report_dir, atlas, labels, material, obj, material_names, object_names, specgloss):
    size = len(labels)
    covered = labels >= 0
    material_ids = np.full((size, size), -1, dtype=np.int16)
    object_ids = np.full_like(material_ids, -1)
    if max(len(material_names), len(object_names)) > np.iinfo(np.int16).max:
        raise ValueError("Categorical atlas has too many IDs for the export format")
    material_ids[covered] = material[labels[covered]]
    object_ids[covered] = obj[labels[covered]]
    report = {}
    for index, name in enumerate(material_names):
        rgba = specgloss[material_ids == index]
        if not rgba.size:
            continue
        spec = rgba[:, :3]
        # Luminance coefficients match the render's scalar inspection.
        spec_value = np.rint(spec @ np.array((0.2126, 0.7152, 0.0722))).astype(np.uint8)
        report[str(index)] = {
            "name": str(name), "texels": len(spec),
            "spec": byte_distribution(spec_value),
            "spec_rgb": {channel: byte_distribution(spec[:, c]) for c, channel in enumerate("rgb")},
            "gloss": byte_distribution(rgba[:, 3]),
        }
    target = report_dir / f"{atlas}_categories.npz"
    temp = target.with_name(f".{target.name}.tmp.npz")
    np.savez_compressed(
        temp, coverage=covered[::-1], material_id=material_ids[::-1], object_id=object_ids[::-1],
        material_names=material_names, object_names=object_names,
    )
    temp.replace(target)
    return report


def bake(atlas, source, geometry_path, destination, report_dir, size, padding, preview=False):
    from bake_drive_v5b import apply as apply_drive
    from bake_markings import apply as apply_markings
    from bake_v5b_surfaces import evaluate

    start = perf_counter()
    with np.load(source, allow_pickle=False) as arrays:
        data = {name: arrays[name] for name in arrays.files}
    uv = np.asarray(data["uv"], dtype=np.float32)
    pos = np.asarray(data["pos"], dtype=np.float32)
    nrm = np.asarray(data["normals"], dtype=np.float32)
    geometry = read_geometry_masks(geometry_path, len(uv))
    if not (np.isfinite(uv).all() and np.isfinite(pos).all() and np.isfinite(nrm).all()):
        raise ValueError(f"{atlas}: geometry data contains non-finite values")
    if np.any(uv < 0) or np.any(uv > 1):
        raise ValueError(f"{atlas}: UV triangle outside 0–1 bounds")
    charts = data["chart"] if "chart" in data else data["island"]
    uv_islands = charts
    island_count = int(len(np.unique(charts)))
    material_names = data["material_names"]
    object_names = data["object_names"]
    material = np.asarray(data["mat"], dtype=np.int32)
    obj = np.asarray(data["obj"], dtype=np.int32)
    routing = np.column_stack((material, obj))
    groups, face_group = np.unique(routing, axis=0, return_inverse=True)
    # Filtering across material boundaries could turn a material height baseline into a seam.
    _, charts = np.unique(np.column_stack((charts, material)), axis=0, return_inverse=True)
    labels, origin, steps, det, overlap = rasterize(uv, size)
    if overlap and not preview:
        raise ValueError(f"{atlas}: {overlap:,} UV texel overlaps; recheck packing")
    seeded, unseeded = seed_subpixel_islands(uv, det, uv_islands, labels)
    if unseeded and not preview:
        raise ValueError(f"{atlas}: {unseeded} subpixel UV islands could not be seeded")
    covered = labels >= 0
    source_uv = data.get("source_uv")
    tangents = data.get("tangent")
    print(f"{atlas}: rasterized {len(uv):,} triangles, {covered.sum():,} covered texels", flush=True)

    height = np.zeros((size, size), dtype=np.float32)
    maps = {
        "albedo": np.zeros((size, size, 4), dtype=np.uint8),
        "normal": np.full((size, size, 3), (128, 128, 255), dtype=np.uint8),
        "specgloss": np.zeros((size, size, 4), dtype=np.uint8),
        "metallic": np.zeros((size, size), dtype=np.uint8),
        "ao": np.full((size, size), 255, dtype=np.uint8),
        "curvature": np.full((size, size), 128, dtype=np.uint8),
        "position": np.zeros((size, size), dtype=np.uint8),
    }
    for base in range(0, size, TILE_ROWS):
        y, x, face, weights = sample_rows(base, min(base + TILE_ROWS, size), labels, origin, steps, det)
        point = np.einsum("ni,nij->nj", weights, pos[face])
        normal = normalize(np.einsum("ni,nij->nj", weights, nrm[face]))
        distance, masks = geometry_masks(face, weights, pos, point, geometry)
        maps["ao"][y, x] = to_u8(masks["ao"])
        maps["curvature"][y, x] = to_u8(0.5 + 0.5 * (masks["convex"] - masks["concave"]))
        maps["position"][y, x] = to_u8(masks["position_height"])
        sample_uv = None if source_uv is None else np.einsum("ni,nij->nj", weights, source_uv[face])
        routes = face_group[face]
        order = np.argsort(routes, kind="stable")
        breaks = np.flatnonzero(np.diff(routes[order])) + 1
        for sample in np.split(order, breaks):
            if not len(sample):
                continue
            mat_id, obj_id = groups[routes[sample[0]]]
            material_name = str(material_names[mat_id])
            object_name = str(object_names[obj_id])
            uv_options = {} if sample_uv is None else {"source_uv": sample_uv[sample]}
            surface_masks = {key: value[sample] for key, value in masks.items()}
            albedo, relief, spec, gloss, metallic = evaluate(
                material_name, object_name, point[sample], normal[sample], distance[sample],
                **uv_options, **surface_masks,
            )
            albedo, relief, spec, gloss, metallic = apply_drive(
                material_name, object_name, point[sample], normal[sample], albedo, relief, spec, gloss, metallic,
            )
            albedo, relief, spec, gloss, metallic = apply_markings(
                object_name, point[sample], normal[sample], albedo, relief, spec, gloss, metallic,
                **surface_masks,
            )
            if not all(np.isfinite(value).all() for value in (albedo, relief, spec, gloss, metallic)):
                raise ValueError(f"{atlas}: non-finite surface for {material_name}, {object_name}")
            yi, xi = y[sample], x[sample]
            height[yi, xi] = relief * RELIEF_GAIN[atlas]
            gloss_byte = to_u8(gloss)
            maps["albedo"][yi, xi, :3] = to_u8(albedo)
            maps["albedo"][yi, xi, 3] = gloss_byte
            maps["specgloss"][yi, xi, :3] = to_u8(spec)
            maps["specgloss"][yi, xi, 3] = gloss_byte
            maps["metallic"][yi, xi] = to_u8(metallic)

    dpdu, dpdv = uv_derivatives(pos, steps, det)
    regularized_texels = zero_reliability_texels = 0
    for base in range(0, size, TILE_ROWS):
        y, x, face, weights = sample_rows(base, min(base + TILE_ROWS, size), labels, origin, steps, det)
        normal = normalize(np.einsum("ni,nij->nj", weights, nrm[face]))
        tangent = None if tangents is None else np.einsum("ni,nij->nj", weights, tangents[face])
        hu = gradient(height, charts, labels, y, x, 0, 1)
        hv = gradient(height, charts, labels, y, x, 1, 0)
        output, reliability = tangent_normal(dpdu[face], dpdv[face], normal, hu, hv, tangent)
        regularized_texels += int(np.count_nonzero(reliability < 1))
        zero_reliability_texels += int(np.count_nonzero(reliability == 0))
        maps["normal"][y, x] = to_u8(output * 0.5 + 0.5)
    del height

    dp = pos[:, 1:] - pos[:, :1]
    world_area = np.linalg.norm(np.cross(dp[:, 0], dp[:, 1]), axis=1) * 0.5
    uv_texel_area = np.abs(det) * 0.5
    sampled_faces = np.unique(labels[covered])
    pixel_count = int(covered.sum())
    normal_deviation = np.abs(maps["normal"][covered][:, :2].astype(np.int16) - 128).max(axis=1)
    density = np.sqrt(uv_texel_area.sum() / max(world_area.sum(), 1e-12))
    lod_density = {}
    if "lod" in data:
        for level in np.unique(data["lod"]):
            mask = data["lod"] == level
            level_density = np.sqrt(uv_texel_area[mask].sum() / max(world_area[mask].sum(), 1e-12))
            lod_density[str(level)] = round(float(level_density), 1)
    stats = {
        "size": size, "triangles": len(uv), "islands": island_count,
        "coverage_pct": round(100 * pixel_count / (size * size), 2),
        "faces_without_texel_centers": len(uv) - len(sampled_faces) + seeded,
        "seeded_subpixel_islands": seeded,
        "uv_overlaps": overlap, "dilation_px": padding,
        "texels_per_meter_area_weighted": round(float(density), 1),
        "texels_per_meter_by_lod": lod_density,
        "tilted_normal_pct": round(100 * float(np.mean(normal_deviation > 3)), 2),
        "normal_relief_gain": RELIEF_GAIN[atlas],
        "normal_regularized_covered_texels": regularized_texels,
        "normal_zero_reliability_covered_texels": zero_reliability_texels,
    }
    dilate(labels, maps, padding)
    stats["normal_audit"] = audit_normals(maps["normal"])
    normal = maps["normal"]
    packed = np.full((size, size, 4), 255, dtype=np.uint8)
    packed[..., 1:3] = normal[..., 1, None]
    packed[..., 3] = normal[..., 0]
    maps["normal_dxt5nm"] = packed
    save_maps(maps, destination, atlas)
    report_dir.mkdir(parents=True, exist_ok=True)
    material_stats = save_categories(
        report_dir, atlas, labels, material, obj, material_names, object_names, maps["specgloss"],
    )
    stats["bake_seconds"] = round(perf_counter() - start, 2)
    print(f"{atlas}: {json.dumps(stats)}", flush=True)
    stats["materials"] = material_stats
    stats_path = report_dir / f"{atlas}_raster.json"
    temporary = stats_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    temporary.replace(stats_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlases", nargs="*", metavar="atlas")
    parser.add_argument("--source", type=Path, default=ROOT / "work" / "bake")
    parser.add_argument("--out", type=Path, default=STAGING / "textures")
    parser.add_argument("--geometry", type=Path, help="mask source directory (defaults to --source)")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--size", type=int)
    parser.add_argument("--padding", type=int, default=PAD)
    parser.add_argument("--preview", action="store_true", help="allow unresolved UV overlaps in a work preview")
    args = parser.parse_args()
    invalid = set(args.atlases) - SIZES.keys()
    if invalid:
        parser.error(f"unknown atlases: {', '.join(sorted(invalid))}")
    if args.size is not None and args.size < 2:
        parser.error("--size must be at least 2")
    if args.padding < 0:
        parser.error("--padding must be nonnegative")
    if args.preview and args.out.resolve() in {(ROOT / "textures" / "v5d").resolve(), (STAGING / "textures").resolve()}:
        parser.error("--preview requires a separate --out directory")
    report_dir = args.report or (args.out if args.preview else STAGING)
    for atlas in args.atlases or SIZES:
        mask_path = (args.geometry or args.source) / f"{atlas}_geometry_v5b.npz"
        bake(atlas, args.source / f"{atlas}.npz", mask_path, args.out, report_dir,
             args.size or SIZES[atlas], args.padding, args.preview)


if __name__ == "__main__":
    main()
