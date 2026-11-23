// Per-raid spawn of the Juggernaut boss.
// A Harmony postfix on LocationLifecycleService.GenerateLocationAndLoot appends a bossTest BossLocationSpawn to the per-raid
// clone of the map base. Editing the database at load would not work: BotPlacementSystem rebuilds every map's boss list
// at start and after each raid. Fika calls the same method, so the postfix covers both.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using HarmonyLib;
using SPTarkov.Common.Models.Logging;
using SPTarkov.DI.Annotations;
using SPTarkov.Reflection.Patching;
using SPTarkov.Server.Core.DI;
using SPTarkov.Server.Core.Models.Eft.Common;
using SPTarkov.Server.Core.Models.Utils;
using SPTarkov.Server.Core.Services.InRaid;

namespace Juggernaut;

[Injectable(InjectionType.Singleton)]
public class JuggernautBossSpawner(ISptLogger<JuggernautBossSpawner> log)
{
    private static readonly string[] HostileRoles = { "pmcUSEC", "pmcBEAR", "pmcBot", "assault", "marksman", "cursedAssault" };

    /// <summary>Adds (or removes) the boss entry on a per-raid copy of the map.</summary>
    public void Apply(LocationBase map)
    {
        var id = map?.Id?.ToLowerInvariant();
        if (string.IsNullOrEmpty(id) || id == "hideout") return;
        var cfg = JuggernautSettings.Config;
        map.BossLocationSpawn ??= new List<BossLocationSpawn>();
        map.BossLocationSpawn.RemoveAll(b => b.BossName == JuggernautBoss.BossName);
        if (!cfg.BossEnabled) return;

        var labs = id == "laboratory";
        var test = cfg.BossTestMode;
        if (!labs && !test) return;
        var chance = test ? 100 : JuggernautSettings.Clamp(cfg.BossChance, 0, 100, 25);
        if (chance <= 0) return;
        var zone = labs ? "BotZoneBasement,BotZoneFloor1,BotZoneFloor2" : id.StartsWith("factory4") ? "BotZone" : "";

        map.BossLocationSpawn.Add(new BossLocationSpawn
        {
            BossName = JuggernautBoss.BossName, BossChance = chance, BossZone = zone,
            BossDifficulty = "normal", BossEscortDifficulty = "normal",
            BossEscortType = JuggernautBoss.BossName, BossEscortAmount = "0", Supports = null,     // no followers
            IsBossPlayer = false, IsRandomTimeSpawn = false,
            Time = test ? 10 : 120, Delay = 0, TriggerId = "", TriggerName = "",
            IgnoreMaxBots = true, ForceSpawn = test, DependKarma = false, DependKarmaPVE = false,
            ShowOnTarkovMap = false, ShowOnTarkovMapPvE = false,
            SpawnMode = new[] { "regular", "pve" }, SptId = "juggernaut"
        });

        // everyone on the map treats the boss as an enemy (the boss' own Mind lists already hostile to them)
        var marked = 0;
        foreach (var h in map.BotLocationModifier?.AdditionalHostilitySettings ?? Enumerable.Empty<AdditionalHostilitySettings>())
        {
            if (h?.BotRole == null || !HostileRoles.Contains(h.BotRole, StringComparer.OrdinalIgnoreCase)) continue;
            (h.AlwaysEnemies ??= new HashSet<string>()).Add(JuggernautBoss.BossName);
            marked++;
        }
        log.Info($"[Juggernaut] boss spawn added on {id}: {chance}%{(test ? " (test mode, forced, ~10 s)" : "")}, zone '{(zone == "" ? "any" : zone)}', hostile entries {marked}");
    }
}

[Injectable]
public class JuggernautSpawnPatch : AbstractPatch
{
    private static JuggernautBossSpawner _spawner;
    private static ISptLogger<JuggernautSpawnPatch> _log;

    public JuggernautSpawnPatch(JuggernautBossSpawner spawner, ISptLogger<JuggernautSpawnPatch> log) : base("JuggernautSpawnPatch")
    {
        _spawner = spawner;
        _log = log;
    }

    protected override MethodBase GetTargetMethod() =>
        AccessTools.Method(typeof(LocationLifecycleService), nameof(LocationLifecycleService.GenerateLocationAndLoot));

    [PatchPostfix]
    public static void Postfix(LocationBase __result)
    {
        try { _spawner?.Apply(__result); }
        catch (Exception ex) { _log?.Error($"[Juggernaut] boss spawn failed: {ex}"); }     // never break the raid start
    }
}

/// <summary>AbstractPatch.Enable() only works from the assembly that owns the patch, so it is switched on here.</summary>
[Injectable(InjectionType.Singleton, OnLoadOrder.Preload + 70)]
public class JuggernautPatchLoader(IEnumerable<IRuntimePatch> patches, ISptLogger<JuggernautPatchLoader> log) : IOnLoad
{
    public Task OnLoadAsync(CancellationToken cancellationToken)
    {
        try
        {
            foreach (var patch in patches.OfType<JuggernautSpawnPatch>())
            {
                patch.Enable();
                log.Success($"[Juggernaut] boss: spawn patch {(patch.IsActive ? "enabled" : "NOT active")} on LocationLifecycleService.GenerateLocationAndLoot");
            }
        }
        catch (Exception ex) { log.Error($"[Juggernaut] boss spawn patch failed: {ex}"); }
        return Task.CompletedTask;
    }
}
