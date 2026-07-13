# Pull AF2Q0.5 payload sweep (0/100/300/500 g, 5-150 Hz) CSVs + overlay PNGs from server.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$LocalRoot = "d:\HuBaiLab"
)

$ErrorActionPreference = "Continue"
$slugs = @(
    "comsol_fig321_af2q05_444_mesh_p1_f5_150",
    "comsol_fig321_af2q05_444_mesh_p1_100g_f5_150",
    "comsol_fig321_af2q05_444_mesh_p1_300g_f5_150",
    "comsol_fig321_af2q05_444_mesh_p1_500g_f5_150"
)

foreach ($slug in $slugs) {
    $localDir = Join-Path $LocalRoot "output\comsol_jobs\$slug"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    $remoteDir = "$RemoteRoot/output/comsol_jobs/$slug"
    scp "${Server}:${remoteDir}/${slug}_transmissibility.csv" $localDir 2>$null
    scp "${Server}:${remoteDir}/${slug}_vld.png" $localDir 2>$null
    scp "${Server}:${remoteDir}/${slug}_fig322_vld.png" $localDir 2>$null
}

$compositeLocal = Join-Path $LocalRoot "output\comsol_jobs\af2q05_payload_composite"
New-Item -ItemType Directory -Force -Path $compositeLocal | Out-Null
scp "${Server}:${RemoteRoot}/output/comsol_jobs/af2q05_payload_composite/*" $compositeLocal 2>$null

Set-Location $LocalRoot
py -3 scripts/plot_comsol_vld_payload_overlay.py --preset f5-150 --variant af2q05 --out-dir output/comsol_jobs/af2q05_payload_composite --slug af2q05_p1_f5_150_payload_overlay --with-trans

Write-Host "Done."
Write-Host "Overlay: output/comsol_jobs/af2q05_payload_composite/af2q05_p1_f5_150_payload_overlay_vld.png"
