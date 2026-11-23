"""Fitted leg armor and articulated exoskeleton for the original EFT rig."""
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from leg_shells import Wrap, between, coordinates, mount_surface, shell_grid


UP = Vector((0, 0, 1))
OUT = Vector((1, 0, 0))


class Geometry:
    def __init__(self, side, lod, trousers=None, cuff_fit=None):
        self.side = side
        self.lod = lod
        self.trousers = trousers
        self.cuff_fit = cuff_fit
        self.vertices = []
        self.weights = []
        self.faces = []
        self.surfaces = []
        self.smooth = []
        self.band_coordinates = {}
        self.armor_component = 0
        self.armor_components = []
        self.inner_faces = {}
        self.depth_pairs = {}
        self.sharp_edges = set()

    def add(self, vertices, faces, skin, surface, smooth=False):
        start = len(self.vertices)
        vertices = list(vertices)
        self.vertices.extend((self.side * x, y, z) for x, y, z in vertices)
        self.weights.extend(skin(v) if callable(skin) else skin for v in vertices)
        for face in faces:
            order = face if self.side > 0 else reversed(face)
            self.faces.append(tuple(start + j for j in order))
            self.surfaces.append(surface)
            self.smooth.append(smooth)
            self.armor_components.append(self.armor_component)
        return start

    def shell(self, profile, project, skin, surface, depth=0.012, bevel=0.003,
              smooth_top=False):
        """Three nested rims around an uneven, chamfered outline."""
        count = len(profile)
        cu = sum(u for u, v in profile) / count
        cv = sum(v for u, v in profile) / count
        inset = []
        for u, v in profile:
            distance = math.hypot(u - cu, v - cv)
            factor = 1 - bevel / distance
            inset.append((cu + factor * (u - cu), cv + factor * (v - cv)))

        if self.lod:
            low = self.add((project(u, v, -depth) for u, v in profile),
                           [tuple(reversed(range(count)))], skin, surface)
            high = self.add((project(u, v, 0) for u, v in profile), [], skin, surface)
        else:
            low = self.add((project(u, v, -depth) for u, v in profile),
                           [tuple(reversed(range(count)))], skin, surface)
            outer = self.add((project(u, v, -bevel) for u, v in profile),
                             [], skin, surface)
            self.join(low, outer, count, surface)
            low = outer
            high = self.add((project(u, v, 0) for u, v in inset), [], skin, surface)

        rim = "edge" if not self.lod and surface in ("khaki", "khaki_dark") else surface
        self.join(low, high, count, rim)
        crown = self.add((project(cu, cv, 0),), [], skin, surface)
        for i in range(count):
            self.record((high + i, high + (i + 1) % count, crown), surface, smooth_top)

    def record(self, indices, surface, smooth=False):
        self.faces.append(indices if self.side > 0 else tuple(reversed(indices)))
        self.surfaces.append(surface)
        self.smooth.append(smooth)
        self.armor_components.append(self.armor_component)

    def join(self, start, end, count, surface, smooth=False):
        for i in range(count):
            j = (i + 1) % count
            self.record((start + i, start + j, end + j, end + i), surface, smooth)

    def band(self, bottom_points, top_points, skin, closed):
        count = len(bottom_points)
        bottom = self.add(bottom_points, [], skin, "band")
        top = self.add(top_points, [], skin, "band")
        u = 0.0
        for i in range(count if closed else count - 1):
            j = (i + 1) % count
            length = ((Vector(bottom_points[j]) - Vector(bottom_points[i])).length
                      + (Vector(top_points[j]) - Vector(top_points[i])).length) * .5
            uv = ((u, 0), (u + length/.24, 0), (u + length/.24, 1), (u, 1))
            self.band_coordinates[len(self.faces)] = uv if self.side > 0 else tuple(reversed(uv))
            self.record((bottom + i, bottom + j, top + j, top + i), "band", True)
            u += length / .24

    def cuff(self, x, y, z, width, contours, skin, tuck=0):
        count = 16 if self.lod else 24

        def conform(point):
            base = skin(point) if callable(skin) else skin
            if self.trousers is None:
                return base
            px, py, pz = point
            following = self.trousers.weights((self.side * px, py, pz))
            fixed = max(0, min(1, (y - py - .027) / .068)) if tuck else 0
            prefix = "Base HumanL" if self.side > 0 else "Base HumanR"
            weights = {name: weight * (1 - fixed) for name, weight in following.items()}
            for name, weight in base.items():
                full_name = prefix + name
                weights[full_name] = weights.get(full_name, 0) + weight * fixed
            strongest = sorted(weights.items(), key=lambda pair: -pair[1])[:4]
            total = sum(weight for _, weight in strongest)
            return {name: weight / total for name, weight in strongest if weight > 0}

        def outline(section, level, offset):
            for i in range(count):
                angle = math.tau * i / count
                dx, dy = math.cos(angle), math.sin(angle)
                sample = i * 16 / count
                j = int(sample)
                t = sample - j
                radius = (1 - t) * section[j] + t * section[(j + 1) % 16]
                pz = z + .019 * dy + level * (1 - .12 * dy)
                fitted = self.cuff_fit.radial(x, y, pz, dx, dy) if self.cuff_fit else None
                if fitted is not None:
                    radius = fitted
                clearance = ((.008 if self.lod else .0065) if fitted is not None else .012) + offset
                if .52 < z < .54 and dy > -.5:
                    clearance += .003
                px = x + (radius + clearance) * dx
                py = y + (radius + clearance) * dy
                if tuck == 1 and px > .216:
                    # Run the outboard webbing into the space beneath the side shield.
                    cover = max(0, min(1, (.005 - py) / .030))
                    px -= cover * max(0, px - (.221 + offset))
                if tuck in (2, 3) and dy < -.35:
                    # Both edges tuck behind the sleeve toward the center of the shin.
                    drape = min(1, (-dy - .35) / .28)
                    px *= 1 - .03 * drape
                    capture = -.070 if tuck == 2 else -.078
                    py += drape * max(0, capture - py + offset)
                yield px, py, pz

        layers = [(-width/2, -.004, contours[0]), (-width/2, 0, contours[0])]
        if not self.lod:
            layers.extend(((-width/2 + .003, .002, contours[0]),
                           ( width/2 - .003, .002, contours[1])))
        layers.extend(((width/2, 0, contours[1]), (width/2, -.004, contours[1])))
        rings = [self.add(outline(section, level, offset), [], conform, "band")
                 for level, offset, section in layers]
        for i, (start, end) in enumerate(zip(rings, rings[1:] + rings[:1])):
            surface = "webbing" if i not in (1, len(rings) - 3) else "band"
            self.join(start, end, count, surface, smooth=True)

    def disc(self, center, axis, radius, width, skin, surface, count=8):
        axis = Vector(axis).normalized()
        u = UP.cross(axis).normalized()
        if u.length_squared < 0.1:
            u = OUT.copy()
        v = axis.cross(u)
        points = []
        for length in (-width / 2, width / 2):
            for i in range(count):
                angle = math.tau * i / count
                points.append(Vector(center) + length * axis
                              + radius * (math.cos(angle) * u + math.sin(angle) * v))
        faces = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
        faces += [(i, (i + 1) % count, (i + 1) % count + count, i + count)
                  for i in range(count)]
        self.add(points, faces, skin, surface)

    def hex_recess(self, center, normal, radius, height, skin, close_base=False):
        axis = Vector(normal).normalized()
        u = UP.cross(axis).normalized()
        v = axis.cross(u)
        rings = []
        for r, h in ((radius, 0), (radius * .83, height),
                     (radius * .39, height), (radius * .335, height * .36)):
            rings.append(self.add((Vector(center) + h * axis + r * (
                math.cos(math.tau * i / 6) * u + math.sin(math.tau * i / 6) * v)
                for i in range(6)), [], skin, "steel"))
        if close_base:
            self.record(tuple(range(rings[0] + 5, rings[0] - 1, -1)), "steel")
        self.join(rings[0], rings[1], 6, "steel")
        self.join(rings[1], rings[2], 6, "steel")
        self.join(rings[2], rings[3], 6, "gunmetal")
        self.record(tuple(range(rings[3], rings[3] + 6)), "gunmetal")

    def cable(self, points, radius, skin, surface="yellow"):
        points = [Vector(p) for p in points]
        count = 5 if self.lod else 7
        rings = []
        for i, center in enumerate(points):
            axis = (points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]).normalized()
            u = axis.cross(OUT).normalized()
            v = axis.cross(u)
            rings.append(self.add((center + radius * (math.cos(math.tau * j / count) * u
                                                       + math.sin(math.tau * j / count) * v)
                                   for j in range(count)), [], skin, surface))
        self.record(tuple(reversed(range(rings[0], rings[0] + count))), surface)
        for start, end in zip(rings, rings[1:]):
            self.join(start, end, count, surface, True)
        self.record(tuple(range(rings[-1], rings[-1] + count)), surface)

    def emit(self, name, part, collection, rig, materials):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update()
        if self.sharp_edges:
            for edge in mesh.edges:
                edge.use_edge_sharp = tuple(sorted(edge.vertices)) in self.sharp_edges
        for material in materials.values():
            mesh.materials.append(material)
        slots = {surface: i for i, surface in enumerate(materials)}
        for polygon, surface, smooth in zip(mesh.polygons, self.surfaces, self.smooth):
            polygon.material_index = slots[surface]
            polygon.use_smooth = smooth
        uv = mesh.uv_layers.new(name="V5_BandUV")
        for polygon_index, coords in self.band_coordinates.items():
            for loop_index, point in zip(mesh.polygons[polygon_index].loop_indices, coords):
                uv.uv[loop_index].vector = point
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj["part"] = part
        if part == "leg_plates":
            attribute = mesh.attributes.new("armor_component", "INT", "FACE")
            attribute.data.foreach_set("value", self.armor_components)
            inner = mesh.attributes.new("v5c_inner", "INT", "FACE")
            markers = [0] * len(mesh.polygons)
            for component, indices in self.inner_faces.items():
                for index in indices:
                    markers[index] = component
            inner.data.foreach_set("value", markers)
            for component, pairs in self.depth_pairs.items():
                obj[f"panel_depth_pairs_{component}"] = pairs
                if component in getattr(self, "local_depth", {1}):
                    obj[f"panel_depth_local_{component}"] = True
                obj[f"panel_depth_{component}"] = ((self.side, 0, 0)
                                                    if component == 2 else (0, -1, 0))
        prefix = "L" if self.side > 0 else "R"
        groups = {}
        for i, weights in enumerate(self.weights):
            if part == "leg_plates":
                # Newly fitted supports interpolate abbreviated and full EFT names.
                # Merge aliases before assigning Blender groups with REPLACE.
                canonical = {}
                for suffix, weight in weights.items():
                    name = suffix if suffix.startswith("Base Human") else f"Base Human{prefix}{suffix}"
                    canonical[name] = canonical.get(name, 0.) + weight
                if len(canonical) != len(weights) or abs(sum(canonical.values()) - 1.) > 1e-6:
                    strongest = sorted(canonical.items(), key=lambda entry: -entry[1])[:4]
                    total = sum(weight for _, weight in strongest)
                    weights = {name: weight / total for name, weight in strongest}
            for suffix, weight in weights.items():
                if weight > 0:
                    group_name = (suffix if suffix.startswith("Base Human")
                                  else f"Base Human{prefix}{suffix}")
                    if group_name not in groups:
                        if group_name not in rig.data.bones:
                            raise KeyError(f"Missing bone {group_name} for {obj.name}")
                        groups[group_name] = obj.vertex_groups.new(name=group_name)
                    groups[group_name].add([i], weight, 'REPLACE')
        modifier = obj.modifiers.new("EFT skin", 'ARMATURE')
        modifier.object = rig
        return obj


