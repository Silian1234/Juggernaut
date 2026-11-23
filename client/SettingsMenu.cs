// F12 (BepInEx Configuration Manager). Server settings mirror the server (owner rule); the hotkey is local.
using System;
using BepInEx.Configuration;
using UnityEngine;

namespace JuggernautClient
{
    internal static class SettingsMenu
    {
        private const string Power = "1. Power", Thermal = "2. Thermal module";
        private static ConfigEntry<float> _drain, _range;
        private static ConfigEntry<bool> _thermal;
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
                if (ColorUtility.TryParseHtmlString(s.OutlineColor, out var c)) OutlineColor = c;
            }
            finally { _syncing = false; }
        }

        private static void OnChanged(object sender, SettingChangedEventArgs e)
        {
            if (_syncing || e?.ChangedSetting == null) return;
            var section = e.ChangedSetting.Definition.Section;
            if (section != Power && section != Thermal) return;
            _dirty = true;
            _changedAt = Time.realtimeSinceStartup;
        }

        internal static void Tick()
        {
            if (!_dirty || Time.realtimeSinceStartup - _changedAt < 0.6f) return;
            _dirty = false;
            var wanted = ServerSettings.Get().Copy();
            wanted.DrainMinutes = _drain.Value; wanted.ThermalEnabled = _thermal.Value; wanted.ThermalRange = _range.Value; wanted.OutlineColor = _color.Value;
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
