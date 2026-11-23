"""Pressed knee shield with a fitted backing and a smooth, independent crown."""
from functools import lru_cache

import numpy as np
from mathutils import Vector

from leg_shells import between, lerp
from legs import KNEE


# Height, medial half-width, lateral half-width, and centerline shift.
PROFILE = (
    (0., .006, .006, .004),
    (.085, .026, .024, .004),
    (.223, .041, .039, .003),
    (.420, .053, .050, .001),
    (.630, .061, .057, 0.),
    (.790, .060, .053, -.001),
    (.920, .055, .050, -.002),
    (1., .044, .045, -.002),
)
COLUMNS = (-1., -.73, -.37, -.33, 0., .33, .37, .59, .635, 1.)
ROWS = (0., .085, .223, .420, .485, .647, .790, .842, .857, .885, .900, 1.)


@lru_cache(maxsize=4096)
def _clearance(garment, x, z, stand_off):
    """Find the front surface offset for a prescribed nearest distance."""
    point = garment.index.ray_cast(Vector((x, -.25, z)), Vector((0, 1, 0)), .25)[0]
    if point is None:
        raise ValueError(f"Knee outline is outside the trousers near {(x, z)}")
    lo, hi = point.y - .034, point.y
    for _ in range(13):
        trial = (lo + hi) * .5
        _, _, _, nearest = garment.index.find_nearest(Vector((x, trial, z)))
        if nearest > stand_off:
            lo = trial
        else:
            hi = trial
    return (lo + hi) * .5


@lru_cache(maxsize=4096)
def _side_limit(garment, side, z):
    """Return the permitted foremost point at the indicated height."""
    direction = Vector((0, 1, 0))
    hits = [garment.index.ray_cast(
        Vector((side * (.087 + i * .002), -.25, z)), direction, .25)[0]
            for i in range(68)]
    return min(point.y for point in hits if point is not None) - .01875


def _smoothstep(value):
    value = min(1., max(0., value))
    return value * value * (3 - 2 * value)


def _outline(u, v):
    medial, lateral, shift = between(PROFILE, v)
    # Bow the dark lateral inset toward the face at mid-height, then close
    # its ends toward the rim so its edge follows the silhouette.
    gate = _smoothstep((v - .085) / .29) * _smoothstep((1.0 - v) / .23)
    wing = .94 - .365 * gate
    fraction = abs(u)
    if u >= .37:
        fraction = between(((.37, .37), (.59, wing - .036),
                            (.635, wing), (1., 1.)), u)[0]
    x = .150 + shift + (lateral if u >= 0 else -medial) * fraction
    cap_scallop = .0036 * (1 - u*u) * _smoothstep((v - .91) / .09)
    z = .459 + .139 * v - cap_scallop
    return x, z


def _stand_off(u, v):
    lip = max(_smoothstep((.16 - v) / .16), _smoothstep((v - .91) / .09))
    wing = _smoothstep((u - .60) / .40) * _smoothstep((v - .22) / .20)
    return .0085 + max(.0026 * lip, .0014 * wing)


def _slot_depth(u, v):
    across = min(1., max(0., (.37 - abs(u)) / .04))
    height = min(1., max(0., (v - .842) / .015), max(0., (.900 - v) / .015))
    return .0035 * across * height


def _inset_depth(u, v):
    wing = min(1., max(0., (u - .59) / .045))
    ends = _smoothstep((v - .085) / .24) * _smoothstep((1 - v) / .135)
    return .0019 * wing * ends


def _crown_basis(x, z):
    """Low-order tensor basis on the curved plate, in metric coordinates."""
    across = (x - .147) / .061
    height = (z - .5285) / .0695
    long = (1., height, 2*height*height - 1, 4*height**3 - 3*height)
    wide = (1., across, across*across, across**3)
    return [a*b for a in long for b in wide]


