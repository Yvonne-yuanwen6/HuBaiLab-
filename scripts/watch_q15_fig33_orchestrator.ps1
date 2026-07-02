# Continuous monitor for Q15 Fig.3.3 orchestrator (server-side auto recovery).
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [int]$PollSeconds = 30
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "=== Q15 Fig.3.3 orchestrator watch (poll ${PollSeconds}s) ===" -ForegroundColor Cyan
Write-Host "  Remote: ${RemoteHost}:${RemoteRoot}" -ForegroundColor Cyan
Write-Host "  Log:    output/logs/q15_fig33_orchestrator.log" -ForegroundColor Cyan
Write-Host "  Ctrl+C stops local watch only; server orchestrator keeps running" -ForegroundColor DarkGray
Write-Host ""

while ($true) {
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $stateJson = ssh $RemoteHost "cat $RemoteRoot/output/logs/q15_fig33_orchestrator_state.json 2>/dev/null"
    $phase = "?"
    $active = ""
    $winner = ""
    if ($stateJson) {
        try {
            $s = $stateJson | ConvertFrom-Json
            $phase = $s.phase
            if ($s.active) { $active = "$($s.active.variant)/$($s.active.suffix)" }
            if ($s.winner) { $winner = $s.winner.suffix }
        } catch { $phase = "parse_err" }
    }
    Write-Host "[$now] phase=$phase active=$active winner=$winner" -ForegroundColor $(if ($phase -eq "done") { "Green" } elseif ($phase -eq "failed") { "Red" } else { "Yellow" })

    if ($active) {
        $slug = ssh $RemoteHost "python3 -c \"import json; s=json.load(open('$RemoteRoot/output/logs/q15_fig33_orchestrator_state.json')); print(s.get('active',{}).get('slug',''))\""
        if ($slug) {
            $sta = "$RemoteRoot/output/jobs/$slug/$slug.sta"
            $lck = ssh $RemoteHost "test -f '$RemoteRoot/output/jobs/$slug/$slug.lck' && echo 1 || echo 0"
            $line = ssh $RemoteHost "grep -E '^[[:space:]]+[0-9]+[[:space:]]+' '$sta' 2>/dev/null | tail -1"
            $st = if ($lck -eq "1") { "RUNNING" } else { "idle/done" }
            if ($line -match '^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)') {
                $sim = [double]$Matches[3]
                $wall = $Matches[4]
                $pct = [math]::Min(100, 100 * $sim / 768.0)
                Write-Host ("  {0} sim={1:F1}/768s ({2:F1}%) wall={3}" -f $st, $sim, $pct, $wall)
            } else {
                Write-Host "  $st (no increment line yet)"
            }
        }
    }

    $tail = ssh $RemoteHost "tail -2 $RemoteRoot/output/logs/q15_fig33_orchestrator.log 2>/dev/null"
    if ($tail) {
        $tail -split "`n" | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    }
    Write-Host ""

    if ($phase -in @("done", "failed")) { break }
    Start-Sleep -Seconds $PollSeconds
}
