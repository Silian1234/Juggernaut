"""Lofted leg armor profiles, including the continuous recesses and vents."""
from bisect import bisect_right
from functools import lru_cache
import math

from mathutils import Vector


def lerp(a, b, t):
    return a + (b - a) * t


def between(rows, value):
    first = max(0, min(len(rows) - 2, bisect_right([row[0] for row in rows], value) - 1))
    low, high = rows[first:first + 2]
    t = max(0, min(1, (value - low[0]) / (high[0] - low[0])))
    return tuple(lerp(a, b, t) for a, b in zip(low[1:], high[1:]))


class Wrap:
    def __init__(self, garment, levels, edges, clearance, fairing=0):
        self.garment = garment
        self.levels = levels
        self.edges = edges
        self.clearance = clearance
        self.fairing = fairing

    @lru_cache(maxsize=4096)
    def radial_profile(self, theta, z):
        x, y, radius = between(self.levels, z)
        if not self.garment:
            return radius
        samples = []
        for dz in (-.018, -.009, 0, .009, .018):
            for dt in (-.23, -.12, 0, .12, .23):
                px, py, _ = between(self.levels, z + dz)
                angle = theta + dt
                value = self.garment.radial(px, py, z + dz, math.sin(angle), -math.cos(angle))
                if value is not None and value < radius + .038:
                    samples.append(value)
        if not samples:
            return radius
        fitted = max(radius - .012, .23 * max(samples) + .77 * sum(samples) / len(samples))
        return lerp(fitted, radius, self.fairing)

    def project(self, u, v, depth):
        inner, outer, angle_in, angle_out = between(self.edges, v)
        theta = math.radians(lerp(angle_in, angle_out, u))
        z = v + lerp(inner, outer, u) * min(1, abs(u - .29) / .29)**2
        x, y, _ = between(self.levels, z)
        r = self.radial_profile(theta, z) + self.clearance(u, z) + depth
        return Vector((x + r * math.sin(theta), y - r * math.cos(theta), z))


def shell_grid(geo, project, columns, rows, skin, thickness, inset=None, slots=(), rib=None):
    """Close the front, chamfer, back, and every wall around a vent."""
    vertices = [(u, v) for v in rows for u in columns]
    nx, ny = len(columns), len(rows)
    boundary = (list(range(nx))
                + [row * nx + nx - 1 for row in range(1, ny)]
                + list(range(nx * ny - 2, nx * (ny - 1) - 1, -1))
                + [row * nx for row in range(ny - 2, 0, -1)])

    def recession(i):
        if inset is None:
            return 0
        u, v = vertices[i]
        left, right, low, high = inset
        depth = .0065 if inset[0] > .75 else .0045
        return -depth * max(0.0, min(1.0, (u - left) / .014, (right - u) / .014,
                                     (v - low) / .007, (high - v) / .007))

    def grid(i, back=False):
        u, v = vertices[i]
        if i in boundary:
            u = lerp(.5, u, .971)
            v = lerp((rows[0] + rows[-1]) * .5, v, .976)
        return project(u, v, -thickness if back else recession(i))

    front = geo.add((grid(i) for i in range(len(vertices))), [], skin, "khaki")
    back = geo.add((grid(i, back=True) for i in range(len(vertices))), [], skin, "khaki")
    edge_high = geo.add((project(*vertices[i], -.003) for i in boundary), [], skin, "edge")
    edge_low = geo.add((project(*vertices[i], -thickness + .002) for i in boundary),
                       [], skin, "edge")
    # Only full-thickness pairs enter the physical thickness report.
    geo.depth_pairs[geo.armor_component] = [j for i in range(len(vertices))
                                            if recession(i) == 0
                                            for j in (back + i, front + i)]
    if not hasattr(geo, "local_depth"):
        geo.local_depth = set()
    geo.local_depth.add(geo.armor_component)

    surface_faces = []
    if rib is not None:
        cross, low, high = rib
        column = columns.index(cross)
        for row, (a, b) in enumerate(zip(rows, rows[1:])):
            if low < (a + b) * .5 < high:
                start = front + row * nx + column
                geo.sharp_edges.add((start, start + nx))
    for j, i in enumerate(boundary):
        k = (j + 1) % len(boundary)
        b = boundary[k]
        geo.record((back + i, back + b, edge_low + k, edge_low + j), "edge")
        geo.record((edge_low + j, edge_low + k, edge_high + k, edge_high + j), "khaki")
        face = (edge_high + j, edge_high + k, front + b, front + i)
        geo.record(face, "edge")
        surface_faces.append(face)

    def opening(column, row):
        if column < 0 or column >= nx - 1 or row < 0 or row >= ny - 1:
            return False
        u = (columns[column] + columns[column + 1]) * .5
        v = (rows[row] + rows[row + 1]) * .5
        return any(l < u < r and b < v < t for l, r, b, t in slots)

    for row in range(ny - 1):
        for column in range(nx - 1):
            i = row * nx + column
            cell = (i, i + 1, i + 1 + nx, i + nx)
            if opening(column, row):
                neighbors = ((column, row - 1), (column + 1, row),
                             (column, row + 1), (column - 1, row))
                for edge, neighbor in enumerate(neighbors):
                    if not opening(*neighbor):
                        a, b = cell[edge], cell[(edge + 1) % 4]
                        geo.record((front + a, front + b, back + b, back + a), "gunmetal")
            else:
                u = (columns[column] + columns[column + 1]) * .5
                v = (rows[row] + rows[row + 1]) * .5
                material = "khaki"
                if inset and inset[0] < u < inset[1] and inset[2] < v < inset[3]:
                    material = "gunmetal" if all(recession(k) < -.004 for k in cell) else "edge"
                geo.record(tuple(back + k for k in reversed(cell)), "khaki")
                face = tuple(front + k for k in cell)
                geo.record(face, material, material == "khaki")
                surface_faces.append(face)

    # The loft can have a different parameter orientation (the instep is X/Y).
    # Its caller orders columns and rows so their cross product points outward.
    return surface_faces


def mount_surface(geo, faces):
    """Query the actual tessellated shell. The hardware shares its skin weights."""
    from mathutils.bvhtree import BVHTree

    index = BVHTree.FromPolygons([Vector((abs(x), y, z)) for x, y, z in geo.vertices], faces)

    def mount(y, z):
        contact, _, _, _ = index.ray_cast(Vector((.48, y, z)), Vector((-1, 0, 0)), .40)
        if contact is None:
            raise ValueError(f"No outer shell surface at y={y:.3f}, z={z:.3f}")
        return tuple(contact)

    return mount


def coordinates(base, horizontal, lod, inset=None, slots=()):
    limits = [item[:2] if horizontal else item[2:] for item in slots]
    if inset:
        lo, hi = inset[:2] if horizontal else inset[2:]
        step = .014 if horizontal else .007
        limits.append((lo, lo + step, hi - step, hi))
    return sorted(set(base[::2] if lod else base).union(
        {base[-1], *(value for span in limits for value in span)}))
