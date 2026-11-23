"""Small service stencils positioned in rest space, shared across both LODs."""
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=4)
def artwork(kind):
    image = Image.new("L", (384, 128))
    pen = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("consolab.ttf", 67)
    except OSError:
        font = ImageFont.load_default(size=64)
    if kind == "leg":
        pen.polygon([(14, 70), (58, 26), (83, 26), (39, 70)], fill=226)
        pen.polygon([(15, 106), (94, 27), (113, 27), (34, 106)], fill=226)
        pen.text((129, 10), "J/05", font=font, fill=230)
        pen.line((135, 99, 306, 99), fill=185, width=4)
        for x in (135, 162, 189, 216):
            pen.line((x, 97, x, 113), fill=172, width=3)
    elif kind == "pack":
        pen.text((6, 2), "24 V", font=font, fill=215)
        pen.line((8, 91, 171, 91), fill=190, width=5)
        pen.line((253, 62, 340, 62), fill=206, width=6)
        pen.polygon([(321, 42), (350, 62), (321, 81)], fill=206)
    else:
        pen.text((31, 7), "07-4", font=font, fill=222)
        for x, width in ((222, 5), (234, 14), (254, 5), (269, 8), (286, 4), (297,12)):
            pen.rectangle((x, 34, x+width, 80), fill=203)
    return np.asarray(image, dtype=np.float32) / 255


def apply(object_name, p, n, albedo, relief, spec, gloss, metallic, *, ao, convex, concave, contact, position_height):
    name = object_name.casefold()
    x, y, z = p.T
    if name.startswith("legframe_"):
        sign = 1 if "legframe_l" in name else -1
        # Print on the recessed side cover of the lower-leg service hatch.
        u = .5 + sign * (y - .016) / .035
        v = .5 - (z - .229) / .012
        facing = (sign * n[:, 0] > .81) & (sign * x > .367)
        kind, tone = "leg", (.73, .64, .44)
    elif name.startswith("powerpack cartridge and covers"):
        # Upper access door; the existing triangular warning sits below it.
        u = .5 - (x - .037) / .039
        v = .5 - (z - 1.492) / .013
        facing = (n[:, 1] > .84) & (y > .285)
        kind, tone = "pack", (.20, .19, .16)
    elif name.startswith("side | ear armor +1"):
        u = .5 + (y + .006) / .035
        v = .5 - (z - 1.720) / .011
        facing = (n[:, 0] > .84) & (x > .131)
        kind, tone = "batch", (.59, .59, .53)
    else:
        return albedo, relief, spec, gloss, metallic
    use = (u >= 0) & (u < 1) & (v >= 0) & (v < 1) & facing
    if np.any(use):
        bitmap = artwork(kind)
        row = v[use] * (bitmap.shape[0] - 1)
        col = u[use] * (bitmap.shape[1] - 1)
        j = np.minimum(row.astype(int), bitmap.shape[0] - 2)
        i = np.minimum(col.astype(int), bitmap.shape[1] - 2)
        fraction_y, fraction_x = row - j, col - i
        upper = bitmap[j, i] * (1 - fraction_x) + bitmap[j, i + 1] * fraction_x
        lower = bitmap[j + 1, i] * (1 - fraction_x) + bitmap[j + 1, i + 1] * fraction_x
        alpha = upper * (1 - fraction_y) + lower * fraction_y
        abrasion = np.maximum(np.sin(x[use] * 2797 + y[use] * 4411 + np.sin(z[use] * 3251) * 2), 0)**4
        exposure = 0.55 + 0.25 * ao[use] + 0.15 * position_height[use]
        damage = 0.10 + 0.54 * convex[use] + 0.24 * concave[use] + 0.24 * contact[use]
        alpha *= exposure * (1 - np.clip(damage * abrasion, 0, 1))
        albedo[use] += (np.array(tone, np.float32) - albedo[use]) * alpha[:, None]
        relief[use] += 0.000085 * alpha
        spec[use] += (np.array((0.19, 0.187, 0.181)) - spec[use]) * alpha[:, None]
        gloss[use] += (.31 - gloss[use]) * alpha
        metallic[use] *= 1 - alpha
    return albedo, relief, spec, gloss, metallic
