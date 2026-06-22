# Wait for SFBLS Q=1.0 4x4x4 fast80, then BCC -> Q05 -> Q15 (serial).
#   - Q1 success @ LoadRateMmMin -> downstream same rate
#   - Q1 failure -> retry Q1 @ FallbackLoadRateMmMin, downstream uses fallback rate
# Default: 8 cpu, 5 mm/min (8 mm/min failed ~62% strain on Q=1.0).
# Low-memory resume uses ReducedCpus (6) via resume_fast80_queue_after_low_memory.ps1.
param(
    [string]$WaitSlug = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80",
    [int]$PollSeconds = 60,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 8,
    [int]$ReducedCpus = 6,
    [int]$ReducedMemoryMB = 6144,
    [switch]$ForceRerun,
    [switch]$StartMemoryWatch,
    [double]$LoadRateMmMin = 5,
    [double]$FallbackLoadRateMmMin = 5
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

    Write-Host "[1/2] Export INP (fast80, mesh=1.2 mm, strain=80%, $RateMmMin mm/min, dt=5e-4) ..."
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$Q",
        "--profile", "fast",
        "--case-suffix", "fast80",
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

function Start-JobMemoryWatch {
    param(
        [Parameter(Mandatory)][string]$Slug,
        [int]$WatchResumeCpus = 0
    )
    $resumeCpus = if ($WatchResumeCpus -gt 0) { $WatchResumeCpus } else { $ReducedCpus }
    $resumeMem = if ($Cpus -le $ReducedCpus) { $ReducedMemoryMB } else { $MemoryMB }
    $autoResume = ($Cpus -gt $ReducedCpus)
    $jobDir = Join-Path $Root "output\jobs\$Slug"
    $watchScript = Join-Path $ScriptDir "watch_abaqus_solve_memory.ps1"
    Write-Host "  Memory watch: pause if free RAM < 1.5GB; resume queue at ${resumeCpus} cpus if triggered" -ForegroundColor DarkCyan
    $watchArgs = @(
        '-NoProfile', '-File', $watchScript,
        '-JobName', $Slug,
        '-JobDir', $jobDir,
        '-Slug', $Slug,
        '-MinFreeGB', '1.5',
        '-WarnFreeGB', '2.5',
        '-IntervalSec', '30',
        '-ResumeCpus', "$resumeCpus",
        '-ResumeMemoryMB', "$resumeMem",
        '-LoadRateMmMin', "$LoadRateMmMin"
    )
    if ($autoResume) { $watchArgs += '-AutoResumeOnLowMemory' }
    Start-Process powershell -ArgumentList $watchArgs -WindowStyle Hidden
}

$rateForRest = $LoadRateMmMin
$jobDirWait = Join-Path $Root "output\jobs\$WaitSlug"
$lckWait = Join-Path $jobDirWait "$WaitSlug.lck"
$initialOutcome = Get-JobOutcome -Slug $WaitSlug
$jobActive = (Test-Path $lckWait) -or (Test-AbaqusJobProcessRunning -JobName $WaitSlug -JobDir $jobDirWait)
if ($initialOutcome -ne 'success' -and -not $jobActive) {
    Write-Host ""
    Write-Host "Q=1.0 not running/completed -> start fresh ($LoadRateMmMin mm/min, cpus=$Cpus)" -ForegroundColor Cyan
    if ($StartMemoryWatch -or $Cpus -gt $ReducedCpus) {
        Start-JobMemoryWatch -Slug $WaitSlug
    }
    Invoke-Fast80Case -Label "SFBLS Q=1.0" -Q 1.0 -Variant "sfbls_af2q1" -CaseCpus $Cpus `
        -RateMmMin $LoadRateMmMin
} elseif ($jobActive -and ($StartMemoryWatch -or $Cpus -gt $ReducedCpus)) {
    Start-JobMemoryWatch -Slug $WaitSlug
}
try {
    Wait-JobOutcome -Slug $WaitSlug -Want "success" | Out-Null
    Write-Host ""
    Write-Host "Q=1.0 completed at $LoadRateMmMin mm/min; downstream jobs unchanged." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "Q=1.0 failed at $LoadRateMmMin mm/min -> retry Q1 and queue at $FallbackLoadRateMmMin mm/min" -ForegroundColor Red
    $rateForRest = $FallbackLoadRateMmMin
    Invoke-Fast80Case -Label "SFBLS Q=1.0 retry" -Q 1.0 -Variant "sfbls_af2q1" -CaseCpus $Cpus `
        -RateMmMin $FallbackLoadRateMmMin
    Wait-JobOutcome -Slug $WaitSlug -Want "success" | Out-Null
    Write-Host ""
    Write-Host "Q=1.0 completed at $FallbackLoadRateMmMin mm/min; downstream jobs use $FallbackLoadRateMmMin mm/min." -ForegroundColor Green
}

$cases = @(
    @{
        Label = "BCC Q=0"
        Q = 0
        Variant = "bcc_af2q0"
        Cpus = $Cpus
        CadExtraNames = @(
            "hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step",
            "hu_bai_bcc_af2q0_L20_4x4x4_solid_array.STEP"
        )
    },
    @{
        Label = "SFBLS Q=0.5"
        Q = 0.5
        Variant = "sfbls_af2q0p5"
        Cpus = $Cpus
        CadExtraNames = @()
    },
    @{
        Label = "SFBLS Q=1.5"
        Q = 1.5
        Variant = "sfbls_af2q1p5"
        Cpus = $Cpus
        CadExtraNames = @()
    }
)
foreach ($case in $cases) {
    $caseSlug = "hu_bai_$($case.Variant)_L20_4x4x4_solid_cad_f_fast80"
    if ($Cpus -gt $ReducedCpus) {
        Start-JobMemoryWatch -Slug $caseSlug
    }
    Invoke-Fast80Case -Label $case.Label -Q $case.Q -Variant $case.Variant `
        -CaseCpus $case.Cpus -RateMmMin $rateForRest -CadExtraNames $case.CadExtraNames
}

Write-Host ""
Write-Host "Queue completed (load rate for downstream: $rateForRest mm/min)." -ForegroundColor Green
