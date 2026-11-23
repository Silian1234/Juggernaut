"""Release LOD0 triangles after all armor has fitted to the original clothes."""

from collections import defaultdict

import bmesh
import bpy
from mathutils.bvhtree import BVHTree


GARMENTS = {
    "Combat shirt": (.52, .008),
    "Combat trousers": (.41, .008),
    "Thigh sheath": (.44, .005),
}
LOD1_GARMENTS = {
    "Combat shirt": (.60, .007),
    "Combat trousers": (.55, .007),
    "Thigh sheath": (.65, .005),
}
SOLE_COMPONENT = 6
TREAD_RIM = 8


def _triangle_count(mesh):
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def _tree(mesh):
    return BVHTree.FromPolygons(
        [v.co for v in mesh.vertices], [tuple(t.vertices) for t in mesh.loop_triangles],
        all_triangles=True,
    )


def _maximum_distance(source, target):
    tree = _tree(target)
    return max(tree.find_nearest(v.co)[3] for v in source.vertices)


def _normalize_skin(obj, rig):
    groups = {g.index: g for g in obj.vertex_groups if g.name in rig.data.bones}
    for v in obj.data.vertices:
        weights = sorted(
            ((g.weight, g.group) for g in v.groups if g.group in groups and g.weight > 0),
            reverse=True,
        )
        retained = weights[:4]
        total = sum(weight for weight, _ in retained)
        if total <= 0:
            raise ValueError(f"{obj.name} vertex {v.index} lost its skinning")
        for _, index in weights[4:]:
            groups[index].remove([v.index])
        for value, index in retained:
            groups[index].add([v.index], value / total, "REPLACE")


def _garment(obj, rig, ratio, distance_limit):
    source = obj.data
    protected = None
    weld = None
    protection_name = "Simplifiable garment panels"
    if obj.name.startswith("Undersuit | Combat shirt LOD"):
        from cloth import armhole_distance

        # Retain the donor faces and weights at the armhole. Budget collapses
        # across this shoulder transition cut through REF_top in raised poses.
        protected = obj.vertex_groups.new(name=protection_name)
        protected.add([v.index for v in source.vertices if armhole_distance(v.co) > 1.17],
                      1, "REPLACE")
        # The LOD0 donor still has split vertices along its UV seams. Joining
        # coincident seams makes the reduced shirt bend as one continuous mesh.
        weld = obj.modifiers.new("Join coincident donor seams", "WELD")
        weld.merge_threshold = 0.000002
    armatures = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
    visible = [mod.show_viewport for mod in armatures]
    for mod in armatures:
        mod.show_viewport = False
    decimate = obj.modifiers.new("V5D garment simplification", "DECIMATE")
    decimate.ratio = ratio
    decimate.use_collapse_triangulate = True
    if protected:
        decimate.vertex_group = protected.name
    try:
        graph = bpy.context.evaluated_depsgraph_get()
        result = bpy.data.meshes.new_from_object(
            obj.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph,
        )
    finally:
        obj.modifiers.remove(decimate)
        if weld is not None:
            obj.modifiers.remove(weld)
        for mod, state in zip(armatures, visible):
            mod.show_viewport = state

    before, after = _triangle_count(source), _triangle_count(result)
    original_area = sum(p.area for p in source.polygons)
    area_ratio = sum(p.area for p in result.polygons) / original_area
    distance = max(_maximum_distance(source, result), _maximum_distance(result, source))
    if before <= after or not .98 <= area_ratio <= 1.02 or distance > distance_limit:
        if protected:
            obj.vertex_groups.remove(protected)
        bpy.data.meshes.remove(result)
        raise ValueError(f"{obj.name} simplification failed, area ratio {area_ratio:.4f}, "
                         f"maximum vertex-to-surface distance {distance * 1000:.2f} mm")
    obj.data = result
    protected = obj.vertex_groups.get(protection_name)
    if protected is not None:
        obj.vertex_groups.remove(protected)
    _normalize_skin(obj, rig)
    if source.users == 0:
        name = source.name
        bpy.data.meshes.remove(source)
        result.name = name
    return {
        "before": before, "after": after, "area_ratio": round(area_ratio, 6),
        "original_area_m2": round(original_area, 6),
        "vertex_surface_max_mm": round(distance * 1000, 3),
    }


