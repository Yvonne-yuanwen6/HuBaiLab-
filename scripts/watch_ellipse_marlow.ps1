# Local monitor: tail server ellipse Marlow batch log + state JSON.
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [int]$PollSeconds = 120
)

$ErrorActionPreference = "SilentlyContinue"
$LogLocal = Join-Path $PSScriptRoot "..\output\logs\ellipse_marlow_watch_local.log" | Resolve-Path -ErrorAction SilentlyContinue
if (-not $LogLocal) {
    $LogLocal = Join-Path (Split-Path $PSScriptRoot -Parent) "output\logs\ellipse_marlow_watch_local.log"
}
New-Item -ItemType Directory -Force -Path (Split-Path $LogLocal) | Out-Null

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $LogLocal -Value $line
    Write-Host $line
}

Log "=== ellipse marlow watch start poll=${PollSeconds}s ==="

while ($true) {
    $stateJson = ssh $RemoteHost "cat '$RemoteRoot/output/logs/ellipse_444_baseline_state.json' 2>/dev/null"
    $tailLog = ssh $RemoteHost "tail -8 '$RemoteRoot/output/logs/ellipse_444_baseline_parallel.log' 2>/dev/null"
    $procN = ssh $RemoteHost "ps aux | awk '/\/bin\/explicit/ && /paperbox_ellipse/ {c++} END {print c+0}'"

    if ($stateJson) {
        try {
            $state = $stateJson | ConvertFrom-Json
            $running = @($state.cases | Where-Object { $_.running }).Count
            $done = @($state.cases | Where-Object { $_.completed -and $_.csv_ready }).Count
            $total = @($state.cases).Count
            Log "status done=$done/$total running=$running explicit_ranks=$procN phase=$($state.phase)"
            foreach ($c in $state.cases) {
                $mark = if ($c.completed) { "OK" } elseif ($c.running) { "RUN" } else { "PEND" }
                Log "  [$mark] $($c.label) $($c.align) Q=$($c.q)"
            }
            if ($state.all_done -eq $true) {
                Log "=== ALL DONE ==="
                break
            }
        } catch {
            Log "WARN state parse failed"
        }
    } else {
        Log "waiting for state file... explicit_ranks=$procN"
    }

    if ($tailLog) {
        Write-Host "--- server log ---" -ForegroundColor DarkGray
        $tailLog | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    }

    Start-Sleep -Seconds $PollSeconds
}
