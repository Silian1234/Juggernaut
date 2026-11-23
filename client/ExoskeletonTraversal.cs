// EXO-3 traversal: small falls cushioned (local player), vault/climb x1.15 when still overweight.
// Obfuscated members are resolved at runtime (see ExoResolve); fall and vault are patched independently.
using System;
using System.Runtime.CompilerServices;
using Comfort.Common;
using EFT;
using EFT.HealthSystem;
using EFT.Vaulting;
using HarmonyLib;
using UnityEngine;

namespace JuggernautClient
{
    internal static class ExoskeletonTraversal
    {
        private static readonly AccessTools.FieldRef<MovementContext, Player> MovementPlayer =
            AccessTools.FieldRefAccess<MovementContext, Player>("_player");
        private static readonly ConditionalWeakTable<MovementContext, VaultTiming> VaultTimings = new();
        private static Action<MovementContext, Vector2, EVaultingStrategy> _computeVaultSpeed;   // MovementContext.method_17
        private static Func<object, float> _fallSafeHeight;                                       // ActiveHealthController FallSafeHeight backing field

        private sealed class VaultTiming
        {
            internal bool Preparing;
            internal bool Pending;
            internal EVaultingStrategy Strategy;
            internal float Speed;
            internal int Frame;

            internal bool TryConsume(EVaultingStrategy strategy, int frame, out float speed)
            {
                speed = Speed;
                if (!Pending) return false;
                Pending = false;
                return Strategy == strategy && frame - Frame <= 120;
            }
        }

        internal static void Patch(Harmony harmony)
        {
            Try("fall cushion", () =>
            {
                var fall = AccessTools.DeclaredMethod(typeof(ActiveHealthController), nameof(ActiveHealthController.HandleFall), new[] { typeof(float) })
                           ?? throw new MissingMethodException("ActiveHealthController.HandleFall(float)");
                // backing field: FallSafeHeight_1 (EFT 40087) / _fallSafeHeight (EFT 40743); the property has only a setter
                try { _fallSafeHeight = ExoResolve.FloatMember(typeof(ActiveHealthController), "FallSafeHeight"); }
                catch (MissingMemberException) { _fallSafeHeight = ExoResolve.FloatMember(typeof(ActiveHealthController), "_fallSafeHeight"); }
                harmony.Patch(fall, prefix: Hook(nameof(CushionFall)));
            });

            Try("vault speed", () =>
            {
                // MovementContext.<compute vault speed>(Vector2 speedRange, EVaultingStrategy strategy)
                var vault = ExoResolve.SingleMethod(typeof(MovementContext), "vault speed calculation",
                    m => m.ReturnType == typeof(void) && ExoResolve.Params(m, typeof(Vector2), typeof(EVaultingStrategy)));
                _computeVaultSpeed = AccessTools.MethodDelegate<Action<MovementContext, Vector2, EVaultingStrategy>>(vault);
                harmony.Patch(vault, postfix: Hook(nameof(SetLocalVaultSpeed)));
                var fikaPlayer = AccessTools.TypeByName("Fika.Core.Main.Players.FikaPlayer");
                if (fikaPlayer != null)
                {
                    var send = AccessTools.DeclaredMethod(fikaPlayer, "OnVaulting", Type.EmptyTypes)
                               ?? throw new MissingMethodException(fikaPlayer.FullName, "OnVaulting");
                    harmony.Patch(send, prefix: Hook(nameof(PrepareVaultPacket)));
                }
            });
        }

        private static void Try(string feature, Action patch)
        {
            try { patch(); Plugin.Log.LogInfo($"[Juggernaut] {feature}: hooked"); }
            catch (Exception ex) { Plugin.Log.LogError($"[Juggernaut] {feature}: DISABLED — {ex.Message}"); }
        }

        // field or property, whichever exists
        private static Traverse Member(Traverse t, string name)
        {
            var f = t.Field(name);
            return f.FieldExists() ? f : t.Property(name);
        }

