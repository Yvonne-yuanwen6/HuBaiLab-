# Generate 4x4x4 SFBLS unit-cell-array STEP files (Q=0.5/1/1.5), then export + submit fast80.
param(
    [switch]$ForceRerun,
    [switch]$SkipGeneration,
    [switch]$SkipFast80,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 4,
    [double]$MeshSize = 0.8,
    [double]$Strain = 0.8
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root

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

$cases = @(
    @{ Q = 0.5; Variant = "sfbls_af2q0p5" },
    @{ Q = 1.0; Variant = "sfbls_af2q1" },
    @{ Q = 1.5; Variant = "sfbls_af2q1p5" }
)

$cadDir = Join-Path $Root "output\cad"
$ProjectPy = Get-ProjectPython
$env:PYTHONPATH = $Root

function Test-StepReady {
    param([string]$Variant)
    $step = Join-Path $cadDir "hu_bai_${Variant}_L20_4x4x4_solid_array.step"
    $manifest = Join-Path $cadDir "hu_bai_${Variant}_L20_4x4x4_array_sw_manifest.json"
    if (-not (Test-Path $step)) { return $false }
    if (-not (Test-Path $manifest)) { return $false }
    try {
        $m = Get-Content $manifest -Raw | ConvertFrom-Json
        if ([int]$m.fused_volume_count -ne 1) { return $false }
    } catch {
        return $false
    }
    return $true
}

if (-not $SkipGeneration) {
    Write-Host "=== Phase 1: 4x4x4 unit-cell-array STEP generation ===" -ForegroundColor Cyan
    foreach ($case in $cases) {
        $variant = $case.Variant
        $q = $case.Q
        if (Test-StepReady -Variant $variant) {
            Write-Host "[SKIP] $variant STEP already ready." -ForegroundColor DarkGreen
            continue
        }
        Write-Host ""
        Write-Host "========== Generate $variant (Q=$q) ==========" -ForegroundColor Yellow
        $genArgs = @(
            "scripts\run_hu_bai_bcc_unitcell_array_step_fuse.py",
            "--cells", "4",
            "--Q", "$q"
        )
        if ($ProjectPy -eq "py") {
            & py -3 @genArgs
        } else {
            & $ProjectPy @genArgs
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] STEP generation failed: $variant" -ForegroundColor Red
            exit $LASTEXITCODE
        }
        if (-not (Test-StepReady -Variant $variant)) {
            Write-Host "[ERROR] STEP not valid after generation: $variant" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host ""
    Write-Host "All 4x4x4 array STEP files ready." -ForegroundColor Green
}

if ($SkipFast80) {
    Write-Host "Skip fast80 (--SkipFast80)." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "=== Phase 2: fast80 export + Abaqus submit (80% strain) ===" -ForegroundColor Cyan
foreach ($case in $cases) {
    $variant = $case.Variant
    $q = $case.Q
    $slug = "hu_bai_${variant}_L20_4x4x4_solid_cad_f_fast80"
    try {
        $step = Get-VerifiedCadStep -Root $Root -Variant $variant -Cells 4
    } catch {
        Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "========== $slug (Q=$q) ==========" -ForegroundColor Cyan
    Write-Host "[1/2] Export INP (fast80, mesh=$MeshSize mm, strain=$([int]($Strain * 100))%) ..."

    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$q",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--strain", "$Strain",
        "--mesh-size", "$MeshSize",
        "--cad", $step
    )
    if ($ProjectPy -eq "py") {
        & py -3 @exportArgs
    } else {
        & $ProjectPy @exportArgs
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Export failed: $slug" -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "[2/2] Submit Abaqus ..."
    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $Cpus
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Submit failed: $slug" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "Pipeline complete: 3x 4x4x4 STEP + fast80 jobs." -ForegroundColor Green
