# V5 bake, pass 2: real materials, not painted spots

The user rejected the first bake: **"I expected a metal texture, not plastic with a scuffed mesh stretched over it."**

Claude checked the maps in `textures/v5d/` and confirmed:
- **`frame_normal.png` is almost flat**: a uniform 128/128/255 fill with faint outlines and a few garbage pixels (stray coloured marks). The normal maps carry no surface relief.
- **The wear is random noise over whole surfaces** (large blotches in the middle of plates), not edge wear driven by the geometry. It reads like camo spots.
- **The renders use a flat grey studio with nothing to reflect**, so even correct metal reads as matte plastic.

**The geometry, UVs, rig and skinning stay frozen (V5d).** Redo only the materials, the bake and the renders.

## Required material work
1. **Bake from the geometry first:** ambient occlusion, curvature (convex edges and concave cavities) and position/height gradient for every atlas. **Drive all wear and grime from these masks**, combined with noise for breakup:
   - paint chips and scratches **on convex edges, corners, bolt heads and high-contact zones** (knees, elbows, the front of the shins, the frame edges);
   - small sparse scratches on flat areas;
   - dirt, dust and oil **in cavities, seams and around joints**;
   - more grime toward the boots.
   - **No large random blotches in the middle of plates.**
2. **Normal maps with real relief** (visible in a raking-light close-up):
   - panel seams and recessed lines;
   - screw and rivet heads where the geometry does not have them;
   - chipped paint edges as a slight height step;
   - fine scratches;
   - small dents on plates;
   - cast/machined texture on the actuator housings;
   - knurling or ribs on caps;
   - the fabric weave and stitching, MOLLE webbing;
   - the rubber hose texture.
   - Bake the high-frequency detail from procedural height (bump) into tangent space, with proper strength; the current maps are near zero.
   - Remove the corrupted pixels.
3. **Material separation in the spec/gloss maps** (the EFT shader is a specular/gloss workflow, `p0/Reflective/Bumped Specular SMap`; `_SpecMap` RGB is specular, A is gloss):

   | Material | Base | Spec | Gloss |
   |---|---|---|---|
   | **Frame, actuators, backpack housing** | dark gunmetal/blued painted steel, grimy | painted ≈0.15–0.25 | painted ≈0.35–0.5 |
   |  — chips | bare steel with bright metallic reflection | ≈0.7–0.9, steel-tinted | ≈0.6–0.75 |
   |  — around the joints | oily dark grime | — | slightly glossier |
   | **Bolts, piston rods, axle caps** | polished or worn metal | high | high |
   | **Khaki plates** | **matte paint**, olive-khaki (not pinkish beige; match ref3's olive-tan) | ≈0.05 | ≈0.25 |
   |  — chips | dark grey composite underneath | ≈0.08–0.12, **not metallic** | ≈0.35 |
   | **Dark segmented thigh plates** | dark painted composite, same rules | | |
   | **Fabric, webbing** | — | very low | near zero |
   | **Rubber hoses** | yellow sleeve | low | ≈0.3 |
   | **Visor** | — | high | very high (glossy) |
   | **Helmet shell** | rubberised paint, matte with a slight sheen | | |

   The spec/gloss contrast between paint, bare metal and fabric must be clearly visible in the maps themselves (check the histograms).
4. **Colour:**
   - plates: **olive-tan/khaki**, as in `ref3.png`, not pink/beige;
   - frame: **dark** gunmetal, not light aluminium.

## Render setup (the evaluation depends on it)
- **Use an HDRI environment** for reflections, for example a CC0 studio or outdoor HDRI from Poly Haven (download it into `art/v5-astra/hdri/`). Keep a dark background visible (as in ref3) and use the HDRI for lighting and reflections. Add a rim light.
- Render on the GPU (OptiX). Reconstruct the materials in Blender from the **same maps** that go into the game, so the render shows what EFT will get (spec → specular tint, gloss → 1 − roughness).

## Deliverables (in `renders/textured/`, overwrite)
- `sheet_dark.png` (5 views) and `sheet.png`.
- `helmet.png`.
- **`closeup_frame.png`**: a knee actuator and frame links in raking light, so the reflections and the relief are visible.
- **`closeup_plate.png`**: a plate edge with chips, so edge wear and the composite underneath are visible.
- `closeup_fabric.png`: the carrier/undersuit weave.
- **`maps_preview.png`**: a contact sheet of all the atlases (albedo, normal, spec, gloss, AO, curvature), so the user can see that the maps carry detail.
- Update `REPORT.md`:
  - for each atlas, the mean/min/max of spec and gloss per material ID;
  - a statement that the normal maps were checked for corruption;
  - what changed versus pass 1.

No geometry changes, no bundles, no game. Work only in `art/v5-astra/`.
