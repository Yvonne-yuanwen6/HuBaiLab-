#!/usr/bin/env bash
# Param-batch Abaqus queue: CAE auto-mesh only, hierarchical export/jobs/post under 批量构型/.
#
# Flow:
#   1) Submit already-exported INPs (up to BATCH_SIM_MAX_PARALLEL, background)
#   2) Continue CAE mesh+export for remaining cases (serial, license-safe)
#   3) On mesh failure: CAE strategy ladder; true failure -> SKIP and continue
#   4) As each export finishes, fill free submit slots
#
# Env:
#   BATCH_SIM_CPUS=48
#   BATCH_SIM_MEMORY_MB=262144
#   BATCH_SIM_MAX_PARALLEL=2
#   BATCH_SIM_ONLY="af2q0_deq2_k1 ..."
#   BATCH_SIM_EXPORT_ONLY=1
#   BATCH_SIM_SUBMIT_ONLY=1
#   BATCH_SIM_FORCE_REMESH=1
#   BATCH_SIM_SKIP_BASELINE=1   # skip lattice_contact+vtopo baseline; still try other seed-0.6
#                               # ladder steps first (auto=1 when FORCE_REMESH=1 unless set to 0)
#   BATCH_SIM_MESH_PROTOCOL=1   # unified comparable mesh: OCP+Gmsh STEP heal + only
#                               # seed0.6 + fast + virtual-topology (no quality/seed ladder)
#   BATCH_SIM_ALLOW_SOLVE_RETRY=0   # if 1, allow re-submit after solve crash (default: skip)
#   BATCH_SIM_IGNORE_PAUSE=1        # ignore _batch_sim_paused.json and run anyway
#   BATCH_HEAL_TIMEOUT_S=2400       # total heal wall budget (0=unlimited)
#   BATCH_HEAL_PRESET_TIMEOUT_S=900 # per-preset heal kill budget
#   BATCH_HEAL_OCP_PREREPAIR=1      # OCP ShapeFix before gmsh presets (default on)
#   BATCH_SIM_FORCE_HEAL=1          # re-heal even if prior used_heal report exists
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

BATCH_NAME="批量构型"
VERIFIED="$ROOT/output/cad/verified"
RUN_SLUG="cae_tet0p6mm80_5mmin_paperbox"
CPUS="${BATCH_SIM_CPUS:-48}"
MEM="${BATCH_SIM_MEMORY_MB:-262144}"
MAX_PARALLEL="${BATCH_SIM_MAX_PARALLEL:-2}"
POLL_SEC="${BATCH_SIM_POLL_SEC:-45}"
FORCE_REMESH="${BATCH_SIM_FORCE_REMESH:-0}"
EXPORT_ONLY="${BATCH_SIM_EXPORT_ONLY:-0}"
SUBMIT_ONLY="${BATCH_SIM_SUBMIT_ONLY:-0}"
# Unified mesh protocol for cross-case comparability (heal + single CAE setting).
MESH_PROTOCOL="${BATCH_SIM_MESH_PROTOCOL:-0}"
# Default: never re-submit a case whose previous Abaqus solve already exited with errors.
ALLOW_SOLVE_RETRY="${BATCH_SIM_ALLOW_SOLVE_RETRY:-0}"
ONLY="${BATCH_SIM_ONLY:-}"
FORCE_HEAL="${BATCH_SIM_FORCE_HEAL:-0}"
export BATCH_HEAL_TIMEOUT_S="${BATCH_HEAL_TIMEOUT_S:-2400}"
export BATCH_HEAL_PRESET_TIMEOUT_S="${BATCH_HEAL_PRESET_TIMEOUT_S:-900}"
export BATCH_SIM_FORCE_HEAL="$FORCE_HEAL"
# Remesh often hits fragile BREPs; default skip the known-bad baseline when forcing remesh.
if [[ -z "${BATCH_SIM_SKIP_BASELINE:-}" && "$FORCE_REMESH" == "1" ]]; then
  export BATCH_SIM_SKIP_BASELINE=1
fi
# Protocol mode implies skip multi-strategy baseline/ladder.
if [[ "$MESH_PROTOCOL" == "1" ]]; then
  export BATCH_SIM_SKIP_BASELINE=1
fi
export BATCH_SIM_ONLY="$ONLY"
export BATCH_SIM_CPUS="$CPUS"
export BATCH_SIM_MEMORY_MB="$MEM"
export BATCH_SIM_RUN_SLUG="$RUN_SLUG"
export BATCH_SIM_MESH_PROTOCOL="$MESH_PROTOCOL"

PAUSE_FILE="output/export/${BATCH_NAME}/_batch_sim_paused.json"
if [[ -f "$PAUSE_FILE" && "${BATCH_SIM_IGNORE_PAUSE:-0}" != "1" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ABORT: pause marker $PAUSE_FILE present. Clear it or set BATCH_SIM_IGNORE_PAUSE=1." >&2
  exit 2
fi

mkdir -p output/logs \
  "output/export/${BATCH_NAME}" \
  "output/jobs/${BATCH_NAME}" \
  "output/post/${BATCH_NAME}" \
  "$VERIFIED"

LOG="output/logs/param_batch_cae_sim_queue.log"
SKIP_FILE="output/export/${BATCH_NAME}/_batch_sim_skipped.json"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]]; then
    echo "$ROOT/.venv/bin/python3"
  else
    echo python3
  fi
}
PY="$(python_cmd)"

