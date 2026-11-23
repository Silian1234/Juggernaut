"""Rest-space material response and relief for the second V5d bake."""

import numpy as np

from bake_surfaces import FABRIC, TAU, bitmap, cartridge_ink, mix, noise, plane, rgb, sample, smooth

COMPOSITE = {
    "khaki paint": (103, 98, 73),
    "khaki chamfers": (109, 104, 79),
    "khaki applique": (101, 96, 74),
    "chamfered khaki edges": (109, 105, 83),
    "knee cop crown": (55, 56, 48),
    "knee cop bevels": (62, 62, 53),
    "black ear armor": (62, 63, 58),
    "black mandible composite": (42, 43, 41),
}
PAINTED_STEEL = {
    "dark graphite frame": (49, 53, 58),
    "charcoal arc hardware": (39, 44, 48),
    "powerpack plate": (60, 62, 60),
    "powerpack edge": (65, 68, 67),
    "powerpack black": (45, 48, 49),
}
BARE_STEEL = {
    "machined steel chamfers": (83, 88, 94),
    "steel hardware": (68, 73, 79),
    "blackened steel fasteners": (60, 64, 70),
}
# Rest-space axes from lower_frame.py. Mirroring only changes the X coordinate.
LEG_HUBS = (
    (.299, -.0045194, .9622123, .055),
    (.321, -.0220907, .7364197, .028),
    (.334, .0558251, .0633801, .031),
)
ARM_HUBS = {
    "l elbow planetary actuator": (-.1499, 1.3565, .044),
    "r elbow planetary actuator": (-.1496, 1.3590, .044),
    "l shoulder drive pivot": (.1333, 1.4011, .041),
    "r shoulder drive pivot": (.1338, 1.4011, .041),
}


def ridge(distance, width):
    return 1 - smooth(width * .25, width, np.abs(distance))


def scatter_strokes(p, n, fine=False):
    """Score marks with physically narrow cross sections and tapered ends."""
    u, v = plane(p, n)
    scale = 46 if fine else 24
    cosine, sine = (.93, .37) if fine else (.48, -.88)
    x = (u * cosine + v * sine) * scale
    y = (v * cosine - u * sine) * scale
    cell = np.floor(np.column_stack((x, y))).astype(np.float32)
    seed = noise(np.column_stack((cell, np.ones(len(p), np.float32))), 1, 13 if fine else 4)
    span = .24 + .20 * seed
    along = x % 1 - .5
    across = y % 1 - (.27 + .43 * seed) + along * (.10 - .19 * seed)
    width = scale * (.00048 if fine else .00080)
    return ridge(across, width) * (1 - smooth(span * .46, span, np.abs(along))) * smooth(.79, .89, seed)


def steel_hubs(obj, p, n):
    """Turned rings on the actual axle locations and milled slots on leg screws."""
    x, y, z = p.T
    if obj.startswith("legframe_"):
        hubs = LEG_HUBS
    else:
        prefix = obj.removesuffix(".001")
        if prefix not in ARM_HUBS:
            return np.zeros(len(p), np.float32), np.zeros(len(p), np.float32)
        cy, cz, size = ARM_HUBS[prefix]
        hubs = ((0, cy, cz, size),)

    machining = np.zeros(len(p), np.float32)
    slots = np.zeros_like(machining)
    for cx, cy, cz, size in hubs:
        dy, dz = y - cy, z - cz
        radius = np.hypot(dy, dz)
        valid = 1 - smooth(size * .95, size * 1.02, radius)
        if cx:
            valid *= smooth(cx - .020, cx + .001, np.abs(x))
        axial = smooth(.49, .88, np.abs(n[:, 0]))
        periodic = np.cos(TAU * radius / .0021)
        tool = np.cos(TAU * radius / .00095)
        knurl = np.cos(np.arctan2(dz, dy) * 48 + np.abs(x) * 320)
        outer_band = smooth(size * .70, size * .83, radius)
        machining += (axial * (periodic * .000040 + tool * .000012) +
                      (1 - axial) * outer_band * np.maximum(knurl, 0) ** 2 * .00028) * valid
        if cx:
            center_slot = ridge(dz + dy * .44, .00105) * (1 - smooth(size * .062, size * .093, np.abs(dy)))
            cap_face = smooth(cx + .025, cx + .028, np.abs(x))
            slots = np.maximum(slots, center_slot * axial * cap_face)
    return machining, slots


