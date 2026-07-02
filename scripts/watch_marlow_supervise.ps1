# Local supervisor: sync server pulls, plot partial curves, tail remote supervise log.
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$LocalRoot = "D:\HuBaiLab",
    [int]$PollSeconds = 120
)

$ErrorActionPreference = "SilentlyContinue"
$Slug = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow"
$LogLocal = Join-Path $LocalRoot "output\logs\marlow_supervise_local.log"
$PostDir = Join-Path $LocalRoot "output\post\$Slug"
New-Item -ItemType Directory -Force -Path $PostDir, (Split-Path $LogLocal) | Out-Null

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $LogLocal -Value $line
    Write-Host $line
}

Log "=== marlow local supervise start poll=${PollSeconds}s ==="

$lastCsvSize = 0
while ($true) {
    $staLine = ssh $RemoteHost "grep -E '^[[:space:]]+[1-9]' '$RemoteRoot/output/jobs/$Slug/$Slug.sta' 2>/dev/null | tail -1"
    $completed = ssh $RemoteHost "grep -c 'COMPLETED SUCCESSFULLY' '$RemoteRoot/output/jobs/$Slug/$Slug.sta' 2>/dev/null"
    $procN = ssh $RemoteHost "ps aux | awk '/\/bin\/explicit/ && /fig33_v2_marlow/ {c++} END {print c+0}'"
    $remoteLog = ssh $RemoteHost "tail -3 '$RemoteRoot/output/logs/marlow_supervise.log' 2>/dev/null"

    $simS = 0.0
    $ke = 0.0
    if ($staLine -match '^\s+\d+\s+[\d.E+-]+\s+([\d.E+-]+).*?\s+([\d.E+-]+)\s+([\d.E+-]+)\s*$') {
        $simS = [double]$Matches[1]
        $ke = [double]$Matches[2]
    }

    $st = if ([int]$completed -gt 0) { "COMPLETED" } elseif ([int]$procN -gt 0) { "RUNNING" } else { "IDLE" }
    Log "$st sim=$simS s ke=$ke ranks=$procN"
    if ($remoteLog) { Write-Host "  server: $remoteLog" -ForegroundColor DarkGray }

    $remoteCsv = "${RemoteHost}:${RemoteRoot}/output/post/${Slug}/${Slug}_stress_strain_partial.csv"
    $localCsv = Join-Path $PostDir "${Slug}_stress_strain_partial.csv"
    scp $remoteCsv $localCsv 2>$null | Out-Null
    if ((Test-Path $localCsv) -and (Get-Item $localCsv).Length -ne $lastCsvSize) {
        $lastCsvSize = (Get-Item $localCsv).Length
        Log "new partial CSV ($lastCsvSize bytes) -> plotting"
        py -3 (Join-Path $LocalRoot "scripts\plot_q05_fig33_marlow_partial.py") --compare-el
    }

    if ($st -eq "COMPLETED") {
        scp "${RemoteHost}:${RemoteRoot}/output/post/${Slug}/${Slug}_stress_strain.csv" (Join-Path $PostDir "${Slug}_stress_strain.csv") 2>$null
        py -3 (Join-Path $LocalRoot "scripts\plot_q05_fig33_marlow_partial.py") --compare-el `
            --png (Join-Path $LocalRoot "output\reports\fig33_v2_marlow\af2q05_exp_vs_sim.png")
        Log "=== COMPLETED — final plot done ==="
        break
    }

    Start-Sleep -Seconds $PollSeconds
}
