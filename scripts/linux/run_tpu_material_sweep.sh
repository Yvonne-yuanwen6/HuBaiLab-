#!/usr/bin/env bash
# Material-level TPU hyperelastic screening on the art workstation.
#
# Exports single-element uniaxial probes, runs Abaqus (fast, ~minutes total),
# extracts curves, scores vs Fig.2.5 WPD reference.
#
#   bash scripts/linux/run_tpu_material_sweep.sh
#   TPU_MAT_MAX_STRAIN=0.8 bash scripts/linux/run_tpu_material_sweep.sh   # lattice-relevant band only
#   TPU_MAT_MODELS="marlow ogden_n2 polynomial" bash scripts/linux/run_tpu_material_sweep.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
source "$SCRIPT_DIR/hubai_env.sh"

LOG="output/logs/tpu_material_sweep.log"
mkdir -p output/logs output/reports/tpu_material_fit

FIG25="${TPU_MAT_FIG25_JSON:-data/hu_bai_tpu_fig25_tensile_traced.json}"
MAX_STRAIN="${TPU_MAT_MAX_STRAIN:-0}"
MODELS="${TPU_MAT_MODELS:-elastic neo_hooke marlow polynomial ogden_n2 reduced_poly_n2}"
CPUS="${TPU_MAT_CPUS:-4}"
MEM_MB="${TPU_MAT_MEMORY_MB:-8192}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

ABQ=""
if command -v abq >/dev/null; then ABQ=abq
elif command -v abaqus >/dev/null; then ABQ=abaqus
else log "ERROR: abq/abaqus not in PATH"; exit 1; fi

[[ -f "$FIG25" ]] || { log "ERROR missing $FIG25 (sync data/ from local)"; exit 1; }

log "=== TPU material sweep start ==="
log "  root=$ROOT"
log "  fig25=$FIG25"
log "  models=$MODELS"
log "  max_strain=${MAX_STRAIN:-auto from Fig.2.5 peak}"

EXPORT_ARGS=(scripts/export_tpu_uniaxial_material_probe.py --fig25-json "$FIG25")
if [[ -n "$MAX_STRAIN" && "$MAX_STRAIN" != "0" ]]; then
  EXPORT_ARGS+=(--max-strain "$MAX_STRAIN")
fi
# shellcheck disable=SC2206
MODEL_ARR=($MODELS)
EXPORT_ARGS+=(--models "${MODEL_ARR[@]}")

python3 "${EXPORT_ARGS[@]}" 2>&1 | tee -a "$LOG"

for model in "${MODEL_ARR[@]}"; do
  slug="tpu_mat_${model}"
  export_dir="$ROOT/output/export/$slug"
  job_dir="$ROOT/output/jobs/$slug"
  inp="$export_dir/${slug}.inp"
  [[ -f "$inp" ]] || { log "SKIP missing INP for $model"; continue; }

  mkdir -p "$job_dir"
  cp -f "$inp" "$job_dir/"
  log "--- solve $slug ---"
  (
    cd "$job_dir"
    "$ABQ" job="$slug" input="${slug}.inp" oldjob=delete cpus="$CPUS" memory="$MEM_MB" interactive
  ) 2>&1 | tee -a "$LOG"

  if [[ ! -f "$job_dir/${slug}.odb" ]]; then
    log "ERROR missing ODB for $slug"
    continue
  fi

  log "--- extract $slug ---"
  "$ABQ" python "$ROOT/scripts/extract_tpu_uniaxial_probe_odb.py" --slug "$slug" --root "$ROOT" 2>&1 | tee -a "$LOG"
done

log "--- evaluate ---"
python3 scripts/evaluate_tpu_material_fit.py --plot --models "${MODEL_ARR[@]}" 2>&1 | tee -a "$LOG"

REPORT="output/reports/tpu_material_fit/tpu_material_fit_report.json"
if [[ -f "$REPORT" ]]; then
  python3 - <<'PY' "$REPORT" | tee -a "$LOG"
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
print("BEST:", r.get("best_model_full_range"))
print("RANK:", " > ".join(r.get("ranking_full_range_rmse") or []))
PY
fi

log "=== done — report: output/reports/tpu_material_fit/tpu_material_fit_report.json ==="
log "=== plot:   output/reports/tpu_material_fit/tpu_material_fit_overlay.png ==="
