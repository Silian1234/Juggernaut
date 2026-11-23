"""Cast stand-offs on the new shells mate with the stock V5B bracket shoes."""
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from legs import CALF, THIGH, blend_skin, cut_box


def fit_standoffs(geo, mounts):
    # Coordinates are expressed on the positive half of the character.
    points = [Vector((geo.side * x, y, z)) for x, y, z in geo.vertices]
    for component, name, sites in (
        (1, "thigh", ((-.018, .825), (-.018, .660))),
        (4, "shin", ((.017, .394), (.031, .188))),
    ):
        faces = [f for i, f in enumerate(geo.faces) if geo.armor_components[i] == component]
        surface = BVHTree.FromPolygons(points, faces)
        for y, z in sites:
            footprint = cut_box(.009, .008, .003)
            # Offset inside the frozen bracket's spreader plate, with a lower
            # shell seat when the bracket straddles the upper hem of the thigh.
            socket = Vector(mounts[name](y, z))
            socket.x += .001
            hits = []
            for shift in (0, -.009, .009, -.018, .018, -.027, .027, -.036):
                trial = []
                for dy, dz in footprint:
                    hit, _, _, _ = surface.ray_cast(
                        Vector((.46, y + dy, z + dz + shift)), Vector((-1, 0, 0)), .33)
                    if hit is None:
                        break
                    trial.append(hit)
                if len(trial) == len(footprint):
                    hits = trial
                    break
            if not hits:
                raise ValueError(f"No seat for {name} bracket at {z:.3f}")
            geo.armor_component = 12 if name == "thigh" else 13
            base = THIGH if name == "thigh" else CALF
            def skin(point):
                if name == "thigh":
                    factor = .72 * max(0, min(1, (point[1] - .024) / .040))
                    return blend_skin(geo, point, base, factor)
                from v5c_shin import greave_skin
                return greave_skin(geo, point)
            rings = []
            for t, scale in ((0., 1.12), (.15, 1.), (.79, .8), (1., .8)):
                ring = []
                for hit, (dy, dz) in zip(hits, footprint):
                    root = hit - Vector((.0016, 0, 0))
                    end = socket + Vector((0, dy, dz))
                    point = root.lerp(end, t)
                    point.y += dy * (scale - 1)
                    point.z += dz * (scale - 1)
                    ring.append(point)
                rings.append(geo.add(ring, [], skin if t < .5 else base, "gunmetal"))
            n = len(footprint)
            geo.record(tuple(rings[0] + i for i in reversed(range(n))), "gunmetal")
            for a, b in zip(rings, rings[1:]):
                geo.join(a, b, n, "gunmetal")
            geo.record(tuple(rings[-1] + i for i in range(n)), "gunmetal")
    geo.armor_component = 0
