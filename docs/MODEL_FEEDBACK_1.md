# Model feedback 1: the suit and helmet must be redone (the user rejected v1)

**Good news:** the bundles load in EFT 40743. The suit is skinned, it animates with the character, and the item works. Keep that pipeline and structure.

**Bad news:** the look was rejected. The user laughed at it. The attached in-game screenshot (`docs/feedback/ingame_back_v1.png`, back view) shows these problems:

1. **Coverage.**
   - **Problem:** the plates are scattered over the body with large gaps. The camo clothing shows on the torso sides, both arms, the back between plates, the thighs and the hips. It reads as a skeletal frame with a few rocks glued on.
   - **Required:** a Juggernaut is **fully enclosed**. Think of the Call of Duty Juggernaut, which is a heavy **EOD bomb suit with ballistic plates on top**. The idea, without copying their asset, is:
     - a thick padded ballistic **base suit** covering the whole body: torso, arms to the wrists, legs to the boots, and a high collar;
     - **thick curved armor plates** layered over the base suit: chest/abdomen, a big back plate with an integrated **power pack housing**, large pauldrons, upper and lower arm plates, a groin/belt apron, thigh plates, knee caps and greaves;
     - very little or no clothing visible anywhere.
2. **Shape.**
   - **Problem:** the faceted low-poly "pyramid / crystal" plates with sharp creases and visible triangles look like rocks.
   - **Required:**
     - plates that are curved and follow the body;
     - **chamfered or rounded thick edges** (real thickness, 15–35 mm);
     - **smooth shading** with proper normals: weighted normals or auto-smooth, no faceting;
     - believable industrial / military armor forms: panel seams, rims, bolts and hinges.
3. **Material.**
   - **Problem:** a flat untextured grey-green with no detail.
   - **Required:** real textures for the EFT shader you used:
     - an albedo with a dark military finish (gunmetal / olive drab), worn and chipped edges, scratches and grime;
     - a **normal map** for panel lines, rivets, fabric weave on the padded suit, and stencils/decals;
     - specular/gloss variation, so metal edges are shinier and the paint and fabric are matte.

   Use texture baking and image generation (gptimage) as needed. Texel density must be good enough to look right at first-person and inventory-preview distance.
4. **Construction.**
   - **Problem:** the plates float on thin struts away from the body.
   - **Required:** plates sit **on** the base suit with straps/buckles and overlap like armor (shingled, layered), so the silhouette is massive and continuous.
   - **Exoskeleton parts:** keep the servo/actuator hints at the hips, knees and elbows, but integrate them (pistons, housings), not as sticks.
5. **Silhouette.**
   - **Required:** much bulkier and heavier, a "walking tank". Broad shoulders, a thick torso, heavy legs and boots (armored boot covers).
6. **Helmet.**
   - **Problem:** it reads as a small box with a tiny visor.
   - **Required:** a large, heavy, rounded bomb-suit-style helmet:
     - a thick shell;
     - a **narrow dark armored visor slit** (dark tinted glass, slight reflection);
     - a heavy faceplate and chin guard;
     - an integrated neck guard that blends into the suit's high collar.
     - Keep the `mod_nvg` mount for the thermal module and the `mod_equipment_001` headset mount working.
7. **Thermal module and power cell.** Bring them up to the same material quality (detail, normal map, wear).

## Constraints (unchanged)
- **Integration:** keep the same bundle file names and prefab paths, and the same prefab structure, which is proven to load. The server code already points at them.
- **Rig:** the same EFT armature and bindposes. Up to 4 bones per vertex.
- **Clipping:** check it with your pose QA. Bigger plates will collide more, so use more bones / better weights where needed.
- **Triangle budget:** raise it as needed for quality. Roughly up to 60–80k tris for LOD0 of the suit and 15–20k for the helmet is acceptable. Provide a proper LOD1.
- **Unity is available now.** The user signed in to Unity Hub, so Unity 2022.3.43f1 Editor batch mode should work. If your sandbox still cannot reach the licensing client, keep your offline path, because the v1 offline bundles did load in game.
- Deliverables as before:
  - bundles in `server/bundles/...`;
  - the scripts;
  - updated previews (front, back, side), rendered with the final textures;
  - updated icons and banner;
  - `art/REPORT.md` and `art/BUNDLES.md` updated.
- **Self-review before you finish:** render front / back / side previews **on the base character with clothing visible**, and judge them critically against these points. If you still see clothing gaps, faceting or floating plates, iterate.
