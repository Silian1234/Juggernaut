// Juggernaut sounds: heavy footsteps, servo whines on starts/turns/jumps, landing stomps,
// dry creaks when discharged, and power up/down cues.
// The clips are CC0 (OpenGameArt; see sfx/CREDITS.txt) and are loaded from the sfx folder next to the DLL.
// Steps follow the game's own footstep events (animation cadence), so a faster sprint does not double them.
using System.Collections;
using System.Collections.Generic;
using System.IO;
using BepInEx.Configuration;
using Comfort.Common;
using CommonAssets.Scripts.Audio;
using EFT;
using HarmonyLib;
using UnityEngine;
using UnityEngine.Networking;

namespace JuggernautClient
{
    internal static class JugSound
    {
        private static readonly Dictionary<string, AudioClip> Clips = new();
        // decoded samples are kept: the game re-initialises the audio system (AudioSettings.Reset) after start-up,
        // which empties every clip created from code, so clips are rebuilt from these when that happens
        private static readonly Dictionary<string, (float[] Samples, int Channels, int Rate)> Raw = new();
        private static bool _clipsDirty;
        private static ConfigEntry<float> _volume;
        private static ConfigEntry<bool> _enabled;
        // per-sound volume, on top of the master volume (1 = as designed)
        private static ConfigEntry<float> _vSurface, _vThump, _vCreak, _vServo, _vJump, _vLand, _vPowerUp, _vPowerDown, _vHum, _vRemote;

        private static Player _player;
        private static GameObject _host;
        private static AudioSource _oneShot, _hum, _surface;
        private static AudioLowPassFilter _surfaceFilter;
        private static AudioClip _pendingSurfaceClip;
        private static readonly AccessTools.FieldRef<Player, SurfaceSet> CurrentSet = AccessTools.FieldRefAccess<Player, SurfaceSet>("_currentSet");
        private static SetMode _lastMode;
        private static Vector3 _lastPos;
        private static float _lastYaw, _airTime, _servoCooldown, _creakCooldown;
        private static bool _wasMoving, _wasGrounded = true;
        private static int _pendingSteps;

        // Player.UpdateStepSourceRolloff runs on every footstep the game plays (walk/run, duck, sprint)
        internal static void Patch(Harmony harmony)
        {
            var step = AccessTools.DeclaredMethod(typeof(Player), nameof(Player.UpdateStepSourceRolloff))
                       ?? throw new System.MissingMethodException("Player.UpdateStepSourceRolloff");
            harmony.Patch(step, postfix: new HarmonyMethod(typeof(JugSound), nameof(OnGameStep)));
        }

        private static void OnGameStep(Player __instance, EAudioMovementState movementState)
        {
            if (Application.isBatchMode || _enabled == null) return;   // headless host: nobody listens
            if (movementState != EAudioMovementState.Run && movementState != EAudioMovementState.Sprint &&
                movementState != EAudioMovementState.Duck) return;
            if (_player == null || !ReferenceEquals(__instance, _player))
            {
                try { RemoteStep(__instance, movementState); }
                catch (System.Exception ex) { Plugin.Log.LogWarning("[Juggernaut] remote step sound failed: " + ex.Message); }
                return;
            }
            _pendingSteps = 1;
            // the game's own footstep clip for the current surface (metal, concrete, wood, grass...), replayed heavier
            try
            {
                var set = CurrentSet(__instance);
                var bank = set == null ? null : movementState == EAudioMovementState.Sprint ? set.SprintSoundBank
                         : movementState == EAudioMovementState.Duck ? set.DuckSoundBank : set.RunSoundBank;
                _pendingSurfaceClip = bank?.PickSingleClip((int)__instance.Environment);
            }
            catch { _pendingSurfaceClip = null; }
        }

        // ---- other suit wearers (bots incl. the Juggernaut boss, Fika teammates): the same heavy steps, in 3D
        private sealed class RemoteRig { public GameObject Root; public AudioSource Step, Surface; }
        private static readonly Dictionary<Player, RemoteRig> Remote = new();
        private static readonly List<Player> RemoteDead = new();