def _sole_islands(bm, component):
    pending = {v for face in bm.faces if face[component] == SOLE_COMPONENT for v in face.verts}
    while pending:
        island = [pending.pop()]
        for vertex in island:
            for edge in vertex.link_edges:
                other = edge.other_vert(vertex)
                if other in pending:
                    pending.remove(other)
                    island.append(other)
        yield sorted(island, key=lambda v: v.index)


def _treads(bm, component):
    """Keep outsole and tread contact profiles, removing each tread's third rim."""
    remap = {}
    centers = []
    pending = list(_sole_islands(bm, component))
    for island in pending:
        if len(island) != 3 * TREAD_RIM + 1:
            continue
        base, bevel, contact = (
            island[:TREAD_RIM], island[TREAD_RIM:2 * TREAD_RIM],
            island[2 * TREAD_RIM:3 * TREAD_RIM],
        )
        center = island[-1]
        if not center.is_manifold or len(center.link_faces) != TREAD_RIM:
            continue
        if not all((a.co.xy - b.co.xy).length < .00001 and
                   min(abs(a.co.z - b.co.z - rise) for rise in (.011, .014)) < .00001 and
                   abs(b.co.z - c.co.z - .003) < .00001
                   for a, b, c in zip(base, bevel, contact)):
            continue
        remap.update(zip(bevel, base))
        centers.append(center)
    if centers:
        bmesh.ops.dissolve_verts(bm, verts=centers, use_face_split=False, use_boundary_tear=False)
        bmesh.ops.weld_verts(bm, targetmap=remap)
    return len(centers)


def _leg_treads(obj):
    source = obj.data
    before = _triangle_count(source)
    bm = bmesh.new()
    try:
        bm.from_mesh(source)
        original = bm.verts.layers.int.new("V5D source vertex")
        for vertex in bm.verts:
            vertex[original] = vertex.index
        component = bm.faces.layers.int["armor_component"]
        count = _treads(bm, component)
        if not count:
            return None
        bm.verts.index_update()
        indices = {vertex[original]: vertex.index for vertex in bm.verts}
        bm.verts.layers.int.remove(original)
        depths = {
            key: [indices[index] for index in obj[key]]
            for key in obj.keys() if key.startswith("panel_depth_pairs_")
        }
        bm.to_mesh(source)
    finally:
        bm.free()
    source.update()
    for key, value in depths.items():
        obj[key] = value
    return {"before": before, "after": _triangle_count(source), "treads": count}


def optimize(lod, collection, rig):
    """Simplify selected LOD0 meshes and report the released triangle counts."""
    if lod != 0:
        return {}
    changes = {}
    modules = defaultdict(int)
    for obj in list(collection.all_objects):
        if obj.type != "MESH":
            continue
        part = obj.get("part")
        label = obj.name.removeprefix("Undersuit | ").removesuffix(" LOD0")
        result = None
        if part == "cloth" and label in GARMENTS:
            result = _garment(obj, rig, *GARMENTS[label])
        elif part == "leg_plates" and obj.name in ("LegArmour_L_LOD0", "LegArmour_R_LOD0"):
            result = _leg_treads(obj)
        if result:
            result["saved"] = result["before"] - result["after"]
            changes[obj.name] = result
            modules[part] += result["saved"]
    print(f"V5D triangle savings by part: {dict(sorted(modules.items()))}", flush=True)
    for name, result in sorted(changes.items()):
        print(f"V5D triangle savings {name}: {result}", flush=True)
    return changes


