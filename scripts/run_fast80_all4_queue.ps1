# Serial fast80 queue: gmsh C3D4 tet mesh, 80% strain, 4x4x4, 8 cpu.
#
#   powershell -File scripts/run_fast80_all4_queue.ps1
#   powershell -File scripts/run_fast80_all4_queue.ps1 -SkipCompleted -CaseKeys q1,q05,q15

param(
    [string[]]$CaseKeys = @("bcc", "q05", "q1", "q15"),
    [int]$PollSeconds = 60,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 8,
    [double]$LoadRateMmMin = 5,
    [switch]$ForceRerun,
    [switch]$SkipCompleted
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
    param([Parameter(Mandatory)][string]$Slug)
    $jobDir = Join-Path $Root "output\jobs\$Slug"
    $sta = Join-Path $jobDir "$Slug.sta"
    $odb = Join-Path $jobDir "$Slug.odb"
    if (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb) { return "success" }
    if ((Test-Path $sta) -and -not (Test-Path (Join-Path $jobDir "$Slug.lck"))) {
        $staText = Get-Content $sta -Raw -ErrorAction SilentlyContinue
        if ($staText -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return "failed" }
        if ($staText -match 'deformation speed/wave speed') { return "failed" }
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
        [switch]$SkipIfSuccess
    )
    $cad = Get-VerifiedCadStep -Root $Root -Variant $Variant -Cells 4
    $slug = "hu_bai_${Variant}_L20_4x4x4_solid_cad_f_fast80"
    $ProjectPy = Get-ProjectPython

    if ($SkipIfSuccess -and (Get-JobOutcome -Slug $slug) -eq 'success') {
        Write-Host ""
        Write-Host "========== $Label : $slug already COMPLETED -> skip ==========" -ForegroundColor Green
        return
    }

    Write-Host ""
    Write-Host "========== $Label : $slug (cpus=$CaseCpus, C3D4 tet 1.2mm, ${LoadRateMmMin}mm/min, 80% strain) ==========" -ForegroundColor Cyan
    Write-Host "  CAD: $cad"

    Write-Host "[1/2] Export INP (gmsh C3D4 fast80) ..."
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$Q",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--load-rate-mm-min", "$LoadRateMmMin",
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
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) {
        if ((Get-JobOutcome -Slug $slug) -eq 'success') {
            Write-Host "  [WARN] Submit exit code $LASTEXITCODE but job COMPLETED; continuing queue." -ForegroundColor Yellow
        } else {
            throw "Submit failed: $slug"
        }
    }

    Wait-JobOutcome -Slug $slug -Want "success" | Out-Null
}

$queueLog = Join-Path $Root "output\reports\fast80_all4_queue.log"
$logDir = Split-Path $queueLog -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
function Write-QLog([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Add-Content -Path $queueLog -Value $line -Encoding UTF8
    Write-Host $line
}

$skipDone = [bool]$SkipCompleted
$allCases = @(
    @{ Key = "bcc"; Label = "BCC Q=0"; Q = 0; Variant = "bcc_af2q0"; SkipIfSuccess = $skipDone },
    @{ Key = "q05"; Label = "SFBLS Q=0.5"; Q = 0.5; Variant = "sfbls_af2q0p5"; SkipIfSuccess = $skipDone },
    @{ Key = "q1"; Label = "SFBLS Q=1.0"; Q = 1.0; Variant = "sfbls_af2q1"; SkipIfSuccess = $skipDone },
    @{ Key = "q15"; Label = "SFBLS Q=1.5"; Q = 1.5; Variant = "sfbls_af2q1p5"; SkipIfSuccess = $skipDone }
)
$keys = @(
    foreach ($raw in $CaseKeys) {
        foreach ($part in ($raw -split ',')) {
            $k = $part.Trim().ToLower()
            if ($k) { $k }
        }
    }
)
$cases = @($allCases | Where-Object { $keys -contains $_.Key })
if ($cases.Count -eq 0) {
    throw "No cases matched -CaseKeys '$($CaseKeys -join ',')' (use bcc q05 q1 q15)"
}

Write-QLog "queue start: fast80 C3D4 cases=$($keys -join ',') skipCompleted=$SkipCompleted rate=${LoadRateMmMin}mm/min"

foreach ($case in $cases) {
    Invoke-Fast80Case -Label ([string]$case.Label) -Q ([double]$case.Q) -Variant ([string]$case.Variant) `
        -CaseCpus $Cpus -SkipIfSuccess:([bool]$case.SkipIfSuccess)
}

Write-QLog "queue completed: $($keys -join ' -> ')"
Write-Host ""
Write-Host "Queue completed." -ForegroundColor Green
