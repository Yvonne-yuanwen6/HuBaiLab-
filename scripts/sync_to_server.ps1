# Sync scripts + src (and optional docs) to the art workstation repo.
param(
    [switch]$IncludeDocs,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "remote_config.ps1")

$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dest = "${HuBaiRemoteHost}:${HuBaiRemoteRoot}"

Write-Host "=== Sync HuBaiLab -> $Dest ===" -ForegroundColor Cyan
Write-Host "  local:  $LocalRoot"
Write-Host "  remote: $HuBaiRemoteRoot"

$Paths = @(
    (Join-Path $LocalRoot "scripts"),
    (Join-Path $LocalRoot "src")
)
if ($IncludeDocs) {
    $Paths += Join-Path $LocalRoot "docs"
}

foreach ($p in $Paths) {
    if (-not (Test-Path $p)) {
        Write-Warning "Skip missing: $p"
        continue
    }
    $rel = Split-Path $p -Leaf
    $target = "$Dest/$rel"
    if ($DryRun) {
        Write-Host "[dry-run] scp -r $p $target"
    } else {
        Write-Host "scp -r $rel ..." -ForegroundColor Yellow
        # Trailing /. merges into existing remote dir (preserves scripts/linux/ layout).
        scp -r "$p/." $target/
    }
}

if (-not $DryRun) {
    ssh $HuBaiRemoteHost "test -f '$HuBaiRemoteRoot/scripts/linux/check_submit_resources.sh' && test -f '$HuBaiRemoteRoot/scripts/linux/hubai_env.sh' && echo 'remote OK: scripts/linux present'"
}

Write-Host "Done." -ForegroundColor Green
