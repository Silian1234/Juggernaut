using EFT;
using EFT.InventoryLogic;
using HarmonyLib;
using EFT.Ballistics;

namespace JuggernautClient
{
    internal static class ExoskeletonMelee
    {
        internal static void Patch(Harmony harmony)
        {
            harmony.Patch(AccessTools.DeclaredMethod(typeof(GameWorld), nameof(GameWorld.HackShot),
                new[] { typeof(DamageInfo) }), prefix: new HarmonyMethod(typeof(ExoskeletonMelee), nameof(ScaleKnifeHit)));
        }

        // Both knife strikes construct their own DamageInfo before HackShot.
        private static void ScaleKnifeHit(ref DamageInfo __0)
        {
            if (__0.DamageType != EDamageType.Melee || __0.Weapon?.GetItemComponent<KnifeComponent>() == null) return;
            int tier = JugTiers.Tier(__0.Player?.iPlayer as Player);
            if (tier > 0) __0.Damage *= JugTiers.Melee[tier];
        }
    }
}
