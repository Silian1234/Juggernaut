"""Two short, independent hip tassets close the gap above the front thigh lames."""

from v5d_pelvis import Garment, front_or_rear, plate
from v5d_torso import match_shell_diagonals


def build(lod, collection, rig):
    trousers = Garment(collection.all_objects[f"Undersuit | Combat trousers LOD{lod}"])
    # The lateral corner rises toward the hip hinge. The narrow inside corner
    # gives the codpiece room to pass over the thigh when the hip flexes.
    levels = (
        (.793, .077, .107), (.805, .058, .143), (.831, .055, .163),
        (.856, .061, .170), (.882, .084, .163), (.900, .101, .146),
        (.908, .117, .138),
    )
    if lod:
        levels = tuple(levels[i] for i in (0, 1, 3, 4, 6))
    width = 5 if lod == 0 else 4
    for sign, side in ((1, "L"), (-1, "R")):
        shell = plate(collection, rig, trousers, lod, "Anterior hip tasset", "hip coverage",
                      side, width, levels, front_or_rear(sign, -1), .007, .0025, lift=.009)
        match_shell_diagonals(shell, width, len(levels), chamfer=False)