def pack_recesses(p, n):
    """Recessed cover junction and captive screw detail on the upper cover face."""
    x, y, z = p.T
    face = smooth(.72, .95, n[:, 1]) * smooth(.281, .293, y)
    cover = ridge(z - 1.510, .00145) * (1 - smooth(.058, .064, np.abs(x)))
    cover *= smooth(.021, .028, np.abs(x))
    dx = np.abs(x) - .0615
    dz = z - 1.487
    radius = np.hypot(dx, dz)
    recess = (1 - smooth(.0025, .0045, radius)) * face
    head = (1 - smooth(.0015, .0026, radius)) * face
    slot = ridge(dz - .32 * dx, .0009) * head
    return cover * face, recess, head, slot


def armor_recesses(p, n):
    """Molded insert joint and two recessed anchors on the front of each greave."""
    x, y, z = p.T
    front = smooth(.58, .95, -n[:, 1]) * (1 - smooth(-.068, -.048, y))
    center = .180 + .11 * (z - .36)
    offset = np.abs(np.abs(x) - center)
    seam = ridge(z - (.371 - .23 * offset), .0015) * (1 - smooth(.024, .034, offset))
    dx = offset - .019
    dz = z - .356
    radius = np.hypot(dx, dz)
    recess = (1 - smooth(.0028, .0047, radius)) * front
    head = (1 - smooth(.0019, .0028, radius)) * front
    slot = ridge(dz + .46 * dx, .00095) * head
    return seam * front, recess, head, slot


