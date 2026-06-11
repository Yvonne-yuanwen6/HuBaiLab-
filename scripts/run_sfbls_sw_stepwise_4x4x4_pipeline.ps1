# Hu & Bai 4x4x4 — verified SolidWorks stepwise pipeline (BCC Q=0, SFBLS Q=0.5/1/1.5).
#
# Proven route: 16-body iz0 compound -> SW fuse 1 body -> Z-copy ->
# 4-body compound -> SW fuse 1 body -> verified merged -> fast80.
#
# Usage (BCC):
#   powershell -File scripts/run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q 0 -Stage 1
#   # SW: Combine 16 bodies -> save verified/zslab_iz0_4x4_sw_fused_bcc_af2q0.STEP
#   powershell -File scripts/run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q 0 -Stage 3
#   # SW: Combine 4 bodies -> save verified/hu_bai_bcc_af2q0_L20_4x4x4_solid_merged.STEP
#
# Usage (SFBLS Q=1.5 example):
# Stages:
#   1  Generate unit-cell seed + optional QA + 16-body iz0 compound
#   2  Print SW instructions only (merge 16 -> 1)
#   3  Z-stack copy from SW-fused layer + 4-body compound
#   4  Print SW instructions only (merge 4 -> 1)
#   5  fast80 INP export + Abaqus submit (requires verified merged STEP)
#   all  Run 1; auto-run 3 if fused layer exists; print remaining manual steps

param(
    [Parameter(Mandatory = $false)]
    [double]$Q = 1.0,
    [ValidateSet("1", "2", "3", "4", "5", "all")]
    [string]$Stage = "1",
    [switch]$SkipStepwiseQa,
    [string]$SwFusedLayer = "",
    [switch]$SkipFast80,
    [switch]$ForceRerun,
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
$env:PYTHONPATH = $Root
$env:PYTHONIOENCODING = "utf-8"

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
function Get-ProjectPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-Path $VenvPy) {
            try {
                & $VenvPy -c "import sys; sys.exit(0)" 2>$null
                if ($LASTEXITCODE -eq 0) { return $VenvPy }
            } catch { }
        }
        return "py"
    }
    if (Test-Path $VenvPy) { return $VenvPy }
    throw "Python not found."
}

function Get-LatticeVariantName([double]$qVal) {
    switch ([math]::Round($qVal, 2)) {
        0 { return "bcc_af2q0" }
        0.5 { return "sfbls_af2q0p5" }
        1.0 { return "sfbls_af2q1" }
        1.5 { return "sfbls_af2q1p5" }
        default { throw "Unsupported Q=$qVal (use 0, 0.5, 1.0, or 1.5)" }
    }
}

function Get-QTag([double]$qVal) {
    if ([math]::Abs($qVal) -lt 1e-9) { return "0" }
    return ([string]$qVal).Replace(".", "p")
}

function Invoke-ProjectPy {
    param([Parameter(Mandatory)][string[]]$PyArgs)
    if ($ProjectPy -eq "py") {
        & py -3 @PyArgs
    } else {
        & $ProjectPy @PyArgs
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $($PyArgs -join ' ')"
    }
}

function Resolve-SwFusedLayerPath {
    param(
        [string]$Override,
        [string]$VerifiedDir,
        [string]$Variant
    )
    if ($Override) {
        $p = $Override
        if (-not (Test-Path $p)) { throw "SW fused layer not found: $p" }
        return (Resolve-Path $p).Path
    }
    $candidates = @(
        (Join-Path $VerifiedDir "zslab_iz0_4x4_sw_fused_${Variant}.STEP"),
        (Join-Path $VerifiedDir "zslab_iz0_4x4_sw_fused_${Variant}.step"),
        (Join-Path $VerifiedDir "zslab_iz0_4x4_sw_fused.STEP"),
        (Join-Path $VerifiedDir "zslab_iz0_4x4_sw_fused.step")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return (Resolve-Path $c).Path }
    }
    return $null
}

