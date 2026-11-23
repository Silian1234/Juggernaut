# Juggernaut From TushonkaGroup · передача разработчику v4

Целевая версия — **SPT 4.1.6 / EFT 0.16.9.5.40743**, Windows, Unity **2022.3.43f1**. Физический путь каждого файла складывается из `server/bundles/` и приведённого ниже ключа. В серверном шаблоне **`_props.Prefab.path` принимает полный ключ с окончанием `.bundle`**. Внутренний адрес GameObject с расширением `.prefab` указан отдельно.

## Манифест

```json
{
  "manifest": [
    {
      "key": "assets/content/items/equipment/juggernaut/item_equipment_juggernaut_suit.bundle",
      "dependencyKeys": ["assets/commonassets/physics/physicsmaterials.bundle", "cubemaps", "shaders"]
    },
    {
      "key": "assets/content/items/equipment/juggernaut/item_equipment_juggernaut_helmet.bundle",
      "dependencyKeys": ["shaders", "cubemaps", "assets/commonassets/physics/physicsmaterials.bundle"]
    },
    {
      "key": "assets/content/items/equipment/juggernaut/item_juggernaut_thermal_module.bundle",
      "dependencyKeys": ["shaders", "cubemaps", "assets/commonassets/physics/physicsmaterials.bundle"]
    },
    {
      "key": "assets/content/items/equipment/juggernaut/item_juggernaut_power_cell.bundle",
      "dependencyKeys": ["shaders", "cubemaps", "assets/commonassets/physics/physicsmaterials.bundle"]
    }
  ]
}
```

## Префабы и LOD

| Предмет | Внутренний адрес префаба | Треугольники LOD0 / LOD1 |
|---|---|---:|
| Костюм | `assets/content/items/equipment/juggernaut/item_equipment_juggernaut_suit.prefab` | 89 853 / 49 260 |
| Шлем | `assets/content/items/equipment/juggernaut/item_equipment_juggernaut_helmet.prefab` | 16 842 / 7 052 |
| Сенсор | `assets/content/items/equipment/juggernaut/item_juggernaut_thermal_module.prefab` | 4 410 / один LOD |
| Энергоблок | `assets/content/items/equipment/juggernaut/item_juggernaut_power_cell.prefab` | 4 360 / один LOD |

### Костюм · ArmorVest

Серверный шаблон — **FORT Redut-T5 (Smog)**, `5ca21c6986f77479963115a7`. Префаб построен на работающем EXO-3 автора. Корень содержит DressItem, PreviewPivot, Loot, Skin и `mod_power_cell`. В ветке Skin сохранены EFT.Visual.SkinDress и два Diz.Skinning.Skin. У обоих LOD есть скинованный игровой меш и статическая версия для лута. Сохранены ванильные bindposes и имена костей, корень — `Root_Joint/Base HumanPelvis`. На вершину приходится от одного до четырёх нормализованных влияний.

Слот `mod_power_cell` должен принимать новый энергоблок. Точка крепления в корне префаба имеет позицию (0, 0.2695, 1.28075) м. Центр батареи в системе координат Blender — (0, 0.272, 1.285) м. Салазки следуют за Spine3, слот расположен в корне. При движении корпуса батарее может потребоваться сопровождение кости на стороне клиента. Геометрическая проверка учитывает штатный поворот вставляемого предмета.

Из штатного `assets/content/items/equipment/rig_tv110/item_equipment_rig_tv110.bundle` взяты выбранные детали разгрузки TV-110 для частной сборки: основа носителя, три подсумка с клапанами, боковой карман и поясной инструментальный подсумок. Сохранены исходные UV и карты материала. Грудная часть привязана к Spine3, поясной подсумок — к тазу. Радиостанция, проводка, броня и рама выполнены для комплекта. Геометрия и текстуры TV-110 упакованы в костюм, внешняя зависимость на бандл разгрузки отсутствует.

