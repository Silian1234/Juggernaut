"""Fitted ankle bands, instep plates and heel guards."""
import math
from functools import lru_cache

from mathutils import Vector

from leg_shells import between
from legs import FOOT


CUFF_TOP = .143
CUFF_BOTTOM = .101
CUFF_SPAN = math.radians(110)
PROFILES = (
    (-.175, .237, .012),
    (-.169, .237, .027),
    (-.154, .235, .042),
    (-.134, .234, .052),
    (-.112, .233, .054),
    (-.103, .233, .053),
    (-.093, .233, .046),
)


def fit_clearance(index, surface, direction, target):
    """Solve closest-surface clearance along the loft's outward direction."""
    lo, hi = 0.0, target * 2.5
    for _ in range(15):
        mid = (lo + hi) * .5
        distance = index.find_nearest(surface + direction * mid)[3]
        if distance < target:
            lo = mid
        else:
            hi = mid
    return surface + direction * ((lo + hi) * .5)


def row_stations(count, first, last, extra=()):
    return sorted({round(first + (last - first) * i / count, 8) for i in range(count + 1)}
                  | {round(value, 8) for value in extra})


def fitted_shell(geo, project, columns, rows, skin, depth, lip=False):
    """Loft matched front/back grids with one continuous chamfer along the rim."""
    nx, ny = len(columns), len(rows)
    width = columns[-1] - columns[0]
    middle = (rows[0] + rows[-1]) / 2
    coordinates = [(u, v) for v in rows for u in columns]
    boundary = (list(range(nx))
                + [row * nx + nx - 1 for row in range(1, ny)]
                + list(range(nx * ny - 2, nx * (ny - 1) - 1, -1))
                + [row * nx for row in range(ny - 2, 0, -1)])
    boundary_ids = set(boundary)

    def exterior(i):
        u, v = coordinates[i]
        if i in boundary_ids:
            u += (.5 - u) * .038 / width
            v += (middle - v) * .052
        return project(u, v, 0)

    front = geo.add((exterior(i) for i in range(len(coordinates))), [], skin, "khaki")
    back = geo.add((project(u, v, -depth) for u, v in coordinates), [], skin, "khaki")
    rim = geo.add((project(*coordinates[i], -.0028) for i in boundary), [], skin, "edge")
    if lip:
        lower_rim = geo.add((project(*coordinates[i], -.0055) for i in boundary),
                            [], skin, "khaki")
    for j, i in enumerate(boundary):
        k = (j + 1) % len(boundary)
        b = boundary[k]
        if lip:
            geo.record((back + i, back + b, lower_rim + k, lower_rim + j), "khaki")
            geo.record((lower_rim + j, lower_rim + k, rim + k, rim + j), "khaki")
        else:
            geo.record((back + i, back + b, rim + k, rim + j), "khaki")
        geo.record((rim + j, rim + k, front + b, front + i), "edge")
    inside = []
    for y in range(ny - 1):
        for x in range(nx - 1):
            i = y * nx + x
            cell = (i, i + 1, i + 1 + nx, i + nx)
            inside.append(len(geo.faces))
            geo.record(tuple(back + j for j in reversed(cell)), "khaki")
            geo.record(tuple(front + j for j in cell), "khaki", True)
    part = geo.armor_component
    if not hasattr(geo, "inner_faces"):
        geo.inner_faces = {}
    geo.inner_faces[part] = inside
    geo.depth_pairs[part] = [j for i in range(len(coordinates)) if i not in boundary_ids
                             for j in (back + i, front + i)]
    if not hasattr(geo, "local_depth"):
        geo.local_depth = set()
    geo.local_depth.add(part)


def fastener(geo, project, u, v, skin):
    point = project(u, v, -.00055)
    horizontal = project(u + .008, v, 0) - project(u - .008, v, 0)
    vertical = project(u, v + .001, 0) - project(u, v - .001, 0)
    axis = horizontal.cross(vertical).normalized()
    geo.disc(point, axis, .0042, .0015, skin, "steel", 5 if geo.lod else 7)


