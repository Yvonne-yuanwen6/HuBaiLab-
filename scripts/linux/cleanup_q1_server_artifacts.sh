#!/usr/bin/env bash
# Remove stale Q1 paper_box exports/jobs/logs (keep Q1.5 and other Q).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "=== Q1 server cleanup $(date) ==="

stop_pat() {
  local pat="$1"
  if pgrep -f "$pat" >/dev/null 2>&1; then
    echo "  stop processes: $pat"
    pkill -TERM -f "$pat" 2>/dev/null || true
    sleep 3
    pkill -KILL -f "$pat" 2>/dev/null || true
  fi
}

stop_pat 'hu_bai_sfbls_af2q1_'
stop_pat '_tmp_launch_q1_fig33_v2_el'

find "$ROOT/output/jobs" -name '*.lck' 2>/dev/null | while read -r lck; do
  case "$lck" in *af2q1*) rm -f "$lck"; echo "  removed lock $lck" ;;
  esac
done

# Export + job trees (Q1 only; slug contains af2q1 not af2q1p5)
while IFS= read -r d; do
  [[ -n "$d" ]] || continue
  echo "  rm -rf $d"
  rm -rf "$d"
done < <(find "$ROOT/output/export" "$ROOT/output/jobs" -maxdepth 1 -type d 2>/dev/null \
  | grep -E 'hu_bai_sfbls_af2q1_' | grep -v 'af2q1p5' || true)

rm -rf "$ROOT/output/export/_q1_mesh_sweep" 2>/dev/null || true
rm -f "$ROOT"/temp-hu_bai_sfbls_af2q1_*.sat "$ROOT"/ABQcae*.exception 2>/dev/null || true

echo "=== Q1 cleanup done $(date) ==="