def hard_surface(key, obj, p, n, distance, ao, convex, concave, contact,
                 low, broad, breakup, micro):
    composite = key in COMPOSITE
    unpainted = key in BARE_STEEL
    tone = (COMPOSITE if composite else BARE_STEEL if unpainted else PAINTED_STEEL)[key]
    if composite and any(part in obj for part in ("hamstring shell", "adductor shell", "popliteal", "hinged medial lame")):
        tone = (54, 56, 49) if "chamfer" not in key else (63, 65, 55)
    if not composite and ("v5_carrier" in obj or "quickrelease" in obj):
        return molded("graphite polymer", ao, concave, low, broad, breakup, micro)

    # Only convex ridges and their immediate shoulders carry paint loss. A
    # second, very thin shoulder survives as visibly burnished paint.
    edge = np.maximum(convex, (.76 if composite else .83) * (1 - smooth(.0004, .0041, distance)))
    edge = np.clip(edge, 0, 1)
    flake = noise(p, 315, 52)
    shape = .58 * breakup + .42 * flake
    erosion = shape + edge * (.33 + .14 * contact)
    chip = smooth(.87, .975, erosion) * smooth(.24, .78, edge)
    lip = smooth(.72, .86, erosion) * (1 - chip) * edge * .80
    impact = scatter_strokes(p, n) * (.26 + contact * .74)
    fine = scatter_strokes(p, n, fine=True)
    cut = np.maximum(impact * (.45 + .51 * edge), fine * (.19 + .29 * contact))
    exposure = np.maximum(chip, cut)
    dent = smooth(.83, .96, breakup) * (1 - smooth(.15, .65, edge)) * contact

    shadow = 1 - ao
    well = smooth(.07, .42, np.maximum(shadow * .85, concave))
    # Vertical residue starts at sheltered openings and contact surfaces.
    streak_noise = noise(p * (1.0, 1.0, .12), 91, 23)
    streak = smooth(.58, .82, streak_noise) * np.maximum(well, contact * .34)
    grime = np.clip(well * (.43 + breakup * .31) + streak * .17 + low * (.30 + broad * .24), 0, .88)
    oil = well * smooth(.27, .66, breakup) * (.62 if not composite else .08)

    color = rgb(*tone) * (1 + .047 * (broad - .5) + .083 * (micro - .5))[:, None]
    height = (micro - .5) * (.000065 if composite else .00010) - dent * .00034
    height += lip * .000045 - chip * .00027 - impact * .00017 - fine * .000091
    height -= well * .00013
    if composite:
        # The fibrous substrate is dark and has a weak, untinted dielectric response.
        color += rgb(20, 18, 11) * lip[:, None]
        composite_grain = np.maximum(0, np.cos(TAU * (p[:, 0] * 350 + p[:, 2] * 98)))
        core = rgb(37, 39, 37) * (.88 + .25 * micro + .075 * composite_grain)[:, None]
        color = mix(color, core, exposure[:, None])
        height += (composite_grain - .5) * exposure * .000080
        spec = mix(.047, .105, exposure) - grime * .012
        gloss = mix(.249, .35, exposure) - .12 * grime
        metallic = np.zeros_like(height)
        if obj.startswith("legarmour_") and key == "khaki paint":
            seam, recess, head, slot = armor_recesses(p, n)
            hardware = head * (1 - slot)
            height += head * .00029 - seam * .00043 - recess * .00039 - slot * .00029
            color = mix(color, rgb(47, 48, 43), np.maximum(seam, recess)[:, None] * .57)
            color = mix(color, rgb(62, 64, 61), hardware[:, None])
            spec = mix(spec, .095, hardware)
            gloss = mix(gloss, .35, hardware)
    else:
        u, v = plane(p, n)
        milling = np.cos(TAU * (u * 680 + v * 17 + micro * .30))
        turning, socket = steel_hubs(obj, p, n)
        height += milling * (.000014 + .000029 * exposure) + turning - socket * .00053
        if "powerpack cartridge" in obj:
            seam, recess, head, slot = pack_recesses(p, n)
            height += head * .00021 - seam * .00055 - recess * .00031 - slot * .00026
            grime = np.maximum(grime, np.maximum(seam, recess) * .66)
            exposure = np.maximum(exposure, head * (1 - slot))
        if unpainted:
            color += rgb(7, 7, 8) * milling[:, None]
            color *= (1 + .16 * lip - .29 * socket)[:, None]
            spec = .66 + .15 * edge + .057 * milling - .35 * socket
            gloss = .66 + .085 * edge + .040 * milling - .21 * socket
            metallic = .88 - .39 * socket
        else:
            color += rgb(8, 10, 12) * lip[:, None]
            steel = rgb(90, 96, 103) * (.83 + .27 * micro + .15 * milling)[:, None]
            color = mix(color, steel, exposure[:, None])
            spec = mix(.190 + .023 * micro, .83, exposure)
            gloss = mix(.41 + .031 * micro, .70, exposure)
            metallic = exposure * .94
        spec -= grime * .085 + oil * .038
        gloss += oil * .16 - grime * .14
        metallic *= 1 - .70 * grime
        spec = spec[:, None] * np.array((.89, .95, 1), dtype=np.float32)
    soil = rgb(63, 55, 41) if composite else rgb(54, 46, 32)
    color = mix(color, soil, (low * .28 + grime * .13)[:, None])
    color *= (1 - .19 * well - oil * .28)[:, None]
    return color, height, spec, gloss, metallic


def yarn_projection(u, v, kind):
    """Alternating over-under threads with rounded yarn crowns."""
    if kind in {"webbing", "retention", "thread"}:
        x, y = 500 * u + 10 * v, 308 * v
    elif kind == "twill":
        x, y = 410 * u - 65 * v, 410 * v + 24 * u
    else:
        x, y = 414 * u + 11 * v, 428 * v - 9 * u
    a = np.maximum(0, np.cos(TAU * (x - .5))) ** 1.6
    b = np.maximum(0, np.cos(TAU * (y - .5))) ** 1.6
    phase = TAU * x / 2 + TAU * y / (3 if kind == "twill" else 2)
    over = .5 + .5 * np.cos(phase)
    return a * (.38 + .62 * over) + b * (1 - .62 * over)


