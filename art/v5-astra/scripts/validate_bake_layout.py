"""Check the packed atlas triangulation at actual texel centers."""
from collections import Counter
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent / "work" / "bake"

cut_file = ROOT.parent.parent / "source" / "bake" / "uv_cuts.json"
cuts = {tuple(pair) for pair in json.loads(cut_file.read_text())} if cut_file.exists() else set()
regular_file = ROOT.parent.parent / "source" / "bake" / "uv_regularized.json"
regularized = {tuple(pair) for pair in json.loads(regular_file.read_text())} if regular_file.exists() else set()
for path in sorted(ROOT.glob("*.npz")):
    with np.load(path) as source:
        size = int(source["resolution"])
        uv = source["uv"].astype(np.float64) * size
        pos = source["pos"].astype(np.float64)
        names = source["object_names"][source["obj"]]
        islands = source["island"]
        polygons = source["polygon"]
    occupied = np.full((size, size), -1, dtype=np.int32)
    overlaps = Counter()
    overlap_texels = 0
    degenerate = Counter()
    for i, (p, q, r) in enumerate(uv):
        a, b = q - p, r - p
        determinant = a[0] * b[1] - a[1] * b[0]
        if abs(determinant) <= 1e-8:
            area = np.linalg.norm(np.cross(pos[i, 1] - pos[i, 0], pos[i, 2] - pos[i, 0]))
            degenerate[(names[i], area > 1e-10)] += 1
            cuts.add((str(names[i]), int(polygons[i])))
            regularized.add((str(names[i]), int(polygons[i])))
            continue
        x0, y0 = np.floor(uv[i].min(axis=0)).astype(int)
        x1, y1 = np.ceil(uv[i].max(axis=0)).astype(int)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        xx, yy = xx + .5 - p[0], yy + .5 - p[1]
        u = (xx * b[1] - yy * b[0]) / determinant
        v = (yy * a[0] - xx * a[1]) / determinant
        mask = (u > 1e-5) & (v > 1e-5) & ((u + v) < (1 - 1e-5))
        target = occupied[y0:y1, x0:x1]
        old = target[mask]
        old = old[old >= 0]
        overlap_texels += len(old)
        for previous in np.unique(old):
            overlaps[(names[i], names[previous], bool(islands[i] == islands[previous]))] += 1
            cuts.add((str(names[i]), int(polygons[i])))
            cuts.add((str(names[previous]), int(polygons[previous])))
            if names[i] == names[previous] and polygons[i] == polygons[previous]:
                regularized.add((str(names[i]), int(polygons[i])))
        target[mask] = i
    print(path.stem, "overlap_texels", overlap_texels, "tri_pairs", sum(overlaps.values()),
          "overlap_sources", overlaps.most_common(12), "zero", degenerate, flush=True)

cut_file.write_text(json.dumps(sorted(cuts), indent=2))


regular_file.write_text(json.dumps(sorted(regularized), indent=2))


