"""An outer thigh shield and three articulated front lames."""
import math
from functools import lru_cache

from mathutils import Vector

from leg_shells import between, mount_surface, shell_grid


AXIS = (
    (.545, .150, -.029), (.620, .135, -.025), (.700, .130, -.022),
    (.780, .124, -.019), (.860, .121, -.016),
)
THICKNESS = .015


def build(geo):
    """Build both the dark front lames and khaki outer shell."""
    from legs import THIGH, blend_skin, cut_box

    cloth = geo.cuff_fit
    if cloth is None:
        raise ValueError("Thigh shields require the fitted combat trousers")

    slices = []
    for triangle in cloth.faces:
        pts = [cloth.points[i] for i in triangle]
        if max(p.x * geo.side for p in pts) > .015:
            edges = list(zip(pts, pts[1:] + pts[:1]))
            slices.append((min(p.z for p in pts), max(p.z for p in pts), edges))

    @lru_cache(maxsize=None)
    def outline(z):
        xy = []
        for lo, hi, edges in slices:
            if not lo <= z <= hi:
                continue
            for a, b in edges:
                if min(a.z, b.z) <= z < max(a.z, b.z):
                    point = a.lerp(b, (z - a.z) / (b.z - a.z))
                    if geo.side * point.x > 0:
                        xy.append((geo.side * point.x, point.y))
        return [(min(values) - .0172, max(values) + .0172) for values in zip(*xy)]

    @lru_cache(maxsize=None)
    def profile(angle, z, side_shield):
        theta = math.radians(angle)
        x, y = between(AXIS, z)
        side = geo.side
        center = Vector((side * x, y, z))
        direction = Vector((side * math.sin(theta), -math.cos(theta), 0))
        contact, _, _, _ = cloth.index.ray_cast(center + .175 * direction, -direction, .17)
        if contact is None:
            raise ValueError(f"No trouser surface at angle={angle:.1f}, z={z:.3f}")
        # Fit using the distance to the actual triangles, including sloping folds.
        low, high = 0.0, .034
        clearance = .0075 + .0007 * abs(math.sin(2 * theta)) ** 2
        for _ in range(13):
            step = (low + high) / 2
            _, _, _, distance = cloth.index.find_nearest(contact + step * direction)
            if distance < clearance:
                low = step
            else:
                high = step
        inside = contact + high * direction
        inside.x *= side
        direction.x *= side

        # Keep the outboard and front extrema within the projection envelope.
        # Most of the panel retains the nominal wall thickness.
        cap = THICKNESS
        for i, (lower, upper) in enumerate(outline(z)):
            if side_shield and i == 0 and .653 < z < .710:
                upper -= .0021
            if direction[i] > .01:
                cap = min(cap, (upper - inside[i]) / direction[i])
            elif direction[i] < -.01:
                cap = min(cap, (lower - inside[i]) / direction[i])
        return inside, direction, cap

    def project(angle, z, depth, side_shield=False):
        point, direction, cap = profile(angle, z, side_shield)
        return point + (THICKNESS + depth) * (cap / THICKNESS) * direction

    def skin(point):
        compliance = .72 * max(0, min(1, (point[1] - .024) / .040))
        return blend_skin(geo, point, THIGH, compliance)

    if not hasattr(geo, "inner_faces"):
        geo.inner_faces = {}

    def mesh(role, projector, columns, rows, inset=None, surface=None):
        geo.armor_component = role
        first_vertex = len(geo.vertices)
        first_face = len(geo.faces)
        grid_size = len(columns) * len(rows)
        faces = shell_grid(geo, projector, columns, rows, skin, THICKNESS, inset)
        inner_start = first_vertex + grid_size
        geo.inner_faces[role] = [
            i for i in range(first_face, len(geo.faces))
            if all(inner_start <= k < inner_start + grid_size for k in geo.faces[i])
        ]
        if surface:
            for i in range(first_face, len(geo.faces)):
                if geo.surfaces[i] == "khaki":
                    geo.surfaces[i] = surface
                elif geo.surfaces[i] == "edge":
                    geo.surfaces[i] = surface
        return faces

    def outer(u, v, depth):
        # Taller on the hip end, with a clipped, rounded nose above the knee.
        corners = (2 * abs(u - .5)) ** 3
        z_lo = .590 + .019 * corners
        z_hi = .850 - .048 * u - .011 * corners
        z = z_lo + (z_hi - z_lo) * v
        front_edge = 50 + 10 * max(0, 1 - v * 7) + 4 * max(0, v * 10 - 9)
        back_edge = 142 - 11 * max(0, 1 - v * 9) - 5 * max(0, v * 10 - 9)
        # Pull the inset to a clipped point without changing the outside edge.
        taper = .115 * max(0, 1 - abs(v - .211) / .16)
        if u < .338:
            shift = taper * u / .338
        elif u > .816:
            shift = -taper * (1 - u) / (1 - .816)
        else:
            shift = taper * (1 - 2 * (u - .338) / (.816 - .338))
        angle = front_edge + (back_edge - front_edge) * (u + shift)
        return project(angle, z, depth, side_shield=True)

    inset = (.338, .816, .211, .913)
    columns = [0, .13, .260, .338, .352, .500, .660, .802, .816, .910, 1]
    rows = [0, .045, .125, .211, .218, .315, .368, .420, .50, .66, .78,
            .906, .913, .962, 1]
    if geo.lod:
        columns = [0, .085, .180, .338, .352, .550, .802, .816, .925, 1]
        rows = [0, .125, .169, .211, .218, .276, .368, .420, .56, .74, .906, .913, 1]
    from v5c_fit import give_thigh_wall_room, mount_thigh_detail

    faces = mesh(1, outer, columns, rows, inset)
    room = give_thigh_wall_room(geo, 1, faces, geo.inner_faces[1])
    structural_mount = mount_surface(geo, faces)

    for v in (.435, .566, .697):
        def pad(u, height, depth):
            return mount_thigh_detail(room, outer(.574 + u, v + height, depth - .0049), geo.side)
        geo.shell(cut_box(.107, .038, .009), pad, skin, "steel_edge",
                  depth=.0032, bevel=.002)

    def seams(u):
        """Arc across the anterior panel, descending inward towards the inseam."""
        return .023 * (u - .48) - .015 * (1 - u) ** 3

    def lame_project(role, u, v, depth):
        bounds = {
            9: (.590, .657), 10: (.6585, .733), 11: (.7345, .816),
        }
        lower, upper = bounds[role]
        lower += seams(u)
        upper += seams(u)
        corner = (2 * abs(u - .5)) ** 6
        lower += (.013 if role == 9 else .0005) * corner
        upper -= (.007 if role == 11 else .0004) * corner
        if role == 9:
            lower = max(.5948, lower)
        if role == 11:
            upper += .019 * u
        z = lower + (upper - lower) * v
        angle_in = -29 - 5 * min(1, max(0, (z - .600) / .120))
        angle_out = 48 + 8 * max(0, min(1, (.651 - z) / .055))
        angle = angle_in + (angle_out - angle_in) * u
        if role == 9 and z < .609:
            # The lower lamella tapers into a shallow ledge behind the knee lip.
            point, direction, cap = profile(angle, z, False)
            blend = min(1., max(0., (z - .598) / .011))
            blend = blend * blend * (3 - 2 * blend)
            thickness = min(cap, .0012 + THICKNESS * blend)
            return point + ((1 + depth / THICKNESS) * thickness - .0017 * (1 - blend)) * direction
        return project(angle, z, depth)

    for role in (9, 10, 11):
        def front(u, v, depth):
            return lame_project(role, u, v, depth)
        columns = [i / (7 if geo.lod else 10) for i in range(8 if geo.lod else 11)]
        rows = [0, .22, .52, .78, 1] if not geo.lod else [0, .31, .68, 1]
        faces = mesh(role, front, columns, rows, surface="dark")
        room = None
        if role == 9 and geo.lod and geo.side < 0:
            room = give_thigh_wall_room(geo, role, faces, geo.inner_faces[role])

        # The clips straddle the dark seams and stop short of the side shield.
        def clip(u, v, depth):
            point = front(.607 + u, (1 if role != 11 else .27) + v, depth + .0008)
            return mount_thigh_detail(room, point, geo.side)
        geo.shell(cut_box(.024, .101, .008), clip, skin, "steel_edge",
                  depth=.0028, bevel=.001)

    return structural_mount

