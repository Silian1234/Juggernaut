# Model competition: rebuild the Juggernaut to match the reference sheet

The user rejected every previous version, both yours (v1–v4) and Claude's mockups. The user has now generated concept sheets and wants a **competition**: you (GPT via Codex) and Claude each build the set independently. The user picks the winner from the renders. The winner's model then goes into the bundles.

**Goal: reproduce the reference as closely as possible.** This time the target is not "inspired by" — it is "make the in-game model look like this picture".

## Reference
- **Main target: `docs/feedback/refs_gpt/ref3.png`** (attached). Reproduce this design: silhouette, part layout, proportions, colours, materials.
- `ref2.png` (attached) is the same design family. Use it only for extra views of the helmet, the leg frame and the plates.
- `ref1.png` is NOT the target (too sci-fi). Ignore it.

## What the reference shows (check each point against your result)
1. **Undersuit:** a black, fairly close-fitting tactical combat suit (shirt + trousers with seams, light padding, velcro). No baggy cargo look and no puffy padding. It covers all clothing.
2. **Plate carrier on the torso:** black, with a high collar/neck guard, a row of 3–4 mag pouches across the chest, a front plate, a cummerbund, a padded belt with pouches, and a groin plate under the belt.
3. **Armor plates:** flat or slightly curved hard plates, olive-tan/khaki (worn paint), with **clipped (chamfered) corners**, visible thickness, rivets/bolts and chipped edges:
   - big shoulder pauldrons, an upper-arm plate, an elbow cap, a forearm plate, gauntlet gloves;
   - a big front thigh plate, a separate hip/side thigh plate, a **big knee plate**, a long shin plate, a small ankle plate.
   The plates are **strapped onto the leg with black straps** and sit close to it. The legs must look like legs with plates on, not tubes or barrels.
4. **Exoskeleton frame:** dark metal, built from **linked segments** (plates with bolts, like a chain of links), running down the outside of the legs from the hip, through a knee hinge and down to an ankle stirrup under the boot. The arm frame runs from a shoulder unit to the elbow and the forearm. It is attached to the body with straps and cuffs. **Yellow hydraulic/cable lines** run along the frame.
5. **Back:** a power-pack/backpack unit on a frame, with a yellow warning triangle, hoses to the shoulders and hips, and pouches on the belt.
6. **Helmet:** a modern high-cut ballistic helmet (Ops-Core / Galvion style, dark grey) with rails, an NVG shroud and side covers, plus a **full black visor down to the chin**, and a black balaclava/neck gaiter under it. **No Soviet Altyn/Vulkan/Maska look and no EOD collar.**
7. **Boots:** black military boots with a thick sole, worn under the ankle stirrup.

## Hard limits
- **Triangle budget: ≤ 30 000 triangles for LOD0 of everything worn together** (suit + undersuit + plates + frame + backpack + helmet + thermal module). Only the player wears this set, and low EFT graphics settings degrade it anyway, so spend triangles on the silhouette, and put detail into normal maps and textures. LOD1 should be about half. List the counts per part.
- Same technical constraints as before:
  - `base_scene.blend` with `EFT_Bind`;
  - skinning to the EFT bones, up to 4 bones per vertex;
  - pose QA for clipping;
  - helmet mounts `mod_nvg` (thermal module) and `mod_equipment_001` (headset);
  - Blender headless.
- Ripping vanilla EFT assets with AssetRipper and kitbashing them (pouches, buckles, a helmet like the Galvion Caiman, a carrier, boots) is allowed and encouraged. It is a private mod.

## Workspace (competition rules)
- Work **only** in `E:\Projects\Juggernaut\art\v5-astra\` (scripts, blend files, textures, renders). Copy what you need from elsewhere. Do not modify the files in `art\` outside your folder.
- Do not touch `art\v5-claude\`: that is Claude's entry. Do not touch `server\`, `client\`, `C:\SPT41` or `C:\SPT`.
- **No bundles in this stage.** Stage 1 is the model, skinned and pose-checked, plus the renders. Only the winner builds bundles afterwards.
- Do not start the game or the SPT server. No git.

## Deliverables (stage 1)
In `E:\Projects\Juggernaut\art\v5-astra\`:
1. `juggernaut_v5.blend`: the skinned set on `EFT_Bind`, with LOD0 and LOD1.
2. **Renders** in `renders\`, Cycles, dark grey background (similar to the reference sheet), on the base character in the bind pose:
   - `sheet.png`, 2400x1200: front, front 3/4, side, back, back 3/4, in one row, like the top row of the reference;
   - `helmet.png`, 1024x1024: a helmet close-up, front 3/4;
   - `legs.png`, 1024x1024: a leg close-up, side;
   - `pose.png`: two QA poses (walking, crouching).
3. `REPORT.md`: triangle counts per part and in total, what was ripped from EFT and what you modelled, a point-by-point comparison with the reference list above, and known gaps.

**Self-review before finishing:** put `sheet.png` next to the top row of `ref3.png` and honestly compare them point by point. If the legs look like tubes, the plates do not cover, the helmet is open or Soviet, or the collar looks like a bomb suit, keep iterating.
