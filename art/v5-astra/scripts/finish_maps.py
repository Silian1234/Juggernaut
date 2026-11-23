"""Build seamless PBR bitmap tiles from a fixed seed in linear color."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "textures" / "finish"
SIZE = 512
rng = np.random.default_rng(805193)


def noise(grid):
    """Bicubic low-pass noise, wrapped so repeated tiles have no seam."""
    source = rng.random((grid, grid))
    source = np.pad(source, 2, mode="wrap")
    cell = SIZE / grid
    arr = Image.fromarray(source.astype(np.float32)).resize(
        (SIZE, SIZE), Image.Resampling.BICUBIC,
        box=(2, 2, grid + 2, grid + 2),
    )
    return np.asarray(arr).clip(0.0, 1.0)


def scratches(count, length, low_width, high_width):
    canvas = Image.new("L", (SIZE * 3, SIZE * 3))
    draw = ImageDraw.Draw(canvas)
    for _ in range(count):
        x, y = rng.uniform(0, SIZE, 2) + SIZE
        direction = rng.uniform(0, np.pi)
        radius = min(rng.exponential(length), 4 * length)
        dx, dy = np.cos(direction) * radius, np.sin(direction) * radius
        width = int(rng.integers(low_width, high_width + 1))
        strength = int(rng.uniform(55, 240))
        draw.line((x, y, x + dx, y + dy), fill=strength, width=width)
    values = np.asarray(canvas, np.float32).reshape(3, SIZE, 3, SIZE)
    return values.max(axis=(0, 2)) / 255.0


def smoothstep(lo, hi, value):
    percent = ((value - lo) / (hi - lo)).clip(0, 1)
    return percent * percent * (3 - 2 * percent)


def save_map(key, channel, values):
    pixels = (values.clip(0, 1) * 255 + 0.5).astype(np.uint8)
    Image.fromarray(pixels).save(OUT / f"{key}_{channel}.png")


def color_map(values):
    return np.where(values <= 0.0031308, 12.92 * values, 1.055 * values ** (1 / 2.4) - 0.055)


def save(key, color, roughness, height, metallic=None):
    save_map(key, "color", color_map(color.clip(0, 1)))
    save_map(key, "roughness", roughness)
    save_map(key, "height", height)
    # OpenGL tangent-space normal for conventional UV export. Blender uses the
    # matching height with direction-independent box projection.
    gx = np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
    gy = np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
    normal = np.stack((-gx * 0.92, gy * 0.92, np.ones_like(gx)), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    save_map(key, "normal", normal * 0.5 + 0.5)
    if metallic is not None:
        save_map(key, "metallic", metallic)


def paint_wear(key, base, roughness, metallic, threshold, rub_amount, weathering, exposed):
    cloud = noise(13) * 0.30 + noise(32) * 0.40 + noise(71) * 0.30
    grain = noise(180)
    pitting = noise(182)
    grit = smoothstep(0.64, 0.98, pitting)
    abrasion = scratches(50 if key == "edge" else 28, 15 if key == "edge" else 10, 1, 1) * (noise(26) * 0.65 + 0.35)
    flake_field = noise(67) * 0.48 + noise(122) * 0.33 + noise(222) * 0.19
    flakes = smoothstep(threshold - 0.027, threshold + 0.036, flake_field)
    wear = np.maximum(flakes, abrasion * rub_amount)
    # Oxide and dust collect in a wider halo around flaked paint.
    grime = smoothstep(0.46, 0.78, cloud)
    halo = smoothstep(threshold - 0.10, threshold - 0.025, flake_field) * (1 - flakes)
    variation = 1 + weathering * ((0.49 - cloud) * 0.42 + (grain - 0.49) * 0.085)
    color = np.array(base) * variation[..., None]
    color *= (1 - (grime * 0.25 * weathering + halo * 0.075 * weathering + grit * 0.035))[..., None]
    exposed = np.array(exposed) * (0.75 + grain * 0.48)[..., None]
    color = color * (1 - wear[..., None]) + exposed * wear[..., None]
    rough = roughness + (cloud - 0.5) * 0.12 + (grain - 0.5) * 0.07 - wear * 0.20
    height = 0.52 + (grain - 0.5) * 0.075 + (cloud - 0.5) * 0.02 - wear * 0.085 - grit * 0.055
    if key in {"frame", "steel", "steel_edge"}:
        brush = noise(190)
        brush = sum(np.roll(brush, offset, axis=1) for offset in range(19)) / 19
        brush -= 0.5
        color *= (1 + brush * 0.34)[..., None]
        rough += brush * 0.18
        height += brush * 0.15
    save(key, color, rough, height, metallic + (0.86 - metallic) * wear)


def soft_surface(key, base, roughness, fiber_type):
    cloud, grain = noise(11), noise(210)
    y, x = np.mgrid[0:SIZE, 0:SIZE] / SIZE * 2 * np.pi
    if fiber_type == "webbing":
        warp = np.cos(128 * x + 0.25 * np.sin(24 * y))
        weft = np.cos(72 * y + 0.70 * np.sin(64 * x))
        yarn = warp * 0.25 + weft * 0.20 + warp * weft * 0.10
    elif fiber_type == "cloth":
        warp = np.cos(128 * (x - 0.25 * y))
        weft = np.cos(152 * y + 38 * x)
        yarn = warp * 0.15 + weft * 0.13 + warp * weft * 0.12
    elif fiber_type == "loops":
        yarn = (noise(112) - 0.50) * 1.15
    else:
        yarn = (noise(96) - 0.50) * 0.40
    dust = smoothstep(0.45, 0.94, cloud)
    variation = 1 + yarn * 0.22 + (grain - 0.5) * 0.23 + dust * 0.13
    color = np.array(base) * variation[..., None] + dust[..., None] * (0.0020, 0.0018, 0.0010)
    rough = roughness + yarn * 0.13 + (grain - 0.5) * 0.18
    height = 0.5 + yarn * 0.48 + (grain - 0.5) * 0.24
    save(key, color, rough, height)


def band_surface():
    y, x = (np.mgrid[0:SIZE, 0:SIZE] + 0.5) / SIZE
    warp = np.cos(x * np.pi * 2 * 86)
    weft = np.cos(y * np.pi * 2 * 21 + warp * 0.51)
    weave = warp * 0.22 + weft * 0.20 + warp * weft * 0.12
    grain = noise(170) - 0.5
    border_dist = np.minimum(y, 1 - y)
    border = 1 - smoothstep(0.027, 0.053, border_dist)
    shoulder = 1 - smoothstep(0.006, 0.017, np.abs(border_dist - 0.045))
    stitch_col = np.abs((x * 83 + 0.07 * np.sin(y * np.pi * 2)) % 1 - 0.5)
    stitch_row = np.abs(border_dist - 0.115) + stitch_col * 0.023
    stitch = (1 - smoothstep(0.017, 0.031, stitch_row)) * (1 - smoothstep(0.25, 0.35, stitch_col))
    color = np.array((0.015, 0.016, 0.015)) * (1 + weave * 0.77 + grain * 0.23 - border * 0.38)[..., None]
    color += (stitch * 0.026 + shoulder * 0.008)[..., None] * (0.93, 0.94, 0.87)
    rough = 0.84 + weave * 0.21 + grain * 0.05 - stitch * 0.14
    height = 0.44 + weave * 0.55 + grain * 0.12 + shoulder * 0.10 + stitch * 0.13
    save("band", color, rough, height)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paint_wear("plate", (0.059, 0.051, 0.039), 0.76, 0.02, 0.84, 0.37, 0.60, (0.145, 0.132, 0.108))
    paint_wear("edge", (0.074, 0.064, 0.050), 0.70, 0.10, 0.68, 0.74, 0.61, (0.175, 0.159, 0.135))
    paint_wear("frame", (0.051, 0.052, 0.050), 0.60, 0.38, 0.77, 0.24, 0.76, (0.116, 0.117, 0.112))
    paint_wear("steel", (0.096, 0.096, 0.091), 0.57, 0.57, 0.72, 0.32, 0.72, (0.179, 0.178, 0.169))
    paint_wear("helmet", (0.035, 0.035, 0.033), 0.71, 0.06, 0.87, 0.20, 0.52, (0.092, 0.088, 0.079))
    paint_wear("steel_edge", (0.122, 0.120, 0.112), 0.47, 0.69, 0.73, 0.46, 0.36, (0.190, 0.185, 0.176))
    band_surface()
    soft_surface("strap", (0.024, 0.023, 0.021), 0.82, "webbing")
    soft_surface("fabric", (0.022, 0.023, 0.022), 0.86, "cloth")
    soft_surface("velcro", (0.029, 0.026, 0.021), 0.88, "loops")
    soft_surface("rubber", (0.014, 0.014, 0.013), 0.75, "grain")
    soft_surface("black", (0.023, 0.024, 0.023), 0.63, "grain")
    soft_surface("yellow", (0.278, 0.150, 0.026), 0.65, "grain")


if __name__ == "__main__":
    main()