class TrouserSkin:
    """Interpolate native cloth weights so the nylon follows the garment."""
    def __init__(self, trousers, rig):
        mesh = trousers.data
        mesh.calc_loop_triangles()
        self.points = [trousers.matrix_world @ vertex.co for vertex in mesh.vertices]
        self.faces = [tuple(tri.vertices) for tri in mesh.loop_triangles]
        self.index = BVHTree.FromPolygons(self.points, self.faces, all_triangles=True)
        self.groups = []
        names = [group.name for group in trousers.vertex_groups]
        for vertex in mesh.vertices:
            self.groups.append({names[g.group]: g.weight for g in vertex.groups
                                if g.weight > 0 and names[g.group] in rig.data.bones
                                and rig.data.bones[names[g.group]].use_deform})

    def radial(self, x, y, z, dx, dy):
        """Measure a stable mirrored envelope from the rendered garment."""
        samples = []
        for side in (1, -1):
            origin = Vector((side * x, y, z))
            axis = Vector((side * dx, dy, 0))
            point, _, _, distance = self.index.ray_cast(origin, axis, .175)
            if point is not None:
                samples.append(distance)
        return max(samples, default=None)

    def weights(self, point):
        nearest, _, triangle, _ = self.index.find_nearest(Vector(point))
        face = self.faces[triangle]
        basis = (OUT, Vector((0, 1, 0)), UP)
        factors = barycentric_transform(nearest, *(self.points[index] for index in face),
                                        *basis)
        combined = {}
        for index, factor in zip(face, factors):
            for name, weight in self.groups[index].items():
                combined[name] = combined.get(name, 0) + max(0, factor) * weight
        strongest = sorted(combined.items(), key=lambda pair: -pair[1])[:4]
        total = sum(weight for name, weight in strongest)
        return {name: weight / total for name, weight in strongest if weight > 0}


