#!/usr/bin/env bash
# Q1.5 Fig.3.3 trend trial — ONE-TIME self-contact OFF (user-approved 2026-06).
#
# Policy: V1 uses --no-lattice-self-contact. If V1 trend FAILS, do NOT disable
# self-contact again without explicit user approval. Later steps (V4/V5) keep
# self-contact ON.
#
#   bash scripts/linux/run_paperbox_q15_fig33_sweep.sh v1
#   bash scripts/linux/run_paperbox_q15_fig33_sweep.sh v1 --export-only
#   bash scripts/linux/run_paperbox_q15_fig33_sweep.sh eval --variant-suffix q15_v1_ns_el
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

STEP="${1:-v1}"
shift || true

CPUS="${Q15_FIG33_CPUS:-24}"
MEM="${Q15_FIG33_MEMORY_MB:-131072}"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
EVAL="scripts/evaluate_paperbox_q15_trend.py"
PLOT="scripts/plot_q15_fig33_vs_sim.py"
TRIAL_LOG="output/logs/q15_fig33_self_contact_trial.json"

V1_SUFFIX="q15_v1_ns_el"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

write_trial_manifest() {
  local status="$1" slug="$2"
  python3 -c "
import json, datetime
p = '$TRIAL_LOG'
try:
    d = json.load(open(p))
except Exception:
    d = {}
d.update({
  'policy': 'one_time_no_self_contact',
  'note': 'If q15_trend_pass is false, forbid --no-lattice-self-contact without user approval',
  'variant_suffix': '$V1_SUFFIX',
  'slug': '$slug',
  'self_contact': False,
  'last_status': '$status',
  'updated_at': datetime.datetime.now().isoformat(timespec='seconds'),
})
json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
print('Trial manifest:', p)
"
}

run_v1() {
  log "=== Q15 Fig.3.3 V1: nosettle + NO self-contact (ONE-TIME) + linear elastic ==="
  log "slug suffix: $V1_SUFFIX"
  export HU_BAI_ALLOW_NO_SELF_CONTACT=1
  bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$V1_SUFFIX" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --contact-store-offsets \
    --no-lattice-self-contact \
    --material-model elastic \
    "$@"
  SLUG="hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${V1_SUFFIX}"
  write_trial_manifest "submitted" "$SLUG"
  log "After job completes: bash scripts/linux/postpull_paperbox_server.sh (or extract slug)"
  log "Then: bash scripts/linux/run_paperbox_q15_fig33_sweep.sh eval --variant-suffix $V1_SUFFIX"
}

run_eval() {
  SUFFIX=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --variant-suffix) SUFFIX="$2"; shift 2 ;;
      *) echo "Unknown: $1"; exit 1 ;;
    esac
  done
  [[ -n "$SUFFIX" ]] || SUFFIX="$V1_SUFFIX"
  log "=== evaluate Q15 trend suffix=$SUFFIX ==="
  python3 "$EVAL" --variant-suffix "$SUFFIX" --write-json "output/logs/q15_fig33_eval_${SUFFIX}.json"
  EC=$?
  python3 "$PLOT" --variant "" --variant "$SUFFIX" --png "output/reports/q15_fig33_exp_vs_sim_${SUFFIX}.png"
  SLUG="hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${SUFFIX}"
  if [[ $EC -eq 0 ]]; then
    write_trial_manifest "trend_pass" "$SLUG"
    log "Q15 trend PASS"
  else
    write_trial_manifest "trend_fail_no_more_noself_without_user" "$SLUG"
    log "Q15 trend FAIL — do NOT disable self-contact again without user approval"
  fi
  return "$EC"
}

case "$STEP" in
  v1) run_v1 "$@" ;;
  eval) run_eval "$@" ;;
  *)
    echo "Usage: $0 v1 [--export-only|--submit-background]"
    echo "       $0 eval --variant-suffix $V1_SUFFIX"
    exit 1
    ;;
esac
