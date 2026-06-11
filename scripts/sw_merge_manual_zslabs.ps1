# Wait for Abaqus (optional), then merge 4 manual z-slabs in SolidWorks.
param(
    [double]$Q = 0.5,
    [string]$ManualDir = "",
    [switch]$AllQ,
    [switch]$WaitForAbaqus,
    [switch]$Visible,
    [switch]$AllowStartSw
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

function Wait-AbaqusIdle {
    Write-Host "Waiting for Abaqus to finish ..." -ForegroundColor Yellow
    while ($true) {
        $abaqus = Get-Process -Name "standard", "explicit", "ABQcaeK" -ErrorAction SilentlyContinue
        if (-not $abaqus) { break }
        Start-Sleep -Seconds 30
    }
}

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

if ($WaitForAbaqus) { Wait-AbaqusIdle }

$ProjectPy = Get-ProjectPython
function Invoke-Py {
    param([string[]]$PyArgs)
    if ($ProjectPy -eq "py") { & py -3 @PyArgs } else { & $ProjectPy @PyArgs }
}

$qs = if ($AllQ) { @(0.5, 1.0, 1.5) } else { @($Q) }

Write-Host "=== SolidWorks merge manual z-slabs ===" -ForegroundColor Cyan
Write-Host "Ensure SolidWorks is running before continuing." -ForegroundColor Yellow

foreach ($q in $qs) {
    Write-Host ""
    Write-Host "---------- Q=$q ----------" -ForegroundColor Yellow
    $args = @("scripts\sw_merge_manual_zslabs.py", "--Q", "$q")
    if ($ManualDir) { $args += @("--manual-dir", $ManualDir) }
    if ($Visible) { $args += "--visible" }
    if ($AllowStartSw) { $args += "--allow-start-sw" }
    Invoke-Py $args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "SolidWorks merge complete." -ForegroundColor Green
