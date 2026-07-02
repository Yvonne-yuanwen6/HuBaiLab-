#!/usr/bin/env bash
set -euo pipefail
F="$(cd "$(dirname "$0")/../.." && pwd)/scripts/linux/run_paperbox_variant.sh"
sed -i 's/material-model pape/material-model paper/' "$F"
grep material-model "$F"
