# Copy CAE-tet export folders to Linux server (INP + manifest + meta only).
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$CaseSuffix = "cae_tet1p2mm80_5mmin_noself"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$dirs = Get-ChildItem (Join-Path $Root "output\export") -Directory |
    Where-Object { $_.Name -like "*_${CaseSuffix}" }

if (-not $dirs) {
    Write-Host "[ERROR] No export dirs matching *_${CaseSuffix}" -ForegroundColor Red
    exit 1
}

Write-Host "=== Sync CAE tet cases -> $RemoteHost ===" -ForegroundColor Cyan
foreach ($d in $dirs) {
    Write-Host "  $($d.Name)"
    scp -r $d.FullName "${RemoteHost}:${RemoteRoot}/output/export/"
}
Write-Host "OK. Submit on server, e.g.:" -ForegroundColor Green
$slugs = ($dirs | ForEach-Object { $_.Name }) -join ','
Write-Host "  ssh $RemoteHost 'cd $RemoteRoot && bash scripts/linux/submit_queue.sh --slugs-csv `"$slugs`" --cpus 32 --memory-mb 131072'"
