# Task: "Juggernaut" super-heavy armored exoskeleton set: a NEW standalone SPT 4.1 mod

## What to build
Build a **new, standalone mod** in this empty project folder, `E:\Projects\Juggernaut`. It is a super-heavy armored exoskeleton set in the style of the Call of Duty *Juggernaut* suit. It is a **set**: its powers work only while all parts are worn and powered.

The user publishes it as a separate mod under the "TushonkaGroup" brand:
- name **"Juggernaut From TushonkaGroup"**
- server GUID `com.silian.juggernaut`
- client GUID `com.silian.juggernaut.client`
- author `silian`
- licence MIT
- version 1.0.0
- `SptVersion ~4.1.3`

It must **not** depend on the FullBodyArmor/Exoskeleton mod and must **not** require it.

### Reference implementation
The user's other mod, at `E:\Projects\FullBodyArmor` (FullBodyArmor 1.1.0 for SPT 4.1.6), already solves most of the hard parts: exoskeleton buffs, full-body Aramid armor, F12 settings and localization. **Read it, then copy and adapt code from it into this project.** It is the same author's code under MIT, so copying is fine.

Do not edit anything in `E:\Projects\FullBodyArmor`: it is read-only reference.

Useful files there:
- `server/` (C#, net10.0):
  - `FullBodyArmor.cs`: FBA carrier and 20 Aramid pieces. Class 6 armor values and collider lists.
  - `Exoskeleton.cs`: exo items, built-in armor slots, Ragman offers.
  - `ClientSettings.cs`: settings routes, with the settings-owner rule.
  - `Texts.cs` + `locales.json`: 17 languages.
- `client/` (BepInEx, netstandard2.1):
  - `ExoTiers.cs`: per-tier stats.
  - `ExoskeletonMovement.cs`, `ExoskeletonTraversal.cs`, `ExoskeletonMelee.cs`, `ExoskeletonRecoil.cs`: the buffs.
  - `ExoskeletonEquipment.cs`: equipment rule.
  - `ServerSettings.cs` + `SettingsMenu.cs`: F12 menu. The server is the source of truth.
  - `ExoResolve.cs`: obfuscated members resolved by signature.
- `tools/` and `tools/exo_model/`: the pipeline that built the EXO models procedurally in Blender, plus the Unity bundle build and bundle patching scripts.

### Coexistence with FullBodyArmor
Both mods may be installed together. Rules for that case:
- Use your own namespaces, Harmony IDs, route URLs (`/juggernaut/...`), config file and locale keys.
- Every patch applies Juggernaut effects **only** while the Juggernaut suit is worn. Never touch the effects of the FBA or EXO items.

## The set
### 1. Juggernaut suit
Slot: ArmorVest, like the other EXO tiers.
- **Armor:** built-in, non-removable armor covering every FBA zone (torso front/back, sides, neck, shoulders, groin, thighs, calves, forearms) at **class 6 Aramid**. Use the same per-zone values as the FBA class 6 pieces in `FullBodyArmor.cs`. Durability is as high as FBA class 6.
- **Weight:** very heavy, proposal 45 kg.
- **Buffs while powered:** better than EXO-3 on every line. Proposed values:

| Buff | Value |
|---|---|
| Sprint | ×1.30 |
| Sprint/arm stamina drain | ×0.45 |
| Weight limits | +60 kg (covers its own weight with room left) |
| Jump | ×1.50 |
| Melee | ×3.5 |
| Fall cushion | 2.0 m |
| Vaulting while overweight | ×1.30 |
| Recoil | ×0.85 |

- **Slot:** one *power cell* slot (see 3).
- **Equipment rule:**
  - While the suit is worn, other armored headwear, face covers, eyewear and ballistic rigs are blocked.
  - The Juggernaut helmet is always allowed, because it is part of the set.
  - Make this rule switchable in F12, on by default.

### 2. Juggernaut helmet
Slot: Headwear.
- **Armor:** full head coverage: top, back, ears, face, eyes, jaw. Class 6 Aramid, with durability on the FBA class 6 scale.
- **Blocks:** face cover and eyewear slots, as a full-face helmet does.
- **Slots:**
  - Earpiece (headset): accepts the vanilla headsets, like Altyn/Rys-T style helmets do.
  - Thermal module: accepts only the new Juggernaut thermal module item (see 4).
- **Look:** a closed, heavy, armored face with a narrow visor, matching the suit.

### 3. Power cell
A new item in the suit's power slot.
- **Capacity:** a resource of N charges. Proposal: N = 6, i.e. 30 minutes.
- **Drain:** while the suit is worn **in raid**, one charge is used every 5 minutes. Nothing is used out of raid or in the hideout.
- **Saving the charge:** the remaining charge must be saved on the item. Store it in the item's own resource/durability-like field so that it survives raid end and shows in the UI. Look at how vanilla items store resources (fuel, `MedKit` HpResource, `Resource`), and choose one that the game saves and shows.
- **Sales:**
  - Ragman sells the cell (proposal: LL3, 40,000 RUB).
  - A hideout craft at the Workbench is optional: only add it if it fits in cleanly.
- **Empty cells:** stay in the slot and can be removed and sold.

### 4. Thermal module (helmet attachment)
A Call of Duty style thermal targeting overlay.
- **Effect:** draws a **bright red outline** (silhouette contour) around enemies and **changes nothing else** in the image. No colour grading, no noise, no blur, no thermal palette, no vignette. The world must look exactly as without the module.
- **Targets:** hostile bots and other players (including Fika `ObservedPlayer`s). Only targets in **line of sight**, not through walls, within 250 m and inside the camera view.
- **When active:** only while the module is in the helmet **and** the set is powered.
- **Toggle:** a hotkey toggles it, configurable in F12. Default: the game's own night-vision toggle key if it can be hooked cleanly, otherwise `T`.
- **Not allowed:** do NOT reuse the game's `ThermalVision` component, because it changes the image. Implement your own outline, for example:
  - a second camera or command buffer that renders target renderers into a mask, then an edge-detect composite that only adds the red edge;
  - or another approach that leaves every other pixel untouched.
- **Shaders:** any shader you need has to be built into an asset bundle with the project's Unity 2022.3.43 pipeline (see `tools/`). Check that it works with the game's renderer (EFT uses the built-in render pipeline).
- **Performance:** keep it cheap, with no per-frame allocations.

### 5. Set rule and the discharged state
The set is **powered** when all of these hold:
- the suit is worn,
- the helmet is worn,
- the power cell has charge left.

| State | What happens |
|---|---|
| Powered | All Juggernaut buffs and the thermal module work. |
| Not powered: no helmet, no cell, or an empty cell | No buffs and no thermal. The full weight is carried by the player with **severe debuffs** (see below). |

Debuffs while not powered (proposal):
- Movement speed ×0.60.
- Sprint disabled.
- Stamina drain ×2.5.
- Jump disabled.
- Weapon ergonomics −40.
- Aim/mouse sensitivity penalty −30 %.
- The suit's 45 kg plus the helmet count normally toward the weight limits, so the game's own overweight penalties stack on top.

Notification:
- Show a short on-screen message when the set changes between powered and discharged, using the game's notification UI.
- Show a warning when the cell has 1 charge left.

## Content and integration
- **Look:** a bulky, heavily plated super-heavy suit, inspired by the Call of Duty Juggernaut silhouette. It must be original: do not copy CoD assets.
- **3D models:** suit + helmet + cell + thermal module. Build them procedurally in Blender (Blender 5.3 is installed under `C:\Program Files\Blender Foundation\`), the same way as `tools/exo_model/`. Then bundle them with the Unity 2022.3.43 pipeline already used for the EXO bundles. Textures may be generated: Codex has access to image generation.
- **IDs:** new template IDs must be unique 24-hex IDs. Never reuse existing ones.
- **Traders:**
  - Ragman LL4 sells the suit, the helmet and the thermal module (proposal: suit 2,500,000; helmet 650,000; module 400,000).
  - Ragman sells the cell, as in section 3.
  - None of the parts are allowed on the flea market.
- **Localization:** all 17 languages in `server/locales.json`, in the same style as the existing texts. Descriptions explain the set rule and the drain.
- **Settings:**
  - **F12** (server-side via the existing settings routes; owner rule unchanged): drain interval (default 5 min), cell capacity, thermal range, thermal on/off, outline colour.
  - **`config.json`:** the same keys.
- **Fika:**
  - buffs and debuffs apply to the local player only, like the existing tiers;
  - the cell drain must run on the client that owns the player;
  - the outline is drawn only for the local player.
- **Project files:**
  - `README.md`, with the same structure as the FullBodyArmor README
  - `LICENSE`: MIT, "Copyright (c) 2026 silian"
  - `FORGE_DESCRIPTION.md`: the Forge description, in Markdown
  - `.gitignore`: bin/ obj/ *.user .vs/ __pycache__/ *.pyc *.blend1 dist/

## Rules
- **Where to work:** only in `E:\Projects\Juggernaut`, using the FullBodyArmor layout: `server/`, `client/`, `tools/`, `art/`, `docs/`, `dist/`. Do NOT run git init or commit: the user handles git.
- **Builds:** use the .NET 10 SDK at `C:\SPT41\_tools\dotnet10\dotnet.exe`. The projects reference the SPT 4.1.6 install at `C:\SPT41`.
- **Packaging:** the result is a release-style tree in `dist/Juggernaut-1.0.0-staging/`, with `SPT_Runtime/user/mods/Juggernaut/...` and `BepInEx/plugins/JuggernautClient/...`.
- **Do not install into `C:\SPT41` or `C:\SPT` yourself.** Claude installs and tests after you finish.
- **Do not start the game.** You may start the server only to check registration, and only if `EscapeFromTarkov.exe` and `SPT.Server.exe` are not running. Stop the server again afterwards.
- **Obfuscated game members:** resolve by signature with `ExoResolve`, as the existing code does.
- **Never guess game API names.** Look them up in `C:\SPT41\EscapeFromTarkov_Data\Managed\Assembly-CSharp.dll`. Decompiled trees are in `C:\SPT41\_ports\_work\dec\new` (4.1) and `dec\old` (4.0).
- **Scope:** do not modify `E:\Projects\FullBodyArmor` or anything else outside this project folder. The only exceptions are the allowed temp and Unity folders.

## Report back
Write `docs/JUGGERNAUT_REPORT.md` covering:
- what was built and where;
- every design decision you had to make;
- build results;
- what is verified (compiles, registers on the server) versus what needs an in-game test;
- any part you could not do.
