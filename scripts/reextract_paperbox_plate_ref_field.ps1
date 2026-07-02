# Re-extract paper_box CAE tet curves from ODB field frames (dense PLATE_REF RF3/U3).
# Skips scp if local upgraded ODB already exists.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = "D:\HuBaiLab",
    [switch]$ForcePull
)

$ErrorActionPreference = "Stop"
$Suffix = "cae_tet0p6mm80_5mmin_paperbox"
$Slugs = @(
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_$Suffix"
)

Set-Location $Local

foreach ($s in $Slugs) {
    $jobDir = Join-Path $Local "output\jobs\$s"
    $exportDir = Join-Path $Local "output\export\$s"
    $postDir = Join-Path $Local "output\post\$s"
    $odb = Join-Path $jobDir "$s.odb"
    $meta = Join-Path $exportDir "${s}_meta.json"
    $upOdb = Join-Path $jobDir "up.odb"
    $csv = Join-Path $postDir "${s}_stress_strain_field.csv"
    $raw = Join-Path $postDir "${s}_stress_strain_field_raw.csv"

    New-Item -ItemType Directory -Force -Path $jobDir, $exportDir, $postDir | Out-Null

    if ($ForcePull -or -not (Test-Path $odb)) {
        Write-Host "scp $s.odb ..." -ForegroundColor Cyan
        scp "${Server}:${Remote}/output/jobs/${s}/${s}.odb" $jobDir
    } else {
        Write-Host "reuse local $s.odb" -ForegroundColor DarkGray
    }

    if (-not (Test-Path $meta)) {
        Write-Host "scp meta $s ..." -ForegroundColor Cyan
        scp "${Server}:${Remote}/output/export/${s}/${s}_meta.json" $exportDir
    }

    if (-not (Test-Path $upOdb) -or $ForcePull) {
        Remove-Item $upOdb -Force -ErrorAction SilentlyContinue
        Write-Host "upgrade $s" -ForegroundColor Cyan
        Push-Location $jobDir
        abaqus upgrade job=up odb="$s.odb"
        Pop-Location
    }

    Write-Host "field extract $s" -ForegroundColor Cyan
    abaqus python scripts\extract_stress_strain_from_odb.py `
        --odb $upOdb --meta $meta --csv $csv --raw-csv $raw `
        --force-mode plate_ref_field --curve-method paper
    if ($LASTEXITCODE -ne 0) { throw "extract failed: $s" }
}

py -3 scripts\plot_paperbox_cae_tet0p6mm80_5mmin_stress_strain.py
Write-Host "Done. PNG: output\reports\paperbox_cae_tet0p6mm80_5mmin_stress_strain_compare.png" -ForegroundColor Green