HIP = {"Thigh1": 1.0}
THIGH = {"Thigh1": .44, "Thigh2": .56}
LOW_THIGH = {"Thigh1": .14, "Thigh2": .86}
CALF = {"Calf": 1.0}
FOOT = {"Foot": 1.0}
KNEE = {"Thigh2": .57, "Calf": .43}


def shin_weight(p):
    blend = max(0.0, min(1.0, (.205 - p[2]) / .127)) * .64
    return {"Calf": 1 - blend, "Foot": blend}


def front(x, z, y, slope, twist, crown):
    def project(u, v, depth):
        return (x + u + twist * v, y + slope * v + crown * u * u - depth, z + v)
    return project


def outer(x, z, y, slope, crown):
    def project(u, v, depth):
        return (x + slope * v - crown * u * u + depth, y + u, z + v)
    return project


def cut_box(half_u, half_v, clip):
    u, v = half_u, half_v
    return [(-u + clip, -v), (u - clip, -v), (u, -v + clip), (u, v - clip),
            (u - clip, v), (-u + clip, v), (-u, v - clip), (-u, -v + clip)]


CUFFS_LEFT = (
    ((.114,.114,.116,.124,.129,.131,.103,.091,.09,.1,.115,.119,.131,.129,.142,.13),
     (.114,.113,.109,.122,.135,.138,.103,.090,.09,.1,.125,.123,.132,.128,.136,.129)),
    ((.103,.107,.099,.102,.109,.114,.111,.105,.101,.103,.105,.103,.097,.101,.106,.107),
     (.098,.097,.099,.11,.119,.126,.122,.115,.108,.105,.109,.109,.105,.105,.1,.1)),
    ((.098,.097,.093,.088,.08,.081,.089,.106,.101,.096,.088,.087,.092,.095,.097,.1),
     (.095,.087,.078,.079,.081,.087,.086,.093,.1,.101,.101,.108,.102,.103,.098,.097)),
    ((.087,.091,.094,.092,.086,.083,.075,.066,.065,.066,.068,.073,.079,.078,.076,.079),
     (.082,.08,.078,.078,.075,.071,.071,.068,.064,.068,.075,.082,.092,.09,.084,.082)),
    ((.085,.082,.085,.088,.085,.073,.06,.053,.052,.054,.06,.073,.098,.117,.109,.095),
     (.074,.072,.075,.086,.086,.074,.059,.048,.048,.049,.057,.069,.078,.09,.087,.078)),
)

