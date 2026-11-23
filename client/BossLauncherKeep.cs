// The boss's grenade launcher must never become loot.
// The server marks it Unlootable from the SecondPrimaryWeapon slot of his body. A weapon in hands at death is thrown to the
// ground by the death animation (FirearmController.OnDropWeapon -> InventoryController.ThrowItem), and Unlootable does not
// apply on the ground, so the launcher is kept in its slot instead of being dropped.
using EFT;
using HarmonyLib;

namespace JuggernautClient
{
    internal static class BossLauncherKeep
    {
        private static readonly AccessTools.FieldRef<Player.ItemHandsController, Player> HandsPlayer =
            AccessTools.FieldRefAccess<Player.ItemHandsController, Player>("_player");

        internal static void Patch(Harmony harmony)
        {
            var drop = AccessTools.DeclaredMethod(typeof(Player.FirearmController), nameof(Player.FirearmController.OnDropWeapon))
                       ?? throw new System.MissingMethodException("Player.FirearmController.OnDropWeapon");
            harmony.Patch(drop, prefix: new HarmonyMethod(typeof(BossLauncherKeep), nameof(Prefix)));
        }

        // any process (host or observer): never drop the launcher; it stays in the corpse's weapon slot
        private static bool Prefix(Player.FirearmController __instance)
        {
            try
            {
                if (__instance?.Item?.StringTemplateId != BossCommon.GrenadeLauncherTpl) return true;
                var player = HandsPlayer(__instance);
                Plugin.Log.LogInfo($"[Juggernaut] boss {player?.Profile?.Nickname}: grenade launcher kept on the body (not dropped)");
                return false;
            }
            catch { return true; }
        }
    }
}