def woven(key, obj, p, n, distance, ao, concave, low, breakup, micro, source_uv):
    tone, kind = FABRIC[key]
    if "looppatch" in obj and key == "carrier black cordura":
        kind = "loop"
    if kind == "loop":
        yarn = .57 * noise(p, 425, 24) + .43 * micro
    else:
        weights = n ** 6
        weights /= np.maximum(weights.sum(axis=1), 1e-6)[:, None]
        yarn = sum(weights[:, axis] * yarn_projection(p[:, u], p[:, v], kind)
                   for axis, (u, v) in enumerate(((1, 2), (0, 2), (0, 1))))
    height = (yarn - .35) * (.00031 if kind in {"webbing", "thread", "retention"} else .00026)
    height += (micro - .5) * .000065
    color = rgb(*tone) * (.85 + .40 * yarn + .075 * (micro - .5))[:, None]
    if source_uv is not None:
        valid = (source_uv >= 0).all(axis=1)
        donor = {"combat shirt": "usec_body", "combat trousers": "pants_usec_commando"}.get(key)
        if donor and valid.any():
            uv = source_uv[valid]
            dyed = sample(bitmap(f"cloth/{donor}_charcoal.png"), uv)
            relief = sample(bitmap(f"cloth/{donor}_weave.png"), uv) - .5
            color[valid] = mix(color[valid], dyed * (.85 + .30 * yarn[valid, None]), .39)
            height[valid] += relief * .00019
        if key == "carrier black loop field" and valid.any():
            pocket = sample(bitmap("carrier-loop.png"), source_uv[valid])
            color[valid] = mix(color[valid], pocket * 1.22, .49)
            height[valid] += smooth(.12, .29, pocket[:, 0]) * .00024
        if kind == "retention":
            valid &= source_uv[:, 1] <= 1
            if valid.any():
                uv = source_uv[valid].copy()
                uv[:, 0] %= 1
                color[valid] = mix(color[valid], sample(bitmap("finish/band_color.png"), uv) * .74, .52)
                height[valid] += (sample(bitmap("finish/band_height.png"), uv) - .5) * .00029

    if kind in {"webbing", "retention"}:
        u, v = plane(p, n)
        seam = ridge(distance - .0012, .00082)
        ticks = ridge((u * 184 + v * 18) % 1 - .5, .37)
        stitch = ridge(distance - .0027, .00090) * ticks
        color += rgb(25, 23, 18) * stitch[:, None] - rgb(7, 7, 6) * seam[:, None]
        height += stitch * .00031 - seam * .00014
    dirt = low * (.18 + breakup * .11) + concave * .11
    color = mix(color, rgb(66, 56, 40), dirt[:, None])
    color *= (.93 + .07 * ao)[:, None]
    spec = .024 + .016 * yarn
    gloss = .018 + .030 * yarn
    return color, height, spec, gloss, np.zeros_like(height)


def molded(key, ao, concave, low, broad, breakup, micro):
    tone, spec, gloss = {
        "graphite laminate": ((47, 49, 48), .094, .33),
        "hardware recesses": ((25, 26, 25), .045, .22),
        "combat boots": ((40, 41, 39), .070, .28),
        "black molded rubber": ((31, 34, 33), .059, .26),
        "molded black rubber": ((29, 31, 31), .060, .25),
    }.get(key, ((43, 46, 45), .065, .30))
    dust = low * (.24 + .20 * broad)
    color = rgb(*tone) * (.96 + .13 * micro)[:, None]
    color = mix(color, rgb(71, 60, 46), dust[:, None])
    color *= (1 - .20 * concave - .09 * (1 - ao))[:, None]
    height = (breakup - .5) * .00015 + (micro - .5) * .00008 - .00010 * concave
    return color, height, spec + .02 * breakup, gloss - .15 * dust, np.zeros_like(height)


