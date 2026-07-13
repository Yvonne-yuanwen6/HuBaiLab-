#!/usr/bin/env bash
# Export equal-area elliptic-strut 4x4x4 paper_box arrays for Q=0, 0.5, 1.0, 1.5.
#
# Ellipse: MAJOR axis || +Z (ellmaj), area = pi mm^2 (same as circle d=2 mm).
# Nominal aspect 2:1.2 scaled -> d_major ~2.582 mm, d_minor ~1.549 mm.
#
#   bash scripts/linux/run_ellipse_paper_box_444_batch_ellmaj.sh
#   nohup bash scripts/linux/run_ellipse_paper_box_444_batch_ellmaj.sh >> output/logs/ellipse_paper_box_444_batch_ellmaj.log 2>&1 &
#
# Env: FORCE=1 MIN_FREE_GB=80 Q_LIST="0 0.5 1.0 1.5"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/ellipse_paper_box_444_batch_ellmaj.log}"
SEED_DIR="${SEED_DIR:-$ROOT/output/cad/_unitcell_paper_box_cut_ellipse_eqarea_ellmaj}"
ARRAY_PREFIX="${ARRAY_PREFIX:-_paper_box_array_ellipse_eqarea_ellmaj}"
ELLIPSE_ALIGN="${ELLIPSE_ALIGN:-major}"
ALIGN_TAG="${ALIGN_TAG:-ellmaj}"
FORCE="${FORCE:-0}"
FORCE_SEEDS="${FORCE_SEEDS:-0}"
MIN_FREE_GB="${MIN_FREE_GB:-80}"
NICE_LEVEL="${NICE_LEVEL:-10}"
Q_LIST="${Q_LIST:-0 0.5 1.0 1.5}"

mkdir -p "$(dirname "$LOG")" "$SEED_DIR"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

free_gb() { free -g | awk 'NR==2 {print $(NF)}'; }

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]] && "$ROOT/.venv/bin/python3" -c 'import sys' 2>/dev/null; then
    echo "$ROOT/.venv/bin/python3"
  elif [[ -x /home/art/conda/bin/python3 ]]; then
    echo /home/art/conda/bin/python3
  else
    echo python3
  fi
}

preflight() {
  local avail
  avail="$(free_gb)"
  log "preflight: available_mem=${avail}G (need >=${MIN_FREE_GB}G)"
  if [[ "$avail" -lt "$MIN_FREE_GB" ]]; then
    log "ABORT: insufficient free memory"
    exit 2
  fi
  if ! "$PY" -c 'import gmsh' 2>/dev/null; then
    log "installing gmsh..."
    "$PY" -m pip install -q 'gmsh>=4.12'
  fi
  if ! "$PY" -c 'from OCP.STEPControl import STEPControl_Reader' 2>/dev/null; then
    log "installing cadquery-ocp..."
    "$PY" -m pip install -q cadquery-ocp
  fi
}

seed_path_for_q() {
  "$PY" -c "
import sys
sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(
    cell_size=20.0, rod_diameter=2.582, amplitude=2.0,
    period_factor=float('$1'), n_segments=24,
)
gen.build_unitcell()
slug = gen.variant_name.lower()
print('$SEED_DIR/unitcell_' + slug + '_paper_box_ellipse_${ALIGN_TAG}_eqarea.step')
"
}

array_dir_for_q() {
  local q="$1"
  local tag="${q//./p}"
  echo "$ROOT/output/cad/${ARRAY_PREFIX}_q${tag}"
}

array_step_for_q() {
  local q="$1"
  local dir
  dir="$(array_dir_for_q "$q")"
  "$PY" -c "
import sys
sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(
    cell_size=20.0, rod_diameter=2.582, amplitude=2.0,
    period_factor=float('$q'), n_segments=24,
)
gen.build_unitcell()
slug = f\"hu_bai_{gen.variant_name.lower()}_L20_4x4x4\"
print('$dir/' + slug + '_paper_box_ellipse_eqarea_${ALIGN_TAG}_array.step')
"
}

seed_ok() {
  local q="$1"
  local seed
  seed="$(seed_path_for_q "$q")"
  [[ -f "$seed" ]] || return 1
  local vols
  vols="$("$PY" -c "
from src.export.paper_box_array_fuse import _count_seed_volumes
print(_count_seed_volumes('$seed'))
")"
  [[ "$vols" == "1" ]]
}

