#!/usr/bin/env bash
# Ellipse 4×4×4 → paperbox baseline (Neo-Hooke + ContactSettle 15%), up to 2 parallel solves.
# Aligns with run_paperbox_cae_tet_pipeline.sh / docs/Abaqus_CAD实体压缩说明.md §2.2.
#
# Queue (7 jobs): ellmaj Q=0,0.5,1,1.5 + ellmin Q=0,0.5,1 (Q=1.5 ellmin CAD not ready).
#
#   bash scripts/linux/run_ellipse_444_marlow_parallel.sh
#   ELLIPSE_BASELINE_MAX_PARALLEL=2 nohup bash scripts/linux/run_ellipse_444_marlow_parallel.sh \
#     >> output/logs/ellipse_444_baseline_parallel.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/ellipse_baseline

LOG="output/logs/ellipse_444_baseline_parallel.log"
STATE="output/logs/ellipse_444_baseline_state.json"
LOCK="$ROOT/output/logs/ellipse_444_baseline_parallel.lock"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"

CPUS="${ELLIPSE_BASELINE_CPUS:-${ELLIPSE_MARLOW_CPUS:-48}}"
MEM="${ELLIPSE_BASELINE_MEMORY_MB:-${ELLIPSE_MARLOW_MEMORY_MB:-262144}}"
POLL_SEC="${ELLIPSE_BASELINE_POLL_SEC:-${ELLIPSE_MARLOW_POLL_SEC:-120}}"
MAX_PARALLEL="${ELLIPSE_BASELINE_MAX_PARALLEL:-${ELLIPSE_MARLOW_MAX_PARALLEL:-2}}"
STALL_MIN="${ELLIPSE_BASELINE_STALL_MIN:-${ELLIPSE_MARLOW_STALL_MIN:-45}}"
BASE_SUFFIX="cae_tet0p6mm80_5mmin_paperbox"

# paper = Neo-Hooke hyperelastic (E=25 MPa, nu=0.47); contact settle 15% per paperbox pipeline.
PAPERBASE_EXTRA=(
  --contact-store-offsets
  --contact-settle
  --contact-settle-fraction 0.15
  --contact-settle-soft-s0 0.02
  --material-model paper
)

# label|Q|align|cad_relpath
QUEUE=(
  "q0_ellmaj|0|ellmaj|output/cad/_paper_box_array_ellipse_eqarea_ellmaj_q0/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step"
  "q0_ellmin|0|ellmin|output/cad/_paper_box_array_ellipse_eqarea_q0/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
  "q0p5_ellmaj|0.5|ellmaj|output/cad/_paper_box_array_ellipse_eqarea_ellmaj_q0p5/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step"
  "q0p5_ellmin|0.5|ellmin|output/cad/_paper_box_array_ellipse_eqarea_q0p5/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step"
  "q1_ellmaj|1|ellmaj|output/cad/_paper_box_array_ellipse_eqarea_ellmaj_q1p0/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step"
  "q1_ellmin|1|ellmin|output/cad/_paper_box_array_ellipse_eqarea_q1p0/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_ellipse_eqarea_ellmin_array.step"
  "q1p5_ellmaj|1.5|ellmaj|output/cad/_paper_box_array_ellipse_eqarea_ellmaj_q1p5/hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step"
)
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ellipse_444_baseline already running (lock $LOCK)" >> "$LOG"
  exit 0
fi

exec > >(tee -a "$LOG") 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
log_file_only() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

parse_entry() {
  local entry="$1" field="$2"
  IFS='|' read -r label q align cad <<< "$entry"
  case "$field" in
    label) echo "$label" ;;
    q) echo "$q" ;;
    align) echo "$align" ;;
    cad) echo "$cad" ;;
  esac
}

slug_for_entry() {
  baseline_slug_for_entry "$1"
}

baseline_suffix_for_entry() {
  local align
  align="$(parse_entry "$1" align)"
  echo "${BASE_SUFFIX}_ellipse_${align}"
}

