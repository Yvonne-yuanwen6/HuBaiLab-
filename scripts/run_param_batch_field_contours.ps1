# Batch-export Abaqus field contour PNGs (low-RAM by default).
#
# Default: Viewer (not CAE) · 1280x960 · 1 case per run · 30s pause · skip done
# Each structure folder: 3 PNGs + 1 collage
#
#   powershell -File scripts/run_param_batch_field_contours.ps1              # 一次只导 1 案
#   powershell -File scripts/run_param_batch_field_contours.ps1 -Limit 1
#   powershell -File scripts/run_param_batch_field_contours.ps1 -Only af2q1_deq2_k1
#   powershell -File scripts/run_param_batch_field_contours.ps1 -CollageOnly
param(
    [string]$Only = "",
    [string]$Fractions = "0,0.45,0.8",
    [string]$StageTags = "start,mid,densify",
    [string]$Fields = "mises",
    [string]$Views = "zup",
    [int]$Limit = 1,
    [double]$PauseSec = 30,
    [ValidateSet("viewer", "cae")]
    [string]$Tool = "viewer",
    [int]$ImageW = 1280,
    [int]$ImageH = 960,
    [switch]$Upgrade,
    [switch]$Force,
    [switch]$DryRun,
    [switch]$CollageOnly,
    [switch]$NoCollage
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "py launcher not found; install Python or fix PATH"
}

$simCmd = "D:\Apps\SIMULIA\Commands"
if (Test-Path -LiteralPath $simCmd) {
    if ($env:Path -notlike "*$simCmd*") {
        $env:Path = "$simCmd;" + $env:Path
    }
}

$argsList = @(
    "--limit", "$Limit",
    "--pause-sec", "$PauseSec",
    "--tool", $Tool,
    "--image-w", "$ImageW",
    "--image-h", "$ImageH"
)
if ($Only) { $argsList += @("--only", $Only) }
if ($Fractions) { $argsList += @("--fractions", $Fractions) }
if ($StageTags) { $argsList += @("--stage-tags", $StageTags) }
if ($Fields) { $argsList += @("--fields", $Fields) }
if ($Views) { $argsList += @("--views", $Views) }
if ($Upgrade) { $argsList += "--upgrade" }
if ($Force) { $argsList += "--force" }
if ($DryRun) { $argsList += "--dry-run" }
if ($CollageOnly) { $argsList += "--collage-only" }
if ($NoCollage) { $argsList += "--no-collage" }

Write-Host "=== field contours (low-RAM: viewer, 1 case/run, pause ${PauseSec}s) ===" -ForegroundColor Cyan
& py -3 (Join-Path $Root "scripts\run_param_batch_field_contours.py") @argsList
exit $LASTEXITCODE
