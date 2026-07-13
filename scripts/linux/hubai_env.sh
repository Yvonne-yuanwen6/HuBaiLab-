# Canonical repo root on the art workstation (mechanical disk under XiangLang).
# Source from other scripts:  . "$(cd "$(dirname "$0")" && pwd)/hubai_env.sh"
# Override: export HU_BAI_REMOTE_ROOT=/other/path

HU_BAI_REMOTE_ROOT="${HU_BAI_REMOTE_ROOT:-/media/art/file/XiangLang/Lattice/LWY/HuBaiLab}"
HU_BAI_REMOTE_HOST="${HU_BAI_REMOTE_HOST:-art@172.20.200.93}"

# Optional Temurin JDK 11 (user install). MPh + COMSOL 5.6 uses COMSOL's bundled JRE 8;
# keep jpype1<1.6 (see requirements.txt). Do not set JAVA_HOME here for MPh workflows.
HU_BAI_JAVA11_HOME="${HU_BAI_JAVA11_HOME:-/home/art/APP/jdk-11.0.27+6}"