baseline_slug_for_entry() {
  local q align
  q="$(parse_entry "$1" q)"
  align="$(parse_entry "$1" align)"
  python3 -c "
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G
q=float('$q')
align='$align'
base='$BASE_SUFFIX'
tag=G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=q).variant_name.lower()
print(f'hu_bai_{tag}_L20_4x4x4_solid_cad_f_{base}_ellipse_{align}')
"
}

baseline_mesh_for_entry() {
  local slug
  slug="$(baseline_slug_for_entry "$1")"
  echo "output/export/${slug}/${slug}_cae_mesh.inp"
}

verified_name_for_entry() {
  local q align
  q="$(parse_entry "$1" q)"
  align="$(parse_entry "$1" align)"
  python3 -c "
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G
q=float('$q')
align='$align'
tag=G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=q).variant_name.lower()
print(f'hu_bai_{tag}_L20_4x4x4_paper_box_ellipse_{align}_array.step')
"
}

install_verified_cad() {
  local entry="$1"
  local src name verified
  src="$(parse_entry "$entry" cad)"
  name="$(verified_name_for_entry "$entry")"
  verified="output/cad/verified/${name}"
  mkdir -p output/cad/verified
  ln -sf "$(realpath "$src")" "$verified"
  echo "$verified"
}

job_completed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

job_failed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] || return 1
  grep -qE 'NOT BEEN COMPLETED|SIGTERM|MPI_Abort|excessively distorted' "$sta" && ! job_completed "$slug"
}

job_running() {
  local slug="$1"
  [[ -f "$ROOT/output/jobs/${slug}/${slug}.lck" ]] && return 0
  pgrep -f "mpiexec.hydra.*${slug}" >/dev/null 2>&1 || \
  pgrep -f "/bin/explicit.*${slug}" >/dev/null 2>&1 || \
  pgrep -f "SMAPython.*-job ${slug}" >/dev/null 2>&1
}

csv_ready() {
  local slug="$1"
  [[ -f "$ROOT/output/post/${slug}/${slug}_stress_strain.csv" ]]
}

last_sim_s() {
  local slug="$1"
  grep -E '^[[:space:]]+[1-9]' "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tail -1 | awk '{print $3}'
}

last_ke() {
  local slug="$1"
  grep -E '^[[:space:]]+[1-9]' "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tail -1 | awk '{print $7}'
}

postpull_slug() {
  local slug="$1"
  if csv_ready "$slug"; then
    return 0
  fi
  if [[ -f "$ROOT/output/jobs/${slug}/${slug}.odb" ]] || job_completed "$slug"; then
    bash "$POSTPULL" "$slug" >> "$LOG" 2>&1 || log "WARN postpull failed $slug"
  fi
}

needs_work() {
  local entry="$1" slug
  slug="$(slug_for_entry "$entry")"
  if job_completed "$slug" && csv_ready "$slug"; then
    return 1
  fi
  return 0
}

count_running_queue() {
  local entry slug n=0
  for entry in "${QUEUE[@]}"; do
    slug="$(slug_for_entry "$entry")"
    if job_running "$slug"; then
      n=$((n + 1))
    fi
  done
  echo "$n"
}

