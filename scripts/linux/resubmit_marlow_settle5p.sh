#!/usr/bin/env bash
# Stop stuck fig33_v2_marlow (nosettle) and resubmit settle5p fix.
set -euo pipefail
ROOT="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

stop_tag() {
  local tag="$1"
  echo "=== stop $tag ==="
  ps aux | awk -v t="$tag" '/\/bin\/explicit/ && $0 ~ t {print $2}' | sort -u | xargs -r kill -TERM 2>/dev/null || true
  sleep 4
  ps aux | awk -v t="$tag" '/\/bin\/explicit/ && $0 ~ t {print $2}' | sort -u | xargs -r kill -KILL 2>/dev/null || true
  ps aux | awk -v t="$tag" '/run_paperbox/ && $0 ~ t {print $2}' | sort -u | xargs -r kill -KILL 2>/dev/null || true
  find "$ROOT/output/jobs" -name '*.lck' 2>/dev/null | while read -r lck; do
    case "$lck" in *"$tag"*) rm -f "$lck"; echo "removed $lck" ;;
    esac
  done
  n=$(ps aux | awk -v t="$tag" '/\/bin\/explicit/ && $0 ~ t' | wc -l)
  echo "remaining explicit ranks for $tag: $n"
}

stop_tag "paperbox_fig33_v2_marlow"

SLUG=hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow
echo "=== clear job dir $SLUG ==="
rm -rf "$ROOT/output/jobs/$SLUG"

echo "=== preflight 48c ==="
bash scripts/linux/check_submit_resources.sh --root . --cpus 48 --memory-mb 262144

echo "=== resubmit marlow settle5p ==="
Q05_V2_CPUS=48 Q05_V2_MEMORY_MB=262144 bash scripts/linux/run_paperbox_q05_fig33_v2_marlow.sh

SLUG=hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow
sleep 8
if [[ -f "output/jobs/$SLUG/$SLUG.lck" ]] || pgrep -f "mpiexec.hydra.*$SLUG" >/dev/null 2>&1; then
  echo "=== RUNNING $SLUG ==="
  head -8 "output/jobs/$SLUG/$SLUG.sta" 2>/dev/null || true
  grep -E '^[[:space:]]+[1-9]' "output/jobs/$SLUG/$SLUG.sta" 2>/dev/null | tail -1 || true
else
  echo "=== WARN: no lck yet — check log ==="
  tail -15 output/logs/paperbox_q05_fig33_v2_marlow.log
  exit 1
fi
