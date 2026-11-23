# Juggernaut: work status (2026-11-22)

## Done by Claude (code)
- **server/** (net10.0, builds with 0 errors). Installed in `C:\SPT41\SPT_Runtime\user\mods\Juggernaut`; registration verified on the server.
  - `JuggernautItems.cs` registers four items:

    | Item | ID | Built from |
    |---|---|---|
    | suit | `dd0dd2c4b50ad72dd5b6dc62` | Kora-Kulon clone; 15 built-in class 6 Aramid slots; 45 kg; native ConflictingItems = all other headwear + armored rigs |
    | helmet | `ad9e1818143bc0cf5bbd4295` | Altyn clone; class 6 top/back/ears/face; blocks face cover + eyewear; `mod_nvg` slot takes only the module |
    | module | `da2c9ba6108e2e14c0e982c6` | PNV-10T adapter clone, no slots |
    | cell | `866318f980bf699a8cae99fc` | Rechargeable battery clone, 1x1, not stackable |

  - Ragman offers: suit LL4 2.5M, helmet LL4 650k, module LL4 400k, cell LL2 8000 (unlimited).
  - Client messages are added to the global locales (`jug.msg.*`), so the client reads them with `.Localized()`.
  - `JuggernautSettings.cs`: `config.json` plus the `/juggernaut/settings` and `/juggernaut/settings/update` routes, with the owner rule.
  - `locales.json`: 17 languages.
  - Models: `Model()` uses `bundles/assets/content/items/equipment/juggernaut/<bundle>` when the file exists. Otherwise the donor's vanilla prefab is used. `bundles.json` still has to be written once the bundles exist.
- **client/** (netstandard2.1, builds with 0 errors). Installed in `C:\SPT41\BepInEx\plugins\JuggernautClient`.
  - `JugSet.cs`: set mode (None / Powered / Discharged).
    - Cell consumption: `ItemManipulator.Remove` + `TryRunNetworkTransaction`, one cell per DrainMinutes, in raid only.
    - Discharged penalties are written into the suit template (`speedPenaltyPercent` -40, `mousePenalty` -30, `weaponErgonomicPenalty` -40), then `RecalculateEquipmentParams` runs.
  - `JugDebuffs.cs`: `CanSprint` and `CanJump` return false while discharged.
  - `JugTiers.cs`: per-mode tables. The FBA hooks (Exoskeleton*.cs, copied) use them.
  - `ThermalOutline.cs` (Codex draft, adapted): mask with a depth test plus an inner-edge outline drawn through a CommandBuffer. It needs `juggernaut_thermal.bundle` next to the DLL.
  - `SettingsMenu.cs` / `ServerSettings.cs`: F12 entries; the toggle key (default `T`) is a local setting.

## Blocked
- **Unity licence expired** ("Access token is unavailable / No ULF license found"). The user must sign in to Unity Hub. This blocks:
  - the thermal shader bundle (`C:\SPT\_codex_downloads\unity\Juggernaut`, `-executeMethod BuildThermal.Build`, output in `Build\juggernaut_thermal.bundle`);
  - Astra's model bundles.

## In progress
- Codex `gpt-6.2-astra` is building the 3D models. Brief: `docs/MODEL_TZ.md`. Log: `C:\SPT\_codex_downloads\juggernaut_model_codex.log`. Expected handover: `art/BUNDLES.md`.

## Not verified in game
- None of it has been run in game yet:
  - cell drain;
  - penalties;
  - sprint and jump block;
  - buffs;
  - thermal outline;
  - equipment conflicts.
