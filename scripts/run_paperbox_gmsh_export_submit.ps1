# Gmsh C3D4 export (local) + sync to server + submit. Server has no gmsh/pip.
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [switch]$ForceRemesh,
    [switch]$ExportOnly,
    [switch]$SubmitOnly
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Slug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_gmsh0p6mm80_5mmin_paperbox"
$Cad = Join-Path $Root "output\cad\verified\hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
$ExportDir = Join-Path $Root "output\export\$Slug"

if (-not $SubmitOnly) {
    if (-not (Test-Path $Cad)) {
        Write-Host "CAD missing locally; pulling from server ..." -ForegroundColor Yellow
        $cadDir = Split-Path $Cad -Parent
        if (-not (Test-Path $cadDir)) { New-Item -ItemType Directory -Path $cadDir -Force | Out-Null }
        scp "${RemoteHost}:${RemoteRoot}/output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step" $cadDir
    }
    if ($ForceRemesh -and (Test-Path $ExportDir)) {
        Remove-Item -Recurse -Force $ExportDir
    }
    Write-Host "=== Gmsh export (local) $Slug ===" -ForegroundColor Cyan
    py -3 scripts/run_hu_bai_bcc_solid_cad_export.py `
        --cells 4 --Q 0 --profile fast `
        --cad $Cad `
        --mesh-method tet --mesh-size 0.6 `
        --strain 0.80 --load-rate-mm-min 5 `
        --explicit-dt 0.0005 --explicit-dt-mode automatic `
        --material-model paper `
        --case-suffix gmsh0p6mm80_5mmin_paperbox
}

if ($ExportOnly) {
    Write-Host "ExportOnly; skip sync/submit." -ForegroundColor Green
    exit 0
}

Write-Host "=== Sync export -> server ===" -ForegroundColor Cyan
scp -r $ExportDir "${RemoteHost}:${RemoteRoot}/output/export/"

Write-Host "=== Submit on server (48 cpu / 256 GB) ===" -ForegroundColor Cyan
ssh $RemoteHost "cd '$RemoteRoot' && rm -rf output/jobs/$Slug && bash scripts/linux/submit_job.sh --slug $Slug --cpus 48 --memory-mb 262144"

Write-Host "Done. Slug: $Slug" -ForegroundColor Green
Write-Host "Watch: powershell -File scripts/watch_job_progress.ps1 -RemoteHost $RemoteHost -Slug $Slug -StepTimeS 768"
