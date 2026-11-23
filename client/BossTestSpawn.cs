// Test mode: the server adds a bossTest wave on every map (about 10 s after the raid starts). BotBossSpawn.Spawn is where the
// wave is processed on the raid host; BossLocationSpawn.PerfectPos makes the spawn system pick the zone and spawn points
// closest to that position. On a Fika headless host the local main player is an invisible dummy, so the position of a real
// human player is used instead.
using System;
using System.Linq;
using Comfort.Common;
using EFT;
using HarmonyLib;
using UnityEngine;

namespace JuggernautClient
{
    internal static class BossTestSpawn
    {
        internal static void Patch(Harmony harmony)
        {
            var spawn = AccessTools.DeclaredMethod(typeof(BotBossSpawn), nameof(BotBossSpawn.Spawn))
                        ?? throw new MissingMethodException("BotBossSpawn.Spawn");
            harmony.Patch(spawn, prefix: new HarmonyMethod(typeof(BossTestSpawn), nameof(SpawnPrefix)));
        }

        // Spawn is an async method: the prefix runs synchronously when it is called, before the wave is processed
        private static void SpawnPrefix(BossLocationSpawn wave)
        {
            try
            {
                if (wave == null || wave.BossType != WildSpawnType.bossTest || !ServerSettings.Get().BossTestMode) return;
                if (wave.PerfectPos.HasValue) return;
                var world = Singleton<GameWorld>.Instance;
                var players = world?.AllAlivePlayersList;
                if (players == null) { Plugin.Log.LogWarning("[Juggernaut] test mode: no game world, boss spawns at its default position"); return; }
                bool headless = BossCommon.IsHeadless();
                var human = players.FirstOrDefault(p => p != null && !p.IsAI && !(headless && ReferenceEquals(p, world.MainPlayer)));
                if (human == null) { Plugin.Log.LogWarning("[Juggernaut] test mode: no human player found, boss spawns at its default position"); return; }
                wave.PerfectPos = human.Transform.position;
                Plugin.Log.LogInfo($"[Juggernaut] test mode: boss PerfectPos = {human.Transform.position} (near {human.Profile?.Nickname}, headless host: {headless})");
            }
            catch (Exception ex) { Plugin.Log.LogWarning("[Juggernaut] test mode position failed: " + ex.Message); }
        }
    }
}
