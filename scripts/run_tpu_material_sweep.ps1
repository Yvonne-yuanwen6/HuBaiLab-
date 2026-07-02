# Sync code + Fig.2.5 data to server, then launch material-level TPU screening.
param(
    [switch]$DryRun,
    [switch]$NoLaunch,
    [string]$RemoteHost = "",
    [string]$RemoteRoot = "",
    [string]$MaxStrain = "0",
    [string]$Models = "elastic neo_hooke marlow polynomial ogden_n2 reduced_poly_n2"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "remote_config.ps1")

if ($RemoteHost) { $HuBaiRemoteHost = $RemoteHost }
if ($RemoteRoot) { $HuBaiRemoteRoot = $RemoteRoot }

$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Fig25Local = Join-Path $LocalRoot "data\hu_bai_tpu_fig25_tensile_traced.json"
$RunScript = "scripts/linux/run_tpu_material_sweep.sh"

if (-not (Test-Path $Fig25Local)) {
    throw "Missing $Fig25Local"
}

Write-Host "=== TPU material sweep: sync + launch ===" -ForegroundColor Cyan
Write-Host "  remote: ${HuBaiRemoteHost}:${HuBaiRemoteRoot}"

if ($DryRun) {
    Write-Host "[dry-run] sync_to_server.ps1"
    Write-Host "[dry-run] scp Fig.2.5 JSON"
    Write-Host "[dry-run] ssh launch $RunScript"
    exit 0
}

& (Join-Path $PSScriptRoot "sync_to_server.ps1")

Write-Host "scp Fig.2.5 data ..." -ForegroundColor Yellow
ssh $HuBaiRemoteHost "mkdir -p '$HuBaiRemoteRoot/data'"
scp $Fig25Local "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/data/hu_bai_tpu_fig25_tensile_traced.json"

ssh $HuBaiRemoteHost "chmod +x '$HuBaiRemoteRoot/$RunScript'"

if ($NoLaunch) {
    Write-Host "Sync done (-NoLaunch). Run on server:" -ForegroundColor Green
    Write-Host "  ssh $HuBaiRemoteHost"
    Write-Host "  cd $HuBaiRemoteRoot"
    Write-Host "  bash $RunScript"
    exit 0
}

$envExports = @(
    "export TPU_MAT_MAX_STRAIN='$MaxStrain'",
    "export TPU_MAT_MODELS='$Models'"
) -join "; "

$cmd = "cd '$HuBaiRemoteRoot' && $envExports && nohup bash $RunScript >> output/logs/tpu_material_sweep_launcher.log 2>&1 & echo LAUNCHED_PID=`$!"
Write-Host "Launching background sweep on server ..." -ForegroundColor Yellow
ssh $HuBaiRemoteHost $cmd

Write-Host ""
Write-Host "Tail server log:" -ForegroundColor Green
Write-Host "  ssh $HuBaiRemoteHost tail -f $HuBaiRemoteRoot/output/logs/tpu_material_sweep.log"
Write-Host ""
Write-Host "After completion, pull report:" -ForegroundColor Green
Write-Host "  scp ${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/reports/tpu_material_fit/tpu_material_fit_report.json output/reports/tpu_material_fit/"
Write-Host "  scp ${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/reports/tpu_material_fit/tpu_material_fit_overlay.png output/reports/tpu_material_fit/"
