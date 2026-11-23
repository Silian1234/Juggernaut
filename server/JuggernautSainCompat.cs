// Optional SAIN support for the Juggernaut boss (role bossTest).
// SAIN keeps per-role settings; an unknown role logs "[bossTest] does not exist in SAINSettings Dictionary!" and SAIN does
// not set the bot up. SAIN's server mod offers SAIN.ServerInterop.ISainBotTypeRegistry for modded roles. It is used here by
// reflection only, so the mod has no hard dependency: without SAIN this step is skipped and the boss runs on the game AI.
// No brains/layers are passed: SAIN already adds its layers to the "BigPipe" brain (Goons) for every role, and the boss
// runs that brain (client BossBrain.cs). The registration only gives SAIN the settings entry for bossTest.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using SPTarkov.Common.Models.Logging;
using SPTarkov.DI.Annotations;
using SPTarkov.Server.Core.DI;
using SPTarkov.Server.Core.Models.Utils;

namespace Juggernaut;

[Injectable(InjectionType.Singleton, OnLoadOrder.PostLoad + 10)]
public class JuggernautSainCompat(IServiceProvider services, ISptLogger<JuggernautSainCompat> log) : IOnLoad
{
    private const int BossTestWildSpawnType = 2;   // EFT WildSpawnType.bossTest (SAIN's ESainWildSpawnType uses the same values)

    public async Task OnLoadAsync(CancellationToken cancellationToken)
    {
        try
        {
            var assemblies = AppDomain.CurrentDomain.GetAssemblies();
            var registryType = assemblies.Select(a => a.GetType("SAIN.ServerInterop.ISainBotTypeRegistry", false)).FirstOrDefault(t => t != null);
            var registrationType = assemblies.Select(a => a.GetType("SAIN.ServerInterop.SainBotTypeRegistration", false)).FirstOrDefault(t => t != null);
            if (registryType == null || registrationType == null)
            {
                log.Info("[Juggernaut] SAIN not installed: boss uses the game AI (Big Pipe brain)");
                return;
            }

            var registry = services.GetService(registryType)
                           ?? assemblies.Select(a => a.GetType("SAINServerMod.Generators.PresetGenerationService", false))
                                        .Where(t => t != null).Select(t => services.GetService(t)).FirstOrDefault(s => s != null);
            if (registry == null || !registryType.IsInstanceOfType(registry))
            {
                log.Warning("[Juggernaut] SAIN found, but its bot type registry is not available: boss not registered in SAIN");
                return;
            }

            var registration = Activator.CreateInstance(registrationType)!;
            void Set(string name, object? value) => registrationType.GetProperty(name)!.SetValue(registration, value);
            Set("Name", "Juggernaut");
            Set("WildSpawnType", BossTestWildSpawnType);
            Set("BotDbKey", JuggernautBoss.BotKey);
            Set("DifficultyModifier", 0.75f);                       // SAIN's value for the vanilla bosses
            Set("Section", "Bosses");
            Set("Description", "Juggernaut From TushonkaGroup: heavy exoskeleton boss on Labs (Big Pipe brain, grenade launcher)");

            var register = registryType.GetMethod("RegisterAsync")!;
            if (register.Invoke(registry, new object[] { registration, cancellationToken }) is Task task) await task;
            log.Success("[Juggernaut] boss registered in SAIN (bossTest, Bosses section)");
        }
        catch (Exception ex)
        {
            log.Warning($"[Juggernaut] SAIN registration failed (the boss still works on the game AI): {ex.GetBaseException().Message}");
        }
    }
}
