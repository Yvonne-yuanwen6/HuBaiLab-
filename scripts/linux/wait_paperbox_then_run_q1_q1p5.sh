#!/usr/bin/env bash
# Wait for running paper_box jobs, then launch Q=1.0 and Q=1.5 with identical settings.
#
#   bash scripts/linux/wait_paperbox_then_run_q1_q1p5.sh
#   nohup bash scripts/linux/wait_paperbox_then_run_q1_q1p5.sh >> output/logs/paperbox_q1_q1p5_queue.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/paperbox_q1_q1p5_queue.log"
CASE_SUFFIX="cae_tet0p6mm80_5mmin_paperbox"
WAIT_SLUGS=(
  "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_${CASE_SUFFIX}"
  "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_${CASE_SUFFIX}"
)
NEXT_QS=(1.0 1.5)

job_completed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

job_running() {
  local slug="$1"
  [[ -f "$ROOT/output/jobs/${slug}/${slug}.lck" ]] && return 0
  pgrep -f "$slug" >/dev/null 2>&1
}

wait_slug() {
  local slug="$1"
  local idle_count=0
  echo "[$(date)] waiting for $slug ..."
  while true; do
    if job_completed "$slug"; then
      echo "[$(date)] COMPLETED $slug"
      return 0
    fi
    if job_running "$slug"; then
      idle_count=0
      local line
      line="$(grep -E '^[[:space:]]+[1-9][0-9]*[[:space:]]+' "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tail -1 || true)"
      echo "[$(date)]   still running $slug  ${line:-no sta yet}"
      sleep 120
      continue
    fi
    idle_count=$((idle_count + 1))
    echo "[$(date)]   no lock/process for $slug (${idle_count}/3; may be restart gap)"
    if [[ $idle_count -ge 3 ]]; then
      if job_completed "$slug"; then
        echo "[$(date)] COMPLETED $slug"
        return 0
      fi
      echo "[$(date)] ERROR $slug stopped without COMPLETED SUCCESSFULLY" >&2
      tail -20 "$ROOT/output/jobs/${slug}/${slug}.sta" >&2 || true
      return 1
    fi
    sleep 120
  done
}

echo ""
echo "=== paperbox queue: wait BCC+Q0.5 then run Q=1.0 + Q=1.5 $(date) ==="
echo "ROOT=$ROOT"

for slug in "${WAIT_SLUGS[@]}"; do
  wait_slug "$slug"
done

echo "[$(date)] prerequisite jobs done; launching Q=1.0 and Q=1.5 in parallel"

pids=()
for q in "${NEXT_QS[@]}"; do
  tag="$(python3 -c "from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G; print(G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=float('$q')).variant_name.lower())")"
  (
    echo "[$(date)] pipeline start Q=$q tag=$tag"
    bash scripts/linux/run_paperbox_cae_tet_pipeline.sh --Q "$q"
    echo "[$(date)] pipeline done Q=$q"
  ) >> "output/logs/${tag}_paperbox_cae_tet_pipeline.log" 2>&1 &
  pids+=("$!")
  echo "[$(date)] spawned Q=$q pid=$!"
done

fail=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    fail=1
  fi
done

if [[ $fail -ne 0 ]]; then
  echo "[$(date)] one or more Q=1.0/1.5 pipelines failed" >&2
  exit 1
fi

echo "[$(date)] all four paper_box CAE tet jobs complete (BCC, Q0.5, Q1, Q1.5)"
echo "DONE $(date)" >> "$LOG"
