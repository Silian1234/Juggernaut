# Juggernaut From TushonkaGroup

A super-heavy powered assault exoskeleton set for SPT 4.1.x (tested on 4.1.6, EFT 0.16.9.5.40743).
Player-facing description: [FORGE_DESCRIPTION.md](FORGE_DESCRIPTION.md).

## Layout
| Path | What |
|---|---|
| `server/` | Server mod (net10.0): items, Ragman offers, settings routes, locales (17 languages), bundles. Output: `SPT_Runtime/user/mods/Juggernaut/`. |
| `client/` | Client plugin (netstandard2.1, BepInEx): set state and cell drain, buffs and debuffs, thermal outline, sounds, F12 settings. Output: `BepInEx/plugins/JuggernautClient/`. |
| `client/sfx/` | Suit sounds (CC0, see `CREDITS.txt`), built by `tools/sfx/build_sfx.py`. |
| `server/bundles/` | Built asset bundles (suit, helmet, thermal module, power cell). |
| `tools/model/` | Blender scripts: `export_v5d.py` (model to bundle sources), `armor_steel_maps.py` (painted-steel armor material). |
| `tools/unity/` | Bundle packers (`suit_serial_build.py`, `build_rigid_bundles.py`, `verify_art_bundles_v5d.py`) and the thermal shaders. |
| `art/v5-astra/scripts/` | The procedural V5d model builder (`build.py`) and its bake/render scripts. |
| `docs/` | Briefs and design notes. |

## Build
.NET 10 SDK (server) and the game's managed assemblies (client; `SptDir` in `client/JuggernautClient.csproj`).

```powershell
dotnet build server -c Release
dotnet build client -c Release
```

## Rebuild the bundles
Python with NumPy, Pillow and lz4; Blender 5.3. From the repository root:

```powershell
$b = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'
& $b -b art\v5-astra\juggernaut_v5_textured.blend -P tools\model\export_v5d.py -- art\v5-astra\textures\v5d .
python -B tools\unity\suit_serial_build.py --art art\v5d_suit --output art\build\v5d_candidate\item_equipment_juggernaut_suit.bundle
python -B tools\unity\build_rigid_bundles.py --art art\v5d_rigid --out art\build\v5d_candidate --evidence art\build\v5d_candidate\bundle_stats.json
python -B tools\unity\verify_art_bundles_v5d.py --bundles art\build\v5d_candidate
```

Large working files (`.blend`, texture atlases, renders) are not in git; see `.gitignore`.

## License
MIT, see [LICENSE](LICENSE). Sounds are CC0 (see `client/sfx/CREDITS.txt`).
