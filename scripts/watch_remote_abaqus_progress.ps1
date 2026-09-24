# Local live HTML progress board for a remote Abaqus Explicit job (.sta over SSH).
# Prefer the thin launcher:
#   powershell -File scripts/start_param_batch_progress_board.ps1 -CaseId af2q1_deq2p5_k1
#
# Direct:
#   powershell -File scripts/watch_remote_abaqus_progress.ps1 -CaseId af2q1_deq2p5_k1
#
# Writes: output/logs/progress_board/{CaseId}_{Slug}.html (+ .json)
# Remote helper: scripts/linux/watch_sta_snapshot.sh (must exist on RemoteRoot)
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CaseId,

    [string]$RemoteHost = $(if ($env:HU_BAI_REMOTE_HOST) { $env:HU_BAI_REMOTE_HOST } else { "art@172.20.200.93" }),
    [string]$RemoteRoot = $(if ($env:HU_BAI_REMOTE_ROOT) { $env:HU_BAI_REMOTE_ROOT } else { "/home/art/HuBaiLab_ssd" }),
    [string]$Slug = "cae_tet0p6mm80_5mmin_paperbox",
    [string]$BatchName = "param_batch",
    # 0 = auto from local meta/manifest (ContactSettle + Compression). Fallback 883.2.
    [double]$StepTotalSec = 0,
    [int]$IntervalSec = 15,
    [switch]$NoBrowser,
    [switch]$SkipHelperCheck
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutDir = Join-Path $Root "output\logs\progress_board"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$HtmlPath = Join-Path $OutDir "${CaseId}_${Slug}.html"
$JsonPath = Join-Path $OutDir "${CaseId}_${Slug}.json"
$RemoteJob = "$RemoteRoot/output/jobs/$BatchName/$CaseId/$Slug"
$HelperRemote = "$RemoteRoot/scripts/linux/watch_sta_snapshot.sh"
$HelperLocal = Join-Path $Root "scripts\linux\watch_sta_snapshot.sh"
$DefaultStepTotalSec = 883.2

function Resolve-StepTotalSec {
    param([double]$Requested)
    if ($Requested -gt 0) { return [double]$Requested }

    $exportDir = Join-Path $Root "output\export\$BatchName\$CaseId\$Slug"
    $metaPath = Join-Path $exportDir "${Slug}_meta.json"
    $manifestPath = Join-Path $exportDir "case_manifest.json"
    $protoPath = Join-Path $exportDir "protocol_local_manifest.json"

    $stepTime = $null
    $settleFrac = $null

    if (Test-Path -LiteralPath $metaPath) {
        try {
            $meta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($null -ne $meta.step_time) { $stepTime = [double]$meta.step_time }
        } catch { }
    }
    if (Test-Path -LiteralPath $manifestPath) {
        try {
            $man = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($null -eq $stepTime -and $man.loading -and $null -ne $man.loading.step_time_s) {
                $stepTime = [double]$man.loading.step_time_s
            }
            if ($man.loading -and $null -ne $man.loading.contact_settle_time_fraction) {
                $settleFrac = [double]$man.loading.contact_settle_time_fraction
            }
            if ($man.loading -and $man.loading.explicit_contact_settle -eq $false) {
                $settleFrac = 0.0
            }
        } catch { }
    }
    if ($null -eq $settleFrac -and (Test-Path -LiteralPath $protoPath)) {
        try {
            $proto = Get-Content -LiteralPath $protoPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($null -ne $proto.contact_settle_fraction) {
                $settleFrac = [double]$proto.contact_settle_fraction
            }
        } catch { }
    }

    if ($null -ne $stepTime -and $stepTime -gt 0) {
        if ($null -eq $settleFrac) { $settleFrac = 0.15 }
        $total = [math]::Round($stepTime * (1.0 + $settleFrac), 1)
        Write-Host ("StepTotalSec auto={0} (compression={1}s settle_frac={2})" -f $total, $stepTime, $settleFrac) -ForegroundColor DarkGray
        return [double]$total
    }

    Write-Host ("StepTotalSec fallback={0} (no local meta for {1}/{2})" -f $DefaultStepTotalSec, $CaseId, $Slug) -ForegroundColor Yellow
    return [double]$DefaultStepTotalSec
}

