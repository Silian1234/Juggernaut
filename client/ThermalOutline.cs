using System.Collections.Generic;
using BepInEx.Logging;
using Comfort.Common;
using EFT;
using EFT.CameraControl;
using UnityEngine;
using UnityEngine.Rendering;

namespace JuggernautClient
{

// Thermal targeting outline: enemies get a thin red contour.
// It is drawn the way visible-only chams are drawn: an inverted hull of each target mesh, rendered inside the
// camera's own frame (before image effects, so DLSS/TAA reconstruct it with the frame) with a normal depth test.
// Walls occlude it by themselves; the scope (optic) camera gets its own command buffer.
internal sealed class ThermalOutline : MonoBehaviour
{
    private const CameraEvent DrawEvent = CameraEvent.AfterForwardAlpha;
    private const string HullAsset = "assets/juggernaut/juggernautthermalhull.shader";
    private static readonly int ColorId = Shader.PropertyToID("_OutlineColor");
    private static readonly int WidthId = Shader.PropertyToID("_Width");

    private readonly Plane[] _frustum = new Plane[6];
    private readonly List<Renderer> _renderers = new(64);
    private readonly Dictionary<Player, Target> _targets = new(64);
    private readonly List<Player> _expiredTargets = new(64);
    private readonly Dictionary<Camera, CommandBuffer> _buffers = new(4);
    private readonly List<Camera> _wanted = new(4);
    private readonly List<Camera> _stale = new(4);
    private readonly List<DrawPart> _visible = new(256);
    private AssetBundle _bundle;
    private Material _hull;
    private GameWorld _world;
    private bool? _lastOn;
    private bool _active;
    private float _nextCleanup;
    private int _debugLog;

    private sealed class Target
    {
        public readonly List<DrawPart> Parts = new(32);
        public float RefreshAt;
        public float SeenAt;
    }

    private readonly struct DrawPart
    {
        public readonly Renderer Renderer;
        public readonly int SubmeshCount;

        public DrawPart(Renderer renderer, int submeshCount)
        {
            Renderer = renderer;
            SubmeshCount = submeshCount;
        }
    }

    internal static void Install(GameObject host, string bundlePath, ManualLogSource log)
    {
        if (!System.IO.File.Exists(bundlePath))
        {
            log.LogWarning($"Juggernaut thermal shader bundle is missing: {bundlePath}");
            return;
        }

        var bundle = AssetBundle.LoadFromFile(bundlePath);
        var hull = bundle != null ? bundle.LoadAsset<Shader>(HullAsset) : null;
        if (hull == null || !hull.isSupported)
        {
            log.LogWarning($"Unable to load a supported Juggernaut thermal shader from {bundlePath}");
            if (bundle != null)
                bundle.Unload(true);
            return;
        }

        var component = host.AddComponent<ThermalOutline>();
        component._bundle = bundle;
        component._hull = new Material(hull) { renderQueue = 4000 };
        component._hull.SetFloat(WidthId, 1f);
    }

    private void OnEnable() => Camera.onPreCull += PrepareCamera;

    private void OnDisable()
    {
        Camera.onPreCull -= PrepareCamera;
        _wanted.Clear();
        SyncCameras();
        _lastOn = null;
        _active = false;
    }

    private void OnDestroy()
    {
        foreach (var entry in _buffers) entry.Value.Dispose();
        _buffers.Clear();
        Destroy(_hull);
        if (_bundle != null)
            _bundle.Unload(false);
    }

    private void Update()
    {
        var world = Singleton<GameWorld>.Instance;
        if (_world != world)
        {
            _world = world;
            _lastOn = null;
            _targets.Clear();
            _nextCleanup = 0f;
        }

        // N (the game's goggles key) toggles the module like any head thermal; its state is saved with the item,
        // so it stays on between raids
        var local = world != null ? world.MainPlayer : null;
        var thermal = local != null ? JugSet.ModuleThermal(local) : null;
        bool on = thermal != null && thermal.Togglable.On;
        if (_lastOn.HasValue && _lastOn.Value != on && thermal != null)
        {
            JugSet.Notify(on ? "jug.msg.thermal_on" : "jug.msg.thermal_off", false);
            _debugLog = 3;
        }
        _lastOn = thermal != null ? on : (bool?)null;

        _active = on && local.HealthController?.IsAlive == true && ServerSettings.Get().ThermalEnabled &&
                  JugSet.Mode(local) == SetMode.Powered;
        _wanted.Clear();
        if (_active)
        {
            var manager = CameraManager.Instance;
            var main = manager != null ? manager.Camera : null;
            if (main != null) _wanted.Add(main);
            var optic = OpticCamera(manager);
            if (optic != null && optic != main && optic.isActiveAndEnabled) _wanted.Add(optic);
        }
        SyncCameras();
    }

    private static Camera OpticCamera(CameraManager manager)
    {
        try { return manager?.OpticCameraManager?.Camera; }
        catch { return null; }
    }

