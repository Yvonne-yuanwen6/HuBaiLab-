#!/usr/bin/env bash
# Continue q05_c10m_s06r3_el_s45 -> 75% via Explicit restart (after backup).
#
#   bash scripts/linux/backup_case_slug.sh q05_c10m_s06r3_el_s45 pre_restart_20260702
#   bash scripts/linux/run_paperbox_q05_c10m_s45to75_restart.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q05_c10m_s06r3_el_s75_cont.log"
FROM_SLUG="q05_c10m_s06r3_el_s45"
TO_SLUG="q05_c10m_s06r3_el_s75_cont"
CPUS="${Q05_C10M_CPUS:-48}"
MEM="${Q05_C10M_MEMORY_MB:-262144}"
TARGET_STRAIN="${Q05_C10M_STRAIN:-0.75}"

exec > >(tee -a "$LOG") 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] restart continue $FROM_SLUG -> $TARGET_STRAIN slug=$TO_SLUG"

[[ -f "output/jobs/$FROM_SLUG/${FROM_SLUG}.res" ]] || {
  echo "Missing ${FROM_SLUG}.res — run backup first, do not overwrite source job."
  exit 1
}

bash scripts/linux/run_paperbox_variant.sh --Q 0.5 \
  --variant-suffix c10m_s06r3_el_s75_cont \
  --short-slug "$TO_SLUG" \
  --restart-from-slug "$FROM_SLUG" \
  --continue-to-strain "$TARGET_STRAIN" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --submit-background

echo "[$(date '+%Y-%m-%d %H:%M:%S')] submitted restart continue $TO_SLUG"
