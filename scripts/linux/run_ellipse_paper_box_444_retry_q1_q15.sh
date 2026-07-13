#!/usr/bin/env bash
# Retry ellipse 444 Q=1.0 and Q=1.5: multi-route seed export + OCP array fuse.
# Q=0/Q=0.5 already done locally.
#
#   bash scripts/linux/run_ellipse_paper_box_444_retry_q1_q15.sh
#   nohup bash scripts/linux/run_ellipse_paper_box_444_retry_q1_q15.sh >> output/logs/ellipse_paper_box_444_retry_q1_q15.log 2>&1 &
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/ellipse_paper_box_444_retry_q1_q15.log}"
SEED_DIR="${SEED_DIR:-$ROOT/output/cad/_unitcell_paper_box_cut_ellipse_eqarea}"
NICE_LEVEL="${NICE_LEVEL:-10}"
FORCE="${FORCE:-1}"

if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
else
  PY=python3
fi

mkdir -p "$(dirname "$LOG")" "$SEED_DIR"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

seed_path_for_q() {
  "$PY" -c "
import sys; sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(cell_size=20, rod_diameter=2.582, amplitude=2, period_factor=float('$1'), n_segments=24)
gen.build_unitcell()
print('$SEED_DIR/unitcell_' + gen.variant_name.lower() + '_paper_box_ellipse_ellmin_eqarea.step')
"
}

array_dir_for_q() {
  local tag="${1//./p}"
  echo "$ROOT/output/cad/_paper_box_array_ellipse_eqarea_q${tag}"
}

rename_array() {
  local q="$1" dir="$2"
  local out def slug
  out="$("$PY" -c "
import sys; sys.path.insert(0,'$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen=HuBaiLatticeGenerator(cell_size=20,rod_diameter=2.582,amplitude=2,period_factor=float('$q'),n_segments=24)
gen.build_unitcell()
slug=f'hu_bai_{gen.variant_name.lower()}_L20_4x4x4'
print(f'$dir/{slug}_paper_box_ellipse_eqarea_array.step')
")"
  slug="$(basename "$out" _paper_box_ellipse_eqarea_array.step)"
  def="$dir/${slug}_paper_box_array.step"
  if [[ -f "$def" && ! -f "$out" ]]; then mv -f "$def" "$out"; fi
  ls -lh "$out" 2>/dev/null || ls -lh "$def" 2>/dev/null || true
}

export_and_fuse_q() {
  local q="$1"
  local skip_gmsh_flag=()
  if [[ "$q" == "1.5" ]]; then
    skip_gmsh_flag=(--skip-gmsh)
  fi

  local seed dir
  seed="$(seed_path_for_q "$q")"
  dir="$(array_dir_for_q "$q")"
  mkdir -p "$dir"

  if [[ "$FORCE" == "1" ]]; then
    rm -f "$seed"
    rm -f "$dir"/*.step
    rm -rf "$dir/.work_zslab_cells"
  fi

  log "EXPORT Q=$q seed (multi-route) -> $seed"
  set +e
  nice -n "$NICE_LEVEL" "$PY" scripts/export_q1_ellipse_paper_box_seed.py \
    --Q "$q" \
    "${skip_gmsh_flag[@]}" \
    --out-step "$seed" \
    2>&1 | tee -a "$LOG"
  local seed_rc=${PIPESTATUS[0]}
  set -e
  if [[ "$seed_rc" -ne 0 ]]; then
    log "FAIL: Q=$q elliptic seed export (rc=$seed_rc)"
    return "$seed_rc"
  fi

  local vols
  vols="$("$PY" -c "
from src.export.paper_box_array_fuse import _count_seed_volumes
print(_count_seed_volumes('$seed'))
")"
  log "Q=$q seed volumes=$vols"
  if [[ "$vols" -ne 1 ]]; then
    log "ABORT Q=$q: seed must be 1 volume, got $vols"
    return 1
  fi

  log "FUSE Q=$q array -> $dir"
  set +e
  nice -n "$NICE_LEVEL" "$PY" scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py \
    --Q "$q" \
    --seed "$seed" \
    --out-dir "$dir" \
    --backend ocp \
    --force \
    2>&1 | tee -a "$LOG"
  local fuse_rc=${PIPESTATUS[0]}
  set -e
  if [[ "$fuse_rc" -ne 0 ]]; then
    log "FAIL: Q=$q array fuse (rc=$fuse_rc)"
    return "$fuse_rc"
  fi

  rename_array "$q" "$dir"
  log "OK Q=$q"
}

log "=== ellipse 444 retry Q=1.0 + Q=1.5 start ==="

failed=0
for q in 1.0 1.5; do
  if ! export_and_fuse_q "$q"; then
    failed=1
    log "Q=$q failed; continuing"
  fi
done

if [[ "$failed" -ne 0 ]]; then
  log "=== retry PARTIAL/FAILED ==="
  exit 1
fi

log "=== retry Q=1.0 + Q=1.5 ALL DONE ==="