def ankle_cuff(geo):
    index = geo.cuff_fit.index
    geo.armor_component = 5
    depth = .007

    def project(u, z, offset):
        # Clip the four corners, retaining two parallel edges through the main band.
        clip = max(0, 1 - (z - CUFF_BOTTOM) / .007, 1 - (CUFF_TOP - z) / .007)
        angle = (2 * u - 1) * (CUFF_SPAN - math.radians(6) * clip)
        # The reference crown dips above the toe and rises into two clipped ears.
        t = (z - CUFF_BOTTOM) / (CUFF_TOP - CUFF_BOTTOM)
        across = abs(2 * u - 1)
        peak = max(0, 1 - ((across - .78) / .78) ** 2)
        crown = .136 + .007 * peak - .004 * max(0, (across - .78) / .22)
        toe_relief = .009 * max(0, 1 - (across / .43) ** 2)
        lower = CUFF_BOTTOM + toe_relief - .010 * min(1, max(0, (across - .2) / .45))
        z = lower + (crown - lower) * t
        origin = Vector((geo.side * (.22 - .40 * (z - .093)), .02, z))
        axis = Vector((geo.side * math.sin(angle), -math.cos(angle), 0))
        surface, _, _, _ = index.ray_cast(origin + axis * .16, -axis, .16)
        if surface is None:
            raise ValueError(f"Ankle fit missed at z={z:.4f}, angle={angle:.3f}")
        point = fit_clearance(index, surface, axis, .0103 if geo.lod else .0100) + axis * (depth + offset)
        return Vector((geo.side * point.x, point.y, point.z))

    def skin(point):
        # Follow the weights on the native garment at the cuff's radial contact.
        x, y, z = point
        origin = Vector((geo.side * (.22 - .40 * (z - .093)), .02, z))
        direction = Vector((geo.side * x, y, z)) - origin
        hit = index.ray_cast(origin, direction.normalized(), .16)[0]
        if hit is None:
            hit = origin + direction
        native = geo.cuff_fit.weights(hit)
        # Let the bottom of the forward band share the instep's foot motion.
        # The upper crown and the rear side ears retain the trouser weights.
        moving = .58 * max(0, min(1, (.13 - z) / .025))
        moving *= max(0, min(1, (-y - .044) / .040))
        if not moving:
            return native
        foot = f"Base Human{'L' if geo.side > 0 else 'R'}Foot"
        weights = {name: weight * (1 - moving) for name, weight in native.items()}
        weights[foot] = weights.get(foot, 0) + moving
        return weights

    columns = ((0, .11, .22, .33, .39, .44, .50, .56, .61, .67, .73, .78, .89, 1)
               if geo.lod else
               (0, .11, .20, .30, .36, .40, .44, .50, .54, .58, .62, .67, .74, .83, .89, 1))
    rows = (CUFF_BOTTOM, CUFF_BOTTOM + .007, .122, CUFF_TOP - .007, CUFF_TOP)
    fitted_shell(geo, project, columns, rows, skin, depth)
    for u in (.20, .80):
        fastener(geo, project, u, .122, skin)


def instep_cover(geo):
    index = geo.boot_fit.index
    geo.armor_component = 7
    up = Vector((0, 0, 1))
    depth = .009

    def boot_clearance(x, y, u):
        hit = index.ray_cast(Vector((geo.side * x, y, .16)), -up, .14)[0]
        if hit is None:
            raise ValueError(f"Boot fit missed at x={x:.4f}, y={y:.4f}")
        seam_clearance = .0004 if geo.lod and .12 < u < .30 and y > -.122 else 0
        return fit_clearance(index, hit, up, .00625 + seam_clearance).z

    @lru_cache(maxsize=512)
    def fitted_height(u, y):
        center, width = between(PROFILES, y)
        return boot_clearance(center + (2 * u - 1) * width, y, u)

    @lru_cache(maxsize=128)
    def crown_at(y):
        # Fair continuous visible cross-sections over the irregular stitching.
        points = [(2 * i / 16 - 1, fitted_height(i / 16, y)) for i in range(17)]
        left = sum(z for w, z in points if -.875 <= w <= -.5) / 4
        right = sum(z for w, z in points if .5 <= w <= .875) / 4
        center = sum(z for w, z in points if abs(w) <= .25) / 5
        slope = (right - left) / 1.375
        curvature = min(-.001, ((left + right) / 2 - center) / .485)
        radius = curvature * min(1, max(0, (y - PROFILES[0][0]) / .010))
        minimum = max(z - slope * w - radius * w * w for w, z in points)
        return max(center + depth, minimum + .0045), slope, radius

    def project(u, y, offset):
        center, width = between(PROFILES, y)
        w = 2 * u - 1
        x = center + w * width
        # Clipped sides reach the boot-to-trouser seam. The middle of the rear
        # rim is shortened so the plate can rotate below the ankle band.
        y -= .008 * max(0, (y + .111) / .018) * (1 - w * w)
        if offset == -depth:
            # Tuck the fitted lower nose behind the continuous forward rim.
            back_y = y + .0075 * max(0, 1 - (y - PROFILES[0][0]) / .016)
            return Vector((x, back_y, boot_clearance(x, back_y, u) + .0010))
        height, slope, radius = crown_at(y)
        exterior_z = height + slope * w + radius * w * w + offset
        if offset == -.0055:
            # Keep the lip above the lower face where its setback tapers away.
            blend = min(1, max(0, (y - PROFILES[0][0] - .006) / .010))
            exterior_z += blend * max(0, fitted_height(u, y) + .0006 - exterior_z)
        return Vector((x, y, exterior_z))

    fitted_shell(geo, project, row_stations(6 if geo.lod else 8, 0, 1),
                 [row[0] for row in PROFILES], FOOT, depth, lip=True)
    for u in (.24, .76):
        fastener(geo, project, u, -.103, FOOT)


