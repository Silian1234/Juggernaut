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
        // raid boss (server contract: BossEnabled .. BossFireInterval)
        public bool BossEnabled = true;
        public float BossChance = 25f;
        public bool BossTestMode;
        public bool BossTestUnarmed;
        public float BossHealth = 1.5f;
        public float BossDamageTaken = 0.35f;
        public float BossBackDamage = 1.0f;
        public float BossGrenadeDamage = 0.4f;
        public float BossGrenadeRadius = 0.5f;
        public float BossFireInterval = 0.6f;
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

        // re-read at every raid start: the raid host (Fika headless) runs for hours and must see settings changed since
        private static object _world;
        internal static void RefreshOnNewRaid(object world)
        {
            if (world == null || ReferenceEquals(world, _world)) return;
            _world = world;
            _loaded = null; _nextTry = DateTime.MinValue;
            Get();
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
