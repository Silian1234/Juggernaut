# Model feedback 3: v3 rejected ("this is total crap"). Redesign from the user's own references

The user rejected v3 outright. v1, v2 and v3 all failed for the same root cause: **the shapes are simple procedural blocks with almost no detail density**, so they read as toys or placeholders. This time the user provided 7 real references (attached, also in `docs/feedback/refs/`).

**Study them carefully. They define the target.** They are for inspiration only: do not copy any single design or its logos/emblems.

| Ref | What to take |
|---|---|
| `ref1_tactical_heavy` (main reference) | A heavy **tactical** armored soldier: a plate carrier with MOLLE pouch rows over the armor, a radio with antenna, tan/coyote webbing accents on dark armor. **Huge armored arm and shoulder stacks**, bulky gauntlets, segmented thigh and shin armor, armored boots. A **closed angular helmet** with a faceted faceplate, a vertical visor slit, side sensor pods and an antenna. A box power pack on the back. |
| `ref6_engineer_specialist` | A gorilla silhouette: massive upper body and forearms, layered segmented armor plates, chunky boots, a tactical vest and pouches over the armor, a faceted closed helmet. Small warm indicator lights are acceptable as tiny accents only. |
| `ref2_black_powerarmor` | Dark armored powered suit: segmented ribbed abdomen/back, big shoulder shells, layered forearm armor, knee actuator hardware. |
| `ref3_exo_back_detail` | Hard-surface **detail density**: panel breakup, vents/grilles, spine segments, bolts, hoses, mechanical joint housings at the hips, knees and ankles. |
| `ref4_leg_exo_frame` | A **visible exoskeleton leg frame** strapped over the legs: thigh/shin struts, knee hub actuator, pistons, ankle stirrup into the boot, cables, worn painted metal. This is how the "exo" part must read. |
| `ref5_exo_back_sketch` | Back unit: a power pack with **hoses/conduits running to the shoulders and arms**, a hip belt, plates over the shoulders. |
| `ref7_real_cosplay` (real gear) | Tarkov-grounded realism: coyote/tan EOD-style suit with real webbing, pouches, knee pads, a big back frame pack and hose, a K6-3-style helmet with a heavy visor. It shows the material realism to aim for: real fabric, webbing, wear. |

## Target design (synthesis)
1. **Silhouette.**
   - Massive upper body: broad multi-segment pauldrons, thick armored upper arms, **oversized armored forearms and gauntlets**, a wide chest.
   - Strong legs with segmented thigh plates and armored shins.
   - **Big armored boots**.
   - Slightly hunched, heavy stance proportions. A walking tank, but anatomical. Not puffy (v2) and not slim (v3).
2. **Two layers.**
   - **Armor layer:** dark gunmetal/near-black plates, thick (25–40 mm), segmented, overlapping, with chamfers and worn edges.
   - **Tactical layer on top:** a plate carrier / chest rig with **MOLLE webbing and pouch rows** (mag pouches, utility pouches, radio pouch + antenna), straps, buckles, a hip belt. **Coyote/tan accents** on the webbing.
   - Strongly recommended: **rip real pouches, webbing, buckles and radio models from EFT's own assets** with AssetRipper (`C:\SPT\_tools\assetripper`, game bundles in `C:\SPT41\EscapeFromTarkov_Data\StreamingAssets\Windows\`) and kitbash them, with their original textures, onto the suit. That makes it look native to Tarkov. It is a private personal mod, so in-game reuse is fine.
3. **Visible exoskeleton.**
   - A leg frame like `ref4`: struts along the thighs and shins, a knee hub actuator with pistons, an ankle stirrup.
   - Hip actuators.
   - Elbow actuators.
   - Hoses/conduits from the back power pack to the shoulders and arms (`ref5`).
4. **Back.**
   - An engineered power pack housing on a frame, with the battery visible (the cell indicator strip may glow very dimly).
   - Hoses and cables.
   - An antenna mount.
5. **Helmet.**
   - Closed, **angular, faceted** (`ref1` style).
   - A faceplate with a narrow dark vertical or T visor slit.
   - Side sensor pods.
   - An antenna.
   - A neck guard that sits into the collar.
   - **Proportional to the bulky body.** v1 and v2 had a too-small helmet, v3 was too tall and egg-shaped.
   - Keep the `mod_nvg` (thermal module) and `mod_equipment_001` (headset) mounts.
6. **Detail density is the priority.** Bolts, rivets, panel seams, vents/grilles, cable runs, labels/stencils, scuffs, chipped paint, dirt. Use proper normal maps and baked AO. If the silhouette is right but the surfaces are plain, it will be rejected again.
7. **Materials.** Realistic PBR for the EFT shader:
   - matte worn paint on the armor;
   - fabric/nylon on the webbing and pouches;
   - bare metal on edges and pistons;
   - rubber on the hoses.

   No glossy plastic look, and no neon (tiny dim LEDs only).

## Process (mandatory)
1. **Concept first:** generate 2–3 concept images (front, back, side, helmet close-up) with gptimage, using these references. Pick the best one and save it in `art/design/v4-concept*.png`. Check it against the table above before you model.
2. **Build:** silhouette and armor, then the exo frame, then the tactical layer (kitbash), then the details, then the textures.
3. **Self-review:** compare the final renders side by side with `ref1` and `ref6`, on the character next to a vanilla PMC. If it looks simpler, smoother or emptier than the references, keep iterating before you hand it over.
4. **Keep all technical constraints:**
   - same bundle names and prefab paths;
   - same rig and bindposes;
   - LODs;
   - mounts;
   - pose QA;
   - no clothing visible.

   The triangle budget may go up to about 90k for LOD0 of the suit and 20k for the helmet.
5. Update the previews, icons, banner, `REPORT.md` and `BUNDLES.md`.