def heel_guard(geo):
    """A single posterior casting above the sole, carried by the foot."""
    index = geo.boot_fit.index
    geo.armor_component = 14
    depth = .007

    @lru_cache(maxsize=None)
    def surface(u, v):
        edge = min(u, 1 - u)
        clip = max(0, 1 - edge / .18)
        bottom = .019 + .006 * clip
        top = .048 - .007 * clip
        z = bottom + (top - bottom) * v
        angle = math.radians(122 + 119 * u)
        origin = Vector((geo.side * .224, .023, z))
        axis = Vector((geo.side * math.sin(angle), -math.cos(angle), 0))
        hit = index.ray_cast(origin + axis * .15, -axis, .15)[0]
        if hit is None:
            raise ValueError(f"Heel fit missed at z={z:.4f}, angle={angle:.3f}")
        return fit_clearance(index, hit, axis, .0103), axis

    def project(u, v, offset):
        point, axis = surface(u, v)
        point = point + axis * (depth + offset)
        return Vector((geo.side * point.x, point.y, point.z))

    columns = (0, .12, .24, .36, .48, .60, .72, .84, 1)
    if geo.lod:
        columns = (0, .15, .29, .43, .56, .69, .84, 1)
    fitted_shell(geo, project, columns, (0., .26, .72, 1.), FOOT, depth)
    for u in (.18, .82):
        fastener(geo, project, u, .51, FOOT)


def achilles_guard(geo):
    """Close the ankle between the calf and heel with a floating rear cuff."""
    index = geo.cuff_fit.index
    geo.armor_component = 15
    depth = .006

    @lru_cache(maxsize=None)
    def surface(u, v):
        corner = max(0, 1 - min(u, 1 - u) / .17)
        bottom = .067 + .008 * corner
        top = .136 - .009 * corner
        z = bottom + (top - bottom) * v
        angle = math.radians(124 + 118 * u)
        origin = Vector((geo.side * (.22 - .4 * (z - .093)), .025, z))
        axis = Vector((geo.side * math.sin(angle), -math.cos(angle), 0))
        hit = index.ray_cast(origin + axis * .16, -axis, .16)[0]
        if hit is None:
            raise ValueError(f"Rear ankle fit missed at z={z:.4f}, angle={angle:.3f}")
        fitted = fit_clearance(index, hit, axis, .0100)
        return fitted, axis

    def project(u, v, offset):
        point, axis = surface(u, v)
        point = point + axis * (depth + offset)
        return Vector((geo.side * point.x, point.y, point.z))

    def skin(point):
        x, y, z = point
        return geo.cuff_fit.weights((geo.side * x, y, z))

    columns = (0, .11, .23, .37, .49, .61, .73, .86, 1)
    if geo.lod:
        columns = (0, .15, .29, .43, .56, .69, .84, 1)
    fitted_shell(geo, project, columns, (0., .24, .50, .76, 1.), skin, depth)


def build(geo):
    ankle_cuff(geo)
    instep_cover(geo)
    heel_guard(geo)
    achilles_guard(geo)