        private static SurfaceSet CurrentSetOf(Player p) { try { return CurrentSet(p); } catch { return null; } }

        private static void RemoteStep(Player p, EAudioMovementState state)
        {
            if (p == null || JugSet.IsLocal(p) || !_enabled.Value || Raw.Count == 0 || JugSet.Worn(p, EFT.InventoryLogic.EquipmentSlot.ArmorVest)?.StringTemplateId != JugSet.Suit)
                return;
            if (ClipsLost()) BuildClips();
            if (!Remote.TryGetValue(p, out var rig) || rig.Root == null)
            {
                rig = new RemoteRig { Root = new GameObject("JuggernautRemoteSteps") };
                rig.Root.transform.SetParent(p.Transform.Original, false);
                rig.Root.transform.localPosition = new Vector3(0f, 0.2f, 0f);
                rig.Step = Spatial(rig.Root);
                var surface = new GameObject("JuggernautRemoteSurface");
                surface.transform.SetParent(rig.Root.transform, false);
                rig.Surface = Spatial(surface);
                surface.AddComponent<AudioLowPassFilter>().cutoffFrequency = 2200f;
                Remote[p] = rig;
            }
            var set = CurrentSetOf(p);
            var bank = set == null ? null : state == EAudioMovementState.Sprint ? set.SprintSoundBank
                     : state == EAudioMovementState.Duck ? set.DuckSoundBank : set.RunSoundBank;
            AudioClip surfaceClip = null;
            try { surfaceClip = bank?.PickSingleClip((int)p.Environment); } catch { }
            if (surfaceClip != null)
            {
                rig.Surface.pitch = Random.Range(0.66f, 0.74f);
                rig.Surface.PlayOneShot(surfaceClip, 0.9f * _volume.Value * _vSurface.Value * _vRemote.Value);
            }
            var step = Pick("step_heavy");
            if (step != null) { rig.Step.pitch = Random.Range(0.94f, 1.06f); rig.Step.PlayOneShot(step, 0.8f * _volume.Value * _vThump.Value * _vRemote.Value); }
        }

        private static AudioSource Spatial(GameObject go)
        {
            var source = go.AddComponent<AudioSource>();
            source.playOnAwake = false; source.spatialBlend = 1f; source.priority = 40;
            source.rolloffMode = AudioRolloffMode.Logarithmic; source.minDistance = 4f; source.maxDistance = 70f;
            source.dopplerLevel = 0f;
            return source;
        }

        private static void CleanupRemote()
        {
            RemoteDead.Clear();
            foreach (var entry in Remote)
                if (entry.Key == null || entry.Value.Root == null || entry.Key.HealthController?.IsAlive != true) RemoteDead.Add(entry.Key);
            foreach (var p in RemoteDead) { if (Remote[p].Root != null) Object.Destroy(Remote[p].Root); Remote.Remove(p); }
        }

        internal static void Init(ConfigFile config)
        {
            _enabled = config.Bind("Juggernaut sounds", "Enabled", true, "Servo, footstep and power sounds of the Juggernaut suit.");
            _volume = config.Bind("Juggernaut sounds", "Volume", 1.0f, new ConfigDescription("Master volume of all suit sounds.",
                new AcceptableValueRange<float>(0f, 1.5f), new ConfigurationManagerAttributes { Order = 99 }));
            int order = 98;
            ConfigEntry<float> Slider(string name, string desc) => config.Bind("Juggernaut sounds", name, 1.0f, new ConfigDescription(
                desc + " Multiplies the master volume: 1 = as designed, 0 = off.", new AcceptableValueRange<float>(0f, 2f),
                new ConfigurationManagerAttributes { Order = order-- }));
            _vSurface = Slider("Footsteps: surface", "The game's own footstep for the floor under you, pitched down and darkened.");
            _vThump = Slider("Footsteps: heavy thump", "The low weight thump under every step.");
            _vCreak = Slider("Creaks (no power)", "Dry creaks of the frame while walking without power.");
            _vServo = Slider("Servos (start / turn)", "Servo whine when you start moving or turn sharply (powered).");
            _vJump = Slider("Jump servo", "Servo push on a jump (powered).");
            _vLand = Slider("Landing", "Heavy stomp when you land after a fall or a jump.");
            _vPowerUp = Slider("Power on", "Cue when the suit gets power.");
            _vPowerDown = Slider("Power off", "Cue when the power runs out.");
            _vHum = Slider("Motor hum", "Motor hum that follows your speed (powered).");
            _vRemote = Slider("Other wearers (3D)", "Footsteps of other players and bots wearing the suit, heard in 3D.");
        }

