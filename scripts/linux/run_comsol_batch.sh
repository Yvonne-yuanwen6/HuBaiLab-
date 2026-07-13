#!/usr/bin/env bash
# Submit one COMSOL batch job on the art Linux server.
#   bash scripts/linux/run_comsol_batch.sh --slug my_case --input models/foo.mph
#   bash scripts/linux/run_comsol_batch.sh --slug my_case --input build/HelloModel.class --study std1 --background
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

SLUG=""
INPUT=""
OUTPUT=""
STUDY=""
JOB_TAG=""
NP=8
MPMODE=""
CONTINUE=0
BACKGROUND=0
COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"

usage() {
  echo "Usage: $0 --slug SLUG --input PATH [--output PATH] [--study TAG] [--job TAG] [--np N] [--mpmode throughput|turnaround|owner] [--continue] [--background]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --input) INPUT="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --study) STUDY="$2"; shift 2 ;;
    --job) JOB_TAG="$2"; shift 2 ;;
    --np) NP="$2"; shift 2 ;;
    --mpmode) MPMODE="$2"; shift 2 ;;
    --continue) CONTINUE=1; shift ;;
    --background) BACKGROUND=1; shift ;;
    --comsol-bin) COMSOL_BIN="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ -n "$SLUG" && -n "$INPUT" ]] || usage
[[ -f "$INPUT" ]] || { echo "Missing input: $INPUT"; exit 1; }
[[ -x "$COMSOL_BIN" || -f "$COMSOL_BIN" ]] || { echo "Missing COMSOL: $COMSOL_BIN"; exit 1; }

mkdir -p output/comsol_jobs output/logs

ARGS=(python3 scripts/comsol_batch.py --slug "$SLUG" --input "$INPUT" --np "$NP" --comsol-bin "$COMSOL_BIN")
[[ -n "$OUTPUT" ]] && ARGS+=(--output "$OUTPUT")
[[ -n "$STUDY" ]] && ARGS+=(--study "$STUDY")
[[ -n "$JOB_TAG" ]] && ARGS+=(--job "$JOB_TAG")
[[ -n "$MPMODE" ]] && ARGS+=(--mpmode "$MPMODE")
[[ $CONTINUE -eq 1 ]] && ARGS+=(--continue)
[[ $BACKGROUND -eq 1 ]] && ARGS+=(--background)

LOG="output/logs/${SLUG}_comsol_submit.log"
echo "=== COMSOL batch $(date) slug=$SLUG ===" | tee -a "$LOG"
echo "COMSOL_BIN=$COMSOL_BIN" | tee -a "$LOG"
echo "INPUT=$INPUT" | tee -a "$LOG"

if [[ $BACKGROUND -eq 1 ]]; then
  nohup "${ARGS[@]}" >> "$LOG" 2>&1 &
  echo "Submitted background PID=$! slug=$SLUG"
  echo "Watch: tail -f output/comsol_jobs/${SLUG}/${SLUG}_batch.log"
else
  "${ARGS[@]}" 2>&1 | tee -a "$LOG"
fi

echo "Job dir: output/comsol_jobs/${SLUG}"
