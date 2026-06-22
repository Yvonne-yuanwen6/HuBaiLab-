# Route A: after BCC 4x4x4 fast80 completes, serially run SFBLS Q=1 -> Q=0.5 -> Q=1.5.
# Uses fast80 defaults (1.2 mm, 80% strain, 5 mm/min, dt=5e-4); override via params below.
param(
    [string]$WaitSlug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80",
    [int]$PollSeconds = 60,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 8,
    [double]$MeshSize = 1.2,
    [double]$Strain = 0.8,
    [double]$LoadRateMmMin = 5.0,
    [double]$ExplicitDt = 0.0005,
    [double]$HoldFraction = 0.05,
    [switch]$SkipWaitBcc,
    [switch]$ForceRerun,
    [switch]$ForceReexport,
    [switch]$ContinueOnFailure
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

$logDir = Join-Path $Root "output\reports"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "sfbls_serial_fast80_m12_after_bcc.log"

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

function Write-QLog {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -Path $logPath -Value $line
    Write-Host $line
}

function Get-TerminalOutcome {
    param([Parameter(Mandatory)][string]$Slug)
    $jobDir = Join-Path $Root "output\jobs\$Slug"
    $sta = Join-Path $jobDir "$Slug.sta"
    $odb = Join-Path $jobDir "$Slug.odb"
    $lck = Join-Path $jobDir "$Slug.lck"
    if (Test-Path $lck) { return "running" }
    if (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb) { return "success" }
    if (Test-Path $sta) { return "failed" }
    return "missing"
}

function Wait-JobTerminal {
    param([Parameter(Mandatory)][string]$Slug)
    Write-QLog "waiting terminal: $Slug (poll ${PollSeconds}s)"
    while ($true) {
        $outcome = Get-TerminalOutcome -Slug $Slug
        if ($outcome -ne "running") {
            Write-QLog "$Slug -> $outcome"
            return $outcome
        }
        $sta = Join-Path $Root "output\jobs\$Slug\$Slug.sta"
        if (Test-Path $sta) {
            $tail = Get-Content $sta -Tail 1 -ErrorAction SilentlyContinue
            Write-QLog "  running  $tail"
        } else {
            Write-QLog "  running  (no .sta)"
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

function Test-RouteAExportReady {
    param([Parameter(Mandatory)][string]$Slug)
    $manifestPath = Join-Path $Root "output\export\$Slug\case_manifest.json"
    $inpPath = Join-Path $Root "output\export\$Slug\$Slug.inp"
    if (-not ((Test-Path $manifestPath) -and (Test-Path $inpPath))) { return $false }
    $m = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $meshOk = [math]::Abs([double]$m.mesh.mesh_size_mm - $MeshSize) -lt 0.01
    $rateOk = [math]::Abs([double]$m.loading.load_rate_mm_min - $LoadRateMmMin) -lt 0.01
    $dtOk = [math]::Abs([double]$m.loading.explicit_dt - $ExplicitDt) -lt 1e-9
    $strainOk = [math]::Abs([double]$m.loading.target_engineering_strain - $Strain) -lt 0.001
    return ($meshOk -and $rateOk -and $dtOk -and $strainOk)
}

function Invoke-RouteAExport {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][double]$Q,
        [Parameter(Mandatory)][string]$Variant,
        [Parameter(Mandatory)][string]$Slug
    )
    $cad = Get-VerifiedCadStep -Root $Root -Variant $Variant -Cells 4
    $ProjectPy = Get-ProjectPython
    Write-QLog "export $Label -> $Slug (mesh=${MeshSize}mm cad=$cad)"
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$Q",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--strain", "$Strain",
        "--mesh-size", "$MeshSize",
        "--load-rate-mm-min", "$LoadRateMmMin",
        "--explicit-dt", "$ExplicitDt",
        "--hold-fraction", "$HoldFraction",
        "--cad", $cad
    )
    if ($ProjectPy -eq "py") {
        & py -3 @exportArgs
    } else {
        & $ProjectPy @exportArgs
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Export failed: $Slug (exit $LASTEXITCODE)"
    }
}

function Invoke-RouteASubmit {
    param(
        [Parameter(Mandatory)][string]$Slug
    )
    $submitScript = Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"
    $submitArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $submitScript,
        "-SkipExport",
        "-Slug", $Slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $Cpus
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    Write-QLog "submit $Slug cpus=$Cpus memory=${MemoryMB}MB"
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Submit failed: $Slug (exit $LASTEXITCODE)"
    }
}

