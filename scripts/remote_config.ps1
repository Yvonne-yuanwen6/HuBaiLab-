# Canonical SSH / remote repo paths for the art workstation (mechanical disk).
# Override without editing files:
#   $env:HU_BAI_REMOTE_HOST = "art@172.20.200.93"
#   $env:HU_BAI_REMOTE_ROOT = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"

if (-not $env:HU_BAI_REMOTE_HOST) {
    $env:HU_BAI_REMOTE_HOST = "art@172.20.200.93"
}
if (-not $env:HU_BAI_REMOTE_ROOT) {
    $env:HU_BAI_REMOTE_ROOT = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
}

$HuBaiRemoteHost = $env:HU_BAI_REMOTE_HOST
$HuBaiRemoteRoot = $env:HU_BAI_REMOTE_ROOT