ARMOR_LIMITS = {"leg_plates": .0025, "arm_plates": .002, "additional_plates": .0018}
SOFT_GEAR_LIMITS = {
    "Boot laces and heel counters": (.0025, .0035),
    "Tactical gloves": (.0035, .0035),
    "Combat boots": (.0025, .0035),
    "Trouser inseams": (.0025, .0035),
    "Glove hems and knuckle welts": (.0025, .0025),
}
ARMOR_RATIOS = (.32, .36, .42, .52, .60, .68, .76, .84, .92)
ROLE_ATTRIBUTES = ("armor_component", "v5c_plate", "v5c_inner", "v5c_outer", "v5d_inner")


def _topology(mesh):
    """Count components and nonmanifold incidences independently of vertex order."""
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        pending = set(bm.verts)
        components = 0
        while pending:
            visited = [pending.pop()]
            components += 1
            for vertex in visited:
                for edge in vertex.link_edges:
                    other = edge.other_vert(vertex)
                    if other in pending:
                        visited.append(other)
                        pending.remove(other)
        abnormal = sum(not e.is_manifold and not e.is_boundary for e in bm.edges)
        boundary = sum(e.is_boundary for e in bm.edges)
        return components, abnormal, bool(boundary)
    finally:
        bm.free()


def _role_surfaces(mesh, leg=False):
    """Gather separate BVHs and independent vertex and centroid samples by plate role."""
    attributes = [mesh.attributes[name].data for name in ROLE_ATTRIBUTES
                  if name in mesh.attributes]
    vertices = [v.co.copy() for v in mesh.vertices]
    faces = defaultdict(list)
    combinations = set()
    mesh.calc_loop_triangles()
    for t in mesh.loop_triangles:
        role = tuple(data[t.polygon_index].value for data in attributes)
        combinations.add((*role, mesh.polygons[t.polygon_index].material_index))
        # The inner-field tag is a semantic boundary on one continuous leg shell.
        faces[role[:1] if leg else role].append(tuple(t.vertices))
    samples = {}
    trees = {}
    for role, triangles in faces.items():
        used = {v for t in triangles for v in t}
        samples[role] = [vertices[v] for v in used]
        samples[role].extend((vertices[a] + vertices[b] + vertices[c]) / 3
                             for a, b, c in triangles)
        trees[role] = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    return trees, samples, combinations


def _armor_distances(original, candidate):
    before_trees, before_samples, before_tags = original
    after_trees, after_samples, after_tags = candidate
    if before_tags != after_tags:
        return float("inf")
    return max(
        tree[role].find_nearest(point)[3]
        for tree, samples in ((before_trees, after_samples), (after_trees, before_samples))
        for role, points in samples.items() for point in points
    )


def _depth_updates(obj, candidate):
    """Track surviving depth witnesses through topology edits by their original face roles."""
    from mathutils.kdtree import KDTree

    keys = [key for key in obj.keys() if key.startswith("panel_depth_pairs_")]
    if not keys:
        return {}
    original = obj.data
    role = candidate.attributes["armor_component"].data
    inner = candidate.attributes["v5c_inner"].data
    by_role = defaultdict(set)
    for p in candidate.polygons:
        by_role[(role[p.index].value, bool(inner[p.index].value))].update(p.vertices)
    updates = {}
    for key in keys:
        part = int(key.rsplit("_", 1)[1])
        states = [by_role[(part, True)], by_role[(part, False)] - by_role[(part, True)]]
        trees = []
        for indices in states:
            if not indices:
                return None
            tree = KDTree(len(indices))
            for i in sorted(indices):
                tree.insert(candidate.vertices[i].co, i)
            tree.balance()
            trees.append(tree)
        remapped = []
        samples = list(obj[key])
        for a, b in zip(samples[::2], samples[1::2]):
            p, q = (original.vertices[i].co for i in (a, b))
            x, ia, da = trees[0].find(p)
            y, ib, db = trees[1].find(q)
            if max(da, db) <= .0015 and abs((x - y).length - (p - q).length) <= .00075:
                remapped.extend((ia, ib))
        if len(remapped) < 6:
            return None
        updates[key] = remapped
    return updates


