# Upload Q=1 unitcell seed and start server layered fuse (iz0 fuse -> copy x3 -> merge).
param(
    [string]$SeedLocal = "",
    [switch]$UseGmshSeed,
    [switch]$StepwiseOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "remote_config.ps1")

$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $SeedLocal) {
    if ($UseGmshSeed) {
        $SeedLocal = Join-Path $LocalRoot "output\cad\_unitcell_paper_box_cut\unitcell_sfbls_af2q1_paper_box_gmsh_seed.step"
    } else {
        $SeedLocal = Join-Path $LocalRoot "output\cad\_unitcell_paper_box_cut\unitcell_sfbls_af2q1_paper_box.step"
    }
}
if (-not (Test-Path $SeedLocal)) {
    throw "Seed not found: $SeedLocal"
}

$SeedRemote = "$($HuBaiRemoteRoot)/output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q1_paper_box.step"
Write-Host "Upload seed -> $SeedRemote" -ForegroundColor Cyan
scp $SeedLocal "${HuBaiRemoteHost}:${SeedRemote}"

Write-Host "Sync src ..." -ForegroundColor Yellow
scp -r (Join-Path $LocalRoot "src/.") "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/src/"

$forceEnv = if ($Force) { "FORCE=1" } else { "FORCE=0" }
if ($StepwiseOnly) {
    $cmd = @"
cd '$HuBaiRemoteRoot' && mkdir -p output/logs && \
nohup env Q=1.0 $forceEnv .venv/bin/python3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 1.0 --stepwise-only \
>> output/logs/paperbox_stepwise_q1p0_launch.log 2>&1 &
echo started stepwise pid=\$!
"@
} else {
    $cmd = @"
cd '$HuBaiRemoteRoot' && mkdir -p output/logs && \
nohup env Q=1.0 $forceEnv bash scripts/linux/run_paper_box_layered_safe.sh \
>> output/logs/paperbox_layered_fuse_q1p0_launch.log 2>&1 &
echo started layered pid=\$!
"@
}

Write-Host "Launch on server ..." -ForegroundColor Cyan
ssh $HuBaiRemoteHost $cmd

Write-Host "Tail log: ssh $HuBaiRemoteHost tail -f $HuBaiRemoteRoot/output/logs/paperbox_layered_fuse_q1p0.log" -ForegroundColor Green
