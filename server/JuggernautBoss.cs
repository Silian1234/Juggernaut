// Juggernaut raid boss, server side.
//   Role    — WildSpawnType bossTest (server key "bosstest"); nothing else in vanilla spawns it. The client plugin gives it the
//             Goon Big Pipe brain, weapon selector and enemy chooser (grenade launcher at 27-130 m); the stats are a bosskilla clone.
//   Gear    — Juggernaut helmet (+ built-in thermal module and headset) and suit with all 15 built-in inserts,
//             PKP/PKM (copied pools of Kaban) in the first weapon slot, "Juggernaut grenade launcher"
//             (M32A1 clone, Unlootable, scaled HE grenades) in the second, Killa's large pockets holding 2 power cells. No followers.
//   Items   — grenade launcher, its cylinder and the grenade are clones, never sold, Fence-blacklisted, unlootable.
// The spawn itself is added per raid by JuggernautBossSpawner (see JuggernautBossSpawn.cs).
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SPTarkov.Common.Models.Logging;
using SPTarkov.DI.Annotations;
using SPTarkov.Server.Core.DI;
using SPTarkov.Server.Core.Models.Common;
using SPTarkov.Server.Core.Models.Eft.Bot.GlobalSettings;
using SPTarkov.Server.Core.Models.Eft.Common;
using SPTarkov.Server.Core.Models.Eft.Common.Tables;
using SPTarkov.Server.Core.Models.Enums;
using SPTarkov.Server.Core.Models.Spt.Config;
using SPTarkov.Server.Core.Models.Spt.Mod;
using SPTarkov.Server.Core.Models.Spt.Tables;
using SPTarkov.Server.Core.Models.Utils;
using SPTarkov.Server.Core.Services.Modding.Custom;
using SPTarkov.Server.Core.Utils.Cloners;

namespace Juggernaut;

