# Q=1.5: manual z-slabs -> gmsh merge -> fast80 (memory-friendly fallback).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== Q=1.5 manual z-slabs ===" -ForegroundColor Cyan
py -3 scripts/prepare_manual_zslabs.py --Q 1.5
if ($LASTEXITCODE -ne 0) {
    Write-Host "Trying multibody fallback..." -ForegroundColor Yellow
    py -3 scripts/prepare_manual_zslabs_multibody.py --Q 1.5
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "=== Q=1.5 gmsh merge ===" -ForegroundColor Cyan
py -3 scripts/merge_manual_zslabs_gmsh.py --Q 1.5
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Q=1.5 fast80 ===" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "run_manual_merge_fast80.ps1") -Q "1.5" -SkipMerge