function Test-SlugPreviouslyFailed {
    param([Parameter(Mandatory)][string]$Slug)
    $failedRoot = Join-Path $Root "output\failed\$Slug"
    if (-not (Test-Path $failedRoot)) { return $false }
    $archives = Get-ChildItem -Path $failedRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'not_completed|deformation_speed|abaqus' }
    return ($archives.Count -gt 0)
}

function Invoke-RouteACase {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][double]$Q,
        [Parameter(Mandatory)][string]$Variant
    )
    $slug = "hu_bai_${Variant}_L20_4x4x4_solid_cad_f_fast80"
    Write-QLog "===== $Label ($slug) ====="

    if (-not $ForceRerun) {
        $outcome = Get-TerminalOutcome -Slug $slug
        $csv = Join-Path $Root "output\post\$slug\${slug}_stress_strain.csv"
        if ($outcome -eq "success" -and (Test-Path $csv)) {
            Write-QLog "skip $slug (already completed + CSV)"
            return
        }
        if ($outcome -eq "failed" -or (Test-SlugPreviouslyFailed -Slug $slug)) {
            Write-QLog "skip $slug (previous failure; partial curve in output/failed/$slug)"
            return
        }
    }

    $needExport = $ForceReexport -or -not (Test-RouteAExportReady -Slug $slug)
    if ($needExport) {
        Invoke-RouteAExport -Label $Label -Q $Q -Variant $Variant -Slug $slug
    } else {
        Write-QLog "reuse export $slug"
    }

    try {
        Invoke-RouteASubmit -Slug $slug
    } catch {
        if (-not $ContinueOnFailure) { throw }
        Write-QLog "WARN submit failed $slug : $($_.Exception.Message)"
    }
    $final = Get-TerminalOutcome -Slug $slug
    if ($final -eq "success") {
        Write-QLog "$slug done"
    } elseif ($ContinueOnFailure) {
        Write-QLog "WARN $slug ended with $final (continuing queue)"
    } else {
        throw "$slug ended with $final"
    }
}

Write-QLog "queue start route=A wait=$WaitSlug mesh=${MeshSize}mm rate=${LoadRateMmMin}mm/min dt=$ExplicitDt"

if (-not $SkipWaitBcc) {
    $bccState = Get-TerminalOutcome -Slug $WaitSlug
    if ($bccState -eq "running") {
        $null = Wait-JobTerminal -Slug $WaitSlug
    } elseif ($bccState -eq "success") {
        Write-QLog "BCC already completed"
    } else {
        throw "BCC $WaitSlug not runnable (state=$bccState); fix before SFBLS queue"
    }

    $bccCsv = Join-Path $Root "output\post\$WaitSlug\${WaitSlug}_stress_strain.csv"
    if (-not (Test-Path $bccCsv)) {
        Write-QLog "BCC post missing; run extract-only submit"
        $submitScript = Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $submitScript `
            -SkipExport -Slug $WaitSlug -Cpus $Cpus -MemoryMB $MemoryMB
        if ($LASTEXITCODE -ne 0) {
            Write-QLog "WARN BCC post-only submit exit=$LASTEXITCODE"
        }
    }
}

$downstream = @(
    @{ Label = "SFBLS Q=1.0"; Q = 1.0; Variant = "sfbls_af2q1" },
    @{ Label = "SFBLS Q=0.5"; Q = 0.5; Variant = "sfbls_af2q0p5" },
    @{ Label = "SFBLS Q=1.5"; Q = 1.5; Variant = "sfbls_af2q1p5" }
)

foreach ($case in $downstream) {
    Invoke-RouteACase -Label $case.Label -Q $case.Q -Variant $case.Variant
}

Write-QLog "queue complete: BCC + Q1 + Q0.5 + Q1.5 (route A 1.2mm serial)"
Write-Host ""
Write-Host "All route-A jobs finished. Log: $logPath" -ForegroundColor Green
