# Pull BCC payload sweep (0/100/300/500 g, 5-150 Hz) CSVs + overlay PNGs from server.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$LocalRoot = "d:\HuBaiLab"
)

$ErrorActionPreference = "Stop"
$slugs = @(
    "comsol_fig321_bcc_444_mesh_p1_f5_150",
    "comsol_fig321_bcc_444_mesh_p1_100g_f5_150",
    "comsol_fig321_bcc_444_mesh_p1_300g_f5_150",
    "comsol_fig321_bcc_444_mesh_p1_500g_f5_150"
)

foreach ($slug in $slugs) {
    $localDir = Join-Path $LocalRoot "output\comsol_jobs\$slug"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    $remoteDir = "$RemoteRoot/output/comsol_jobs/$slug"
    foreach ($pat in @(
        "${slug}_transmissibility.csv",
        "${slug}_vld.csv",
        "${slug}_vld.png",
        "${slug}_fig322_vld.png",
        "${slug}_isolation_summary.json",
        "${slug}_harmonic_plotgroups.json",
        "case_manifest.json"
    )) {
        try {
            scp "${Server}:${remoteDir}/$pat" $localDir 2>$null | Out-Null
        } catch {
            # optional artifact
        }
    }
}

$compositeLocal = Join-Path $LocalRoot "output\comsol_jobs\bcc_payload_composite"
New-Item -ItemType Directory -Force -Path $compositeLocal | Out-Null
try {
    scp "${Server}:${RemoteRoot}/output/comsol_jobs/bcc_payload_composite/*" $compositeLocal 2>$null | Out-Null
} catch {
    # composite may not exist until batch finishes
}

Set-Location $LocalRoot
py -3 scripts/plot_comsol_vld_payload_overlay.py --bcc-f5-150 --paper-bcc --with-trans

Write-Host "Done."
Write-Host "Overlay: output/comsol_jobs/bcc_payload_composite/bcc_p1_f5_150_payload_overlay_vld.png"
