// Juggernaut boss damage rules (host side, bossTest bots only).
//   - Player.ApplyDamageInfo is where every damage source ends for a player object, after armor: bullets (ApplyShot ->
//     ApplyDamageInfo, also Fika's FikaBot.ApplyShot), explosions and fragments (the body-part bridge calls it directly).
//     Fika's FikaBot/FikaPlayer overrides call the base method once, so a prefix on Player.ApplyDamageInfo runs once per hit.
//   - A hit on the battery pack (back or sides of the torso: body colliders SpineTop/SpineDown and the side chest
//     colliders, or a back/side armor plate collider) uses BossBackDamage and immediately switches the armor off for
//     DischargeSeconds: damage multiplier 1.0 from every side and no sprint. Every further such hit restarts the timer.
//   - Sprint: BotOwner.Sprint / BotMover.Sprint are the bot AI's only sprint switches; while discharged the request is turned
//     into "stop", and MovementContext.CanSprint answers false as a second guard.
using System;
using System.Runtime.CompilerServices;
using EFT;
using EFT.Ballistics;
using EFT.HealthSystem;
using HarmonyLib;
using UnityEngine;

namespace JuggernautClient
{
    internal static class BossDamage
    {
        private const float DischargeSeconds = 25f;

        private sealed class State { public float DischargedUntil; }
        [ThreadStatic] private static bool _backPlateHit;
        private static readonly ConditionalWeakTable<Player, State> States = new ConditionalWeakTable<Player, State>();
        private static readonly AccessTools.FieldRef<MovementContext, Player> MovementPlayer =
            AccessTools.FieldRefAccess<MovementContext, Player>("_player");
        private static bool _failedLogged;

        internal static void Patch(Harmony harmony)
        {
            var apply = AccessTools.DeclaredMethod(typeof(Player), nameof(Player.ApplyDamageInfo),
                            new[] { typeof(DamageInfo), typeof(EBodyPart), typeof(EBodyPartColliderType), typeof(float) })
                        ?? throw new MissingMethodException("Player.ApplyDamageInfo");
            harmony.Patch(apply, prefix: new HarmonyMethod(typeof(BossDamage), nameof(ApplyDamagePrefix)));
            // bullets come through ApplyShot first; it knows which armor plate collider was hit
            var shot = AccessTools.DeclaredMethod(typeof(Player), nameof(Player.ApplyShot))
                       ?? throw new MissingMethodException("Player.ApplyShot");
            harmony.Patch(shot, prefix: new HarmonyMethod(typeof(BossDamage), nameof(ApplyShotPrefix)),
                          finalizer: new HarmonyMethod(typeof(BossDamage), nameof(ApplyShotFinalizer)));

            var ownerSprint = AccessTools.DeclaredMethod(typeof(BotOwner), nameof(BotOwner.Sprint), new[] { typeof(bool), typeof(bool) })
                              ?? throw new MissingMethodException("BotOwner.Sprint(bool,bool)");
            harmony.Patch(ownerSprint, prefix: new HarmonyMethod(typeof(BossDamage), nameof(OwnerSprintPrefix)));
            var moverSprint = AccessTools.DeclaredMethod(typeof(BotMover), nameof(BotMover.Sprint), new[] { typeof(bool), typeof(bool) })
                              ?? throw new MissingMethodException("BotMover.Sprint(bool,bool)");
            harmony.Patch(moverSprint, prefix: new HarmonyMethod(typeof(BossDamage), nameof(MoverSprintPrefix)));
            harmony.Patch(AccessTools.PropertyGetter(typeof(MovementContext), nameof(MovementContext.CanSprint)),
                postfix: new HarmonyMethod(typeof(BossDamage), nameof(CanSprintPostfix)));
        }

        internal static bool IsDischarged(Player p) =>
            p != null && States.TryGetValue(p, out var s) && Time.time < s.DischargedUntil;

        // damageInfo is a by-value struct parameter: `ref` lets the prefix change the damage that the original then applies
        private static void ApplyShotPrefix(EArmorPlateCollider __3) =>
            _backPlateHit = __3.ToString().IndexOf("back", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            __3.ToString().IndexOf("side", StringComparison.OrdinalIgnoreCase) >= 0;

        private static Exception ApplyShotFinalizer(Exception __exception) { _backPlateHit = false; return __exception; }

        private static void ApplyDamagePrefix(Player __instance, ref DamageInfo damageInfo, EBodyPartColliderType __2)
        {
            try
            {
                if (!BossCommon.IsBossAI(__instance) || !damageInfo.DamageType.IsEnemyDamage() || damageInfo.Damage <= 0f) return;
                var settings = ServerSettings.Get();
                var state = States.GetOrCreateValue(__instance);
                bool discharged = Time.time < state.DischargedUntil;
                if (!discharged && state.DischargedUntil > 0f)
                {
                    state.DischargedUntil = 0f;
                    Plugin.Log.LogInfo("[Juggernaut] boss recharged: damage reduction and sprint are back");
                }
                bool back = _backPlateHit || __2 == EBodyPartColliderType.SpineTop || __2 == EBodyPartColliderType.SpineDown ||
                            __2 == EBodyPartColliderType.LeftSideChestUp || __2 == EBodyPartColliderType.LeftSideChestDown ||
                            __2 == EBodyPartColliderType.RightSideChestUp || __2 == EBodyPartColliderType.RightSideChestDown;
                float multiplier = discharged ? 1f : back ? settings.BossBackDamage : settings.BossDamageTaken;
                float before = damageInfo.Damage;
                damageInfo.Damage = before * multiplier;
                string kind = discharged ? "discharged" : back ? "battery" : "front";
                if (back) Discharge(__instance, state, !discharged);
                Plugin.Log.LogInfo($"[Juggernaut] boss hit ({kind}, {damageInfo.DamageType}, collider {__2}{(_backPlateHit ? ", battery plate" : "")}): damage {before:0.#} -> {damageInfo.Damage:0.#} (x{multiplier:0.##})");
            }
            catch (Exception ex)
            {
                if (_failedLogged) return;
                _failedLogged = true;
                Plugin.Log.LogWarning("[Juggernaut] boss damage hook failed: " + ex);
            }
        }

        private static void Discharge(Player boss, State state, bool firstHit)
        {
            state.DischargedUntil = Time.time + DischargeSeconds;
            Plugin.Log.LogInfo(firstHit ? $"[Juggernaut] boss battery hit: armor OFF for {DischargeSeconds:0} s (full damage from every side, no sprint)"
                                        : $"[Juggernaut] boss battery hit again: armor stays off, timer reset to {DischargeSeconds:0} s");
            try
            {
                var mover = boss.AIData.BotOwner.Mover;
                mover?.SprintPause(DischargeSeconds);
                mover?.Sprint(false);   // stops a sprint that is already running
            }
            catch (Exception ex) { Plugin.Log.LogWarning("[Juggernaut] could not stop the boss sprint: " + ex.Message); }
        }

        private static void OwnerSprintPrefix(BotOwner __instance, ref bool val)
        {
            if (val && IsDischarged(__instance.GetPlayer)) val = false;
        }

        private static void MoverSprintPrefix(BotMover __instance, ref bool val)
        {
            if (val && IsDischarged(__instance._owner?.GetPlayer)) val = false;
        }

        private static void CanSprintPostfix(MovementContext __instance, ref bool __result)
        {
            if (__result && IsDischarged(MovementPlayer(__instance))) __result = false;
        }
    }
}
