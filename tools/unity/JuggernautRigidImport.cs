using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

// Rehydrates the same verified accessory bundle prefab and meshes as editable project assets.
public static class JuggernautRigidImport
{
    const string Folder = "assets/content/items/equipment/juggernaut";
    const string ArtAssets = "Assets/Juggernaut/Accessories";
    const string PrefabDir = "Assets/Content/Items/Equipment/Juggernaut";
    static readonly string[] Items =
    {
        "item_equipment_juggernaut_helmet",
        "item_juggernaut_thermal_module",
        "item_juggernaut_power_cell"
    };
    static readonly string[] Dependencies =
    {
        "shaders", "cubemaps", "assets/commonassets/physics/physicsmaterials.bundle"
    };

    [MenuItem("Juggernaut/Import editable accessories")]
    public static void Import()
    {
        if (Application.unityVersion != "2022.3.43f1")
            throw new InvalidOperationException("Use Unity 2022.3.43f1.");

        string workspace = Path.GetFullPath(Path.Combine(Application.dataPath, "../../.."));
        string bundles = Arg("-juggernautBundles", Path.Combine(workspace, "server/bundles", Folder));
        string game = Arg("-juggernautGame", @"C:\SPT41\EscapeFromTarkov_Data\StreamingAssets\Windows");
        var ownedDependencies = new List<AssetBundle>();
        try
        {
            foreach (string key in Dependencies)
                Load(Path.Combine(game, key), key, ownedDependencies);
            Directory.CreateDirectory(PrefabDir);
            AssetDatabase.Refresh();
            foreach (string item in Items)
                ImportItem(bundles, item);
            AssetDatabase.SaveAssets();
        }
        finally
        {
            for (int i = ownedDependencies.Count - 1; i >= 0; i--)
                ownedDependencies[i].Unload(true);
        }
    }

    static void ImportItem(string bundles, string item)
    {
        var owned = new List<AssetBundle>(1);
        var bundle = Load(Path.Combine(bundles, item + ".bundle"), $"{Folder}/{item}.bundle", owned);
        GameObject root = null;
        try
        {
            string assetName = $"{Folder}/{item}.prefab";
            var template = bundle.LoadAsset<GameObject>(assetName);
            if (!template)
                throw new InvalidDataException($"Missing root GameObject at {assetName}.");

            root = Object.Instantiate(template);
            root.name = item;
            string target = $"{ArtAssets}/{item}";
            Directory.CreateDirectory(target);
            AssetDatabase.Refresh();

            var cache = new Dictionary<Object, Object>();
            var defaultShader = Shader.Find("Standard (Specular setup)");
            if (!defaultShader)
                throw new InvalidOperationException("The built-in Standard preview shader is unavailable.");

            foreach (var filter in root.GetComponentsInChildren<MeshFilter>(true))
                filter.sharedMesh = SaveReference(filter.sharedMesh, target, cache, Object.Instantiate);
            foreach (var renderer in root.GetComponentsInChildren<MeshRenderer>(true))
                renderer.sharedMaterials = renderer.sharedMaterials.Select(material =>
                    SaveReference(material, target, cache, source => PreviewMaterial(source,
                        defaultShader, target, cache))).ToArray();
            foreach (var collider in root.GetComponentsInChildren<MeshCollider>(true))
                collider.sharedMesh = SaveReference(collider.sharedMesh, target, cache, Object.Instantiate);
            foreach (var collider in root.GetComponentsInChildren<Collider>(true))
                collider.sharedMaterial = SaveReference(collider.sharedMaterial, target, cache, Object.Instantiate);

            int missingScripts = 0;
            foreach (var node in root.GetComponentsInChildren<Transform>(true))
                missingScripts += GameObjectUtility.RemoveMonoBehavioursWithMissingScript(node.gameObject);
            if (missingScripts != 0)
                Debug.LogWarning($"{item}: Unity could not bind {missingScripts} donor script reference(s).");

            var renderers = root.GetComponentsInChildren<MeshRenderer>(true);
            if (renderers.Length == 0 || renderers.Any(r => r.sharedMaterials.Any(m => !m)))
                throw new InvalidDataException($"{item} has incomplete renderers.");
            if (item == Items[0] &&
                (!root.transform.Find("mod_nvg") || !root.transform.Find("mod_equipment_001")))
                throw new InvalidDataException("The Juggernaut helmet mount hierarchy is incomplete.");

            if (!root.GetComponent<PreviewPivot>())
            {
                var pivot = root.AddComponent<PreviewPivot>();
                pivot.pivotPosition = root.GetComponent<LODGroup>().localReferencePoint;
                pivot.pivotRotation = Quaternion.identity;
                pivot.scale = Vector3.one;
                pivot.Icon = new PreviewPivot.IconSettings { rotation = Quaternion.identity, boundsScale = 1 };
            }
            if (item != Items[2] && !root.GetComponent<EFT.Visual.Dress>())
            {
                var dress = root.AddComponent<EFT.Visual.Dress>();
                dress.DecalTextureType = 1;
                dress.Renderers = renderers;
            }

            string prefabPath = $"{PrefabDir}/{item}.prefab";
            var prefab = PrefabUtility.SaveAsPrefabAsset(root, prefabPath, out bool success);
            if (!prefab || !success)
                throw new IOException($"Could not save {prefabPath}.");
            Debug.Log($"Imported {prefabPath}");
        }
        finally
        {
            if (root)
                Object.DestroyImmediate(root);
            foreach (var entry in owned)
                entry.Unload(true);
        }
    }

