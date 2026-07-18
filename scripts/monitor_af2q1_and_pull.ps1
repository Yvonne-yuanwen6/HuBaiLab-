# Monitor AF2Q1 payload batch on server; pull overlay when done.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$LocalRoot = "d:\HuBaiLab",
    [int]$IntervalSec = 90
)

$batchLog = "$RemoteRoot/output/logs/af2q1_payload_f5_150_batch.log"
$monitorLog = "$RemoteRoot/output/logs/af2q1_payload_monitor.log"

function Get-BatchTail {
    ssh $Server "tail -12 $batchLog 2>/dev/null"
}

while ($true) {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] AF2Q1 batch monitor"
    $tail = Get-BatchTail
    Write-Host $tail
    if ($tail -match "batch done") {
        Write-Host "[$ts] Batch complete — pulling results..."
        break
    }
    $running = ssh $Server "pgrep -f af2q1_444_mesh_p1 >/dev/null; echo `$?"
    if ($running -ne "0" -and $tail -notmatch "batch done") {
        Write-Host "[$ts] WARN: no af2q1 processes; check log"
        if ($tail -match "ERROR") { exit 1 }
    }
    Start-Sleep -Seconds $IntervalSec
}

# Pull AF2Q1 only
$slugs = @(
    "comsol_fig321_af2q1_444_mesh_p1_f5_150",
    "comsol_fig321_af2q1_444_mesh_p1_100g_f5_150",
    "comsol_fig321_af2q1_444_mesh_p1_300g_f5_150",
    "comsol_fig321_af2q1_444_mesh_p1_500g_f5_150"
)
foreach ($slug in $slugs) {
    $localDir = Join-Path $LocalRoot "output\comsol_jobs\$slug"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    scp "${Server}:${RemoteRoot}/output/comsol_jobs/${slug}/${slug}_transmissibility.csv" $localDir 2>$null
}
$composite = Join-Path $LocalRoot "output\comsol_jobs\af2q1_payload_composite"
New-Item -ItemType Directory -Force -Path $composite | Out-Null
scp "${Server}:${RemoteRoot}/output/comsol_jobs/af2q1_payload_composite/*" $composite 2>$null

Set-Location $LocalRoot
py -3 scripts/plot_comsol_vld_payload_overlay.py --preset f5-150 --variant af2q1 `
    --out-dir output/comsol_jobs/af2q1_payload_composite --slug af2q1_p1_f5_150_payload_overlay --with-trans

Write-Host "Done: output/comsol_jobs/af2q1_payload_composite/af2q1_p1_f5_150_payload_overlay_vld.png"
