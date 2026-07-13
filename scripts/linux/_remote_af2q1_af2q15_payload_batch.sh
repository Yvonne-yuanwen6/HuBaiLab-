#!/usr/bin/env bash
# Sequential: AF2Q1 then AF2Q1.5 payload sweeps (0/100/300/500 g, 5–150 Hz).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
mkdir -p output/logs
LOG="output/logs/af2q1_af2q15_payload_batch.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== AF2Q1 + AF2Q1.5 payload batch $(date) ==="
bash scripts/linux/_remote_af2q1_payload_f5_150_batch.sh
bash scripts/linux/_remote_af2q15_payload_f5_150_batch.sh
echo "=== all done $(date) ==="
