// The Juggernaut thermal module is a real head thermal device (T-7 template), so the game toggles it with N and
// keeps its state. Its picture is not the game's thermal filter: when the module is the worn thermal, the camera
// thermal effect is kept off and ThermalOutline draws the red outline instead.
using EFT.CameraControl;
using HarmonyLib;

namespace JuggernautClient
{
    internal static class ThermalPictureBlock
    {
        internal static void Patch(Harmony harmony)
        {
            // SPT 4.1.6 (EFT 40743): PlayerCameraController.method_5 applies Player.ThermalVisionObserver to the camera
            var apply = AccessTools.DeclaredMethod(typeof(PlayerCameraController), "method_5", new System.Type[0])
                        ?? throw new System.MissingMethodException("PlayerCameraController.method_5()");
            harmony.Patch(apply, prefix: new HarmonyMethod(typeof(ThermalPictureBlock), nameof(Prefix)));
        }

        private static bool Prefix(PlayerCameraController __instance)
        {
            var component = __instance.Player?.ThermalVisionObserver?.Component;
            if (component == null || component.Item.StringTemplateId != JugSet.Module) return true;
            var thermal = CameraManager.Instance?.ThermalVision;
            if (thermal != null && thermal.enabled && thermal.On) thermal.StartSwitch(false);
            return false;
        }
    }
}