def _crown(garment, side, domain, outline):
    """Fit one coherent pressed surface to the front-depth and clearance envelopes."""
    targets, limits, backing = [], [], []
    for (u, v), (x, z) in zip(domain, outline):
        back = _clearance(garment, side*x, z, _stand_off(u, v))
        limit = _side_limit(garment, side, z)
        detail = _slot_depth(u, v) + _inset_depth(u, v)
        available = back - .0018 - detail
        # Keep the shoulders and tip tucked around the joint while projecting
        # the center of the shield a little farther over the patella.
        thickness = .005 + .0045 * (1 - abs(u)**2) * _smoothstep(v / .32)
        thickness = lerp(thickness, .0034, _smoothstep((v - .76) / .205))
        targets.append(min(available, max(limit, back - thickness - detail)))
        limits.append(min(limit, available))
        backing.append(available)
    basis = np.asarray([_crown_basis(*point) for point in outline])
    targets = np.asarray(targets)
    lower = np.asarray(limits)
    upper = np.asarray(backing)
    # Penalize the high-order cross terms so small cloth wrinkles cannot
    # propagate into the molded face. Fit envelopes with extra weight.
    regularize = np.diag([.01 + .20*(a*b) + .11*(a+b) for a in range(4) for b in range(4)])
    regularize[0, 0] = .0001
    penalty = regularize @ regularize
    coefficients = np.linalg.solve(basis.T @ basis + penalty, basis.T @ targets)
    for _ in range(18):
        proposed = basis @ coefficients
        weights = np.where((proposed > upper) | (proposed < lower), 36., 1.)
        desired = np.where(proposed > upper, upper, np.where(proposed < lower, lower, targets))
        weighted = basis.T * weights
        revision = np.linalg.solve(weighted @ basis + penalty, weighted @ desired)
        coefficients = .65 * coefficients + .35 * revision
    positions = basis @ coefficients
    # The collar backing can require a local relief hidden by the thigh hem.
    return np.clip(positions, lower, upper)


def build(geo):
    """Add the knee plate with a sharp perimeter bevel and recessed details."""
    geo.armor_component = 3
    columns = COLUMNS if geo.lod == 0 else tuple(u for u in COLUMNS if u != -.73)
    rows = ROWS
    nx, ny = len(columns), len(rows)
    domain = [(u, v) for v in rows for u in columns]
    boundary = (list(range(nx))
                + [row * nx + nx - 1 for row in range(1, ny)]
                + list(range(nx * ny - 2, nx * (ny - 1) - 1, -1))
                + [row * nx for row in range(ny - 2, 0, -1)])
    boundary_set = set(boundary)

    # The crown and the rim share the die outline. The hidden backing is
    # independently projected onto the garment and can be refined later.
    def outline_point(u, v):
        x, z = _outline(u, v)
        # The coarser left thigh hem sits slightly lower over the lateral collar.
        if geo.lod and geo.side > 0:
            z -= .0027 * _smoothstep((v - .90) / .10) * _smoothstep((u + .30) / .36)
        return x, z

    outline = [outline_point(u, v) for u, v in domain]
    front_domain = [(u*.969, lerp(.5, v, .973)) if i in boundary_set else (u, v)
                    for i, (u, v) in enumerate(domain)]
    front_outline = [outline_point(u, v) for u, v in front_domain]
    crown = _crown(geo.cuff_fit, geo.side, front_domain, front_outline)

    inner = [(x, _clearance(geo.cuff_fit, geo.side*x, z, _stand_off(u, v)), z)
             for (u, v), (x, z) in zip(domain, outline)]
    outer = [(x, y + _slot_depth(u, v) + _inset_depth(u, v), z)
             for (u, v), (x, z), y in zip(front_domain, front_outline, crown)]

    rear = geo.add(inner, [], KNEE, "khaki")
    fore = geo.add(outer, [], KNEE, "khaki")
    rim = geo.add(((inner[i][0], outer[i][1] + .0014, inner[i][2]) for i in boundary),
                  [], KNEE, "edge")

    for j, a in enumerate(boundary):
        k = (j + 1) % len(boundary)
        b = boundary[k]
        geo.record((rear + a, rear + b, rim + k, rim + j), "khaki", True)
        geo.record((rim + j, rim + k, fore + b, fore + a), "edge")

    inner_faces = []
    for row in range(ny - 1):
        v = (rows[row] + rows[row + 1]) * .5
        for column in range(nx - 1):
            i = row * nx + column
            u = (columns[column] + columns[column + 1]) * .5
            cell = (i, i + 1, i + nx + 1, i + nx)
            inner_faces.append(len(geo.faces))
            geo.record(tuple(rear + j for j in reversed(cell)), "khaki")
            if abs(u) < .37 and .842 < v < .900:
                floor = abs(u) < .33 and .857 < v < .885
                surface, smooth = ("dark", True) if floor else ("knee_chamfer", False)
            elif u > .59 and .085 < v < 1.:
                surface, smooth = ("knee_crown", True) if u > .635 else ("knee_chamfer", False)
            else:
                surface, smooth = "khaki", True
            geo.record(tuple(fore + j for j in cell), surface, smooth)

    geo.inner_faces[3] = inner_faces
    if not hasattr(geo, "local_depth"):
        geo.local_depth = set()
    geo.local_depth.add(3)
    geo.depth_pairs[3] = [j for i, (u, v) in enumerate(domain) for j in (rear + i, fore + i)
                          if i not in boundary_set and _slot_depth(u, v) == 0.]
