#!/usr/bin/env bash
set -uo pipefail
ROOT="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
cd "$ROOT"

echo "=== Active job locks (.lck) ==="
locks=$(find output/jobs -name '*.lck' 2>/dev/null || true)
if [[ -z "$locks" ]]; then
  echo "(none)"
else
  while IFS= read -r lck; do
    slug=$(basename "$lck" .lck)
    echo "$slug"
    if [[ -f "output/jobs/${slug}/${slug}.sta" ]]; then
      tail -1 "output/jobs/${slug}/${slug}.sta" 2>/dev/null | tr -s ' ' | cut -c1-100
    fi
  done <<< "$locks"
fi

echo
echo "=== Abaqus jobs (from process cmdline) ==="
ps aux | grep -E 'SMAPython|/bin/explicit|mpiexec\.hydra|mpirun' | grep -v grep | \
  grep -oE 'hu_bai[^ ]+' | sort -u || echo "(none)"

echo
echo "=== Linux orchestrator scripts ==="
pgrep -af 'scripts/linux' 2>/dev/null | grep -v 'pgrep -af' | \
  grep -E 'paperbox|comsol|hu_bai|fuse|marlow|supervise|orchestr|run_hu_bai' || echo "(none)"

echo
echo "=== COMSOL job details ==="
ps aux | grep -E 'comsol_run|comsol_batch|mph_builder|comsol\.py' | grep -v grep || true
ls -lt output/comsol_jobs 2>/dev/null | head -8 || true
for d in output/comsol_jobs/*/; do
  [[ -f "${d}case_manifest.json" ]] || continue
  echo "--- $(basename "$d")"
  python3 -c "import json; d=json.load(open('${d}case_manifest.json')); print('  status:', d.get('status'), 'phase:', d.get('phase'), 'updated:', d.get('updated_at',''))" 2>/dev/null || true
done

echo
echo "=== Python HuBai (CAD fuse etc) ==="
ps aux | grep python | grep -v grep | grep -E 'HuBaiLab|hu_bai|run_hu_bai|comsol' | \
  awk '{for(i=11;i<=NF;i++) printf "%s ", $i; print ""}' || echo "(none)"

echo
echo "=== Q05 fig33 improve sweep ==="
if [[ -f output/logs/q05_fig33_improve_ready.json ]]; then
  python3 - <<'PY'
import json
d = json.load(open('output/logs/q05_fig33_improve_ready.json'))
print('all_ready:', d.get('all_ready'))
print('disabled:', d.get('disabled_variants'))
for v in d.get('variants', []):
    print(f"  {v['suffix']}: completed={v['completed']} csv={v['csv_ready']} disabled={v.get('disabled', False)}")
PY
else
  echo "(no ready json)"
fi

echo
echo "=== Supervisor / improve running? ==="
pgrep -af 'paperbox_q05_fig33_improve_supervise' 2>/dev/null | grep -v pgrep || echo "supervise: stopped"
pgrep -af 'run_paperbox_q05_fig33_improve' 2>/dev/null | grep -v pgrep || echo "improve: stopped"
pgrep -af 'fig33_v2_paper_dt1e4' 2>/dev/null | grep -v pgrep || echo "dt1e4: stopped"
