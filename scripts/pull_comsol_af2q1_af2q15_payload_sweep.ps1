# Pull AF2Q1 + AF2Q1.5 payload sweep results from server.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$LocalRoot = "d:\HuBaiLab"
)

$ErrorActionPreference = "Continue"
$variants = @(
    @{ key = "af2q1"; slugs = @(
        "comsol_fig321_af2q1_444_mesh_p1_f5_150",
        "comsol_fig321_af2q1_444_mesh_p1_100g_f5_150",
        "comsol_fig321_af2q1_444_mesh_p1_300g_f5_150",
        "comsol_fig321_af2q1_444_mesh_p1_500g_f5_150"
    ); composite = "af2q1_payload_composite"; overlay = "af2q1_p1_f5_150_payload_overlay" },
    @{ key = "af2q15"; slugs = @(
        "comsol_fig321_af2q15_444_mesh_p1_f5_150",
        "comsol_fig321_af2q15_444_mesh_p1_100g_f5_150",
        "comsol_fig321_af2q15_444_mesh_p1_300g_f5_150",
        "comsol_fig321_af2q15_444_mesh_p1_500g_f5_150"
    ); composite = "af2q15_payload_composite"; overlay = "af2q15_p1_f5_150_payload_overlay" }
)

foreach ($v in $variants) {
    foreach ($slug in $v.slugs) {
        $localDir = Join-Path $LocalRoot "output\comsol_jobs\$slug"
        New-Item -ItemType Directory -Force -Path $localDir | Out-Null
        $remoteDir = "$RemoteRoot/output/comsol_jobs/$slug"
        scp "${Server}:${remoteDir}/${slug}_transmissibility.csv" $localDir 2>$null
    }
    $compositeLocal = Join-Path $LocalRoot "output\comsol_jobs\$($v.composite)"
    New-Item -ItemType Directory -Force -Path $compositeLocal | Out-Null
    scp "${Server}:${RemoteRoot}/output/comsol_jobs/$($v.composite)/*" $compositeLocal 2>$null
}

Set-Location $LocalRoot
foreach ($v in $variants) {
    py -3 scripts/plot_comsol_vld_payload_overlay.py --preset f5-150 --variant $v.key `
        --out-dir "output/comsol_jobs/$($v.composite)" --slug $v.overlay --with-trans
}

Write-Host "Done."
Write-Host "AF2Q1:  output/comsol_jobs/af2q1_payload_composite/af2q1_p1_f5_150_payload_overlay_vld.png"
Write-Host "AF2Q1.5: output/comsol_jobs/af2q15_payload_composite/af2q15_p1_f5_150_payload_overlay_vld.png"
