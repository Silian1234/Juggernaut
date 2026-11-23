# Re-materials the V5d armor atlas as painted armour steel (run inside Blender, numpy available):
#   paint chips (dull composite)  -> bare steel: dark diffuse, bright steel specular, high gloss
#   olive / dark paint            -> uneven gloss (noise), polished convex edges, dust and grime in cavities (AO)
# Usage: blender -b --python armor_steel_maps.py -- <src textures/v5d> <out stage dir>
import sys, os, shutil
import bpy
import numpy as np

src, out = sys.argv[sys.argv.index("--") + 1:][:2]
os.makedirs(out, exist_ok=True)
for name in os.listdir(src):                      # untouched atlases are copied as they are
    if name.endswith(".png") and not name.startswith("armor_"):
        shutil.copy2(os.path.join(src, name), os.path.join(out, name))


def load(name, srgb):
    im = bpy.data.images.load(os.path.join(src, name))
    im.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    w, h = im.size
    return np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4), (w, h)


def save(arr, size, name, srgb):
    im = bpy.data.images.new(name, size[0], size[1], alpha=True, float_buffer=False)
    im.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    im.pixels.foreach_set(np.clip(arr, 0, 1).astype(np.float32).ravel())
    im.filepath_raw = os.path.join(out, name)
    im.file_format = "PNG"
    im.save()


def blur(a, r):
    k = 2 * r + 1
    c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), mode="edge"), axis=0); a = (c[k:] - c[:-k]) / k
    c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), mode="edge"), axis=1); return (c[:, k:] - c[:, :-k]) / k


def noise(shape, cell, seed):
    rng = np.random.default_rng(seed)
    h, w = shape
    small = rng.random((h // cell + 2, w // cell + 2)).astype(np.float32)
    big = np.kron(small, np.ones((cell, cell), np.float32))[:h, :w]
    return blur(big, max(1, cell // 2))


alb, size = load("armor_albedo.png", True)       # sRGB values as stored in the file
sg, _ = load("armor_specgloss.png", False)
ao = load("armor_ao.png", False)[0][..., 0]
cur = load("armor_curvature.png", False)[0][..., 0]
shape = ao.shape

rgb = alb[..., :3]
spec, gloss = sg[..., 0], sg[..., 3]
mx, mn = rgb.max(-1), rgb.min(-1)
sat = (mx - mn) / np.maximum(mx, 1e-4)
used = mx > 0.01

paint_olive = used & (spec < 0.07) & (sat > 0.18)
paint_dark = used & (spec >= 0.07) & (spec < 0.10) & (sat < 0.12)
chips = used & (spec >= 0.10) & (spec < 0.30)          # dull composite showing through
metal = used & (spec >= 0.30)                         # existing steel hardware stays
paint = paint_olive | paint_dark
print("masks olive %.3f dark %.3f chips %.3f metal %.3f" % tuple(m.mean() for m in (paint_olive, paint_dark, chips, metal)))

n_big = noise(shape, 96, 1)          # broad gloss variation (handling, weather)
n_mid = noise(shape, 24, 2)          # smudges
n_fine = noise(shape, 4, 3)          # grain
edge = np.clip((cur - 0.80) / 0.18, 0, 1)            # convex edges
cavity = np.clip((0.45 - ao) / 0.35, 0, 1)           # occluded areas

new_rgb = rgb.copy()
new_spec = spec.copy()
new_gloss = gloss.copy()

# --- paint: slightly desaturated olive drab, worn shine on edges, dust in cavities
base = rgb[paint]
lum = base.mean(-1, keepdims=True)
base = (base * 0.95 + lum * 0.05) * 0.80                          # deeper olive drab
dust = np.array([0.46, 0.43, 0.37], np.float32)
grime = np.array([0.10, 0.095, 0.085], np.float32)
c = cavity[paint][:, None]; e = edge[paint][:, None]
base = base * (1 - 0.35 * c) + dust * (0.12 * c)                 # dust in recesses
base = base * (1 - 0.10 * (1 - ao[paint][:, None]))
base = base * (0.94 + 0.10 * n_mid[paint][:, None])               # tonal variation
steel_edge = np.array([0.20, 0.20, 0.21], np.float32)
base = base * (1 - 0.55 * e) + steel_edge * (0.55 * e)            # paint worn through to steel on edges
new_rgb[paint] = base
new_spec[paint] = 0.05 + 0.04 * n_big[paint] + 0.45 * edge[paint]             # matte paint, bare-steel sheen on worn edges
new_gloss[paint] = (0.14 + 0.16 * n_big[paint] + 0.08 * n_fine[paint]
                    + 0.40 * edge[paint] - 0.08 * cavity[paint])

# --- chips: bare steel (specular workflow: dark diffuse, bright specular)
steel = np.array([0.07, 0.07, 0.075], np.float32)
new_rgb[chips] = steel * (0.8 + 0.4 * n_fine[chips][:, None])
new_spec[chips] = 0.62 + 0.20 * n_fine[chips]
new_gloss[chips] = 0.55 + 0.20 * n_mid[chips]

new_alb = alb.copy(); new_alb[..., :3] = new_rgb
new_alb[..., 3] = np.clip(new_gloss, 0, 1)            # albedo alpha mirrors gloss, as in the original atlas
new_sg = sg.copy()
new_sg[..., 0] = new_sg[..., 1] = new_sg[..., 2] = np.clip(new_spec, 0, 1)
new_sg[..., 3] = np.clip(new_gloss, 0, 1)

save(new_alb, size, "armor_albedo.png", True)
save(new_sg, size, "armor_specgloss.png", False)
for name in ("armor_normal.png", "armor_normal_dxt5nm.png", "armor_ao.png", "armor_curvature.png"):
    shutil.copy2(os.path.join(src, name), os.path.join(out, name))
met = (chips | metal).astype(np.float32)
save(np.dstack([met, met, met, np.ones_like(met)]), size, "armor_metallic.png", False)
print("DONE", out)