CUFFS_RIGHT = (
    ((.144,.11,.101,.102,.104,.105,.107,.092,.089,.093,.105,.11,.115,.12,.127,.132),
     (.147,.104,.10,.106,.117,.135,.108,.092,.089,.093,.116,.114,.118,.121,.126,.139),
    ),
    ((.105,.107,.106,.105,.109,.106,.113,.106,.096,.096,.096,.094,.094,.095,.102,.099),
     (.098,.101,.099,.106,.107,.108,.108,.105,.103,.105,.102,.103,.10,.102,.108,.101)),
    ((.089,.091,.096,.095,.093,.093,.096,.099,.10,.094,.089,.087,.088,.09,.093,.092),
     (.099,.097,.088,.083,.081,.085,.095,.099,.103,.105,.103,.109,.11,.108,.10,.101)),
    ((.082,.087,.095,.101,.099,.094,.088,.08,.073,.069,.067,.07,.075,.085,.084,.081),
     (.076,.076,.08,.09,.088,.085,.082,.08,.077,.08,.083,.089,.091,.086,.078,.076)),
    ((.082,.08,.083,.084,.079,.071,.059,.053,.051,.054,.06,.075,.106,.12,.109,.094),
     (.067,.069,.075,.081,.084,.08,.065,.054,.049,.049,.059,.073,.087,.089,.083,.075)),
)


