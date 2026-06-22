#!/usr/bin/env bash
# Locate Abaqus on Ubuntu/Linux and print PATH / license hints.
set -euo pipefail

echo "=== find_abaqus ==="

candidates=(
  "$HOME/APP/abaqus2022/Commands/abq"
  "$HOME/APP/abaqus2022/Commands/abaqus"
  /opt/DASSAULT/SIMULIA/Commands/abaqus
  /usr/SIMULIA/Commands/abaqus
  "$HOME/SIMULIA/Commands/abaqus"
  "$HOME/abaqus/Commands/abaqus"
)

found=0
for p in "${candidates[@]}"; do
  if [[ -x "$p" ]]; then
    echo "FOUND: $p"
    dirname "$p"
    found=1
  fi
done

if [[ $found -eq 0 ]]; then
  echo "Not in common paths. Searching (may take a minute)..."
  find /opt /usr /home /local 2>/dev/null -name abaqus -type f -executable | head -20
fi

echo ""
echo "SIMULIA directories:"
find /opt /usr /home /local 2>/dev/null -type d -name SIMULIA | head -10

echo ""
echo "Current PATH abaqus:"
command -v abaqus || echo "(not in PATH)"

echo ""
echo "License env (if set):"
echo "  LM_LICENSE_FILE=${LM_LICENSE_FILE:-<unset>}"
echo "  ABAQUSLM_LICENSE_FILE=${ABAQUSLM_LICENSE_FILE:-<unset>}"
