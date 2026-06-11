# Wait for SFBLS Q=1.0 4x4x4 fast80 (4 cpu, 10 mm/min), then:
#   - Q1 success -> Q05 (6 cpu), Q15 (4 cpu), BCC (4 cpu) @ 10 mm/min unchanged
#   - Q1 failure -> re-run Q1 @ 8 mm/min, then Q05/Q15/BCC all @ 8 mm/min
param(
    [string]$WaitSlug = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80",
    [int]$PollSeconds = 60,
    [int]$MemoryMB = 8192,
    [switch]$ForceRerun,
    [double]$LoadRateMmMin = 10,
    [double]$FallbackLoadRateMmMin = 8
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
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

function Get-JobOutcome {
    param(
        [Parameter(Mandatory)][string]$Slug
    )
    $jobDir = Join-Path $Root "output\jobs\$Slug"
    $sta = Join-Path $jobDir "$Slug.sta"
    $odb = Join-Path $jobDir "$Slug.odb"
    if (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb) { return "success" }
    if ((Test-Path $sta) -and -not (Test-Path (Join-Path $jobDir "$Slug.lck"))) {
        $staText = Get-Content $sta -Raw -ErrorAction SilentlyContinue
        if ($staText -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return "failed" }
        if ($staText -notmatch 'SOLUTION PROGRESS') { return "failed" }
    }
    return "running"
}

function Wait-JobOutcome {
    param(
        [Parameter(Mandatory)][string]$Slug,
        [ValidateSet("success", "failed")][string]$Want = "success"
    )
    Write-Host "=== Waiting for $Slug -> $Want (poll ${PollSeconds}s) ===" -ForegroundColor Yellow
    while ($true) {
        $outcome = Get-JobOutcome -Slug $Slug
        if ($outcome -eq $Want) {
            Write-Host "  $Slug -> $outcome" -ForegroundColor Green
            return $outcome
        }
        if ($Want -eq "success" -and $outcome -eq "failed") {
            throw "$Slug failed (see output\jobs\$Slug\$Slug.sta)"
        }
        if ($Want -eq "failed" -and $outcome -eq "success") {
            return "success"
        }
        $sta = Join-Path $Root "output\jobs\$Slug\$Slug.sta"
        if (Test-Path $sta) {
            $tail = Get-Content $sta -Tail 1 -ErrorAction SilentlyContinue
            Write-Host "  $(Get-Date -Format 'HH:mm:ss')  $tail" -ForegroundColor DarkYellow
        } else {
            Write-Host "  $(Get-Date -Format 'HH:mm:ss')  waiting for .sta ..." -ForegroundColor DarkYellow
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

function Invoke-Fast80Case {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][double]$Q,
        [Parameter(Mandatory)][string]$Variant,
        [Parameter(Mandatory)][int]$CaseCpus,
        [Parameter(Mandatory)][double]$RateMmMin,
        [string[]]$CadExtraNames = @()
    )
    $cad = Get-VerifiedCadStep -Root $Root -Variant $Variant -Cells 4 -ExtraNames $CadExtraNames
    $slug = "hu_bai_${Variant}_L20_4x4x4_solid_cad_f_fast80"
    $ProjectPy = Get-ProjectPython

    Write-Host ""
    Write-Host "========== $Label : $slug (cpus=$CaseCpus, $RateMmMin mm/min) ==========" -ForegroundColor Cyan
    Write-Host "  CAD: $cad"

    Write-Host "[1/2] Export INP (fast80, mesh=0.8 mm, strain=80%, $RateMmMin mm/min) ..."
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$Q",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--strain", "0.8",
        "--mesh-size", "0.8",
        "--load-rate-mm-min", "$RateMmMin",
        "--cad", $cad
    )
    if ($ProjectPy -eq "py") {
        & py -3 @exportArgs
    } else {
        & $ProjectPy @exportArgs
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Export failed: $slug"
    }

    Write-Host "[2/2] Submit Abaqus (cpus=$CaseCpus) ..."
    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $CaseCpus
    )
    $submitArgs += "-ForceRerun"
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Submit failed: $slug"
    }
}

$rateForRest = $LoadRateMmMin
try {
    Wait-JobOutcome -Slug $WaitSlug -Want "success" | Out-Null
    Write-Host ""
    Write-Host "Q=1.0 completed at $LoadRateMmMin mm/min; downstream jobs unchanged." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "Q=1.0 failed at $LoadRateMmMin mm/min -> retry Q1 and queue at $FallbackLoadRateMmMin mm/min" -ForegroundColor Red
    $rateForRest = $FallbackLoadRateMmMin
    Invoke-Fast80Case -Label "SFBLS Q=1.0 retry" -Q 1.0 -Variant "sfbls_af2q1" -CaseCpus 4 `
        -RateMmMin $FallbackLoadRateMmMin
    Wait-JobOutcome -Slug $WaitSlug -Want "success" | Out-Null
    Write-Host ""
    Write-Host "Q=1.0 completed at $FallbackLoadRateMmMin mm/min; downstream jobs use $FallbackLoadRateMmMin mm/min." -ForegroundColor Green
}

$cases = @(
    @{
        Label = "SFBLS Q=0.5"
        Q = 0.5
        Variant = "sfbls_af2q0p5"
        Cpus = 6
        CadExtraNames = @()
    },
    @{
        Label = "SFBLS Q=1.5"
        Q = 1.5
        Variant = "sfbls_af2q1p5"
        Cpus = 4
        CadExtraNames = @()
    },
    @{
        Label = "BCC Q=0"
        Q = 0
        Variant = "bcc_af2q0"
        Cpus = 4
        CadExtraNames = @(
            "hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step",
            "hu_bai_bcc_af2q0_L20_4x4x4_solid_array.STEP"
        )
    }
)
foreach ($case in $cases) {
    Invoke-Fast80Case -Label $case.Label -Q $case.Q -Variant $case.Variant `
        -CaseCpus $case.Cpus -RateMmMin $rateForRest -CadExtraNames $case.CadExtraNames
}

Write-Host ""
Write-Host "Queue completed (load rate for downstream: $rateForRest mm/min)." -ForegroundColor Green