function Write-Stage2Instructions {
    param(
        [string]$CompoundStep,
        [string]$SuggestedFusedPath
    )
    Write-Host ""
    Write-Host "=== Stage 2: SolidWorks (manual) ===" -ForegroundColor Yellow
    Write-Host "  1. Open: $CompoundStep"
    Write-Host "  2. Combine -> Add (16 bodies -> 1 solid)"
    Write-Host "  3. Save As: $SuggestedFusedPath"
    Write-Host ""
    Write-Host "Then run:" -ForegroundColor Cyan
    Write-Host "  powershell -File scripts/run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q $Q -Stage 3"
}

function Write-Stage4Instructions {
    param(
        [string]$CompoundStep,
        [string]$SuggestedMergedPath
    )
    Write-Host ""
    Write-Host "=== Stage 4: SolidWorks (manual) ===" -ForegroundColor Yellow
    Write-Host "  1. Open: $CompoundStep"
    Write-Host "  2. Combine -> Add (4 bodies -> 1 solid)"
    Write-Host "  3. Save As: $SuggestedMergedPath"
    Write-Host ""
    Write-Host "Then run:" -ForegroundColor Cyan
    Write-Host "  powershell -File scripts/run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q $Q -Stage 5"
}

function Invoke-Stage1 {
    param(
        [double]$qVal,
        [string]$StepwiseDir,
        [bool]$WithQa
    )
    Write-Host "=== Stage 1: unit-cell seed + iz0 16-body compound (Q=$qVal) ===" -ForegroundColor Cyan

    Invoke-ProjectPy @(
        "scripts/export_unitcell_seed_check.py",
        "--Q", "$qVal"
    )

    if ($WithQa) {
        Write-Host ""
        Write-Host "--- Stepwise QA: pair + line ---" -ForegroundColor DarkGray
        Invoke-ProjectPy @("scripts/export_pair_fuse_check.py", "--Q", "$qVal")
        Invoke-ProjectPy @(
            "scripts/export_line_from_unitcell_seed.py",
            "--Q", "$qVal",
            "--axis", "y",
            "--count", "4",
            "--compound"
        )
        Invoke-ProjectPy @(
            "scripts/export_line_from_unitcell_seed.py",
            "--Q", "$qVal",
            "--axis", "x",
            "--count", "4",
            "--compound"
        )
    }

    Invoke-ProjectPy @(
        "scripts/export_zslab_layer_from_column.py",
        "--Q", "$qVal",
        "--compound",
        "--out-dir", $StepwiseDir
    )

    $compound = Join-Path $StepwiseDir "zslab_iz0_4x4_compound_from_seed.step"
    if (-not (Test-Path $compound)) {
        throw "Expected compound STEP missing: $compound"
    }
    Write-Host ""
    Write-Host "Stage 1 OK: $compound" -ForegroundColor Green
    return $compound
}

function Invoke-Stage3 {
    param(
        [string]$FusedLayer,
        [string]$ZstackDir
    )
    Write-Host "=== Stage 3: Z-stack from SW-fused layer ===" -ForegroundColor Cyan
    Write-Host "  Seed: $FusedLayer"
    Write-Host "  Out:  $ZstackDir"

    Invoke-ProjectPy @(
        "scripts/export_zstack_from_sw_fused_layer.py",
        "--seed", $FusedLayer,
        "--out-dir", $ZstackDir
    )

    $compound = Join-Path $ZstackDir "zstack_4x4x4_sw_fused_4layer_compound.step"
    if (-not (Test-Path $compound)) {
        throw "Expected 4-layer compound missing: $compound"
    }
    Write-Host ""
    Write-Host "Stage 3 OK: $compound" -ForegroundColor Green
    return $compound
}

function Invoke-Stage5 {
    param(
        [double]$qVal,
        [string]$Variant,
        [string]$CadStep
    )
    Write-Host "=== Stage 5: fast80 export + Abaqus ===" -ForegroundColor Cyan
    Write-Host "  CAD: $CadStep"

    $slug = "hu_bai_${Variant}_L20_4x4x4_solid_cad_f_fast80"

    Invoke-ProjectPy @(
        "scripts/run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$qVal",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--strain", "$Strain",
        "--mesh-size", "$MeshSize",
        "--cad", $CadStep
    )

    if ($SkipFast80) {
        Write-Host "Skip Abaqus submit (--SkipFast80)." -ForegroundColor Yellow
        return
    }

    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $Cpus
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) { throw "Abaqus submit failed (exit $LASTEXITCODE)" }
}

