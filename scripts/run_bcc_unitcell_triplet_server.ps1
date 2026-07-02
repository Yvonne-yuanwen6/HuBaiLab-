# Sync triplet STEPs + code, launch server V2 jobs, watch, pull CSVs/ODBs, plot overlay.
param(
    [string]$RemoteHost = $env:HU_BAI_REMOTE_HOST,
    [string]$RemoteRoot = $env:HU_BAI_REMOTE_ROOT,
    [switch]$LaunchOnly,
    [switch]$PullOnly,
    [switch]$EqArea,
    [switch]$AreaPi,
    [switch]$AreaPiCf,
    [switch]$AreaPiPt
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "remote_config.ps1")
if (-not $RemoteHost) { $RemoteHost = $HuBaiRemoteHost }
if (-not $RemoteRoot) { $RemoteRoot = $HuBaiRemoteRoot }

$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($AreaPiPt) {
    $CadLocal = Join-Path $LocalRoot "output\cad\triplet_unitcell_bcc_api_pt"
    $Slugs = @(
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_circ_api_pt_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_ellmin_api_pt_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_ellmaj_api_pt_v2_el"
    )
    $RunScript = "scripts/linux/run_bcc_unitcell_triplet_api_pt80_v2_el.sh"
    $LogName = "bcc_unitcell_triplet_api_pt80_v2_el.log"
    $PlotArgs = @("--area-pi-pt")
    $CadRemoteDir = "triplet_unitcell_bcc_api_pt"
    $PngHint = "output\reports\bcc_unitcell_triplet\triplet_api_pt80_stress_strain.png"
    $ExportHint = "py -3 scripts/export_bcc_unitcell_triplet_steps.py --target-area-pi --parallel-transport-sweep --cad-suffix pt --ocp-only --out-dir output/cad/triplet_unitcell_bcc_api_pt"
} elseif ($AreaPiCf) {
    $CadLocal = Join-Path $LocalRoot "output\cad\triplet_unitcell_bcc_api_frenet"
    $Slugs = @(
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_circ_api_cf_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_ellmin_api_cf_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_ellmaj_api_cf_v2_el"
    )
    $RunScript = "scripts/linux/run_bcc_unitcell_triplet_api_cf80_v2_el.sh"
    $LogName = "bcc_unitcell_triplet_api_cf80_v2_el.log"
    $PlotArgs = @("--area-pi-cf")
    $CadRemoteDir = "triplet_unitcell_bcc_api_frenet"
    $PngHint = "output\reports\bcc_unitcell_triplet\triplet_api_cf80_stress_strain.png"
    $ExportHint = "py -3 scripts/export_bcc_unitcell_triplet_steps.py --target-area-pi --cad-suffix cf --ocp-only --out-dir output/cad/triplet_unitcell_bcc_api_frenet"
} elseif ($AreaPi) {
    $CadLocal = Join-Path $LocalRoot "output\cad\triplet_unitcell_bcc_api"
    $Slugs = @(
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_circ_api_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_ellmin_api_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm80p_5mmin_uc_ellmaj_api_v2_el"
    )
    $RunScript = "scripts/linux/run_bcc_unitcell_triplet_api80_v2_el.sh"
    $LogName = "bcc_unitcell_triplet_api80_v2_el.log"
    $PlotArgs = @("--area-pi")
    $CadRemoteDir = "triplet_unitcell_bcc_api"
    $PngHint = "output\reports\bcc_unitcell_triplet\triplet_api80_stress_strain.png"
    $ExportHint = "py -3 scripts/export_bcc_unitcell_triplet_steps.py --target-area-pi --ocp-only --out-dir output/cad/triplet_unitcell_bcc_api"
} elseif ($EqArea) {
    $CadLocal = Join-Path $LocalRoot "output\cad\triplet_unitcell_bcc_eqarea"
    $Slugs = @(
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm70p_5mmin_uc_circ_eqa_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm70p_5mmin_uc_ellmin_eqa_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm70p_5mmin_uc_ellmaj_eqa_v2_el"
    )
    $RunScript = "scripts/linux/run_bcc_unitcell_triplet_eqarea_v2_el.sh"
    $LogName = "bcc_unitcell_triplet_eqarea_v2_el.log"
    $PlotArgs = @("--eq-area")
    $CadRemoteDir = "triplet_unitcell_bcc_eqarea"
    $PngHint = "output\reports\bcc_unitcell_triplet\triplet_v2_el_eqarea_stress_strain.png"
    $ExportHint = "py -3 scripts/export_bcc_unitcell_triplet_steps.py --equal-area --ocp-only --out-dir output/cad/triplet_unitcell_bcc_eqarea"
} else {
    $CadLocal = Join-Path $LocalRoot "output\cad\triplet_unitcell_bcc"
    $Slugs = @(
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm70p_5mmin_uc_circ_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm70p_5mmin_uc_ellmin_v2_el",
        "hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_cae_tet0p6mm70p_5mmin_uc_ellmaj_v2_el"
    )
    $RunScript = "scripts/linux/run_bcc_unitcell_triplet_v2_el.sh"
    $LogName = "bcc_unitcell_triplet_v2_el.log"
    $PlotArgs = @()
    $CadRemoteDir = "triplet_unitcell_bcc"
    $PngHint = "output\reports\bcc_unitcell_triplet\triplet_v2_el_stress_strain.png"
    $ExportHint = "py -3 scripts/export_bcc_unitcell_triplet_steps.py --ocp-only"
}

