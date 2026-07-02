# Pull snap-through sweep ODBs, extract curves, analyze + plot.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = "D:\HuBaiLab"
)

$ErrorActionPreference = "Stop"
$Suffixes = @(
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4_nohold"
)
$Tags = @("sfbls_af2q0p5")  # Q=0.5 only

Set-Location $Local

foreach ($tag in $Tags) {
    foreach ($suffix in $Suffixes) {
        $s = "hu_bai_${tag}_L20_4x4x4_solid_cad_f_$suffix"
        $jobDir = Join-Path $Local "output\jobs\$s"
        $exportDir = Join-Path $Local "output\export\$s"
        $postDir = Join-Path $Local "output\post\$s"
        $odb = Join-Path $jobDir "$s.odb"
        $meta = Join-Path $exportDir "${s}_meta.json"
        $upOdb = Join-Path $jobDir "up.odb"
        $csv = Join-Path $postDir "${s}_stress_strain.csv"
        $raw = Join-Path $postDir "${s}_stress_strain_raw.csv"
        $yield = Join-Path $postDir "${s}_yield.json"

        $remoteSta = "${Server}:${Remote}/output/jobs/${s}/${s}.sta"
        $staLocal = Join-Path $jobDir "$s.sta"
        New-Item -ItemType Directory -Force -Path $jobDir, $exportDir, $postDir | Out-Null
        scp $remoteSta $staLocal 2>$null
        if (-not (Select-String -Path $staLocal -Pattern "COMPLETED SUCCESSFULLY" -Quiet -ErrorAction SilentlyContinue)) {
            Write-Host "[SKIP] $s not completed" -ForegroundColor DarkYellow
            continue
        }

        Write-Host "scp $s.odb ..." -ForegroundColor Cyan
        scp "${Server}:${Remote}/output/jobs/${s}/${s}.odb" $jobDir
        if (-not (Test-Path $meta)) {
            scp "${Server}:${Remote}/output/export/${s}/${s}_meta.json" $exportDir
        }

        Remove-Item $upOdb -Force -ErrorAction SilentlyContinue
        Push-Location $jobDir
        abaqus upgrade job=up odb="$s.odb"
        Pop-Location
        abaqus python scripts\extract_stress_strain_from_odb.py `
            --odb $upOdb --meta $meta --csv $csv --raw-csv $raw --yield-json $yield `
            --force-mode paper --curve-method paper
    }
}

py -3 scripts\analyze_paperbox_snapthrough.py --write-summary output\logs\paperbox_snapthrough_summary.json
py -3 scripts\plot_paperbox_snapthrough_compare.py
Write-Host "Done." -ForegroundColor Green
