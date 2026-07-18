#!/usr/bin/env bash
# BCC Fig.2.10-style pre-validation: energy check + mesh-size F–u sweep.
#
#   bash scripts/linux/run_bcc_mesh_validation.sh --post-only
#   bash scripts/linux/run_bcc_mesh_validation.sh --submit
#   bash scripts/linux/run_bcc_mesh_validation.sh --submit --plot
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/mesh_convergence

LOG="output/logs/bcc_mesh_validation.log"
SUBMIT=0
POST_ONLY=0
PLOT=0
LEVEL_FILTER=""
CPUS="${MESH_CONV_CPUS:-48}"
MEM="${MESH_CONV_MEMORY_MB:-262144}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --submit) SUBMIT=1; shift ;;
    --post-only) POST_ONLY=1; shift ;;
    --plot) PLOT=1; shift ;;
    --level) LEVEL_FILTER="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEM="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--submit] [--post-only] [--plot] [--level ID]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

readarray -t LEVEL_JSON < <(python3 - <<'PY'
import json
from src.mesh.bcc_mesh_validation import BCC_MESH_SEED_LEVELS, slug_for_bcc_level
for lv in BCC_MESH_SEED_LEVELS:
    print(json.dumps({
        "id": lv["id"],
        "slug": slug_for_bcc_level(lv),
        "reuse": bool(lv.get("reuse_baseline")),
        "seed": lv["cae_seed_mm"],
        "rods": lv["cae_rods_per_diameter"],
        "quality": lv["cae_mesh_quality"],
        "suffix": lv.get("variant_suffix") or "",
    }))
PY
)

log "=== BCC mesh validation post_only=$POST_ONLY submit=$SUBMIT ==="

for row in "${LEVEL_JSON[@]}"; do
  ID="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$row")"
  SLUG="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['slug'])" "$row")"
  REUSE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['reuse'])" "$row")"
  SEED="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['seed'])" "$row")"
  RODS="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['rods'])" "$row")"
  QUAL="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['quality'])" "$row")"
  SUFFIX="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['suffix'])" "$row")"

  if [[ -n "$LEVEL_FILTER" && "$ID" != "$LEVEL_FILTER" ]]; then
    continue
  fi

  log "--- level=$ID seed=$SEED slug=$SLUG reuse=$REUSE ---"
  CSV="output/post/${SLUG}/${SLUG}_stress_strain.csv"
  STA="output/jobs/${SLUG}/${SLUG}.sta"
  ODB="output/jobs/${SLUG}/${SLUG}.odb"

  ENERGY_CSV="output/post/${SLUG}/${SLUG}_energy.csv"
  ensure_post() {
    if [[ -f "$ODB" ]]; then
      mkdir -p "output/post/${SLUG}"
      [[ -f "$CSV" ]] || bash scripts/linux/postpull_paperbox_server.sh "$SLUG" >> "$LOG" 2>&1 || log "WARN postpull $SLUG"
      if [[ ! -f "$ENERGY_CSV" ]]; then
        abq python scripts/extract_odb_energy_py2.py "$ODB" "$ENERGY_CSV" >> "$LOG" 2>&1 \
          || log "WARN energy extract $SLUG"
      fi
    fi
  }

  if [[ "$POST_ONLY" -eq 1 ]]; then
    if [[ -f "$ODB" ]]; then
      ensure_post
      log "post ready: $SLUG"
    else
      log "WARN no ODB for $SLUG"
    fi
    continue
  fi

  if [[ "$REUSE" == "True" ]]; then
    ensure_post
    continue
  fi

  if [[ "$SUBMIT" -eq 1 ]]; then
    if [[ -f "$ODB" ]] && grep -q "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" "$STA" 2>/dev/null; then
      log "already completed: $SLUG"
      ensure_post
      continue
    fi
    bash scripts/linux/run_paperbox_variant.sh \
      --Q 0 \
      --variant-suffix "$SUFFIX" \
      --force-remesh \
      --cae-seed "$SEED" \
      --cae-mesh-quality "$QUAL" \
      --cae-rods-per-diameter "$RODS" \
      --cpus "$CPUS" \
      --memory-mb "$MEM" \
      --contact-store-offsets \
      --submit-background \
      >> "$LOG" 2>&1 || log "ERROR export/submit $ID"
  fi
done

if [[ "$SUBMIT" -eq 1 ]]; then
  log "Waiting for meshseed jobs to finish..."
  for row in "${LEVEL_JSON[@]}"; do
    ID="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$row")"
    SLUG="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['slug'])" "$row")"
    REUSE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['reuse'])" "$row")"
    if [[ -n "$LEVEL_FILTER" && "$ID" != "$LEVEL_FILTER" ]]; then
      continue
    fi
    [[ "$REUSE" == "True" ]] && continue
    while [[ -f "output/jobs/${SLUG}/${SLUG}.lck" ]]; do
      log "WAIT $SLUG"
      sleep 120
    done
    ODB="output/jobs/${SLUG}/${SLUG}.odb"
    CSV="output/post/${SLUG}/${SLUG}_stress_strain.csv"
    ENERGY_CSV="output/post/${SLUG}/${SLUG}_energy.csv"
    if [[ -f "$ODB" ]]; then
      mkdir -p "output/post/${SLUG}"
      [[ -f "$CSV" ]] || bash scripts/linux/postpull_paperbox_server.sh "$SLUG" >> "$LOG" 2>&1 || log "WARN postpull $SLUG"
      [[ -f "$ENERGY_CSV" ]] || abq python scripts/extract_odb_energy_py2.py "$ODB" "$ENERGY_CSV" >> "$LOG" 2>&1 || log "WARN energy $SLUG"
    fi
  done
fi

if [[ "$PLOT" -eq 1 || "$POST_ONLY" -eq 1 || "$SUBMIT" -eq 1 ]]; then
  python3 scripts/plot_bcc_quasi_static_mesh_validation.py >> "$LOG" 2>&1 || log "WARN plot failed"
fi

log "=== done ==="
