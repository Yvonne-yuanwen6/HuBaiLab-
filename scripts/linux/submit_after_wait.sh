#!/usr/bin/env bash
# Wait until a job's .lck is gone, then submit one or more jobs serially.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CPUS=32
MEMORY_MB=131072
WAIT_FOR=""
SLUGS=()

usage() {
  echo "Usage: $0 --wait-for SLUG [--cpus N] [--memory-mb N] --slug SLUG [--slug SLUG ...]"
  echo "       $0 --wait-for SLUG ... --slugs-csv a,b,c"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEMORY_MB="$2"; shift 2 ;;
    --wait-for) WAIT_FOR="$2"; shift 2 ;;
    --slug) SLUGS+=("$2"); shift 2 ;;
    --slugs-csv) IFS=',' read -ra _csv <<< "$2"; SLUGS+=("${_csv[@]}"); shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ -n "$WAIT_FOR" ]] || usage
[[ ${#SLUGS[@]} -gt 0 ]] || usage

if [[ -d /home/art/APP/abaqus2022/Commands ]]; then
  export PATH="/home/art/APP/abaqus2022/Commands:${PATH:-/usr/bin:/bin}"
fi

LCK="$ROOT/output/jobs/$WAIT_FOR/${WAIT_FOR}.lck"
echo "=== submit_after_wait: waiting for $WAIT_FOR ==="
while [[ -f "$LCK" ]]; do
  echo "$(date '+%Y-%m-%d %H:%M:%S')  still running: $WAIT_FOR"
  sleep 60
done
echo "=== $WAIT_FOR finished (no .lck) ==="
sleep 5

CSV=""
for s in "${SLUGS[@]}"; do
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  [[ -n "$s" ]] || continue
  CSV="${CSV:+$CSV,}$s"
done

bash "$SCRIPT_DIR/submit_queue.sh" --cpus "$CPUS" --memory-mb "$MEMORY_MB" --slugs-csv "$CSV"