def _original_armor(obj, rig, limit, needed):
    original = obj.data
    if original.shape_keys or len(original.polygons) < 4 or _triangle_count(original) < 20:
        return None

    leg = obj.get("part") == "leg_plates"
    reference = _role_surfaces(original, leg)
    topology = _topology(original)
    before = _triangle_count(original)
    armatures = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
    visible = [mod.show_viewport for mod in armatures]
    for mod in armatures:
        mod.show_viewport = False
    decimate = obj.modifiers.new("V5D original armor reduction", "DECIMATE")
    decimate.use_collapse_triangulate = True
    result = None
    try:
        ratios = ARMOR_RATIOS
        if needed < before:
            ratios = sorted(ratios, key=lambda ratio: (before * (1 - ratio) < needed,
                                                       abs(before * (1 - ratio) - needed)))
        for ratio in ratios:
            decimate.ratio = ratio
            graph = bpy.context.evaluated_depsgraph_get()
            candidate = bpy.data.meshes.new_from_object(
                obj.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph,
            )
            after = _triangle_count(candidate)
            if before > after and _topology(candidate) == topology:
                distance = _armor_distances(reference, _role_surfaces(candidate, leg))
                if distance <= limit:
                    depths = _depth_updates(obj, candidate)
                    if depths is not None:
                        result = candidate
                        break
            bpy.data.meshes.remove(candidate)
    finally:
        obj.modifiers.remove(decimate)
        for mod, state in zip(armatures, visible):
            mod.show_viewport = state
    if result is None:
        return None
    obj.data = result
    if armatures and obj.vertex_groups:
        _normalize_skin(obj, rig)
    for key, value in depths.items():
        obj[key] = value
    if original.users == 0:
        name = original.name
        bpy.data.meshes.remove(original)
        result.name = name
    return {"before": before, "after": after, "saved": before - after,
            "role_vertex_centroid_max_mm": round(distance * 1000, 3)}


def _leg_roles(obj):
    """Return the disconnected role IDs, verifying they have no shared vertices."""
    ids = set()
    seen = {}
    roles = obj.data.attributes["armor_component"].data
    for face in obj.data.polygons:
        role = roles[face.index].value
        ids.add(role)
        for i in face.vertices:
            if seen.setdefault(i, role) != role:
                return ()
    return sorted(ids)


def _extract_leg_role(obj, role):
    copied = obj.data.copy()
    bm = bmesh.new()
    try:
        bm.from_mesh(copied)
        source = bm.verts.layers.int.new("V5D original vertex index")
        for v in bm.verts:
            v[source] = v.index
        attr = bm.faces.layers.int["armor_component"]
        keep = {v for face in bm.faces if face[attr] == role for v in face.verts}
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
        bm.verts.index_update()
        indices = {v[source]: v.index for v in bm.verts}
        bm.verts.layers.int.remove(source)
        bm.to_mesh(copied)
    finally:
        bm.free()
    return copied, indices


def _leg_armor(obj, collection, rig, needed):
    roles = _leg_roles(obj)
    if not roles:
        return None
    original = obj.data
    before = _triangle_count(original)
    distance = 0
    saved = 0
    depth_updates = {}
    assembled = bmesh.new()
    try:
        for role in roles:
            key = f"panel_depth_pairs_{role}"
            temporary = obj.copy()
            temporary.data, indices = _extract_leg_role(obj, role)
            for prop in list(temporary.keys()):
                if prop.startswith("panel_depth_pairs_"):
                    del temporary[prop]
            if key in obj:
                temporary[key] = [indices[index] for index in obj[key]]
            collection.objects.link(temporary)
            try:
                change = (_original_armor(temporary, rig, ARMOR_LIMITS["leg_plates"], needed - saved)
                          if role != SOLE_COMPONENT and needed > saved else None)
                if change:
                    saved += change["saved"]
                    distance = max(distance, change["role_vertex_centroid_max_mm"])
                if key in temporary:
                    offset = len(assembled.verts)
                    depth_updates[key] = [offset + i for i in temporary[key]]
                assembled.from_mesh(temporary.data)
            finally:
                scratch = temporary.data
                bpy.data.objects.remove(temporary, do_unlink=True)
                bpy.data.meshes.remove(scratch)
        if not saved:
            return None
        assembled.to_mesh(original)
    finally:
        assembled.free()
    for key, value in depth_updates.items():
        obj[key] = value
    return {"before": before, "after": _triangle_count(original), "saved": saved,
            "role_vertex_centroid_max_mm": distance}

