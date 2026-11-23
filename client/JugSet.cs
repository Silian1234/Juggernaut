// Juggernaut set state and power.
//   Powered    = suit + Juggernaut helmet worn, and the current power window is paid (one cell = DrainMinutes).
//   Discharged = suit worn but no helmet, or no cell left to pay the next window.
// In raid, every DrainMinutes the suit consumes (removes) one power cell from the player's own inventory
// (pockets, rig, backpack, secure container) through a normal inventory transaction, so the server saves it.
// Out of raid nothing is drained. Only the local main player is handled (Fika: each client drains its own cells).
using System;
using System.Linq;
using Comfort.Common;
using EFT;
using EFT.Communications;
using EFT.InventoryLogic;
using UnityEngine;

namespace JuggernautClient
{
    internal enum SetMode { None = 0, Powered = 1, Discharged = 2 }

    internal static class JugSet
    {
        internal const string Suit = "dd0dd2c4b50ad72dd5b6dc62";
        internal const string Helmet = "ad9e1818143bc0cf5bbd4295";
        internal const string Module = "da2c9ba6108e2e14c0e982c6";
        internal const string Cell = "866318f980bf699a8cae99fc";

        private static SetMode _mode;
        private static Player _player;
        private static GameWorld _world;
        private static float _paidUntil;          // Time.time until which the set is powered
        private static bool _warnedNoHelmet, _warnedNoCells;
        private static float _nextTry;
        private static ArmoredEquipmentTemplate _penaltyTemplate;
        private static SetMode _appliedPenalties;
        private static float _raidStartedAt = -1f;

        private static bool RaidStarted()
        {
            try
            {
                var game = Singleton<AbstractGame>.Instance;
                return game != null && game.Status == GameStatus.Started;
            }
            catch { return false; }
        }

        internal static SetMode Mode(Player p) => p != null && ReferenceEquals(p, _player) ? _mode : SetMode.None;

        internal static bool IsLocal(Player p) => p != null && ReferenceEquals(Singleton<GameWorld>.Instance?.MainPlayer, p);

        internal static Item Worn(Player p, EquipmentSlot slot) => p?.Inventory?.Equipment?.GetSlot(slot)?.ContainedItem;

        // the helmet's built-in thermal module (a ThermalVision item: N toggles it, the state is saved with the item)
        internal static ThermalVisionComponent ModuleThermal(Player p)
        {
            if (!(Worn(p, EquipmentSlot.Headwear) is CompoundItem helmet) || helmet.StringTemplateId != Helmet) return null;
            var module = helmet.Slots.Select(s => s?.ContainedItem).FirstOrDefault(i => i?.StringTemplateId == Module);
            return module?.GetItemComponent<ThermalVisionComponent>();
        }

        internal static bool HasModule(Player p)
        {
            if (!(Worn(p, EquipmentSlot.Headwear) is CompoundItem helmet) || helmet.StringTemplateId != Helmet) return false;
            return helmet.Slots.Any(s => s?.ContainedItem?.StringTemplateId == Module);
        }

        internal static void Tick()
        {
            var world = Singleton<GameWorld>.Instance;
            if (!ReferenceEquals(world, _world))
            {
                _world = world; _paidUntil = 0f; _warnedNoHelmet = _warnedNoCells = false; _nextTry = 0f;
            }
            var player = world?.MainPlayer;
            var mode = Compute(world, player);
            if (mode != _mode || !ReferenceEquals(player, _player))
            {
                var old = _mode;
                _player = player; _mode = mode;
                if (old != SetMode.None && mode == SetMode.Powered) Notify("jug.msg.powered", false);
                if (mode == SetMode.Powered && old == SetMode.None) Notify("jug.msg.powered", false);
                if (mode == SetMode.Discharged) Notify(_warnedNoHelmet ? "jug.msg.nohelmet" : "jug.msg.discharged", true);
            }
            ApplyPenalties(player, mode);
        }

