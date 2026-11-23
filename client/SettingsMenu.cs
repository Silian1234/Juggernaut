// F12 (BepInEx Configuration Manager). Server settings mirror the server (owner rule); the hotkey is local.
using System;
using BepInEx.Configuration;
using UnityEngine;

namespace JuggernautClient
{
    internal static class SettingsMenu
    {
        private const string Power = "1. Power", Thermal = "2. Thermal module", Boss = "3. Juggernaut boss";
        private static ConfigEntry<float> _drain, _range;
        private static ConfigEntry<bool> _thermal;
        private static ConfigEntry<bool> _bossOn, _bossTest, _bossUnarmed;
        private static ConfigEntry<float> _bossChance, _bossHealth, _bossDamage, _bossBack, _bossGrenadeDmg, _bossGrenadeRadius, _bossInterval;
        private static ConfigEntry<string> _color;
        private static bool _syncing, _dirty;
        private static float _changedAt;

        internal static Color OutlineColor { get; private set; } = new Color(1f, 0.1f, 0.1f, 1f);

        internal static void Init(ConfigFile config)
        {
            _drain = config.Bind(Power, "Minutes per power cell", 5f, Desc("How long one power cell powers the set in raid. Server setting.", 4, new AcceptableValueRange<float>(0.5f, 60f)));
            _thermal = config.Bind(Thermal, "Enabled", true, Desc("Allow the thermal targeting module. Server setting.", 3));
            _range = config.Bind(Thermal, "Range (m)", 250f, Desc("Maximum outline distance. Server setting.", 2, new AcceptableValueRange<float>(10f, 1000f)));
            _color = config.Bind(Thermal, "Outline colour", "#FF1A1A", Desc("Outline colour as #RRGGBB. Server setting.", 1));
            const string Restart = " Takes effect when the server loads: restart the game (SPT server) after changing it.";
            const string NextRaid = " Applied from the next raid.";
            _bossOn = config.Bind(Boss, "Boss enabled", true, Desc("The Juggernaut boss can spawn in raids (Labs)." + NextRaid, 9));
            _bossChance = config.Bind(Boss, "Spawn chance (%)", 25f, Desc("Chance per Labs raid that the boss spawns." + NextRaid, 8, new AcceptableValueRange<float>(0f, 100f)));
            _bossTest = config.Bind(Boss, "Test mode", false, Desc("Boss spawns in every raid on every map, 100%, about 10 seconds after the raid starts, close to the first human player." + NextRaid, 7));
            _bossUnarmed = config.Bind(Boss, "Test mode: unarmed boss", false, Desc("Test mode only: the boss spawns without his PKP and grenade launcher (melee only), so you can walk around him and check the battery pack hits on his back and sides." + NextRaid, 7));
            _bossHealth = config.Bind(Boss, "Health multiplier", 1.5f, Desc("Multiplier on the boss's health per body part." + NextRaid, 6, new AcceptableValueRange<float>(0.1f, 20f)));
            _bossDamage = config.Bind(Boss, "Damage taken multiplier", 0.35f, Desc("Multiplier on all damage the boss takes (not from behind). Applied live on the raid host.", 5, new AcceptableValueRange<float>(0.01f, 2f)));
            _bossBack = config.Bind(Boss, "Damage from behind multiplier", 1.0f, Desc("Multiplier instead of the one above for hits on the battery pack (back and sides of the torso). Any such hit switches his armor off for 25 s: full damage from every side, no sprint. Applied live on the raid host.", 4, new AcceptableValueRange<float>(0.01f, 5f)));
            _bossGrenadeDmg = config.Bind(Boss, "Grenade damage multiplier", 0.4f, Desc("Multiplier on the damage of the boss's grenades." + Restart, 3, new AcceptableValueRange<float>(0.05f, 5f)));
            _bossGrenadeRadius = config.Bind(Boss, "Grenade radius multiplier", 0.5f, Desc("Multiplier on the explosion radius of the boss's grenades." + Restart, 2, new AcceptableValueRange<float>(0.1f, 5f)));
            _bossInterval = config.Bind(Boss, "Seconds between grenade shots", 0.6f, Desc("Minimum time between the boss's grenade shots. Applied live on the raid host.", 1, new AcceptableValueRange<float>(0.1f, 10f)));
            ServerSettings.Loaded += Show;
            config.SettingChanged += OnChanged;
            Show(ServerSettings.Get());
        }

        private static ConfigDescription Desc(string text, int order, AcceptableValueBase range = null) =>
            new ConfigDescription(text + " Shared by everyone on this server; only the settings owner can change it.",
                range, new ConfigurationManagerAttributes { Order = order });

        private static void Show(JugSettings s)
        {
            if (_drain == null || s == null) return;
            _syncing = true;
            try
            {
                _drain.Value = s.DrainMinutes; _thermal.Value = s.ThermalEnabled; _range.Value = s.ThermalRange; _color.Value = s.OutlineColor;
                _bossOn.Value = s.BossEnabled; _bossChance.Value = s.BossChance; _bossTest.Value = s.BossTestMode; _bossUnarmed.Value = s.BossTestUnarmed; _bossHealth.Value = s.BossHealth;
                _bossDamage.Value = s.BossDamageTaken; _bossBack.Value = s.BossBackDamage; _bossGrenadeDmg.Value = s.BossGrenadeDamage;
                _bossGrenadeRadius.Value = s.BossGrenadeRadius; _bossInterval.Value = s.BossFireInterval;
                if (ColorUtility.TryParseHtmlString(s.OutlineColor, out var c)) OutlineColor = c;
            }
            finally { _syncing = false; }
        }

        private static void OnChanged(object sender, SettingChangedEventArgs e)
        {
            if (_syncing || e?.ChangedSetting == null) return;
            var section = e.ChangedSetting.Definition.Section;
            if (section != Power && section != Thermal && section != Boss) return;
            _dirty = true;
            _changedAt = Time.realtimeSinceStartup;
        }

        internal static void Tick()
        {
            if (!_dirty || Time.realtimeSinceStartup - _changedAt < 0.6f) return;
            _dirty = false;
            var wanted = ServerSettings.Get().Copy();
            wanted.DrainMinutes = _drain.Value; wanted.ThermalEnabled = _thermal.Value; wanted.ThermalRange = _range.Value; wanted.OutlineColor = _color.Value;
            wanted.BossEnabled = _bossOn.Value; wanted.BossChance = _bossChance.Value; wanted.BossTestMode = _bossTest.Value; wanted.BossTestUnarmed = _bossUnarmed.Value; wanted.BossHealth = _bossHealth.Value;
            wanted.BossDamageTaken = _bossDamage.Value; wanted.BossBackDamage = _bossBack.Value; wanted.BossGrenadeDamage = _bossGrenadeDmg.Value;
            wanted.BossGrenadeRadius = _bossGrenadeRadius.Value; wanted.BossFireInterval = _bossInterval.Value;
            var answer = ServerSettings.Update(wanted);
            if (answer == null) { Show(ServerSettings.Get()); return; }
            if (!answer.Accepted) Plugin.Log.LogWarning("[Juggernaut] settings change refused: this profile is not the settings owner");
            Show(answer);
        }
    }

    // Read by BepInEx Configuration Manager through reflection.
    internal sealed class ConfigurationManagerAttributes
    {
        public int? Order;
    }
}
