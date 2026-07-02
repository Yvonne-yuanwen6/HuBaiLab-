#!/usr/bin/env bash
# Stop a single paper_box job by slug substring (does not touch other hu_bai jobs).
set -euo pipefail
PAT="${1:?usage: stop_paperbox_job.sh SLUG_SUBSTRING}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "=== stop job pattern: $PAT $(date) ==="
pkill -TERM -f "$PAT" 2>/dev/null || true
sleep 5
pkill -KILL -f "$PAT" 2>/dev/null || true
sleep 2

# Remove lock files matching pattern
find "$ROOT/output/jobs" -name '*.lck' 2>/dev/null | while read -r lck; do
  case "$lck" in *"$PAT"*) rm -f "$lck"; echo "removed $lck" ;;
  esac
done

n=$(ps aux | grep "$PAT" | grep -v grep | wc -l || true)
echo "remaining processes matching $PAT: $n"
echo "=== done ==="
