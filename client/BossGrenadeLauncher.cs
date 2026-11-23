// Juggernaut boss grenade launcher (an M32A1 clone: a Revolver-class weapon with a 6-camora CylinderMagazine), host side.
//   - Cylinder never runs dry: FireCylinderMagOperation.PrepareShot removes the round from its camora (RemoveAmmoInCamora);
//     right after the shot event the same camora gets a fresh clone of the fired round (Ammo.Clone + Slot.AddWithoutRestrictions),
//     so Count stays at the maximum and BotReload.CanReloadPreCheck (MaxCount == current count) never starts a reload.
//   - Fire interval: ShootData.UpdNextFingerDown sets when the bot may pull the trigger again; the postfix raises it to
//     (time of the last trigger pull + BossFireInterval).
// Both only act for bossTest bots simulated by this process (BossCommon.IsBossAI).
using System;
using EFT;
using EFT.InventoryLogic;
using HarmonyLib;
using UnityEngine;

namespace JuggernautClient
{
    internal static class BossGrenadeLauncher
    {
        private static int _shots, _refillFailures, _intervalLogs;

        internal static void Patch(Harmony harmony)
        {
            var fire = AccessTools.DeclaredMethod(typeof(Player.FirearmController.FireCylinderMagOperation), "OnFireEvent")
                       ?? throw new MissingMethodException("FireCylinderMagOperation.OnFireEvent");
            harmony.Patch(fire, postfix: new HarmonyMethod(typeof(BossGrenadeLauncher), nameof(AfterFire)));
            var next = AccessTools.DeclaredMethod(typeof(ShootData), nameof(ShootData.UpdNextFingerDown))
                       ?? throw new MissingMethodException("ShootData.UpdNextFingerDown");
            harmony.Patch(next, postfix: new HarmonyMethod(typeof(BossGrenadeLauncher), nameof(AfterNextFingerDown)));
        }

        private static void AfterFire(Player.FirearmController.FireCylinderMagOperation __instance)
        {
            try
            {
                var player = __instance.Player;
                if (!BossCommon.IsBossAI(player)) return;
                var magazine = __instance._cylinderMagazine;
                int index = __instance._camoraIndex;
                var fired = __instance._singleShotData.AmmoToFire;
                if (magazine == null || fired == null || index < 0 || index >= magazine.Camoras.Length) return;
                _shots++;
                var camora = magazine.Camoras[index];
                if (camora.ContainedItem != null) return;   // nothing was removed (dry fire) or already refilled
                var round = fired.Clone(MongoID.Generate().ToString());
                round.IsUsed = false;
                var result = camora.AddWithoutRestrictions(round);
                if (result.Failed)
                {
                    if (_refillFailures++ < 3) Plugin.Log.LogWarning($"[Juggernaut] boss grenade launcher refill failed: {result.Error}");
                    return;
                }
                if (_shots <= 3 || _shots % 20 == 0)
                    Plugin.Log.LogInfo($"[Juggernaut] boss shot #{_shots} with {__instance.Weapon.ShortName.Localized()} ({fired.Template.NameLocalizationKey?.Localized() ?? fired.TemplateId.ToString()}): camora {index} refilled, cylinder {magazine.Count}/{magazine.MaxCount}");
            }
            catch (Exception ex)
            {
                if (_refillFailures++ < 3) Plugin.Log.LogWarning("[Juggernaut] boss grenade launcher refill hook failed: " + ex);
            }
        }

        private static void AfterNextFingerDown(ShootData __instance)
        {
            try
            {
                var owner = __instance._owner;
                if (owner == null || !BossCommon.IsBossAI(owner.GetPlayer)) return;
                if (!(owner.WeaponManager?.CurrentWeapon is Revolver)) return;   // only the grenade launcher; the PKP keeps its own cadence
                float interval = Mathf.Max(0f, ServerSettings.Get().BossFireInterval);
                float allowed = __instance.LastTriggerPressd + interval;
                if (__instance.nextFingerDownCan >= allowed) return;
                __instance.nextFingerDownCan = allowed;
                if (_intervalLogs++ < 3) Plugin.Log.LogInfo($"[Juggernaut] boss grenade launcher: next shot not before {interval:0.##} s after the last one");
            }
            catch (Exception ex)
            {
                if (_intervalLogs++ < 3) Plugin.Log.LogWarning("[Juggernaut] boss fire interval hook failed: " + ex.Message);
            }
        }
    }
}
