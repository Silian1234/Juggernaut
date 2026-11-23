// EXO-3 movement: sprint speed x1.15, sprint + hand stamina drain x0.75, overweight limits +15 kg, jump height x1.25.
// Obfuscated members are resolved at runtime (see ExoResolve); each feature is patched independently.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using Comfort.Common;
using EFT;
using HarmonyLib;
using UnityEngine;

namespace JuggernautClient
{
    internal static class ExoskeletonMovement
    {
        // per-tier values: JugTiers (sprint, stamina, overweight, jump)
        private static readonly AccessTools.FieldRef<MovementContext, Player> MovementPlayer =
            AccessTools.FieldRefAccess<MovementContext, Player>("_player");
        private static readonly ConditionalWeakTable<PhysicalBase, object> ShiftedLimits = new();

        // resolved at runtime
        private static AccessTools.FieldRef<Physical, Player> _physicalPlayer;   // Physical.Player_0
        private static FieldInfo _jumpImpulse;                                               // JumpPlayerState.Vector3_1
        private static FieldInfo _staminaPool, _handsPool;                                   // PhysicalBase.Stamina / HandsStamina
        private static FieldInfo _consumptionType;                                           // <consumption>.ConsumptionType
        private static object _sprintConsumption;                                            // EConsumptionType.Sprint

