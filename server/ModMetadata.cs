using System.Collections.Generic;
using SPTarkov.Server.Core.Models.Spt.Mod;
using Range = SemanticVersioning.Range;
using Version = SemanticVersioning.Version;

namespace Juggernaut;

public record ModMetadata : IModMetadata
{
    public string ModGuid { get; init; } = "com.silian.juggernaut";
    public string Name { get; init; } = "Juggernaut From TushonkaGroup";
    public string Author { get; init; } = "silian";
    public List<string> Contributors { get; init; }
    public Version Version { get; init; } = new("1.0.0");
    public Range SptVersion { get; init; } = new("~4.1.3");
    public List<string> Incompatibilities { get; init; }
    public Dictionary<string, Range> ModDependencies { get; init; }
    public string Url { get; init; }
    public string License { get; init; } = "MIT";
    public bool HasPrepatcher { get; init; } = false;
}
