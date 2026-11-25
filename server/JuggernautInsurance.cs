// Insurance: the suit and the helmet come back whole.
// SPT insures only those armor parts whose slot names match the vanilla soft-insert names (soft_armor_front, helmet_top...).
// The suit's plate slots (Front_plate...), forearms, thighs, calves, the helmet face and the built-in thermal module / ears
// are not on that list, so they were never insured and the returned suit or helmet came back with parts missing.
// A postfix on InsuranceService.MapInsuredItemsToTrader adds every part of a lost insured suit or helmet to the returned
// package (from the pre-raid profile, same trader). It works for gear insured before this fix too.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using HarmonyLib;
using SPTarkov.Common.Models.Logging;
using SPTarkov.DI.Annotations;
using SPTarkov.Reflection.Patching;
using SPTarkov.Server.Core.Extensions;
using SPTarkov.Server.Core.Models.Common;
using SPTarkov.Server.Core.Models.Eft.Common;
using SPTarkov.Server.Core.Models.Eft.Common.Tables;
using SPTarkov.Server.Core.Models.Spt.Services;
using SPTarkov.Server.Core.Models.Utils;
using SPTarkov.Server.Core.Services.Commerce;

namespace Juggernaut;

[Injectable]
public class JuggernautInsurancePatch : AbstractPatch
{
    private static ISptLogger<JuggernautInsurancePatch> _log;
    private static readonly HashSet<string> Roots = new(StringComparer.OrdinalIgnoreCase) { JuggernautItems.Suit, JuggernautItems.Helmet };

    public JuggernautInsurancePatch(ISptLogger<JuggernautInsurancePatch> log) : base("JuggernautInsurancePatch")
    {
        _log = log;
    }

    protected override MethodBase GetTargetMethod() =>
        AccessTools.Method(typeof(InsuranceService), nameof(InsuranceService.MapInsuredItemsToTrader));

    [PatchPostfix]
    public static void Postfix(List<InsuranceEquipmentPkg> __result, MongoId sessionId, PmcData pmcProfile)
    {
        try { AddMissingParts(__result, sessionId, pmcProfile); }
        catch (Exception ex) { _log?.Error($"[Juggernaut] insurance: could not add suit/helmet parts: {ex}"); }   // never break the raid end
    }

    private static void AddMissingParts(List<InsuranceEquipmentPkg> packages, MongoId sessionId, PmcData profile)
    {
        var inventory = profile?.Inventory?.Items;
        if (packages == null || packages.Count == 0 || inventory == null) return;
        var present = new HashSet<string>(packages.Where(p => p.ItemToReturnToPlayer != null).Select(p => p.ItemToReturnToPlayer.Id.ToString()));
        var added = new List<InsuranceEquipmentPkg>();
        foreach (var pkg in packages)
        {
            var root = pkg.ItemToReturnToPlayer;
            if (root == null || !Roots.Contains(root.Template.ToString())) continue;
            int count = 0;
            foreach (var part in inventory.GetItemWithChildren(root.Id, excludeStoredItems: true))
            {
                var id = part.Id.ToString();
                if (id == root.Id.ToString() || !present.Add(id)) continue;
                added.Add(new InsuranceEquipmentPkg { SessionId = sessionId, PmcData = profile, ItemToReturnToPlayer = part with { }, TraderId = pkg.TraderId });
                count++;
            }
            if (count > 0) _log?.Info($"[Juggernaut] insurance: {count} built-in parts of {(root.Template.ToString() == JuggernautItems.Suit ? "suit" : "helmet")} {root.Id} added to the return");
        }
        packages.AddRange(added);
    }
}
