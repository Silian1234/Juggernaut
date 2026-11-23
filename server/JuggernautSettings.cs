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
}

public record JuggernautClientSettings : IRequestData
{
    public double DrainMinutes { get; set; }
    public bool ThermalEnabled { get; set; }
    public double ThermalRange { get; set; }
    public string OutlineColor { get; set; }
    public bool CanEdit { get; set; }
    public bool Accepted { get; set; }
}

public static class JuggernautSettings
{
    private static string ConfigPath =>
        Path.Combine(Path.GetDirectoryName(typeof(JuggernautSettings).Assembly.Location)!, "config.json");

    public static JuggernautConfig Config { get; private set; } = Load();

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
            try { JuggernautSettings.Save(); }
            catch (Exception ex) { log.Warning($"[Juggernaut] could not save config.json: {ex.Message}"); }
        }
        log.Info($"[Juggernaut] settings changed from F12: cell lasts {c.DrainMinutes} min, thermal {(c.ThermalEnabled ? "on" : "off")} {c.ThermalRange} m {c.OutlineColor}");
        return new ValueTask<string>(json.Serialize(JuggernautSettings.Current(id, true)));
    })
]);