        internal static IEnumerator Load(string dir)
        {
            if (!Directory.Exists(dir)) { Plugin.Log.LogWarning($"[Juggernaut] sound folder missing: {dir}"); yield break; }
            foreach (var file in Directory.GetFiles(dir, "*.wav"))
            {
                try
                {
                    Raw[Path.GetFileNameWithoutExtension(file)] = ReadWav(file);
                }
                catch (System.Exception ex) { Plugin.Log.LogWarning($"[Juggernaut] sound {Path.GetFileName(file)}: {ex.Message}"); }
                yield return null;
            }
            AudioSettings.OnAudioConfigurationChanged += _ => _clipsDirty = true;
            BuildClips();
            Plugin.Log.LogInfo($"[Juggernaut] sounds loaded: {Clips.Count}");
        }

        // Unity's WAV loader returned empty clips for these files, so PCM WAV (8/16/24/32-bit int or 32-bit float) is
        // parsed here and turned into an AudioClip directly.
        private static void BuildClips()
        {
            foreach (var clip in Clips.Values) if (clip != null) Object.Destroy(clip);
            Clips.Clear();
            foreach (var entry in Raw)
            {
                var (samples, channels, rate) = entry.Value;
                var clip = AudioClip.Create(entry.Key, samples.Length / channels, channels, rate, false);
                clip.SetData(samples, 0);
                Clips[entry.Key] = clip;
            }
            _clipsDirty = false;
        }

        // true when the clips have to be rebuilt (audio system reset, or a clip lost its data)
        private static bool ClipsLost()
        {
            if (_clipsDirty) return true;
            foreach (var clip in Clips.Values) return clip == null || clip.samples == 0;
            return Raw.Count > 0;
        }

        private static (float[] Samples, int Channels, int Rate) ReadWav(string path)
        {
            var b = File.ReadAllBytes(path);
            if (b.Length < 44 || System.Text.Encoding.ASCII.GetString(b, 0, 4) != "RIFF" || System.Text.Encoding.ASCII.GetString(b, 8, 4) != "WAVE")
                throw new InvalidDataException("not a RIFF/WAVE file");
            int pos = 12, channels = 0, rate = 0, bits = 0, format = 0, dataStart = -1, dataLength = 0;
            while (pos + 8 <= b.Length)
            {
                string id = System.Text.Encoding.ASCII.GetString(b, pos, 4);
                int size = System.BitConverter.ToInt32(b, pos + 4);
                int body = pos + 8;
                if (id == "fmt ")
                {
                    format = System.BitConverter.ToUInt16(b, body);
                    channels = System.BitConverter.ToUInt16(b, body + 2);
                    rate = System.BitConverter.ToInt32(b, body + 4);
                    bits = System.BitConverter.ToUInt16(b, body + 14);
                    if (format == 0xFFFE && size >= 26) format = System.BitConverter.ToUInt16(b, body + 24);   // extensible: sub-format
                }
                else if (id == "data")
                {
                    dataStart = body;
                    dataLength = System.Math.Min(size, b.Length - body);
                    break;
                }
                pos = body + size + (size & 1);
            }
            if (dataStart < 0 || channels <= 0 || rate <= 0) throw new InvalidDataException("missing fmt or data chunk");
            int bytes = bits / 8, frames = dataLength / (bytes * channels);
            var samples = new float[frames * channels];
            for (int n = 0, o = dataStart; n < samples.Length; n++, o += bytes)
            {
                switch (bits)
                {
                    case 8: samples[n] = (b[o] - 128) / 128f; break;
                    case 16: samples[n] = System.BitConverter.ToInt16(b, o) / 32768f; break;
                    case 24: samples[n] = ((b[o] | (b[o + 1] << 8) | ((sbyte)b[o + 2] << 16))) / 8388608f; break;
                    case 32: samples[n] = format == 3 ? System.BitConverter.ToSingle(b, o) : System.BitConverter.ToInt32(b, o) / 2147483648f; break;
                    default: throw new InvalidDataException($"unsupported {bits}-bit WAV");
                }
            }
            if (frames <= 0) throw new InvalidDataException("empty data chunk");
            return (samples, channels, rate);
        }
        private static AudioClip Pick(string prefix)
        {
            var list = new List<AudioClip>(6);
            foreach (var entry in Clips)
                // "servo_" (start/turn) must not pick "servo_jump": the jump has its own slider
                if (entry.Key.StartsWith(prefix) && !(prefix == "servo_" && entry.Key.StartsWith("servo_jump"))) list.Add(entry.Value);
            return list.Count == 0 ? null : list[Random.Range(0, list.Count)];
        }

