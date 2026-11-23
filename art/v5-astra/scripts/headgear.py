"""V5 helmet, visor and removable thermal unit on the EFT bind model."""

from collections import defaultdict
import json
from math import cos, pi, sin, tau
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from finish import flat_material as material

HEAD_ANCHOR = Vector((-.00062798, .02180314, 1.65807902))
NECK = "Base HumanNeck"
# Prior accessory pipeline converts Blender (x,y,z) into Unity (-x,z,-y).
TO_BLENDER = Matrix(((-1, 0, 0), (0, 0, -1), (0, 1, 0)))
SLOTS = {
    "mod_nvg": ((7.103704433575331e-7, .13487572968006134, .14867863059043884),
                (.8779819011688232, 0, 0, -.4786938428878784), (1, 1, 1)),
    "mod_equipment_001": ((0, .004999999888241291, -.04500000178813934),
                          (-.6018150448799133, 0, 0, .7986355423927307), (1.26, 1, 1)),
}


def surfaces():
    return {
        "crown": material("Helmet | graphite laminate", (.029, .031, .033), .69),
        "top": material("Helmet | khaki applique", (.079, .069, .050), .68),
        "cut": material("Helmet | chamfered khaki edges", (.092, .081, .059), .66),
        "rail": material("Helmet | charcoal ARC hardware", (.030, .031, .030), .69, .22),
        "hard": material("Helmet | black mandible composite", (.018, .019, .020), .72),
        "panel": material("Helmet | black ear armor", (.022, .023, .025), .66),
        "rubber": material("Helmet | molded black rubber", (.013, .014, .015), .77),
        "fabric": material("Helmet | black balaclava", (.011, .012, .013), .90),
        "dark": material("Helmet | hardware recesses", (.009, .010, .011), .59, .18),
        "bolt": material("Helmet | blackened steel fasteners", (.060, .064, .067), .43, .48),
        "glass": material("Helmet | smoked black visor", (.009, .011, .014), .31, specular=.17),
        "optic": material("Thermal | coated germanium", (.027, .052, .042), .19, .32),
    }