    private void SyncCameras()
    {
        _stale.Clear();
        foreach (var entry in _buffers)
            if (entry.Key == null || !_wanted.Contains(entry.Key))
                _stale.Add(entry.Key);
        foreach (var camera in _stale)
        {
            var buffer = _buffers[camera];
            if (camera != null) camera.RemoveCommandBuffer(DrawEvent, buffer);
            buffer.Dispose();
            _buffers.Remove(camera);
        }
        foreach (var camera in _wanted)
        {
            if (_buffers.ContainsKey(camera)) continue;
            var buffer = new CommandBuffer { name = "Juggernaut thermal outline" };
            camera.AddCommandBuffer(DrawEvent, buffer);
            _buffers.Add(camera, buffer);
        }
    }

    private void PrepareCamera(Camera camera)
    {
        if (camera == null || !_buffers.TryGetValue(camera, out var commands))
            return;

        commands.Clear();
        var local = _world != null ? _world.MainPlayer : null;
        var players = _world != null ? _world.AllAlivePlayersList : null;
        if (!_active || local == null || players == null)
            return;

        float range = Mathf.Clamp(ServerSettings.Get().ThermalRange, 0f, 1000f);
        if (range <= 0f)
            return;

        _hull.SetColor(ColorId, SettingsMenu.OutlineColor);
        var cameraPosition = camera.transform.position;
        float rangeSquared = range * range;
        float now = Time.unscaledTime;
        GeometryUtility.CalculateFrustumPlanes(camera, _frustum);

        _visible.Clear();
        for (int index = 0; index < players.Count; ++index)
        {
            var player = players[index];
            if (player == null || player == local || !IsTarget(local, player) ||
                (player.Transform.position - cameraPosition).sqrMagnitude > rangeSquared)
                continue;

            if (!_targets.TryGetValue(player, out var target))
            {
                target = new Target();
                _targets.Add(player, target);
            }
            target.SeenAt = now;
            if (now >= target.RefreshAt)
                RefreshParts(player, target, now);

            foreach (var part in target.Parts)
            {
                var renderer = part.Renderer;
                // only what the game actually renders: the current LOD (isVisible), no shadow-only proxies
                if (renderer == null || !renderer.enabled || !renderer.gameObject.activeInHierarchy ||
                    renderer.shadowCastingMode == ShadowCastingMode.ShadowsOnly ||
                    (camera.cullingMask & (1 << renderer.gameObject.layer)) == 0 ||
                    !GeometryUtility.TestPlanesAABB(_frustum, renderer.bounds))
                    continue;

                _visible.Add(part);
            }
        }

        // pass 0 marks every visible target pixel in the stencil, pass 1 draws the hull only outside them
        if (_visible.Count > 0)
        {
            commands.DrawProcedural(Matrix4x4.identity, _hull, 0, MeshTopology.Triangles, 3);   // clear our stencil bit
            foreach (var part in _visible)
                for (int submesh = 0; submesh < part.SubmeshCount; ++submesh)
                    commands.DrawRenderer(part.Renderer, _hull, submesh, 1);                   // mark the targets
            foreach (var part in _visible)
                for (int submesh = 0; submesh < part.SubmeshCount; ++submesh)
                    commands.DrawRenderer(part.Renderer, _hull, submesh, 2);                   // hull outside them
        }

        if (_debugLog > 0)
        {
            _debugLog--;
            int draws = 0; foreach (var t in _targets.Values) draws += t.Parts.Count;
            Plugin.Log.LogInfo($"[Juggernaut] thermal: camera {camera.name} ({camera.actualRenderingPath}, {camera.pixelWidth}x{camera.pixelHeight}), targets {_targets.Count}, parts {draws}, drawn {_visible.Count}, cameras {_buffers.Count}");
        }
        if (now >= _nextCleanup)
            RemoveExpiredTargets(now);
    }

    private void RefreshParts(Player player, Target target, float now)
    {
        target.RefreshAt = now + 1f;
        target.Parts.Clear();
        _renderers.Clear();
        player.GetComponentsInChildren(false, _renderers);
        foreach (var renderer in _renderers)
        {
            Mesh mesh = null;
            if (renderer is SkinnedMeshRenderer skinned)
                mesh = skinned.sharedMesh;
            else if (renderer is MeshRenderer && renderer.TryGetComponent<MeshFilter>(out var filter))
                mesh = filter.sharedMesh;

            if (mesh != null)
                target.Parts.Add(new DrawPart(renderer, mesh.subMeshCount));
        }
        _renderers.Clear();
    }

    private void RemoveExpiredTargets(float now)
    {
        _nextCleanup = now + 2f;
        _expiredTargets.Clear();
        foreach (var entry in _targets)
        {
            if (entry.Key == null || now - entry.Value.SeenAt > 3f)
                _expiredTargets.Add(entry.Key);
        }

        foreach (var target in _expiredTargets)
            _targets.Remove(target);
        _expiredTargets.Clear();
    }

    private static bool IsTarget(Player local, Player candidate)
    {
        if (!candidate.IsAI)
            return string.IsNullOrEmpty(local.GroupId) || local.GroupId != candidate.GroupId;

        var group = candidate.AIData?.BotOwner?.BotsGroup;
        if (group != null)
            return group.IsEnemy(local);

        // Remote co-op AI can lack the host's AI controller. Only infer the
        // common scav-versus-PMC hostility in that case.
        return candidate.Side == EPlayerSide.Savage && local.Side != EPlayerSide.Savage;
    }
}
}
