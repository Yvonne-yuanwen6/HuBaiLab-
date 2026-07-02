#!/usr/bin/env bash
# Extract stress-strain CSV from a completed paperbox job on the server.
# Usage: bash scripts/linux/postpull_paperbox_server.sh SLUG
set -euo pipefail

SLUG="${1:?usage: postpull_paperbox_server.sh SLUG}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

ODB="output/jobs/${SLUG}/${SLUG}.odb"
META="output/export/${SLUG}/${SLUG}_meta.json"
POST="output/post/${SLUG}"
CSV="${POST}/${SLUG}_stress_strain.csv"
RAW="${POST}/${SLUG}_stress_strain_raw.csv"
UP="${POST}/up.odb"

[[ -f "$ODB" ]] || { echo "Missing ODB: $ODB"; exit 1; }
[[ -f "$META" ]] || { echo "Missing meta: $META"; exit 1; }

mkdir -p "$POST"

echo "=== postpull $SLUG $(date) ==="

# Abaqus Python 2.7 (readOnly ODB) — extract_stress_strain_from_odb.py is Py3-only.
abq python "$ROOT/scripts/extract_live_odb_server_py2.py" \
  "$ODB" "$META" "$CSV"

echo "Wrote $CSV"
wc -l "$CSV"