ensure_baseline_mesh() {
  local entry="$1"
  local label q align cad baseline_slug baseline_mesh baseline_suffix
  label="$(parse_entry "$entry" label)"
  q="$(parse_entry "$entry" q)"
  align="$(parse_entry "$entry" align)"
  baseline_slug="$(baseline_slug_for_entry "$entry")"
  baseline_mesh="$(baseline_mesh_for_entry "$entry")"
  baseline_suffix="$(baseline_suffix_for_entry "$entry")"

  if [[ -f "$baseline_mesh" ]]; then
    log_file_only "baseline mesh reuse $label -> $baseline_mesh"
    echo "$baseline_mesh"
    return 0
  fi

  local legacy_slug legacy_mesh
  for legacy_slug in \
    "${baseline_slug}_fig33_v2_marlow" \
    "${baseline_slug/_ellipse_${align}/_ellipse_${align}_v2_marlow}"; do
    legacy_mesh="output/export/${legacy_slug}/${legacy_slug}_cae_mesh.inp"
    if [[ -f "$legacy_mesh" ]]; then
      mkdir -p "output/export/${baseline_slug}"
      ln -sf "$(realpath "$legacy_mesh")" "$baseline_mesh"
      log_file_only "baseline mesh from legacy export $label -> $baseline_mesh"
      echo "$baseline_mesh"
      return 0
    fi
  done

  [[ -f "$(parse_entry "$entry" cad)" ]] || { log "ERROR missing CAD $label"; return 1; }
  cad="$(install_verified_cad "$entry")"
  log_file_only "BUILD baseline mesh $label slug=$baseline_slug"

  local heal_args=()
  if [[ "$align" == "ellmaj" ]]; then
    heal_args=(--heal-step-on-mesh-fail)
  fi

  if ! python3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py \
    --cells 4 --Q "$q" --profile fast \
    --cad "$cad" \
    --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact \
    --mesh-locally \
    --strain 0.80 --load-rate-mm-min 5 \
    --explicit-dt 0.0005 --explicit-dt-mode automatic \
    --case-suffix "$baseline_suffix" \
    "${PAPERBASE_EXTRA[@]}" \
    "${heal_args[@]}"; then
    log "ERROR baseline mesh export failed $label"
    return 1
  fi

  if [[ ! -f "$baseline_mesh" ]]; then
    log "ERROR baseline mesh missing after export: $baseline_mesh"
    return 1
  fi
  log_file_only "baseline mesh ready $baseline_mesh"
  echo "$baseline_mesh"
}

export_one() {
  local entry="$1"
  local label q align cad slug suffix baseline_mesh inp heal_args=()
  label="$(parse_entry "$entry" label)"
  q="$(parse_entry "$entry" q)"
  align="$(parse_entry "$entry" align)"
  slug="$(baseline_slug_for_entry "$entry")"
  suffix="$(baseline_suffix_for_entry "$entry")"
  baseline_mesh="$(baseline_mesh_for_entry "$entry")"
  inp="output/export/${slug}/${slug}.inp"

  cad="output/cad/verified/$(verified_name_for_entry "$entry")"
  [[ -f "$cad" ]] || cad="$(install_verified_cad "$entry")"

  if [[ "$align" == "ellmaj" ]]; then
    heal_args=(--heal-step-on-mesh-fail)
  fi

  rm -rf "output/jobs/${slug}"

  if [[ -f "$inp" ]]; then
    log "REUSE baseline INP (Neo-Hooke) $label slug=$slug"
    return 0
  fi

  if [[ ! -f "$baseline_mesh" ]]; then
    baseline_mesh="$(ensure_baseline_mesh "$entry")" || return 1
    if [[ -f "$inp" ]]; then
      log "REUSE baseline INP after mesh build $label slug=$slug"
      return 0
    fi
  fi

  log "EXPORT $label Q=$q align=$align slug=$slug (Neo-Hooke paper + baseline mesh)"
  if [[ -f "$baseline_mesh" ]]; then
    if ! python3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py \
      --cells 4 --Q "$q" --profile fast \
      --cad "$cad" \
      --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact \
      --cae-mesh-inp "$baseline_mesh" \
      --mesh-locally \
      --strain 0.80 --load-rate-mm-min 5 \
      --explicit-dt 0.0005 --explicit-dt-mode automatic \
      --case-suffix "$suffix" \
      "${PAPERBASE_EXTRA[@]}" \
      "${heal_args[@]}"; then
      log "ERROR export failed $label slug=$slug"
      return 1
    fi
  else
    if ! python3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py \
      --cells 4 --Q "$q" --profile fast \
      --cad "$cad" \
      --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact \
      --mesh-locally \
      --strain 0.80 --load-rate-mm-min 5 \
      --explicit-dt 0.0005 --explicit-dt-mode automatic \
      --case-suffix "$suffix" \
      "${PAPERBASE_EXTRA[@]}" \
      "${heal_args[@]}"; then
      log "ERROR export failed $label slug=$slug"
      return 1
    fi
  fi
  return 0
}

submit_one() {
  local slug="$1"
  log "SUBMIT $slug cpus=$CPUS mem=${MEM}MB"
  bash scripts/linux/submit_job.sh \
    --slug "$slug" \
    --cpus "$CPUS" \
    --memory-mb "$MEM" \
    --skip-resource-check \
    --background
}

