"""Faceted shoulder roofs, articulated limb plates and square-toed boots."""
from collections import defaultdict
import math

import bpy
from mathutils import Vector

from v2_plates import FRONT, UP, OCTAGON, _hub


BEVEL_FAMILIES = {"olive": "edge", "graphite": "edge_dark"}


def _material_slot(obj, family):
    name = "V2_" + family
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    obj.data.materials.append(material)
    return len(obj.data.materials) - 1


def _fastener(a, name, bone, anchor, axis, radius=.006):
    if a.lod:
        return
    a.turning(name + "Seat", bone, "graphite", anchor, axis,
              ((radius, -.002), (radius, .0002), (radius * .82, .0012)), sides=10)
    a.turning(name + "Stud", bone, "steel", anchor, axis,
              ((radius * .61, .0009), (radius * .68, .0027), (radius * .48, .0035)), sides=6)


def _chamfered(a, name, bone, family, point, outline, thickness, edge=True):
    """A closed plate with a flat face, full-depth side wall, and milled chamfer."""
    bevel = min(thickness * .30, .009)
    bevel_scale = 1 - min(.13, bevel * 15)
    sections = ((.94, 0), (1., bevel * .28), (1., thickness - bevel),
                (bevel_scale, thickness))
    vertices, faces, uv = [], [], []
    count = len(outline)
    for index, (scale, depth) in enumerate(sections):
        for u, v in outline:
            vertices.append(point(u * scale, v * scale, depth))
            uv.append((.5 + u * scale * .46, .5 + v * scale * .46))
        if index:
            a._join(faces, (index - 1) * count, index * count, count)
    faces.extend((tuple(reversed(range(count))), tuple(range(3 * count, 4 * count))))
    obj = a.mesh(name, bone, family, vertices, faces, uv, smooth=False)
    if edge and family in BEVEL_FAMILIES:
        index = _material_slot(obj, BEVEL_FAMILIES[family])
        for polygon in list(obj.data.polygons)[2 * count:3 * count]:
            polygon.material_index = index
    return obj


def _limb_axes(start, end, outward):
    up = (start - end).normalized()
    right = up.cross(Vector(outward)).normalized()
    return up, right, right.cross(up)


def _radius(a, center, axis, nominal, fit):
    hit, _, _, _ = a.surface.ray_cast(center + axis * (nominal + fit), -axis, fit * 2)
    if hit is None:
        return nominal
    return max(nominal - fit * .4, (hit - center).dot(axis) + .006)


def _set_panel_normals(mesh, face_columns):
    # A pressed strip keeps its longitudinal highlights continuous through the
    # bevel breaks. Adjacent strips still have separate normals at the crest.
    sums = defaultdict(Vector)
    for face_id, column in face_columns:
        polygon = mesh.polygons[face_id]
        polygon.use_smooth = True
        for vertex in polygon.vertices:
            sums[column, vertex] += polygon.normal * polygon.area
    normals = [(0, 0, 0)] * len(mesh.loops)
    for face_id, column in face_columns:
        for loop_id in mesh.polygons[face_id].loop_indices:
            vertex = mesh.loops[loop_id].vertex_index
            normals[loop_id] = sums[column, vertex].normalized()
    mesh.normals_split_custom_set(normals)


