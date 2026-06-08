# Prepare 4 z-slabs in output/cad/manual/ for SolidWorks merge,
# then run mesh + Abaqus pilot on iz0 while waiting for manual full merge.
param(
    [double]$Q = 0.5,
    [switch]$SkipGenerate,
    [switch]$SkipMeshPilot,
    [switch]$ForceRerun,
    [int]$MemoryMB = 6144,
    [int]$Cpus = 4,
    [double]$MeshSize = 1.42,
    [double]$Strain = 0.15
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
function Get-ProjectPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-Path $VenvPy) {
            try { & $VenvPy -c "import sys; sys.exit(0)" 2>$null; if ($LASTEXITCODE -eq 0) { return $VenvPy } } catch { }
        }
        return "py"
    }
    if (Test-Path $VenvPy) { return $VenvPy }
    throw "Python not found."
}

$ProjectPy = Get-ProjectPython
function Invoke-Py {
    param([string[]]$PyArgs)
    if ($ProjectPy -eq "py") { & py -3 @PyArgs } else { & $ProjectPy @PyArgs }
}

Write-Host "=== Phase 1: 4 z-slabs -> output/cad/manual/ ===" -ForegroundColor Cyan
$prepArgs = @("scripts\prepare_manual_zslabs.py", "--Q", "$Q")
if ($SkipGenerate) { $prepArgs += "--skip-generate" }
Invoke-Py $prepArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$variant = switch ([math]::Round($Q, 2)) {
    0.5 { "sfbls_af2q0p5" }
    1.0 { "sfbls_af2q1" }
    1.5 { "sfbls_af2q1p5" }
    default { "sfbls_af2q0p5" }
}
$manualDir = Join-Path $Root "output\cad\manual\hu_bai_${variant}_L20_4x4x4"
$iz0 = Join-Path $manualDir "zslab_iz0.step"
$manifest = Join-Path $manualDir "manual_sw_manifest.json"

Write-Host ""
Write-Host "Manual folder: $manualDir" -ForegroundColor Green
Write-Host "  -> Open zslab_iz0..iz3.step in SolidWorks, Combine -> Add" -ForegroundColor Yellow
Write-Host "  -> Save merged solid as *_solid_merged.step or .x_t in same folder" -ForegroundColor Yellow

if ($SkipMeshPilot) {
    Write-Host "Skip mesh pilot (--SkipMeshPilot)." -ForegroundColor Yellow
    exit 0
}

if (-not (Test-Path $iz0)) {
    Write-Host "[ERROR] Missing pilot CAD: $iz0" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Phase 2: mesh + compression pilot (iz0 single layer) ===" -ForegroundColor Cyan
Write-Host "  Uses iz0 only to validate gmsh mesh + Abaqus while you merge full block in SW." -ForegroundColor DarkGray

$slug = "hu_bai_${variant}_L20_4x4x1_solid_cad_p_manual_iz0"
$exportArgs = @(
    "scripts\run_hu_bai_bcc_solid_cad_export.py",
    "--cells", "4",
    "--nz", "1",
    "--Q", "$Q",
    "--stroke", "pilot",
    "--case-suffix", "manual_iz0",
    "--strain", "$Strain",
    "--mesh-size", "$MeshSize",
    "--cad", $iz0
)
Invoke-Py $exportArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$submitArgs = @(
    "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
    "-SkipExport",
    "-Slug", $slug,
    "-Stroke", "pilot",
    "-Cells", "4",
    "-MemoryMB", $MemoryMB,
    "-Cpus", $Cpus
)
if ($ForceRerun) { $submitArgs += "-ForceRerun" }
& powershell @submitArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Pilot done. After SW merge, re-run full export:" -ForegroundColor Green
Write-Host "  py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 4 --Q $Q --profile fast --cad <merged.step>" -ForegroundColor Cyan
