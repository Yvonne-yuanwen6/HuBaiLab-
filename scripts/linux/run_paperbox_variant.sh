#!/usr/bin/env bash
# Export + submit one paper_box CAE tet variant (reuses baseline CAE mesh by default).
#
#   bash scripts/linux/run_paperbox_variant.sh --Q 0 --variant-suffix paperbox_nosettle \
#     --contact-store-offsets
#
#   bash scripts/linux/run_paperbox_variant.sh --Q 0.5 --variant-suffix paperbox_nosettle_dt1e4 \
#     --contact-store-offsets --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

Q="0"
VARIANT_SUFFIX=""
BASE_SUFFIX="cae_tet0p6mm80_5mmin_paperbox"
SHORT_SLUG=""
CAE_SEED="0.6"
CAE_ELEMENT_TYPE="C3D4"
CAE_MESH_QUALITY="lattice_contact"
CAE_VIRTUAL_TOPOLOGY=1
FORCE_REMESH=0
CAE_RODS_PER_DIAMETER=""
RESTART_FROM_SLUG=""
CONTINUE_TO_STRAIN=""
CPUS=48
MEMORY_MB=262144
EXPORT_ONLY=0
SUBMIT_ONLY=0
SUBMIT_BACKGROUND=0
EXTRA_EXPORT=()

usage() {
  echo "Usage: $0 --Q 0|0.5|1|1.5 --variant-suffix NAME [export.py args...]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --Q) Q="$2"; shift 2 ;;
    --variant-suffix) VARIANT_SUFFIX="$2"; shift 2 ;;
    --base-suffix) BASE_SUFFIX="$2"; shift 2 ;;
    --short-slug) SHORT_SLUG="$2"; shift 2 ;;
    --cae-seed) CAE_SEED="$2"; shift 2 ;;
    --cae-element-type) CAE_ELEMENT_TYPE="$2"; shift 2 ;;
    --cae-mesh-quality) CAE_MESH_QUALITY="$2"; shift 2 ;;
    --force-remesh) FORCE_REMESH=1; shift ;;
    --restart-from-slug) RESTART_FROM_SLUG="$2"; shift 2 ;;
    --continue-to-strain) CONTINUE_TO_STRAIN="$2"; shift 2 ;;
    --cae-rods-per-diameter) CAE_RODS_PER_DIAMETER="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEMORY_MB="$2"; shift 2 ;;
    --export-only) EXPORT_ONLY=1; shift ;;
    --submit-only) SUBMIT_ONLY=1; shift ;;
    --submit-background) SUBMIT_BACKGROUND=1; shift ;;
    --no-virtual-topology) CAE_VIRTUAL_TOPOLOGY=0; shift ;;
    -h|--help) usage ;;
    *) EXTRA_EXPORT+=("$1"); shift ;;
  esac
done

[[ -n "$VARIANT_SUFFIX" ]] || usage

if [[ -n "$RESTART_FROM_SLUG" ]]; then
  [[ -n "$CONTINUE_TO_STRAIN" ]] || {
    echo "ERROR: --restart-from-slug requires --continue-to-strain (target total engineering strain)"
    exit 1
  }
fi

LATTICE_TAG="$(python3 -c "from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G; print(G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=float('$Q')).variant_name.lower())")"
LATTICE_SLUG="hu_bai_${LATTICE_TAG}_L20_4x4x4"
BASELINE_SLUG="${LATTICE_SLUG}_solid_cad_f_${BASE_SUFFIX}"
CASE_SUFFIX="${BASE_SUFFIX}_${VARIANT_SUFFIX}"
if [[ -n "$SHORT_SLUG" ]]; then
  SLUG="$SHORT_SLUG"
else
  SLUG="${LATTICE_SLUG}_solid_cad_f_${CASE_SUFFIX}"
fi
if [[ -n "$RESTART_FROM_SLUG" && -z "$SHORT_SLUG" ]]; then
  SLUG="$(python3 -c "from src.export.explicit_continue import default_continue_slug; print(default_continue_slug('$RESTART_FROM_SLUG', float('$CONTINUE_TO_STRAIN')))")"
fi
LOG="output/logs/${SLUG}_pipeline.log"
CAD="output/cad/verified/${LATTICE_SLUG}_paper_box_array.step"
EXPORT_DIR="output/export/${SLUG}"
JOB_DIR="output/jobs/${SLUG}"
BASELINE_MESH="output/export/${BASELINE_SLUG}/${BASELINE_SLUG}_cae_mesh.inp"

exec > >(tee -a "$LOG") 2>&1

echo ""
echo "=== paperbox variant $(date) Q=$Q variant=$VARIANT_SUFFIX slug=$SLUG ==="
echo "ROOT=$ROOT baseline_mesh=$BASELINE_MESH force_remesh=$FORCE_REMESH rods_per_diameter=${CAE_RODS_PER_DIAMETER:-default}"

