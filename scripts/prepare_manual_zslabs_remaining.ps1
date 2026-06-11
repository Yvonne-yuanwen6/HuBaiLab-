# Generate 4 z-slabs per Q into output/cad/manual/ (skip Q=0.5 if already done).
param(
    [switch]$SkipQ05,
    [switch]$WaitForAbaqus
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

$cases = @(
    @{ Q = 0.5; Variant = "sfbls_af2q0p5" },
    @{ Q = 1.0; Variant = "sfbls_af2q1" },
    @{ Q = 1.5; Variant = "sfbls_af2q1p5" }
)

function Get-ProjectPython {
    $VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-Path $VenvPy) {
            try { & $VenvPy -c "import sys; sys.exit(0)" 2>$null; if ($LASTEXITCODE -eq 0) { return $VenvPy } } catch { }
        }
        return "py"
    }
    if (Test-Path $VenvPy) { return $VenvPy }
    throw "Python not found."
}

function Test-ManualReady {
    param([string]$Variant)
    $dir = Join-Path $Root "output\cad\manual\hu_bai_${Variant}_L20_4x4x4"
    if (-not (Test-Path $dir)) { return $false }
    foreach ($iz in 0..3) {
        if (-not (Test-Path (Join-Path $dir "zslab_iz$iz.step"))) { return $false }
    }
    return $true
}

function Wait-AbaqusIdle {
    Write-Host "Waiting for Abaqus job to finish (poll every 30s)..." -ForegroundColor Yellow
    while ($true) {
        $abaqus = Get-Process -Name "standard", "explicit", "ABQcaeK" -ErrorAction SilentlyContinue
        if (-not $abaqus) { break }
        Start-Sleep -Seconds 30
    }
    Write-Host "No Abaqus solver process detected." -ForegroundColor Green
}

$ProjectPy = Get-ProjectPython
function Invoke-Py {
    param([string[]]$PyArgs)
    if ($ProjectPy -eq "py") { & py -3 @PyArgs } else { & $ProjectPy @PyArgs }
}

if ($WaitForAbaqus) { Wait-AbaqusIdle }

Write-Host "=== Manual z-slabs for remaining Q values ===" -ForegroundColor Cyan
foreach ($case in $cases) {
    $q = $case.Q
    $variant = $case.Variant
    if ($SkipQ05 -and $q -eq 0.5) {
        Write-Host "[SKIP] Q=$q ($variant) --SkipQ05" -ForegroundColor DarkGreen
        continue
    }
    if (Test-ManualReady -Variant $variant) {
        Write-Host "[SKIP] Q=$q ($variant) manual folder already has 4 layers." -ForegroundColor DarkGreen
        continue
    }
    Write-Host ""
    Write-Host "========== Q=$q ($variant) ==========" -ForegroundColor Yellow
    Invoke-Py @("scripts\prepare_manual_zslabs.py", "--Q", "$q")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] Fused z-slab failed for Q=$q; trying multi-body fallback..." -ForegroundColor Yellow
        Invoke-Py @("scripts\prepare_manual_zslabs_multibody.py", "--Q", "$q")
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed Q=$q (fused + multibody)" -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }
}

Write-Host ""
Write-Host "All manual z-slab folders ready under output/cad/manual/" -ForegroundColor Green
