// Server-side settings (config.json of the server mod): read from /juggernaut/settings, changed via
// /juggernaut/settings/update. The server is the source of truth; only the settings owner may change them.
using System;
using Newtonsoft.Json;
using SPT.Common.Http;

namespace JuggernautClient
{
    internal sealed class JugSettings
    {
        public float DrainMinutes = 5f;
        public bool ThermalEnabled = true;
        public float ThermalRange = 250f;
        public string OutlineColor = "#FF1A1A";
        public bool CanEdit;
        public bool Accepted;

        internal JugSettings Copy() => (JugSettings)MemberwiseClone();
    }

    internal static class ServerSettings
    {
        private static readonly JugSettings Defaults = new JugSettings();
        private static JugSettings _loaded;
        private static DateTime _nextTry;
        private static bool _warned;

        internal static event Action<JugSettings> Loaded;

        internal static JugSettings Get()
        {
            if (_loaded != null) return _loaded;
            if (DateTime.UtcNow < _nextTry) return Defaults;
            try
            {
                var json = RequestHandler.GetJson("/juggernaut/settings");
                if (string.IsNullOrEmpty(json)) throw new InvalidOperationException("empty answer (server mod missing?)");
                Set(JsonConvert.DeserializeObject<JugSettings>(json) ?? throw new InvalidOperationException("bad answer"));
                Plugin.Log.LogInfo("[Juggernaut] server settings: " + JsonConvert.SerializeObject(_loaded));
                return _loaded;
            }
            catch (Exception ex)
            {
                _nextTry = DateTime.UtcNow.AddSeconds(30);
                if (!_warned) Plugin.Log.LogWarning("[Juggernaut] server settings unavailable, using defaults: " + ex.Message);
                _warned = true;
                return Defaults;
            }
        }

        internal static JugSettings Update(JugSettings wanted)
        {
            try
            {
                var json = RequestHandler.PostJson("/juggernaut/settings/update", JsonConvert.SerializeObject(wanted));
                var answer = JsonConvert.DeserializeObject<JugSettings>(json) ?? throw new InvalidOperationException("bad answer");
                Set(answer);
                return answer;
            }
            catch (Exception ex)
            {
                Plugin.Log.LogWarning("[Juggernaut] settings update failed: " + ex.Message);
                return null;
            }
        }

        private static void Set(JugSettings s)
        {
            _loaded = s;
            Loaded?.Invoke(s);
        }
    }
}