def _panel(a, name, bone, family, start, end, outward, rows, thickness,
           *, fit=.03, slots=False, anchors=()):
    """Rows list longitudinal fraction, sector center/width in degrees and fit radius.

    The supplied row stations and angular columns are the actual breaklines. At each
    station the exposed face is straight between adjacent breaklines, while the shell
    chamfer stays confined to the outside perimeter.
    """
    up, right, front = _limb_axes(start, end, outward)
    columns = (-1, -.50, -.14, .14, .50, 1) if slots else (
        (-1, -.46, .46, 1) if a.lod else (-1, -.57, 0, .57, 1))
    stride, height = len(columns), len(rows)
    surface = []
    directions = []
    for fraction, yaw, width, nominal in rows:
        center = start.lerp(end, fraction)
        for column in columns:
            angle = math.radians(yaw + width * column)
            axis = front * math.cos(angle) + right * math.sin(angle)
            radius = _radius(a, center, axis, nominal, fit)
            # Angular faces behind the contour retain a few millimetres of air.
            surface.append(center + axis * radius)
            directions.append(axis)
    perimeter = (
        [index * stride for index in range(height)]
        + [(height - 1) * stride + index for index in range(1, stride)]
        + [index * stride + stride - 1 for index in reversed(range(height - 1))]
        + [index for index in reversed(range(1, stride - 1))]
    )
    bevel = min(.010, thickness * .29)
    vertices = list(surface)
    uv = [(index % stride / (stride - 1), 1 - index // stride / (height - 1))
          for index in range(len(surface))]
    exterior = len(vertices)
    for index, (point, direction) in enumerate(zip(surface, directions)):
        offset = Vector()
        row, column = divmod(index, stride)
        if row in (0, height - 1):
            toward = index + stride if row == 0 else index - stride
            offset += (surface[toward] - point).normalized() * bevel
        if column in (0, stride - 1):
            toward = index + 1 if column == 0 else index - 1
            offset += (surface[toward] - point).normalized() * bevel
        vertices.append(point + direction * thickness + offset)
        uv.append(uv[index])

    faces, recess, bevel_faces, face_columns = [], [], [], []
    open_row = 1
    for row in range(height - 1):
        for column in range(stride - 1):
            index = row * stride + column
            corners = (index, index + stride, index + stride + 1, index + 1)
            faces.append(tuple(reversed(corners)))
            corners = tuple(exterior + corner for corner in corners)
            if slots and row == open_row and column == 2:
                floor = tuple(range(len(vertices), len(vertices) + 4))
                for corner in corners:
                    vertices.append(vertices[corner] - directions[corner - exterior] * .013)
                    uv.append(uv[corner])
                for i, corner in enumerate(corners):
                    j = (i + 1) % 4
                    recess.append(len(faces))
                    faces.append((corner, corners[j], floor[j], floor[i]))
                recess.append(len(faces))
                faces.append(floor)
            else:
                face_columns.append((len(faces), column))
                faces.append(corners)

    band = len(vertices)
    for point in perimeter:
        vertices.append(surface[point] + directions[point] * (thickness - bevel))
        uv.append(uv[point])
    for index, point in enumerate(perimeter):
        j = (index + 1) % len(perimeter)
        neighbor = perimeter[j]
        faces.append((point, neighbor, band + j, band + index))
        bevel_faces.append(len(faces))
        faces.append((band + index, band + j, exterior + neighbor, exterior + point))

    obj = a.mesh(name, bone, family, vertices, faces, uv, smooth=False)
    _set_panel_normals(obj.data, face_columns)
    edge_material = _material_slot(obj, BEVEL_FAMILIES[family])
    for index in bevel_faces:
        obj.data.polygons[index].material_index = edge_material
    if slots:
        recess_material = _material_slot(obj, "fabricdark")
        for index in recess:
            obj.data.polygons[index].material_index = recess_material
    for number, (row, column) in enumerate(anchors):
        index = row * stride + column if column >= 0 else (row + 1) * stride + column
        _fastener(a, f"{name}Fastener{number}", bone,
                  vertices[exterior + index], directions[index])
    return obj


def _piston(a, name, bone, start, end, radius):
    axis = (end - start).normalized()
    length = (end - start).length
    a.turning(name + "Sleeve", bone, "graphite", start, axis,
              ((radius * .83, 0), (radius, .006), (radius, length * .64),
               (radius * .74, length * .71)), sides=8 if a.lod else 12)
    a.turning(name + "Rod", bone, "steel", start, axis,
              ((radius * .43, length * .69), (radius * .43, length - .005),
               (radius * .71, length - .002), (radius * .71, length)), sides=8)


def _dorsal_patch(a, name, bone, start, end, outward, width, length, radius, thickness):
    normal = _limb_axes(start, end, outward)[2]
    origin = start.lerp(end, .49) + normal * radius
    plane = a.planar(origin, normal, start - end, width, length)
    _chamfered(a, name, bone, "graphite", plane, OCTAGON, thickness)


def arm(a, side, sign):
    def head(name):
        return a.head(side + name)

    shoulder, elbow, wrist = (head(name) for name in ("Upperarm", "Forearm1", "Palm"))
    palm = head("Digit31")
    upper, lower = side + "Upperarm", side + "Forearm1"
    outer = Vector((sign, .08, .42))
    shoulder_out = Vector((sign, .04, .66))
    dorsal = Vector((sign, -.12, .65))

    _panel(a, "DeltoidRoof" + side, upper, "graphite", shoulder, elbow, shoulder_out,
           ((-.12, -15 * sign, 31, .118), (.045, -15 * sign, 57, .122),
            (.115, -15 * sign, 58, .126), (.32, -10 * sign, 57, .123),
            (.455, -4 * sign, 42, .114), (.51, 5 * sign, 19, .110)),
           .031, fit=.029, slots=True,
           anchors=((2, 1), (2, -2), (4, 1)))
    _panel(a, "DeltoidLowerBlade" + side, upper, "graphite", shoulder, elbow, shoulder_out,
           ((.39, 10 * sign, 31, .118), (.47, 18 * sign, 39, .112),
            (.56, 24 * sign, 29, .109), (.605, 29 * sign, 17, .107)), .018, fit=.024)
    _panel(a, "BicepsGuard" + side, upper, "graphite", shoulder, elbow, (sign * .48, -1, .10),
           ((.31, 8 * sign, 17, .112), (.42, 0, 25, .108), (.65, -5 * sign, 22, .109),
            (.73, -8 * sign, 12, .109)), .017, fit=.024)
    _panel(a, "TricepsBlade" + side, upper, "graphite", shoulder, elbow, (sign * .47, .93, -.13),
           ((.26, 0, 20, .124), (.40, 0, 35, .124), (.59, -7 * sign, 29, .118),
            (.70, -11 * sign, 14, .112)), .018, fit=.025)
    _panel(a, "ElbowCap" + side, lower, "graphite", elbow, wrist, (sign * .58, .54, -.59),
           ((-.175, 0, 20, .103), (-.095, 0, 35, .106), (.075, 0, 39, .108),
            (.185, 0, 24, .098)), .021, fit=.025)
    hinge_axis = _limb_axes(elbow, wrist, (sign, .47, .03))[2]
    pivot = elbow + hinge_axis * _radius(a, elbow, hinge_axis, .112, .032)
    _hub(a, "ElbowServo" + side, lower, pivot, hinge_axis, .034)

    _panel(a, "VambraceBlade" + side, lower, "graphite", elbow, wrist, dorsal,
           ((.355, -4 * sign, 28, .102), (.43, -1 * sign, 46, .101),
            (.57, 2 * sign, 44, .094), (.77, 4 * sign, 33, .085),
            (.86, 9 * sign, 19, .078)), .022, fit=.026, anchors=((1, 1), (1, -2)))
    _panel(a, "VambraceCounterplate" + side, lower, "graphite", elbow, wrist, -dorsal,
           ((.32, 8 * sign, 22, .091), (.42, 9 * sign, 41, .090), (.61, 11 * sign, 39, .079),
            (.82, 15 * sign, 24, .064)), .013, fit=.025)
    _panel(a, "WristClasp" + side, side + "Forearm3", "graphite", elbow, wrist, outer,
           ((.89, 0, 54, .073), (.92, 0, 64, .070), (.985, 0, 58, .058)), .012, fit=.024)
    _dorsal_patch(a, "GloveGuard" + side, side + "Palm",
                  wrist, palm, dorsal, .043, .046, .041, .012)
    for digit in range(1, 6):
        for joint in range(1, 3):
            first, second = f"Digit{digit}{joint}", f"Digit{digit}{joint + 1}"
            start, end = head(first), head(second)
            span = (end - start).length
            width = (.0115 if digit in (1, 2, 3) else .0093) - .0015 * (joint - 1)
            _dorsal_patch(a, f"FingerGuard{side}{digit}{joint}", side + first,
                          start, end, dorsal, width, span * .43,
                          width + (.004 if joint == 1 else .002), .006)


def _sole(a, name, bone, sign, outline, z0, z1, family):
    center = Vector((sign * .222, -.035, (z0 + z1) * .5))
    point = lambda u, v, depth: center + Vector((u, v, z0 - center.z + depth))
    _chamfered(a, name, bone, family, point, outline, z1 - z0, edge=False)


def _boot(a, side, sign, ankle, toe):
    foot = side + "Foot"
    tip = side + "Toe"
    lateral = Vector((sign, 0, 0))
    heel_outline = ((-.070, -.055), (.071, -.055), (.077, -.036), (.071, .135),
                    (.055, .157), (-.050, .157), (-.072, .136), (-.078, -.032))
    toe_outline = ((-.063, -.158), (.052, -.158), (.080, -.132), (.078, -.055),
                   (-.077, -.055), (-.080, -.132))
    _sole(a, "HeelSole" + side, foot, sign, heel_outline, -.010, .025, "fabricdark")
    _sole(a, "ToeSole" + side, tip, sign, toe_outline, -.010, .025, "fabricdark")

    # A rigid ankle prism ends over the instep; the Toe-weighted cap can flex away.
    quarters = a.planar((sign * .264, .029, .071), (sign, 0, .22), UP, .094, .049)
    _chamfered(a, "BootQuarterOut" + side, foot, "graphite", quarters,
               ((-.78, -.96), (.82, -.96), (1, -.57), (.81, .53),
                (.53, 1), (-.51, .9), (-.90, .45), (-1, -.42)), .019)
    inner = a.planar((sign * .159, .029, .068), (-sign, 0, .17), UP, .091, .049)
    _chamfered(a, "BootQuarterIn" + side, foot, "graphite", inner, OCTAGON, .016)
    counter = a.planar((sign * .212, .108, .057), (0, 1, .12), UP, .061, .040)
    _chamfered(a, "BootHeelCounter" + side, foot, "graphite", counter, OCTAGON, .018)

    instep_shape = ((-.87, -1), (.87, -1), (1, -.57), (.89, .57),
                    (.66, .98), (-.66, .98), (-.91, .57), (-1, -.57))
    instep = a.planar((sign * .207, -.025, .103), (0, -.43, 1), UP, .063, .039)
    _chamfered(a, "BootInstep" + side, foot, "graphite", instep, instep_shape, .020)
    toe_bridge = a.planar((toe.x, -.126, .060), (0, -.22, 1), UP, .070, .044)
    _chamfered(a, "BootToeRoof" + side, tip, "graphite", toe_bridge, instep_shape, .017)
    toe_cap = a.planar((toe.x, -.174, .040), (0, -1, .31), UP, .068, .019)
    _chamfered(a, "BootToeCounter" + side, tip, "graphite", toe_cap, OCTAGON, .018)
    _hub(a, "AnkleServo" + side, foot, ankle + lateral * .075 + UP * .044, lateral, .025)
    if a.lod:
        return
    for index, y in enumerate((-.158, -.118, -.075, -.020, .027, .073, .102)):
        owner = tip if y < -.09 else foot
        width = .012 if index in (0, 6) else .016
        for edge_sign in (-1, 1):
            lug_center = sign * .222 + edge_sign * .069
            lug = a.planar((lug_center, y, -.008), UP, FRONT, .012, width)
            _chamfered(a, f"BootLug{side}{index}{edge_sign}", owner, "fabricdark", lug,
                       OCTAGON, .027, edge=False)


def leg(a, side, sign):
    def head(name):
        return a.head(side + name)

    hip, knee, ankle, toe = (head(name) for name in ("Thigh1", "Calf", "Foot", "Toe"))
    thigh, calf = side + "Thigh1", side + "Calf"
    lateral = Vector((sign, 0, 0))
    diagonal = Vector((sign * .56, -1, 0))
    forward = Vector((sign * .06, -1, 0))

    _panel(a, "HipTasset" + side, thigh, "graphite", hip, knee, diagonal,
           ((.132, -4 * sign, 23, .150), (.189, 1 * sign, 43, .147),
            (.31, -7 * sign, 43, .153), (.385, -14 * sign, 28, .155)),
           .031, fit=.032, anchors=((1, 1), (1, -2)))
    _panel(a, "UpperCuisses" + side, thigh, "graphite", hip, knee, diagonal,
           ((.402, -8 * sign, 37, .155), (.45, -4 * sign, 48, .152),
            (.55, 2 * sign, 42, .146), (.59, 14 * sign, 31, .141)),
           .028, fit=.032, anchors=((2, 1),))
    _panel(a, "LowerCuisses" + side, thigh, "graphite", hip, knee, diagonal,
           ((.607, 1 * sign, 37, .145), (.65, 5 * sign, 43, .136),
            (.82, 9 * sign, 38, .121), (.86, 14 * sign, 24, .120)),
           .026, fit=.026, anchors=((2, -2),))
    _panel(a, "HamstringShield" + side, thigh, "graphite", hip, knee, (sign * .23, 1, 0),
           ((.26, 0, 23, .145), (.34, 0, 45, .142), (.56, -6 * sign, 42, .136),
            (.655, -13 * sign, 27, .134), (.702, -13 * sign, 16, .133)),
           .020, fit=.031)

    hip_hub_center = hip.lerp(knee, .17) + lateral * .160 + Vector((0, .041, 0))
    _hub(a, "HipServo" + side, thigh, hip_hub_center, lateral, .040)
    _piston(a, "HipDrive" + side, thigh, hip_hub_center.lerp(hip, .04) + UP * -.033,
            hip.lerp(knee, .52) + lateral * .166 + Vector((0, .043, 0)), .017)
    pivot = knee + lateral * .126 + Vector((0, .010, .006))
    _hub(a, "KneeServo" + side, calf, pivot, lateral, .042)
    _piston(a, "KneeDrive" + side, calf, pivot - UP * .023,
            knee.lerp(ankle, .33) + lateral * .125 + Vector((0, .031, 0)), .014)

    _panel(a, "Poleyn" + side, calf, "graphite", knee, ankle, forward,
           ((-.115, 0, 25, .108), (-.072, 0, 40, .108), (.032, 0, 53, .104),
            (.112, 0, 33, .096), (.145, 0, 19, .091)), .026, fit=.025,
           anchors=((2, 1), (2, -2)))
    _panel(a, "GreaveBlade" + side, calf, "graphite", knee, ankle, forward,
           ((.137, 1 * sign, 37, .092), (.211, 2 * sign, 58, .093),
            (.39, 3 * sign, 59, .094), (.65, 2 * sign, 45, .099),
            (.701, 0, 30, .096), (.741, 0, 20, .095)), .024, fit=.026,
           anchors=((1, 1), (1, -2), (4, 2)))
    _panel(a, "CalfShield" + side, calf, "graphite", knee, ankle, (-sign * .04, 1, 0),
           ((.273, -26 * sign, 22, .137), (.35, -22 * sign, 33, .139),
            (.52, -14 * sign, 40, .141), (.77, -10 * sign, 35, .104),
            (.86, -11 * sign, 26, .079)), .020, fit=.035, anchors=((3, 2),))
    _boot(a, side, sign, ankle, toe)