        private static int _diag = 3;

        private static void Play(string prefix, float volume, ConfigEntry<float> part, float pitchJitter = 0.06f)
        {
            volume *= part.Value;
            if (volume <= 0f) return;
            var clip = Pick(prefix);
            if (clip == null || _oneShot == null) return;
            if (_diag > 0)
            {
                _diag--;
                var listener = Object.FindObjectOfType<AudioListener>();
                Plugin.Log.LogInfo($"[Juggernaut] sound {clip.name}: state {clip.loadState}, len {clip.length:F2}s, vol {volume * _volume.Value:F2}, " +
                                   $"listener {(listener != null ? listener.name + (listener.enabled ? "" : " (off)") : "none")}, AudioListener.volume {AudioListener.volume:F2}, pause {AudioListener.pause}");
            }
            _oneShot.pitch = 1f + Random.Range(-pitchJitter, pitchJitter);
            _oneShot.PlayOneShot(clip, volume * _volume.Value);
        }

        private static void Attach(Player player)
        {
            Detach();
            _player = player;
            _host = new GameObject("JuggernautSuitAudio");
            _host.transform.SetParent(player.Transform.Original, false);
            _host.transform.localPosition = new Vector3(0f, 0.9f, 0f);
            _oneShot = NewSource(false);
            _hum = NewSource(true);
            // the surface layer gets its own object: a low-pass filter acts on every source of its GameObject
            var surfaceHost = new GameObject("JuggernautSurfaceSteps");
            surfaceHost.transform.SetParent(_host.transform, false);
            _surface = surfaceHost.AddComponent<AudioSource>();
            _surface.playOnAwake = false; _surface.spatialBlend = 0f; _surface.priority = 32;
            _surfaceFilter = surfaceHost.AddComponent<AudioLowPassFilter>();
            _surfaceFilter.cutoffFrequency = 2200f;
            _hum.clip = Clips.TryGetValue("hum_loop", out var hum) ? hum : null;
            _lastPos = player.Transform.position;
            _lastYaw = player.Transform.rotation.eulerAngles.y;
            _lastMode = JugSet.Mode(player);
        }

        private static AudioSource NewSource(bool loop)
        {
            var source = _host.AddComponent<AudioSource>();
            source.loop = loop;
            source.playOnAwake = false;
            source.spatialBlend = 0f;          // the wearer hears it in his own head
            source.priority = 32;
            // routed straight to the listener: the game mixer group used before kept the suit silent
            return source;
        }

        private static void Detach()
        {
            if (_host != null) Object.Destroy(_host);
            _host = null; _oneShot = null; _hum = null; _surface = null; _surfaceFilter = null; _player = null;
        }

        private static float _nextRemoteCleanup;