def curved_panel(geo, project, rows, skin, face, thickness, bevel, screws=()):
    """Loft a constant-thickness clipped panel and keep the crown smooth."""
    columns = 3 if geo.lod else (4 if face in ("webbing", "rubber") else 5)
    count = len(rows)
    stride = columns + 1
    # Traverse the perimeter counter-clockwise in panel coordinates.
    boundary = (list(range(stride))
                + [row * stride + columns for row in range(1, count)]
                + list(range(count * stride - 2, (count - 1) * stride - 1, -1))
                + [row * stride for row in range(count - 2, 0, -1)])

    def grid(inset):
        for row, (v, left, right) in enumerate(rows):
            v += inset if row == 0 else -inset if row == count - 1 else 0
            for column in range(stride):
                weight = column / columns
                yield (left + inset + weight * (right - left - 2 * inset), v)

    coordinates = list(grid(0))
    face_coordinates = list(grid(bevel))
    fitted_back = geo.armor_component == 1
    back = geo.add((project(*coordinates[i], -thickness) for i in boundary),
                   [] if fitted_back else [tuple(reversed(range(len(boundary))))],
                   skin, face)
    if fitted_back:
        back_skin = geo.add((project(u, v, -thickness) for u, v in face_coordinates),
                            [], skin, face)
    side = geo.add((project(*coordinates[i], -bevel) for i in boundary), [], skin, face)
    top = geo.add((project(u, v, 0) for u, v in face_coordinates), [], skin, face)
    rim = "edge" if face == "khaki" else face
    if fitted_back:
        geo.depth_pairs[1] = [index for i in range(len(face_coordinates))
                              for index in (back_skin + i, top + i)]
    elif geo.armor_component in (2, 4, 5):
        geo.depth_pairs[geo.armor_component] = [index for j, i in enumerate(boundary)
                                                for index in (back + j, top + i)]
    for j, i in enumerate(boundary):
        k = (j + 1) % len(boundary)
        neighbor = boundary[k]
        if fitted_back:
            geo.record((back + k, back + j, back_skin + i, back_skin + neighbor), face)
        geo.record((back + j, back + k, side + k, side + j), face)
        geo.record((side + j, side + k, top + neighbor, top + i), rim)

    cells = []
    for row in range(count - 1):
        for column in range(columns):
            i = row * stride + column
            cells.append((i, i + 1, i + 1 + stride, i + stride))

    def midpoint(cell):
        return tuple(sum(face_coordinates[j][axis] for j in cell) / 4 for axis in (0, 1))

    perforated = {}
    for u, v in screws[:2] if geo.lod else screws:
        cell = min((item for item in cells if item not in perforated),
                   key=lambda item: math.dist(midpoint(item), (u, v)))
        perforated[cell] = midpoint(cell)

    for cell in cells:
        if fitted_back:
            geo.record(tuple(back_skin + j for j in reversed(cell)), face)
        vertices = tuple(top + j for j in cell)
        if cell not in perforated:
            geo.record(vertices, face, True)
            continue
        center = perforated[cell]
        corners = [face_coordinates[i] for i in cell]
        radius = min(.0063, min(
            abs((q[0] - p[0]) * (p[1] - center[1]) - (p[0] - center[0]) * (q[1] - p[1]))
            / math.dist(p, q)
            for p, q in zip(corners, corners[1:] + corners[:1])) * .81)
        counterbore(geo, vertices, corners, center, radius, project, skin, face)


def counterbore(geo, vertices, corners, center, radius, project, skin, surface):
    """Real blind bore milled into the panel, with a recessed socket screw."""
    cx, cy = center
    angles = []
    for p, q in zip(corners, corners[1:] + corners[:1]):
        angles.append(math.atan2(p[1] - cy, p[0] - cx))
        if not geo.lod:
            angles.append(math.atan2((p[1] + q[1]) * .5 - cy, (p[0] + q[0]) * .5 - cx))

    count = len(angles)
    mouth = geo.add((project(cx + radius * math.cos(a), cy + radius * math.sin(a), 0)
                     for a in angles), [], skin, surface)
    for i, vertex in enumerate(vertices):
        next_vertex = vertices[(i + 1) % 4]
        if geo.lod:
            geo.record((vertex, next_vertex, mouth + (i + 1) % 4, mouth + i), surface, True)
        else:
            first = mouth + i * 2
            last = mouth + (i * 2 + 2) % count
            geo.record((vertex, next_vertex, last, first + 1), surface, True)
            geo.record((vertex, first + 1, first), surface, True)

    floor = geo.add((project(cx + radius * .91 * math.cos(a),
                             cy + radius * .91 * math.sin(a), -.004)
                     for a in angles), [], skin, surface)
    geo.join(mouth, floor, count, "edge" if surface == "khaki" else "gunmetal")
    geo.record(tuple(range(floor, floor + count)), "gunmetal")
    axis = (Vector(project(cx, cy, .001)) - Vector(project(cx, cy, 0))).normalized()
    if geo.lod:
        geo.disc(project(cx, cy, -.0032), axis, radius * .71, .0014, skin, "steel", 5)
    else:
        geo.hex_recess(project(cx, cy, -.0041), axis, radius * .76, .0032, skin)


def fitted_cuff(geo, index, x, y, z, width, skin, tuck=0):
    """Use one mirrored strap envelope fitted around both native trouser legs."""
    # The right and left cloth folds differ slightly. One envelope contains both.
    contours = tuple(tuple(max(left, right) for left, right in zip(a, b))
                     for a, b in zip(CUFFS_LEFT[index], CUFFS_RIGHT[index]))
    geo.cuff(x, y, z, width, contours, skin, tuck)


