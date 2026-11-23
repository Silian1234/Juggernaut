"""Physically scaled diffuse, relief, and response for the frozen V5d surfaces."""

from functools import lru_cache
from pathlib import Path

import numpy as np

TEXTURES = Path(__file__).resolve().parents[1] / "textures"
TAU = 2 * np.pi
LATTICE = np.random.default_rng(210934).random((64, 64, 64), dtype=np.float32)


def smooth(lo, hi, value):
    t = np.clip((value - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


def mix(a, b, amount):
    return a + (b - a) * amount


def rgb(r, g, b):
    return np.array((r, g, b), dtype=np.float32) / 255


def noise(p, frequency, offset=0):
    """Continuous value field; p is in metres; topology and UV splits do not affect it."""
    q = p * frequency + offset
    cell = np.floor(q).astype(np.int32)
    f = q - cell.astype(np.float32)
    f *= f * (3 - 2 * f)
    x, y, z = (cell & 63).T
    xx, yy, zz = ((cell + 1) & 63).T
    u, v, w = f.T
    xy0 = mix(mix(LATTICE[x, y, z], LATTICE[xx, y, z], u),
              mix(LATTICE[x, yy, z], LATTICE[xx, yy, z], u), v)
    xy1 = mix(mix(LATTICE[x, y, zz], LATTICE[xx, y, zz], u),
              mix(LATTICE[x, yy, zz], LATTICE[xx, yy, zz], u), v)
    return mix(xy0, xy1, w)


def plane(p, n):
    """Choose the best planar projection for narrow anisotropic marks."""
    axis = np.abs(n).argmax(axis=1)
    u = np.where(axis == 0, p[:, 1], p[:, 0])
    v = np.where(axis == 2, p[:, 1], p[:, 2])
    return u, v


def scratches(p, n, grain, fine=False):
    """Sparse tapered strokes with varying angle, offset, length and depth."""
    u, v = plane(p, n)
    scale = 137 if fine else 31
    a, b = (0.64, 0.77) if fine else (0.87, 0.49)
    x = (u * a + v * b) * scale
    y = (v * a - u * b) * scale
    ix, iy = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    seed = LATTICE[ix & 63, iy & 63, 37 if fine else 11]
    ends = LATTICE[iy & 63, ix & 63, 27 if fine else 41]
    length = (0.28 + 0.17 * seed) if fine else (0.19 + 0.30 * seed)
    along = x - ix - 0.5
    across = y - iy - (0.16 + ends * 0.68) - along * (ends - 0.5) * 0.38
    taper = 1 - smooth(length * 0.64, length, np.abs(along))
    width = (0.027 if fine else 0.014) * (1.15 + 0.60 * (grain - 0.5))
    mark = 1 - smooth(width * 0.12, width, np.abs(across))
    activity = smooth(0.55 if fine else 0.75, 0.96, seed)
    return (taper * mark * activity).astype(np.float32)


PAINT = {
    "khaki paint": ((76, 71, 62), (40, 40, 38), .22, .30, 0, .0045, False),
    "khaki chamfers": ((84, 77, 67), (41, 41, 38), .23, .32, 0, .0033, True),
    "khaki applique": ((80, 75, 64), (42, 42, 40), .22, .33, 0, .0032, False),
    "chamfered khaki edges": ((88, 83, 72), (43, 43, 40), .23, .34, 0, .0027, True),
    "powerpack plate": ((78, 75, 63), (57, 59, 58), .24, .29, .06, .0035, False),
    "powerpack edge": ((83, 79, 67), (66, 68, 66), .25, .32, .09, .0035, True),
    "knee cop crown": ((59, 60, 57), (36, 37, 37), .25, .34, 0, .0035, False),
    "knee cop bevels": ((69, 68, 63), (39, 40, 39), .26, .38, 0, .0035, True),
    "black mandible composite": ((44, 45, 44), (73, 71, 64), .25, .31, 0, .0022, False),
    "black ear armor": ((57, 57, 54), (83, 80, 73), .25, .33, 0, .0026, False),
    "dark graphite frame": ((55, 57, 55), (112, 111, 105), .24, .31, .21, .0031, False),
    "charcoal arc hardware": ((47, 49, 48), (93, 92, 87), .24, .35, .22, .0022, False),
    "steel hardware": ((83, 86, 82), (132, 133, 128), .29, .37, .61, .0025, False),
    "machined steel chamfers": ((111, 113, 109), (161, 161, 154), .32, .47, .73, .0025, True),
    "blackened steel fasteners": ((66, 68, 66), (126, 126, 120), .29, .47, .62, .0019, False),
}

FABRIC = {
    "combat shirt": ((37, 39, 39), "twill"),
    "combat trousers": ((42, 44, 43), "twill"),
    "black balaclava": ((27, 28, 28), "twill"),
    "thigh sheath": ((49, 50, 46), "cordura"),
    "tactical gloves": ((48, 48, 46), "cordura"),
    "black woven cloth": ((38, 39, 38), "cordura"),
    "carrier black cordura": ((43, 45, 42), "cordura"),
    "carrier charcoal plate bag": ((49, 51, 47), "cordura"),
    "carrier smoke brown pouch canvas": ((65, 59, 48), "cordura"),
    "carrier dull olive pouches": ((64, 63, 48), "cordura"),
    "carrier smoke belt pouches": ((58, 54, 45), "cordura"),
    "carrier black loop field": ((46, 47, 43), "loop"),
    "black hook and loop": ((46, 47, 41), "loop"),
    "carrier binding tape": ((59, 60, 52), "webbing"),
    "carrier dark nylon webbing": ((51, 53, 45), "webbing"),
    "black nylon webbing": ((47, 49, 43), "webbing"),
    "black retention webbing": ((46, 48, 43), "retention"),
    "carrier gray bartacks": ((85, 81, 70), "thread"),
    "sleeve cuffs": ((38, 40, 39), "webbing"),
    "glove hems and knuckle welts": ((53, 53, 49), "webbing"),
    "trouser inseams": ((49, 50, 47), "thread"),
    "boot laces and heel counters": ((52, 53, 49), "thread"),
}


def fields(p, n):
    cloud = noise(p, 13, 11) * .65 + noise(p, 39, 17) * .35
    detail = noise(p, 124, 9)
    grain = noise(p, 930, 29)
    # Patchy mineral dust rises through the lower greave instead of making a
    # single horizontal color cutoff. The underside keeps the darker stains.
    low = 1 - smooth(.09, .68, p[:, 2])
    dust = low * smooth(.29, .73, cloud) * (.72 + .28 * n[:, 2])
    return cloud, detail, grain, dust


def painted(key, obj, p, n, d, cloud, detail, grain, dust):
    base, exposed, spec, gloss, metallic, span, bevel = PAINT[key]
    is_metal = key in {"dark graphite frame", "charcoal arc hardware", "steel hardware",
                       "machined steel chamfers", "blackened steel fasteners"}
    # Moulded quick-release parts share the donor's frame slot.
    if key in {"dark graphite frame", "steel hardware"} and "v5_carrier" in obj:
        return molded("graphite polymer", p, d, cloud, grain, dust)
    shell = any(word in obj for word in ("hamstring shell", "adductor shell", "popliteal"))
    if shell and key in {"khaki paint", "khaki chamfers", "powerpack plate", "powerpack edge"}:
        base = (58, 60, 55) if not bevel else (66, 67, 61)
        exposed = (35, 37, 35)
    soot = smooth(.45, .81, cloud * .75 + detail * .25)
    dry = smooth(.49, .81, detail * .45 + cloud * .55)
    color = rgb(*base) * (1 + .31 * (cloud - .5) + .09 * (detail - .5) +
                          .060 * (grain - .5) - .18 * soot)[:, None]
    color += rgb(10, 8, 5) * dry[:, None]

    # Paint breaks irregularly around physical bevels. The finer sub-layer
    # is kept inside its paler abrasion halo instead of coating every edge.
    flank = noise(p, 238, 4)
    nano = noise(p, 470, 45)
    breakup = .36 * detail + .39 * flank + .25 * nano
    edge = 1 - smooth(span * .08, span, d)
    edge_wear = smooth(.65, .81, breakup + edge * (.25 if is_metal else .218))
    if bevel:
        edge_wear = np.maximum(edge_wear, smooth(.64, .81, breakup + .030))
    scattered = smooth(.80, .93, breakup) * smooth(.60, .84, cloud) * (.08 if is_metal else .30)
    large = scratches(p, n, grain)
    small = scratches(p, n, grain, fine=True)
    abrasion = np.maximum(large * (.37 + edge * .24), small * (.13 + edge * .19))
    chip = np.maximum(edge_wear, scattered)
    raw = np.maximum(chip, abrasion)
    halo = smooth(.53, .69, breakup + edge * .18) * (1 - chip) * edge
    rim = rgb(16, 13, 9) if not is_metal else rgb(15, 15, 14)
    color += rim * halo[:, None]
    worn = rgb(*exposed) * (.84 + grain * .26 + nano * .12)[:, None]
    color = mix(color, worn, raw[:, None])

    mud = dust * smooth(.30, .77, detail) * (1 - raw * .28)
    if not is_metal:
        color = mix(color, rgb(57, 47, 35), mud[:, None] * .44)
        color += rgb(14, 11, 6) * (dust * (1 - mud * .9) * .48)[:, None]
    else:
        color = mix(color, rgb(71, 60, 46), mud[:, None] * .38)
    height = ((grain - .5) * .000065 + (detail - .5) * .000082 +
              halo * .000045 - chip * .00019 - abrasion * .00013)
    shine = gloss + .06 * grain - .08 * soot - .13 * mud + raw * (.17 if is_metal else -.03)
    reflection = spec + raw * (.14 if is_metal else -.035) - mud * .07
    metal = metallic + (.94 - metallic) * raw if is_metal else np.full(len(p), metallic, np.float32)

    pivot = any(tag in obj for tag in ("pivot", "drive", "actuator", "hinge", "fastener", "collar"))
    if is_metal:
        u, v = plane(p, n)
        brush = np.sin(TAU * (u * 1170 + v * 21 + grain * .21))
        brush *= .15 + edge * .34 + raw * .48
        height += brush * .000009
        color += rgb(4, 4, 4) * brush[:, None]
        oil = smooth(.46, .75, cloud * .6 + detail * .4) * (.54 if pivot else .19)
        color = mix(color, rgb(31, 29, 23), oil[:, None])
        shine += oil * .22
    return color, height, reflection, shine, metal


@lru_cache(maxsize=None)
def bitmap(relative):
    from PIL import Image

    return np.asarray(Image.open(TEXTURES / relative), dtype=np.float32) / 255


def sample(image, uv):
    """Bilinear lookup from bottom-left UV, clamping the outermost texels."""
    h, w = image.shape[:2]
    x = np.clip(uv[:, 0] * w - .5, 0, w - 1)
    y = np.clip((1 - uv[:, 1]) * h - .5, 0, h - 1)
    i, j = x.astype(np.int32), y.astype(np.int32)
    ri, rj = np.minimum(i + 1, w - 1), np.minimum(j + 1, h - 1)
    fu, fv = (x - i).astype(np.float32), (y - j).astype(np.float32)
    if image.ndim == 3:
        fu, fv = fu[:, None], fv[:, None]
    return mix(mix(image[j, i], image[j, ri], fu), mix(image[rj, i], image[rj, ri], fu), fv)


def filaments(p, n, kind, detail):
    weights = n * n
    weights *= weights
    weights /= np.maximum(weights.sum(axis=1), 1e-6)[:, None]
    result = np.zeros(len(p), np.float32)
    phase = detail * 1.1
    for axis, (u, v) in enumerate(((1, 2), (0, 2), (0, 1))):
        x, y = p[:, u], p[:, v]
        if kind == "twill":
            a = np.cos(TAU * (680 * x - 135 * y) + phase)
            b = np.cos(TAU * (730 * y + 160 * x) + a * .75)
        elif kind in {"webbing", "retention", "thread"}:
            a = np.cos(TAU * (790 * x + 22 * y) + phase)
            b = np.cos(TAU * (455 * y) + a * .72)
        else:
            a = np.cos(TAU * (730 * x + 21 * y) + phase)
            b = np.cos(TAU * (755 * y - 11 * x) + a * .87)
        result += weights[:, axis] * (a * .34 + b * .30 + a * b * .20)
    return result


def woven(key, obj, p, n, d, cloud, detail, grain, dust, source_uv):
    base, kind = FABRIC[key]
    if key == "carrier black cordura" and "looppatch" in obj:
        kind = "loop"
    u, v = plane(p, n)
    grain -= .5
    if kind == "loop":
        loops = noise(p, 656, 24) - .5
        flock = noise(p, 1390, 38) - .5
        yarn = (loops * .80 + flock * .45)
        relief = yarn * .00011
    else:
        yarn = filaments(p, n, kind, detail)
        relief = yarn * (.000035 if kind == "cordura" else .000047)
    color = rgb(*base) * (1 + .18 * (cloud - .5) + .085 * yarn + .09 * grain)[:, None]
    height = relief + grain * .000029
    donor = {"combat shirt": "usec_body", "combat trousers": "pants_usec_commando"}.get(key)
    if donor and source_uv is not None:
        valid = (source_uv >= 0).all(axis=1)
        dyed = sample(bitmap(f"cloth/{donor}_charcoal.png"), source_uv[valid])
        relief_source = sample(bitmap(f"cloth/{donor}_weave.png"), source_uv[valid]) - .5
        color[valid] = mix(color[valid], dyed * 1.12, .66)
        height[valid] = height[valid] * .60 + relief_source * .00016

    if kind == "retention" and source_uv is not None:
        band = (source_uv >= 0).all(axis=1) & (source_uv[:, 1] <= 1)
        band_uv = source_uv[band].copy()
        band_uv[:, 0] %= 1
        binding = sample(bitmap("finish/band_color.png"), band_uv)
        details = sample(bitmap("finish/band_height.png"), band_uv) - .5
        color[band] = mix(color[band], binding * .70, .70)
        height[band] = height[band] * .50 + details * .00034
    if key == "carrier black loop field" and source_uv is not None:
        valid = (source_uv >= 0).all(axis=1)
        pocket = sample(bitmap("carrier-loop.png"), source_uv[valid])
        stitches = smooth(.12, .29, pocket[:, 0])
        color[valid] = mix(color[valid], pocket * 1.38, .53)
        height[valid] += stitches * .00014
    if kind in {"webbing", "retention"}:
        border = 1 - smooth(.00042, .00135, np.abs(d - .0012))
        stitch_row = 1 - smooth(.00036, .00083, np.abs(d - .0032))
        stitch_break = smooth(.23, .34, np.abs((u * 182 + v * 103) % 1.0 - .5))
        thread = stitch_row * (1 - stitch_break)
        color *= (1 - .13 * border)[:, None]
        color += rgb(26, 24, 19) * thread[:, None]
        height += border * .00012 + thread * .00019
    fuzz = smooth(.54, .82, detail) * (.34 + dust)
    color += rgb(12, 10, 7) * fuzz[:, None]
    color = mix(color, rgb(72, 62, 47), (dust * .25 * smooth(.22, .82, detail))[:, None])
    return color, height, .19 + .046 * yarn, .14 + .075 * yarn - dust * .05, np.zeros(len(p), np.float32)


def molded(key, p, d, cloud, grain, dust):
    tones = {
        "graphite laminate": ((47, 48, 48), .20, .27, .000079),
        "hardware recesses": ((24, 25, 25), .18, .28, .000035),
        "powerpack black": ((42, 43, 41), .24, .39, .000065),
        "graphite polymer": ((45, 47, 46), .22, .35, .000080),
        "combat boots": ((41, 42, 41), .24, .31, .00011),
        "black molded rubber": ((33, 35, 34), .19, .24, .000073),
        "molded black rubber": ((32, 34, 34), .20, .28, .000067),
    }
    base, reflection, gloss, texture = tones.get(key, tones["graphite polymer"])
    pebbled = noise(p, 530, 37)
    smooth_wear = (1 - smooth(.0003, .0034, d)) * smooth(.37, .76, cloud)
    color = rgb(*base) * (.96 + pebbled * .11 + (grain - .5) * .11)[:, None]
    color += rgb(20, 18, 14) * (smooth_wear + dust * .88)[:, None]
    height = (pebbled - .5) * texture + (grain - .5) * texture * .24
    return color, height, reflection + smooth_wear * .07, gloss + smooth_wear * .15 - dust * .07, np.zeros(len(p), np.float32)


def lens(key, p, n, d, cloud, grain):
    coated = key == "coated germanium"
    base = rgb(39, 52, 46) if coated else rgb(22, 24, 26)
    edge = 1 - smooth(.0007, .0046, d)
    dust = edge * smooth(.61, .85, grain) * .40
    rub = scratches(p, n, grain, fine=True) * .27
    color = base * (1 + (cloud - .5) * .10)[:, None]
    color += rgb(26, 20, 14) * (dust + rub * .37)[:, None]
    reflection = .44 if coated else .34
    gloss = .82 if coated else .775
    return color, rub * -.000016, reflection - dust * .08, gloss - dust * .075 - rub * .12, np.full(len(p), .14 if coated else .02, np.float32)


def service(obj, p, n, cloud, detail, grain, dust):
    is_mark = "powerpack cartridge" in obj or "hip belt ring" in obj
    if is_mark:
        color = rgb(167, 117, 44) * (1 - smooth(.61, .88, detail) * .34)[:, None]
        height = (grain - .5) * .000018
        return color, height, np.full(len(p), .24), np.full(len(p), .32), np.zeros(len(p))
    u, v = plane(p, n)
    left = np.cos(TAU * (515 * u + 407 * v))
    right = np.cos(TAU * (515 * u - 407 * v) + left * .43)
    braid = (left + right + left * right * .38) * .37
    dirt = smooth(.41, .81, cloud * .7 + detail * .3) * (.66 + dust * .34)
    color = rgb(167, 115, 45) * (1 + braid * .12 + (grain - .5) * .11)[:, None]
    color = mix(color, rgb(77, 58, 31), (dirt * .51)[:, None])
    return color, braid * .000077, .25 + .04 * braid, .36 + .06 * braid - dirt * .14, np.zeros(len(p))


def cartridge_ink(p, n, color, height, response, gloss, grain):
    # The cartridge drawing aligns to the flat face, behind the raised vent
    # assembly. Its hinged catches and the warning outline already have geometry.
    x, y, z = p.T
    region = (n[:, 1] > .84) & (np.abs(x) < .053) & (y > .275) & (y < .280) & (z > 1.346) & (z < 1.408)
    if region.any():
        uv = np.column_stack((.5 - x[region] / .106, (z[region] - 1.346) / .062))
        ink = sample(bitmap("pack/cartridge-markings.png"), uv)
        stamp = sample(bitmap("pack/cartridge-stamp.png"), uv) - .5
        alpha = ink[:, 3] * (1 - smooth(.70, .90, grain[region]) * .32)
        color[region] = mix(color[region], ink[:, :3], alpha[:, None])
        height[region] += stamp * .00031
    # The existing upper glass insert carries the charge bars, above the triangle.
    ux = np.abs(x)
    panel = (n[:, 1] > .85) & (y > .2915) & (y < .2925) & (ux < .0132) & (np.abs(z - 1.491) < .0078)
    if panel.any():
        alpha = smooth(.0049, .0066, np.abs(z[panel] - 1.491)) * .22
        color[panel] = mix(rgb(29, 32, 28), rgb(95, 93, 72), alpha[:, None])
        response[panel] = .40
        gloss[panel] = .61
        column = (.011 - x[panel]) / .0044
        inside = (column > 0) & (column < 5) & (column % 1.0 > .13) & (column % 1.0 < .82) & (np.abs(z[panel] - 1.491) < .0033)
        bars = np.where((column < 3)[:, None], rgb(140, 125, 66), rgb(57, 62, 48))
        color[panel] = np.where(inside[:, None], bars, color[panel])


def evaluate(material, obj, p, n, edge_distance, source_uv=None):
    """Return sRGB albedo, relief in metres, specular, gloss, and metalness."""
    key = material.lower().split(" | ")[-1]
    obj = obj.lower()
    d = edge_distance
    cloud, detail, grain, dust = fields(p, n)
    if key in PAINT:
        result = painted(key, obj, p, n, d, cloud, detail, grain, dust)
    elif key in FABRIC:
        result = woven(key, obj, p, n, d, cloud, detail, grain, dust, source_uv)
    elif key in {"smoked black visor", "opaque black visor", "coated germanium"}:
        result = lens(key, p, n, d, cloud, grain)
    elif key == "yellow cable jacket":
        result = service(obj, p, n, cloud, detail, grain, dust)
    else:
        result = molded(key, p, d, cloud, grain, dust)
    albedo, height, spec, gloss, metal = result
    if key == "powerpack black" and "powerpack cartridge" in obj:
        cartridge_ink(p, n, albedo, height, spec, gloss, grain)
    return (
        np.clip(albedo, 0, 1).astype(np.float32, copy=False),
        height.astype(np.float32, copy=False),
        np.clip(spec, 0, 1).astype(np.float32, copy=False),
        np.clip(gloss, 0, 1).astype(np.float32, copy=False),
        np.clip(metal, 0, 1).astype(np.float32, copy=False),
    )