function Ensure-RemoteHelper {
    if ($SkipHelperCheck) { return }
    if (-not (Test-Path -LiteralPath $HelperLocal)) {
        throw "Missing local helper: $HelperLocal"
    }
    $exists = ssh -o BatchMode=yes -o ConnectTimeout=12 $RemoteHost "test -f '$HelperRemote' && echo 1 || echo 0" 2>$null
    if ($exists -eq "1") { return }
    Write-Host "Remote helper missing; uploading watch_sta_snapshot.sh ..." -ForegroundColor Yellow
    ssh -o BatchMode=yes -o ConnectTimeout=12 $RemoteHost "mkdir -p '$RemoteRoot/scripts/linux'"
    scp -o BatchMode=yes -o ConnectTimeout=20 $HelperLocal "${RemoteHost}:${HelperRemote}"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to scp helper to ${RemoteHost}:${HelperRemote}"
    }
    ssh -o BatchMode=yes $RemoteHost "chmod +x '$HelperRemote'"
    Write-Host "Remote helper OK: $HelperRemote" -ForegroundColor Green
}

$StepTotalSec = Resolve-StepTotalSec -Requested $StepTotalSec
Ensure-RemoteHelper

function Get-RemoteSnapshot {
    # Call a fixed remote helper (avoids Windows OpenSSH mangling multiline scripts).
    ssh -o BatchMode=yes -o ConnectTimeout=12 $RemoteHost `
        "/bin/bash" $HelperRemote $RemoteJob $Slug $CaseId
}

function Parse-StaProgress([string]$staText, [double]$totalSec) {
    $stepTime = $null
    $totalTime = $null
    $wall = $null
    $inc = $null
    $frame = $null
    $stepNo = $null
    $completed = $false
    $error = $false
    foreach ($line in ($staText -split "`n")) {
        $t = $line.Trim()
        if ($t -match '(?i)THE ANALYSIS HAS (BEEN )?COMPLETED') {
            $completed = $true
        }
        # Do NOT treat WARNING text containing "error/erroneous/round-off errors" as failure.
        if ($t -match '(?i)Abaqus/?Explicit Analysis exited with an error' -or
            $t -match '(?i)^\*\*\*ERROR' -or
            $t -match '(?i)FATAL ERROR' -or
            $t -match '(?i)THE ANALYSIS HAS BEEN ABORTED') {
            $error = $true
        }
        if ($t -match '^\s*STEP\s+(\d+)\s+ORIGIN') {
            $stepNo = [int]$Matches[1]
        }
        # INCREMENT STEP_TIME TOTAL_TIME WALL STABLE ...
        if ($t -match '^\s*(\d+)\s+([0-9.+-Ee]+)\s+([0-9.+-Ee]+)\s+(\d{2}:\d{2}:\d{2})\b') {
            $inc = [int]$Matches[1]
            $stepTime = [double]$Matches[2]
            $totalTime = [double]$Matches[3]
            $wall = $Matches[4]
        }
        if ($t -match 'Output Field Frame Number\s+(\d+).*step time\s+([0-9.+-Ee]+)') {
            $frame = [int]$Matches[1]
            if ($null -eq $stepTime) { $stepTime = [double]$Matches[2] }
        }
    }
    # Prefer TOTAL TIME (across ContactSettle + Compression) for overall %.
    $pct = 0.0
    $progressClock = $null
    if ($null -ne $totalTime) {
        $progressClock = $totalTime
    } elseif ($null -ne $stepTime) {
        $progressClock = $stepTime
    }
    if ($null -ne $progressClock -and $totalSec -gt 0) {
        $pct = [math]::Min(100.0, [math]::Round(100.0 * $progressClock / $totalSec, 2))
    }
    if ($completed) { $pct = 100.0 }
    return [pscustomobject]@{
        Increment     = $inc
        StepTime      = $stepTime
        TotalTime     = $totalTime
        ProgressClock = $progressClock
        StepNo        = $stepNo
        WallClock     = $wall
        Frame         = $frame
        Percent       = $pct
        Completed     = $completed
        Error         = $error
    }
}

