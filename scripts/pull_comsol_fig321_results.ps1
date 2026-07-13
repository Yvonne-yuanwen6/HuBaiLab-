# Pull Fig. 3.21 COMSOL results from server and run local post-process.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$LocalRoot = "d:\HuBaiLab"
)

$ErrorActionPreference = "Stop"
$slugs = @(
    "comsol_fig321_bcc_444",
    "comsol_fig321_af2q05_444",
    "comsol_fig321_af2q1_444",
    "comsol_fig321_af2q15_444"
)

foreach ($slug in $slugs) {
    $localDir = Join-Path $LocalRoot "output\comsol_jobs\$slug"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    $remoteDir = "$RemoteRoot/output/comsol_jobs/$slug"
    scp "${Server}:${remoteDir}/${slug}_eigenfrequencies.csv" $localDir 2>$null
    scp "${Server}:${remoteDir}/${slug}_mode_shapes.json" $localDir 2>$null
    scp "${Server}:${remoteDir}/${slug}_mode0*.png" $localDir 2>$null
    scp "${Server}:${remoteDir}/case_manifest.json" $localDir 2>$null
    scp "${Server}:${remoteDir}/${slug}_isolation_summary.json" $localDir 2>$null
}

$compositeLocal = Join-Path $LocalRoot "output\comsol_jobs\fig321_composite"
New-Item -ItemType Directory -Force -Path $compositeLocal | Out-Null
scp "${Server}:${RemoteRoot}/output/comsol_jobs/fig321_composite/fig321_eigenmodes.png" $compositeLocal 2>$null

Set-Location $LocalRoot
py -3 scripts/plot_comsol_fig321.py --out output/comsol_jobs/fig321_composite/fig321_eigenmodes.png

foreach ($slug in $slugs) {
    $csv = Join-Path $LocalRoot "output\comsol_jobs\$slug\${slug}_eigenfrequencies.csv"
    if (Test-Path $csv) {
        py -3 scripts/plot_comsol_eigenfrequencies.py $csv
    }
}

Write-Host "Done. Composite: output/comsol_jobs/fig321_composite/fig321_eigenmodes.png"