[Injectable(InjectionType.Singleton, OnLoadOrder.Preload + 60)]
public class JuggernautBoss(TemplateTable templates, BotTable botTable, BotConfig botConfig, TraderConfig traderConfig,
    CustomItemService itemService, ICloner cloner, ISptLogger<JuggernautBoss> log) : IOnLoad
{
    public const string BotKey = "bosstest";      // BotTable key (lowercase role)
    public const string BossName = "bossTest";    // WildSpawnType name, as used in BossLocationSpawn

    public static readonly string GrenadeLauncher = Id("boss.gl");
    public static readonly string Cylinder = Id("boss.glmag");
    public static readonly string Grenade = Id("boss.grenade");

    private const string LauncherDonor = "6275303a9f372d6ea97f9ec7";   // Milkor M32A1 MSGL
    private const string CylinderDonor = "627bce33f21bc425b06ab967";   // its 6-shot cylinder
    private const string GrenadeDonor = "5ede474b0c226a66f5402622";    // 40x46 M381 HE
    private const string Pkp = "64ca3d3954fc657e230529cc";
    private const string Pkm = "64637076203536ad5600c990";
    private const string GlGrip = "571659bb2459771fb2755a12";          // ids taken from the vanilla M32A1 preset / bot pools
    private const string GlStock = "55d4ae6c4bdc2d8b2f8b456e";
    private const string GlSight = "6284bd5f95250a29bc628a30";
    private const string HbLaunchers = "5b5f79d186f774093f2ed3c2", HbMagazines = "5b5f754a86f774094242f19b", HbAmmo = "5b47574386f77428ca22b33b";
    private const string Caliber40 = "Caliber40x46", Caliber762 = "Caliber762x54R";

    private static readonly string[] KillerRoles = { "pmcBEAR", "pmcUSEC", "pmcBot", "assault", "marksman", "assaultGroup", "cursedAssault" };

    private BodyPart _baseHealth;

    private static string Id(string name)
    {
        var bytes = System.Security.Cryptography.MD5.HashData(System.Text.Encoding.ASCII.GetBytes("juggernaut." + name));
        return Convert.ToHexString(bytes, 0, 12).ToLowerInvariant();
    }

    public Task OnLoadAsync(CancellationToken cancellationToken)
    {
        try
        {
            RegisterItems();
            RegisterBot();
            JuggernautSettings.Changed += ApplyHealth;
        }
        catch (Exception ex) { log.Error($"[Juggernaut] boss registration failed: {ex}"); }
        return Task.CompletedTask;
    }

    // ------------------------------------------------------------------ items

    private TemplateItem Clone(string id, string donor, string handbook, int price, string key)
    {
        var items = templates.Items;
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
        return item;
    }

    // Unlootable only blocks taking the item out of a container whose id contains UnlootableFromSlot
    // (EFT UnlootableComponent.IsUnlootableFrom), so each item names the slot it really sits in on the boss
    private static void Lock(TemplateItemProperties p, string slot)
    {
        p.Unlootable = true;
        p.UnlootableFromSlot = slot;
        p.UnlootableFromSide = new[] { PlayerSideMask.Bear, PlayerSideMask.Usec, PlayerSideMask.Savage };
        p.CanSellOnRagfair = false;
    }

    private void RegisterItems()
    {
        var cfg = JuggernautSettings.Config;
        var dmg = JuggernautSettings.Clamp(cfg.BossGrenadeDamage, 0.01, 10, 0.4);
        var rad = JuggernautSettings.Clamp(cfg.BossGrenadeRadius, 0.1, 5, 0.5);
        var grenadeId = new MongoId(Grenade);
        var cylinderId = new MongoId(Cylinder);

        // ---- grenade: explosion damage and radius scaled at server start
        var g = Clone(Grenade, GrenadeDonor, HbAmmo, 1500, "jug.grenade").Properties;
        g.ExplosionStrength = Math.Round((g.ExplosionStrength ?? 0) * dmg, 2);
        g.Damage = Math.Round((g.Damage ?? 0) * dmg, 2);
        g.MinExplosionDistance = Math.Round((g.MinExplosionDistance ?? 0) * rad, 2);
        g.MaxExplosionDistance = Math.Round((g.MaxExplosionDistance ?? 0) * rad, 2);
        Lock(g, "camora");                    // camora_000..005 of the cylinder

        // ---- cylinder: holds only our grenade
        var m = Clone(Cylinder, CylinderDonor, HbMagazines, 20000, "jug.glmag").Properties;
        foreach (var slot in m.Slots ?? Enumerable.Empty<Slot>())
        {
            slot.Id = new MongoId(Id("boss.glmag.slot." + slot.Name)); slot.Parent = cylinderId;
            foreach (var f in slot.Properties?.Filters ?? Enumerable.Empty<SlotFilter>()) f.Filter = new HashSet<MongoId> { grenadeId };
        }
        Lock(m, "mod_magazine");

        // ---- launcher: takes only our cylinder
        var gl = Clone(GrenadeLauncher, LauncherDonor, HbLaunchers, 250000, "jug.gl").Properties;
        foreach (var slot in gl.Slots ?? Enumerable.Empty<Slot>())
        {
            slot.Id = new MongoId(Id("boss.gl.slot." + slot.Name)); slot.Parent = new MongoId(GrenadeLauncher);
            if (slot.Name == "mod_magazine")
                foreach (var f in slot.Properties?.Filters ?? Enumerable.Empty<SlotFilter>()) f.Filter = new HashSet<MongoId> { cylinderId };
        }
        gl.DefAmmo = grenadeId;
        Lock(gl, "SecondPrimaryWeapon");      // the boss carries it in his second weapon slot

        // ---- never sold: no trader offer exists; Fence must not pick them up either
        foreach (var id in new[] { GrenadeLauncher, Cylinder, Grenade }) traderConfig.Fence.Blacklist.Add(new MongoId(id));

        log.Success($"[Juggernaut] boss items: grenade launcher {GrenadeLauncher}, cylinder {Cylinder}, grenade {Grenade} " +
                    $"(damage x{dmg} -> strength {g.ExplosionStrength}, direct {g.Damage}; radius x{rad} -> {g.MinExplosionDistance}..{g.MaxExplosionDistance} m; unlootable, not sold, Fence blacklisted)");
    }

    // ------------------------------------------------------------------ bot type

    private static Dictionary<MongoId, double> Pool(params string[] ids) => ids.ToDictionary(i => new MongoId(i), _ => 1d);

    private static Dictionary<double, double> Weights(double value) => new() { [value] = 1 };

    private void RegisterBot()
    {
        var items = templates.Items;
        var killa = botTable.Types.GetValueOrDefault("bosskilla") ?? throw new InvalidOperationException("bot type bosskilla is missing");
        var kaban = botTable.Types.GetValueOrDefault("bossboar");
        var cfg = JuggernautSettings.Config;
        var t = cloner.Clone(killa) ?? throw new InvalidOperationException("could not clone bosskilla");
        var lmg = items.ContainsKey(new MongoId(Pkp)) ? Pkp : Pkm;
        var warnings = new List<string>();

        // ---- equipment pools and chances (every slot key of Killa's template must stay)
        var chances = t.BotChances.EquipmentChances;
        var eq = t.BotInventory.Equipment;
        foreach (var slot in eq.Keys.ToList())
        {
            var keep = slot is EquipmentSlots.Pockets or EquipmentSlots.Scabbard or EquipmentSlots.SecuredContainer;   // Killa's own
            if (!keep) eq[slot] = new Dictionary<MongoId, double>();
            if (!keep) chances[slot.ToString()] = 0;
        }
        eq[EquipmentSlots.ArmorVest] = Pool(JuggernautItems.Suit);
        eq[EquipmentSlots.Headwear] = Pool(JuggernautItems.Helmet);
        // Big Pipe convention (the client gives the boss Big Pipe's brain and weapon selector): LMG first, launcher second
        eq[EquipmentSlots.FirstPrimaryWeapon] = Pool(lmg);
        eq[EquipmentSlots.SecondPrimaryWeapon] = Pool(GrenadeLauncher);
        foreach (var s in new[] { "ArmorVest", "Headwear", "FirstPrimaryWeapon", "SecondPrimaryWeapon", "Pockets" }) chances[s] = 100;
        foreach (var s in new[] { "Holster", "TacticalVest", "Backpack", "Earpiece", "Eyewear", "FaceCover", "ArmBand" }) chances[s] = 0;
        if (!eq.TryGetValue(EquipmentSlots.Pockets, out var pockets) || pockets.Count == 0)
        {
            eq[EquipmentSlots.Pockets] = Pool("5af99e9186f7747c447120b8");   // large pockets: 1x2 power cells must fit
            warnings.Add("bosskilla has no pockets pool, using Killa's large pockets");
        }

        // ---- mods: built-in suit/helmet parts, launcher and cylinder, LMG tree from Kaban
        var mods = new Dictionary<MongoId, Dictionary<string, HashSet<MongoId>>>();
        var modChances = t.BotChances.EquipmentModsChances = new Dictionary<string, double>();
        void Built(string tpl)
        {
            var d = mods[new MongoId(tpl)] = new Dictionary<string, HashSet<MongoId>>();
            foreach (var slot in items[new MongoId(tpl)].Properties.Slots ?? Enumerable.Empty<Slot>())
            {
                var f = slot.Properties?.Filters?.FirstOrDefault();
                var part = f?.Plate ?? f?.Filter?.FirstOrDefault();
                if (part == null) { warnings.Add($"{tpl} slot {slot.Name} has no filter"); continue; }
                d[slot.Name] = new HashSet<MongoId> { part.Value };
                modChances[slot.Name.ToLowerInvariant()] = 100;
            }
        }
        Built(JuggernautItems.Suit);
        Built(JuggernautItems.Helmet);
        mods[new MongoId(GrenadeLauncher)] = new Dictionary<string, HashSet<MongoId>>
        {
            ["mod_magazine"] = new() { new MongoId(Cylinder) }, ["mod_pistol_grip"] = new() { new MongoId(GlGrip) },
            ["mod_stock"] = new() { new MongoId(GlStock) }, ["mod_scope"] = new() { new MongoId(GlSight) },
        };
        mods[new MongoId(Cylinder)] = Enumerable.Range(0, 6).ToDictionary(i => $"camora_{i:000}", _ => new HashSet<MongoId> { new MongoId(Grenade) });

        var lmgTree = 0;
        if (kaban?.BotInventory?.Mods != null)
        {
            var queue = new Queue<MongoId>(); queue.Enqueue(new MongoId(lmg));
            while (queue.Count > 0)
            {
                var tpl = queue.Dequeue();
                if (mods.ContainsKey(tpl) || !kaban.BotInventory.Mods.TryGetValue(tpl, out var pool)) continue;
                mods[tpl] = pool.ToDictionary(kv => kv.Key, kv => new HashSet<MongoId>(kv.Value));
                lmgTree++;
                foreach (var child in pool.Values.SelectMany(v => v)) queue.Enqueue(child);
            }
        }
        if (lmgTree == 0) warnings.Add($"no mod pool for {lmg} in bossboar: the LMG will fall back to its default preset");
        t.BotInventory.Mods = mods;

        // required slots without a pool would never be generated ("lacks a mod slot pool")
        foreach (var (tpl, pool) in mods)
            foreach (var slot in items.GetValueOrDefault(tpl)?.Properties?.Slots ?? Enumerable.Empty<Slot>())
                if (slot.Required == true && !pool.ContainsKey(slot.Name))
                    warnings.Add($"{items[tpl].Name} ({tpl}): required slot {slot.Name} has no pool");

        // weapon mod chances: Kaban's values, our launcher and the LMG parts always
        t.BotChances.WeaponModsChances = kaban?.BotChances?.WeaponModsChances != null
            ? new Dictionary<string, double>(kaban.BotChances.WeaponModsChances) : new Dictionary<string, double>();
        foreach (var s in new[] { "mod_magazine", "mod_pistol_grip", "mod_pistolgrip", "mod_stock", "mod_scope", "mod_barrel", "mod_handguard", "mod_bipod", "mod_sight_rear" })
            t.BotChances.WeaponModsChances[s] = 100;

        // ---- ammo
        var ammo = new Dictionary<string, Dictionary<MongoId, double>> { [Caliber40] = Pool(Grenade) };
        if (kaban?.BotInventory?.Ammo != null && kaban.BotInventory.Ammo.TryGetValue(Caliber762, out var lmgAmmo) && lmgAmmo.Count > 0)
            ammo[Caliber762] = new Dictionary<MongoId, double>(lmgAmmo);
        else warnings.Add($"no {Caliber762} ammo pool in bossboar");
        t.BotInventory.Ammo = ammo;

        // ---- loot: exactly two power cells in the pockets, nothing else
        t.BotInventory.Items = new ItemPools
        {
            Backpack = new(), Pockets = Pool(JuggernautItems.Cell), SecuredContainer = new(), SpecialLoot = new(), TacticalVest = new()
        };
        var gen = t.BotGeneration.Items;
        foreach (var d in new[] { gen.Grenades, gen.Healing, gen.Drugs, gen.Food, gen.Drink, gen.Currency, gen.Stims, gen.BackpackLoot, gen.VestLoot,
                     gen.Magazines, gen.SpecialItems, gen.LooseLoot })
            if (d != null) { d.Weights = Weights(0); d.Whitelist = null; }
        gen.PocketLoot.Weights = Weights(2);
        gen.PocketLoot.Whitelist = null;

        // ---- name, health
        t.FirstNames = new List<string> { "Juggernaut" };
        t.LastNames = new List<string>();
        _baseHealth = cloner.Clone(t.BotHealth.BodyParts.First());

        // ---- difficulty: no followers, hostile to everyone
        var enemies = KillerRoles.Select(r => Enum.Parse<WildSpawnType>(r)).ToList();
        foreach (var d in t.BotDifficulty.Values)
        {
            d.Boss.GluharFollowersSecurity = 0; d.Boss.GluharFollowersAssault = 0; d.Boss.GluharFollowersScout = 0;
            d.Boss.GluharFollowersSnipe = 0; d.Boss.GluharFollowersToReinforsments = 0;
            d.Mind.EnemyBotTypes = new List<WildSpawnType>(enemies);
            d.Mind.WarnBotTypes = new List<WildSpawnType>();
            d.Mind.DefaultBearBehaviour = BotGlobalsMindSettings.EWarnBehaviour.AlwaysEnemies;
            d.Mind.DefaultUsecBehaviour = BotGlobalsMindSettings.EWarnBehaviour.AlwaysEnemies;
            d.Mind.DefaultSavageBehaviour = BotGlobalsMindSettings.EWarnBehaviour.AlwaysEnemies;
        }

        botTable.Types[BotKey] = t;
        botConfig.PresetBatch[BossName] = 1;          // one bot per request, not the default 10
        ApplyHealth();

        // ---- self-check: every id the template names must exist
        var missing = new List<string>();
        void Need(string what, MongoId tpl) { if (!items.ContainsKey(tpl)) missing.Add($"{what} {tpl}"); }
        foreach (var (slot, pool) in eq) foreach (var tpl in pool.Keys) Need(slot.ToString(), tpl);
        foreach (var (tpl, pool) in mods) { Need("mods of", tpl); foreach (var child in pool.Values.SelectMany(v => v)) Need($"mod of {tpl}", child); }
        foreach (var pool in ammo.Values) foreach (var tpl in pool.Keys) Need("ammo", tpl);
        foreach (var tpl in t.BotInventory.Items.Pockets.Keys) Need("pocket loot", tpl);
        if (!botConfig.Equipment.ContainsKey(BotKey)) warnings.Add("bot.json has no equipment.bosstest entry: equipment generation will fail");
        if (botConfig.PresetBatch.GetValueOrDefault(BossName) != 1) warnings.Add("PresetBatch.bossTest was not applied");
        foreach (var w in missing.Select(m => "missing template: " + m).Concat(warnings)) log.Warning($"[Juggernaut] boss: {w}");

        log.Success($"[Juggernaut] boss: bot type '{BotKey}' registered (clone of bosskilla): equipment ArmorVest suit, Headwear helmet, " +
                    $"FirstPrimaryWeapon {(lmg == Pkp ? "PKP" : "PKM")}, SecondPrimaryWeapon grenade launcher; " +
                    $"inventory pools: mods for {mods.Count} templates ({lmgTree} from bossboar), ammo [{string.Join(", ", ammo.Keys)}], pockets 2x power cell; " +
                    $"followers 0 in {t.BotDifficulty.Count} difficulties; PresetBatch.bossTest=1; health x{JuggernautSettings.Clamp(cfg.BossHealth, 0.1, 20, 1.5)}");
    }

    /// <summary>Killa's per-part health x BossHealth; called at load and after every settings change.</summary>
    public void ApplyHealth()
    {
        try
        {
            if (_baseHealth == null || botTable.Types.GetValueOrDefault(BotKey) is not { } t) return;
            var mult = JuggernautSettings.Clamp(JuggernautSettings.Config.BossHealth, 0.1, 20, 1.5);
            MinMax<double> Scale(MinMax<double> b) { var v = Math.Max(1, Math.Round(b.Max * mult)); return new MinMax<double>(v, v); }
            t.BotHealth.BodyParts = new List<BodyPart>
            {
                new()
                {
                    Head = Scale(_baseHealth.Head), Chest = Scale(_baseHealth.Chest), Stomach = Scale(_baseHealth.Stomach),
                    LeftArm = Scale(_baseHealth.LeftArm), RightArm = Scale(_baseHealth.RightArm),
                    LeftLeg = Scale(_baseHealth.LeftLeg), RightLeg = Scale(_baseHealth.RightLeg)
                }
            };
            // test aid: an unarmed boss (melee only) can be walked around to check the battery pack hits
            var unarmed = JuggernautSettings.Config.BossTestMode && JuggernautSettings.Config.BossTestUnarmed;
            t.BotChances.EquipmentChances["FirstPrimaryWeapon"] = unarmed ? 0 : 100;
            t.BotChances.EquipmentChances["SecondPrimaryWeapon"] = unarmed ? 0 : 100;
            if (unarmed) log.Info("[Juggernaut] boss test: unarmed (no PKP, no grenade launcher)");
            log.Info($"[Juggernaut] boss health x{mult}: head {Math.Round(_baseHealth.Head.Max * mult)}, chest {Math.Round(_baseHealth.Chest.Max * mult)}, " +
                     $"legs {Math.Round(_baseHealth.LeftLeg.Max * mult)} per part");
        }
        catch (Exception ex) { log.Warning($"[Juggernaut] could not apply boss health: {ex.Message}"); }
    }
}
