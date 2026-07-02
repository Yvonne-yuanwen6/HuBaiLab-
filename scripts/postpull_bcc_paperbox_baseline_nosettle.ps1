# Pull BCC baseline + BCC nosettle (partial), extract, plot compare.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = "D:\HuBaiLab"
)

$ErrorActionPreference = "Stop"
$Slugs = @(
    @{ Label = "baseline (ContactSettle)"; Slug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox" },
    @{ Label = "nosettle (~86% interrupted)"; Slug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle" }
)

Set-Location $Local

foreach ($item in $Slugs) {
    $s = $item.Slug
    $jobDir = Join-Path $Local "output\jobs\$s"
    $exportDir = Join-Path $Local "output\export\$s"
    $postDir = Join-Path $Local "output\post\$s"
    $odb = Join-Path $jobDir "$s.odb"
    $meta = Join-Path $exportDir "${s}_meta.json"
    $upOdb = Join-Path $jobDir "up.odb"
    $csv = Join-Path $postDir "${s}_stress_strain.csv"
    $raw = Join-Path $postDir "${s}_stress_strain_raw.csv"
    $yield = Join-Path $postDir "${s}_yield.json"

    New-Item -ItemType Directory -Force -Path $jobDir, $exportDir, $postDir | Out-Null

    Write-Host "scp $($item.Label) ..." -ForegroundColor Cyan
    scp "${Server}:${Remote}/output/jobs/${s}/${s}.odb" $jobDir

    if (-not (Test-Path $meta)) {
        scp "${Server}:${Remote}/output/export/${s}/${s}_meta.json" $exportDir
    }

    Remove-Item $upOdb -Force -ErrorAction SilentlyContinue
    Write-Host "upgrade+extract $s" -ForegroundColor Cyan
    Push-Location $jobDir
    abaqus upgrade job=up odb="$s.odb"
    Pop-Location

    abaqus python scripts\extract_stress_strain_from_odb.py `
        --odb $upOdb --meta $meta --csv $csv --raw-csv $raw --yield-json $yield `
        --force-mode paper --curve-method paper
    if ($LASTEXITCODE -ne 0) {
        abaqus python scripts\extract_stress_strain_from_odb.py `
            --odb $upOdb --meta $meta --csv $csv --raw-csv $raw --yield-json $yield `
            --force-mode fixed_bottom_ref --curve-method paper
    }
}

py -3 scripts\plot_bcc_paperbox_baseline_vs_nosettle.py
Write-Host "Done. PNG: output\reports\bcc_paperbox_baseline_vs_nosettle.png" -ForegroundColor Green
