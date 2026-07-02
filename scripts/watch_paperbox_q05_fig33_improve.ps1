# Monitor Q0.5 Fig.3.3 improvement sweep on server (serial orchestrator).
param(
    [int]$PollSeconds = 60
)

$ErrorActionPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "remote_config.ps1")

$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Base = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"

$Variants = @(
    "fig33_v2_paper",
    "fig33_v2_ep",
    "paperbox_settle5p",
    "fig33_v2_paper_dt1e4"
)

$StepTimeS = 768.0
$TargetStrain = 0.8

function Parse-StaLine {
    param([string]$Line)
    if ($Line -match 'Output Field Frame Number\s+(\d+),\s+of\s+(\d+),\s+at step time\s+([\d.E+-]+)') {
        return [PSCustomObject]@{ Kind = 'frame'; SimS = [double]$Matches[3] }
    }
    if ($Line -match '^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)') {
        return [PSCustomObject]@{ Kind = 'inc'; SimS = [double]$Matches[3]; Wall = [string]$Matches[4] }
    }
    return $null
}

function Sync-RemoteSta {
    param([string]$Slug)
    $jobDir = Join-Path $LocalRoot "output\jobs\$Slug"
    New-Item -ItemType Directory -Force -Path $jobDir | Out-Null
    $remoteJob = "$HuBaiRemoteRoot/output/jobs/$Slug"
    scp "${HuBaiRemoteHost}:${remoteJob}/${Slug}.sta" $jobDir 2>$null | Out-Null
    scp "${HuBaiRemoteHost}:${remoteJob}/${Slug}.lck" $jobDir 2>$null | Out-Null
}

function Get-JobStatus {
    param([string]$Slug)
    $sta = Join-Path $LocalRoot "output\jobs\$Slug\$Slug.sta"
    $lck = Join-Path $LocalRoot "output\jobs\$Slug\$Slug.lck"
    if ((Test-Path $sta) -and (Select-String -Path $sta -Pattern 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' -Quiet)) { return 'DONE' }
    if (Test-Path $lck) { return 'RUN' }
    if ((Test-Path $sta) -and (Select-String -Path $sta -Pattern 'THE ANALYSIS HAS NOT BEEN COMPLETED|excessively distorted' -Quiet)) { return 'FAIL' }
    if (Test-Path $sta) { return 'STOP' }
    return 'WAIT'
}

function Get-Progress {
    param([string]$Slug)
    $sta = Join-Path $LocalRoot "output\jobs\$Slug\$Slug.sta"
    $simS = 0.0; $wall = '--:--:--'
    if (-not (Test-Path $sta)) { return $simS, $wall }
    foreach ($line in (Get-Content $sta -Tail 40 -ErrorAction SilentlyContinue)) {
        $p = Parse-StaLine $line
        if (-not $p) { continue }
        if ($p.SimS -gt $simS) { $simS = $p.SimS }
        if ($p.Kind -eq 'inc') { $wall = $p.Wall }
    }
    return $simS, $wall
}

Write-Host "=== Q05 Fig.3.3 improve monitor ===" -ForegroundColor Cyan
Write-Host "  Remote: ${HuBaiRemoteHost}:${HuBaiRemoteRoot}"
Write-Host "  Poll:   ${PollSeconds}s"
Write-Host ""

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts]" -ForegroundColor DarkGray

    $orch = ssh $HuBaiRemoteHost "pgrep -af 'run_paperbox_q05_fig33_improve.sh' 2>/dev/null | head -1"
    if ($orch) { Write-Host "  orchestrator: RUNNING" -ForegroundColor Green }
    else { Write-Host "  orchestrator: idle/done" -ForegroundColor Yellow }

    foreach ($v in $Variants) {
        $slug = "${Base}_$v"
        Sync-RemoteSta $slug
        $st = Get-JobStatus $slug
        $simS, $wall = Get-Progress $slug
        $pct = if ($StepTimeS -gt 0) { [math]::Min(100, 100 * $simS / $StepTimeS) } else { 0 }
        $strainPct = [math]::Min(100, 100 * $simS / $StepTimeS * $TargetStrain)
        $color = switch ($st) {
            'DONE' { 'Green' }
            'RUN'  { 'Cyan' }
            'FAIL' { 'Red' }
            default { 'Gray' }
        }
        Write-Host ("  {0,-22} {1,-5} sim {2,6:F0}/{3} s  strain~{4,5:F1}%  wall {5}" -f $v, $st, $simS, $StepTimeS, $strainPct, $wall) -ForegroundColor $color
    }

    $ready = Join-Path $LocalRoot "output\logs\q05_fig33_improve_ready.json"
    scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/logs/q05_fig33_improve_ready.json" $ready 2>$null | Out-Null
    if ((Test-Path $ready) -and (Get-Content $ready -Raw | Select-String '"all_ready"\s*:\s*true' -Quiet)) {
        Write-Host "`nAll Q05 improve variants ready." -ForegroundColor Green
        break
    }

    Start-Sleep -Seconds $PollSeconds
}