function Write-BoardHtml($state) {
    $pct = [double]$state.percent
    $barColor = if ($state.error) { "#c62828" } elseif ($state.completed) { "#2e7d32" } else { "#1565c0" }
    $status = if ($state.error) { "ERROR" } elseif ($state.completed) { "COMPLETED" } elseif ($state.alive) { "RUNNING" } else { "IDLE / UNKNOWN" }
    $stepDisp = if ($null -ne $state.progress_clock) { ("{0:N1} / {1:N1} s" -f $state.progress_clock, $state.step_total) } else { "n/a (waiting .sta)" }
    $eta = $state.eta_text
    $staEsc = [System.Net.WebUtility]::HtmlEncode(($state.sta_tail -join "`n"))
    $html = @"
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta http-equiv="refresh" content="$IntervalSec"/>
<title>$CaseId progress</title>
<style>
  body { font-family: "Segoe UI", Consolas, monospace; background:#0f1419; color:#e7ecf1; margin:24px; }
  h1 { font-size:20px; margin:0 0 8px; }
  .sub { color:#9aa7b5; margin-bottom:18px; }
  .card { background:#1a2330; border:1px solid #2a3848; border-radius:10px; padding:16px 18px; margin-bottom:14px; }
  .row { display:flex; gap:18px; flex-wrap:wrap; }
  .kpi { min-width:140px; }
  .kpi .v { font-size:22px; font-weight:600; }
  .kpi .l { color:#9aa7b5; font-size:12px; }
  .bar { height:22px; background:#0b1016; border-radius:11px; overflow:hidden; border:1px solid #2a3848; }
  .fill { height:100%; width:${pct}%; background:$barColor; transition:width .4s; }
  .pct { font-size:28px; font-weight:700; color:$barColor; margin:8px 0; }
  pre { white-space:pre-wrap; background:#0b1016; padding:12px; border-radius:8px; font-size:12px; color:#c5d0da; max-height:340px; overflow:auto; }
  .ok { color:#81c784; } .bad { color:#ef9a9a; } .run { color:#64b5f6; }
</style>
</head>
<body>
  <h1>$CaseId · $Slug</h1>
  <div class="sub">remote: $RemoteJob<br/>updated: $($state.local_time) · auto-refresh ${IntervalSec}s</div>
  <div class="card">
    <div class="pct">${pct}%</div>
    <div class="bar"><div class="fill"></div></div>
    <div class="row" style="margin-top:14px">
      <div class="kpi"><div class="l">STATUS</div><div class="v $(if($state.completed){'ok'}elseif($state.error){'bad'}else{'run'})">$status</div></div>
      <div class="kpi"><div class="l">TOTAL TIME</div><div class="v">$stepDisp</div></div>
      <div class="kpi"><div class="l">ABAQUS STEP</div><div class="v">$(if($null -ne $state.step_no){$state.step_no}else{'-'})</div></div>
      <div class="kpi"><div class="l">INCREMENT</div><div class="v">$(if($null -ne $state.increment){$state.increment}else{'-'})</div></div>
      <div class="kpi"><div class="l">WALL (sta)</div><div class="v">$(if($state.wall){$state.wall}else{'-'})</div></div>
      <div class="kpi"><div class="l">ETA</div><div class="v">$eta</div></div>
      <div class="kpi"><div class="l">ODB</div><div class="v">$($state.odb_mb) MB</div></div>
      <div class="kpi"><div class="l">JOB DIR</div><div class="v">$($state.job_mb) MB</div></div>
      <div class="kpi"><div class="l">explicit ranks</div><div class="v">$($state.explicit_n)</div></div>
      <div class="kpi"><div class="l">mem avail/total</div><div class="v">$($state.mem)</div></div>
      <div class="kpi"><div class="l">load1</div><div class="v">$($state.load1)</div></div>
    </div>
  </div>
  <div class="card">
    <div class="l" style="color:#9aa7b5;margin-bottom:8px">.sta tail</div>
    <pre>$staEsc</pre>
  </div>
</body>
</html>
"@
    Set-Content -LiteralPath $HtmlPath -Value $html -Encoding UTF8
}

Write-Host "Progress board -> $HtmlPath" -ForegroundColor Cyan
Write-Host "Remote job    -> $RemoteJob" -ForegroundColor DarkGray
Write-Host "StepTotalSec  -> $StepTotalSec" -ForegroundColor DarkGray
# Placeholder so browser can open immediately.
@"
<!DOCTYPE html><html><head><meta charset='utf-8'/><meta http-equiv='refresh' content='$IntervalSec'/>
<title>$CaseId loading</title></head>
<body style='font-family:Segoe UI;background:#0f1419;color:#e7ecf1;padding:24px'>
<h1>$CaseId</h1><p>Waiting for first SSH poll…</p></body></html>
"@ | Set-Content -LiteralPath $HtmlPath -Encoding UTF8
if (-not $NoBrowser) {
    try { Invoke-Item -LiteralPath $HtmlPath } catch { Start-Process "explorer.exe" -ArgumentList $HtmlPath }
}

while ($true) {
    $raw = ""
    try { $raw = (Get-RemoteSnapshot | Out-String) } catch { $raw = "SSH_ERROR: $_" }

    $kv = @{}
    $staLines = @()
    $inSta = $false
    foreach ($line in ($raw -split "`r?`n")) {
        if ($line -eq "---STA_TAIL---") { $inSta = $true; continue }
        if ($line -eq "---STA_END---") { $inSta = $false; continue }
        if ($inSta) { $staLines += $line; continue }
        if ($line -match '^([A-Z0-9_]+)=(.*)$') { $kv[$Matches[1]] = $Matches[2] }
    }

    $prog = Parse-StaProgress ($staLines -join "`n") $StepTotalSec
    $etaText = "-"
    $clock = $prog.ProgressClock
    if ($null -ne $clock -and $clock -gt 1 -and -not $prog.Completed -and $prog.WallClock) {
        $parts = $prog.WallClock.Split(":")
        if ($parts.Count -eq 3) {
            $wallSec = [int]$parts[0] * 3600 + [int]$parts[1] * 60 + [int]$parts[2]
            if ($wallSec -gt 0) {
                $rate = $clock / $wallSec
                $remain = ($StepTotalSec - $clock) / [math]::Max($rate, 1e-9)
                if ($remain -lt 0) { $remain = 0 }
                $ts = [TimeSpan]::FromSeconds([math]::Round($remain))
                $etaText = ("{0:d2}:{1:d2}:{2:d2}" -f [int]$ts.TotalHours, $ts.Minutes, $ts.Seconds)
            }
        }
    } elseif ($prog.Completed) {
        $etaText = "done"
    }

    $memText = "-"
    if ($kv.Contains("MEM_LINE") -and $kv["MEM_LINE"]) {
        $mm = ($kv["MEM_LINE"] -split '\s+' | Where-Object { $_ })
        # free -g row: Mem total used free shared buff/cache available
        if ($mm.Count -ge 7) { $memText = ("{0}/{1} GiB" -f $mm[6], $mm[1]) }
        elseif ($mm.Count -ge 4) { $memText = ("free {0}/{1} GiB" -f $mm[3], $mm[1]) }
    }
    $jobMb = $kv["JOB_MB"]
    if (-not $jobMb) { $jobMb = "-" }

    $explicitN = 0
    if ($kv.Contains("EXPLICIT_N") -and $kv["EXPLICIT_N"] -match '^\d+$') {
        $explicitN = [int]$kv["EXPLICIT_N"]
    }

    $state = [ordered]@{
        case_id     = $CaseId
        slug        = $Slug
        local_time  = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        remote_now  = $kv["NOW"]
        alive       = ($kv["ALIVE"] -eq "1" -or $kv["LCK"] -eq "1" -or $explicitN -gt 0)
        lck         = ($kv["LCK"] -eq "1")
        explicit_n  = $kv["EXPLICIT_N"]
        odb_mb      = $kv["ODB_MB"]
        job_mb      = $jobMb
        mem         = $memText
        load1       = $kv["LOAD1"]
        percent         = $prog.Percent
        step_time       = $prog.StepTime
        total_time      = $prog.TotalTime
        progress_clock  = $prog.ProgressClock
        step_no         = $prog.StepNo
        step_total      = $StepTotalSec
        increment       = $prog.Increment
        wall            = $prog.WallClock
        frame           = $prog.Frame
        completed       = $prog.Completed
        error           = $prog.Error
        eta_text        = $etaText
        sta_tail        = ($staLines | Select-Object -Last 20)
    }
    ($state | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $JsonPath -Encoding UTF8
    Write-BoardHtml $state

    $msg = "[{0}] {1}% total={2}s step#{3} inc={4} odb={5}MB eta={6}" -f `
        $state.local_time, $state.percent, $state.progress_clock, $state.step_no, $state.increment, $state.odb_mb, $state.eta_text
    Write-Host $msg

    if ($state.completed) {
        Write-Host "Monitor stopping: COMPLETED" -ForegroundColor Green
        break
    }
    if ($state.error) {
        Write-Host "Monitor stopping: real ERROR detected" -ForegroundColor Red
        break
    }
    Start-Sleep -Seconds $IntervalSec
}
