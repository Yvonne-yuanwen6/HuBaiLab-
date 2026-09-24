# Canonical SSH / remote repo paths for the art workstation.
# 2026-09-15: mechanical disk /media/art/file/... is retired (dead). Do not use it.
# Interim remote root = SSD bootstrap copy until a new path is announced.
# Override without editing files:
#   $env:HU_BAI_REMOTE_HOST = "art@172.20.200.93"
#   $env:HU_BAI_REMOTE_ROOT = "/home/art/HuBaiLab_ssd"

. (Join-Path $PSScriptRoot "local_config.ps1")

if (-not $env:HU_BAI_REMOTE_HOST) {
    $env:HU_BAI_REMOTE_HOST = "art@172.20.200.93"
}
if (-not $env:HU_BAI_REMOTE_ROOT) {
    $env:HU_BAI_REMOTE_ROOT = "/home/art/HuBaiLab_ssd"
}

$HuBaiRemoteHost = $env:HU_BAI_REMOTE_HOST
$HuBaiRemoteRoot = $env:HU_BAI_REMOTE_ROOT
