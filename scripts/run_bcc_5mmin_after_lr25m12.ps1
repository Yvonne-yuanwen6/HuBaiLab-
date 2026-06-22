# Wait for BCC fast80_lr25m12 (25 mm/min, 1.2 mm) to finish, then run canonical
# 5 mm/min / 1.2 mm / dt=5e-4 BCC fast80 (~4 h @ 8 cpus), success or failure.
param(
    [string]$WaitSlug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80_lr25m12",
    [string]$NextSlug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80",
    [int]$PollSeconds = 60,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 8,
    [switch]$SkipSubmit25
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

$logDir = Join-Path $Root "output\reports"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "bcc_lr25_then_5mmin_queue.log"

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
    if (Test-Path $sta) {
        $staText = Get-Content $sta -Raw -ErrorAction SilentlyContinue
        if ($staText -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return "failed" }
        if ($staText -match 'SOLUTION PROGRESS') { return "failed" }
        return "failed"
    }
    return "failed"
}

function Wait-JobTerminal {
    param([Parameter(Mandatory)][string]$Slug)
    Write-QLog "waiting for terminal outcome: $Slug (poll ${PollSeconds}s)"
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
            Write-QLog "  running  (no .sta yet)"
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

Write-QLog "queue start wait=$WaitSlug next=$NextSlug cpus=$Cpus memory=${MemoryMB}MB"

if (-not $SkipSubmit25) {
    $exportInp = Join-Path $Root "output\export\$WaitSlug\$WaitSlug.inp"
    if (-not (Test-Path $exportInp)) {
        Write-QLog "ERROR missing export INP: $exportInp"
        exit 1
    }
    $outcome0 = Get-TerminalOutcome -Slug $WaitSlug
    if ($outcome0 -eq "running") {
        Write-QLog "skip lr25 submit (already running)"
    } else {
        Write-QLog "submit lr25m12 ..."
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1") `
            -SkipExport -Slug $WaitSlug -ForceRerun -Cpus $Cpus -MemoryMB $MemoryMB
        if ($LASTEXITCODE -ne 0) {
            Write-QLog "lr25 submit exit=$LASTEXITCODE (queue continues after terminal state)"
        }
    }
}

$null = Wait-JobTerminal -Slug $WaitSlug

Write-QLog "submit 5 mm/min BCC ($NextSlug) ..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1") `
    -SkipExport -Slug $NextSlug -ForceRerun -Cpus $Cpus -MemoryMB $MemoryMB
$exit = $LASTEXITCODE
Write-QLog "5 mm/min BCC submit exit=$exit"
exit $exit
