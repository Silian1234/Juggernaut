// Raid boss "Juggernaut" (WildSpawnType.bossTest): shared helpers.
// All boss logic runs where the bot is simulated: on the raid host (Fika: the headless client), in the process that owns
// the bot's BotOwner. Other clients see ObservedPlayer copies without a BotOwner, so IsBossAI is false there and every
// boss hook does nothing. Nothing here touches the camera or the local main player, so a headless host is fine.
using EFT;
using HarmonyLib;

namespace JuggernautClient
{
    internal static class BossCommon
    {
        /// <summary>True for the Juggernaut boss bot simulated by this process (AI-controlled, has a BotOwner here).</summary>
        internal static bool IsBossAI(Player p)
        {
            if (p == null || !p.IsAI) return false;
            var role = p.Profile?.Info?.Settings?.Role;
            if (role != WildSpawnType.bossTest) return false;
            return p.AIData?.BotOwner != null;
        }

        // template id of the boss grenade launcher (server: MD5("juggernaut.boss.gl"), JuggernautBoss.GrenadeLauncher)
        internal const string GrenadeLauncherTpl = "ffd5144668e8b31ab47f1979";

        /// <summary>True while the boss holds his grenade launcher (the armor overheats: no damage reduction).</summary>
        internal static bool HoldsLauncher(Player p)
        {
            try { return p?.HandsController?.Item?.StringTemplateId == GrenadeLauncherTpl; }
            catch { return false; }
        }

        /// <summary>True on a Fika headless host (reflection: Fika is optional).</summary>
        internal static bool IsHeadless()
        {
            try
            {
                var type = AccessTools.TypeByName("Fika.Core.Main.Utils.FikaBackendUtils");
                var prop = type == null ? null : AccessTools.Property(type, "IsHeadless");
                return prop != null && (bool)prop.GetValue(null);
            }
            catch { return false; }
        }
    }
}