class Headgear:
    def __init__(self, lod, collection, rig):
        self.low = bool(lod)
        self.collection = collection
        self.rig = rig
        self.materials = surfaces()
        self.objects = []
        self.part = "helmet"

    def add(self, name, points, faces, keys, indices=None, smooth=False):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(points, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        self.collection.objects.link(obj)
        for key in keys:
            mesh.materials.append(self.materials[key])
        for poly in mesh.polygons:
            poly.use_smooth = smooth
            if indices is not None:
                poly.material_index = indices[poly.index]
        obj["part"] = self.part
        if self.part == "thermal":
            obj["optional"] = True
        self.objects.append(obj)
        return obj

    def skin(self, obj):
        if not obj.vertex_groups:
            vg = obj.vertex_groups.new(name=NECK)
            vg.add(list(range(len(obj.data.vertices))), 1, "REPLACE")
        mod = obj.modifiers.new("EFT bind", "ARMATURE")
        mod.object = self.rig

    def socket(self, name):
        position, rotation, scale = SLOTS[name]
        rotation = Quaternion((rotation[3], *rotation[:3])).normalized()
        world = (TO_BLENDER @ rotation.to_matrix() @ Matrix.Diagonal(Vector(scale))
                 @ TO_BLENDER.transposed()).to_4x4()
        world.translation = HEAD_ANCHOR + TO_BLENDER @ Vector(position)
        empty = bpy.data.objects.new(name, None)
        self.collection.objects.link(empty)
        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = .024
        empty["native_donor"] = "EFT 40743 item_equipment_helmet_hops_core_fast"
        empty.parent = self.rig
        empty.parent_type = "BONE"
        empty.parent_bone = NECK
        bpy.context.view_layer.update()
        empty.matrix_world = world
        return empty

    def shell(self):
        # Keep the donor's high-cut laminate. Exterior rail hardware has its own mesh.
        source = Path(__file__).resolve().parents[1] / "source" / "fast_shell_geometry.json"
        donor = json.loads(source.read_text(encoding="utf-8"))
        p = [(HEAD_ANCHOR.x - x * 1.055, HEAD_ANCHOR.y + y, HEAD_ANCHOR.z + z)
             for x, y, z in donor["positions"]]
        group = donor["groups"][0]
        used = sorted(set(group))
        lookup = {old: new for new, old in enumerate(used)}
        faces = [tuple(lookup[group[i + j]] for j in (0, 2, 1))
                 for i in range(0, len(group), 3)]
        obj = self.add("FAST | high-cut laminate shell", [p[i] for i in used], faces,
                       ["crown"], smooth=True)
        obj["native_donor"] = donor["source"]
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.00006)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        if self.low:
            decimate = obj.modifiers.new("Secondary ballistic silhouette", "DECIMATE")
            decimate.ratio = .60
            depsgraph = bpy.context.evaluated_depsgraph_get()
            reduced = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
            original = obj.data
            obj.modifiers.remove(decimate)
            obj.data = reduced
            bpy.data.meshes.remove(original)
        shell = obj.data
        shell.set_sharp_from_angle(angle=.70)
        return BVHTree.FromPolygons([v.co for v in shell.vertices],
                                    [tuple(f.vertices) for f in shell.polygons])

    def extrusion(self, name, perimeter, depth, bevel, key, edge=None):
        perimeter = [Vector(q) for q in perimeter]
        depth = Vector(depth)
        center = sum(perimeter, Vector()) / len(perimeter)
        inner = [q + (center - q).normalized() * bevel for q in perimeter]
        rings = [[q + depth for q in perimeter], perimeter, inner] if bevel else [
            [q + depth for q in perimeter], perimeter]
        count = len(perimeter)
        faces = [tuple(reversed(range(count)))]
        material_ids = [0]
        for row in range(len(rings)-1):
            for i in range(count):
                j = (i + 1) % count
                start, end = row * count, (row + 1) * count
                faces.append((start + i, start + j, end + j, end + i))
                material_ids.append(int(edge is not None and row == 1))
        faces.append(tuple(range((len(rings)-1) * count, len(rings) * count)))
        material_ids.append(0)
        obj = self.add(name, sum(rings, []), faces, [key, edge] if edge else [key], material_ids)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        return obj

    def box(self, name, center, size, key, edge=None, axis="Y", chamfer=.002, bevel=.0015):
        a, b, d = size[0] / 2, size[1] / 2, size[2]
        corners = [(-a+chamfer,-b), (a-chamfer,-b), (a,-b+chamfer),
                   (a,b-chamfer), (a-chamfer,b), (-a+chamfer,b),
                   (-a,b-chamfer), (-a,-b+chamfer)]
        offsets = {"Y": lambda u, v: (u, -d/2, v),
                   "Z": lambda u, v: (u, v, d/2)}
        pts = [Vector(center) + Vector(offsets[axis](u,v)) for u,v in corners]
        direction = (0,d,0) if axis == "Y" else (0,0,-d)
        return self.extrusion(name, pts, direction, bevel if not self.low else 0, key, edge)

    def screw(self, name, point, normal, radius=.0045, drive=False):
        tip = Vector(point)
        normal = Vector(normal).normalized()
        reference = Vector((0, 0, 1) if abs(normal.z) < .96 else (0, 1, 0))
        u = normal.cross(reference).normalized()
        v = normal.cross(u).normalized()
        count = 8 if self.low else 12

        def circle(center, scale):
            return [center + scale * radius * (u*cos(tau*i/count) + v*sin(tau*i/count))
                    for i in range(count)]

        if drive:
            self.extrusion(name + " | seating collar", circle(tip-normal*.0019, 1.21),
                           -normal*.0018, 0 if self.low else .0005, "dark")
        self.extrusion(name, circle(tip, 1), -normal*.0022,
                       .0006, "bolt", "rail")
        if drive and not self.low:
            tip += normal * .00012
            points = [tip + u*x*radius + v*y*radius
                      for x,y in ((-.57,-.13),(.57,-.13),(.57,.13),(-.57,.13))]
            self.add(name + " | slot", points, [(0,1,2,3)], ["dark"])

    def sheet(self, name, rings, key, closed=False, smooth=True, loop=False):
        count = len(rings[0])
        faces = [(k*count+i, k*count+j, l*count+j, l*count+i)
                 for k in range(len(rings) if loop else len(rings)-1)
                 for l in ((k+1) % len(rings),)
                 for i in range(count if closed else count-1) for j in ((i+1)%count,)]
        return self.add(name, sum(rings, []), faces, [key], smooth=smooth)

    def solid_strip(self, name, inner, surface, key, bevel_key=None, smooth=False):
        # The outer bevel uses four profile stations, while the hidden back needs only two.
        count = len(surface[0])
        width = len(surface)
        grid = width * count
        faces = []
        materials = []
        for layer in (0, grid):
            for row in (range(width - 1) if layer else (0,)):
                for column in range(count - 1):
                    i = layer + row * count + column
                    stride = count if layer else (width - 1) * count
                    face = (i, i + 1, i + stride + 1, i + stride)
                    faces.append(face if layer else face[::-1])
                    materials.append(int(bool(layer and bevel_key and row in (0, width-2))))
        for row in (0, width-1):
            for column in range(count-1):
                i = row * count + column
                face = (i, i + grid, i + grid + 1, i + 1)
                faces.append(face if row == 0 else face[::-1])
                materials.append(int(bool(bevel_key)))
        for column in (0, count-1):
            face = (column, column + (width - 1) * count,
                    *(grid + column + row * count for row in range(width-1, -1, -1)))
            faces.append(face if column == 0 else face[::-1])
            materials.append(int(bool(bevel_key)))
        obj = self.add(name, sum(inner, []) + sum(surface, []), faces,
                       [key, bevel_key] if bevel_key else [key], materials)
        if smooth:
            for polygon, material_index in zip(obj.data.polygons, materials):
                polygon.use_smooth = material_index == 0
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        return obj

    def crown_panels(self, tree):
        origin = Vector((HEAD_ANCHOR.x, -.004, 1.719))
        steps = 7 if self.low else 20

        def project(ray, height):
            p, _, _, _ = tree.ray_cast(origin + ray * .4, -ray, .40)
            if p is None:
                raise RuntimeError(f"Applique projection missed FAST crown: {ray}")
            return p + ray * height

        # A true sweep runs from the brow to the elevated rail seat. Its lower
        # flange stands clear of the shell edge and visor gasket across the front.
        def brim(az, elevation, height):
            return project(Vector((sin(az)*cos(elevation), -cos(az)*cos(elevation),
                                   sin(elevation))), height)

        stops = ((.006, .242, .28), (.30, .243, .29), (.55, .250, .27),
                 (.80, .260, .24), (1.01, .277, .237), (1.14, .360, .245),
                 (1.28, .395, .222), (1.42, .412, .190))
        samples = []
        for left, right in zip(stops, stops[1:]):
            subdivisions = 1 if self.low else 3
            samples.extend(tuple(a + (b-a)*i/subdivisions for a,b in zip(left,right))
                           for i in range(subdivisions))
        samples.append(stops[-1])
        for side in (-1, 1):
            overlap = 1 if self.low else 3
            straights = (
                ("brow", samples[:3*overlap+1], .002, 0),
                ("temple", samples[3*overlap:], -.001, .006),
            )
            for name, stations, standoff, seam in straights:
                base, surface = [], []
                for fraction, offset in ((0,.014), (.12,.017), (.88,.011), (1,.007)):
                    base.append([brim(side*(a+seam), el+width*fraction, .001)
                                 for a,el,width in stations])
                    surface.append([brim(side*(a+seam), el+width*fraction, offset+standoff)
                                    for a,el,width in stations])
                self.solid_strip(f"Applique | {name} brim panel {side:+d}", base, surface,
                                 "top", "cut", smooth=True)
            for a, el, offset in ((.35,.426,.018), (.75,.435,.018), (1.24,.499,.015)):
                p = brim(side*a, el, offset)
                self.screw(f"Applique | anti-rotation fastener {side:+d}", p, p-origin,
                           .0035, True)

        # Two broad skids traverse the crown with graphite visible in between.
        def crown(t, lateral, height):
            return project(Vector((sin(lateral), -cos(lateral)*cos(t), cos(lateral)*sin(t))), height)

        for side in (-1, 1):
            for label, start, end in (("forward",.52,1.52), ("aft",1.537,2.50)):
                stations = [start + (end-start)*i/steps for i in range(steps+1)]
                base, surface = [], []
                for edge, height in ((-1,.0015), (-.84,.0068), (.80,.0068), (1,.002)):
                    laterals = [side * (.396 + .170*cos(t-.45) + edge * (
                        .148 - .046*((t-1.48)/1.04)**4 + .021*cos(4*t+side*.35)))
                        for t in stations]
                    base.append([crown(t, u, -.0025) for t, u in zip(stations, laterals)])
                    surface.append([crown(t, u, height) for t, u in zip(stations, laterals)])
                self.solid_strip(f"Applique | {label} crown applique {side:+d}",
                                 base, surface, "top", "cut", smooth=True)
            for t in (.61, 2.39) if not self.low else (.61,):
                p = crown(t, side*(.396 + .170*cos(t-.45)), .007)
                self.screw(f"Applique | traverse screw {side:+d}", p, p-origin, .0032, True)

    @staticmethod
    def pane_point(theta, fraction, offset=0):
        # The brow follows the shell, the lower edge rises under each cheek.
        t = abs(theta)/1.34
        bottom = 1.644 + .055*t**2.50
        top = 1.756 - .005*t
        rx = .104 + .014*fraction
        depth = .144 - .004*fraction
        return (HEAD_ANCHOR.x + (rx + offset)*sin(theta),
                -.004 - (depth + offset)*cos(theta),
                bottom + (top-bottom)*fraction)

    def visor(self):
        steps = 16 if self.low else 32
        angles = [1.34*(2*i/steps-1) for i in range(steps+1)]
        fractions = (0, .25, .53, .78, 1)
        obj = self.sheet("Visor | smoked wraparound face shield",
                         [[self.pane_point(t,f) for t in angles] for f in fractions], "glass")
        # Give the opaque shield a definite thickness at all four edges.
        solidify = obj.modifiers.new("Molded shield thickness", "SOLIDIFY")
        solidify.thickness = .0025
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
        original = obj.data
        obj.modifiers.remove(solidify)
        obj.data = evaluated
        bpy.data.meshes.remove(original)
        outer_rows = [[self.pane_point(t, f, grow) for t in angles]
                      for f, grow in ((1.089,.003), (1.053,.007), (1.006,.008), (.972,.003))]
        inner_rows = [[self.pane_point(t, f, grow) for t in angles]
                      for f, grow in ((1.089,-.002), (1.053,.001), (1.006,.001), (.972,-.003))]
        self.solid_strip("Visor | fitted rubber brim gasket", inner_rows, outer_rows,
                         "rubber", "rubber", smooth=True)

    def mandible(self):
        # A continuous inner seal joins the shield, chin plate and two jaw links.
        span = 1.42
        angles = [span*(2*i/(12 if self.low else 20)-1) for i in range((12 if self.low else 20)+1)]
        rows = []
        for height, grow in ((.008,-.003), (.002,.004), (-.027,.004), (-.033,-.018)):
            row = []
            for angle in angles:
                x, y, z = self.pane_point(angle, 0, grow)
                row.append((x, y, z + height))
            rows.append(row)
        self.sheet("Mandible | continuous jaw seal", rows, "rubber", smooth=True)

        # The central piece covers the mouth and chin. Its broad front facets
        # step back at the cheeks so the separate arms stay visible.
        angles = (-.57, -.48, -.38, -.26, -.13, 0, .13, .26, .38, .48, .57)
        outer, inner = [], []
        for z_offset, grow, taper in ((.009,.003,1.05), (.001,.012,1),
                                      (-.026,.010,.93), (-.039,-.0005,.77)):
            front, backing = [], []
            for angle in angles:
                x, y, z = self.pane_point(angle*taper, 0, grow)
                z += z_offset + .005*(abs(angle)/.57)**2
                front.append((x, y, z))
                backing.append((x*.93, y+.014, z))
            outer.append(front)
            inner.append(backing)
        self.solid_strip("Mandible | central chin cup", inner, outer, "hard", "panel",
                         smooth=True)

        for side in (-1, 1):
            # The ends tuck into both adjoining panels. The exposed edge matches
            # the continuous curvature of the smoked visor.
            silhouette = ((.049,-.128,1.626), (.067,-.114,1.628), (.102,-.070,1.650),
                          (.130,-.039,1.666), (.133,-.033,1.684), (.121,-.038,1.696),
                          (.099,-.076,1.673), (.062,-.117,1.651), (.050,-.127,1.647))
            self.extrusion(f"Mandible | articulated jaw arm {side:+d}",
                           [(side*(.132 + .73*(y+.037)), y-.004*(1-max(0,(y+.037)/.09)), z)
                            for _,y,z in silhouette],
                           (-side*.009,.008,.001), .0023 if not self.low else 0, "hard", "panel")
            cover = ((.065,-.122,1.634), (.094,-.082,1.650), (.116,-.054,1.666),
                     (.118,-.051,1.680), (.109,-.059,1.680), (.077,-.106,1.654),
                     (.064,-.122,1.646))
            self.extrusion(f"Mandible | jaw insert {side:+d}",
                           [(side*(.134 + .73*(y+.037)), y-.002, z) for _,y,z in cover],
                           (-side*.004,.002,0), .0014 if not self.low else 0, "panel", "hard")
            link = ((.060,-.133,1.626), (.080,-.109,1.637),
                    (.075,-.110,1.652), (.056,-.131,1.644))
            self.extrusion(f"Mandible | chin link {side:+d}", [(side*x,y,z) for x,y,z in link],
                           (-side*.006,.007,0), .0014 if not self.low else 0, "rail", "hard")
            self.screw(f"Mandible | arm hinge pin {side:+d}", (side*.131,-.041,1.681),
                       (side,-.28,.06), .0051, True)
            if not self.low:
                self.screw(f"Mandible | chin link screw {side:+d}", (side*.069,-.120,1.642),
                           (side*.68,-1,0), .0029, True)

    def cheek_and_rails(self):
        for side in (-1, 1):
            def point(x, y, z):
                # The rail seat tucks into the receding rear edge of the shell.
                return Vector((side*(x-.15*max(0,y)), y, z))

            def armor(name, x, outline, depth, bevel, key, edge=None):
                return self.extrusion(f"Side | {name} {side:+d}",
                                      [point(x,y,z) for y,z in outline],
                                      (-depth*side,0,0), bevel if not self.low else 0, key, edge)

            def window(name, x, outline, opening, thickness, finish, chamfer):
                outer = [point(x,y,z) for y,z in outline]
                inner = [point(x,y,z) for y,z in opening]
                inset = Vector((-thickness*side,0,0))
                reverse = Vector((side*chamfer,0,0))
                center = sum(outer, Vector()) / len(outer)
                lip = [q + reverse + (center-q).normalized()*chamfer for q in outer]
                obj = self.sheet(f"Side | {name} {side:+d}",
                                 [[v+inset for v in outer], outer, lip, inner, [v+inset for v in inner]],
                                 finish, closed=True, smooth=False, loop=True)
                obj.data.materials.append(self.materials["bolt"])
                for face in list(obj.data.polygons)[len(outer):2*len(outer)]:
                    face.material_index = 1
                bm = bmesh.new()
                bm.from_mesh(obj.data)
                bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
                bm.to_mesh(obj.data)
                bm.free()

            # A continuous rail is recessed into the helmet side under the brow strip.
            outline = [(-.064,1.749),(-.040,1.782),(-.018,1.798),(.054,1.799),
                       (.091,1.781),(.102,1.755),(.084,1.752),(.047,1.767),
                       (.013,1.769),(-.019,1.763),(-.050,1.742)]
            armor("ARC rail seat", .113, outline, .025, .004, "rail", "panel")
            window("ARC track with open indexing channel", .123,
                   [(-.039,1.776),(-.027,1.787),(.046,1.792),(.070,1.781),
                    (.079,1.771),(.064,1.771),(.002,1.768),(-.034,1.767)],
                   [(-.028,1.775),(-.022,1.782),(.046,1.786),(.060,1.780),
                    (.065,1.776),(.053,1.776),(.004,1.773),(-.025,1.772)],
                   .010, "rail", .0022 if not self.low else .001)
            for i in range(3 if self.low else 6):
                y = -.018 + i*(.026 if self.low else .013)
                z = 1.774 + (y+.018)*.09
                armor("ARC index bar", .123, [(y,z),(y-.001,z+.009),
                                             (y+.0023,z+.010),(y+.003,z+.001)],
                      .009, .0007, "panel", "rail")

            # The hanger supplies two lugs between the lower rail and deeper impact shell.
            armor("ear hanger", .125, [(-.024,1.726),(-.028,1.760),(-.022,1.770),
                                     (.019,1.771),(.032,1.760),(.027,1.733),(.018,1.724)],
                  .020, .003, "rail", "panel")
            armor("ear impact gasket", .130, [(-.055,1.705),(-.049,1.747),(-.022,1.761),
                                            (.028,1.758),(.049,1.732),(.043,1.686),
                                            (.023,1.671),(-.021,1.668),(-.047,1.683)],
                  .025, .004, "rubber")
            ear_outline = [(-.049,1.706),(-.044,1.742),(-.023,1.753),(.024,1.750),
                           (.044,1.732),(.039,1.699),(.028,1.679),(.020,1.676),
                           (-.018,1.679),(-.039,1.688)]
            armor("ear armor", .137, ear_outline, .016, .0032, "panel", "hard")
            armor("ear armor lower overlap", .139,
                  [(-.042,1.702),(-.020,1.703),(.012,1.695),(.036,1.700),(.027,1.681),
                   (.017,1.676),(-.018,1.679),(-.041,1.688)],
                  .005, .0018, "hard", "rail")
            armor("visor lock fitted saddle", .120, [(-.077,1.702),(-.078,1.725),(-.072,1.732),
                                                  (-.051,1.732),(-.043,1.719),(-.045,1.704),
                                                  (-.055,1.698),(-.071,1.698)],
                  .033, .0020, "hard", "rail")
            eye_bolt = point(.125,-.065,1.716)
            window("visor lock collar", .122,
                   [(-.079,1.705),(-.080,1.726),(-.073,1.733),(-.056,1.731),
                    (-.051,1.725),(-.052,1.706),(-.058,1.700),(-.073,1.700)],
                   [(-.073,1.707),(-.073,1.724),(-.070,1.727),(-.061,1.725),
                    (-.058,1.723),(-.059,1.709),(-.062,1.706),(-.070,1.706)],
                   .010, "hard", .0015)
            self.screw("Side | visor lock pin", eye_bolt, (side,-.15,.05), .004, True)
            for y,z in ((-.022,1.744),(.027,1.735),(.021,1.686),(-.030,1.693)):
                self.screw("Side | ear cover screw", point(.1375,y,z), (side,0,0), .003, True)

            # Rear clip engages the top rail and wraps around the adjacent back edge.
            armor("ARC rear saddle", .118, [(.056,1.771),(.065,1.803),(.074,1.812),
                                           (.101,1.805),(.112,1.793),(.106,1.771),(.087,1.766)],
                  .028, .004, "rail", "panel")
            window("rear saddle tie aperture", .122,
                   [(.064,1.775),(.070,1.802),(.076,1.808),(.097,1.802),
                    (.109,1.792),(.104,1.774),(.091,1.770),(.078,1.771)],
                   [(.073,1.779),(.077,1.797),(.081,1.801),(.094,1.796),
                    (.101,1.790),(.098,1.779),(.090,1.775),(.082,1.775)],
                   .009, "panel", .0014)
            armor("rear retention clip", .110, [(.099,1.699),(.092,1.750),(.095,1.766),
                                               (.113,1.764),(.126,1.728),(.122,1.704),
                                               (.116,1.695),(.106,1.694)],
                  .021, .003, "rail", "panel")
            self.screw("Side | rear clip lower bolt", point(.113,.111,1.709),
                       (side,.25,0), .0043, True)
            self.screw("Side | rear clip upper bolt", point(.112,.107,1.750),
                       (side,.25,0), .0035, True)
            self.screw("Side | forward rail anchor", point(.118,-.042,1.765),
                       (side,-.22,.07), .004, True)

    def shroud(self):
        # Front plate is canted to match the FAST slot mounting face.
        origin = HEAD_ANCHOR + TO_BLENDER @ Vector(SLOTS["mod_nvg"][0])
        outward = Vector((0,-.91,.414)).normalized()
        vertical = Vector((0,.414,.91)).normalized()
        across = Vector((1,0,0))

        def outline(center, w, h, cut):
            return [center + across*u + vertical*v for u,v in (
                (-w+cut,-h),(w-cut,-h),(w,-h+cut),(w,h-cut),
                (w-cut,h),(-w+cut,h),(-w,h-cut),(-w,-h+cut))]

        backing = origin + Vector((0,-.021,0))
        mount_plate = self.extrusion("Shroud | chamfered mounting backplate", outline(backing,.028,.031,.007),
                       -Vector((0,-.97,.23))*.027, .0025 if not self.low else 0, "rail", "cut")
        mount_plate["mount_seat"] = "mod_nvg"
        front = backing + outward*.006
        outer = outline(front,.022,.024,.0040)
        inner = outline(front + outward*.0004,.015,.016,.0025)
        recess = [p-outward*.0045 for p in inner]
        lip = [p+outward*.0016 for p in outer]
        receiver = self.sheet("Shroud | open rectangular receiver", [outer,lip,inner,recess],
                              "hard", closed=True, smooth=False)
        receiver["mount_seat"] = "mod_nvg"
        receiver.data.materials.append(self.materials["panel"])
        for face in list(receiver.data.polygons)[8:16]:
            face.material_index = 1
        self.add("Shroud | receiver seat", recess, [tuple(range(8))], ["dark"])
        for side in [-1,1]:
            for height in [-1, 1] if not self.low else [1]:
                self.screw("Shroud | screw", backing+across*(side*.024)+vertical*(height*.014)
                           +outward*.0004, outward, radius=.0032, drive=True)

    def rear(self):
        point = HEAD_ANCHOR + TO_BLENDER @ Vector(SLOTS["mod_equipment_001"][0])
        yoke = self.box("Rear | lower retention yoke",
                        (point.x,.091,point.z+.011),
                        (.107,.031,.052), "hard", "rail", chamfer=.007)
        yoke["mount_seat"] = "mod_equipment_001"
        armor = self.box("Rear | nape facing", (point.x,.120,point.z+.006),
                         (.088,.025,.013), "panel", "rail", chamfer=.004)
        armor["mount_seat"] = "mod_equipment_001"
        for side in (-1,1):
            self.screw("Rear | lower yoke fastener", (point.x+side*.034,.128,point.z+.007),
                       (0,1,0), .004, True)
        self.box("Rear | fitted accessory plate", (HEAD_ANCHOR.x,.134,1.735),
                 (.066,.047,.013), "rail", "cut", chamfer=.006)
        # The rear plate above faces forward by construction; its backing exposes / seats
        # on the rear shell. Two dark tabs sit proud of the rear for the accessory straps.
        self.box("Rear | lower retention bar", (HEAD_ANCHOR.x,.138,1.717),
                 (.069,.013,.014), "hard", chamfer=.0035)
        self.box("Rear | hook field", (HEAD_ANCHOR.x,.139,1.743),
                 (.045,.017,.009), "panel", chamfer=.003)

    def gaiter(self):
        """Fit a smooth fabric envelope over the native USEC jaw, ears and throat."""
        source = Path(__file__).resolve().parents[1] / "source" / "reference" / "usec_head.json"
        head = json.loads(source.read_text(encoding="utf-8"))
        positions = [Vector(p) for p in head["positions"]]
        triangles = head["triangles"]
        tree = BVHTree.FromPolygons(positions, triangles, all_triangles=True)
        pivot = Vector((HEAD_ANCHOR.x, .017, 0))
        steps = 14 if self.low else 24
        levels = (1.555, 1.573, 1.586, 1.597, 1.608, 1.623, 1.642,
                  1.659, 1.680, 1.705, 1.731, 1.755)
        if self.low:
            levels = (1.555,1.575,1.596,1.619,1.648,1.681,1.716,1.756)
        bones = [path.rsplit("/", 1)[-1] for path in head["bonePaths"]]
        bone_names = [NECK if name == "Base HumanHead" else name for name in bones]

        def cast(z, theta):
            normal = Vector((sin(theta), -cos(theta), 0))
            center = Vector((pivot.x,pivot.y,z))
            point, _, _, distance = tree.ray_cast(center + .31*normal, -normal, .31)
            return .31 - distance if point is not None else 0

        rings = []
        for row, z in enumerate(levels):
            ring = []
            for i in range(steps):
                theta = tau*i/steps
                # The margin covers interpolation between stations and retains enough
                # space for the knit to drape over the ear and chin.
                under_jaw = z < 1.608 and abs(theta - pi) > 2.25
                overshoot = .018 if under_jaw else .006
                reach = max(cast(z+dz,theta+dtheta)
                            for dz in (-.006, 0, .006, overshoot)
                            for dtheta in (-.10, 0, .10))
                minimum = .064 + .007*sin(theta)**2
                seam = .0016*sin(3*theta+.70*row) + .0011*sin(7*theta-.85*row)
                margin = .010 if self.low else .0075
                ear_overlap = .010*sin(theta)**4 if 1.656 < z < 1.742 else 0
                radius = max(reach + margin + ear_overlap, minimum) + seam
                ring.append((pivot.x + radius*sin(theta), pivot.y - radius*cos(theta), z))
            rings.append(ring)
        obj = self.sheet("Balaclava | fitted black gaiter", rings, "fabric", closed=True)
        obj["fitted_to"] = "USEC reference head"
        # Transfer the throat and collar weight gradient. Above the jaw, the native
        # rigid Head skin is represented by Base HumanNeck in this 58-bone rig.
        groups = {}
        for vert in obj.data.vertices:
            reference, _, face, _ = tree.find_nearest(vert.co)
            triangle = triangles[face]
            points = [positions[i] for i in triangle]
            weights = barycentric_transform(reference, *points,
                                             Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1)))
            influences = defaultdict(float)
            for index, fraction in zip(triangle, weights):
                for bone, weight in zip(head["boneIndices"][index], head["boneWeights"][index]):
                    if weight > 0 and bone_names[bone] in self.rig.data.bones:
                        influences[bone_names[bone]] += weight * max(fraction, 0)
            strongest = sorted(influences.items(), key=lambda item: item[1], reverse=True)[:4]
            total = sum(weight for _, weight in strongest if weight > .00001)
            for bone, weight in strongest:
                if weight <= .00001:
                    continue
                if bone not in groups:
                    groups[bone] = obj.vertex_groups.new(name=bone)
                groups[bone].add([vert.index], weight/total, "REPLACE")
        return obj

    def thermal(self):
        self.part = "thermal"
        x = HEAD_ANCHOR.x
        self.box("Thermal | dovetail tongue", (x,-.151,1.792),
                 (.025,.028,.026), "bolt", chamfer=.0032)
        self.box("Thermal | hinge cradle", (x,-.167,1.812),
                 (.047,.028,.031), "hard", "rail", chamfer=.004)
        self.box("Thermal | imager housing", (x,-.177,1.840),
                 (.072,.041,.048), "panel", "hard", chamfer=.007, bevel=.003)
        self.box("Thermal | front gasket", (x,-.197,1.841),
                 (.063,.034,.007), "rubber", chamfer=.005)
        self.box("Thermal | focus bezel", (x+.011,-.203,1.842),
                 (.039,.032,.011), "hard", "rail", chamfer=.0046)
        self.box("Thermal | battery cap", (x-.023,-.202,1.840),
                 (.013,.025,.014), "crown", "rail", chamfer=.003)
        self.box("Thermal | control field", (x,-.174,1.865),
                 (.048,.022,.0045), "hard", axis="Z", chamfer=.003)
        for i in range(3):
            self.box("Thermal | sealed control", (x+.013*(i-1),-.174,1.868),
                     (.009,.011,.004), "rubber", axis="Z", chamfer=.0013)

        def ring(y, radius):
            count = 12 if self.low else 24
            return [Vector((x+.011+radius*cos(tau*i/count), y, 1.842+radius*sin(tau*i/count)))
                    for i in range(count)]

        collar = [ring(y, radius) for y,radius in ((-.207,.014),(-.211,.0145),
                  (-.220,.0145),(-.222,.013),(-.222,.011),(-.216,.0103),(-.213,.0103))]
        self.sheet("Thermal | stepped focus collar", collar, "dark", closed=True, loop=True)
        lens = [ring(-.2165,.0104), ring(-.2179,.006), ring(-.2185,.0025)]
        self.sheet("Thermal | curved germanium objective", lens, "optic", closed=True)
        self.add("Thermal | germanium center", lens[-1], [tuple(range(len(lens[-1])))], ["optic"])
        if not self.low:
            for i in range(16):
                theta = tau*i/16
                cx = x+.011+.0149*cos(theta)
                cz = 1.842+.0149*sin(theta)
                normal = Vector((cos(theta),0,sin(theta)))
                tangent = Vector((-sin(theta),0,cos(theta)))
                points = [Vector((cx,-.215,cz)) + Vector((0,dy,0)) + tangent*dt
                          for dy,dt in ((-.004,-.0011),(.004,-.0011),(.004,.0011),(-.004,.0011))]
                self.extrusion("Thermal | focus grip rib", points, -normal*.002,
                               .00055, "panel", "hard")
        for side in (-1,1):
            self.screw("Thermal | horizontal swivel axle", (x+side*.026,-.165,1.817),
                       (side,0,0), .007, True)
            self.screw("Thermal | bezel fastener", (x+side*.029,-.201,1.853),
                       (0,-1,0), .0021, True)


def build(lod, collection, rig):
    """Populate the collection with the requested headgear LOD and return its objects."""
    assembly = Headgear(lod, collection, rig)
    shell = assembly.shell()
    assembly.crown_panels(shell)
    assembly.visor()
    assembly.mandible()
    assembly.cheek_and_rails()
    assembly.shroud()
    assembly.rear()
    assembly.gaiter()
    nvg = None
    if not lod:
        nvg = assembly.socket("mod_nvg")
        assembly.socket("mod_equipment_001")
    assembly.thermal()
    for obj in assembly.objects:
        if nvg and obj["part"] == "thermal":
            # Mesh coordinates begin in bind world. The inverse socket transform
            # preserves that fit while making the thermal a detachable child.
            obj.parent = nvg
            obj.matrix_parent_inverse = nvg.matrix_world.inverted()
        else:
            assembly.skin(obj)
    return assembly.objects

