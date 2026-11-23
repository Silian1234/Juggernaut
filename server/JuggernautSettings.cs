// Settings shared with the client plugin (F12 menu), stored in config.json next to the DLL.
//   /juggernaut/settings        -> current values (+ whether this profile may change them)
//   /juggernaut/settings/update -> change them; accepted only from the settings owner, then saved
// Owner: SettingsOwnerProfileId; empty = the first profile that changes a setting becomes the owner.
using System;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using SPTarkov.Common.Models.Logging;
using SPTarkov.DI.Annotations;
using SPTarkov.Server.Core.DI;
using SPTarkov.Server.Core.Models.Utils;
using SPTarkov.Server.Core.Utils;

namespace Juggernaut;

public class JuggernautConfig
{
    public double DrainMinutes { get; set; } = 5;        // one power cell powers the set for this long (in raid)
    public bool ThermalEnabled { get; set; } = true;
    public double ThermalRange { get; set; } = 250;      // metres
    public string OutlineColor { get; set; } = "#FF1A1A";
    public string SettingsOwnerProfileId { get; set; } = "";

    // ---- Juggernaut raid boss (section "3. Juggernaut boss" in the client F12 menu)
    public bool BossEnabled { get; set; } = true;            // the boss can spawn at all
    public double BossChance { get; set; } = 25;             // % per Labs raid
    public bool BossTestMode { get; set; } = false;          // 100% on EVERY map, ~10 s after the raid starts
    public bool BossTestUnarmed { get; set; } = false;       // test mode only: boss spawns without his PKP and grenade launcher
    public double BossHealth { get; set; } = 1.5;            // multiplier on Killa's per-part HP (applied live)
    public double BossDamageTaken { get; set; } = 0.35;      // multiplier on all damage the boss takes (client/host)
    public double BossBackDamage { get; set; } = 1.0;        // same, for hits from behind (battery pack)
    public double BossGrenadeDamage { get; set; } = 0.4;     // grenade explosion damage multiplier (applied at server start)
    public double BossGrenadeRadius { get; set; } = 0.5;     // grenade explosion radius multiplier (applied at server start)
    public double BossFireInterval { get; set; } = 0.6;      // min seconds between grenade shots (client/host)
}

public record JuggernautClientSettings : IRequestData
{
    public double DrainMinutes { get; set; }
    public bool ThermalEnabled { get; set; }
    public double ThermalRange { get; set; }
    public string OutlineColor { get; set; }
    // boss settings are nullable so that an update from a client that does not send them leaves the stored values alone
    public bool? BossEnabled { get; set; }
    public double? BossChance { get; set; }
    public bool? BossTestMode { get; set; }
    public bool? BossTestUnarmed { get; set; }
    public double? BossHealth { get; set; }
    public double? BossDamageTaken { get; set; }
    public double? BossBackDamage { get; set; }
    public double? BossGrenadeDamage { get; set; }
    public double? BossGrenadeRadius { get; set; }
    public double? BossFireInterval { get; set; }
    public bool CanEdit { get; set; }
    public bool Accepted { get; set; }
}

public static class JuggernautSettings
{
    private static string ConfigPath =>
        Path.Combine(Path.GetDirectoryName(typeof(JuggernautSettings).Assembly.Location)!, "config.json");

    public static JuggernautConfig Config { get; private set; } = Load();

    /// <summary>Raised (outside the lock) after the settings were changed from the F12 menu.</summary>
    public static event Action Changed;

    internal static void RaiseChanged()
    {
        try { Changed?.Invoke(); } catch { /* a listener must never break the settings route */ }
    }

    /// <summary>Clamps a number to [min, max]; NaN/Infinity fall back to <paramref name="fallback"/>.</summary>
    public static double Clamp(double? value, double min, double max, double fallback) =>
        value is { } v && double.IsFinite(v) ? Math.Clamp(v, min, max) : fallback;

    private static JuggernautConfig Load()
    {
        try
        {
            return File.Exists(ConfigPath) ? JsonSerializer.Deserialize<JuggernautConfig>(File.ReadAllText(ConfigPath)) ?? new JuggernautConfig() : new JuggernautConfig();
        }
        catch { return new JuggernautConfig(); }
    }

