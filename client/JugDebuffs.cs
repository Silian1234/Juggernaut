// Discharged set: no sprint, no jumping (MovementContext.CanSprint / CanJump answer false for the local player).
using HarmonyLib;
using EFT;

namespace JuggernautClient
{
    internal static class JugDebuffs
    {
        private static readonly AccessTools.FieldRef<MovementContext, Player> MovementPlayer =
            AccessTools.FieldRefAccess<MovementContext, Player>("_player");

        internal static void Patch(Harmony harmony)
        {
            harmony.Patch(AccessTools.PropertyGetter(typeof(MovementContext), nameof(MovementContext.CanSprint)),
                postfix: new HarmonyMethod(typeof(JugDebuffs), nameof(Block)));
            harmony.Patch(AccessTools.PropertyGetter(typeof(MovementContext), nameof(MovementContext.CanJump)),
                postfix: new HarmonyMethod(typeof(JugDebuffs), nameof(Block)));
        }

        private static void Block(MovementContext __instance, ref bool __result)
        {
            if (__result && JugSet.Mode(MovementPlayer(__instance)) == SetMode.Discharged) __result = false;
        }
    }
}
