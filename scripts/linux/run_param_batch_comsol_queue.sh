#!/usr/bin/env bash
# Param-batch COMSOL isolation: frequency-only (no eigen), hierarchical under 批量构型/.
#
#   bash scripts/linux/run_param_batch_comsol_queue.sh
#
# Env:
#   BATCH_COMSOL_NP=16
#   BATCH_COMSOL_ONLY="af2q0_deq2_k1 af2q0p5_deq2_k1"
#   BATCH_COMSOL_FORCE=1
#   BATCH_COMSOL_FREQ_MIN=10 BATCH_COMSOL_FREQ_MAX=500 BATCH_COMSOL_FREQ_STEP=10
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"
# MPh needs an X display (mphserver -graphics). Prefer existing desktop :1.
export DISPLAY="${DISPLAY:-:1}"

BATCH_CAD="$ROOT/output/cad/批量构型"
BATCH_NAME="批量构型"
COMSOL_BATCH="$ROOT/output/comsol_jobs/${BATCH_NAME}"
RUN_SLUG="${BATCH_COMSOL_RUN_SLUG:-fig28_p1_300g}"
NP="${BATCH_COMSOL_NP:-8}"
FORCE="${BATCH_COMSOL_FORCE:-0}"
ONLY="${BATCH_COMSOL_ONLY:-}"
FREQ_MIN="${BATCH_COMSOL_FREQ_MIN:-10}"
FREQ_MAX="${BATCH_COMSOL_FREQ_MAX:-500}"
FREQ_STEP="${BATCH_COMSOL_FREQ_STEP:-10}"
FREQ_N=$(( (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 ))
LATTICE_HAUTO="${BATCH_COMSOL_LATTICE_HAUTO:-4}"
FIXTURE_HAUTO="${BATCH_COMSOL_FIXTURE_HAUTO:-5}"

mkdir -p output/logs "$COMSOL_BATCH"
LOG="output/logs/param_batch_comsol_queue.log"
INDEX_OUT="${COMSOL_BATCH}/_batch_comsol_index.json"
STATUS_OUT="${COMSOL_BATCH}/_batch_comsol_status.json"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

python_cmd() {
  # Hard-prefer conda python with MPh/jpype installed.
  # Project .venv has include-system-site-packages=false and cannot import MPh.
  if [[ -n "${BATCH_COMSOL_PYTHON:-}" && -x "${BATCH_COMSOL_PYTHON}" ]]; then
    echo "$BATCH_COMSOL_PYTHON"
    return 0
  fi
  if [[ -x /home/art/conda/bin/python3 ]]; then
    echo /home/art/conda/bin/python3
    return 0
  fi
  echo python3
}
PY="$(python_cmd)"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] python=$PY" | tee -a "$LOG"
"$PY" -c "import jpype, mph; print('mph_ok', mph.__version__)" | tee -a "$LOG"

export BATCH_COMSOL_ONLY="$ONLY"
export BATCH_COMSOL_RUN_SLUG="$RUN_SLUG"
export BATCH_COMSOL_NP="$NP"
export BATCH_COMSOL_FREQ_MIN="$FREQ_MIN"
export BATCH_COMSOL_FREQ_MAX="$FREQ_MAX"
export BATCH_COMSOL_FREQ_STEP="$FREQ_STEP"