        internal static void Tick()
        {
            if (Time.unscaledTime >= _nextRemoteCleanup) { _nextRemoteCleanup = Time.unscaledTime + 5f; CleanupRemote(); }
            var player = Singleton<GameWorld>.Instance?.MainPlayer;
            var mode = player != null ? JugSet.Mode(player) : SetMode.None;
            if (!_enabled.Value || Raw.Count == 0 || player == null || mode == SetMode.None || player.HealthController?.IsAlive != true)
            {
                if (_host != null) Detach();
                return;
            }
            if (ClipsLost())
            {
                BuildClips();
                Plugin.Log.LogInfo($"[Juggernaut] sound clips rebuilt: {Clips.Count}");
                Detach();
            }
            if (!ReferenceEquals(player, _player) || _host == null) Attach(player);

            float dt = Mathf.Max(Time.deltaTime, 1e-4f);
            var pos = player.Transform.position;
            var delta = pos - _lastPos; _lastPos = pos;
            var flat = new Vector3(delta.x, 0f, delta.z);
            float speed = flat.magnitude / dt;
            if (speed > 20f) speed = 0f;                    // teleport / respawn
            bool grounded = player.MovementContext?.IsGrounded ?? true;
            bool powered = mode == SetMode.Powered;

            // power cues
            if (mode != _lastMode)
            {
                if (_lastMode == SetMode.Discharged && powered) Play("power_up", 1f, _vPowerUp, 0f);
                else if (_lastMode == SetMode.Powered && mode == SetMode.Discharged) Play("power_down", 1f, _vPowerDown, 0f);
                _lastMode = mode;
            }

            // footsteps: one heavy step on each footstep the game itself plays
            if (_pendingSteps > 0)
            {
                _pendingSteps = 0;
                var surfaceClip = _pendingSurfaceClip; _pendingSurfaceClip = null;
                if (grounded && speed > 0.3f)
                {
                    // surface layer: the game's clip pitched down and darkened (a much heavier foot on the same floor)
                    if (surfaceClip != null && _surface != null)
                    {
                        _surface.pitch = Random.Range(0.66f, 0.74f);
                        _surface.PlayOneShot(surfaceClip, 0.9f * _volume.Value * _vSurface.Value);
                    }
                    // weight layer: our non-ringing low thump under it
                    Play("step_heavy", powered ? 0.8f : 0.7f, _vThump);
                    if (!powered && Random.value < 0.35f && _creakCooldown <= 0f) { Play("creak", 0.7f, _vCreak); _creakCooldown = 1.2f; }
                }
            }

            // servo whine on starting to move and on sharp turns (powered only)
            _servoCooldown -= dt; _creakCooldown -= dt;
            bool moving = speed > 0.6f;
            float yaw = player.Transform.rotation.eulerAngles.y;
            float yawRate = Mathf.Abs(Mathf.DeltaAngle(_lastYaw, yaw)) / dt; _lastYaw = yaw;
            if (powered && _servoCooldown <= 0f && ((moving && !_wasMoving) || yawRate > 260f))
            {
                Play("servo_", 0.5f, _vServo, 0.05f);
                _servoCooldown = 1.6f;
            }
            _wasMoving = moving;

            // jump and landing
            if (!grounded) _airTime += dt;
            if (_wasGrounded && !grounded && delta.y > 0.02f && powered) Play("servo_jump", 0.9f, _vJump, 0.05f);
            if (!_wasGrounded && grounded && _airTime > 0.35f) Play("land_heavy", Mathf.Clamp01(0.6f + _airTime * 0.5f), _vLand, 0.04f);
            if (grounded) _airTime = 0f;
            _wasGrounded = grounded;

            // motor hum follows the speed while powered
            if (_hum != null && _hum.clip != null)
            {
                float target = powered ? Mathf.Clamp01(speed / 6f) * 0.35f * _volume.Value * _vHum.Value : 0f;
                _hum.volume = Mathf.MoveTowards(_hum.volume, target, dt * 0.8f);
                _hum.pitch = 0.9f + Mathf.Clamp01(speed / 6f) * 0.25f;
                if (_hum.volume > 0.001f && !_hum.isPlaying) _hum.Play();
                else if (_hum.volume <= 0.001f && _hum.isPlaying) _hum.Stop();
            }
        }
    }
}
