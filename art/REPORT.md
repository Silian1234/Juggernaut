# Juggernaut From TushonkaGroup · v4

Четыре игровых предмета для EFT 0.16.9.5.40743. Основу комплекта составляют тёмные трёхсекционные наплечники и набедренные пластины, разгрузка с подсумками TV-110, наружная рама ног и съёмная батарея в спинной кассете. На шлеме — дымчатая Т-образная щель, боковые узлы и короткая антенна. Сохранились адреса и крепления предыдущей поставки. [Передача разработчику](BUNDLES.md)

[Концепт A](design/v4-concept-a.png) · [Концепт B](design/v4-concept-b.png) · [Выбор дизайна](design/V4.md) · [Сравнение с референсами и ЧВК](design/v4-review.png) · [Ракурсы](previews/) · [Иконки](icons/) · [Баннер](banner.png) · [Сцена костюма](suit/suit.blend) · [Сцена шлема и модулей](accessories/accessories.blend)

## Что изменилось после просмотра на персонаже

В первом рендере между шлемом и раздельными блоками воротника была видна длинная гладкая полоса. У шлема удлинили скуловые панели и добавили складки нижнего уплотнения, у костюма появился V-образный горжет с вырезом под микрофон RAC. Перешили видимые участки строп, затемнили крепёж и кожухи цилиндров. На животе добавили перекрывающиеся секции, на бедре и голени — крышки с рёбрами, на предплечьях — утопленные жалюзи. На крупном плане проверили блики на наплечниках: для широких поверхностей исправили нормали, сохранив острый обод. Концевики шлангов получили болтовые гнёзда с проверенным контактом от гайки до плечевой пластины. [Наплечник до](build/v4-upper/crown-before.png) и [после](build/v4-upper/crown-after.png). В финальных ракурсах под бронёй находятся голова USEC Эрик, куртка Crye AC и брюки Commando. Рядом стоит тот же ЧВК в той же позе и масштабе. [Посадка и ограничения](suit/README.md)

## Пересборка

Для пересборки из готовых экспортов выполните из корня проекта:

```powershell
.\tools\unity\rebuild_bundles.ps1 -CompareLayout art/build/v3-reference/bundle-audit.json
```

Полный цикл использует Blender 5.3, Python с NumPy, Pillow и lz4, локальный EXO-3 и штатные ассеты EFT 40743. Первый скрипт извлекает выбранные компоненты TV-110 вместе с исходными UV и тремя текстурами. Художественная геометрия и материалы собираются следующими командами:

```powershell
$b = 'C:/Program Files/Blender Foundation/Blender 5.3/blender.exe'
$frame = 'C:/SPT/_fullbody_armor/exoskeleton/gpt/exo_t3a.blend'
python -B tools/model/v4_tactical_extract.py
& $b --factory-startup -b $frame --python-exit-code 1 --python tools/model/suit_build.py
& $b --factory-startup -b --python-exit-code 1 --python tools/model/accessories.py
python -B tools/model/v2_rigid_surface.py --art art/accessories
& $b --factory-startup -b --python-exit-code 1 --python tools/model/accessories.py
& $b --factory-startup -b art/suit/suit.blend --python-exit-code 1 --python tools/model/export_suit.py -- art/suit/suit_unity.json
Copy-Item art/suit/suit_unity.json art/unity_project/Assets/Juggernaut/Suit/exo_unity.json
Copy-Item art/suit/textures/exo_dif.png,art/suit/textures/exo_nrm.png,art/suit/textures/exo_gloss.png art/unity_project/Assets/Juggernaut/Suit/
.\tools\unity\rebuild_bundles.ps1 -CompareLayout art/build/v3-reference/bundle-audit.json
```

Для повторения студийных ракурсов, иконок и баннера:

```powershell
$pmc = 'art/build/v3-presentation/pmc-assets'
$renders = 'art/build/v4-presentation/shipping'
$scratch = Join-Path $renders 'banner-input'
python -B tools/model/extract_pmc_reference.py --out $pmc
& $b --factory-startup -b art/suit/suit.blend -t 8 --python-exit-code 1 --python tools/model/render_art.py -- --pmc-assets $pmc --destination $renders --scratch $scratch
python -B tools/model/render_banner.py --scratch $scratch --output (Join-Path $renders 'banner.png')
python -B tools/model/render_contacts.py $renders --details
Copy-Item (Join-Path $renders 'previews/*.png') art/previews/
Copy-Item (Join-Path $renders 'icons/*.png') art/icons/
Copy-Item (Join-Path $renders 'banner.png') art/banner.png
Copy-Item (Join-Path $renders 'design-review.png') art/design/v4-review.png
```

Проект редактора находится в `art/unity_project`. Его входы лежат в `Assets/Juggernaut/Suit`. Для редакторской сборки служат `JuggernautSuitBuild.Build` и `tools/unity/patch_editor_suit.py`, для редактирования аксессуаров — меню `Juggernaut → Import editable accessories`. [Исходники Blender](../tools/model/) · [Инструменты Unity](../tools/unity/). В этой среде Unity 2022.3.43f1 завершил запуск с кодом 199 из-за отказа соединения с LicensingClient. Бандлы собраны офлайн из сериализованных префабов той же версии. Игровой прогон v4 остаётся открытым. [Журнал Editor](build/v4-technical/unity-2022.3.43f1-probe.log) · [Аудит поставки](build/bundle-audit.json)



