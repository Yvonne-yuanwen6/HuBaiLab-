#!/usr/bin/env bash
# Extract stress-strain for one 批量构型 CAE case (hierarchical paths).
# Usage:
#   bash scripts/linux/postpull_param_batch_cae.sh af2q0_deq2_k1
#   bash scripts/linux/postpull_param_batch_cae.sh --all-completed
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

BATCH="批量构型"
RUN="${BATCH_SIM_RUN_SLUG:-cae_tet0p6mm80_5mmin_paperbox}"

postpull_one() {
  local cid="$1"
  local odb="output/jobs/${BATCH}/${cid}/${RUN}/${RUN}.odb"
  local meta="output/export/${BATCH}/${cid}/${RUN}/${RUN}_meta.json"
  local post="output/post/${BATCH}/${cid}/${RUN}"
  local csv="${post}/${RUN}_stress_strain.csv"

  [[ -f "$odb" ]] || { echo "SKIP $cid: no odb"; return 1; }
  [[ -f "$meta" ]] || { echo "SKIP $cid: no meta"; return 1; }
  mkdir -p "$post"
  echo "=== postpull $cid $(date) ==="
  abq python "$ROOT/scripts/extract_live_odb_server_py2.py" "$odb" "$meta" "$csv"
  echo "Wrote $csv ($(wc -l <"$csv") lines)"
}

if [[ "${1:-}" == "--all-completed" ]]; then
  shopt -s nullglob
  for sta in "output/jobs/${BATCH}"/*/"${RUN}/${RUN}.sta"; do
    if grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta" 2>/dev/null; then
      cid="$(basename "$(dirname "$(dirname "$sta")")")"
      postpull_one "$cid" || true
    fi
  done
  exit 0
fi

CID="${1:?usage: postpull_param_batch_cae.sh CASE_ID | --all-completed}"
postpull_one "$CID"
