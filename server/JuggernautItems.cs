// Juggernaut set: suit (ArmorVest), helmet (Headwear), thermal module (helmet attachment), power cell (consumable).
//   Suit    — Kora-Kulon clone, NO removable parts: built-in class 6 Aramid inserts on every FBA zone, 45 kg.
//             Native ConflictingItems: every other headwear and every armored rig (the set rule, always on).
//   Helmet  — Vulkan-5 clone, closed full face: built-in class 6 Aramid on top/back/ears/face (eyes+jaw), blocks face cover
//             and eyewear, earpiece stays free; slot mod_nvg takes only the thermal module.
//   Module  — T-7 thermal clone (a real head thermal: N toggles it, the on/off state is saved with the item);
//             the client replaces the thermal picture with the red outline.
//   Cell    — Portable Powerbank clone (1x2); the suit consumes one from the inventory every DrainMinutes (client).
// Models come from art/ bundles when present (see bundles.json); until then the donors' vanilla models are used.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SPTarkov.Common.Models.Logging;
using SPTarkov.DI.Annotations;
using SPTarkov.Server.Core.DI;
using SPTarkov.Server.Core.Models.Common;
using SPTarkov.Server.Core.Models.Eft.Common;
using SPTarkov.Server.Core.Models.Eft.Common.Tables;
using SPTarkov.Server.Core.Models.Enums;
using SPTarkov.Server.Core.Models.Spt.Config;
using SPTarkov.Server.Core.Models.Spt.Mod;
using SPTarkov.Server.Core.Models.Spt.Tables;
using SPTarkov.Server.Core.Services.Modding.Custom;
using Path = System.IO.Path;

namespace Juggernaut;