mapfile -t READY < <("$PY" - <<'PY'
import json, os
from pathlib import Path

root = Path(".").resolve()
batch = root / "output" / "cad" / "批量构型"
st = json.loads((batch / "_batch_status.json").read_text(encoding="utf-8"))
idx = json.loads((batch / "_batch_index.json").read_text(encoding="utf-8"))
only = [x for x in os.environ.get("BATCH_SIM_ONLY", "").split() if x]
only_set = set(only)
order = list(idx.get("generation_order") or [])
seen, ordered = set(), []
# When ONLY is set, preserve that order (easy-first remesh, etc.).
for cid in (only if only else []) + order + [c["case_id"] for c in st["cases"]]:
    if cid in seen:
        continue
    seen.add(cid)
    ordered.append(cid)

ready = []
for cid in ordered:
    if only_set and cid not in only_set:
        continue
    row = next((c for c in st["cases"] if c["case_id"] == cid), None)
    meta = dict(idx.get("cases", {}).get(cid) or {})
    arr = batch / cid / f"{cid}_444.step"
    if not arr.is_file() or arr.stat().st_size < 1_000_000:
        continue
    # Explicit ONLY list: allow cases missing from _batch_status (status often
    # gets overwritten) as long as array STEP exists.
    if not row:
        if cid not in only_set:
            continue
        row = {"case_id": cid, "qc_ok": True, "volume_ratio": None}
    # Explicit ONLY may include qc_fail cases (e.g. remesh after STEP repair).
    if not row.get("qc_ok") and cid not in only_set:
        continue
    ready.append({
        "case_id": cid,
        "Af": float(meta.get("Af", 2.0)),
        "Q": float(meta.get("Q", 0.0)),
        "deq_mm": float(meta.get("deq_mm", 2.0)),
        "k": float(meta.get("k", 1.0)),
        "phase": meta.get("phase"),
        "cad_step": str(arr.as_posix()),
        "volume_ratio": row.get("volume_ratio"),
        "run_slug": os.environ.get("BATCH_SIM_RUN_SLUG", "cae_tet0p6mm80_5mmin_paperbox"),
        "mesh": "cae_auto_only",
        "cpus": int(os.environ.get("BATCH_SIM_CPUS", "48")),
        "memory_mb": int(os.environ.get("BATCH_SIM_MEMORY_MB", "262144")),
    })

out = {
    "name": "批量构型_abaqus_cae",
    "cad_root": "output/cad/批量构型",
    "export_root": "output/export/批量构型",
    "jobs_root": "output/jobs/批量构型",
    "post_root": "output/post/批量构型",
    "run_slug": os.environ.get("BATCH_SIM_RUN_SLUG", "cae_tet0p6mm80_5mmin_paperbox"),
    "mesh_policy": "CAE automatic tet only; failure uses CAE strategy ladder then skip",
    "cases": {r["case_id"]: r for r in ready},
    "queue": [r["case_id"] for r in ready],
}
Path("output/export/批量构型").mkdir(parents=True, exist_ok=True)
Path("output/export/批量构型/_batch_sim_index.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
for r in ready:
    print(r["case_id"])
PY
)

if [[ ${#READY[@]} -eq 0 ]]; then
  log "ABORT: no QC-ok cases with array STEP"
  exit 1
fi

log "=== param-batch CAE sim queue start cpus=$CPUS mem=$MEM parallel=$MAX_PARALLEL cases=${#READY[@]} allow_solve_retry=$ALLOW_SOLVE_RETRY ==="
log "queue: ${READY[*]}"

declare -A SKIPPED=()
declare -A LAUNCHED=()

load_skipped() {
  [[ -f "$SKIP_FILE" ]] || return 0
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    local cid="${line%%$'\t'*}"
    local reason="${line#*$'\t'}"
    SKIPPED["$cid"]="$reason"
  done < <(
    "$PY" - <<'PY'
import json
from pathlib import Path
p = Path("output/export/批量构型/_batch_sim_skipped.json")
if not p.is_file():
    raise SystemExit
data = json.loads(p.read_text(encoding="utf-8"))
for cid, meta in (data.get("skipped") or {}).items():
    reason = ""
    if isinstance(meta, dict):
        reason = str(meta.get("reason") or "")
    else:
        reason = str(meta)
    print(f"{cid}\t{reason}")
PY
  )
  if [[ ${#SKIPPED[@]} -gt 0 ]]; then
    log "loaded skips: ${!SKIPPED[*]}"
  fi
}

case_roots() {
  local cid="$1"
  export HU_BAI_EXPORT_ROOT="$ROOT/output/export/${BATCH_NAME}/${cid}"
  export HU_BAI_JOBS_ROOT="$ROOT/output/jobs/${BATCH_NAME}/${cid}"
  export HU_BAI_POST_ROOT="$ROOT/output/post/${BATCH_NAME}/${cid}"
  mkdir -p "$HU_BAI_EXPORT_ROOT" "$HU_BAI_JOBS_ROOT" "$HU_BAI_POST_ROOT"
}

unset_case_roots() {
  unset HU_BAI_EXPORT_ROOT HU_BAI_JOBS_ROOT HU_BAI_POST_ROOT
}

job_dir() { echo "$ROOT/output/jobs/${BATCH_NAME}/$1/${RUN_SLUG}"; }
sta_path() { echo "$(job_dir "$1")/${RUN_SLUG}.sta"; }
export_dir() { echo "$ROOT/output/export/${BATCH_NAME}/$1/${RUN_SLUG}"; }
mesh_inp_path() { echo "$(export_dir "$1")/${RUN_SLUG}_cae_mesh.inp"; }
comp_inp_path() { echo "$(export_dir "$1")/${RUN_SLUG}.inp"; }

job_running() { [[ -f "$(job_dir "$1")/${RUN_SLUG}.lck" ]]; }
job_completed() {
  local sta
  sta="$(sta_path "$1")"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}
# Lock-file collisions from a double-submit are NOT real solve failures.
job_lock_collision() {
  local cid="$1"
  local slog
  slog="$(job_dir "$cid")/${RUN_SLUG}_submit.log"
  [[ -f "$slog" ]] && grep -q 'Detected lock file' "$slog" 2>/dev/null
}

# True when a previous solve finished unsuccessfully (no .lck, not success).
# Used to prevent infinite re-submit loops (e.g. Excessive distortion crashes).
job_failed() {
  local cid="$1"
  local jd sta slog
  job_running "$cid" && return 1
  job_completed "$cid" && return 1
  # Double-submit race: second launch dies on .lck — allow a clean retry.
  job_lock_collision "$cid" && return 1
  jd="$(job_dir "$cid")"
  sta="$jd/${RUN_SLUG}.sta"
  slog="$jd/${RUN_SLUG}_submit.log"
  # Prefer explicit Abaqus failure markers in sta / submit log.
  if [[ -f "$sta" ]] && grep -qE \
      'THE ANALYSIS HAS BEEN ABORTED|Abaqus/Analysis exited with errors|Analysis exited with an error|Excessive distortion' \
      "$sta" 2>/dev/null; then
    return 0
  fi
  if [[ -f "$slog" ]] && grep -qE \
      'Abaqus/Analysis exited with errors|Abaqus/Explicit Analysis exited with an error|Abaqus Error: Abaqus/Explicit Analysis exited with an error' \
      "$slog" 2>/dev/null; then
    return 0
  fi
  return 1
}
job_fail_reason() {
  local cid="$1"
  local jd sta slog snip
  jd="$(job_dir "$cid")"
  sta="$jd/${RUN_SLUG}.sta"
  slog="$jd/${RUN_SLUG}_submit.log"
  snip=""
  if [[ -f "$sta" ]]; then
    snip="$(grep -E 'Excessive distortion|THE ANALYSIS HAS BEEN ABORTED|exited with an error|exited with errors' "$sta" 2>/dev/null | tail -1 | tr -s ' ' | cut -c1-100 || true)"
  fi
  if [[ -z "$snip" && -f "$slog" ]]; then
    snip="$(grep -E 'Excessive distortion|exited with an error|exited with errors|Detected lock file' "$slog" 2>/dev/null | tail -1 | tr -s ' ' | cut -c1-100 || true)"
  fi
  if [[ -n "$snip" ]]; then
    echo "solve failed: $snip"
  else
    echo "solve failed (Abaqus exited with errors)"
  fi
}

# Wipe a job dir that only failed due to .lck collision (tiny/no real progress).
clear_lock_collision_job() {
  local cid="$1" jd
  job_lock_collision "$cid" || return 1
  job_running "$cid" && return 1
  job_completed "$cid" && return 1
  jd="$(job_dir "$cid")"
  log "CLEAR lock-collision job dir $cid"
  rm -rf "$jd"
  mkdir -p "$jd"
  unset "LAUNCHED[$cid]" || true
  return 0
}
reap_failed_jobs() {
  [[ "$ALLOW_SOLVE_RETRY" == "1" ]] && return 0
  local cid
  for cid in "${READY[@]}"; do
    [[ -n "${SKIPPED[$cid]:-}" ]] && continue
    job_completed "$cid" && continue
    job_running "$cid" && continue
    if job_failed "$cid"; then
      mark_skip "$cid" "$(job_fail_reason "$cid")"
    fi
  done
}
inp_ready() { [[ -f "$(comp_inp_path "$1")" ]]; }

case_params() {
  local cid="$1"
  "$PY" - <<PY
import json
d=json.load(open("output/export/批量构型/_batch_sim_index.json",encoding="utf-8"))
c=d["cases"]["$cid"]
print(f'{c["Af"]} {c["Q"]} {c["deq_mm"]} {c["cad_step"]}')
PY
}

verify_cad() {
  local cid="$1" src="$2"
  local dst="$VERIFIED/batch_${cid}_paper_box_array.step"
  cp -f "$src" "$dst"
  echo "$dst"
}

mark_skip() {
  local cid="$1" reason="$2"
  SKIPPED["$cid"]="$reason"
  log "SKIP $cid :: $reason"
  BATCH_SIM_SKIP_CID="$cid" BATCH_SIM_SKIP_REASON="$reason" "$PY" - <<'PY'
import json, datetime, os
from pathlib import Path
p = Path("output/export/批量构型/_batch_sim_skipped.json")
data = {"updated_at": datetime.datetime.now().isoformat(timespec="seconds"), "skipped": {}}
if p.is_file():
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
cid = os.environ["BATCH_SIM_SKIP_CID"]
reason = os.environ.get("BATCH_SIM_SKIP_REASON", "")
data.setdefault("skipped", {})[cid] = {
    "reason": reason,
    "at": datetime.datetime.now().isoformat(timespec="seconds"),
}
data["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

# Official comparable protocol: OCP ShapeFix + Gmsh OCC heal (mass gate) then one CAE setting.
# Skip re-heal only when a prior successful used_heal report exists (failed attempts re-run).
heal_cad_for_protocol() {
  # Writes healed path to $3 (out var file); returns 0 if a path was decided.
  local cid="$1" src="$2" out_path_file="$3"
  local heal_dir="$VERIFIED/heal_${cid}"
  local skip_reason_file
  mkdir -p "$heal_dir"
  rm -f "$out_path_file"

  if [[ "${BATCH_SIM_FORCE_HEAL:-0}" != "1" ]]; then
    skip_reason_file="$(mktemp)"
    if BATCH_SIM_HEAL_CID="$cid" BATCH_SIM_HEAL_SKIP_OUT="$skip_reason_file" \
        "$PY" - <<'PY' >/dev/null 2>&1
import os, sys
from pathlib import Path
from src.export.step_heal_for_cae import should_skip_cae_heal

cid = os.environ["BATCH_SIM_HEAL_CID"]
out = Path(os.environ["BATCH_SIM_HEAL_SKIP_OUT"])
skip, reason = should_skip_cae_heal(cid)
out.write_text(reason + "\n", encoding="utf-8")
sys.exit(0 if skip else 1)
PY
    then
      reason="$(tr -d '\r\n' <"$skip_reason_file")"
      # Prefer prior healed STEP when used_heal; else verified raw.
      reuse="$src"
      if [[ -f "$heal_dir/healed_path.txt" ]]; then
        cand="$(tr -d '\r\n' <"$heal_dir/healed_path.txt")"
        if [[ -n "$cand" && -f "$cand" ]]; then
          reuse="$cand"
        fi
      fi
      log "HEAL SKIP $cid :: $reason -> $reuse"
      printf '%s\n' "$reuse" >"$out_path_file"
      # Do not clobber a real prior heal_report.json (used_heal / attempts).
      if [[ ! -f "$heal_dir/heal_report.json" ]] \
          || ! grep -qE '"used_heal": true|"attempts"' "$heal_dir/heal_report.json" 2>/dev/null; then
        printf '%s\n' "$reuse" >"$heal_dir/healed_path.txt"
        BATCH_SIM_HEAL_DIR="$heal_dir" BATCH_SIM_HEAL_SKIP_OUT="$skip_reason_file" \
          BATCH_SIM_HEAL_REUSE="$reuse" "$PY" - <<'PY' >/dev/null 2>&1 || true
import json, os
from pathlib import Path
reason = Path(os.environ["BATCH_SIM_HEAL_SKIP_OUT"]).read_text(encoding="utf-8").strip()
rep = {
    "used_heal": False,
    "skipped_cae_heal": True,
    "reason": reason,
    "reuse_step": os.environ.get("BATCH_SIM_HEAL_REUSE", ""),
}
Path(os.environ["BATCH_SIM_HEAL_DIR"], "heal_report.json").write_text(
    json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
PY
      else
        # Keep existing report; only refresh path pointer for this run.
        printf '%s\n' "$reuse" >"$heal_dir/healed_path.txt"
      fi
      rm -f "$skip_reason_file"
      return 0
    fi
    rm -f "$skip_reason_file"
  fi

  log "HEAL STEP $cid (structure-preserving v3: light sew/ShapeFix or KEEP verified raw; mass∈[0.98,1.02] face∈[0.92,1.08]; timeout=${BATCH_HEAL_TIMEOUT_S}s / preset=${BATCH_HEAL_PRESET_TIMEOUT_S}s)"
  local t0 t1
  t0="$(date +%s)"
  if ! BATCH_SIM_HEAL_SRC="$src" BATCH_SIM_HEAL_DIR="$heal_dir" BATCH_SIM_HEAL_CID="$cid" \
      "$PY" - <<'PY' >>"$LOG" 2>&1
import json, os
from pathlib import Path
from src.export.step_heal_for_cae import heal_step_for_cae

src = os.environ["BATCH_SIM_HEAL_SRC"]
out_dir = os.environ["BATCH_SIM_HEAL_DIR"]
cid = os.environ["BATCH_SIM_HEAL_CID"]
healed, rep = heal_step_for_cae(
    src,
    out_dir,
    basename=f"batch_{cid}",
    stop_on_first_ok=True,
)
Path(out_dir, "heal_report.json").write_text(
    json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
Path(out_dir, "healed_path.txt").write_text(healed + "\n", encoding="utf-8")
print(
    f"  heal done used={rep.get('used_heal')} preset={rep.get('preset')} "
    f"elapsed_s={rep.get('elapsed_s')} timed_out={rep.get('timed_out')}",
    flush=True,
)
PY
  then
    return 1
  fi
  t1="$(date +%s)"
  log "HEAL WALL $cid $((t1 - t0))s"
  if [[ -f "$heal_dir/healed_path.txt" ]]; then
    cp -f "$heal_dir/healed_path.txt" "$out_path_file"
    return 0
  fi
  return 1
}

mesh_protocol_only() {
  # Returns 0 if mesh written; uses healed STEP when heal succeeds (else raw verified).
  local cid="$1" step="$2" out="$3" deq="$4"
  local mesh_step="$step"
  local path_file
  local t_mesh0 t_mesh1
  path_file="$(mktemp)"
  fill_submit_slots || true
  if heal_cad_for_protocol "$cid" "$step" "$path_file"; then
    mesh_step="$(tr -d '\r\n' <"$path_file")"
    if [[ -n "$mesh_step" && -f "$mesh_step" && "$mesh_step" != "$step" ]]; then
      log "HEAL OK $cid -> $mesh_step"
    else
      log "HEAL kept original STEP $cid (no accepted preset / skipped / identity)"
      mesh_step="$step"
    fi
  else
    log "WARN heal failed $cid; using raw STEP"
    mesh_step="$step"
  fi
  rm -f "$path_file"
  log "CAE PROTOCOL $cid: seed0.6 quality=fast virtual-topology (no ladder)"
  t_mesh0="$(date +%s)"
  rm -f "$out"
  if bash scripts/linux/run_abaqus_cae_mesh.sh \
      --step "$mesh_step" --out "$out" --mesh-mode tet \
      --part-name LATTICE --element-type C3D4 --rods-per-diameter 3.0 \
      --seed 0.6 --mesh-quality fast --virtual-topology \
      --rod-diameter "${deq}" >>"$LOG" 2>&1; then
    if [[ -f "$out" && "$(wc -c <"$out" | tr -d ' ')" -gt 1000000 ]]; then
      t_mesh1="$(date +%s)"
      log "CAE PROTOCOL SUCCESS $cid wall=$((t_mesh1 - t_mesh0))s -> $out"
      return 0
    fi
  fi
  t_mesh1="$(date +%s)"
  log "CAE PROTOCOL FAIL $cid wall=$((t_mesh1 - t_mesh0))s (0 elems / mesh error)"
  return 1
}

# CAE strategy ladder (no gmsh). Policy: keep seed 0.6 for cross-case comparability.
# Vary quality / vtopo / seed-part-only first; only enlarge seed if all 0.6 tries fail.
# When baseline (lattice_contact+vtopo @0.6) already failed, do NOT put that combo as try#1.
# Disabled when BATCH_SIM_MESH_PROTOCOL=1.
mesh_ladder() {
  local cid="$1" step="$2" out="$3" deq="$4"
  local -a tries=(
    "--seed 0.6 --mesh-quality lattice_contact --rod-diameter ${deq}"
    "--seed 0.6 --mesh-quality lattice --virtual-topology --rod-diameter ${deq}"
    "--seed 0.6 --mesh-quality fast --virtual-topology --rod-diameter ${deq}"
    "--seed 0.6 --mesh-quality lattice_curve --virtual-topology --rod-diameter ${deq}"
    "--seed 0.6 --mesh-quality fast --seed-part-only --ignore-invalid --virtual-topology --rod-diameter ${deq}"
    "--seed 0.6 --mesh-quality coarse --seed-part-only --ignore-invalid --virtual-topology --vtopo-short-edge 3.0 --vtopo-small-face 25 --rod-diameter ${deq}"
    "--seed 0.6 --mesh-quality lattice_contact --virtual-topology --rod-diameter ${deq}"
    # Last resort only — coarser seed breaks cross-case mesh-size comparability
    "--seed 0.8 --mesh-quality coarse --seed-part-only --ignore-invalid --virtual-topology --vtopo-short-edge 3.0 --vtopo-small-face 25 --rod-diameter ${deq}"
    "--seed 0.8 --mesh-quality lattice_contact --ignore-invalid --virtual-topology --rod-diameter ${deq}"
    "--seed 1.0 --mesh-quality coarse --seed-part-only --ignore-invalid --rod-diameter ${deq}"
  )
  local i=0 args
  mkdir -p "$(dirname "$out")"
  for args in "${tries[@]}"; do
    # Keep solve slots filled while CAE ladder runs (mesh stays serial).
    fill_submit_slots || true
    i=$((i + 1))
    log "CAE ladder $cid try#$i: $args"
    rm -f "$out"
    # shellcheck disable=SC2086
    if bash scripts/linux/run_abaqus_cae_mesh.sh \
      --step "$step" --out "$out" --mesh-mode tet --part-name LATTICE --element-type C3D4 \
      --rods-per-diameter 3.0 \
      $args >>"$LOG" 2>&1; then
      if [[ -f "$out" && "$(wc -c <"$out" | tr -d ' ')" -gt 1000000 ]]; then
        log "CAE ladder $cid SUCCESS try#$i -> $out"
        return 0
      fi
      log "CAE ladder $cid try#$i wrote tiny/empty mesh; continue"
    else
      log "CAE ladder $cid FAIL try#$i"
    fi
  done
  return 1
}

export_from_mesh() {
  local cid="$1" Af="$2" Q="$3" deq="$4" verified="$5" mesh_inp="$6"
  case_roots "$cid"
  local -a args=(
    scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
    --cells 4 --Q "$Q" --Af "$Af" --rod-diameter "$deq"
    --profile fast
    --cad "$verified"
    --cae-seed 0.6
    --cae-element-type C3D4
    --cae-mesh-quality lattice_contact
    --strain 0.80 --load-rate-mm-min 5
    --explicit-dt 0.0005 --explicit-dt-mode automatic
    --material-model paper
    --contact-store-offsets
    --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02
    --slug-mode short
    --short-slug "$RUN_SLUG"
    --mesh-locally
    --cae-mesh-inp "$mesh_inp"
  )
  if ! "$PY" "${args[@]}" >>"$LOG" 2>&1; then
    unset_case_roots
    return 1
  fi
  unset_case_roots
  return 0
}

# Background compression-INP builds must not block the next CAE mesh.
declare -A EXPORT_BG_PIDS=()

start_export_bg() {
  local cid="$1" Af="$2" Q="$3" deq="$4" verified="$5" mesh_inp="$6"
  if inp_ready "$cid"; then
    return 0
  fi
  if [[ -n "${EXPORT_BG_PIDS[$cid]:-}" ]] && kill -0 "${EXPORT_BG_PIDS[$cid]}" 2>/dev/null; then
    log "EXPORT BG already running $cid pid=${EXPORT_BG_PIDS[$cid]}"
    return 0
  fi
  log "EXPORT BG start $cid (mesh ready; do not block next CAE mesh)"
  (
    if export_from_mesh "$cid" "$Af" "$Q" "$deq" "$verified" "$mesh_inp"; then
      log "EXPORT OK $cid (bg)"
    else
      log "EXPORT FAIL $cid (bg)"
      mark_skip "$cid" "compression export failed after mesh"
    fi
  ) &
  EXPORT_BG_PIDS[$cid]=$!
}

reap_export_bg() {
  local cid pid
  for cid in "${!EXPORT_BG_PIDS[@]}"; do
    pid="${EXPORT_BG_PIDS[$cid]}"
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null || true
      unset "EXPORT_BG_PIDS[$cid]"
      if inp_ready "$cid"; then
        log "EXPORT BG reaped OK $cid -> submit slot"
      else
        log "EXPORT BG reaped without INP $cid"
      fi
      fill_submit_slots || true
    fi
  done
}

wait_export_bg_all() {
  while [[ ${#EXPORT_BG_PIDS[@]} -gt 0 ]]; do
    reap_export_bg
    fill_submit_slots || true
    [[ ${#EXPORT_BG_PIDS[@]} -eq 0 ]] && break
    sleep 8
  done
}

# Mesh this case (serial CAE). Compression INP is kicked off in background.
mesh_one() {
  local cid="$1"
  local Af Q deq cad verified mesh_inp
  read -r Af Q deq cad <<<"$(case_params "$cid")"
  [[ -f "$cad" ]] || { log "ERROR missing CAD $cad"; return 1; }
  verified="$(verify_cad "$cid" "$cad")"
  case_roots "$cid"
  mesh_inp="$(mesh_inp_path "$cid")"

  if [[ "$FORCE_REMESH" == "1" ]]; then
    rm -rf "$(export_dir "$cid")" "$(job_dir "$cid")"
    mkdir -p "$(export_dir "$cid")"
  fi

  if inp_ready "$cid" && [[ "$FORCE_REMESH" != "1" ]]; then
    unset_case_roots
    log "SKIP mesh/export (inp exists) $cid"
    return 0
  fi

  if [[ -f "$mesh_inp" && "$(wc -c <"$mesh_inp" | tr -d ' ')" -gt 1000000 && "$FORCE_REMESH" != "1" ]]; then
    log "REUSE CAE mesh $cid -> $mesh_inp"
    unset_case_roots
    start_export_bg "$cid" "$Af" "$Q" "$deq" "$verified" "$mesh_inp"
    return 0
  fi

  # Unified comparable protocol: heal + seed0.6/fast/vtopo only (no strategy ladder).
  if [[ "$MESH_PROTOCOL" == "1" ]]; then
    unset_case_roots
    if mesh_protocol_only "$cid" "$verified" "$mesh_inp" "$deq"; then
      start_export_bg "$cid" "$Af" "$Q" "$deq" "$verified" "$mesh_inp"
      return 0
    fi
    return 1
  fi

  if [[ "${BATCH_SIM_SKIP_BASELINE:-0}" != "1" ]]; then
    log "CAE AUTO MESH $cid Af=$Af Q=$Q deq=$deq (baseline)"
    local -a base_args=(
      scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
      --cells 4 --Q "$Q" --Af "$Af" --rod-diameter "$deq"
      --profile fast
      --cad "$verified"
      --cae-seed 0.6
      --cae-element-type C3D4
      --cae-mesh-quality lattice_contact
      --cae-virtual-topology
      --strain 0.80 --load-rate-mm-min 5
      --explicit-dt 0.0005 --explicit-dt-mode automatic
      --material-model paper
      --contact-store-offsets
      --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02
      --slug-mode short
      --short-slug "$RUN_SLUG"
      --mesh-locally
    )
    if "$PY" "${base_args[@]}" >>"$LOG" 2>&1 && inp_ready "$cid"; then
      unset_case_roots
      log "EXPORT OK $cid (baseline all-in-one)"
      return 0
    fi
    # Baseline may have written mesh without compression INP in some paths; prefer ladder mesh.
    if [[ -f "$mesh_inp" && "$(wc -c <"$mesh_inp" | tr -d ' ')" -gt 1000000 ]]; then
      unset_case_roots
      start_export_bg "$cid" "$Af" "$Q" "$deq" "$verified" "$mesh_inp"
      return 0
    fi
    log "WARN baseline mesh/export failed $cid; CAE ladder..."
    unset_case_roots
  else
    log "SKIP baseline (BATCH_SIM_SKIP_BASELINE=1); CAE ladder first for $cid"
    unset_case_roots
  fi

  if mesh_ladder "$cid" "$verified" "$mesh_inp" "$deq"; then
    start_export_bg "$cid" "$Af" "$Q" "$deq" "$verified" "$mesh_inp"
    return 0
  fi
  return 1
}

# Back-compat name used by older call sites
export_one() { mesh_one "$@"; }

submit_one() {
  local cid="$1"
  local i
  if [[ -n "${SKIPPED[$cid]:-}" ]]; then
    return 0
  fi
  if job_completed "$cid"; then
    log "SKIP submit (completed) $cid"
    return 0
  fi
  if job_running "$cid"; then
    log "SKIP submit (running) $cid"
    return 0
  fi
  # Prevent double-submit before .lck appears (bg export reap + main loop race).
  if [[ -n "${LAUNCHED[$cid]:-}" ]]; then
    log "SKIP submit (already launched) $cid"
    return 0
  fi
  # Auto-heal prior lock-file collision, then allow one clean submit.
  clear_lock_collision_job "$cid" || true
  if [[ "$ALLOW_SOLVE_RETRY" != "1" ]] && job_failed "$cid"; then
    mark_skip "$cid" "$(job_fail_reason "$cid")"
    return 0
  fi
  if ! inp_ready "$cid"; then
    return 1
  fi
  case_roots "$cid"
  # Reserve slot BEFORE spawning so concurrent fill_submit_slots cannot double-fire.
  LAUNCHED["$cid"]=1
  log "SUBMIT $cid cpus=$CPUS mem=$MEM"
  if ! bash scripts/linux/submit_job.sh \
      --slug "$RUN_SLUG" \
      --cpus "$CPUS" \
      --memory-mb "$MEM" \
      --background >>"$LOG" 2>&1; then
    log "ERROR submit failed $cid (will retry later)"
    unset "LAUNCHED[$cid]" || true
    unset_case_roots
    return 1
  fi
  # Wait briefly for .lck so the next fill_submit_slots sees the job as running.
  for i in 1 2 3 4 5 6 7 8 9 10; do
    job_running "$cid" && break
    sleep 1
  done
  if ! job_running "$cid"; then
    if job_lock_collision "$cid"; then
      log "WARN submit hit lock collision $cid — clearing for later retry"
      clear_lock_collision_job "$cid" || true
      unset "LAUNCHED[$cid]" || true
      unset_case_roots
      return 1
    fi
    log "WARN submit returned but no .lck yet $cid (keeping LAUNCHED guard)"
  fi
  unset_case_roots
  return 0
}

count_running() {
  local n=0 cid
  for cid in "${READY[@]}"; do
    if job_running "$cid" && ! job_completed "$cid"; then
      n=$((n + 1))
    elif [[ -n "${LAUNCHED[$cid]:-}" ]] && ! job_completed "$cid" && ! job_failed "$cid"; then
      # Count in-flight launches that have not yet written .lck.
      n=$((n + 1))
    fi
  done
  echo "$n"
}

fill_submit_slots() {
  [[ "$EXPORT_ONLY" == "1" ]] && return 0
  local cid running
  reap_failed_jobs
  running="$(count_running)"
  for cid in "${READY[@]}"; do
    [[ -n "${SKIPPED[$cid]:-}" ]] && continue
    job_completed "$cid" && continue
    job_running "$cid" && continue
    [[ -n "${LAUNCHED[$cid]:-}" ]] && continue
    inp_ready "$cid" || continue
    [[ "$running" -ge "$MAX_PARALLEL" ]] && break
    if submit_one "$cid"; then
      if job_running "$cid" || [[ -n "${LAUNCHED[$cid]:-}" ]]; then
        running=$((running + 1))
      fi
    fi
  done
}

write_status() {
  "$PY" - <<'PY'
import json, datetime
from pathlib import Path
idx = json.loads(Path("output/export/批量构型/_batch_sim_index.json").read_text(encoding="utf-8"))
run = idx["run_slug"]
skipped = {}
sp = Path("output/export/批量构型/_batch_sim_skipped.json")
if sp.is_file():
    try:
        skipped = json.loads(sp.read_text(encoding="utf-8")).get("skipped") or {}
    except Exception:
        skipped = {}
rows = []
for cid in idx["queue"]:
    jd = Path("output/jobs/批量构型") / cid / run
    sta = jd / f"{run}.sta"
    lck = jd / f"{run}.lck"
    inp = Path("output/export/批量构型") / cid / run / f"{run}.inp"
    status = "pending"
    progress = None
    if cid in skipped:
        status = "skipped"
        progress = str(skipped[cid].get("reason") or "")[:120]
    elif sta.is_file() and "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta.read_text(errors="ignore"):
        status = "completed"
    elif lck.is_file():
        status = "running"
        try:
            progress = sta.read_text(errors="ignore").strip().splitlines()[-1][:120]
        except Exception:
            progress = None
    elif inp.is_file():
        status = "exported"
    rows.append({"case_id": cid, "status": status, "progress": progress, "job_dir": str(jd)})
out = {
    "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "cases": rows,
}
Path("output/export/批量构型/_batch_sim_status.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
}

# ---- kick off: submit whatever is already exported ----
load_skipped
reap_failed_jobs
if [[ "$SUBMIT_ONLY" != "1" || "$EXPORT_ONLY" != "1" ]]; then
  :
fi
if [[ "$EXPORT_ONLY" != "1" ]]; then
  log "=== kickoff submit for already-exported cases ==="
  fill_submit_slots
  write_status >/dev/null || true
fi

if [[ "$SUBMIT_ONLY" == "1" ]]; then
  log "=== submit-only: wait for jobs ==="
else
  # Mesh serially; compression INP export runs in background so the next CAE mesh
  # is not blocked. Submit slots fill as soon as each INP appears (max parallel).
  for cid in "${READY[@]}"; do
    reap_export_bg
    fill_submit_slots
    if inp_ready "$cid" && [[ "$FORCE_REMESH" != "1" ]]; then
      continue
    fi
    if [[ -n "${SKIPPED[$cid]:-}" ]]; then
      continue
    fi
    if mesh_one "$cid"; then
      write_status >/dev/null || true
      reap_export_bg
      fill_submit_slots
      continue
    fi
    mark_skip "$cid" "CAE mesh ladder exhausted (0 elements / all tries failed)"
    write_status >/dev/null || true
  done
  log "=== waiting for background compression exports ==="
  wait_export_bg_all
fi

if [[ "$EXPORT_ONLY" == "1" ]]; then
  wait_export_bg_all
  write_status | tee -a "$LOG"
  log "=== export-only done ==="
  exit 0
fi

# ---- wait for all submits (skip skipped / never-exported) ----
log "=== wait/submit phase max_parallel=$MAX_PARALLEL ==="
while true; do
  fill_submit_slots
  local_pending=0
  for cid in "${READY[@]}"; do
    [[ -n "${SKIPPED[$cid]:-}" ]] && continue
    if job_completed "$cid"; then
      continue
    fi
    # Failed solves are reaped in fill_submit_slots; treat as non-pending.
    if [[ "$ALLOW_SOLVE_RETRY" != "1" ]] && job_failed "$cid"; then
      continue
    fi
    if inp_ready "$cid" || job_running "$cid"; then
      local_pending=1
      if job_running "$cid"; then
        sta="$(sta_path "$cid")"
        prog=""
        if [[ -f "$sta" ]]; then
          prog="$(tail -1 "$sta" 2>/dev/null | tr -s ' ' | cut -c1-90 || true)"
        fi
        log "RUNNING $cid ${prog:+| $prog}"
      fi
    fi
  done
  write_status >/dev/null || true
  log "tick running=$(count_running)/$MAX_PARALLEL pending_work=$local_pending skipped=${#SKIPPED[@]}"
  if [[ "$local_pending" -eq 0 ]]; then
    break
  fi
  sleep "$POLL_SEC"
done

write_status | tee -a "$LOG"
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  log "=== finished with skips: ${!SKIPPED[*]} ==="
else
  log "=== ALL queued cases completed (no skips) ==="
fi