        private static SetMode Compute(GameWorld world, Player player)
        {
            if (world == null || player == null || world is HideoutGameWorld || player is HideoutPlayer) return SetMode.None;
            if (player.HealthController?.IsAlive != true) return SetMode.None;
            // Fika: inventory transactions sent while the raid is still loading hang on the host and lock the
            // whole inventory ("Default Inventory is currently being modified"), so weapons cannot be equipped.
            if (!RaidStarted()) { _raidStartedAt = -1f; return SetMode.None; }
            if (_raidStartedAt < 0f) _raidStartedAt = Time.time;
            if (Time.time < _raidStartedAt + 3f) return SetMode.None;
            if (Worn(player, EquipmentSlot.ArmorVest)?.StringTemplateId != Suit) return SetMode.None;
            if (Worn(player, EquipmentSlot.Headwear)?.StringTemplateId != Helmet)
            {
                _warnedNoHelmet = true;
                return SetMode.Discharged;
            }
            _warnedNoHelmet = false;
            if (Time.time < _paidUntil) return SetMode.Powered;
            if (Time.time < _nextTry) return SetMode.Discharged;
            return TryConsumeCell(player) ? SetMode.Powered : SetMode.Discharged;
        }

        /// <summary>Removes one cell from the player's inventory and pays the next power window.</summary>
        private static bool TryConsumeCell(Player player)
        {
            try
            {
                var cells = player.Inventory.GetPlayerItems(EPlayerItems.Equipment).Where(i => i.StringTemplateId == Cell).ToList();
                if (cells.Count == 0)
                {
                    _nextTry = Time.time + 2f;
                    if (!_warnedNoCells) { _warnedNoCells = true; }
                    return false;
                }
                var controller = player.InventoryController;
                // simulate = true: only build the removal operation; TryRunNetworkTransaction executes it once
                // and syncs it (Fika: through the host). Executing it here as well removed the cell twice.
                var result = ItemManipulator.Remove(cells[0], controller, true);
                if (result.Failed)
                {
                    Plugin.Log.LogWarning("[Juggernaut] could not consume a power cell: " + result.Error);
                    _nextTry = Time.time + 5f;
                    return false;
                }
                controller.TryRunNetworkTransaction(result);
                _warnedNoCells = false;
                _paidUntil = Time.time + Mathf.Max(0.5f, ServerSettings.Get().DrainMinutes) * 60f;
                int left = cells.Count - 1;
                if (left == 0) Notify("jug.msg.lastcell", true);
                else Notify("jug.msg.cell", false, left);
                Plugin.Log.LogInfo($"[Juggernaut] power cell consumed, {left} left, powered for {ServerSettings.Get().DrainMinutes} min");
                return true;
            }
            catch (Exception ex)
            {
                _nextTry = Time.time + 5f;
                Plugin.Log.LogWarning("[Juggernaut] power cell consumption failed: " + ex.Message);
                return false;
            }
        }

        /// <summary>Discharged: the suit's own gear penalties become heavy; powered / not worn: none.</summary>
        private static void ApplyPenalties(Player player, SetMode mode)
        {
            var want = mode == SetMode.Discharged ? SetMode.Discharged : SetMode.Powered;
            if (want == _appliedPenalties && _penaltyTemplate != null) return;
            var suit = Worn(player, EquipmentSlot.ArmorVest);
            var template = suit?.StringTemplateId == Suit ? suit.Template as ArmoredEquipmentTemplate : _penaltyTemplate;
            if (template == null) return;
            _penaltyTemplate = template;
            _appliedPenalties = want;
            bool d = want == SetMode.Discharged;
            template.speedPenaltyPercent = d ? JugTiers.DischargedSpeedPenalty : 0f;
            template.mousePenalty = d ? JugTiers.DischargedMousePenalty : 0f;
            template.weaponErgonomicPenalty = d ? JugTiers.DischargedErgoPenalty : 0f;
            try { if (IsLocal(player)) player.RecalculateEquipmentParams(); }
            catch (Exception ex) { Plugin.Log.LogWarning("[Juggernaut] penalty refresh failed: " + ex.Message); }
        }

        internal static void Notify(string key, bool warning, int n = 0)
        {
            try
            {
                var text = key.Localized().Replace("{n}", n.ToString());
                if (warning) NotificationManager.DisplayWarningNotification(text);
                else NotificationManager.DisplayMessageNotification(text);
            }
            catch (Exception ex) { Plugin.Log.LogWarning("[Juggernaut] notification failed: " + ex.Message); }
        }
    }
}
