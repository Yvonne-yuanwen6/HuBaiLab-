#!/usr/bin/env bash
# Retry ellipse 444 Q=1.5: multi-route seed export (both_end + OCP glue) then array fuse.
# Q=0/Q=0.5 already done; Q=1.0 skipped (known fuse issue).
#
#   bash scripts/linux/run_ellipse_paper_box_444_retry_q15.sh
#   nohup bash scripts/linux/run_ellipse_paper_box_444_retry_q15.sh >> output/logs/ellipse_paper_box_444_retry_q15.log 2>&1 &
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/ellipse_paper_box_444_retry_q15.log}"
SEED_DIR="${SEED_DIR:-$ROOT/output/cad/_unitcell_paper_box_cut_ellipse_eqarea}"
OUT_DIR="$ROOT/output/cad/_paper_box_array_ellipse_eqarea_q1p5"
NICE_LEVEL="${NICE_LEVEL:-10}"
FORCE="${FORCE:-0}"

if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
else
  PY=python3
fi

mkdir -p "$(dirname "$LOG")" "$SEED_DIR" "$OUT_DIR"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

seed_path() {
  "$PY" -c "
import sys; sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(cell_size=20, rod_diameter=2.582, amplitude=2, period_factor=1.5, n_segments=24)
gen.build_unitcell()
print('$SEED_DIR/unitcell_' + gen.variant_name.lower() + '_paper_box_ellipse_ellmin_eqarea.step')
"
}

array_step_path() {
  "$PY" -c "
import sys; sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(cell_size=20, rod_diameter=2.582, amplitude=2, period_factor=1.5, n_segments=24)
gen.build_unitcell()
slug = f'hu_bai_{gen.variant_name.lower()}_L20_4x4x4'
print('$OUT_DIR/' + slug + '_paper_box_ellipse_eqarea_array.step')
"
}

rename_array() {
  local out def slug
  out="$(array_step_path)"
  slug="$(basename "$out" _paper_box_ellipse_eqarea_array.step)"
  def="$OUT_DIR/${slug}_paper_box_array.step"
  if [[ -f "$def" && ! -f "$out" ]]; then
    mv -f "$def" "$out"
    log "Renamed -> $out"
  fi
  ls -lh "$out" 2>/dev/null || ls -lh "$def" 2>/dev/null || true
}

log "=== ellipse 444 retry Q=1.5 start (multi-route seed) ==="

SEED="$(seed_path)"
if [[ "$FORCE" == "1" ]]; then
  rm -f "$SEED"
  rm -f "$OUT_DIR"/*.step
  rm -rf "$OUT_DIR/.work_zslab_cells"
fi

log "EXPORT Q=1.5 seed (multi-route) -> $SEED"
set +e
nice -n "$NICE_LEVEL" "$PY" scripts/export_q1_ellipse_paper_box_seed.py \
  --Q 1.5 \
  --skip-gmsh \
  --out-step "$SEED" \
  2>&1 | tee -a "$LOG"
seed_rc=${PIPESTATUS[0]}
set -e
if [[ "$seed_rc" -ne 0 ]]; then
  log "FAIL: Q=1.5 elliptic seed export (rc=$seed_rc)"
  exit "$seed_rc"
fi

vols="$("$PY" -c "
from src.export.paper_box_array_fuse import _count_seed_volumes
print(_count_seed_volumes('$SEED'))
")"
log "Q=1.5 seed volumes=$vols"
if [[ "$vols" -ne 1 ]]; then
  log "ABORT: seed must be 1 volume, got $vols"
  exit 1
fi

log "FUSE Q=1.5 array -> $OUT_DIR"
set +e
nice -n "$NICE_LEVEL" "$PY" scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py \
  --Q 1.5 \
  --seed "$SEED" \
  --out-dir "$OUT_DIR" \
  --backend ocp \
  --force \
  2>&1 | tee -a "$LOG"
fuse_rc=${PIPESTATUS[0]}
set -e
if [[ "$fuse_rc" -ne 0 ]]; then
  log "FAIL: Q=1.5 array fuse (rc=$fuse_rc)"
  exit "$fuse_rc"
fi

rename_array
log "=== retry Q=1.5 ALL DONE ==="