def sole(geo):
    """Full outsole with rounded welt, recessed arch, and molded tread blocks."""
    geo.armor_component = 6
    profile = [
        (.178, -.128), (.195, -.168), (.221, -.184), (.254, -.184),
        (.280, -.166), (.292, -.140), (.300, -.097), (.299, -.061),
        (.288, -.031), (.277, .011), (.266, .052), (.260, .084),
        (.228, .115), (.193, .123), (.169, .113), (.146, .085),
        (.147, .044), (.159, .006), (.171, -.032), (.165, -.075),
        (.171, -.104),
    ]

    def arch(y):
        return .011 * max(0.0, 1 - abs(y + .004) / .060)

    points = profile[::2] if geo.lod else profile
    rings = []
    profile_z = ((-.009, .96, 1), (.008, 1, .3), (.031, .98, 0)) if geo.lod else (
        (-.009, .95, 1), (-.004, 1, .8), (.017, 1, .1),
        (.024, .983, 0), (.028, 1, 0), (.032, .971, 0))
    for z, scale, arch_scale in profile_z:
        rings.append(geo.add(((.219 + (x - .219) * scale, -.030 + (y + .030) * scale,
                               z + arch_scale * arch(y)) for x, y in points),
                             [], FOOT, "rubber"))
    for i, (start, end) in enumerate(zip(rings, rings[1:])):
        geo.join(start, end, len(points), "dark" if not geo.lod and i == 3 else "rubber")
    geo.record(tuple(reversed(range(rings[0], rings[0] + len(points)))), "rubber")
    geo.record(tuple(range(rings[-1], rings[-1] + len(points))), "rubber")

    def tread_block(half_width, half_length, clip, mount, depth, underside=False):
        if not geo.lod and not underside:
            geo.shell(cut_box(half_width, half_length, clip), mount, FOOT, "rubber", depth, .003)
            return
        # Underfoot cleats have raked ends. The distant mesh keeps each cleat's
        # full length and height, with four corners at the ground contact patch.
        w, h = half_width, half_length
        rim = ((-w, -h), (w, -h), (w, h), (-w, h)) if geo.lod else (
            (-w + clip, -h), (w, -h), (w, h - clip),
            (w - clip, h), (-w, h), (-w, -h + clip),
        )
        order = tuple(range(len(rim)))
        base = geo.add((mount(u, v, -depth) for u, v in rim), [tuple(reversed(order))], FOOT, "rubber")
        top = geo.add((mount(u, v, 0) for u, v in rim), [order], FOOT, "rubber")
        geo.join(base, top, len(rim), "rubber")

    # Outboard lugs straddle the wall and footprint, leaving clear tread channels.
    rows = (1, 3, 5, 7, 10, 12, 14, 16, 18, 20) if geo.lod else range(len(profile))
    for i in rows:
        start = Vector(profile[i])
        end = Vector(profile[(i + 1) % len(profile)])
        center = (start + end) * .5
        side = (end - start).normalized()
        inward = Vector((-side.y, side.x))
        z = -.017 + arch(center.y) * .85

        def mount(u, v, depth):
            point = center + u * side - (v-.005) * inward
            return point.x, point.y, z - depth

        width = min(.022, (start-end).length * .78) * .5
        tread_block(width, .012, .003, mount, .017)

    # Two staggered rows of chevrons underneath heel and forefoot.
    for row, (y, center) in enumerate(((-.150, .234), (-.119, .232), (-.085, .232),
                                       (-.056, .228), (.039, .202), (.068, .202), (.092, .201))):
        if geo.lod and row in (1, 4, 6):
            continue
        for side in (-1, 1):
            def mount(u, v, depth):
                return center + side * .018 + u, y - v + side * .38 * u, -.017 - depth

            tread_block(.016, .011, .004, mount, .014, underside=True)


def knee_cop(geo):
    """Deep octagonal shell with a clean, inset face and broad crown bevel planes."""
    geo.armor_component = 3
    def project(u, v, depth):
        # Shingle-like nose and an upper flare leave room for the thigh tip.
        lod_clearance = .010 * max(0, min(1, (v - .025) / .045)) if geo.lod else 0
        return (.150 + u - .075 * v, -.169 - .28 * max(v, 0)
                + .10 * min(v, 0) + 1.55 * u * u - depth - lod_clearance, .524 + v)
    contour = ((-.039,-.076), (.037,-.076), (.061,-.049), (.068,.046),
               (.044,.080), (-.041,.079), (-.065,.048), (-.060,-.050))
    # The face tapers in both axes, leaving the hard sloping shoulders readable in profile.
    layers = ((.94, -.019), (1., -.016), (.99, -.012), (.78, -.003), (.69, 0))
    if geo.lod:
        layers = (layers[0], layers[1], layers[3], layers[4])
    rings = []
    for scale, depth in layers:
        rings.append(geo.add((project(u * scale, v * scale, depth) for u, v in contour),
                             [], KNEE, "khaki"))
    inner = geo.add((project(0, 0, -.0153),), [], KNEE, "khaki")
    for j in range(8):
        geo.record((inner, rings[0] + (j + 1) % 8, rings[0] + j), "khaki")
    for i, (start, end) in enumerate(zip(rings, rings[1:])):
        geo.join(start, end, 8, "edge" if i == len(rings) - 3 else "khaki")

    top = tuple(range(rings[-1], rings[-1] + 8))
    ridge = geo.add((project(-.037, .026, .002), project(.039, .025, .002)),
                    [], KNEE, "khaki")
    geo.record((top[0], top[1], top[2], ridge + 1, ridge, top[7]), "khaki")
    geo.record((top[2], top[3], ridge + 1), "khaki")
    geo.record((top[3], top[4], top[5], top[6], ridge, ridge + 1), "khaki")
    geo.record((top[6], top[7], ridge), "khaki")
    geo.depth_pairs[3] = [index for j in range(8) for index in (rings[0] + j, rings[-1] + j)]
    for sign in (-1, 1):
        for v in ((.044,) if geo.lod else (-.033, .045)):
            u = sign * (.052 if v > 0 else .050)
            axis = Vector((sign * .72, -.59, .09))
            if geo.lod:
                geo.disc(project(u, v, -.018), axis, .005, .004, KNEE, "gunmetal", 6)
            else:
                geo.hex_recess(project(u, v, -.019), axis, .006, .004, KNEE, close_base=True)


