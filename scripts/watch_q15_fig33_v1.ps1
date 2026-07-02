# Monitor Q1.5 Fig.3.3 V1 trial on server (poll .sta + pipeline log).
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [double]$StepTimeS = 768.0,
    [double]$TargetStrain = 0.8,
    [int]$PollSeconds = 20
)

$ErrorActionPreference = "SilentlyContinue"
$Slug = "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_q15_v1_ns_el"
$Sta = "$RemoteRoot/output/jobs/$Slug/$Slug.sta"
$Lck = "$RemoteRoot/output/jobs/$Slug/$Slug.lck"
$Log = "$RemoteRoot/output/logs/sfbls_af2q1p5_q15_v1_ns_el_pipeline.log"

Write-Host "=== Q15 Fig.3.3 V1 monitor (no self-contact, ONE-TIME trial) ===" -ForegroundColor Cyan
Write-Host "  Remote: ${RemoteHost}:${RemoteRoot}" -ForegroundColor Cyan
Write-Host "  Slug:   $Slug" -ForegroundColor Cyan
Write-Host "  Poll:   ${PollSeconds}s   step~${StepTimeS}s   strain~$([int]($TargetStrain*100))%" -ForegroundColor Cyan
Write-Host "  Ctrl+C to stop watching (job keeps running on server)" -ForegroundColor DarkGray
Write-Host ""

while ($true) {
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $completed = ssh $RemoteHost "grep -c 'COMPLETED SUCCESSFULLY' '$Sta' 2>/dev/null"
    $hasLck = ssh $RemoteHost "test -f '$Lck' && echo 1 || echo 0"
    $hasSta = ssh $RemoteHost "test -f '$Sta' && echo 1 || echo 0"
    $hasExport = ssh $RemoteHost "test -f '$RemoteRoot/output/export/$Slug/$Slug.inp' && echo 1 || echo 0"

    if ([int]$completed -gt 0) { $st = "COMPLETED" }
    elseif ($hasLck -eq "1") { $st = "RUNNING" }
    elseif ($hasSta -eq "1") { $st = "STOPPED" }
    elseif ($hasExport -eq "1") { $st = "QUEUED/EXPORTED" }
    else { $st = "WAITING (export/submit)" }

    $simS = 0.0
    $wall = "--:--:--"
    $ke = $null
    $ie = $null
    if ($hasSta -eq "1") {
        $line = ssh $RemoteHost "grep -E '^[[:space:]]+[0-9]+[[:space:]]+' '$Sta' 2>/dev/null | tail -1"
        if ($line -match '^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)\s+([\d.E+-]+)\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)') {
            $simS = [double]$Matches[3]
            $wall = $Matches[4]
            $ke = [double]$Matches[7]
            $ie = [double]$Matches[8]
        }
    }

    $pct = if ($StepTimeS -gt 0) { [math]::Min(100, 100 * $simS / $StepTimeS) } else { 0 }
    $estr = $TargetStrain * $simS / $StepTimeS * 100
    $filled = [int][math]::Floor(40 * $pct / 100)
    $bar = ("#" * $filled).PadRight(40, "-")

    $color = switch ($st) {
        "COMPLETED" { "Green" }
        "RUNNING" { "Yellow" }
        "STOPPED" { "Red" }
        default { "Gray" }
    }

    Write-Host "[$now] $st" -ForegroundColor $color
    if ($st -match "RUNNING|COMPLETED|STOPPED") {
        Write-Host ("  [{0}] {1,5:F1}%  sim {2,7:F1}/{3} s  strain~{4,5:F1}%  wall {5}" -f $bar, $pct, $simS, $StepTimeS, $estr, $wall)
        if ($null -ne $ke -and $ie -gt 0) {
            $ratio = 100 * $ke / $ie
            Write-Host ("  KE={0:G3}  IE={1:G3}  KE/IE={2:F1}%" -f $ke, $ie, $ratio) -ForegroundColor $(if ($ratio -lt 5) { "Green" } else { "Yellow" })
        }
    }
    if ($st -match "WAITING|QUEUED") {
        $tail = ssh $RemoteHost "tail -3 '$Log' 2>/dev/null"
        if ($tail) {
            Write-Host "  pipeline log:" -ForegroundColor DarkYellow
            $tail -split "`n" | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkYellow }
        }
    }
    Write-Host ""

    if ($st -eq "COMPLETED") {
        Write-Host "Done. Run on server:" -ForegroundColor Green
        Write-Host "  bash scripts/linux/run_paperbox_q15_fig33_sweep.sh eval --variant-suffix q15_fig33_v1_nosettle_noself_elastic"
        break
    }
    if ($st -eq "STOPPED") {
        Write-Host "Job stopped/failed. Check .sta / .msg on server." -ForegroundColor Red
        break
    }
    Start-Sleep -Seconds $PollSeconds
}
