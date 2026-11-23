// Juggernaut From TushonkaGroup — client plugin.
using System;
using System.IO;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;

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
            Feature("suit footsteps", JugSound.Patch);
            ExoskeletonMovement.Patch(harmony);
            ExoskeletonTraversal.Patch(new Harmony("com.silian.juggernaut.traversal"));
            SettingsMenu.Init(Config);
            JugSound.Init(Config);
            StartCoroutine(JugSound.Load(Path.Combine(Path.GetDirectoryName(Info.Location), "sfx")));
            ThermalOutline.Install(gameObject, Path.Combine(Path.GetDirectoryName(Info.Location), "juggernaut_thermal.bundle"), Log);
        }

        private void Update()
        {
            SettingsMenu.Tick();
            JugSet.Tick();
            JugSound.Tick();
        }
    }
}
