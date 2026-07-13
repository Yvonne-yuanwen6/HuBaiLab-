#!/usr/bin/env bash
# Continue ellipse 444: fuse Q=0/Q=0.5, export+fuse Q=1.5; Q=1.0 skipped (known fuse issue).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/hubai_env.sh"
ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
LOG="${LOG:-$ROOT/output/logs/ellipse_paper_box_444_continue.log}"
PY="${PY:-$ROOT/.venv/bin/python3}"
SEED_DIR="$ROOT/output/cad/_unitcell_paper_box_cut_ellipse_eqarea"
log(){ echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

rename_array(){
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

fuse_q(){
  local q="$1" seed="$2" dir="$3"
  log "FUSE Q=$q seed=$seed"
  "$PY" scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q "$q" --seed "$seed" --out-dir "$dir" --backend ocp --force >>"$LOG" 2>&1
  rename_array "$q" "$dir"
}

log "=== continue start ==="
fuse_q 0 "$SEED_DIR/unitcell_bcc_af2q0_paper_box_ellipse_ellmin_eqarea.step" "$ROOT/output/cad/_paper_box_array_ellipse_eqarea_q0"
fuse_q 0.5 "$SEED_DIR/unitcell_sfbls_af2q0p5_paper_box_ellipse_ellmin_eqarea.step" "$ROOT/output/cad/_paper_box_array_ellipse_eqarea_q0p5"

log "EXPORT Q=1.5 seed"
"$PY" scripts/export_unitcell_paper_box_cut.py --Q 1.5 --solid-profile ellipse --ellipse-align minor --compression-axis z --target-area-pi --out-dir "$SEED_DIR" >>"$LOG" 2>&1
fuse_q 1.5 "$SEED_DIR/unitcell_sfbls_af2q1p5_paper_box_ellipse_ellmin_eqarea.step" "$ROOT/output/cad/_paper_box_array_ellipse_eqarea_q1p5"

log "=== continue ALL DONE (Q=1.0 skipped) ==="
