#!/usr/bin/env bash
# Stop in-flight Q0.5 paperbox jobs and resubmit at 24 cpus (export already done).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"

CPUS="${Q05_PARALLEL_CPUS:-24}"
MEM="${Q05_PARALLEL_MEMORY_MB:-131072}"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
STOP_SH="scripts/linux/stop_paperbox_job.sh"

echo "=== resubmit Q0.5 at cpus=$CPUS memory=$MEM $(date) ==="

for pat in \
  'sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p' \
  'sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_q05_rods4'; do
  sleep 5
  bash "$STOP_SH" "$pat" || true
  sleep 8
done

find "$ROOT/output/jobs" -path '*af2q0p5*paperbox*' -name '*.lck' -delete 2>/dev/null || true
pkill -KILL -f 'sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox' 2>/dev/null || true
sleep 5

submit() {
  local suffix="$1"
  shift
  echo "=== submit $suffix cpus=$CPUS ==="
  bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$suffix" \
    --submit-only --submit-background --cpus "$CPUS" --memory-mb "$MEM" "$@"
}

submit paperbox_settle5p &
PID1=$!
sleep 5
submit paperbox_q05_rods4 &
PID2=$!
wait "$PID1" "$PID2" || true

echo "=== done $(date) ==="