kill_slug() {
  local slug="$1"
  ps aux | awk -v s="$slug" '/\/bin\/explicit/ && $0 ~ s {print $2}' | xargs -r kill -KILL 2>/dev/null || true
  ps aux | awk -v s="$slug" '/mpiexec.hydra/ && $0 ~ s {print $2}' | xargs -r kill -KILL 2>/dev/null || true
}

start_one() {
  local entry="$1"
  local label slug
  label="$(parse_entry "$entry" label)"
  slug="$(slug_for_entry "$entry")"

  if job_completed "$slug"; then
    log "SKIP $label already COMPLETED slug=$slug"
    postpull_slug "$slug"
    return 0
  fi

  if job_running "$slug"; then
    log "RESUME $label already running slug=$slug"
    return 0
  fi

  if ! export_one "$entry"; then
    log "ERROR start aborted for $label (export failed)"
    return 1
  fi
  submit_one "$slug"
  log "STARTED $label slug=$slug"
}

resubmit_one() {
  local entry="$1"
  local label slug
  label="$(parse_entry "$entry" label)"
  slug="$(slug_for_entry "$entry")"
  log "RESUBMIT $label slug=$slug"
  kill_slug "$slug"
  sleep 5
  rm -f "output/jobs/${slug}/${slug}.lck"
  if ! export_one "$entry"; then
    log "ERROR resubmit export failed $label slug=$slug"
    return 1
  fi
  submit_one "$slug"
}

declare -A LAST_SIM
declare -A STALL_SINCE
declare -A RESUBMIT_COUNT

init_state() {
  python3 -c "
import json, datetime
print(json.dumps({
  'policy': 'ellipse_444_baseline parallel (Neo-Hooke paper)',
  'material': 'paper',
  'cpus': $CPUS,
  'memory_mb': $MEM,
  'max_parallel': $MAX_PARALLEL,
  'queue_labels': [x.split('|',1)[0] for x in '''${QUEUE[*]}'''.split()],
  'phase': 'running',
  'started_at': datetime.datetime.now().isoformat(timespec='seconds'),
}, indent=2))
" > "$STATE"
}

finish_state() {
  python3 -c "
import json, datetime
s=json.load(open('$STATE'))
s['phase']='done'
s['finished_at']=datetime.datetime.now().isoformat(timespec='seconds')
json.dump(s, open('$STATE','w'), indent=2)
"
}

