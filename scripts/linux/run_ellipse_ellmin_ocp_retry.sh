#!/usr/bin/env bash
# Retry ellmin (short-axis) ellipse 444 Q=1.0 + Q=1.5 using OCP-only routes.
#
# Q=1.0: OCP multi-strategy seed sweep -> OCP layered array fuse
# Q=1.5: OCP inter-slab sweep on existing z-slabs (seed already OK)
#
#   bash scripts/linux/run_ellipse_ellmin_ocp_retry.sh
#   nohup bash scripts/linux/run_ellipse_ellmin_ocp_retry.sh >> output/logs/ellipse_ellmin_ocp_retry_nohup.log 2>&1 &
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/ellipse_ellmin_ocp_retry.log}"
SEED_DIR="${SEED_DIR:-$ROOT/output/cad/_unitcell_paper_box_cut_ellipse_eqarea}"
NICE_LEVEL="${NICE_LEVEL:-10}"

mkdir -p "$(dirname "$LOG")" "$SEED_DIR"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
else
  PY=python3
fi

seed_q1() {
  "$PY" -c "
import sys; sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(cell_size=20, rod_diameter=2.582, amplitude=2, period_factor=1.0, n_segments=24)
gen.build_unitcell()
print('$SEED_DIR/unitcell_' + gen.variant_name.lower() + '_paper_box_ellipse_ellmin_eqarea.step')
"
}

array_dir_q1() {
  echo "$ROOT/output/cad/_paper_box_array_ellipse_eqarea_q1p0"
}

array_step_q1() {
  "$PY" -c "
import sys; sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(cell_size=20, rod_diameter=2.582, amplitude=2, period_factor=1.0, n_segments=24)
gen.build_unitcell()
slug = f'hu_bai_{gen.variant_name.lower()}_L20_4x4x4'
print('$(array_dir_q1)/' + slug + '_paper_box_ellipse_eqarea_ellmin_array.step')
"
}

seed_ok() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  local vols
  vols="$("$PY" -c "
from src.export.paper_box_array_fuse import _count_seed_volumes
print(_count_seed_volumes('$path'))
")"
  [[ "$vols" == "1" ]]
}

log "=== ellmin OCP retry start ==="

# --- Q=1.0 seed (OCP-only sweep) ---
Q1_SEED="$(seed_q1)"
log "Q=1.0 OCP seed sweep -> $Q1_SEED"
if seed_ok "$Q1_SEED"; then
  log "Q=1.0 seed already vol=1: $Q1_SEED"
else
  rm -f "$Q1_SEED"
  set +e
  nice -n "$NICE_LEVEL" "$PY" scripts/export_q1_ellipse_paper_box_seed.py \
    --Q 1.0 \
    --ellipse-align minor \
    --ocp-only \
    --skip-gmsh \
    --out-step "$Q1_SEED" \
    2>&1 | tee -a "$LOG"
  q1_seed_rc=${PIPESTATUS[0]}
  set -e
  if [[ "$q1_seed_rc" -ne 0 ]] || ! seed_ok "$Q1_SEED"; then
    log "FAIL: Q=1.0 OCP seed export"
  else
    log "OK: Q=1.0 OCP seed"
  fi
fi

# --- Q=1.0 array fuse (OCP) ---
Q1_ARRAY="$(array_step_q1)"
Q1_DIR="$(array_dir_q1)"
if seed_ok "$Q1_SEED"; then
  mkdir -p "$Q1_DIR"
  if [[ -f "$Q1_ARRAY" ]] && [[ "$(stat -c%s "$Q1_ARRAY" 2>/dev/null || echo 0)" -gt 1048576 ]]; then
    log "skip Q=1.0 array (exists): $Q1_ARRAY"
  else
    log "Q=1.0 OCP array fuse -> $Q1_ARRAY"
    rm -f "$Q1_DIR"/zslab_iz*_4x4_paper_box_fused.step "$Q1_ARRAY"
    rm -rf "$Q1_DIR/.work_zslab_cells"
    set +e
    nice -n "$NICE_LEVEL" "$PY" scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py \
      --Q 1.0 \
      --seed "$Q1_SEED" \
      --out-dir "$Q1_DIR" \
      --backend ocp \
      --force \
      2>&1 | tee -a "$LOG"
    q1_fuse_rc=${PIPESTATUS[0]}
    set -e
    DEFAULT="$Q1_DIR/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
    if [[ -f "$DEFAULT" && ! -f "$Q1_ARRAY" ]]; then
      mv -f "$DEFAULT" "$Q1_ARRAY"
    fi
    if [[ "$q1_fuse_rc" -eq 0 && -f "$Q1_ARRAY" ]]; then
      ls -lh "$Q1_ARRAY" | tee -a "$LOG"
      log "OK: Q=1.0 OCP array"
    else
      log "FAIL: Q=1.0 OCP array fuse (rc=$q1_fuse_rc)"
    fi
  fi
else
  log "SKIP Q=1.0 array (no valid seed)"
fi

# --- Q=1.5 inter-slab (OCP sweep on existing z-slabs) ---
log "Q=1.5 OCP inter-slab sweep"
set +e
nice -n "$NICE_LEVEL" "$PY" scripts/retry_ellipse_ellmin_ocp_interslab.py --Q 1.5 2>&1 | tee -a "$LOG"
q15_rc=${PIPESTATUS[0]}
set -e
if [[ "$q15_rc" -eq 0 ]]; then
  log "OK: Q=1.5 OCP inter-slab"
else
  log "FAIL: Q=1.5 OCP inter-slab (rc=$q15_rc)"
fi

log "=== ellmin OCP retry done ==="