def jacket(obj, p, n, distance, ao, low, breakup):
    mark = "powerpack cartridge" in obj or "hip belt ring" in obj
    weights = n ** 6
    weights /= np.maximum(weights.sum(axis=1), 1e-6)[:, None]
    braid = np.zeros_like(ao)
    if not mark:
        for axis, (u, v) in enumerate(((1, 2), (0, 2), (0, 1))):
            a = np.cos(TAU * (338 * p[:, u] + 295 * p[:, v]))
            b = np.cos(TAU * (338 * p[:, u] - 295 * p[:, v]))
            braid += weights[:, axis] * ((a + b) * .38 + a * b * .15)
    shoulder = (1 - smooth(.001, .010, distance)) * .22
    dirt = shoulder + (1 - ao) * .40 + low * .14
    color = rgb(160, 115, 38) * (.97 + braid * .16 + (breakup - .5) * .075)[:, None]
    color = mix(color, rgb(71, 55, 27), dirt[:, None])
    height = braid * .00021
    return color, height, .066 + braid * .014, .32 - dirt * .097, np.zeros_like(height)


def visor(key, p, n, distance, micro):
    coated = key == "coated germanium"
    color = rgb(40, 51, 46) if coated else rgb(23, 27, 31)
    streak = scatter_strokes(p, n, fine=True) * .17
    residue = (1 - smooth(.0006, .0036, distance)) * smooth(.51, .82, micro) * .40
    color = color + rgb(30, 25, 17) * (residue + streak)[:, None]
    spec = (.54 if coated else .58) - residue * .15
    gloss = (.93 if coated else .95) - residue * .13 - streak * .18
    return color, -.000038 * streak, spec, gloss, np.zeros_like(streak)


def evaluate(material, obj, p, n, distance, *, source_uv=None, ao, convex, concave, contact, position_height):
    """Return sRGB albedo, meter height, specular RGB, gloss, and metalness."""
    key = material.lower().split(" | ")[-1]
    obj = obj.lower()
    broad = noise(p, 26, 17)
    breakup = noise(p, 121, 9)
    micro = noise(p, 617, 29)
    low = (1 - smooth(.027, .372, position_height)) ** 2
    if key in COMPOSITE or key in PAINTED_STEEL or key in BARE_STEEL:
        result = hard_surface(key, obj, p, n, distance, ao, convex, concave, contact, low, broad, breakup, micro)
    elif key in FABRIC:
        result = woven(key, obj, p, n, distance, ao, concave, low, breakup, micro, source_uv)
    elif key in {"smoked black visor", "opaque black visor", "coated germanium"}:
        result = visor(key, p, n, distance, micro)
    elif key == "yellow cable jacket":
        result = jacket(obj, p, n, distance, ao, low, breakup)
    else:
        result = molded(key, ao, concave, low, broad, breakup, micro)

    color, height, spec, gloss, metal = result
    if key == "powerpack black" and "powerpack cartridge" in obj:
        response = np.ones(len(p), np.float32)
        cartridge_ink(p, n, color, height, response, gloss, micro)
        indicator = response < 1
        if spec.ndim == 2:
            spec[indicator] = response[indicator, None]
        else:
            spec[indicator] = response[indicator]
    if spec.ndim == 1:
        spec = np.repeat(spec[:, None], 3, axis=1)
    return (np.clip(color, 0, 1).astype(np.float32, copy=False),
            height.astype(np.float32, copy=False),
            np.clip(spec, 0, 1).astype(np.float32, copy=False),
            np.clip(gloss, 0, 1).astype(np.float32, copy=False),
            np.clip(metal, 0, 1).astype(np.float32, copy=False))