    public static void Save()
    {
        var tmp = ConfigPath + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(Config, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(tmp, ConfigPath, true);
    }

    public static string Color(string c) =>
        c is { Length: 7 } && c[0] == '#' && Uri.IsHexDigit(c[1]) && Uri.IsHexDigit(c[2]) && Uri.IsHexDigit(c[3]) &&
        Uri.IsHexDigit(c[4]) && Uri.IsHexDigit(c[5]) && Uri.IsHexDigit(c[6]) ? c.ToUpperInvariant() : "#FF1A1A";

    public static JuggernautClientSettings Current(string profileId, bool accepted)
    {
        var c = Config;
        return new JuggernautClientSettings
        {
            DrainMinutes = c.DrainMinutes, ThermalEnabled = c.ThermalEnabled, ThermalRange = c.ThermalRange, OutlineColor = c.OutlineColor,
            BossEnabled = c.BossEnabled, BossChance = c.BossChance, BossTestMode = c.BossTestMode, BossTestUnarmed = c.BossTestUnarmed, BossHealth = c.BossHealth,
            BossDamageTaken = c.BossDamageTaken, BossBackDamage = c.BossBackDamage, BossGrenadeDamage = c.BossGrenadeDamage,
            BossGrenadeRadius = c.BossGrenadeRadius, BossFireInterval = c.BossFireInterval,
            CanEdit = string.IsNullOrEmpty(c.SettingsOwnerProfileId) || c.SettingsOwnerProfileId == profileId,
            Accepted = accepted,
        };
    }
}

[Injectable]
public class JuggernautSettingsRouter(JsonUtil json, ISptLogger<JuggernautSettingsRouter> log) : StaticRouter(json,
[
    new RouteAction("/juggernaut/settings", (url, info, sessionId, output, cancellationToken) =>
        new ValueTask<object>(json.Serialize(JuggernautSettings.Current(sessionId.ToString(), false)))),

    new RouteAction<JuggernautClientSettings>("/juggernaut/settings/update", (url, info, sessionId, output, cancellationToken) =>
    {
        var id = sessionId.ToString();
        var c = JuggernautSettings.Config;
        lock (c)
        {
            if (!string.IsNullOrEmpty(c.SettingsOwnerProfileId) && c.SettingsOwnerProfileId != id)
            {
                log.Warning($"[Juggernaut] settings change from profile {id} refused: owner is {c.SettingsOwnerProfileId}");
                return new ValueTask<string>(json.Serialize(JuggernautSettings.Current(id, false)));
            }
            if (string.IsNullOrEmpty(c.SettingsOwnerProfileId)) c.SettingsOwnerProfileId = id;
            c.DrainMinutes = Math.Clamp(info.DrainMinutes, 0.5, 120);
            c.ThermalEnabled = info.ThermalEnabled;
            c.ThermalRange = Math.Clamp(info.ThermalRange, 10, 1000);
            c.OutlineColor = JuggernautSettings.Color(info.OutlineColor);
            if (info.BossEnabled.HasValue) c.BossEnabled = info.BossEnabled.Value;
            if (info.BossTestMode.HasValue) c.BossTestMode = info.BossTestMode.Value;
            if (info.BossTestUnarmed.HasValue) c.BossTestUnarmed = info.BossTestUnarmed.Value;
            if (info.BossChance.HasValue) c.BossChance = JuggernautSettings.Clamp(info.BossChance, 0, 100, c.BossChance);
            if (info.BossHealth.HasValue) c.BossHealth = JuggernautSettings.Clamp(info.BossHealth, 0.1, 20, c.BossHealth);
            if (info.BossDamageTaken.HasValue) c.BossDamageTaken = JuggernautSettings.Clamp(info.BossDamageTaken, 0.01, 10, c.BossDamageTaken);
            if (info.BossBackDamage.HasValue) c.BossBackDamage = JuggernautSettings.Clamp(info.BossBackDamage, 0.01, 10, c.BossBackDamage);
            if (info.BossGrenadeDamage.HasValue) c.BossGrenadeDamage = JuggernautSettings.Clamp(info.BossGrenadeDamage, 0.01, 10, c.BossGrenadeDamage);
            if (info.BossGrenadeRadius.HasValue) c.BossGrenadeRadius = JuggernautSettings.Clamp(info.BossGrenadeRadius, 0.1, 5, c.BossGrenadeRadius);
            if (info.BossFireInterval.HasValue) c.BossFireInterval = JuggernautSettings.Clamp(info.BossFireInterval, 0.1, 30, c.BossFireInterval);
            try { JuggernautSettings.Save(); }
            catch (Exception ex) { log.Warning($"[Juggernaut] could not save config.json: {ex.Message}"); }
        }
        JuggernautSettings.RaiseChanged();
        log.Info($"[Juggernaut] settings changed from F12: cell lasts {c.DrainMinutes} min, thermal {(c.ThermalEnabled ? "on" : "off")} {c.ThermalRange} m {c.OutlineColor}; " +
                 $"boss {(c.BossEnabled ? "on" : "off")} {c.BossChance}% test {(c.BossTestMode ? "on" : "off")} hp x{c.BossHealth} dmg x{c.BossDamageTaken} back x{c.BossBackDamage} " +
                 $"grenade x{c.BossGrenadeDamage}/r x{c.BossGrenadeRadius} (restart) fire {c.BossFireInterval}s");
        return new ValueTask<string>(json.Serialize(JuggernautSettings.Current(id, true)));
    })
]);
