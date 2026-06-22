# Q1 SFBLS 4x4x4 fast80: 0.8 mm @ 3.5 mm/min; on failure retry @ 3.0 mm/min (same mesh/dt/tuning).
param(
    [string]$Slug = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80",
    [string]$Cad = "output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_solid_merged.STEP",
    [double]$MeshSize = 0.8,
    [double]$PrimaryLoadRateMmMin = 3.5,
    [double]$FallbackLoadRateMmMin = 3.0,
    [double]$ExplicitDt = 0.0005,
    [double]$HoldFraction = 0.05,
    [int]$RestartInterval = 12,
    [double]$BulkViscosityLinear = 0.18,
    [double]$BulkViscosityQuadratic = 2.0,
    [int]$PollSeconds = 60,
    [int]$Cpus = 8,
    [int]$MemoryMB = 8192,
    [switch]$SkipPrimaryExport,
    [switch]$SkipPrimarySubmit
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

$logDir = Join-Path $Root "output\reports"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "q1_m08_lr35_then_lr30_queue.log"

function Write-QLog {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -Path $logPath -Value $line
    Write-Host $line
}

function Get-JobOutcome {
    param([Parameter(Mandatory)][string]$JobSlug)
    $jobDir = Join-Path $Root "output\jobs\$JobSlug"
    $sta = Join-Path $jobDir "$JobSlug.sta"
    $odb = Join-Path $jobDir "$JobSlug.odb"
    $lck = Join-Path $jobDir "$JobSlug.lck"
    if (Test-Path $lck) { return "running" }
    if (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb) { return "success" }
    if (Test-Path $sta) {
        $staText = Get-Content $sta -Raw -ErrorAction SilentlyContinue
        if ($staText -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return "failed" }
        if ($staText -match 'SOLUTION PROGRESS') { return "failed" }
        return "failed"
    }
    # No .sta yet (packager/submit still starting) — keep polling, do not treat as failure.
    if (Test-Path (Join-Path $jobDir "$JobSlug.inp")) { return "running" }
    return "running"
}

function Wait-JobTerminal {
    param([Parameter(Mandatory)][string]$JobSlug)
    Write-QLog "waiting terminal: $JobSlug (poll ${PollSeconds}s)"
    while ($true) {
        $outcome = Get-JobOutcome -JobSlug $JobSlug
        if ($outcome -ne "running") {
            Write-QLog "$JobSlug -> $outcome"
            return $outcome
        }
        $sta = Join-Path $Root "output\jobs\$JobSlug\$JobSlug.sta"
        if (Test-Path $sta) {
            $tail = Get-Content $sta -Tail 1 -ErrorAction SilentlyContinue
            Write-QLog "  running  $tail"
        } else {
            Write-QLog "  running  (no .sta yet)"
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

function Invoke-ExportQ1 {
    param([Parameter(Mandatory)][double]$LoadRateMmMin)
    $log = Join-Path $logDir ("q1_m08_lr{0}_export.log" -f ($LoadRateMmMin.ToString().Replace('.', 'p')))
    Write-QLog "export mesh=$MeshSize load=$LoadRateMmMin dt=$ExplicitDt -> $log"
    $args = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "1.0",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--mesh-size", $MeshSize,
        "--load-rate-mm-min", $LoadRateMmMin,
        "--explicit-dt", $ExplicitDt,
        "--hold-fraction", $HoldFraction,
        "--restart-interval", $RestartInterval,
        "--bulk-viscosity-linear", $BulkViscosityLinear,
        "--bulk-viscosity-quadratic", $BulkViscosityQuadratic,
        "--cad", $Cad
    )
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 @args 2>&1 | Tee-Object -FilePath $log
    } else {
        & python @args 2>&1 | Tee-Object -FilePath $log
    }
    if ($LASTEXITCODE -ne 0) { throw "export failed load=$LoadRateMmMin exit=$LASTEXITCODE" }
}

function Invoke-SubmitQ1 {
    param(
        [Parameter(Mandatory)][double]$LoadRateMmMin,
        [switch]$ForceRerun
    )
    $log = Join-Path $logDir ("q1_m08_lr{0}_submit.log" -f ($LoadRateMmMin.ToString().Replace('.', 'p')))
    Write-QLog "submit load=$LoadRateMmMin force=$ForceRerun -> $log"
    $submitArgs = @(
        "-NoProfile", "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-Slug", $Slug,
        "-SkipExport",
        "-Cpus", $Cpus,
        "-MemoryMB", $MemoryMB
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs 2>&1 | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
    return 0
}

Write-QLog "queue start primary=$PrimaryLoadRateMmMin fallback=$FallbackLoadRateMmMin mesh=$MeshSize"

if (-not $SkipPrimaryExport) {
    Invoke-ExportQ1 -LoadRateMmMin $PrimaryLoadRateMmMin
}
if (-not $SkipPrimarySubmit) {
    $null = Invoke-SubmitQ1 -LoadRateMmMin $PrimaryLoadRateMmMin -ForceRerun
}

$outcome = Wait-JobTerminal -JobSlug $Slug
if ($outcome -eq "success") {
    Write-QLog "Q1 completed at $PrimaryLoadRateMmMin mm/min"
    exit 0
}

Write-QLog "primary failed; fallback export+submit @ $FallbackLoadRateMmMin mm/min"
Invoke-ExportQ1 -LoadRateMmMin $FallbackLoadRateMmMin
$exit = Invoke-SubmitQ1 -LoadRateMmMin $FallbackLoadRateMmMin -ForceRerun
exit $exit
