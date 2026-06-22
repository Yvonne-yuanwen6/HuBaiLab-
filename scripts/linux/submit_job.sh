#!/usr/bin/env bash
# Submit one HuBaiLab Abaqus job on Linux (mirror of submit_hu_bai_bcc_solid_cad_compression.ps1 solve step).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SLUG=""
CPUS=8
MEMORY_MB=8192
RECOVER=0

usage() {
  echo "Usage: $0 --slug SLUG [--cpus N] [--memory-mb N] [--recover]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEMORY_MB="$2"; shift 2 ;;
    --recover) RECOVER=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ -n "$SLUG" ]] || usage

ABQ=""
if command -v abq >/dev/null; then
  ABQ=abq
elif command -v abaqus >/dev/null; then
  ABQ=abaqus
else
  echo "Neither abq nor abaqus in PATH. Try: export PATH=\"\$HOME/APP/abaqus2022/Commands:\$PATH\""
  exit 1
fi

JOB_DIR="$ROOT/output/jobs/$SLUG"
EXPORT_DIR="$ROOT/output/export/$SLUG"
INP="$EXPORT_DIR/${SLUG}.inp"

[[ -f "$INP" ]] || { echo "Missing INP: $INP (run export on this machine first)"; exit 1; }

mkdir -p "$JOB_DIR"
cp -f "$INP" "$JOB_DIR/"
cd "$JOB_DIR"

if [[ $RECOVER -eq 1 ]]; then
  "$ABQ" job="$SLUG" recover cpus="$CPUS" memory="$MEMORY_MB" interactive
else
  "$ABQ" job="$SLUG" input="${SLUG}.inp" oldjob=delete cpus="$CPUS" memory="$MEMORY_MB" interactive
fi

echo "Job dir: $JOB_DIR"
echo "Watch:   tail -f $JOB_DIR/${SLUG}.sta"