        internal static void Patch(Harmony harmony)
        {
            // Sprint: same two points the KnifeSprint mod uses — the clamped speed and the applied motion while sprinting.
            Try("sprint speed", () =>
            {
                Install(harmony, AccessTools.PropertyGetter(typeof(MovementContext), nameof(MovementContext.ClampedSpeed)), postfix: nameof(ClampedSpeedPostfix));
                Install(harmony, AccessTools.DeclaredMethod(typeof(MovementState), nameof(MovementState.ApplyMotion)), prefix: nameof(ApplyMotionPrefix));
            });

            Try("jump height", () =>
            {
                var enter = AccessTools.DeclaredMethod(typeof(JumpPlayerState), nameof(JumpPlayerState.Enter));
                _jumpImpulse = ExoResolve.LastStoredField(enter, typeof(Vector3), "jump impulse");
                Install(harmony, enter, postfix: nameof(JumpPostfix));
            });

            // Weight: add the suit's kilograms to the health controller's absolute carrying-weight modifier
            // (the same input stimulator buffs use), so the game's own limit formula and the inventory UI pick it up.
            Try("weight limits", () =>
            {
                _physicalPlayer = AccessTools.FieldRefAccess<Physical, Player>(
                    ExoResolve.SingleField(typeof(Physical), typeof(Player), "physical owner"));
                MethodInfo getter = null;
                for (var t = typeof(EFT.HealthSystem.ActiveHealthController); t != null && getter == null; t = t.BaseType)
                    getter = t.GetMethod("get_CarryingWeightAbsoluteModifier", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
                Install(harmony, getter ?? throw new MissingMethodException("CarryingWeightAbsoluteModifier getter"), postfix: nameof(CarryWeightPostfix));
                Install(harmony, AccessTools.DeclaredMethod(typeof(PhysicalBase), nameof(PhysicalBase.LateUpdate)), prefix: nameof(WeightRefreshPrefix));
            });

            Try("stamina drain", () =>
            {
                _staminaPool = AccessTools.Field(typeof(PhysicalBase), "Stamina") ?? throw new MissingFieldException("Stamina");
                _handsPool = AccessTools.Field(typeof(PhysicalBase), "HandsStamina") ?? throw new MissingFieldException("HandsStamina");
                var poolType = _staminaPool.FieldType;                                  // GClass774
                var consume = AccessTools.DeclaredMethod(poolType, "Consume") ?? throw new MissingMethodException(poolType.Name, "Consume");
                var process = AccessTools.DeclaredMethod(poolType, "Process") ?? throw new MissingMethodException(poolType.Name, "Process");
                var consumptionType = consume.GetParameters()[0].ParameterType;         // GClass773
                _consumptionType = AccessTools.Field(consumptionType, "ConsumptionType") ?? throw new MissingFieldException("ConsumptionType");
                _sprintConsumption = Enum.Parse(_consumptionType.FieldType, "Sprint");
                DeltaField = AccessTools.Field(consumptionType, "Delta") ?? throw new MissingFieldException("Delta");
                ConsumptionClass = consumptionType;
                Install(harmony, consume, transpiler: nameof(DrainTranspiler));
                Install(harmony, process, transpiler: nameof(DrainTranspiler));
            });
        }

        private static void Try(string feature, Action patch)
        {
            try { patch(); Plugin.Log.LogInfo($"[Juggernaut] {feature}: hooked"); }
            catch (Exception ex) { Plugin.Log.LogError($"[Juggernaut] {feature}: DISABLED — {ex.Message}"); }
        }

        private static void Install(Harmony harmony, MethodBase method, string prefix = null, string postfix = null, string transpiler = null)
        {
            if (method == null) throw new MissingMethodException("target method not found");
            HarmonyMethod Hook(string name) => name == null ? null : new HarmonyMethod(typeof(ExoskeletonMovement), name);
            harmony.Patch(method, prefix: Hook(prefix), postfix: Hook(postfix), transpiler: Hook(transpiler));
        }

        private static Player PhysicalPlayer(PhysicalBase physical) =>
            physical is Physical p && _physicalPlayer != null ? _physicalPlayer(p) : null;

        // ---- sprint ----
        private static bool IsLocal(Player p) => p != null && ReferenceEquals(Singleton<GameWorld>.Instance?.MainPlayer, p);

        private static void ClampedSpeedPostfix(MovementContext __instance, ref float __result)
        {
            if (!__instance.IsSprintEnabled) return;
            var p = MovementPlayer(__instance);
            if (IsLocal(p)) __result *= JugTiers.Sprint[JugTiers.Tier(p)];
        }

        private static void ApplyMotionPrefix(MovementState __instance, ref Vector3 __0)
        {
            var ctx = __instance.MovementContext;
            if (ctx == null || !ctx.IsSprintEnabled) return;
            var p = MovementPlayer(ctx);
            if (IsLocal(p)) __0 *= JugTiers.Sprint[JugTiers.Tier(p)];
        }

        // ---- jump ----
        private static void JumpPostfix(JumpPlayerState __instance)
        {
            int tier = JugTiers.Tier(MovementPlayer(__instance.MovementContext));
            if (_jumpImpulse == null || tier == 0) return;
            var v = (Vector3)_jumpImpulse.GetValue(__instance);
            v.y *= Mathf.Sqrt(JugTiers.Jump[tier]);   // height ~ v^2
            _jumpImpulse.SetValue(__instance, v);
        }

        // ---- weight ----
        private static void CarryWeightPostfix(object __instance, ref float __result)
        {
            var p = Singleton<GameWorld>.Instance?.MainPlayer;
            if (p != null)
            {
                if (ReferenceEquals(p.HealthController, __instance)) __result += JugTiers.Overweight[JugTiers.Tier(p)];
                return;
            }
            // Out of raid (stash, traders, builds, hideout menus) there is no player object: the only live
            // health controller is the profile's own, so read the suit from the session profile's equipment.
            if (!TarkovApplication.Exist(out var app)) return;
            var equipment = app.GetClientBackEndSession()?.Profile?.Inventory?.Equipment;
            __result += JugTiers.Overweight[JugTiers.TierOf(equipment?.GetSlot(EFT.InventoryLogic.EquipmentSlot.ArmorVest)?.ContainedItem?.StringTemplateId)];
        }

        // re-run the game's limit calculation when the local player's suit tier changes
        private static void WeightRefreshPrefix(PhysicalBase __instance)
        {
            var p = PhysicalPlayer(__instance);
            if (!IsLocal(p)) return;
            int tier = JugTiers.Tier(p);
            int applied = ShiftedLimits.TryGetValue(__instance, out var t) ? (int)t : 0;
            if (tier == applied) return;
            ShiftedLimits.Remove(__instance);
            ShiftedLimits.Add(__instance, tier);
            __instance.OnWeightLimitsUpdated();
        }

        // ---- stamina ----
        private static FieldInfo DeltaField;
        private static Type ConsumptionClass;

        private static IEnumerable<CodeInstruction> DrainTranspiler(IEnumerable<CodeInstruction> instructions, MethodBase original)
        {
            var code = instructions.ToList();
            var hits = code.Select((instruction, i) => (instruction, i)).Where(x => x.instruction.LoadsField(DeltaField)).Select(x => x.i).ToArray();
            bool continuous = original.Name == "Process";
            if (hits.Length != (continuous ? 2 : 1) || !(code[hits[0] + 1].operand is MethodInfo read) ||
                read.Name != (continuous ? "op_Implicit" : "get_Value"))
                throw new InvalidOperationException("stamina cost calculation changed: " + original.Name);
            // Process reads Delta once for the cost and again only for the restoration cooldown.
            int index = hits[0];
            var loadConsumption = code[index - 1];
            if (loadConsumption.opcode != OpCodes.Ldarg_1 && loadConsumption.opcode != OpCodes.Ldloc_S && loadConsumption.opcode != OpCodes.Ldloc)
                throw new InvalidOperationException("stamina consumption source changed");
            var insert = new List<CodeInstruction>
            {
                new CodeInstruction(OpCodes.Ldarg_0),
                new CodeInstruction(loadConsumption.opcode, loadConsumption.operand),
            };
            if (ConsumptionClass.IsValueType) insert.Add(new CodeInstruction(OpCodes.Box, ConsumptionClass));
            insert.Add(new CodeInstruction(OpCodes.Call, AccessTools.Method(typeof(ExoskeletonMovement), nameof(ScaleDrain))));
            code.InsertRange(index + 2, insert);
            return code;
        }

        private static float ScaleDrain(float cost, object pool, object consumption)
        {
            if (cost <= 0f) return cost;
            var player = Singleton<GameWorld>.Instance?.MainPlayer;
            var physical = player?.Physical;
            if (physical == null) return cost;
            bool hands = ReferenceEquals(pool, _handsPool.GetValue(physical));
            bool sprint = !hands && ReferenceEquals(pool, _staminaPool.GetValue(physical)) &&
                          Equals(_consumptionType.GetValue(consumption), _sprintConsumption);
            return hands || sprint ? cost * JugTiers.Stamina[JugTiers.Tier(player)] : cost;
        }
    }
}