def blend_skin(geo, point, base, compliance):
    if compliance == 0 or geo.cuff_fit is None:
        return base
    x, y, z = point
    native = geo.cuff_fit.weights((geo.side * x, y, z))
    prefix = "Base HumanL" if geo.side > 0 else "Base HumanR"
    mixed = {name: weight * compliance for name, weight in native.items()}
    for name, weight in base.items():
        name = prefix + name
        mixed[name] = mixed.get(name, 0) + weight * (1 - compliance)
    highest = sorted(mixed.items(), key=lambda pair: -pair[1])[:4]
    total = sum(weight for _, weight in highest)
    return {name: weight / total for name, weight in highest if weight}


def boot_armor(geo):
    geo.armor_component = 5
    cuff = Wrap(geo.cuff_fit, ((.078, .222, .006, .101), (.116, .215, .015, .104),
                              (.155, .202, .022, .079)),
                ((.098, .014, .009, -36, 49), (.105, .012, .009, -48, 62),
                 (.117, .008, .010, -55, 69), (.124, .006, .008, -50, 62)),
                lambda u, z: .033 + .004 * abs(u - .5))
    def cuff_face(u, v, depth):
        point = cuff.project(u, v, depth)
        point.y += .010
        point.z += (.007 * max(0, min(1, (v - .110) / .014))
                    * max(0, 1 - u / .63))
        point.z -= .022 * max(0, (u - .53) / .47)
        point.z += .003 * max(0, 1 - abs(u - .43) / .30)
        point.y -= .006 * max(0, 1 - abs(u - .49) / .29)
        wing_contact = .016 if geo.lod else .021
        point.x -= wing_contact * max(0, (u - .62) / .38)
        point.x -= .012 * max(0, 1 - abs(u - .19) / .30)
        return point

    def cuff_skin(p):
        compliance = .65 * max(0, min(1, (.217 - p[0]) / .029))
        return blend_skin(geo, p, FOOT, compliance)

    shell_grid(geo, cuff_face,
               [i / 10 for i in range(11)] if not geo.lod else [i / 5 for i in range(6)],
               [.098, .105, .115, .120, .124],
               cuff_skin, .014)

    geo.armor_component = 7
    profiles = (
        (-.184, .235, .031, .076, .004),
        (-.175, .235, .044, .093, .011),
        (-.161, .234, .050, .111, .017),
        (-.145, .232, .052, .117, .021),
        (-.127, .230, .047, .125, .024),
        (-.118, .232, .029, .124, .024),
    )

    def instep(u, v, depth):
        center, half, crown, shoulder = between(profiles, v)
        width = 2 * u - 1
        toe = max(0, min(1, (-v - .15) / .032))
        setback = toe * .011 * abs(width)**3
        lod_clearance = (.006 * max(0, width) + .015 * toe) if geo.lod else 0
        lod_cutback = .004 * max(0, (v + .13) / .013) if geo.lod else 0
        return (center + half * width, v + .045 * half * width + setback - lod_cutback,
                crown - shoulder * abs(width)**3 + depth + lod_clearance)

    shell_grid(geo, instep,
               [i / 8 for i in range(9)] if not geo.lod else [i / 6 for i in range(7)],
               [row[0] for row in profiles], FOOT, .014)
    sole(geo)


def pressed_rib(u, v, center, half_width, low, high, ramp, height):
    """Taper a pressed bead into its parent plate without a separate overlay."""
    across = max(0, min(1, (half_width - abs(u - center)) / (half_width * .65)))
    along = max(0, min(1, (v - low) / ramp, (high - v) / ramp))
    return height * across * along


