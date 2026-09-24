# Canonical repo root on the art workstation.
# 2026-09-15: mechanical disk /media/art/file/... is retired (dead). Do not use it.
# Interim remote root = SSD bootstrap copy until a new path is announced.
# Source from other scripts:  . "$(cd "$(dirname "$0")" && pwd)/hubai_env.sh"
# Override: export HU_BAI_REMOTE_ROOT=/other/path

HU_BAI_REMOTE_ROOT="${HU_BAI_REMOTE_ROOT:-/home/art/HuBaiLab_ssd}"
HU_BAI_REMOTE_HOST="${HU_BAI_REMOTE_HOST:-art@172.20.200.93}"

# Optional Temurin JDK 11 (user install). MPh + COMSOL 5.6 uses COMSOL's bundled JRE 8;
# keep jpype1<1.6 (see requirements.txt). Do not set JAVA_HOME here for MPh workflows.
HU_BAI_JAVA11_HOME="${HU_BAI_JAVA11_HOME:-/home/art/APP/jdk-11.0.27+6}"
