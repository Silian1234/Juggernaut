"""Head-mounted soft seal for the gap between the crown and suit collar."""

from math import cos, exp, sin, tau


# Radii at 15-degree intervals from the chin to the nape, relative to the
# original EFT Head attachment pivot. Lower rows tuck into the suit collar.
PROFILES = (
    (1.574, (.079, .077, .076, .077, .077, .078, .079, .080, .083, .088, .088, .084, .079)),
    (1.588, (.108, .103, .093, .085, .078, .074, .072, .071, .070, .071, .072, .070, .066)),
    (1.595, (.141, .132, .114, .096, .085, .080, .077, .075, .076, .079, .080, .077, .071)),
    (1.609, (.146, .137, .120, .106, .091, .082, .078, .076, .075, .077, .078, .074, .070)),
    (1.630, (.145, .136, .122, .110, .094, .083, .079, .075, .073, .073, .073, .069, .068)),
    (1.649, (.149, .138, .125, .113, .093, .082, .079, .075, .073, .073, .073, .069, .068)),
    (1.666, (.159, .142, .129, .116, .099, .085, .081, .077, .075, .075, .074, .069, .068)),
    (1.688, (.162, .139, .130, .115, .100, .095, .082, .080, .079, .079, .078, .074, .072)),
)


def head_cowl(api, collection, m, low_detail):
    """Seat an independently formed fabric seal around the lower jaw."""
    side_count = 48 if low_detail else 72
    x, y = -.00062798, .02180314
    points = []
    faces = []
    # Return the last and first stations inwards to finish the sewn edge.
    for z, profile, retreat in (
        *((z, row, 0) for z, row in PROFILES),
        (PROFILES[-1][0] - .002, PROFILES[-1][1], .004),
        (PROFILES[0][0] + .002, PROFILES[0][1], .004),
    ):
        for step in range(side_count):
            angle = tau * step / side_count
            station = 24 * min(step, side_count - step) / side_count
            index = min(int(station), 11)
            blend = station - index
            radius = profile[index] * (1 - blend) + profile[index + 1] * blend - retreat
            # Relieve the forward flanks by the RAC microphone seat.
            height_gate = ((z - 1.598) / .011) ** 2
            angle_gate = ((station * 15 - 34) / 13) ** 2
            radius -= .018 * exp(-height_gate - angle_gate)
            points.append((x + radius * sin(angle), y - radius * cos(angle), z))
    row_count = len(points) // side_count
    for row in range(row_count):
        following = (row + 1) % row_count
        for side in range(side_count):
            next_side = (side + 1) % side_count
            faces.append((row * side_count + side, row * side_count + next_side,
                          following * side_count + next_side, following * side_count + side))
    return api.surface(collection, "Helmet - fitted fabric jaw seal", points, faces, [m["gasket"]])