def make_plates(geo):
    import v5c_boot
    import v5c_knee
    import v5c_shin
    import v5c_thigh

    v5c_thigh.build(geo)
    v5c_knee.build(geo)
    v5c_shin.build(geo)
    v5c_boot.build(geo)
    sole(geo)
    geo.armor_component = 0


def webbing_buckle(geo, project, skin, scale=1):
    """Hollow chamfered frame, moving pin and a threaded, folded strap tail."""
    def mount(u, v, depth):
        return project(u * scale, v * scale, depth * scale)

    outer_ring = cut_box(.020, .017, .004)
    inner_ring = cut_box(.013, .0105, .003)
    if geo.lod:
        outer_ring = outer_ring[::2]
        inner_ring = inner_ring[::2]
    count = len(outer_ring)
    rings = [geo.add((mount(u*factor, v*factor, depth) for u, v in profile),
                     [], skin, "gunmetal")
             for profile, factor, depth in
             ((outer_ring, .96, -.008), (outer_ring, 1, -.006),
              (outer_ring, .94, .001), (inner_ring, 1, .001),
              (inner_ring, .96, -.008))]
    for i, (start, end) in enumerate(zip(rings, rings[1:] + rings[:1])):
        geo.join(start, end, count, "steel_edge" if i in (1, 2) else "gunmetal")

    for u, v, half_u, half_v, depth, thickness, material in (
        (0, 0, .0027, .012, .0014, .004, "steel"),
        (0, -.007, .015, .018, -.004, .003, "webbing"),
        (.000, .024, .014, .012, -.005, .003, "band"),
    ):
        def local_project(du, dv, d):
            return mount(u + du, v + dv, d + depth)

        geo.shell(cut_box(half_u, half_v, min(.003, half_u*.5)), local_project,
                  skin, material, thickness, .001)


def _materials():
    from finish import flat_material, material
    names = {"khaki": "plate", "khaki_dark": "plate", "gunmetal": "frame",
             "steel": "steel", "webbing": "strap", "dark": "black",
             "yellow": "yellow", "edge": "edge", "band": "band",
             "steel_edge": "steel_edge", "rubber": "rubber"}
    result = {key: material(name) for key, name in names.items()}
    result["knee_chamfer"] = flat_material("V5 | Knee cop bevels", (.035, .037, .038), .65)
    result["knee_crown"] = flat_material("V5 | Knee cop crown", (.040, .042, .042), .65)
    return result


def build(lod, collection, rig):
    """Build mirrored leg shields and frames at LOD0 or LOD1."""
    from lower_frame import make_frame
    from v5c_fit import refine
    from v5c_mate import mate
    from v5c_mounts import fit_standoffs
    from v5c_reduce import reduce

    materials = _materials()
    objects = []
    trousers = bpy.data.objects.get("REF_pants")
    trouser_skin = TrouserSkin(trousers, rig) if trousers is not None else None
    fitted_trousers = next((obj for obj in collection.objects
                            if obj.name.startswith(f"Undersuit | Combat trousers LOD{lod}")), None)
    cuff_fit = TrouserSkin(fitted_trousers, rig) if fitted_trousers is not None else None
    boots = bpy.data.objects[f"Undersuit | Combat boots LOD{lod}"]
    boot_fit = TrouserSkin(boots, rig)
    mount_file = Path(__file__).resolve().parent.parent / "source" / "leg_frame_mounts.json"
    with mount_file.open(encoding="utf-8") as stream:
        accepted_mounts = json.load(stream)
    for side, label in ((1, "L"), (-1, "R")):
        # Frame and armor use separate objects for reporting and tuning.
        plates = Geometry(side, lod, trouser_skin, cuff_fit)
        frame = Geometry(side, lod)
        plates.boot_fit = boot_fit
        make_plates(plates)
        # Keep the accepted frame's original bracket positions through armor revisions.
        anchors = accepted_mounts[f"{lod},{side}"]
        frame.mounts = {part: (lambda y, z, table=points: table[f"{y:.9f},{z:.9f}"])
                        for part, points in anchors.items()}
        fit_standoffs(plates, frame.mounts)
        # Reserve the tread savings for the new worn armor, keeping the
        # existing non-tread tessellation budget at each distance.
        reduce(plates, 5246 if lod == 0 else 3246)
        refine(plates)
        mate(plates)
        make_frame(frame, frame)
        objects.append(plates.emit(f"LegArmour_{label}_LOD{lod}", "leg_plates",
                                   collection, rig, materials))
        frame_obj = frame.emit(f"LegFrame_{label}_LOD{lod}", "leg_frame",
                               collection, rig, materials)
        frame_obj["frame_nodes"] = json.dumps(getattr(frame, "frame_nodes", {}))
        objects.append(frame_obj)
    return objects


