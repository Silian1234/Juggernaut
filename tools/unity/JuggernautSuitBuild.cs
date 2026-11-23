using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

// Editor-only builder for the standalone Juggernaut ArmorVest.
public static class JuggernautSuitBuild
{
    const string RipPrefab = "Assets/Rip/Prefab/item_equipment_armor_redut_T5.prefab";
    const string ShaderPath = "Assets/Shaders/Reflect-BumpSpecSMap.shader";
    const string Dir = "Assets/Juggernaut/Suit";
    const string ItemName = "item_equipment_juggernaut_suit";
    const string PrefabDir = "Assets/Content/Items/Equipment/Juggernaut";
    const string CubePath = "Assets/FBA/Gen/placeholder_cube.cubemap";
    const string PhysPath = "Assets/FBA/Gen/placeholder_phys.physicMaterial";

    [Serializable] class BoneInfo { public string name; public string path; public float[] bindpose; }
    [Serializable] class Lod { public float[] v; public float[] n; public float[] uv; public int[] t; public int[] bi; public float[] bw; }
    [Serializable] class Data { public BoneInfo[] bones; public Lod[] lods; }

    static void Tex(string path, bool normal, bool srgb)
    {
        var ti = (TextureImporter)AssetImporter.GetAtPath(path) ?? throw new Exception("missing " + path);
        ti.textureType = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
        ti.sRGBTexture = srgb; ti.mipmapEnabled = true; ti.maxTextureSize = 4096;
        ti.SaveAndReimport();
    }

    static Mesh MakeMesh(Lod l, Matrix4x4[] bind, bool skinned, string name)
    {
        int n = l.v.Length / 3;
        var verts = new Vector3[n]; var norms = new Vector3[n]; var uvs = new Vector2[n]; var bws = new BoneWeight[n];
        for (int i = 0; i < n; i++)
        {
            verts[i] = new Vector3(l.v[i * 3], l.v[i * 3 + 1], l.v[i * 3 + 2]);
            norms[i] = new Vector3(l.n[i * 3], l.n[i * 3 + 1], l.n[i * 3 + 2]);
            uvs[i] = new Vector2(l.uv[i * 2], l.uv[i * 2 + 1]);
            bws[i] = new BoneWeight
            {
                boneIndex0 = l.bi[i * 4], weight0 = l.bw[i * 4], boneIndex1 = l.bi[i * 4 + 1], weight1 = l.bw[i * 4 + 1],
                boneIndex2 = l.bi[i * 4 + 2], weight2 = l.bw[i * 4 + 2], boneIndex3 = l.bi[i * 4 + 3], weight3 = l.bw[i * 4 + 3]
            };
        }
        var m = new Mesh { name = name, indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
        m.vertices = verts; m.normals = norms; m.uv = uvs;
        m.SetTriangles(l.t, 0);
        if (skinned) { m.boneWeights = bws; m.bindposes = bind; }
        m.RecalculateTangents(); m.RecalculateBounds();
        return m;
    }

    public static void Build()
    {
        if (Application.unityVersion != "2022.3.43f1")
            throw new InvalidOperationException("Use Unity 2022.3.43f1");
        string dir = Dir;
        string outPrefab = $"{PrefabDir}/{ItemName}.prefab";
        string bundle = $"assets/content/items/equipment/juggernaut/{ItemName}.bundle";
        string outDir = Path.GetFullPath(Path.Combine(Application.dataPath, "../../build/suit"));
        Directory.CreateDirectory(PrefabDir);
        Directory.CreateDirectory($"{dir}/Gen");
        AssetDatabase.Refresh();
        var shader = AssetDatabase.LoadAssetAtPath<Shader>(ShaderPath) ?? throw new Exception("placeholder shader missing");
        var cube = AssetDatabase.LoadAssetAtPath<Cubemap>(CubePath);
        if (cube == null) { cube = new Cubemap(4, TextureFormat.RGBA32, false); AssetDatabase.CreateAsset(cube, CubePath); }
        var phys = AssetDatabase.LoadAssetAtPath<PhysicMaterial>(PhysPath);
        if (phys == null) { phys = new PhysicMaterial("placeholder_phys"); AssetDatabase.CreateAsset(phys, PhysPath); }

        Tex($"{dir}/exo_dif.png", false, true); Tex($"{dir}/exo_gloss.png", false, false); Tex($"{dir}/exo_nrm.png", true, false);

        // Retain the Redut shader property sheet and replace its maps with the authored atlas.
        var redutMat = AssetDatabase.LoadAssetAtPath<Material>("Assets/Rip/Mat/item_equipment_armor_redut_T5.mat");
        if (!redutMat) throw new InvalidDataException("Missing Redut carrier material");
        var matPath = $"{dir}/Gen/juggernaut_suit.mat";
        AssetDatabase.DeleteAsset(matPath);
        var mat = new Material(redutMat) { name = "juggernaut_suit", shader = shader };
        mat.SetTexture("_MainTex", AssetDatabase.LoadAssetAtPath<Texture2D>($"{dir}/exo_dif.png"));
        mat.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>($"{dir}/exo_nrm.png"));
        mat.SetTexture("_SpecMap", AssetDatabase.LoadAssetAtPath<Texture2D>($"{dir}/exo_gloss.png"));
        mat.SetTexture("_Cube", cube);
        AssetDatabase.CreateAsset(mat, matPath);

        var data = JsonUtility.FromJson<Data>(File.ReadAllText($"{dir}/exo_unity.json"));
        var paths = data.bones.Select(b => b.path).ToArray();
        var bind = data.bones.Select(b =>
        {
            var m = new Matrix4x4();
            for (int r = 0; r < 4; r++) for (int c = 0; c < 4; c++) m[r, c] = b.bindpose[c * 4 + r];
            return m;
        }).ToArray();

        var go = (GameObject)UnityEngine.Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>(RipPrefab));
        go.name = ItemName;
        var cellSlot = new GameObject("mod_power_cell").transform;
        cellSlot.SetParent(go.transform, false);
        cellSlot.localPosition = new Vector3(0f, .2695f, 1.28075f);
        // EFT SlotView.InsertItem supplies a further +90 degree X turn on the cell.
        cellSlot.localRotation = new Quaternion(0f, 0f, 1f, 0f);

