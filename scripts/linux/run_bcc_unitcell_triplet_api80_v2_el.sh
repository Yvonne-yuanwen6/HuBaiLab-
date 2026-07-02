#!/usr/bin/env bash
# BCC unit-cell triplet: all strut cross-sections A = pi mm^2.
# Circle d=2 mm; ellipse 2.582x1.549 mm (2:1.2 ratio scaled to pi).
# V2 elastic, CAE C3D4 mesh only, 80% strain, self-contact.
#
#   bash scripts/linux/run_bcc_unitcell_triplet_api80_v2_el.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/bcc_unitcell_triplet

LOG="output/logs/bcc_unitcell_triplet_api80_v2_el.log"
CAD_DIR="output/cad/triplet_unitcell_bcc_api"
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

V2_EXPORT_CIRC=(
  --cells 1 --Q 0 --profile fast
  --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact
  --cae-virtual-topology --mesh-locally
  --strain 0.80 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --contact-store-offsets --material-model elastic
)

V2_EXPORT_ELLIPSE=(
  --cells 1 --Q 0 --profile fast
  --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact
  --mesh-locally
  --strain 0.80 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --contact-store-offsets --material-model elastic
)

declare -a CASES=(
  "circular|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_circ_api.step|cae_tet0p6mm80p_5mmin_uc_circ_api_v2_el"
  "ellipse_minor|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmin_api.step|cae_tet0p6mm80p_5mmin_uc_ellmin_api_v2_el"
  "ellipse_major|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmaj_api.step|cae_tet0p6mm80p_5mmin_uc_ellmaj_api_v2_el"
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

cae_export() {
  local label="$1"
  local cad="$2"
  local suffix="$3"
  local slug="$4"
  local -a extra=()
  if [[ "$label" == "circular" ]]; then
    extra=("${V2_EXPORT_CIRC[@]}")
  else
    extra=("${V2_EXPORT_ELLIPSE[@]}")
  fi
  "$PY" scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py \
    "${extra[@]}" \
    --cad "$cad" \
    --case-suffix "$suffix"
}

cae_export_ellmaj() {
  local cad="$1"
  local suffix="$2"
  local slug="$3"
  local -a attempts=(
    "0.6|lattice_contact|0"
    "0.6|lattice|0"
    "0.6|fast|0"
    "0.6|lattice_curve|0"
    "0.8|lattice_contact|0"
    "0.8|lattice|0"
    "0.6|lattice_contact|1"
  )
  local seed quality vtopo extra_vtopo
  for attempt in "${attempts[@]}"; do
    IFS='|' read -r seed quality vtopo <<< "$attempt"
    extra_vtopo=()
    if [[ "$vtopo" == "1" ]]; then
      extra_vtopo=(--cae-virtual-topology)
    fi
    log "ellmaj CAE try seed=${seed} quality=${quality} vtopo=${vtopo}"
    rm -rf "output/jobs/${slug}" "output/export/${slug}"
    if "$PY" scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py \
      --cells 1 --Q 0 --profile fast \
      --cae-seed "$seed" --cae-element-type C3D4 --cae-mesh-quality "$quality" \
      "${extra_vtopo[@]}" \
      --mesh-locally \
      --strain 0.80 --load-rate-mm-min 5 \
      --explicit-dt 0.0005 --explicit-dt-mode automatic \
      --contact-store-offsets --material-model elastic \
      --cad "$cad" \
      --case-suffix "$suffix"; then
      log "ellmaj CAE OK seed=${seed} quality=${quality} vtopo=${vtopo}"
      return 0
    fi
  done
  return 1
}

log "=== BCC unitcell triplet API (A=pi) 80% CAE start cpus=$CPUS mem=$MEM ==="

mkdir -p "$VERIFIED_DIR" "$CAD_DIR"
copy_map=(
  "${CAD_DIR}/hu_bai_bcc_unitcell_L20_d2x1.2_Api_z_circular.step|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_circ_api.step"
  "${CAD_DIR}/hu_bai_bcc_unitcell_L20_d2x1.2_Api_z_ellipse_minor_align.step|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmin_api.step"
  "${CAD_DIR}/hu_bai_bcc_unitcell_L20_d2x1.2_Api_z_ellipse_major_align.step|${VERIFIED_DIR}/hu_bai_bcc_af0q0_L20_1x1x1_uc_ellmaj_api.step"
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

  log "EXPORT $label (CAE) -> $slug"
  rm -rf "output/jobs/${slug}" "output/export/${slug}"
  if ! cae_export "$label" "$cad" "$suffix" "$slug"; then
    if [[ "$label" == "ellipse_major" ]]; then
      cae_export_ellmaj "$cad" "$suffix" "$slug" || { log "ERROR export failed $slug (all CAE attempts)"; exit 1; }
    else
      log "ERROR export failed $slug"
      exit 1
    fi
  fi

  log "SUBMIT $slug"
  bash scripts/linux/submit_job.sh --slug "$slug" --cpus "$CPUS" --memory-mb "$MEM" --skip-resource-check \
    >> "$LOG" 2>&1 || { log "ERROR submit failed $slug"; exit 1; }

  wait_for_slug "$slug" || exit 1
  postpull_slug "$slug" || { log "WARN postpull failed $slug"; }
  log "DONE $slug"
done

log "=== ALL THREE API80 COMPLETE ==="
python3 scripts/plot_bcc_unitcell_triplet_v2_el.py --area-pi \
  --write-json output/reports/bcc_unitcell_triplet/manifest_api80.json \
  >> "$LOG" 2>&1 || log "WARN plot script failed"