    static Material PreviewMaterial(Material original, Shader shader, string folder,
                                    Dictionary<Object, Object> cache)
    {
        // The standalone editor uses a built-in shader so no prefab retains temporary EFT bundle assets.
        var material = new Material(shader);
        string[] sources = { "_MainTex", "_BumpMap", "_SpecMap" };
        string[] destinations = { "_MainTex", "_BumpMap", "_SpecGlossMap" };
        for (int i = 0; i < sources.Length; i++)
        {
            var texture = original.GetTexture(sources[i]) as Texture2D;
            if (!texture)
                throw new InvalidDataException(original.name + " lacks " + sources[i]);
            material.SetTexture(destinations[i], SaveReference(texture, folder, cache, Object.Instantiate));
        }
        material.SetFloat("_GlossMapScale", 1f);
        material.SetFloat("_SmoothnessTextureChannel", 1f);
        material.EnableKeyword("_NORMALMAP");
        material.EnableKeyword("_SPECGLOSSMAP");
        material.EnableKeyword("_SMOOTHNESS_TEXTURE_ALBEDO_CHANNEL_A");
        return material;
    }

    static T SaveReference<T>(T original, string folder, Dictionary<Object, Object> cache,
                              Func<T, T> copy) where T : Object
    {
        if (!original)
            return null;
        if (cache.TryGetValue(original, out Object existing))
            return (T)existing;

        var asset = copy(original);
        asset.name = original.name;
        string ext = asset is Material ? "mat" : asset is PhysicMaterial ? "physicMaterial" : "asset";
        string path = $"{folder}/{original.name}.{ext}";
        var persisted = AssetDatabase.LoadAssetAtPath<T>(path);
        if (persisted)
        {
            EditorUtility.CopySerialized(asset, persisted);
            Object.DestroyImmediate(asset);
            EditorUtility.SetDirty(persisted);
        }
        else
        {
            AssetDatabase.CreateAsset(asset, path);
            persisted = asset;
        }
        cache.Add(original, persisted);
        return persisted;
    }

    static AssetBundle Load(string path, string key, List<AssetBundle> owned)
    {
        var existing = AssetBundle.GetAllLoadedAssetBundles().FirstOrDefault(bundle =>
        {
            if (!bundle || string.IsNullOrEmpty(bundle.name))
                return false;
            string name = bundle.name.Replace('\\', '/');
            return string.Equals(name, key, StringComparison.OrdinalIgnoreCase)
                || string.Equals(name, Path.GetFileName(key), StringComparison.OrdinalIgnoreCase);
        });
        if (existing)
            return existing;

        var bundle = AssetBundle.LoadFromFile(path);
        if (!bundle)
            throw new IOException($"Could not load asset bundle {path}.");
        owned.Add(bundle);
        return bundle;
    }

    static string Arg(string name, string fallback)
    {
        string[] args = Environment.GetCommandLineArgs();
        int index = Array.IndexOf(args, name);
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : fallback;
    }
}