# --- main ---

$ProjectPy = Get-ProjectPython
$Variant = Get-LatticeVariantName -qVal $Q
$QTag = Get-QTag -qVal $Q
$SlugBase = "hu_bai_${Variant}_L20_4x4x4"
$VerifiedDir = Get-VerifiedCadDir -Root $Root
$StepwiseDir = Join-Path $Root "output\cad\_stepwise_q${QTag}"
$ZstackDir = Join-Path $StepwiseDir "sw_zstack"
$Compound16 = Join-Path $StepwiseDir "zslab_iz0_4x4_compound_from_seed.step"
$Compound4 = Join-Path $ZstackDir "zstack_4x4x4_sw_fused_4layer_compound.step"
$SuggestedFused = Join-Path $VerifiedDir "zslab_iz0_4x4_sw_fused_${Variant}.STEP"
$SuggestedMerged = Join-Path $VerifiedDir "${SlugBase}_solid_merged.STEP"

Write-Host ""
Write-Host "SW stepwise pipeline  Q=$Q  variant=$Variant  stage=$Stage" -ForegroundColor White
Write-Host "  stepwise: $StepwiseDir"
Write-Host "  verified: $VerifiedDir"

$stagesToRun = @()
switch ($Stage) {
    "all" { $stagesToRun = @("1", "2", "3", "4", "5") }
    default { $stagesToRun = @($Stage) }
}

foreach ($s in $stagesToRun) {
    switch ($s) {
        "1" {
            $null = Invoke-Stage1 -qVal $Q -StepwiseDir $StepwiseDir -WithQa:(-not $SkipStepwiseQa)
        }
        "2" {
            if (-not (Test-Path $Compound16)) {
                throw "Run Stage 1 first. Missing: $Compound16"
            }
            Write-Stage2Instructions -CompoundStep $Compound16 -SuggestedFusedPath $SuggestedFused
        }
        "3" {
            $fused = Resolve-SwFusedLayerPath -Override $SwFusedLayer -VerifiedDir $VerifiedDir -Variant $Variant
            if (-not $fused) {
                Write-Stage2Instructions -CompoundStep $Compound16 -SuggestedFusedPath $SuggestedFused
                throw "SW-fused iz0 layer not found under verified/. Complete Stage 2 first."
            }
            $null = Invoke-Stage3 -FusedLayer $fused -ZstackDir $ZstackDir
        }
        "4" {
            if (-not (Test-Path $Compound4)) {
                throw "Run Stage 3 first. Missing: $Compound4"
            }
            Write-Stage4Instructions -CompoundStep $Compound4 -SuggestedMergedPath $SuggestedMerged
        }
        "5" {
            $cad = Get-VerifiedCadStep -Root $Root -Variant $Variant -Cells 4
            Invoke-Stage5 -qVal $Q -Variant $Variant -CadStep $cad
        }
    }
}

if ($Stage -eq "all") {
    $fused = Resolve-SwFusedLayerPath -Override $SwFusedLayer -VerifiedDir $VerifiedDir -Variant $Variant
    if ($fused -and -not (Test-Path $Compound4)) {
        Write-Host ""
        Write-Host "Auto-continuing to Stage 3 (fused layer found)..." -ForegroundColor DarkGreen
        $null = Invoke-Stage3 -FusedLayer $fused -ZstackDir $ZstackDir
    }
    if (Test-Path $Compound16) {
        if (-not $fused) {
            Write-Stage2Instructions -CompoundStep $Compound16 -SuggestedFusedPath $SuggestedFused
        } elseif (Test-Path $Compound4) {
            if (-not (Test-VerifiedCadStepReady -Root $Root -Variant $Variant -Cells 4)) {
                Write-Stage4Instructions -CompoundStep $Compound4 -SuggestedMergedPath $SuggestedMerged
            } else {
                Write-Host ""
                Write-Host "Verified merged STEP already present. Run Stage 5 for fast80:" -ForegroundColor Green
                Write-Host "  powershell -File scripts/run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q $Q -Stage 5"
            }
        }
    }
}

Write-Host ""
Write-Host "Done (stage=$Stage)." -ForegroundColor Green