# Build index + ready queue from per-case qc.json (freq-only; do not trust stale _batch_status)
mapfile -t READY < <("$PY" - <<'PY'
import json, os
from pathlib import Path

root = Path(".").resolve()
batch = root / "output" / "cad" / "批量构型"
comsol = root / "output" / "comsol_jobs" / "批量构型"
idx = json.loads((batch / "_batch_index.json").read_text(encoding="utf-8"))
only = {x for x in os.environ.get("BATCH_COMSOL_ONLY", "").split() if x}
run_slug = os.environ.get("BATCH_COMSOL_RUN_SLUG", "fig28_p1_300g")
order = list(idx.get("generation_order") or [])

def qc_ok(path: Path):
    if not path.is_file():
        return False, None
    d = json.loads(path.read_text(encoding="utf-8"))
    nested = d.get("qc") or {}
    ok = bool(
        d.get("ok")
        or d.get("qc_ok")
        or d.get("status") == "ok"
        or nested.get("ok")
        or nested.get("status") == "ok"
    )
    vr = d.get("volume_ratio") or nested.get("volume_ratio")
    return ok, vr

ready = []
for cid in order:
    if only and cid not in only:
        continue
    meta = dict(idx.get("cases", {}).get(cid) or {})
    arr = batch / cid / f"{cid}_444.step"
    ok, vr = qc_ok(batch / cid / f"{cid}_qc.json")
    if not ok:
        continue
    if not arr.is_file() or arr.stat().st_size < 1_000_000:
        continue
    ready.append({
        "case_id": cid,
        "Af": float(meta.get("Af", 2.0)),
        "Q": float(meta.get("Q", 0.0)),
        "deq_mm": float(meta.get("deq_mm", 2.0)),
        "k": float(meta.get("k", 1.0)),
        "phase": meta.get("phase"),
        "cad_step": str(arr.as_posix()),
        "volume_ratio": vr,
        "run_slug": run_slug,
        "job_rel": f"output/comsol_jobs/批量构型/{cid}/{run_slug}",
    })

out = {
    "name": "批量构型_comsol_isolation",
    "thesis": "Hu & Bai 2024 §2.4.3 / Fig.2.8 — COMSOL frequency transmissibility (eigen OFF)",
    "cad_root": "output/cad/批量构型",
    "comsol_root": "output/comsol_jobs/批量构型",
    "run_slug": run_slug,
    "defaults": {
        "cells": [4, 4, 4],
        "cell_size_mm": 20.0,
        "include_fig28": True,
        "interface_coupling": "p1_continuity",
        "top_payload_kg": 0.3,
        "lattice_mesh_mm": 0.6,
        "excitation_axis": "z",
        "base_acceleration_m_s2": 0.98,
        "run_eigen": False,
        "studies": ["freq"],
        "physics_controlled_mesh": True,
        "mesh_note": "physics-controlled hauto (same as fig321 mesh_p1); avoids broken fixture Mesh Copy",
        "freq_hz": [
            float(os.environ.get("BATCH_COMSOL_FREQ_MIN", "10")),
            float(os.environ.get("BATCH_COMSOL_FREQ_MAX", "2000")),
            float(os.environ.get("BATCH_COMSOL_FREQ_STEP", "10")),
        ],
        "np": int(os.environ.get("BATCH_COMSOL_NP", "16")),
    },
    "expected_files": {
        "case_manifest.json": "build settings + CAD/job paths",
        "{run_slug}.mph": "unsolved model (after build)",
        "{run_slug}_solved.mph": "after freq solve",
        "{run_slug}_transmissibility.csv": "T(f) = a_top/a_base",
        "{run_slug}_batch.log": "comsol batch solve log",
    },
    "queue": [r["case_id"] for r in ready],
    "cases": {r["case_id"]: r for r in ready},
    "skipped_note": "Only QC-ok CAD cases; eigen study disabled (--freq-only)",
}
comsol.mkdir(parents=True, exist_ok=True)
(comsol / "_batch_comsol_index.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
for r in ready:
    (comsol / r["case_id"] / run_slug).mkdir(parents=True, exist_ok=True)
    print(r["case_id"])
PY
)

if [[ ${#READY[@]} -eq 0 ]]; then
  log "ABORT: no QC-ok cases with array STEP found under $BATCH_CAD"
  exit 1
fi

log "=== param-batch COMSOL freq-only start np=$NP freq=${FREQ_MIN}-${FREQ_MAX}/${FREQ_STEP} (${FREQ_N} pts/case) lattice_hauto=$LATTICE_HAUTO cases=${#READY[@]} ==="
log "queue: ${READY[*]}"
log "eigen: OFF (--freq-only)"

case_params() {
  local cid="$1"
  "$PY" - <<PY
import json
d=json.load(open("${INDEX_OUT}",encoding="utf-8"))
c=d["cases"]["$cid"]
print(f'{c["Af"]} {c["Q"]} {c["deq_mm"]} {c["cad_step"]}')
PY
}

job_dir() {
  local cid="$1"
  echo "${COMSOL_BATCH}/${cid}/${RUN_SLUG}"
}

case_done() {
  local cid="$1"
  local jd slug_csv
  jd="$(job_dir "$cid")"
  slug_csv="${jd}/${RUN_SLUG}_transmissibility.csv"
  [[ -f "${jd}/${RUN_SLUG}_solved.mph" ]] || return 1
  [[ -f "$slug_csv" ]] || return 1
  # reject format-preview placeholders
  if grep -q 'FORMAT SAMPLE' "$slug_csv" 2>/dev/null; then
    return 1
  fi
  return 0
}

freq_plan_stale() {
  # Exit 0 when case_manifest freq_hz matches current queue plan; 1 when rebuild needed.
  local jd="$1"
  local manifest="${jd}/case_manifest.json"
  [[ -f "$manifest" ]] || return 1
  FREQ_MANIFEST="$manifest" FREQ_MIN="$FREQ_MIN" FREQ_MAX="$FREQ_MAX" FREQ_STEP="$FREQ_STEP" "$PY" - <<'PY'
import json, os, sys
from pathlib import Path
p = Path(os.environ["FREQ_MANIFEST"])
d = json.loads(p.read_text(encoding="utf-8"))
fh = (d.get("isolation") or {}).get("freq_hz") or []
if len(fh) != 3:
    sys.exit(1)
want = [float(os.environ["FREQ_MIN"]), float(os.environ["FREQ_MAX"]), float(os.environ["FREQ_STEP"])]
cur = [float(x) for x in fh]
sys.exit(0 if cur == want else 1)
PY
}

clear_case_solve_artifacts() {
  local jd="$1"
  rm -f "${jd}/${RUN_SLUG}.mph" "${jd}/${RUN_SLUG}_solved.mph" \
    "${jd}/${RUN_SLUG}_solved.mph.status" "${jd}/${RUN_SLUG}_solved.mph.recovery" \
    "${jd}/${RUN_SLUG}_transmissibility.csv" "${jd}/${RUN_SLUG}_batch.log" \
    "${jd}/${RUN_SLUG}_eigenfrequencies.csv" "${jd}/case_manifest.json" \
    "${jd}/_error.txt" 2>/dev/null || true
}

solved_ok() {
  # True if comsol batch finished writing a usable solved mph (even if wrapper died).
  local jd="$1"
  local solved="${jd}/${RUN_SLUG}_solved.mph"
  local blog="${jd}/${RUN_SLUG}_batch.log"
  local st="${jd}/${RUN_SLUG}_solved.mph.status"
  [[ -f "$solved" ]] || return 1
  [[ "$(stat -c%s "$solved" 2>/dev/null || echo 0)" -gt 100000000 ]] || return 1
  if [[ -f "$st" ]] && grep -qi 'Done' "$st" 2>/dev/null; then
    return 0
  fi
  if [[ -f "$blog" ]] && grep -qE '当前进度:[[:space:]]*100 % - 完成|参数 freq = 2000' "$blog" 2>/dev/null; then
    return 0
  fi
  return 1
}

batch_running_for() {
  # True if a comsol batch/launcher is still working this case's job dir.
  local cid="$1"
  local jd
  jd="$(job_dir "$cid")"
  pgrep -f "comsolbatch.*${cid}|comsollauncher.*${cid}|comsol batch.*${jd}" >/dev/null 2>&1
}

wait_orphaned_batch() {
  # If wrapper SIGSEGV'd, comsol batch child may still be writing solved.mph.
  local cid="$1"
  local jd blog
  jd="$(job_dir "$cid")"
  blog="${jd}/${RUN_SLUG}_batch.log"
  local waited=0
  local max_wait="${BATCH_COMSOL_ORPHAN_WAIT_SEC:-7200}"
  while (( waited < max_wait )); do
    if solved_ok "$jd"; then
      log "RECOVER $cid: orphaned comsol batch finished (solved.mph ready)"
      return 0
    fi
    if ! batch_running_for "$cid"; then
      # no launcher; give filesystem a moment then recheck
      sleep 5
      if solved_ok "$jd"; then
        log "RECOVER $cid: solved.mph appeared after batch exit"
        return 0
      fi
      return 1
    fi
    if (( waited % 120 == 0 )); then
      local freq=""
      if [[ -f "$blog" ]]; then
        freq="$(grep -oE '参数 freq = [0-9.]+' "$blog" 2>/dev/null | tail -1 || true)"
      fi
      log "WAIT orphan batch $cid ${waited}s ${freq}"
    fi
    sleep 30
    waited=$((waited + 30))
  done
  return 1
}

extract_one() {
  local cid="$1"
  local jd case_log
  jd="$(job_dir "$cid")"
  case_log="output/logs/param_batch_comsol_${cid}.log"
  export HU_BAI_COMSOL_JOBS_ROOT="${COMSOL_BATCH}/${cid}"
  write_status "$cid" "extracting" >/dev/null || true
  log "EXTRACT $cid"
  set +e
  "$PY" -u scripts/comsol_extract_isolation.py "${jd}/${RUN_SLUG}_solved.mph" \
      >>"$case_log" 2>&1
  local erc=$?
  set -e
  tee -a "$LOG" <"$case_log" >/dev/null || true
  if [[ $erc -ne 0 ]]; then
    log "WARN extract failed $cid (exit=$erc, solved mph kept)"
  fi
  if [[ -f "${jd}/${RUN_SLUG}_transmissibility.csv" ]] && ! grep -q 'FORMAT SAMPLE' "${jd}/${RUN_SLUG}_transmissibility.csv"; then
    "$PY" -u scripts/plot_comsol_vld.py "${jd}/${RUN_SLUG}_transmissibility.csv" \
      >>"$case_log" 2>&1 || true
  fi
  unset HU_BAI_COMSOL_JOBS_ROOT
  if case_done "$cid"; then
    log "DONE $cid"
    rm -f "${jd}/_error.txt"
    write_status "" "" >/dev/null || true
    return 0
  fi
  echo "incomplete: missing csv after extract $(date -Iseconds)" > "${jd}/_error.txt"
  write_status "$cid" "error" >/dev/null || true
  return 1
}

write_status() {
  local current="${1:-}"
  local phase="${2:-}"
  CURRENT_CASE="$current" CURRENT_PHASE="$phase" "$PY" - <<'PY'
import json, datetime, os
from pathlib import Path
idx = json.loads(Path(os.environ["INDEX_OUT"]).read_text(encoding="utf-8"))
run = idx["run_slug"]
current = os.environ.get("CURRENT_CASE", "")
phase = os.environ.get("CURRENT_PHASE", "") or "running"
rows = []
for cid in idx["queue"]:
    jd = Path("output/comsol_jobs/批量构型") / cid / run
    mph = jd / f"{run}.mph"
    solved = jd / f"{run}_solved.mph"
    csvp = jd / f"{run}_transmissibility.csv"
    blog = jd / f"{run}_batch.log"
    err = jd / "_error.txt"
    status = "pending"
    progress = None
    if csvp.is_file() and "FORMAT SAMPLE" not in csvp.read_text(encoding="utf-8", errors="ignore"):
        status = "completed"
    elif solved.is_file() and solved.stat().st_size > 100_000_000:
        # Prefer solved recovery over stale _error.txt (wrapper SIGSEGV false fail).
        status = "solved_extracting"
        if err.is_file():
            progress = "solved.mph ready (ignore stale error marker)"
    elif err.is_file():
        status = "error"
        progress = err.read_text(errors="ignore").strip().splitlines()[-1][:140] if err.stat().st_size else None
    elif solved.is_file() and solved.stat().st_size > 1_000_000:
        status = "solved_extracting"
    elif mph.is_file() and mph.stat().st_size > 1_000_000:
        status = "built"
        if blog.is_file():
            try:
                lines = blog.read_text(errors="ignore").strip().splitlines()
                progress = (lines[-1] if lines else "")[:140]
            except Exception:
                progress = None
    if current and cid == current and status not in ("completed", "error"):
        status = phase
    rows.append({
        "case_id": cid,
        "status": status,
        "progress": progress,
        "job_dir": str(jd.as_posix()),
    })
out = {
    "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "phase": "freq_only_queue",
    "run_slug": run,
    "run_eigen": False,
    "physics_controlled_mesh": True,
    "current": current or None,
    "cases": rows,
}
Path(os.environ["STATUS_OUT"]).write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
n_ok = sum(1 for r in rows if r["status"] == "completed")
n_err = sum(1 for r in rows if r["status"] == "error")
print(f"status written: completed={n_ok}/{len(rows)} error={n_err}")
PY
}
export INDEX_OUT STATUS_OUT

clean_preview() {
  local jd="$1"
  rm -f "${jd}/_EXPECTED_FILES.txt" "${jd}/.gitkeep" 2>/dev/null || true
  if [[ -f "${jd}/${RUN_SLUG}_transmissibility.csv" ]] && grep -q 'FORMAT SAMPLE' "${jd}/${RUN_SLUG}_transmissibility.csv" 2>/dev/null; then
    rm -f "${jd}/${RUN_SLUG}_transmissibility.csv" "${jd}/${RUN_SLUG}_eigenfrequencies.csv"
  fi
  if [[ -f "${jd}/case_manifest.json" ]] && grep -q '_format_preview' "${jd}/case_manifest.json" 2>/dev/null; then
    rm -f "${jd}/case_manifest.json"
  fi
}

run_one() {
  local cid="$1"
  local Af Q deq cad jd
  read -r Af Q deq cad <<<"$(case_params "$cid")"
  [[ -f "$cad" ]] || { log "ERROR missing CAD $cad"; return 1; }
  jd="$(job_dir "$cid")"
  mkdir -p "$jd"
  clean_preview "$jd"

  if case_done "$cid" && [[ "$FORCE" != "1" ]]; then
    log "SKIP done $cid"
    return 0
  fi

  # Recover: solved mph already finished (wrapper may have SIGSEGV'd) → extract only.
  if [[ "$FORCE" != "1" ]] && solved_ok "$jd" && ! case_done "$cid"; then
    log "RECOVER extract-only $cid (solved.mph present, no CSV)"
    rm -f "${jd}/_error.txt"
    extract_one "$cid"
    return $?
  fi

  export HU_BAI_COMSOL_JOBS_ROOT="${COMSOL_BATCH}/${cid}"
  local case_log="output/logs/param_batch_comsol_${cid}.log"
  local mph="${jd}/${RUN_SLUG}.mph"

  if [[ "$FORCE" == "1" ]]; then
    clear_case_solve_artifacts "$jd"
  elif [[ -f "$mph" ]] && ! freq_plan_stale "$jd"; then
    log "REBUILD $cid: freq plan changed → ${FREQ_MIN}-${FREQ_MAX}/${FREQ_STEP} (${FREQ_N} pts)"
    clear_case_solve_artifacts "$jd"
  fi

  rm -f "${jd}/_error.txt"
  local common_args=(
    --comsol-bin "$COMSOL_BIN"
    --Q "$Q" --Af "$Af" --rod-diameter "$deq"
    --cells 4 --nz 4
    --cad "$cad"
    --slug "$RUN_SLUG"
    --freq-only
    --physics-controlled-mesh
    --excitation-axis z
    --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP"
    --fixture-template "$ROOT/output/comsol_jobs/comsol_fixture_444/comsol_fixture_444.mph"
    --np "$NP"
    --lattice-hauto "$LATTICE_HAUTO"
    --fixture-hauto "$FIXTURE_HAUTO"
  )

  # --- Phase A: build in its own process (MPh client dies with the process) ---
  if [[ ! -f "$mph" || "$(stat -c%s "$mph" 2>/dev/null || echo 0)" -lt 1000000 || "$FORCE" == "1" ]]; then
    log "BUILD $cid Af=$Af Q=$Q deq=$deq np=$NP (physics-controlled, build-only)"
    write_status "$cid" "building" >/dev/null || true
    set +e
    "$PY" -u scripts/comsol_run_hu_bai.py "${common_args[@]}" --build-only \
        >"$case_log" 2>&1
    local brc=$?
    set -e
    tee -a "$LOG" <"$case_log" >/dev/null || true
    if [[ $brc -ne 0 || ! -f "$mph" ]]; then
      log "ERROR build failed $cid (exit=$brc)"
      echo "build failed exit=$brc $(date -Iseconds)" > "${jd}/_error.txt"
      tail -n 40 "$case_log" >> "${jd}/_error.txt" 2>/dev/null || true
      write_status "$cid" "error" >/dev/null || true
      unset HU_BAI_COMSOL_JOBS_ROOT
      return 1
    fi
  else
    log "REUSE mph $cid -> $mph"
  fi

  # --- Phase B: solve without MPh (no ClientWebSocket during multi-hour wait) ---
  if ! solved_ok "$jd"; then
    # Soft-relaunch: previous wrapper may have been killed while batch still runs.
    if batch_running_for "$cid"; then
      log "WAIT existing comsol batch $cid (reuse in-flight solve)"
      write_status "$cid" "solving" >/dev/null || true
      if wait_orphaned_batch "$cid"; then
        :
      else
        log "WARN in-flight batch gone without solved.mph $cid — will start fresh solve"
        rm -f "${jd}/${RUN_SLUG}_solved.mph" \
          "${jd}/${RUN_SLUG}_solved.mph.status" \
          "${jd}/${RUN_SLUG}_solved.mph.recovery" 2>/dev/null || true
      fi
    fi
  fi
  if ! solved_ok "$jd"; then
    log "SOLVE $cid (solve-only, comsol batch np=$NP)"
    write_status "$cid" "solving" >/dev/null || true
    set +e
    "$PY" -u scripts/comsol_run_hu_bai.py "${common_args[@]}" \
        --solve-only "$mph" \
        >>"$case_log" 2>&1
    local src=$?
    set -e
    tee -a "$LOG" <"$case_log" >/dev/null || true
    if [[ $src -ne 0 ]]; then
      log "WARN solve wrapper exit=$src $cid — check orphaned batch / solved.mph"
      if wait_orphaned_batch "$cid"; then
        :
      elif solved_ok "$jd"; then
        log "RECOVER $cid: solved.mph OK despite wrapper exit=$src"
      else
        log "ERROR solve failed $cid (exit=$src)"
        echo "solve failed exit=$src $(date -Iseconds)" > "${jd}/_error.txt"
        tail -n 40 "$case_log" >> "${jd}/_error.txt" 2>/dev/null || true
        write_status "$cid" "error" >/dev/null || true
        unset HU_BAI_COMSOL_JOBS_ROOT
        return 1
      fi
    fi
  else
    log "REUSE solved $cid"
  fi

  unset HU_BAI_COMSOL_JOBS_ROOT
  extract_one "$cid"
}

for cid in "${READY[@]}"; do
  run_one "$cid" || log "CONTINUE after failure on $cid"
done

write_status "" "" | tee -a "$LOG" || true
log "=== param-batch COMSOL queue finished ==="
