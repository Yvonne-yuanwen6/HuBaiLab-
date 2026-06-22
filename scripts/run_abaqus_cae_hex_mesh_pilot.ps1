# Pilot Abaqus/CAE built-in C3D8R mesh on verified STEP (BCC default).
param(
    [string]$StepPath = "",
    [double]$SeedMm = 1.2,
    [string]$OutInp = "",
    [string]$PartName = "LATTICE",
    [ValidateSet("hex", "tet")]
    [string]$MeshMode = "hex",
    [switch]$MergeSolids
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root

if (-not $StepPath) {
    $StepPath = Join-Path $Root "output\cad\verified\hu_bai_bcc_af2q0_L20_4x4x4_solid_merged.step"
}
if (-not $OutInp) {
    $inpName = if ($MeshMode -eq "tet") { "bcc_cae_tet_mesh.inp" } else { "bcc_cae_hex_mesh.inp" }
    $OutInp = Join-Path $Root "output\export\cae_hex_pilot\$inpName"
}

if (-not (Test-Path $StepPath)) {
    Write-Host "[ERROR] STEP not found: $StepPath" -ForegroundColor Red
    exit 1
}

$outDir = Split-Path $OutInp -Parent
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$env:HU_BAI_ROOT = $Root
$env:HU_BAI_STEP = $StepPath
$env:HU_BAI_SEED = "$SeedMm"
$env:HU_BAI_OUT = $OutInp
$env:HU_BAI_PART_NAME = $PartName
$env:HU_BAI_MESH_MODE = $MeshMode
if ($MergeSolids) { $env:HU_BAI_MERGE_SOLIDS = "1" } else { Remove-Item Env:HU_BAI_MERGE_SOLIDS -ErrorAction SilentlyContinue }

Write-Host "=== Abaqus CAE built-in mesh pilot ===" -ForegroundColor Cyan
Write-Host "  STEP: $StepPath"
Write-Host "  part: $PartName (mergeSolids=$($MergeSolids.IsPresent))"
Write-Host "  mode: $MeshMode (seed ${SeedMm} mm)"
Write-Host "  OUT:  $OutInp"

& abaqus cae noGUI=scripts\abaqus_cae_hex_mesh_pilot.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path $OutInp)) {
    Write-Host "[ERROR] INP not created: $OutInp" -ForegroundColor Red
    exit 1
}
$inpText = Get-Content $OutInp -Raw
if ($inpText -notmatch '(?m)^\*Node\b') {
    Write-Host "[ERROR] INP has no *Node section (mesh empty): $OutInp" -ForegroundColor Red
    exit 1
}

Write-Host "OK: CAE mesh INP -> $OutInp" -ForegroundColor Green
