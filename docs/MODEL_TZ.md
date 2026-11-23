# Task: 3D models and asset bundles for the "Juggernaut" set (models only, no mod code)

You make the **art and the bundles** for a new SPT 4.1.6 (EFT 0.16.9.5.40743) mod, *Juggernaut From TushonkaGroup*. It is a super-heavy armored exoskeleton set in the spirit of the Call of Duty *Juggernaut* suit.

The mod's C# code is written by someone else. **Do not write or edit any mod code** in `server/` or `client/`, and ignore the files that are already there.

If `docs/JUGGERNAUT_TZ.md` exists, read it only for the gameplay context.

## You did this before: reuse that pipeline
The same author's EXO-1/2/3 exoskeletons were modelled by you (GPT via Codex) with this pipeline:
- **Workspace, tasks and reports:** `C:\SPT\_fullbody_armor\exoskeleton\gpt\`. Read `TASK*.md` and `REPORT*.md` first. The base scene with the EFT character, armature and bindposes is `base_scene.blend`. The tier models are `exo_model.blend`, `exo_t2.blend`, `exo_t3.blend` and `exo_t3a.blend`.
- **Blender scripts:** the procedural builders are in that folder and are mirrored in `E:\Projects\FullBodyArmor\tools\exo_model\` (`build_tiers.py`, `build_t3a.py`, `geometry.py`, the atlas, preview and QA scripts). The export to Unity JSON is `E:\Projects\FullBodyArmor\tools\export_exo.py`.
- **Unity:** the bundle builder is `E:\Projects\FullBodyArmor\tools\unity\ExoTierBuild.cs` (with `FbaBuild.cs` for the FBA carrier). The Unity 2022.3.43f1 project with the ripped vanilla prefabs and shaders is `C:\SPT\_fullbody_armor\exoskeleton\project`. The build logs (`unity-*.log`) are next to it.
- **Bundle fixes after the build:** `E:\Projects\FullBodyArmor\tools\patch_bundle_exo.py`.
- **Installed EXO bundles** (to compare structure): `C:\SPT41\SPT_Runtime\user\mods\FullBodyArmor\bundles\assets\content\items\equipment\exoskeleton\`.
- **Tools:**
  - Blender 5.3: `C:\Program Files\Blender Foundation\`.
  - Unity 2022.3.43f1: `C:\Program Files\Unity\Hub\Editor\2022.3.43f1\Editor\Unity.exe`.
  - AssetRipper: `C:\SPT\_tools\assetripper`, if you need to rip more vanilla prefabs, for example a helmet.
  - Game asset bundles: `C:\SPT41\EscapeFromTarkov_Data\StreamingAssets\Windows\`.
- **Workspace rule:** do your work in `E:\Projects\Juggernaut\art\` (sources, blend files, previews) and a copy of the Unity project, `E:\Projects\Juggernaut\art\unity_project\`. Copy it from the EXO project. **Do not modify the EXO project** or anything in `C:\SPT\_fullbody_armor`.

## Look
Super-heavy, bulky, heavily plated armor, like a walking tank:
- thick layered plates over the chest, shoulders, arms and legs;
- a massive collar;
- armored gauntlets and boots;
- visible heavy servo/actuator details at the hips, knees and elbows, so it reads as a powered exoskeleton;
- dark military finish (gunmetal / olive drab), worn edges.

It must be **original**. Do not copy CoD or any other game's assets. The silhouette is clearly bigger and heavier than EXO-3.

## Deliverables
Build four items. Each one gets its own bundle, under `E:\Projects\Juggernaut\server\bundles\assets\content\items\equipment\juggernaut\`.

| Item | Bundle | Slot / use | Notes |
|---|---|---|---|
| Juggernaut suit | `item_equipment_juggernaut_suit.bundle` | ArmorVest. A skinned full-body dress item like the EXO tiers | Same prefab structure as the EXO bundles (DressItem / PreviewPivot / Loot / Skin with EFT Skin LODs, up to 4 bones per vertex, EFT bindposes). It covers the body like EXO-3 and must not clip badly in the main poses. Use your QA approach from the EXO tasks. |
| Juggernaut helmet | `item_equipment_juggernaut_helmet.bundle` | Headwear. Full-face, fully closed, with a narrow armored visor | Base the prefab on a vanilla full-face helmet rip, for example Altyn or Rys-T, including its slot and attach-point transforms. It needs a working **earpiece (headset)** attach point, and a top or front **mount point for the thermal module**. Name and keep the mount transform as the vanilla helmets do (for example the `mod_nvg` slot transform). It must be wearable together with the suit without clipping into the collar. |
| Thermal module | `item_juggernaut_thermal_module.bundle` | A helmet attachment in the helmet's NVG/mount slot | A compact sensor pod with a red lens. Base the prefab on a vanilla helmet-mounted device rip so that it attaches correctly. It must NOT contain or reference the game's ThermalVision or NightVision components or materials. It is a pure cosmetic mesh, and the effect is done in code. |
| Power cell | `item_juggernaut_power_cell.bundle` | A loose inventory item, 1x2 cells, also used in a slot on the suit | A chunky battery pack with a charge indicator strip. Base it on a vanilla loot item prefab rip (for example a battery-type barter item) for correct world and loot behaviour. |

Also deliver:
- **Inventory icons**, 256 px PNG with a transparent background, one per item, in `E:\Projects\Juggernaut\art\icons\`.
- **A banner image** in `E:\Projects\Juggernaut\art\banner.png` (1920x1080). Use renders or generated images of the set.
- **Preview renders** (front, back, side) of the suit and helmet worn on the base character, in `E:\Projects\Juggernaut\art\previews\`.
- **The Blender build scripts** for reproducibility in `E:\Projects\Juggernaut\tools\model\`, and the Unity build script(s) in `E:\Projects\Juggernaut\tools\unity\`.
- **`E:\Projects\Juggernaut\art\BUNDLES.md`**, the handover document for the coder. For each bundle, list:
  - the bundle path;
  - the prefab asset path inside the bundle (the `Prefab.path` the server item must use);
  - the dependency keys for `bundles.json`;
  - the helmet's slot / attach-point transform names;
  - which vanilla template each item was based on, so the coder can clone that item on the server for matching slots and behaviour;
  - triangle counts and LODs;
  - known limitations.

## Rules
- Unity version must stay exactly 2022.3.43f1. Bundles must load in EFT 0.16.9.5.40743. The EXO bundles built with the same pipeline already load in this client, so compare against them.
- Do not install anything into `C:\SPT41` or `C:\SPT`, and do not start the game or the SPT server.
- Do not run git commands.
- If something cannot be done properly, say so in `BUNDLES.md`. Do not fake it. Typical cases: no good vanilla rip for the helmet attach points, or skinning problems.
- Write a short `E:\Projects\Juggernaut\art\REPORT.md` with what you did and how to rebuild.
