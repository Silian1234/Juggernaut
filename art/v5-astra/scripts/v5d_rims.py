"""Ease local backing folds that remain after the final armor fit."""

import bmesh
from mathutils import Vector


# Local-space anchors from the audited panel meshes. The source index is only
# a hint. A topology change can move a vertex to a different index.
FIT_TOLERANCE = .00015
HIP_QUAD = (
    (5, (-.142865509, -.144185066, .915000021)),
    (6, (-.205813959, -.096446447, .915000021)),
    (1, (-.227238193, -.064658843, .879000008)),
    (0, (-.199973434, -.112106033, .879000008)),
)
REPAIRS = {
    (0, 'L Forearm rear spine'): (
        (26, (0.406176448, -0.362672567, 1.334238052), (-0.000153506, -0.000098575, -0.000292767)),
        (39, (0.423928320, -0.358616799, 1.347386360), (0.000111604, -0.000016048, -0.000038318)),
    ),
    (0, 'L Forearm wrist extension'): (
        (3, (0.340714693, -0.363012612, 1.341962457), (-0.000041639, -0.000139660, -0.000066914)),
        (20, (0.334030867, -0.385903925, 1.406340599), (-0.000130298, 0.000357704, 0.000109488)),
        (10, (0.330045909, -0.386627406, 1.408259273), (0.000004860, -0.000044909, 0.000062451)),
        (9, (0.339045525, -0.384344906, 1.422059536), (-0.000252168, -0.000137131, -0.000116630)),
        (15, (0.333465040, -0.396528333, 1.395247340), (-0.000187989, -0.000121483, 0.000041532)),
        (17, (0.322346747, -0.365735024, 1.378771901), (-0.000022114, -0.000097442, -0.000003997)),
        (13, (0.371836483, -0.380510360, 1.335829139), (-0.000193333, 0.000028765, 0.000042368)),
    ),
    (0, 'R Biceps elbow bridge'): (
        (2, (-0.360460401, -0.075780638, 1.474915147), (0.000041236, -0.000113293, 0.000101088)),
        (27, (-0.336323529, -0.116328642, 1.494515419), (-0.000501914, 0.000153935, -0.000453651)),
        (3, (-0.337688565, -0.101993650, 1.492259860), (0.000364166, 0.000096202, 0.000797816)),
        (8, (-0.321938396, -0.128063008, 1.494595528), (-0.000176834, 0.000200149, 0.000280952)),
    ),
    (1, 'L Forearm wrist extension'): (
        (21, (0.330999255, -0.386454314, 1.407800317), (0.000067480, 0.000111312, -0.000041632)),
        (11, (0.327014297, -0.387177795, 1.409718990), (0.000127657, 0.000010260, 0.000022175)),
        (15, (0.332715780, -0.396469295, 1.404834390), (0.000173247, 0.000105592, -0.000022053)),
        (10, (0.336541802, -0.384781450, 1.424418330), (-0.000086680, -0.000158887, -0.000063886)),
        (17, (0.334737629, -0.397176474, 1.368813157), (0.000069521, -0.000001781, 0.000056944)),
        (16, (0.330062687, -0.397172928, 1.395954132), (-0.000047068, 0.000105843, 0.000106412)),
    ),
    (1, 'V5D Armor | Belt hip yoke L LOD1'): (
        (24, (0.181826934, 0.094332933, 0.963999987), (-0.000490600, -0.000058347, 0.000189174)),
        (23, (0.198362887, 0.052863780, 0.963999987), (0.000066330, 0.000023595, 0.000071018)),
        (40, (0.194050193, -0.095256016, 0.961000025), (-0.000288099, 0.000567699, -0.000206153)),
        (28, (0.176019311, 0.078139298, 1.001000047), (-0.000193507, -0.000041883, 0.000135244)),
        (3, (0.208558202, 0.054244507, 0.963999987), (-0.000131702, 0.000027261, -0.000159696)),
        (25, (0.149939537, -0.118668556, 1.001000047), (-0.000092567, -0.000003105, -0.000037705)),
        (5, (0.157235160, -0.125707716, 1.001000047), (-0.000171836, -0.000140704, 0.000646034)),
        (9, (0.141699925, 0.128856599, 1.001000047), (-0.000159696, 0.000303893, 0.000503033)),
        (11, (0.190529108, -0.044289891, 1.036999941), (-0.000019716, 0.000172952, -0.000045485)),
        (4, (0.191272885, 0.097882852, 0.963999987), (-0.000049793, 0.000100749, 0.000121176)),
        (20, (0.186254025, -0.091730691, 0.963999987), (-0.000036252, -0.000016560, -0.000094669)),
        (0, (0.195526525, -0.097591810, 0.963999987), (-0.000016385, -0.000092242, 0.000015206)),
        (53, (0.152141839, -0.126141846, 1.001000047), (-0.000192905, -0.000084334, -0.000119569)),
    ),
}


def _source_vertex(mesh, index, anchor):
    anchor = Vector(anchor)
    if index < len(mesh.vertices) and (mesh.vertices[index].co - anchor).length < FIT_TOLERANCE:
        return mesh.vertices[index]
    matches = [vertex for vertex in mesh.vertices
               if (vertex.co - anchor).length < FIT_TOLERANCE]
    if len(matches) != 1:
        raise ValueError(f"{mesh.name}: expected one source vertex near {tuple(anchor)}")
    return matches[0]


def _split_hip_quad(mesh):
    # The coarse, twisted outer quad dives through the backing on its default
    # diagonal. Bake the other diagonal without moving either shell.
    indices = [_source_vertex(mesh, index, anchor).index for index, anchor in HIP_QUAD]
    cage = bmesh.new()
    try:
        cage.from_mesh(mesh)
        cage.verts.ensure_lookup_table()
        corners = [cage.verts[index] for index in indices]
        faces = [face for face in corners[0].link_faces if set(face.verts) == set(corners)]
        if len(faces) != 1:
            raise ValueError(f"{mesh.name}: expected the original outer hip quad")
        bmesh.utils.face_split(faces[0], corners[1], corners[3])
        cage.to_mesh(mesh)
    finally:
        cage.free()
    mesh.update()


def fit(lod, collection):
    """Apply the audited local changes to the matching LOD."""
    objects = {obj.name.split(".")[0]: obj for obj in collection.all_objects
               if obj.type == "MESH"}
    for (level, name), repairs in REPAIRS.items():
        if level != lod:
            continue
        mesh = objects[name].data
        if mesh.shape_keys or mesh.users != 1:
            raise ValueError(f"{mesh.name}: unexpected shape keys or shared mesh data")
        vertices = [(_source_vertex(mesh, index, anchor), delta)
                    for index, anchor, delta in repairs]
        for vertex, delta in vertices:
            vertex.co += Vector(delta)
        mesh.update()
    if lod == 1:
        _split_hip_quad(objects["V5D Armor | Lower hip lame R LOD1"].data)
