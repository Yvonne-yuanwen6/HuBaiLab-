# Push HuBaiLab code (src/scripts/docs) to server via LAN UNC — no internet required.
param(
    [Parameter(Mandatory)][string]$ServerRoot,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Test-Path $ServerRoot)) {
    throw "Cannot reach server path: $ServerRoot`nCheck: same LAN, share enabled, UNC correct (e.g. \\192.168.1.50\HuBaiLab)"
}

$robocopyArgs = @(
    "/R:2", "/W:5", "/NFL", "/NDL", "/NJH", "/NJS"
)
if ($DryRun) { $robocopyArgs += "/L" }

function Sync-Dir {
    param([string]$Rel)
    $src = Join-Path $LocalRoot $Rel
    $dst = Join-Path $ServerRoot $Rel
    if (-not (Test-Path $src)) { return }
    Write-Host "  $Rel -> $dst" -ForegroundColor Cyan
    & robocopy $src $dst /E /MIR @robocopyArgs
}

Write-Host "=== sync_to_server ===" -ForegroundColor Cyan
Write-Host "  local:  $LocalRoot"
Write-Host "  server: $ServerRoot"
if ($DryRun) { Write-Host "  (dry run)" -ForegroundColor Yellow }
Write-Host ""

foreach ($rel in @("src", "scripts", "docs")) { Sync-Dir $rel }

foreach ($file in @("requirements.txt", "README.md")) {
    $src = Join-Path $LocalRoot $file
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $ServerRoot $file
    Write-Host "  $file" -ForegroundColor Cyan
  if ($DryRun) {
        Write-Host "    (would copy)" -ForegroundColor Gray
    } else {
        Copy-Item -Path $src -Destination $dst -Force
    }
}

Write-Host ""
Write-Host "Done. output/ was NOT synced (jobs/odb stay on server)." -ForegroundColor Green
