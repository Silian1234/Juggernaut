# V5 bake: textures for the approved V5d geometry

**The user approved the V5d model** ("I like how it turned out"). **The geometry is frozen.** Do not move, add or remove plates, do not change the frame or the helmet, do not change the skinning. You may only fix tiny geometric issues that would break the bake (e.g. overlapping UVs, flipped normals).

The next step is the **textured (baked) model**. The user wants to see it rendered.

## Look of the materials (match ref3: `docs/feedback/refs_gpt/ref3.png`, `crop_front.png`, `crop_helmet.png`)
| Material | Look |
|---|---|
| **Khaki/coyote armor plates** | Painted composite. Worn, matte paint with **chipped edges** showing dark material underneath, scuffs and scratches, dust and dirt in recesses, slightly darker grime toward the bottom of the legs. Small stencil marks and numbers are fine (no real brands). |
| **Dark segmented thigh plates and dark pieces** | Dark grey/black painted, the same wear language. |
| **Undersuit and fabric** | Black ballistic nylon/cordura with a visible **weave**, seams and stitching, light dust. Webbing straps with a nylon texture, black plastic buckles. |
| **Carrier and pouches** | Black/ranger-green Cordura, MOLLE webbing, velcro patches, fabric wear. |
| **Exoskeleton frame** | Dark gunmetal painted metal. **Worn bare metal on the edges** and on the actuator caps, screws, oily grime around the joints, small labels/warning decals. |
| **Hydraulic hoses** | Yellow rubber/braided sleeve with dirt and fittings. |
| **Helmet** | Dark grey shell with a fabric/rubberised texture, khaki applique plates with wear, metal screws, rails. **Glossy dark visor** with reflection. |
| **Backpack** | Painted housing with the yellow warning triangle, vents, the cell indicator. |

## Technical
- **Bake to atlases for the EFT shader**, the same as your previous EXO/Juggernaut bundles: albedo (sRGB), tangent-space normal (OpenGL +Y unless the EFT pipeline needs otherwise; use what your earlier working bundles used), and gloss/specular.
- **Normal maps carry the fine detail:** panel seams, rivets, the fabric weave, scratches, MOLLE.
- **Texel density:** good enough for first person (hands/forearms) and the inventory preview. Suggested split (adjust as needed):
  - suit and plates: 2× 4096;
  - frame and backpack: 1× 2048–4096;
  - helmet: 1× 2048.
  - Keep the total sane for one player-only item.
- LOD1 uses the same atlases.
- Keep the triangle counts (≤ 80k LOD0).

## Deliverables (in `art/v5-astra/`)
- **Textured renders** in Cycles on the GPU (OptiX), in `renders/textured/`:
  - `sheet.png`: 5 views as before;
  - `helmet.png`, `legs_front.png`, `legs.png`, `arms.png`;
  - `closeup_plate.png`: a close-up of a plate edge and the frame, to judge the wear and normals;
  - `pose.png`.
  - Same backdrop and lighting as before, plus a version on a darker background like ref3: `sheet_dark.png`.
- The texture files in `textures/`, with sizes listed in `REPORT.md`.
- `REPORT.md`:
  - the atlas list (size, channels, colour space);
  - texel density;
  - anything that could not be baked well;
  - a comparison against ref3.

No bundles yet, and no game. Work only in `art/v5-astra/`.