def _lod1_cloth(meshes, rig, remaining):
    changes = {}
    for obj in meshes:
        if remaining <= 0:
            break
        if obj.get("part") != "cloth":
            continue
        label = obj.name.removeprefix("Undersuit | ").removesuffix(" LOD1")
        if label not in LOD1_GARMENTS:
            continue
        result = _garment(obj, rig, *LOD1_GARMENTS[label])
        result["saved"] = result["before"] - result["after"]
        remaining -= result["saved"]
        changes[obj.name] = result
        print(f"V5D LOD1 additional triangle savings {obj.name}: {result}", flush=True)
    return changes

def _simplify_soft_gear(lod, meshes, rig, remaining):
    changes = {}
    clothes = {obj.name.removeprefix("Undersuit | ").removesuffix(f" LOD{lod}"): obj
               for obj in meshes if obj.get("part") == "cloth"}
    for label, tolerances in SOFT_GEAR_LIMITS.items():
        if remaining <= 0:
            break
        obj = clothes.get(label)
        if obj is None:
            continue
        result = _original_armor(obj, rig, tolerances[lod], remaining)
        if result:
            changes[obj.name] = result
            remaining -= result["saved"]
            print(f"V5D LOD{lod} additional triangle savings {obj.name}: {result}", flush=True)
    return changes


def optimize_existing_armor(lod, collection, rig, target_triangles=None):
    """Release triangles from armor shells and soft gear toward a worn total."""
    meshes = [obj for obj in collection.all_objects if obj.type == "MESH"]
    remaining = None if target_triangles is None else (
        sum(_triangle_count(obj.data) for obj in meshes) - target_triangles
    )
    changes = {}
    modules = defaultdict(int)
    limb_armor = (f"LegArmour_L_LOD{lod}", f"LegArmour_R_LOD{lod}")
    priority = ("arm_plates", "additional_plates", "leg_plates")
    allowed = (obj for obj in meshes if obj.get("part") in priority)
    for obj in sorted(allowed, key=lambda obj: priority.index(obj.get("part"))):
        if remaining is not None and remaining <= 0:
            break
        part = obj.get("part")
        if part not in ARMOR_LIMITS:
            continue
        if part == "leg_plates" and obj.name not in limb_armor:
            continue
        needed = float("inf") if remaining is None else remaining
        result = (_leg_armor(obj, collection, rig, needed) if part == "leg_plates"
                  else _original_armor(obj, rig, ARMOR_LIMITS[part], needed))
        if result:
            changes[obj.name] = result
            modules[part] += result["saved"]
            if remaining is not None:
                remaining -= result["saved"]
    print(f"V5D LOD{lod} additional triangle savings by part: {dict(sorted(modules.items()))}",
          flush=True)
    for part, saved in sorted(modules.items()):
        distances = [result["role_vertex_centroid_max_mm"] for name, result in changes.items()
                     if bpy.data.objects[name].get("part") == part]
        print(f"V5D LOD{lod} {part} reduced by {saved} triangles, "
              f"sampled maximum deviation {max(distances):.3f} mm", flush=True)
    if lod == 1 and remaining is not None and remaining > 0:
        cloth_changes = _lod1_cloth(meshes, rig, remaining)
        changes.update(cloth_changes)
        remaining -= sum(result["saved"] for result in cloth_changes.values())
    if remaining is not None and remaining > 0:
        changes.update(_simplify_soft_gear(lod, meshes, rig, remaining))
    return changes
