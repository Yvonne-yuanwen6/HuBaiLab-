#!/usr/bin/env bash
# Add Abaqus Commands to ~/.bashrc (Ubuntu default install).
# Usage: bash scripts/linux/setup_abaqus_env.sh [/opt/DASSAULT/SIMULIA/Commands]
set -euo pipefail

CMD_DIR="${1:-$HOME/APP/abaqus2022/Commands}"
ABQ="${CMD_DIR}/abq"
ABA="${CMD_DIR}/abaqus"

if [[ -x "$ABQ" ]]; then
  TEST_CMD=("$ABQ" information=release)
elif [[ -x "$ABA" ]]; then
  TEST_CMD=("$ABA" information=release)
else
  echo "ERROR: neither $ABQ nor $ABA found."
  echo "Run: bash scripts/linux/find_abaqus.sh"
  exit 1
fi

MARK="# HuBaiLab Abaqus PATH"
if grep -q "$MARK" ~/.bashrc 2>/dev/null; then
  echo "Already configured in ~/.bashrc"
else
  {
    echo ""
    echo "$MARK"
    echo "export PATH=\"${CMD_DIR}:\$PATH\""
  } >> ~/.bashrc
  echo "Appended PATH to ~/.bashrc"
fi

# License — set only if your group uses a network license server:
# export LM_LICENSE_FILE=27000@license-server-hostname

export PATH="${CMD_DIR}:$PATH"
echo "Test:"
"${TEST_CMD[@]}" | head -5
