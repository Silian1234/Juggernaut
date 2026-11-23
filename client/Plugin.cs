// Juggernaut From TushonkaGroup — client plugin.
using System;
using System.IO;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace JuggernautClient
{
    [BepInPlugin("com.silian.juggernaut.client", "Juggernaut From TushonkaGroup", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        internal static ManualLogSource Log;

        private void Awake()
        {
            Log = Logger;
            var harmony = new Harmony("com.silian.juggernaut.client");
            void Feature(string name, Action<Harmony> patch)
            {
                try { patch(harmony); Log.LogInfo($"[Juggernaut] {name}: hooked"); }
                catch (Exception ex) { Log.LogError($"[Juggernaut] {name}: DISABLED — {ex.Message}"); }
            }
            Feature("melee", ExoskeletonMelee.Patch);
            Feature("recoil", ExoskeletonRecoil.Patch);
            Feature("sprint/jump block", JugDebuffs.Patch);
            Feature("thermal picture block", ThermalPictureBlock.Patch);
            Feature("boss launcher stays on the body", BossLauncherKeep.Patch);
            Feature("suit footsteps", JugSound.Patch);
            Feature("exoskeleton movement", ExoskeletonMovement.Patch);
            Feature("exoskeleton traversal", _ => ExoskeletonTraversal.Patch(new Harmony("com.silian.juggernaut.traversal")));
            // raid boss (bossTest): runs on the raid host, which may be a Fika headless client
            Feature("boss role switches (bossTest -> followerBigPipe)", BossBrain.Patch);
            Feature("boss damage / discharge / sprint", BossDamage.Patch);
            Feature("boss grenade launcher (refill, fire interval)", BossGrenadeLauncher.Patch);
            Feature("boss test spawn", BossTestSpawn.Patch);
            SettingsMenu.Init(Config);
            JugSound.Init(Config);
            StartCoroutine(JugSound.Load(Path.Combine(Path.GetDirectoryName(Info.Location), "sfx")));
            // a headless host has no graphics device: no thermal outline there
            if (Application.isBatchMode) Log.LogInfo("[Juggernaut] batch mode (headless host): thermal outline not installed");
            else
            {
                try { ThermalOutline.Install(gameObject, Path.Combine(Path.GetDirectoryName(Info.Location), "juggernaut_thermal.bundle"), Log); }
                catch (Exception ex) { Log.LogError("[Juggernaut] thermal outline: DISABLED — " + ex.Message); }
            }
        }

        private readonly int[] _tickErrors = new int[3];

        private void Update()
        {
            // every per-frame feature guards against a missing main player / camera itself; this keeps one failure from
            // stopping the others (and from spamming the log) on a headless host
            try { ServerSettings.RefreshOnNewRaid(Comfort.Common.Singleton<EFT.GameWorld>.Instance); } catch { }
            Guarded(0, "settings", SettingsMenu.Tick);
            Guarded(1, "set power", JugSet.Tick);
            Guarded(2, "sound", JugSound.Tick);
        }

        private void Guarded(int slot, string name, Action tick)
        {
            if (_tickErrors[slot] >= 5) return;
            try { tick(); }
            catch (Exception ex)
            {
                if (++_tickErrors[slot] >= 5) Log.LogError($"[Juggernaut] {name} update disabled after repeated errors: {ex}");
                else Log.LogWarning($"[Juggernaut] {name} update error: {ex.Message}");
            }
        }
    }
}
