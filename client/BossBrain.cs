// The Juggernaut boss (WildSpawnType.bossTest) behaves like Goon "Big Pipe" (followerBigPipe), who natively fights with an
// M32 grenade launcher. The vanilla bossTest role is an immobile test dummy, so three role switches treat it as followerBigPipe:
//   - StandartBotBrain.Activate        -> FollowerBigPipeLayersStrategy (BigPipeFightLayer is a BossKillaLayer: Killa-style push)
//   - BotWeaponManager constructor     -> BigPipeBotWeaponSelector (GL in SecondPrimaryWeapon at 27-130 m, main weapon otherwise;
//                                         the OnActiveEquipmentSlotChanged hookup after the switch stays as it is)
//   - BotEnemyChooser.Create           -> BigPipeEnemyChooser (instead of TestEnemyChooser)
// Each method reads `Profile.Info.Settings.Role` once for its switch; the transpiler passes that read through MapRole.
// The profile role itself is not changed, every other system still sees bossTest. Runs on the host that creates the bot.
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Reflection.Emit;
using EFT;
using HarmonyLib;

namespace JuggernautClient
{
    internal static class BossBrain
    {
        private static readonly Dictionary<MethodBase, int> Mapped = new Dictionary<MethodBase, int>();

        internal static WildSpawnType MapRole(WildSpawnType role) => role == WildSpawnType.bossTest ? WildSpawnType.followerBigPipe : role;

        internal static void Patch(Harmony harmony)
        {
            var sites = new MethodBase[]
            {
                AccessTools.DeclaredMethod(typeof(StandartBotBrain), nameof(StandartBotBrain.Activate)),
                AccessTools.DeclaredConstructor(typeof(BotWeaponManager), new[] { typeof(BotOwner) }),
                AccessTools.DeclaredMethod(typeof(BotEnemyChooser), nameof(BotEnemyChooser.Create), new[] { typeof(BotOwner) }),
            };
            foreach (var site in sites)
            {
                if (site == null) throw new MissingMethodException("a bossTest role switch (StandartBotBrain.Activate / BotWeaponManager ctor / BotEnemyChooser.Create) was not found");
                harmony.Patch(site, transpiler: new HarmonyMethod(typeof(BossBrain), nameof(Transpile)));
                // Harmony runs the transpiler during Patch(), so the count is known here
                if (!Mapped.TryGetValue(site, out var n) || n != 1)
                    throw new InvalidOperationException($"{site.DeclaringType.Name}.{site.Name}: expected 1 role read, mapped {n}");
            }
            harmony.Patch(sites[0], postfix: new HarmonyMethod(typeof(BossBrain), nameof(Activated)));
        }

        // only the first read of ProfileSettings.Role is the switch; later reads (e.g. the agent's debug name) stay untouched
        private static IEnumerable<CodeInstruction> Transpile(IEnumerable<CodeInstruction> code, MethodBase original)
        {
            var role = AccessTools.Field(typeof(ProfileSettings), nameof(ProfileSettings.Role))
                       ?? throw new MissingFieldException("ProfileSettings.Role");
            var map = AccessTools.Method(typeof(BossBrain), nameof(MapRole));
            int count = 0;
            foreach (var instruction in code)
            {
                yield return instruction;
                if (count == 0 && instruction.opcode == OpCodes.Ldfld && Equals(instruction.operand, role))
                {
                    count++;
                    yield return new CodeInstruction(OpCodes.Call, map);
                }
            }
            Mapped[original] = count;
        }

        private static void Activated(StandartBotBrain __instance)
        {
            try
            {
                var owner = __instance._owner;
                if (owner?.Profile?.Info?.Settings?.Role != WildSpawnType.bossTest) return;
                Plugin.Log.LogInfo($"[Juggernaut] boss {owner.Profile.Nickname}: brain {__instance.BaseBrain?.GetType().Name} ({__instance.BaseBrain?.ShortName()}), weapon selector {owner.WeaponManager?.Selector?.GetType().Name}, enemy chooser {owner.EnemyChooser?.GetType().Name}");
            }
            catch (Exception ex) { Plugin.Log.LogWarning("[Juggernaut] boss brain log failed: " + ex.Message); }
        }
    }
}