        // skinned LODs
        var skins = go.GetComponentsInChildren<Diz.Skinning.Skin>(true).OrderBy(s => s.gameObject.name).ToArray();
        if (skins.Length != 2) throw new Exception("expected 2 skin LODs, found " + skins.Length);
        for (int lod = 0; lod < 2; lod++)
        {
            var mesh = MakeMesh(data.lods[lod], bind, true, $"juggernaut_suit_lod{lod}");
            var mp = $"{dir}/Gen/{mesh.name}.asset"; AssetDatabase.DeleteAsset(mp); AssetDatabase.CreateAsset(mesh, mp);
            var smr = skins[lod]._skinnedMeshRenderer;
            smr.sharedMesh = mesh;
            smr.sharedMaterials = new[] { mat };
            smr.localBounds = new Bounds(Vector3.zero, new Vector3(2.4f, 2.4f, 2.4f));
            smr.updateWhenOffscreen = false;
            skins[lod]._bonePaths = paths;
            skins[lod]._rootBonePath = "Root_Joint/Base HumanPelvis";
            Debug.Log($"Juggernaut lod{lod}: verts {mesh.vertexCount} tris {mesh.triangles.Length / 3} bones {paths.Length}");
        }

        // loot (dropped item): static exo meshes, colliders fitted to them
        var loots = go.GetComponentsInChildren<MeshFilter>(true).OrderBy(f => f.gameObject.name).ToArray();
        for (int i = 0; i < loots.Length; i++)
        {
            var mesh = MakeMesh(data.lods[Math.Min(i, 1)], bind, false, $"juggernaut_suit_loot{i}");
            var mp = $"{dir}/Gen/{mesh.name}.asset"; AssetDatabase.DeleteAsset(mp); AssetDatabase.CreateAsset(mesh, mp);
            loots[i].sharedMesh = mesh;
            var r = loots[i].GetComponent<MeshRenderer>(); if (r != null) r.sharedMaterials = new[] { mat };
            var bc = loots[i].GetComponent<BoxCollider>();
            if (bc != null) { bc.center = mesh.bounds.center; bc.size = mesh.bounds.size; }
        }
        var bounds = loots[0].sharedMesh.bounds;
        foreach (var col in go.GetComponentsInChildren<BoxCollider>(true))
        {
            col.sharedMaterial = phys;
            col.center = bounds.center;
            col.size = bounds.size;
        }
        var pivot = go.GetComponent<PreviewPivot>();
        pivot.pivotPosition = bounds.center;
        foreach (var group in go.GetComponentsInChildren<LODGroup>(true))
        {
            group.localReferencePoint = bounds.center;
            group.size = Mathf.Max(bounds.size.x, bounds.size.y, bounds.size.z);
        }

        AssetDatabase.DeleteAsset(outPrefab);
        PrefabUtility.SaveAsPrefabAsset(go, outPrefab);
        UnityEngine.Object.DestroyImmediate(go);

        AssetDatabase.SaveAssets();
        Directory.CreateDirectory(outDir);
        var builds = new[]
        {
            Entry(bundle, outPrefab),
            Entry("shaders", ShaderPath),
            Entry("cubemaps", CubePath),
            Entry("assets/commonassets/physics/physicsmaterials.bundle", PhysPath)
        };
        var manifest = BuildPipeline.BuildAssetBundles(outDir, builds,
            BuildAssetBundleOptions.UncompressedAssetBundle | BuildAssetBundleOptions.StrictMode,
            BuildTarget.StandaloneWindows64);
        if (!manifest) throw new InvalidOperationException("Suit bundle build failed");
        Debug.Log("Juggernaut output: " + Path.Combine(outDir, bundle));
    }

    static AssetBundleBuild Entry(string name, string path)
    {
        return new AssetBundleBuild { assetBundleName = name, assetNames = new[] { path } };
    }
}

