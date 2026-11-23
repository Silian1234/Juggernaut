using System.IO;
using UnityEditor;

// Builds juggernaut_thermal.bundle (the two outline shaders) for the Juggernaut client plugin.
// Unity -batchmode -quit -projectPath <this> -executeMethod BuildThermal.Build
public static class BuildThermal
{
    public static void Build()
    {
        const string outDir = "Build";
        Directory.CreateDirectory(outDir);
        var build = new AssetBundleBuild
        {
            assetBundleName = "juggernaut_thermal.bundle",
            assetNames = new[] { "Assets/Juggernaut/JuggernautThermalMask.shader", "Assets/Juggernaut/JuggernautThermalOutline.shader" }
        };
        BuildPipeline.BuildAssetBundles(outDir, new[] { build }, BuildAssetBundleOptions.None, BuildTarget.StandaloneWindows64);
    }
}
