#!/usr/bin/env bash
# Remove stale/wrong Q1 STEP + job artifacts; keep OCP444 CAD tree.
#
#   DRY_RUN=1 bash scripts/linux/cleanup_q1_stale_cad_exports.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

DRY_RUN="${DRY_RUN:-0}"
LOG="output/logs/cleanup_q1_stale_cad_exports.log"
mkdir -p output/logs

OCP_DIR="output/cad/_paper_box_array_q1p0_ocp"
VERIFIED="output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
RUNNING_SLUG="hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

rm_path() {
  local p="$1"
  [[ -e "$p" ]] || return 0
  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY rm -rf $p"
  else
    log "rm -rf $p"
    rm -rf "$p"
  fi
}

log "=== cleanup wrong Q1 CAD/jobs (keep OCP444) dry_run=$DRY_RUN ==="

# 1) Wrong gmsh layered route (351 MB 4-body compound array + old z-slabs)
rm_path "output/cad/_paper_box_array_q1p0"
rm_path "output/cad/_paper_box_array_q1p0_manual_q1"

# 2) OCP probe/temp STEPs (not production)
for f in "$OCP_DIR"/.__probe*.step; do
  [[ -e "$f" ]] || continue
  rm_path "$f"
done

# 3) Non-canonical Q1.0 verified STEPs (keep 51 MB OCP444 canonical only)
for f in output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_*; do
  [[ -e "$f" ]] || continue
  [[ "$f" == "$VERIFIED" ]] && continue
  rm_path "$f"
done

# 4) Completed Q1 job dirs (old/wrong ODB+inp copies); skip running fig33_v2_el
for d in output/jobs/hu_bai_sfbls_af2q1_L20_4x4x4_*; do
  [[ -d "$d" ]] || continue
  base="$(basename "$d")"
  if [[ "$base" == "$RUNNING_SLUG" ]]; then
    log "KEEP running job: $d"
    continue
  fi
  if compgen -G "$d/*.lck" >/dev/null 2>&1; then
    log "SKIP job with lock: $d"
    continue
  fi
  rm_path "$d"
done

# 5) Remove pre-OCP444 Q1 export INPs (mtime before verified CAD install 2026-06-30 22:36)
#    Keep OCP444-era exports (baseline mesh + variant INPs from new verified CAD).
CUTOFF="2026-06-30 22:35:00"
for d in output/export/hu_bai_sfbls_af2q1_L20_4x4x4_*; do
  [[ -d "$d" ]] || continue
  inp="$(find "$d" -maxdepth 1 -name '*.inp' -type f | head -1)"
  [[ -n "$inp" ]] || continue
  if [[ "$(date -r "$inp" '+%F %T')" < "$CUTOFF" ]]; then
    rm_path "$d"
  else
    log "KEEP OCP444 export: $d"
  fi
done

log "=== kept OCP444 CAD ==="
ls -lh "$VERIFIED" 2>/dev/null | tee -a "$LOG" || true
find "$OCP_DIR" -maxdepth 1 -type f -name '*.step' -printf '  %12s %p\n' 2>/dev/null | tee -a "$LOG" || true
log "=== done ==="
