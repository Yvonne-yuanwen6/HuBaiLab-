#!/usr/bin/env bash
# Submit one HuBaiLab Abaqus job on Linux (mirror of submit_hu_bai_bcc_solid_cad_compression.ps1 solve step).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SLUG=""
CPUS=8
MEMORY_MB=8192
RECOVER=0
RESTART_FROM=""
SKIP_RESOURCE_CHECK=0
BACKGROUND=0

usage() {
  echo "Usage: $0 --slug SLUG [--cpus N] [--memory-mb N] [--recover] [--restart-from OLDJOB] [--skip-resource-check] [--background]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEMORY_MB="$2"; shift 2 ;;
    --recover) RECOVER=1; shift ;;
    --restart-from) RESTART_FROM="$2"; shift 2 ;;
    --skip-resource-check) SKIP_RESOURCE_CHECK=1; shift ;;
    --background) BACKGROUND=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ -n "$SLUG" ]] || usage

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECK_ARGS=(--root "$ROOT" --cpus "$CPUS" --memory-mb "$MEMORY_MB")
[[ "$SKIP_RESOURCE_CHECK" -eq 1 ]] && CHECK_ARGS+=(--force)
bash "$SCRIPT_DIR/check_submit_resources.sh" "${CHECK_ARGS[@]}"

ABQ=""
if command -v abq >/dev/null; then
  ABQ=abq
elif command -v abaqus >/dev/null; then
  ABQ=abaqus
else
  echo "Neither abq nor abaqus in PATH. Try: export PATH=\"\$HOME/APP/abaqus2022/Commands:\$PATH\""
  exit 1
fi

JOBS_ROOT="${HU_BAI_JOBS_ROOT:-$ROOT/output/jobs}"
EXPORT_ROOT="${HU_BAI_EXPORT_ROOT:-$ROOT/output/export}"
JOB_DIR="$JOBS_ROOT/$SLUG"
EXPORT_DIR="$EXPORT_ROOT/$SLUG"
INP="$EXPORT_DIR/${SLUG}.inp"

[[ -f "$INP" ]] || { echo "Missing INP: $INP (run export on this machine first)"; exit 1; }

mkdir -p "$JOB_DIR"
cp -f "$INP" "$JOB_DIR/"
cd "$JOB_DIR"

if [[ -n "$RESTART_FROM" ]]; then
  SRC_JOB="${HU_BAI_RESTART_JOBS_ROOT:-$ROOT/output/jobs}/$RESTART_FROM"
  [[ -d "$SRC_JOB" ]] || { echo "Missing restart source job dir: $SRC_JOB"; exit 1; }
  for ext in abq mdl stt pac prt res sel odb; do
    src_file="$SRC_JOB/${RESTART_FROM}.${ext}"
    dst_file="${RESTART_FROM}.${ext}"
    if [[ -f "$src_file" && ! -e "$dst_file" ]]; then
      echo "Link restart file: $src_file -> $JOB_DIR/$dst_file"
      ln -sf "$src_file" "$dst_file" 2>/dev/null || cp -f "$src_file" "$dst_file"
    fi
  done
  [[ -e "${RESTART_FROM}.res" ]] || { echo "Missing ${RESTART_FROM}.res in $JOB_DIR"; exit 1; }
fi

SUBMIT_LOG="$JOB_DIR/${SLUG}_submit.log"
if [[ $RECOVER -eq 1 ]]; then
  ABQ_CMD=( "$ABQ" job="$SLUG" recover cpus="$CPUS" memory="$MEMORY_MB" interactive )
elif [[ -n "$RESTART_FROM" ]]; then
  ABQ_CMD=( "$ABQ" job="$SLUG" input="${SLUG}.inp" oldjob="$RESTART_FROM" cpus="$CPUS" memory="$MEMORY_MB" interactive )
else
  ABQ_CMD=( "$ABQ" job="$SLUG" input="${SLUG}.inp" oldjob=delete cpus="$CPUS" memory="$MEMORY_MB" interactive )
fi

if [[ $BACKGROUND -eq 1 ]]; then
  nohup "${ABQ_CMD[@]}" >> "$SUBMIT_LOG" 2>&1 &
  echo "Submitted background PID=$! slug=$SLUG"
  echo "Log: $SUBMIT_LOG"
else
  "${ABQ_CMD[@]}"
fi

echo "Job dir: $JOB_DIR"
echo "Watch:   tail -f $JOB_DIR/${SLUG}.sta"