export_seeds() {
  local q
  for q in $Q_LIST; do
    if [[ "$FORCE_SEEDS" != "1" ]] && seed_ok "$q"; then
      log "skip seed Q=$q (already vol=1): $(seed_path_for_q "$q")"
      continue
    fi
    if [[ "$q" == "1.0" || "$q" == "1" || "$q" == "1.5" ]]; then
      log "=== export Q=$q elliptic seed (multi-route, align=${ELLIPSE_ALIGN}) ==="
      rm -f "$(seed_path_for_q "$q")"
      set +e
      nice -n "$NICE_LEVEL" "$PY" scripts/export_q1_ellipse_paper_box_seed.py \
        --Q "$q" \
        --ellipse-align "$ELLIPSE_ALIGN" \
        --out-dir "$SEED_DIR" \
        $( [[ "$q" == "1.5" ]] && echo --skip-gmsh ) \
        --out-step "$(seed_path_for_q "$q")" \
        2>&1 | tee -a "$LOG"
      q_rc=${PIPESTATUS[0]}
      set -e
      if [[ "$q_rc" -ne 0 ]]; then
        log "WARN: Q=$q elliptic seed export failed (rc=$q_rc); will skip Q=$q array fuse"
      fi
      continue
    fi
    log "=== export Q=$q elliptic unitcell seed (gmsh, align=${ELLIPSE_ALIGN}) ==="
    nice -n "$NICE_LEVEL" "$PY" scripts/export_unitcell_paper_box_cut.py \
      --Q "$q" \
      --solid-profile ellipse \
      --ellipse-align "$ELLIPSE_ALIGN" \
      --compression-axis z \
      --target-area-pi \
      --out-dir "$SEED_DIR" \
      2>&1 | tee -a "$LOG"
  done
}

fuse_one() {
  local q="$1"
  local seed out_dir array_step
  seed="$(seed_path_for_q "$q")"
  out_dir="$(array_dir_for_q "$q")"
  array_step="$(array_step_for_q "$q")"
  mkdir -p "$out_dir"

  if [[ "$FORCE" != "1" && -f "$array_step" ]]; then
    local sz
    sz=$(stat -c%s "$array_step" 2>/dev/null || echo 0)
    if [[ "$sz" -gt 1048576 ]]; then
      log "skip array Q=$q (exists): $array_step"
      return 0
    fi
  fi

  if [[ ! -f "$seed" ]]; then
    log "ABORT Q=$q: missing seed $seed"
    return 1
  fi

  local vols
  vols="$("$PY" -c "
from src.export.paper_box_array_fuse import _count_seed_volumes
print(_count_seed_volumes('$seed'))
")"
  log "Q=$q seed volumes=$vols ($seed)"
  if [[ "$vols" -ne 1 ]]; then
    log "ABORT Q=$q: array fuse requires 1-volume seed, got $vols"
    return 1
  fi

  if [[ "$FORCE" == "1" ]]; then
    log "FORCE=1 Q=$q: removing prior outputs in $out_dir"
    rm -f "$out_dir"/zslab_iz*_4x4_paper_box_fused.step
    rm -f "$array_step"
    rm -rf "$out_dir/.work_zslab_cells"
  fi

  log "=== Q=$q layered fuse -> $array_step ==="
  local fuse_args=(
    scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py
    --Q "$q"
    --seed "$seed"
    --out-dir "$out_dir"
    --backend ocp
  )
  if [[ "$FORCE" == "1" ]]; then
    fuse_args+=(--force)
  fi

  set +e
  nice -n "$NICE_LEVEL" "$PY" "${fuse_args[@]}" 2>&1 | tee -a "$LOG"
  local rc=${PIPESTATUS[0]}
  set -e
  if [[ $rc -ne 0 ]]; then
    log "FAIL Q=$q exit $rc"
    return "$rc"
  fi
  if [[ ! -f "$array_step" ]]; then
    local default_step
    default_step="$("$PY" -c "
import sys
sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(
    cell_size=20.0, rod_diameter=2.582, amplitude=2.0,
    period_factor=float('$q'), n_segments=24,
)
gen.build_unitcell()
slug = f\"hu_bai_{gen.variant_name.lower()}_L20_4x4x4\"
print('$out_dir/' + slug + '_paper_box_array.step')
")"
    if [[ -f "$default_step" ]]; then
      mv -f "$default_step" "$array_step"
      log "Renamed -> $array_step"
    fi
  fi
  if [[ ! -f "$array_step" ]]; then
    log "FAIL Q=$q: array STEP missing $array_step"
    return 1
  fi
  ls -lh "$array_step" | tee -a "$LOG"
  log "OK Q=$q"
}

PY="$(python_cmd)"
preflight

log "=== ellipse paper_box 444 batch (ellmaj: major||+Z) start Q_LIST=[$Q_LIST] ==="
export_seeds

failed=0
for q in $Q_LIST; do
  if ! fuse_one "$q"; then
    failed=1
    log "Q=$q array fuse failed; continuing with remaining Q values"
  fi
done

if [[ "$failed" -ne 0 ]]; then
  log "=== batch PARTIAL/FAILED (see log) ==="
  exit 1
fi

log "=== batch ALL DONE ==="
for q in $Q_LIST; do
  log "Q=$q -> $(array_step_for_q "$q")"
done
