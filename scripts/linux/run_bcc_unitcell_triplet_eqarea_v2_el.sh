#!/usr/bin/env bash
# BCC unit-cell triplet with equal-area circular strut (d_circ = sqrt(d_major*d_minor)).
# Ellipse cases unchanged (2.0 x 1.2 mm). V2 elastic, 70% strain, self-contact.
#
#   bash scripts/linux/run_bcc_unitcell_triplet_eqarea_v2_el.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/bcc_unitcell_triplet

LOG="output/logs/bcc_unitcell_triplet_eqarea_v2_el.log"
CAD_DIR="output/cad/triplet_unitcell_bcc_eqarea"
VERIFIED_DIR="output/cad/verified"
CPUS="${BCC_UC_CPUS:-16}"
MEM="${BCC_UC_MEMORY_MB:-32768}"
POLL_SEC="${BCC_UC_POLL_SEC:-30}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]]; then
    echo "$ROOT/.venv/bin/python3"
  else
    echo python3
  fi
}

PY="$(python_cmd)"

V2_EXPORT=(
  --cells 1 --Q 0 --profile fast
  --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact
  --cae-virtual-topology --mesh-locally
  --strain 0.70 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --contact-store-offsets --material-model elastic
)

V2_EXPORT_ELLIPSE=(
  --cells 1 --Q 0 --profile fast
  --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact
  --mesh-locally
  --strain 0.70 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --contact-store-offsets --material-model elastic
)

V2_EXPORT_ELLMAJ_GMSH=(
  --cells 1 --Q 0 --profile fast --stroke full
  --mesh-size 0.6
  --strain 0.70 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --contact-store-offsets --material-model elastic
)

declare -a CASES=(
  "circular|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_circ_eqa.step|cae_tet0p6mm70p_5mmin_uc_circ_eqa_v2_el"
  "ellipse_minor|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmin_eqa.step|cae_tet0p6mm70p_5mmin_uc_ellmin_eqa_v2_el"
  "ellipse_major|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmaj_eqa.step|cae_tet0p6mm70p_5mmin_uc_ellmaj_eqa_v2_el"
)

slug_for_suffix() {
  python3 -c "suffix='$1'; print(f'hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_{suffix}')"
}

job_completed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

job_running() {
  local slug="$1"
  [[ -f "$ROOT/output/jobs/${slug}/${slug}.lck" ]] && return 0
  pgrep -f "$slug" >/dev/null 2>&1
}

wait_for_slug() {
  local slug="$1"
  while job_running "$slug"; do
    local prog=""
    if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]]; then
      prog="$(tail -1 "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tr -s ' ' | cut -c1-100 || true)"
    fi
    log "WAIT $slug ${prog:+( $prog )}"
    sleep "$POLL_SEC"
  done
  if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]] && ! job_completed "$slug"; then
    log "ERROR $slug stopped without COMPLETED"
    return 1
  fi
  return 0
}

postpull_slug() {
  local slug="$1"
  bash scripts/linux/postpull_paperbox_server.sh "$slug" >> "$LOG" 2>&1
}

log "=== BCC unitcell triplet EQAREA V2 start cpus=$CPUS mem=$MEM ==="

mkdir -p "$VERIFIED_DIR" "$CAD_DIR"
copy_map=(
  "${CAD_DIR}/hu_bai_bcc_unitcell_L20_d2x1.2_eqarea_z_circular.step|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_circ_eqa.step"
  "${CAD_DIR}/hu_bai_bcc_unitcell_L20_d2x1.2_eqarea_z_ellipse_minor_align.step|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmin_eqa.step"
  "${CAD_DIR}/hu_bai_bcc_unitcell_L20_d2x1.2_eqarea_z_ellipse_major_align.step|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmaj_eqa.step"
)
for pair in "${copy_map[@]}"; do
  src="${pair%%|*}"
  dst="${pair##*|}"
  [[ -f "$src" ]] || { log "ERROR missing source CAD: $src"; exit 1; }
  cp -f "$src" "$dst"
  log "verified CAD: $dst"
done

for entry in "${CASES[@]}"; do
  IFS='|' read -r label cad suffix <<< "$entry"
  slug="$(slug_for_suffix "$suffix")"
  [[ -f "$cad" ]] || { log "ERROR missing CAD: $cad"; exit 1; }

  if job_completed "$slug"; then
    log "SKIP export/submit (done): $slug"
    postpull_slug "$slug" || true
    continue
  fi
  if job_running "$slug"; then
    log "SKIP export (running): $slug"
    wait_for_slug "$slug" || exit 1
    postpull_slug "$slug" || true
    continue
  fi

  log "EXPORT $label -> $slug"
  rm -rf "output/jobs/${slug}" "output/export/${slug}"
  if [[ "$label" == "ellipse_major" ]]; then
    if ! "$PY" -c 'import gmsh' 2>/dev/null; then
      if [[ -x "$ROOT/.venv/bin/pip" ]]; then
        log "installing gmsh into project venv..."
        "$ROOT/.venv/bin/pip" install -q 'gmsh>=4.12'
        PY="$ROOT/.venv/bin/python3"
      else
        log "ERROR gmsh not available for ellipse_major export"
        exit 1
      fi
    fi
    "$PY" scripts/run_hu_bai_bcc_solid_cad_export.py \
      "${V2_EXPORT_ELLMAJ_GMSH[@]}" \
      --cad "$cad" \
      --case-suffix "$suffix" || { log "ERROR export failed $slug"; exit 1; }
  else
    export_args=("${V2_EXPORT[@]}")
    if [[ "$label" != "circular" ]]; then
      export_args=("${V2_EXPORT_ELLIPSE[@]}")
    fi
    "$PY" scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py \
      "${export_args[@]}" \
      --cad "$cad" \
      --case-suffix "$suffix" || { log "ERROR export failed $slug"; exit 1; }
  fi

  log "SUBMIT $slug"
  bash scripts/linux/submit_job.sh --slug "$slug" --cpus "$CPUS" --memory-mb "$MEM" --skip-resource-check \
    >> "$LOG" 2>&1 || { log "ERROR submit failed $slug"; exit 1; }

  wait_for_slug "$slug" || exit 1
  postpull_slug "$slug" || { log "WARN postpull failed $slug"; }
  log "DONE $slug"
done

log "=== ALL THREE EQAREA COMPLETE ==="
python3 scripts/plot_bcc_unitcell_triplet_v2_el.py --eq-area \
  --write-json output/reports/bcc_unitcell_triplet/manifest_eqarea.json \
  >> "$LOG" 2>&1 || log "WARN plot script failed"
