"""Fit pressed vents, inspection covers and service lettering to the armature."""
import bpy
from math import radians
from mathutils import Quaternion, Vector

from v2_plates import UP, _bvh


def glyphs(text):
    font = bpy.data.curves.new("Service lettering", "FONT")
    font.body = text
    font.align_x = "CENTER"
    font.align_y = "CENTER"
    font.resolution_u = 3
    obj = bpy.data.objects.new("Marking stencil", font)
    bpy.context.scene.collection.objects.link(obj)
    try:
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        points = [v.co.xy.copy() for v in mesh.vertices]
        faces = [tuple(tri.vertices) for tri in mesh.loop_triangles]
        evaluated.to_mesh_clear()
        return points, faces
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.curves.remove(font)


def die(target, center, normal, upright):
    surface = _bvh([target])
    n = normal.normalized()
    local_center, n, _, _ = surface.ray_cast(center + n * .12, -n, .24)
    if local_center is None:
        raise ValueError(f"Cannot locate ink surface on {target.name}")
    horizontal = upright.cross(n).normalized()
    vertical = n.cross(horizontal)
    def stamp(x, y, relief):
        start = local_center + horizontal * x + vertical * y + n * .035
        hit, face_normal, _, _ = surface.ray_cast(start, -n, .080)
        if hit is None:
            raise ValueError(f"Tooling extends beyond {target.name}")
        return hit + face_normal * relief
    return stamp


def apply_label(armor, target, title, legend, width, center, normal, upright):
    stamp = die(target, center, normal, upright)
    points, faces = glyphs(legend)
    xlo, xhi = min(p.x for p in points), max(p.x for p in points)
    ylo, yhi = min(p.y for p in points), max(p.y for p in points)
    scale = width / (xhi - xlo)
    verts, uv = [], []
    for p in points:
        x, y = (p.x - (xhi + xlo) / 2) * scale, (p.y - (yhi + ylo) / 2) * scale
        verts.append(stamp(x, y, .00065))
        uv.append(((p.x - xlo) / (xhi - xlo), (p.y - ylo) / (yhi - ylo)))
    bone = target.vertex_groups[0].name.removeprefix("Base Human")
    mark = armor.mesh(title, bone, "marking", verts, faces, uv, smooth=False)
    del mark["v2_rigid"]
    mark["v2_swatch_uv"] = True


def inlet(armor, target, stamp, title, width, height):
    # The octagonal rim, sloping return and shadowed bed are a single punch.
    contour = ((-.71,-1), (.75,-1), (1,-.73), (1,.48),
               (.59,1), (-.80,1), (-1,.70), (-1,-.63))
    profile = ((1.02,-.001), (1,.0021), (.94,.0053), (.77,.0053),
               (.72,.0018))
    bone = target.vertex_groups[0].name.removeprefix("Base Human")
    points, uv, faces = [], [], []
    for row, (fraction, depth) in enumerate(profile):
        for u, v in contour:
            points.append(stamp(width*u*fraction/2, height*v*fraction/2, depth))
            uv.append(((u*fraction+1)/2, (v*fraction+1)/2))
        if row:
            armor._join(faces, 8*(row-1), 8*row, 8)
    faces.append(tuple(range(32,40)))
    faces.append(tuple(reversed(range(8))))
    obj = armor.mesh(title+"Bezel", bone, "graphite", points, faces, uv, smooth=False)
    for material in ("V2_edge_dark", "V2_black"):
        obj.data.materials.append(bpy.data.materials.get(material) or bpy.data.materials.new(material))
    for poly in list(obj.data.polygons)[16:24]:
        poly.material_index = 1
    obj.data.polygons[-2].material_index = 2
    # Each angled blade casts a real shadow across the backing plate.
    for index, line in enumerate((-.36,-.03,.30)):
        x0, x1 = -.29*width, .29*width
        base = line*height/2
        lip = .13*height
        pts = [stamp(x, base+offset, z) for x in (x0,x1)
               for offset,z in ((0,.0022), (.001,.0066), (lip,.0042), (lip,.0021))]
        faces = [(0,1,2,3), (7,6,5,4),
                 (4,5,1,0), (5,6,2,1), (6,7,3,2), (7,4,0,3)]
        uv = [(i//4, (i%4)/3) for i in range(8)]
        armor.mesh(f"{title}Louver{index}", bone, "edge_dark", pts, faces, uv, smooth=False)


def build(a):
    shoulder, elbow = a.head("RUpperarm"), a.head("RForearm1")
    down = Vector((0, 0, -1))
    swing = Quaternion((elbow - shoulder).cross(down).normalized(), radians(36))
    to_rest = (Quaternion(Vector((1, 0, 0)), radians(23)) @ swing).inverted()
    right_roof = next(obj for obj in a.objects if obj.name.endswith("ShoulderRoofR"))
    anchor = shoulder + to_rest @ (Vector((-.271, -.062, 1.520)) - shoulder)
    apply_label(a, right_roof, "ShoulderLotInk", "TG  /  04", .052, anchor,
                to_rest @ Vector((-.28, -.64, .74)), to_rest @ UP)
    for side in ("L", "R"):
        panel = next(obj for obj in a.objects if obj.name.endswith("VambraceCentralOuter" + side))
        wrist, hinge = a.head(side+"Palm"), a.head(side+"Forearm1")
        center = sum((v.co for v in panel.data.vertices), Vector()) / len(panel.data.vertices)
        length = (hinge-wrist).normalized()
        delta = center-wrist
        outward = (delta-length*delta.dot(length)).normalized()
        inlet(a, panel, die(panel, center, outward, length), "WristCooling"+side, .046, .056)
    left_shin = next(obj for obj in a.objects if obj.name.endswith("ShinShellL"))
    center = sum((v.co for v in left_shin.data.vertices), Vector()) / len(left_shin.data.vertices)
    apply_label(a, left_shin, "AccessCoverInk", "S-12", .029, center, Vector((0, -1, 0)), UP)
