#!/usr/bin/env bash
# Extract stress-strain CSV from ODB on Linux server (requires abaqus python).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SLUG=""
FORCE_MODE="paper"

usage() {
  echo "Usage: $0 --slug SLUG [--force-mode paper|fixed_bottom_ref]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --force-mode) FORCE_MODE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ -n "$SLUG" ]] || usage

ABQ=""
if command -v abq >/dev/null; then ABQ=abq
elif command -v abaqus >/dev/null; then ABQ=abaqus
else
  echo "Neither abq nor abaqus in PATH"
  exit 1
fi

JOB_DIR="$ROOT/output/jobs/$SLUG"
EXPORT_DIR="$ROOT/output/export/$SLUG"
POST_DIR="$ROOT/output/post/$SLUG"
ODB="$JOB_DIR/${SLUG}.odb"
META="$EXPORT_DIR/${SLUG}_meta.json"
CSV="$POST_DIR/${SLUG}_stress_strain.csv"
RAW="$POST_DIR/${SLUG}_stress_strain_raw.csv"
YIELD="$POST_DIR/${SLUG}_yield.json"

[[ -f "$ODB" ]] || { echo "Missing ODB: $ODB"; exit 1; }
[[ -f "$META" ]] || { echo "Missing meta: $META"; exit 1; }

mkdir -p "$POST_DIR"

run_extract() {
  local mode="$1"
  echo "=== extract $SLUG force-mode=$mode ==="
  "$ABQ" python "$ROOT/scripts/extract_stress_strain_from_odb.py" \
    --odb "$ODB" --meta "$META" \
    --csv "$CSV" --raw-csv "$RAW" \
    --yield-json "$YIELD" \
    --force-mode "$mode" --curve-method paper
}

if ! run_extract "$FORCE_MODE"; then
  if [[ "$FORCE_MODE" != "fixed_bottom_ref" ]]; then
    echo "[WARN] retry fixed_bottom_ref"
    run_extract "fixed_bottom_ref"
  else
    exit 1
  fi
fi

echo "Post: $CSV"