update_state_snapshot() {
  python3 - <<PY
import json, datetime, sys
from pathlib import Path

root = Path(".")
state_path = root / "output/logs/ellipse_444_baseline_state.json"
queue_path = root / "output/logs/ellipse_444_baseline_queue.tsv"
state = json.loads(state_path.read_text(encoding="utf-8"))
entries = [ln for ln in queue_path.read_text(encoding="utf-8").strip().split("\n") if ln]

def slug_for(q, align):
    sys.path.insert(0, str(root))
    from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G
    tag = G(cell_size=20, rod_diameter=2, amplitude=2, period_factor=float(q)).variant_name.lower()
    return f"hu_bai_{tag}_L20_4x4x4_solid_cad_f_${BASE_SUFFIX}_ellipse_{align}"

items = []
all_done = True
for raw in entries:
    label, q, align, cad = raw.split("|", 3)
    slug = slug_for(q, align)
    sta = root / "output/jobs" / slug / f"{slug}.sta"
    csv = root / "output/post" / slug / f"{slug}_stress_strain.csv"
    txt = sta.read_text(encoding="utf-8", errors="replace") if sta.is_file() else ""
    completed = "COMPLETED SUCCESSFULLY" in txt
    csv_ok = csv.is_file()
    running = (root / "output/jobs" / slug / f"{slug}.lck").is_file()
    items.append({
        "label": label, "q": q, "align": align, "slug": slug,
        "completed": completed, "csv_ready": csv_ok, "running": running,
    })
    all_done = all_done and completed and csv_ok

state["cases"] = items
state["all_done"] = all_done
state["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
print(json.dumps({"all_done": all_done, "running": sum(1 for x in items if x["running"])}, indent=2))
PY
}

for entry in "${QUEUE[@]}"; do
  cad="$(parse_entry "$entry" cad)"
  [[ -f "$cad" ]] || { log "ERROR preflight missing CAD: $cad"; exit 1; }
done

QUEUE_FILE="output/logs/ellipse_444_baseline_queue.tsv"
printf '%s\n' "${QUEUE[@]}" > "$QUEUE_FILE"

log "=== ellipse_444_baseline start cpus=$CPUS mem_mb=$MEM max_parallel=$MAX_PARALLEL jobs=${#QUEUE[@]} material=paper(Neo-Hooke) ==="
init_state

while true; do
  running="$(count_running_queue)"
  for entry in "${QUEUE[@]}"; do
    slug="$(slug_for_entry "$entry")"
    label="$(parse_entry "$entry" label)"

    if needs_work "$entry"; then
      if job_running "$slug"; then
        :
      elif [[ "$running" -lt "$MAX_PARALLEL" ]]; then
        if start_one "$entry"; then
          running=$((running + 1))
        fi
      fi
    elif job_completed "$slug"; then
      postpull_slug "$slug"
    fi
  done

  running="$(count_running_queue)"
  pending=0
  for entry in "${QUEUE[@]}"; do
    needs_work "$entry" && pending=1
  done

  for entry in "${QUEUE[@]}"; do
    slug="$(slug_for_entry "$entry")"
    label="$(parse_entry "$entry" label)"

    if job_completed "$slug"; then
      continue
    fi

    if job_failed "$slug" && ! job_running "$slug"; then
      n="${RESUBMIT_COUNT[$slug]:-0}"
      if [[ "$n" -lt 2 ]]; then
        log "FAIL $label slug=$slug resubmit_count=$n"
        resubmit_one "$entry"
        RESUBMIT_COUNT[$slug]=$((n + 1))
        LAST_SIM[$slug]=""
        STALL_SINCE[$slug]=""
      else
        log "ERROR $label slug=$slug failed after $n resubmits — manual check"
      fi
      continue
    fi

    if job_running "$slug"; then
      sim="$(last_sim_s "$slug" || echo 0)"
      ke="$(last_ke "$slug" || echo 0)"
      prev="${LAST_SIM[$slug]:-}"
      if [[ -n "$prev" && "$sim" == "$prev" ]]; then
        STALL_SINCE[$slug]="${STALL_SINCE[$slug]:-$(date +%s)}"
        stall_min=$(( ($(date +%s) - STALL_SINCE[$slug]) / 60 ))
        if [[ "$stall_min" -ge "$STALL_MIN" ]]; then
          log "STALL $label ${stall_min}min at sim=${sim}s ke=${ke} — kill + resubmit"
          n="${RESUBMIT_COUNT[$slug]:-0}"
          if [[ "$n" -lt 2 ]]; then
            resubmit_one "$entry"
            RESUBMIT_COUNT[$slug]=$((n + 1))
          else
            log "ERROR $label stall but resubmit limit reached"
          fi
          LAST_SIM[$slug]=""
          STALL_SINCE[$slug]=""
        fi
      else
        STALL_SINCE[$slug]=""
        LAST_SIM[$slug]="$sim"
      fi
      if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]]; then
        prog="$(tail -1 "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tr -s ' ' | cut -c1-72 || true)"
        log "[$label] RUNNING sim=${sim}s ke=${ke} ${prog:+( $prog )}"
      fi
    elif [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]] && ! job_completed "$slug"; then
      n="${RESUBMIT_COUNT[$slug]:-0}"
      if [[ "$n" -lt 2 ]]; then
        log "STOPPED $label slug=$slug (not running) — resubmit"
        resubmit_one "$entry"
        RESUBMIT_COUNT[$slug]=$((n + 1))
      fi
    fi
  done

  update_state_snapshot >> "$LOG" 2>&1 || true
  log "tick running=$running max=$MAX_PARALLEL pending=$pending"
  [[ "$pending" -eq 0 ]] && break
  sleep "$POLL_SEC"
done

for entry in "${QUEUE[@]}"; do
  postpull_slug "$(slug_for_entry "$entry")"
done

finish_state
log "=== ellipse_444_baseline finished ==="