На костюме один EFT-материал Redut с тремя атласами 4096². В `_MainTex` учтена запечённая на геометрии окклюзия крупных участков. Мелкие детали используют повторяемые участки материала. `_BumpMap` использует tangent-space normal в DXT5nm, `_SpecMap` задаёт разницу блеска ткани, резины, металла и краски. Исходная карта окклюзии хранится в [exo_ao.png](suit/textures/exo_ao.png). При сгибе колена на 120° тяги бедра и голени перекрываются до 13,50 мм. В шести проверенных позах внешняя одежда была полностью закрыта на обоих LOD. [Скиннинг и проверка поз](suit/README.md)

### Шлем · Headwear

Серверный шаблон — **Vulkan-5 LShZ-5 (Black)**, `5ca20ee186f774799474abc2`. Забрало и подбородочная защита встроены. Для двух креплений использован донор **Tac-Kek FAST MT (Replica)**, `5ea05cf85ad9772e6624305d`. Точные имена непосредственных дочерних Transform корня:

| Transform | Предмет и фильтр | Посадка |
|---|---|---|
| `mod_nvg` | ID нового теплового сенсора | Положение, поворот и масштаб слота FAST MT |
| `mod_equipment_001` | **Ops-Core FAST RAC Headset**, `5a16b9fffcdbcb0176308b34` | Масштаб по X ×1,26, перенос назад 45 мм и вверх 5 мм, наклон 16° относительно исходной посадки |

В шаблоне предусмотрите оба слота, блокировку FaceCover и Eyewear, а для обычного слота персонажа Earpiece выставьте `BlocksEarpiece = false`. С реальным мешем примерена конкретная гарнитура RAC. У других голов и отдельно надеваемых наушников посадка может отличаться. Мягкие вставки у ушей и шеи допускают контакт с амбушюрами и микрофоном. Геометрия костюма и шлема проверялась отдельно от подсчёта мягких контактов. [Матрицы слотов](rigid/bundle_stats.json) · [Проверка гарнитуры](accessories/rac_fit_qa.json) · [Примерка сенсора и воротника](accessories/collar_qa.json)

### Сенсор · крепление шлема

Основа — **PVS-7 Wilcox Adapter**, `5c11046cd174af02a012e42b`. При клонировании уберите дочерний слот исходного адаптера. Сенсор устанавливается в `mod_nvg`. У него короткий корпус, крепёжная лапка, пассивная красная линза и обычный предметный шейдер EFT. В бандле отсутствуют компоненты и материалы ThermalVision и NightVision. Визуальный эффект реализуется клиентским кодом.

### Энергоблок · лут 1×2

Основа — **Portable Powerbank**, `5af0561e86f7745f5f3ad6ac`. Для инвентаря задайте `Width = 1`, `Height = 2`. Родной шаблон занимает 1×1. Сохранены PreviewPivot, BoxCollider и MeshCollider с геометрией в 12 треугольников. Размер корпуса около 114 × 221 × 87 мм. Узкая янтарная шкала статическая. Привязка к фактическому заряду потребует кода. [Посадка батареи](suit/v4_cell_fit.json)

## Проверка поставки

WebExtract и binary2text из Unity 2022.3.43f1 используются для повторного чтения всех четырёх файлов. Аудит сопоставляет структуру с предыдущей поставкой, проверяет цели ссылок, материал Redut, форматы карт, коллайдеры и матрицы креплений. Для поставки v4 разрешились все 570 ненулевых ссылок. Иерархии, компоненты, уровни и пороги LOD, пути и трансформы слотов совпали с v3. Положение установленных сенсора и энергоблока сверено по вершинам после преобразования вставки EFT. [Аудит поставленных файлов и SHA-256](build/bundle-audit.json)

Для v1 пользователь подтвердил загрузку и анимацию в EFT 40743. Для v4 проверены файлы и позы в Blender. Освещение в клиенте, полный набор игровых анимаций, выбрасывание предметов в рейде и динамическая посадка батареи остаются за пределами этого прогона. Редактор здесь вернул 199 при соединении с LicensingClient, использован офлайн-путь исходных префабов. [Сборка и журнал редактора](REPORT.md)



