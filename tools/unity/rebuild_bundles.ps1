# Repackage the authored meshes in the matching Unity 2022.3.43f1 donor layouts.
param([string]$Python = 'python', [string]$CompareLayout)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$folder = 'assets/content/items/equipment/juggernaut'
$candidate = Join-Path $workspace 'art/build/candidate'
$destination = Join-Path $workspace "server/bundles/$folder"
$suit = 'item_equipment_juggernaut_suit.bundle'
$items = @($suit, 'item_equipment_juggernaut_helmet.bundle',
    'item_juggernaut_thermal_module.bundle', 'item_juggernaut_power_cell.bundle')

function Invoke-ArtPython {
    & $Python -B @args
    if ($LASTEXITCODE -ne 0) { throw "Python exited with code $LASTEXITCODE" }
}

Push-Location $workspace
try {
    New-Item -ItemType Directory -Path $candidate, $destination -Force | Out-Null
    $comparison = @()
    if ($CompareLayout) { $comparison = @('--compare-layout', $CompareLayout) }
    Invoke-ArtPython tools/unity/suit_serial_build.py --output (Join-Path $candidate $suit)
    Invoke-ArtPython tools/unity/build_rigid_bundles.py --out $candidate
    Invoke-ArtPython tools/unity/verify_art_bundles.py --bundles $candidate @comparison
    foreach ($name in $items) {
        Copy-Item -LiteralPath (Join-Path $candidate $name) -Destination (Join-Path $destination $name)
    }
    Invoke-ArtPython tools/unity/verify_art_bundles.py --bundles $destination @comparison
}
finally {
    Pop-Location
}