[[ -f "$CAD" ]] || { echo "Missing CAD: $CAD"; exit 1; }
if [[ -n "$RESTART_FROM_SLUG" ]]; then
  echo "=== explicit restart continue from $RESTART_FROM_SLUG -> strain=$CONTINUE_TO_STRAIN slug=$SLUG ==="
  if [[ "$SUBMIT_ONLY" -eq 0 ]]; then
    rm -rf "$JOB_DIR"
    CONTINUE_ARGS=(
      scripts/export_explicit_continue.py
      --from-slug "$RESTART_FROM_SLUG"
      --to-slug "$SLUG"
      --to-strain "$CONTINUE_TO_STRAIN"
      --copy-restart-files
    )
    python3 "${CONTINUE_ARGS[@]}"
  fi
  if [[ "$EXPORT_ONLY" -eq 1 ]]; then
    echo "=== continue export-only done $(date) slug=$SLUG ==="
    exit 0
  fi
  if [[ -f "$JOB_DIR/${SLUG}.lck" ]]; then
    echo "=== skip submit: job already running slug=$SLUG ==="
    exit 0
  fi
  echo "=== submit continue $(date) slug=$SLUG restart_from=$RESTART_FROM_SLUG cpus=$CPUS ==="
  SUBMIT_ARGS=(--slug "$SLUG" --cpus "$CPUS" --memory-mb "$MEMORY_MB" --restart-from "$RESTART_FROM_SLUG" --skip-resource-check)
  if [[ "$SUBMIT_BACKGROUND" -eq 1 ]]; then
    SUBMIT_ARGS+=(--background)
  fi
  bash scripts/linux/submit_job.sh "${SUBMIT_ARGS[@]}"
  echo "=== continue variant finished $(date) slug=$SLUG ==="
  exit 0
fi
if [[ "$FORCE_REMESH" -eq 0 && -z "$SHORT_SLUG" ]]; then
  [[ -f "$BASELINE_MESH" ]] || {
    echo "Missing baseline mesh (run baseline pipeline first): $BASELINE_MESH"
    exit 1
  }
fi

if [[ "$SUBMIT_ONLY" -eq 0 ]]; then
rm -rf "$JOB_DIR"
EXPORT_ARGS=(
  scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
  --cells 4 --Q "$Q" --profile fast
  --cad "$CAD"
  --cae-seed "$CAE_SEED"
  --cae-element-type "$CAE_ELEMENT_TYPE"
  --cae-mesh-quality "$CAE_MESH_QUALITY"
  --strain 0.80 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --material-model paper
  --case-suffix "$CASE_SUFFIX"
  --mesh-locally
)
if [[ -n "$SHORT_SLUG" ]]; then
  EXPORT_ARGS+=(--slug-mode short --short-slug "$SHORT_SLUG")
fi
if [[ "$CAE_VIRTUAL_TOPOLOGY" -eq 1 ]]; then
  EXPORT_ARGS+=(--cae-virtual-topology)
fi
if [[ "$FORCE_REMESH" -eq 0 && -z "$SHORT_SLUG" ]]; then
  EXPORT_ARGS+=(--cae-mesh-inp "$BASELINE_MESH")
else
  echo "Fresh CAE mesh for slug (seed=$CAE_SEED elem=$CAE_ELEMENT_TYPE quality=$CAE_MESH_QUALITY)"
fi
if [[ -n "$CAE_RODS_PER_DIAMETER" ]]; then
  EXPORT_ARGS+=(--cae-rods-per-diameter "$CAE_RODS_PER_DIAMETER")
fi
if [[ ${#EXTRA_EXPORT[@]} -gt 0 ]]; then
  EXPORT_ARGS+=("${EXTRA_EXPORT[@]}")
fi

# One-time Q15 Fig.3.3 trial: after failed no-self-contact run, require explicit opt-in.
if printf '%s\n' "${EXTRA_EXPORT[@]}" | grep -qx -- '--no-lattice-self-contact'; then
  TRIAL_JSON="$ROOT/output/logs/q15_fig33_self_contact_trial.json"
  if [[ -f "$TRIAL_JSON" ]]; then
    TRIAL_STATUS="$(python3 -c "import json; print(json.load(open('$TRIAL_JSON')).get('last_status',''))")"
    if [[ "$TRIAL_STATUS" == "trend_fail_no_more_noself_without_user" ]]; then
      if [[ "${HU_BAI_ALLOW_NO_SELF_CONTACT:-0}" != "1" ]]; then
        echo "ERROR: Q15 no-self-contact trial already FAILED."
        echo "  Do not use --no-lattice-self-contact without user approval."
        echo "  Set HU_BAI_ALLOW_NO_SELF_CONTACT=1 only after user confirms."
        exit 1
      fi
    fi
  fi
fi

python3 "${EXPORT_ARGS[@]}"
fi

if [[ "$EXPORT_ONLY" -eq 1 ]]; then
  echo "=== export-only done $(date) slug=$SLUG ==="
  exit 0
fi

if [[ -f "$JOB_DIR/${SLUG}.lck" ]]; then
  echo "=== skip submit: job already running slug=$SLUG ==="
  exit 0
fi

echo "=== submit $(date) slug=$SLUG cpus=$CPUS background=$SUBMIT_BACKGROUND ==="
SUBMIT_ARGS=(--slug "$SLUG" --cpus "$CPUS" --memory-mb "$MEMORY_MB" --skip-resource-check)
if [[ "$SUBMIT_BACKGROUND" -eq 1 ]]; then
  SUBMIT_ARGS+=(--background)
fi
bash scripts/linux/submit_job.sh "${SUBMIT_ARGS[@]}"

echo "=== variant finished $(date) slug=$SLUG ==="
