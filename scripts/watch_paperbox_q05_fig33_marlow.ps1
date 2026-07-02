# Live monitor: Q0.5 fig33_v2_marlow_settle5p (48c, Marlow + ContactSettle 5%).
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$VariantSuffix = "fig33_v2_marlow",
    [double]$StepTimeS = 806.4,
    [double]$TargetStrain = 0.8,
    [int]$PollSeconds = 30
)

$ErrorActionPreference = "SilentlyContinue"
$Slug = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_$VariantSuffix"
$Sta = "$RemoteRoot/output/jobs/$Slug/$Slug.sta"
$Lck = "$RemoteRoot/output/jobs/$Slug/$Slug.lck"

Write-Host "=== Q05 fig33_v2_marlow monitor (poll=${PollSeconds}s) ===" -ForegroundColor Cyan
Write-Host "  slug: $Slug" -ForegroundColor DarkGray
Write-Host "  remote: ${RemoteHost}:${RemoteRoot}" -ForegroundColor DarkGray
Write-Host "  target: step=${StepTimeS}s  strain~$([int]($TargetStrain * 100))%" -ForegroundColor DarkGray
Write-Host "  Ctrl+C to stop watching" -ForegroundColor DarkGray
Write-Host ""

while ($true) {
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = ssh $RemoteHost "grep -E '^[[:space:]]+[1-9][0-9]*[[:space:]]+' '$Sta' 2>/dev/null | tail -1"
    $completed = ssh $RemoteHost "grep -c 'COMPLETED SUCCESSFULLY' '$Sta' 2>/dev/null"
    $hasLck = ssh $RemoteHost "test -f '$Lck' && echo 1 || echo 0"
    $procN = ssh $RemoteHost "ps aux | awk '/\/bin\/explicit/ && /paperbox_$VariantSuffix/ {c++} END {print c+0}'"
    $cpus = ssh $RemoteHost "ps -eo args | grep '/bin/explicit' | grep 'paperbox_$VariantSuffix' | head -1 | grep -oP '\-cpus \K\d+'"

    if ([int]$completed -gt 0) { $st = "COMPLETED" }
    elseif ($hasLck -eq "1" -or [int]$procN -gt 0) { $st = "RUNNING" }
    elseif ($line) { $st = "STOPPED" }
    else { $st = "WAITING" }

    $simS = 0.0
    $wall = "--:--:--"
    $ke = $null
    if ($line -match '^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)\s+([\d.E+-]+)\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)') {
        $simS = [double]$Matches[3]
        $wall = $Matches[4]
        $ke = [double]$Matches[7]
        $ie = [double]$Matches[8]
    }

    $pct = if ($StepTimeS -gt 0) { [math]::Min(100, 100 * $simS / $StepTimeS) } else { 0 }
    $estr = $TargetStrain * $simS / $StepTimeS * 100
    $filled = [int][math]::Floor(40 * $pct / 100)
    $bar = ("#" * $filled).PadRight(40, "-")

    $eta = "calculating..."
    if ($simS -gt 0.5 -and $wall -match '^(\d\d):(\d\d):(\d\d)$') {
        $wallSec = [int]$Matches[1] * 3600 + [int]$Matches[2] * 60 + [int]$Matches[3]
        $rate = $wallSec / $simS
        $remain = [math]::Max(0, $StepTimeS - $simS)
        $etaSec = [int][math]::Round($remain * $rate)
        $eta = (Get-Date).AddSeconds($etaSec).ToString("HH:mm")
    }

    $color = switch ($st) {
        "COMPLETED" { "Green" }
        "RUNNING" { "Yellow" }
        "FAILED" { "Red" }
        default { "Gray" }
    }

    Write-Host "[$now] $st" -ForegroundColor $color
    Write-Host ("  cpus={0}  ranks={1}  lck={2}" -f ($(if ($cpus) { $cpus } else { "?" })), $procN, $hasLck)
    Write-Host ("  [{0}] {1,5:F1}%  sim {2,7:F1}/{3} s  strain~{4,5:F1}%  wall {5}" -f $bar, $pct, $simS, $StepTimeS, $estr, $wall)
    if ($null -ne $ke) { Write-Host ("  KE={0:G3}  IE={1:G3}  ETA~{2}" -f $ke, $ie, $eta) }
    else { Write-Host "  ETA~$eta" }
    Write-Host ""

    if ($st -eq "COMPLETED") {
        Write-Host "=== Analysis completed ===" -ForegroundColor Green
        break
    }
    Start-Sleep -Seconds $PollSeconds
}
