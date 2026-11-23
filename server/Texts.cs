// Item texts for every game language, read from locales.json next to the DLL.
// A language without a key falls back to "en"; "en" goes first because SPT uses the first entry
// for game languages that are absent from the dictionary.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SPTarkov.Server.Core.Models.Spt.Mod;

namespace Juggernaut;

internal static class Texts
{
    /// <summary>Client messages added to the game's global locales (the client shows them with .Localized()).</summary>
    public static readonly string[] MessageKeys =
    {
        "jug.msg.powered", "jug.msg.discharged", "jug.msg.cell", "jug.msg.lastcell", "jug.msg.nocells", "jug.msg.nohelmet",
        "jug.msg.thermal_on", "jug.msg.thermal_off",
    };

    private static Dictionary<string, Dictionary<string, string>> _langs;

    private static Dictionary<string, Dictionary<string, string>> Langs => _langs ??= Load();

    private static Dictionary<string, Dictionary<string, string>> Load()
    {
        var path = Path.Combine(Path.GetDirectoryName(typeof(Texts).Assembly.Location)!, "locales.json");
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        var result = new Dictionary<string, Dictionary<string, string>>();
        foreach (var lang in doc.RootElement.EnumerateObject())
        {
            if (lang.Value.ValueKind != JsonValueKind.Object) continue;   // "_comment"
            result[lang.Name] = lang.Value.EnumerateObject().ToDictionary(k => k.Name, k => k.Value.GetString());
        }
        if (!result.ContainsKey("en")) throw new InvalidDataException("locales.json has no \"en\" section");
        return result;
    }

    public static string Get(string lang, string key)
    {
        if (Langs.TryGetValue(lang, out var t) && t.TryGetValue(key, out var s)) return s;
        if (Langs["en"].TryGetValue(key, out s)) return s;
        throw new KeyNotFoundException($"locales.json: missing en key \"{key}\"");
    }

    /// <summary>Name/short/description in every language. Values starting with '@' are keys translated per language.</summary>
    public static Dictionary<string, LocaleDetails> Item(string nameKey, string shortKey, string descKey,
        params (string Placeholder, string Value)[] values) =>
        ItemWith(nameKey, shortKey, descKey, values
            .Select(v => (v.Placeholder, (Func<string, string>)(lang => v.Value.StartsWith("@") ? Get(lang, v.Value.Substring(1)) : v.Value)))
            .ToArray());

    /// <summary>Same, with placeholder values computed per language.</summary>
    public static Dictionary<string, LocaleDetails> ItemWith(string nameKey, string shortKey, string descKey,
        params (string Placeholder, Func<string, string> Value)[] values)
    {
        string Fill(string lang, string key)
        {
            var s = Get(lang, key);
            foreach (var (ph, v) in values) s = s.Replace("{" + ph + "}", v(lang));
            return s;
        }
        var result = new Dictionary<string, LocaleDetails>();
        foreach (var lang in Langs.Keys.OrderBy(l => l == "en" ? 0 : 1))
            result[lang] = new LocaleDetails { Name = Fill(lang, nameKey), ShortName = Fill(lang, shortKey), Description = Fill(lang, descKey) };
        return result;
    }
}