        private static HarmonyMethod Hook(string method) => new(typeof(ExoskeletonTraversal), method);

        private static bool IsLocal(Player player) =>
            player != null && ReferenceEquals(Singleton<GameWorld>.Instance?.MainPlayer, player);

        private static void CushionFall(ActiveHealthController __instance, ref float __0)
        {
            int tier = JugTiers.Tier(__instance.Player);
            if (IsLocal(__instance.Player) && tier > 0)
                __0 = ExoskeletonTraversalRules.CushionedFallHeight(__0, _fallSafeHeight(__instance), JugTiers.FallCushion[tier]);
        }

        private static void SetLocalVaultSpeed(MovementContext __instance, EVaultingStrategy __1)
        {
            var player = MovementPlayer(__instance);
            if (!IsLocal(player)) return;
            if (VaultTimings.TryGetValue(__instance, out var timing))
            {
                if (timing.Preparing) return;
                if (timing.TryConsume(__1, Time.frameCount, out var speed)) { SetVaultSpeed(__instance, speed); return; }
            }
            SetVaultSpeed(__instance, SpeedForGear(__instance.VaultingSpeed, player));
        }

        private static float SpeedForGear(float speed, Player player) => player.Physical is { } physical
            ? ExoskeletonTraversalRules.VaultSpeed(speed, physical.Overweight, physical.WalkOverweight, JugTiers.Tier(player))
            : speed;

        private static void SetVaultSpeed(MovementContext movement, float speed)
        {
            if (speed == movement.VaultingSpeed) return;
            movement.VaultingSpeed = speed;
            movement.PlayerAnimator.SetVaultingSpeed(speed);
        }

        // Fika sends the vault packet before the animator enters the state that normally computes the local speed.
        private static void PrepareVaultPacket(Player __instance)
        {
            if (!IsLocal(__instance) || __instance.MovementContext is not { } movement || __instance.VaultingParameters is not { } parameters) return;
            if (!VaultTimings.TryGetValue(movement, out var timing) && JugTiers.Tier(__instance) == 0) return;
            var strategy = parameters.GetVaultingStrategy();
            // GlobalConfiguration.VaultingSettings.MovesSettings.{Vault|Climb}Settings.SpeedRange (read by reflection)
            var moves = Member(Member(Traverse.Create(Singleton<GlobalConfiguration>.Instance), "VaultingSettings"), "MovesSettings");
            var settings = strategy switch
            {
                EVaultingStrategy.Vault => Member(moves, "VaultSettings"),
                EVaultingStrategy.Climb => Member(moves, "ClimbSettings"),
                _ => null
            };
            if (settings?.GetValue() == null) return;
            var range = Member(settings, "SpeedRange").GetValue<Vector2>();

            timing ??= VaultTimings.GetValue(movement, _ => new VaultTiming());
            timing.Pending = false;
            timing.Preparing = true;
            try { _computeVaultSpeed(movement, range, strategy); }
            finally { timing.Preparing = false; }
            timing.Speed = SpeedForGear(movement.VaultingSpeed, __instance);
            SetVaultSpeed(movement, timing.Speed);
            timing.Strategy = strategy;
            timing.Frame = Time.frameCount;
            timing.Pending = true;
        }
    }

    internal static class ExoskeletonTraversalRules
    {
        private const float FullCushionHeight = 3f;
        private const float MaximumFallHeight = 4f;
        // cushion (metres) per tier: JugTiers.FallCushion; full up to 3 m, tapering to zero at 4 m
        // The Juggernaut's cushion simply takes cushionMetres off every fall (the FBA taper capped it at 4 m falls).
        internal static float CushionedFallHeight(float height, float safeHeight, float cushionMetres)
        {
            if (!(height > safeHeight)) return height;
            return Math.Max(safeHeight, height - cushionMetres);
        }

        internal static float VaultSpeed(float speed, float overweight, float walkOverweight, int tier) =>
            tier > 0 && (overweight > 0f || walkOverweight > 0f) ? speed * JugTiers.Vault[tier] : speed;
    }
}