function Test-JobCompleted {
    param([string]$StaPath)
    if (-not (Test-Path $StaPath)) { return $false }
    return (Select-String -Path $StaPath -Pattern "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" -Quiet)
}

if (-not $PullOnly) {
    if (-not (Test-Path $CadLocal)) {
        Write-Host "[ERROR] Missing CAD folder: $CadLocal" -ForegroundColor Red
        Write-Host "Run: $ExportHint"
        exit 1
    }
    Write-Host "=== Sync scripts/src ===" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "sync_to_server.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== Sync triplet STEPs ===" -ForegroundColor Cyan
    ssh $RemoteHost "mkdir -p '$RemoteRoot/output/cad/$CadRemoteDir'"
    scp "$CadLocal\*.step" "${RemoteHost}:${RemoteRoot}/output/cad/$CadRemoteDir/"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== Launch server pipeline (background) ===" -ForegroundColor Cyan
    ssh $RemoteHost "cd '$RemoteRoot' && chmod +x $RunScript && nohup bash $RunScript >> output/logs/$LogName 2>&1 & echo PID=\$!"
    if ($LaunchOnly) {
        Write-Host "Launched. Watch: ssh $RemoteHost tail -f $RemoteRoot/output/logs/$LogName"
        exit 0
    }
}

Write-Host "=== Watch jobs on server ===" -ForegroundColor Cyan
$poll = 60
while ($true) {
    $done = 0
    foreach ($s in $Slugs) {
        $sta = ssh $RemoteHost "test -f '$RemoteRoot/output/jobs/$s/${s}.sta' && grep -q 'COMPLETED SUCCESSFULLY' '$RemoteRoot/output/jobs/$s/${s}.sta' && echo OK || echo NO"
        if ($sta -match "OK") { $done++ }
    }
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] completed $done / $($Slugs.Count)"
    if ($done -eq $Slugs.Count) { break }
    Start-Sleep -Seconds $poll
}

Write-Host "=== Pull post CSVs ===" -ForegroundColor Cyan
foreach ($s in $Slugs) {
    $postDir = Join-Path $LocalRoot "output\post\$s"
    New-Item -ItemType Directory -Force -Path $postDir | Out-Null
    scp "${RemoteHost}:${RemoteRoot}/output/post/${s}/${s}_stress_strain.csv" "$postDir\"
    scp "${RemoteHost}:${RemoteRoot}/output/post/${s}/${s}_stress_strain_raw.csv" "$postDir\" 2>$null
}

Write-Host "=== Pull ODB files ===" -ForegroundColor Cyan
foreach ($s in $Slugs) {
    $jobDir = Join-Path $LocalRoot "output\jobs\$s"
    New-Item -ItemType Directory -Force -Path $jobDir | Out-Null
    scp "${RemoteHost}:${RemoteRoot}/output/jobs/${s}/${s}.odb" "$jobDir\"
    scp "${RemoteHost}:${RemoteRoot}/output/export/${s}/${s}_meta.json" "$jobDir\" 2>$null
}

Write-Host "=== Plot overlay ===" -ForegroundColor Cyan
Set-Location $LocalRoot
$env:PYTHONPATH = $LocalRoot
py -3 scripts/plot_bcc_unitcell_triplet_v2_el.py @PlotArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Done." -ForegroundColor Green
Write-Host "  PNG: $PngHint"