[Injectable(InjectionType.Singleton, OnLoadOrder.Preload + 40)]
public class JuggernautItems(TemplateTable templates, TradersTable traders, GlobalTable globals, LocaleTable locales,
    CustomItemService itemService, TraderConfig traderConfig, ISptLogger<JuggernautItems> log) : IOnLoad
{
    public const string Suit = "dd0dd2c4b50ad72dd5b6dc62";
    public const string Helmet = "ad9e1818143bc0cf5bbd4295";
    public const string Module = "da2c9ba6108e2e14c0e982c6";
    public const string Cell = "866318f980bf699a8cae99fc";

    private const string SuitDonor = "64be79c487d1510151095552";      // NPP KlASS Kora-Kulon
    private const string HelmetDonor = "5ca20ee186f774799474abc2";    // Vulkan-5 LShZ-5 (closed helmet; model base)
    private const string ModuleDonor = "5c110624d174af029e69734c";    // T-7 thermal goggles (ThermalVision template)
    private const string CellDonor = "5af0561e86f7745f5f3ad6ac";      // Portable Powerbank (model base)
    private const string RacHeadset = "5a16b9fffcdbcb0176308b34";     // Ops-Core FAST RAC Headset (helmet-mounted; donor of the built-in ears)
    private static readonly string Ears = Id("item.ears");             // built-in headset, Ops-Core AMP sound profile
    private const string InsertDonor = "6575d9a79e27f4a85e08112d";    // Redut-T5 built-in soft insert
    private const string ArmorSlotProto = "64479fdf9731c8fadc0642c1";
    private const string ModSlotProto = "55d30c4c4bdc2db4468b457e";
    private const string Ragman = "5ac3b934156ae10c4430e83c";
    private const string Roubles = "5449016a4bdc2d6f028b456f";
    private const string Headwear = "5a341c4086f77401f2541505";
    private const string Rig = "5448e5284bdc2dcb718b4567";
    // handbook categories (verified in handbook.json): Body armor, Headgear, Mounts, Energy elements, Gear components
    private const string HbArmor = "5b5f701386f774093f2ecf0f", HbHelmets = "5b47574386f77428ca22b330",
        HbMounts = "5b5f755f86f77447ec5d770e", HbEnergy = "5b47574386f77428ca22b2ed", HbPlates = "5b5f704686f77447ec5d76d7";
    private const string ModelDir = "assets/content/items/equipment/juggernaut/";

    // class 6 Aramid, same scale as FullBodyArmor class 6 (durability 85; plates 0.30 / soft 0.36 blunt)
    private const double Durability = 85, BluntSoft = 0.36, BluntPlate = 0.30;

    private record Zone(string Key, double Blunt, string[] Colliders, string[] Plates);
    private static readonly Zone[] SuitZones =
    {
        new("torso", BluntPlate, new[] { "RibcageUp", "RibcageLow", "SpineTop", "SpineDown" }, new[] { "Plate_Granit_SAPI_chest", "Plate_Granit_SAPI_back" }),
        new("side", BluntPlate, new[] { "LeftSideChestDown", "RightSideChestDown", "LeftSideChestUp", "RightSideChestUp" },
            new[] { "Plate_Granit_SSAPI_side_left_high", "Plate_Granit_SSAPI_side_left_low", "Plate_Granit_SSAPI_side_right_high", "Plate_Granit_SSAPI_side_right_low" }),
        new("collar", BluntSoft, new[] { "NeckFront", "NeckBack" }, new string[0]),
        new("shoulder", BluntSoft, new[] { "LeftUpperArm", "RightUpperArm" }, new string[0]),
        new("forearm", BluntSoft, new[] { "LeftForearm", "RightForearm" }, new string[0]),
        new("groin", BluntSoft, new[] { "Pelvis", "PelvisBack" }, new string[0]),
        new("thigh", BluntSoft, new[] { "LeftThigh", "RightThigh" }, new string[0]),
        new("calf", BluntSoft, new[] { "LeftCalf", "RightCalf" }, new string[0]),
    };
    // suit slot -> zone, colliders, plate colliders (one slot per side, like EXO-3)
    private static readonly (string Slot, string Zone, string[] Colliders, string[] Plates)[] SuitSlots =
    {
        ("Front_plate", "torso", new[] { "RibcageUp", "RibcageLow" }, new[] { "Plate_Granit_SAPI_chest" }),
        ("Back_plate", "torso", new[] { "SpineTop", "SpineDown" }, new[] { "Plate_Granit_SAPI_back" }),
        ("Left_side_plate", "side", new[] { "LeftSideChestDown", "LeftSideChestUp" }, new[] { "Plate_Granit_SSAPI_side_left_high", "Plate_Granit_SSAPI_side_left_low" }),
        ("Right_side_plate", "side", new[] { "RightSideChestDown", "RightSideChestUp" }, new[] { "Plate_Granit_SSAPI_side_right_high", "Plate_Granit_SSAPI_side_right_low" }),
        ("Collar", "collar", new[] { "NeckFront", "NeckBack" }, new string[0]),
        ("Shoulder_l", "shoulder", new[] { "LeftUpperArm" }, new string[0]),
        ("Shoulder_r", "shoulder", new[] { "RightUpperArm" }, new string[0]),
        ("Forearm_l", "forearm", new[] { "LeftForearm" }, new string[0]),
        ("Forearm_r", "forearm", new[] { "RightForearm" }, new string[0]),
        ("Groin", "groin", new[] { "Pelvis" }, new string[0]),
        ("Groin_back", "groin", new[] { "PelvisBack" }, new string[0]),
        ("Thigh_l", "thigh", new[] { "LeftThigh" }, new string[0]),
        ("Thigh_r", "thigh", new[] { "RightThigh" }, new string[0]),
        ("Calf_l", "calf", new[] { "LeftCalf" }, new string[0]),
        ("Calf_r", "calf", new[] { "RightCalf" }, new string[0]),
    };
    private static readonly (string Slot, string Key, string[] Colliders)[] HelmetSlots =
    {
        ("Helmet_top", "helmet_top", new[] { "ParietalHead", "HeadCommon" }),
        ("Helmet_back", "helmet_back", new[] { "BackHead" }),
        ("Helmet_ears", "helmet_ears", new[] { "Ears" }),
        ("Helmet_face", "helmet_face", new[] { "Eyes", "Jaw" }),
    };

    public Task OnLoadAsync(CancellationToken cancellationToken)
    {
        try { Register(); }
        catch (Exception ex) { log.Error($"[Juggernaut] registration failed: {ex}"); }
        return Task.CompletedTask;
    }

    private static string Id(string name)
    {
        var bytes = System.Security.Cryptography.MD5.HashData(System.Text.Encoding.ASCII.GetBytes("juggernaut." + name));
        return Convert.ToHexString(bytes, 0, 12).ToLowerInvariant();
    }

    private Dictionary<MongoId, TemplateItem> Items => templates.Items;

    private TemplateItem Clone(string id, string donor, string handbook, int price, string key)
    {
        var items = Items;
        if (items.ContainsKey(new MongoId(id))) throw new InvalidOperationException($"template {id} already exists");
        var r = itemService.CreateItemFromClone(new NewItemFromCloneDetails
        {
            NewItemName = string.Empty,
            ItemTplToClone = new MongoId(donor), NewId = id, ParentId = items[new MongoId(donor)].Parent.ToString(),
            HandbookParentId = handbook, HandbookPriceRoubles = price, FleaPriceRoubles = price,
            Locales = Texts.Item(key + ".name", key + ".short", key + ".desc")
        });
        if (r?.Success != true || !items.TryGetValue(new MongoId(id), out var item) || item.Properties == null)
            throw new InvalidOperationException($"{key}: clone failed: " + string.Join("; ", r?.Errors ?? new List<string>()));
        item.Properties.CanSellOnRagfair = false;
        return item;
    }

    private string Insert(string key, string[] colliders, string[] plates, double blunt)
    {
        var id = Id("insert." + key);
        var item = Clone(id, InsertDonor, HbPlates, 30000, "jug.insert");
        var p = item.Properties;
        p.ArmorClass = 6;
        p.ArmorMaterial = ArmorMaterial.Aramid;
        p.MaxDurability = Durability; p.Durability = Durability;
        p.ArmorColliders = colliders.ToList();
        p.ArmorPlateColliders = plates.ToList();
        p.BluntThroughput = blunt;
        p.ArmorType = "Heavy";
        p.Weight = 0;     // the weight is on the frame / helmet shell
        return id;
    }

    private static Slot ArmorSlot(string parent, string name, string plate, string[] colliders, string[] plates) => new()
    {
        Id = Id($"{parent}.slot.{name}"), Name = name, Parent = parent, Prototype = ArmorSlotProto, Required = true, MergeSlotWithChildren = true,
        Properties = new SlotProperties { Filters = new List<SlotFilter> { new()
        {
            Filter = new HashSet<MongoId> { new MongoId(plate) }, Plate = new MongoId(plate), Locked = true,
            ArmorColliders = colliders.ToList(), ArmorPlateColliders = plates.ToList(), BluntDamageReduceFromSoftArmor = false
        } } }
    };

    private Prefab Model(string bundle, Prefab fallback)
    {
        var dir = Path.Combine(Path.GetDirectoryName(typeof(JuggernautItems).Assembly.Location)!, "bundles");
        var file = Path.Combine(dir, (ModelDir + bundle).Replace('/', Path.DirectorySeparatorChar));
        return File.Exists(file) ? new Prefab { Path = ModelDir + bundle, Rcid = "" } : fallback;
    }

    private void Register()
    {
        var items = Items;
        var cfg = JuggernautSettings.Config;

        // ---- power cell
        var cell = Clone(Cell, CellDonor, HbEnergy, 8000, "jug.cell").Properties;
        cell.Width = 1; cell.Height = 2; cell.Weight = 0.8; cell.StackMaxSize = 1;
        cell.Prefab = Model("item_juggernaut_power_cell.bundle", cell.Prefab);

        // ---- thermal module (a T-7 thermal device with our model; the picture is replaced client-side)
        var module = Clone(Module, ModuleDonor, HbMounts, 400000, "jug.module").Properties;
        module.Slots = new List<Slot>();
        module.Weight = 0.6;
        module.Prefab = Model("item_juggernaut_thermal_module.bundle", module.Prefab);

        // ---- built-in ears: RAC clone with the Ops-Core AMP sound profile, locked into the helmet
        var ears = Clone(Ears, RacHeadset, HbMounts, 150000, "jug.ears").Properties;
        ears.Distortion = 0.05; ears.CompressorThreshold = -24; ears.CompressorGain = 8;
        ears.AmbientVolume = -65; ears.DryVolume = -60; ears.HighpassFreq = 200; ears.HighpassResonance = 2.2;
        ears.CompressorAttack = 35; ears.CompressorRelease = 160;
        ears.Weight = 0;

        // ---- helmet
        var helmet = Clone(Helmet, HelmetDonor, HbHelmets, 10000000, "jug.helmet").Properties;
        var hSlots = HelmetSlots.Select(s => ArmorSlot(Helmet, s.Slot, Insert(s.Key, s.Colliders, new string[0], BluntSoft), s.Colliders, new string[0])).ToList();
        hSlots.Add(new Slot
        {
            Id = Id("helmet.slot.mod_nvg"), Name = "mod_nvg", Parent = Helmet, Prototype = ModSlotProto, Required = false, MergeSlotWithChildren = false,
            Properties = new SlotProperties { Filters = new List<SlotFilter> { new() { Filter = new HashSet<MongoId> { new MongoId(Module) }, Locked = true } } }
        });
        hSlots.Add(new Slot
        {
            Id = Id("helmet.slot.mod_equipment_001"), Name = "mod_equipment_001", Parent = Helmet, Prototype = ModSlotProto, Required = false, MergeSlotWithChildren = false,
            Properties = new SlotProperties { Filters = new List<SlotFilter> { new() { Filter = new HashSet<MongoId> { new MongoId(Ears) }, Locked = true } } }
        });
        helmet.Slots = hSlots;
        helmet.BlocksFaceCover = true;
        helmet.BlocksEyewear = true;
        helmet.BlocksEarpiece = true;    // the ears are built in
        helmet.Weight = 6.5;
        helmet.ArmorMaterial = ArmorMaterial.Aramid;
        helmet.Prefab = Model("item_equipment_juggernaut_helmet.bundle", helmet.Prefab);

        // ---- suit
        var suit = Clone(Suit, SuitDonor, HbArmor, 15000000, "jug.suit").Properties;
        var zoneIds = SuitZones.ToDictionary(z => z.Key, z => Insert(z.Key, z.Colliders, z.Plates, z.Blunt));
        suit.Slots = SuitSlots.Select(s => ArmorSlot(Suit, s.Slot, zoneIds[s.Zone], s.Colliders, s.Plates)).ToList();
        suit.Weight = 45;
        suit.ArmorMaterial = ArmorMaterial.Aramid;
        suit.SpeedPenaltyPercent = 0; suit.MousePenalty = 0; suit.WeaponErgonomicPenalty = 0;   // discharged penalties: client
        suit.Prefab = Model("item_equipment_juggernaut_suit.bundle", suit.Prefab);
        // set rule (always on): no other headwear, no armored rigs
        suit.ConflictingItems = items.Values.Where(t => t.Type == "Item" && t.Id.ToString() != Helmet &&
                (IsUnder(t, Headwear, items) || (IsUnder(t, Rig, items) && HasArmor(t, items))))
            .Select(t => t.Id).ToHashSet();

        // ---- Ragman
        var assort = traders.GetValueOrDefault(new MongoId(Ragman))?.Assort ?? throw new InvalidOperationException("Ragman assortment unavailable");
        var presets = globals.ItemPresets;
        Sell(assort, presets, Suit, suit.Slots.ToList(), 4, 15000000, 1, "Juggernaut suit");
        Sell(assort, presets, Helmet, hSlots, 4, 10000000, 1, "Juggernaut helmet");   // thermal module and ears come built in
        Sell(assort, presets, Cell, new List<Slot>(), 2, 8000, 0, null);

        // ---- Fence never sells the set (his random presets would also pick up the built-in helmet modules)
        foreach (var id in new[] { Suit, Helmet, Module, Cell, Ears }.Concat(zoneIds.Values).Concat(hSlots.Select(x => x.Properties.Filters.Single().Filter.First().ToString())))
            traderConfig.Fence.Blacklist.Add(new MongoId(id));

        // ---- client messages, localized through the game's own locale tables
        foreach (var (lang, table) in locales.Global)
            table.AddTransformer(t => { foreach (var k in Texts.MessageKeys) t[k] = Texts.Get(lang, k); return t; });

        log.Success($"[Juggernaut] registered: suit ({suit.Slots.Count()} built-in class 6 slots, {suit.ConflictingItems.Count()} conflicts), helmet, thermal module, power cell; " +
                    $"models {(suit.Prefab.Path.StartsWith(ModelDir) ? "custom" : "vanilla fallback")}; drain every {cfg.DrainMinutes} min");
    }

    private void Sell(TraderAssort assort, Dictionary<MongoId, Preset> presets, string tpl, List<Slot> slots, int loyalty, int price, int limit, string presetName)
    {
        var offer = new MongoId(Id("offer." + tpl));
        if (assort.Items.Any(i => i.Id == offer)) throw new InvalidOperationException($"offer for {tpl} already exists");
        var kit = Kit(offer, new MongoId(tpl), slots, true, limit);
        assort.Items.AddRange(kit);
        assort.BarterScheme.Add(offer, new() { new() { new BarterScheme { Template = new MongoId(Roubles), Count = price } } });
        assort.LoyalLevelItems.Add(offer, loyalty);
        if (presetName != null)
        {
            var presetId = new MongoId(Id("preset." + tpl)); var root = new MongoId();
            presets.Add(presetId, new Preset { Id = presetId, Type = "Preset", Name = presetName, Parent = root, Encyclopedia = new MongoId(tpl),
                Items = Kit(root, new MongoId(tpl), slots, false, 0) });
        }
    }

    private List<Item> Kit(MongoId rootId, MongoId tpl, List<Slot> slots, bool forSale, int limit)
    {
        var upd = forSale ? new Upd { StackObjectsCount = limit > 0 ? 10 : 999999, UnlimitedCount = limit == 0 } : null;
        if (forSale && limit > 0) { upd.BuyRestrictionMax = limit; upd.BuyRestrictionCurrent = 0; }
        var kit = new List<Item> { new() { Id = rootId, Template = tpl, ParentId = forSale ? "hideout" : null, SlotId = forSale ? "hideout" : null, Upd = upd } };
        foreach (var slot in slots)
        {
            var f = slot.Properties.Filters.Single(); var plate = f.Plate ?? f.Filter.First();   // armor insert, or the built-in mod
            var max = Items[plate].Properties.MaxDurability ?? 0;
            kit.Add(new Item { Id = new MongoId(), Template = plate, ParentId = rootId.ToString(), SlotId = slot.Name,
                Upd = max > 0 ? new Upd { Repairable = new UpdRepairable { Durability = max, MaxDurability = max } } : null });
        }
        return kit;
    }

    private static bool IsUnder(TemplateItem item, string baseClass, Dictionary<MongoId, TemplateItem> items)
    {
        var target = new MongoId(baseClass);
        for (var i = 0; i < 32 && item != null; ++i)
        {
            if (item.Parent == target) return true;
            items.TryGetValue(item.Parent, out item);
        }
        return false;
    }

    private static bool HasArmor(TemplateItem item, Dictionary<MongoId, TemplateItem> items) =>
        (item.Properties?.ArmorClass ?? 0) > 0 ||
        (item.Properties?.Slots?.Any(s => s.Properties?.Filters?.Any(f =>
            f.ArmorColliders?.Any() == true || f.ArmorPlateColliders?.Any() == true ||
            (f.Plate.HasValue && items.TryGetValue(f.Plate.Value, out var part) && (part.Properties?.ArmorClass ?? 0) > 0)) == true) == true);
}
