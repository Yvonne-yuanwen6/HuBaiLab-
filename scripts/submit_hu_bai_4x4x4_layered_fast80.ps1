# Wait for 4x4x4 layered STEP files, then export + submit fast80 (80% strain) sequentially.
# Matches Fig.3.3 SFBLS fast80: --case-suffix fast80 (1.2 mm, 80%, 5 mm/min, dt=5e-4).
param(
    [switch]$ForceRerun,
    [switch]$SkipWait,
    [int]$PollSeconds = 120,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 4,
    [double]$MeshSize = 1.2,
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

function Test-LayeredStepReady {
    param([string]$Variant)
    $step = Join-Path $cadDir "hu_bai_${Variant}_L20_4x4x4_solid_layered.step"
    $manifest = Join-Path $cadDir "hu_bai_${Variant}_L20_4x4x4_layered_sw_manifest.json"
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

function Test-LayeredGenerationRunning {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'py.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -match 'run_hu_bai_bcc_layered_step_fuse') {
            return $true
        }
    }
    return $false
}

function Wait-AllLayeredSteps {
    Write-Host "Waiting for 4x4x4 layered STEP files (poll every ${PollSeconds}s)..." -ForegroundColor Yellow
    while ($true) {
        $ready = @($cases | Where-Object { Test-LayeredStepReady -Variant $_.Variant })
        $pending = @($cases | Where-Object { -not (Test-LayeredStepReady -Variant $_.Variant) })
        if ($pending.Count -eq 0) {
            Write-Host "All layered STEP files ready." -ForegroundColor Green
            return
        }
        $names = ($pending | ForEach-Object { $_.Variant }) -join ", "
        $gen = if (Test-LayeredGenerationRunning) { "layered generation running" } else { "no layered generation process detected" }
        Write-Host "  Pending ($($pending.Count)): $names  [$gen]" -ForegroundColor DarkYellow
        if (-not (Test-LayeredGenerationRunning)) {
            Write-Host "[ERROR] Generation stopped but STEP files still missing: $names" -ForegroundColor Red
            exit 1
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

if (-not $SkipWait) {
    Wait-AllLayeredSteps
}

$ProjectPy = Get-ProjectPython
$env:PYTHONPATH = $Root

foreach ($case in $cases) {
    $variant = $case.Variant
    $q = $case.Q
    try {
        $step = Get-VerifiedCadStep -Root $Root -Variant $variant -Cells 4 -ExtraNames @(
            "hu_bai_${variant}_L20_4x4x4_solid_layered.step"
        )
    } catch {
        Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
    $slug = "hu_bai_${variant}_L20_4x4x4_solid_cad_f_fast80"

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
Write-Host "All 4x4x4 SFBLS layered fast80 jobs completed." -ForegroundColor Green
