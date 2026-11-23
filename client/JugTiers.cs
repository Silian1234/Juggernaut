// Juggernaut stats per set mode. Index: 0 = suit not worn, 1 = powered, 2 = discharged.
// The movement/traversal/melee/recoil hooks are the FullBodyArmor exoskeleton hooks with these tables.
// Discharged speed/mouse/ergonomics penalties are applied through the suit template's own gear penalties (JugSet),
// sprint and jump are blocked in JugDebuffs.
using EFT;
using EFT.InventoryLogic;

namespace JuggernautClient
{
    internal static class JugTiers
    {
        //                                       none   powered discharged
        internal static readonly float[] Sprint = { 1f, 1.80f, 1f };
        internal static readonly float[] Stamina = { 1f, 0.35f, 2.5f };
        internal static readonly float[] Overweight = { 0f, 60f, 0f };
        internal static readonly float[] Jump = { 1f, 2.00f, 1f };
        internal static readonly float[] Melee = { 1f, 5.0f, 1f };
        internal static readonly float[] FallCushion = { 0f, 3.0f, 0f };
        internal static readonly float[] Vault = { 1f, 1.30f, 1f };
        internal static readonly float[] Recoil = { 1f, 0.50f, 1f };

        // discharged gear penalties written into the suit template (game percent units)
        internal const float DischargedSpeedPenalty = -40f;     // movement x0.60
        internal const float DischargedMousePenalty = -30f;
        internal const float DischargedErgoPenalty = -40f;

        /// <summary>Mode index of the local player (other players: 0).</summary>
        internal static int Tier(Player player) => (int)JugSet.Mode(player);

        /// <summary>Out of raid (stash, traders): wearing the suit counts as powered for the weight display.</summary>
        internal static int TierOf(string templateId) => templateId == JugSet.Suit ? 1 : 0;
    }
}
