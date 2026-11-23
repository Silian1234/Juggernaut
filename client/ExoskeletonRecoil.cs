// EXO-2 / EXO-3: slightly lower recoil for the local player (JugTiers.Recoil: x0.95 / x0.90).
// Scales the per-shot recoil force fed into the new recoil system; weapon stats, sensitivity and dispersion are untouched.
using Comfort.Common;
using EFT;
using EFT.Animations.NewRecoil;
using HarmonyLib;

namespace JuggernautClient
{
    internal static class ExoskeletonRecoil
    {
        // SPT 4.1 (EFT 40743): private field _firearmController (4.0: public FirearmController)
        private static readonly AccessTools.FieldRef<NewRecoilShotEffect, Player.FirearmController> Firearm =
            AccessTools.FieldRefAccess<NewRecoilShotEffect, Player.FirearmController>("_firearmController");

        internal static void Patch(Harmony harmony)
        {
            var add = AccessTools.DeclaredMethod(typeof(NewRecoilShotEffect), nameof(NewRecoilShotEffect.AddRecoilForce), new[] { typeof(float) })
                      ?? throw new System.MissingMethodException("NewRecoilShotEffect.AddRecoilForce(float)");
            harmony.Patch(add, prefix: new HarmonyMethod(typeof(ExoskeletonRecoil), nameof(ScaleRecoil)));
        }

        private static void ScaleRecoil(NewRecoilShotEffect __instance, ref float __0)
        {
            var player = Singleton<GameWorld>.Instance?.MainPlayer;
            var firearm = Firearm(__instance);
            if (player == null || firearm == null || !ReferenceEquals(player.HandsController, firearm)) return;
            __0 *= JugTiers.Recoil[JugTiers.Tier(player)];
        }
    }
}
