#!/usr/bin/env python3
"""Windows local param-batch COMSOL queue (freq-only, serial).

Mirrors scripts/linux/run_param_batch_comsol_queue.sh without SSH/server.

Env:
  COMSOL_BIN                 default: D:\\Apps\\COMSOL\\COMSOL63\\...\\comsol.exe
  BATCH_COMSOL_NP            default: 2
  BATCH_COMSOL_ONLY          space-separated case ids
  BATCH_COMSOL_FORCE         1 to rebuild
  BATCH_COMSOL_FREQ_MIN/MAX/STEP
  BATCH_COMSOL_RUN_SLUG      default: fig28_p1_300g
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)
os.environ.setdefault("HU_BAI_PROJECT_ROOT", str(ROOT))
os.environ.setdefault("PYTHONUNBUFFERED", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
# Clip lattice tips that poke through the §2.4.3 plate plane — otherwise fin
# often omits identity pair ap2 on curved SFBLS STEP (Windows batch saw this).
os.environ.setdefault("HU_BAI_COMSOL_CLIP_TOP", "1")
# Avoid Windows GBK console crashes on thesis unicode in prints.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

DEFAULT_COMSOL = Path(r"D:\Apps\COMSOL\COMSOL63\Multiphysics\bin\win64\comsol.exe")
BATCH_NAME = "批量构型"
CAD_BATCH = ROOT / "output" / "cad" / BATCH_NAME
COMSOL_BATCH = ROOT / "output" / "comsol_jobs" / BATCH_NAME
RUN_SLUG = os.environ.get("BATCH_COMSOL_RUN_SLUG", "fig28_p1_300g")
NP = int(os.environ.get("BATCH_COMSOL_NP", "2"))
FORCE = os.environ.get("BATCH_COMSOL_FORCE", "0") == "1"
ONLY = {x for x in os.environ.get("BATCH_COMSOL_ONLY", "").split() if x}
FREQ_MIN = float(os.environ.get("BATCH_COMSOL_FREQ_MIN", "10"))
FREQ_MAX = float(os.environ.get("BATCH_COMSOL_FREQ_MAX", "500"))
FREQ_STEP = float(os.environ.get("BATCH_COMSOL_FREQ_STEP", "10"))
LATTICE_HAUTO = int(os.environ.get("BATCH_COMSOL_LATTICE_HAUTO", "4"))
FIXTURE_HAUTO = int(os.environ.get("BATCH_COMSOL_FIXTURE_HAUTO", "5"))
SOLID_ORDER = int(os.environ.get("BATCH_COMSOL_SOLID_ORDER", "2"))
FREQ_LINEAR_SOLVER = os.environ.get("BATCH_COMSOL_FREQ_LINEAR_SOLVER", "direct").strip().lower()
PY = sys.executable
COMSOL_BIN = os.environ.get("COMSOL_BIN", "").strip() or str(DEFAULT_COMSOL)

LOG = ROOT / "output" / "logs" / "param_batch_comsol_queue_win.log"
INDEX_OUT = COMSOL_BATCH / "_batch_comsol_index.json"
STATUS_OUT = COMSOL_BATCH / "_batch_comsol_status.json"
FIXTURE = ROOT / "output" / "comsol_jobs" / "comsol_fixture_444" / "comsol_fixture_444.mph"

# Remaining cases without good CSV on this machine (override with BATCH_COMSOL_ONLY).
DEFAULT_REMAINING = [
    "af2q0_deq2_k1p5",
    "af2q0p5_deq2_k1p5",
    "af2q0p5_deq2_k2",
    "af2q1_deq2_k1",
    "af2q1_deq2_k1p5",
    "af2q1_deq2_k2",
    "af2q1_deq2p5_k1",
    "af2q1p5_deq2_k1p5",
    "af2q1p5_deq2_k2",
    "af3q1_deq2_k1",
]


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def find_cad_batch() -> Path:
    if CAD_BATCH.is_dir() and (CAD_BATCH / "_batch_index.json").exists():
        return CAD_BATCH
    cad_root = ROOT / "output" / "cad"
    for d in cad_root.iterdir():
        if d.is_dir() and (d / "af2q0_deq2_k1").is_dir():
            return d
    raise SystemExit(f"CAD batch not found under {cad_root}")


def qc_ok(path: Path) -> tuple[bool, float | None]:
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
        or nested.get("single_solid_ok")
    )
    vr = d.get("volume_ratio") or nested.get("volume_ratio")
    return ok, vr


def parse_params(cid: str, qc: dict) -> dict:
    meta = {
        "Af": qc.get("Af"),
        "Q": qc.get("Q"),
        "deq_mm": qc.get("deq_mm"),
        "k": qc.get("k"),
        "phase": qc.get("phase"),
    }
    if meta["Af"] is None:
        m = re.match(
            r"af(?P<Af>\d+(?:p\d+)?)q(?P<Q>\d+(?:p\d+)?)_deq(?P<deq>\d+(?:p\d+)?)_k(?P<k>\d+(?:p\d+)?)",
            cid,
        )
        if not m:
            raise ValueError(f"cannot parse params from {cid}")

        def num(s: str) -> float:
            return float(s.replace("p", "."))

        meta["Af"] = num(m.group("Af"))
        meta["Q"] = num(m.group("Q"))
        meta["deq_mm"] = num(m.group("deq"))
        meta["k"] = num(m.group("k"))
    return meta


def build_ready(cad: Path) -> list[dict]:
    idx_path = cad / "_batch_index.json"
    if idx_path.is_file():
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        order = list(idx.get("generation_order") or [])
        cases_meta = idx.get("cases") or {}
    else:
        order = sorted(x.name for x in cad.iterdir() if x.is_dir() and x.name.startswith("af"))
        cases_meta = {}

    only = ONLY or set(DEFAULT_REMAINING)
    ready = []
    for cid in order:
        if cid not in only:
            continue
        meta = dict(cases_meta.get(cid) or {})
        qc_path = cad / cid / f"{cid}_qc.json"
        ok, vr = qc_ok(qc_path)
        if not ok:
            log(f"SKIP qc-not-ok {cid}")
            continue
        step = cad / cid / f"{cid}_444.step"
        if not step.is_file() or step.stat().st_size < 1_000_000:
            log(f"SKIP missing/small STEP {cid}")
            continue
        qc = json.loads(qc_path.read_text(encoding="utf-8")) if qc_path.is_file() else {}
        parsed = parse_params(cid, {**meta, **qc})
        ready.append(
            {
                "case_id": cid,
                "Af": float(parsed["Af"]),
                "Q": float(parsed["Q"]),
                "deq_mm": float(parsed["deq_mm"]),
                "k": float(parsed.get("k") or 1.0),
                "phase": parsed.get("phase"),
                "cad_step": str(step.resolve()),
                "volume_ratio": vr,
                "run_slug": RUN_SLUG,
                "job_rel": f"output/comsol_jobs/{BATCH_NAME}/{cid}/{RUN_SLUG}",
            }
        )
    return ready


def write_index(ready: list[dict]) -> None:
    COMSOL_BATCH.mkdir(parents=True, exist_ok=True)
    out = {
        "name": f"{BATCH_NAME}_comsol_isolation",
        "thesis": "Hu & Bai 2024 §2.4.3 / Fig.2.8 — COMSOL frequency transmissibility (eigen OFF)",
        "cad_root": f"output/cad/{BATCH_NAME}",
        "comsol_root": f"output/comsol_jobs/{BATCH_NAME}",
        "run_slug": RUN_SLUG,
        "host": "windows_local",
        "defaults": {
            "cells": [4, 4, 4],
            "cell_size_mm": 20.0,
            "include_fig28": True,
            "interface_coupling": "p1_continuity",
            "top_payload_kg": 0.3,
            "excitation_axis": "z",
            "base_acceleration_m_s2": 0.98,
            "run_eigen": False,
            "studies": ["freq"],
            "physics_controlled_mesh": True,
            "freq_hz": [FREQ_MIN, FREQ_MAX, FREQ_STEP],
            "np": NP,
        },
        "queue": [r["case_id"] for r in ready],
        "cases": {r["case_id"]: r for r in ready},
    }
    INDEX_OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in ready:
        (COMSOL_BATCH / r["case_id"] / RUN_SLUG).mkdir(parents=True, exist_ok=True)


def job_dir(cid: str) -> Path:
    return COMSOL_BATCH / cid / RUN_SLUG


def case_done(cid: str) -> bool:
    jd = job_dir(cid)
    csvp = jd / f"{RUN_SLUG}_transmissibility.csv"
    solved = jd / f"{RUN_SLUG}_solved.mph"
    if not solved.is_file() or not csvp.is_file():
        return False
    txt = csvp.read_text(encoding="utf-8", errors="ignore")
    return "FORMAT SAMPLE" not in txt and csvp.stat().st_size > 200


def clear_artifacts(jd: Path) -> None:
    for name in [
        f"{RUN_SLUG}.mph",
        f"{RUN_SLUG}_solved.mph",
        f"{RUN_SLUG}_solved.mph.status",
        f"{RUN_SLUG}_solved.mph.recovery",
        f"{RUN_SLUG}_transmissibility.csv",
        f"{RUN_SLUG}_batch.log",
        f"{RUN_SLUG}_eigenfrequencies.csv",
        "case_manifest.json",
        "_error.txt",
    ]:
        p = jd / name
        if p.exists():
            p.unlink()


def write_status(current: str = "", phase: str = "") -> None:
    if not INDEX_OUT.is_file():
        return
    idx = json.loads(INDEX_OUT.read_text(encoding="utf-8"))
    rows = []
    for cid in idx["queue"]:
        jd = job_dir(cid)
        csvp = jd / f"{RUN_SLUG}_transmissibility.csv"
        solved = jd / f"{RUN_SLUG}_solved.mph"
        mph = jd / f"{RUN_SLUG}.mph"
        err = jd / "_error.txt"
        status = "pending"
        progress = None
        if case_done(cid):
            status = "completed"
        elif err.is_file():
            status = "error"
            try:
                progress = err.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[-1][:140]
            except Exception:
                progress = None
        elif solved.is_file() and solved.stat().st_size > 1_000_000:
            status = "solved_extracting"
        elif mph.is_file() and mph.stat().st_size > 1_000_000:
            status = "built"
        if current and cid == current and status not in ("completed", "error"):
            status = phase or "running"
        rows.append(
            {
                "case_id": cid,
                "status": status,
                "progress": progress,
                "job_dir": str(jd.as_posix()),
            }
        )
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "phase": "freq_only_queue_win",
        "run_slug": RUN_SLUG,
        "run_eigen": False,
        "physics_controlled_mesh": True,
        "np": NP,
        "current": current or None,
        "cases": rows,
    }
    STATUS_OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_cmd(args: list[str], log_path: Path, env: dict | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"\n=== CMD {' '.join(args)} ===\n")
        f.flush()
        proc = subprocess.run(
            args,
            cwd=str(ROOT),
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return int(proc.returncode)


def ensure_fixture() -> None:
    if FIXTURE.is_file() and FIXTURE.stat().st_size > 1_000_000:
        log(f"fixture ok: {FIXTURE}")
        return
    log("building fixture template…")
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["COMSOL_BIN"] = COMSOL_BIN
    env["PYTHONPATH"] = str(ROOT)
    rc = run_cmd(
        [
            PY,
            "-u",
            "scripts/comsol_run_hu_bai.py",
            "--comsol-bin",
            COMSOL_BIN,
            "--build-fixture-template",
            "--cells",
            "4",
            "--nz",
            "4",
            "--np",
            str(NP),
        ],
        ROOT / "output" / "logs" / "comsol_fixture_444_build_win.log",
        env=env,
    )
    if rc != 0 or not FIXTURE.is_file():
        raise SystemExit(f"fixture build failed rc={rc}")
    log(f"fixture saved: {FIXTURE} ({FIXTURE.stat().st_size/1e6:.1f} MB)")


def common_args(cid: str, Af: float, Q: float, deq: float, cad: str) -> list[str]:
    return [
        PY,
        "-u",
        "scripts/comsol_run_hu_bai.py",
        "--comsol-bin",
        COMSOL_BIN,
        "--Q",
        str(Q),
        "--Af",
        str(Af),
        "--rod-diameter",
        str(deq),
        "--cells",
        "4",
        "--nz",
        "4",
        "--cad",
        cad,
        "--slug",
        RUN_SLUG,
        "--freq-only",
        "--physics-controlled-mesh",
        "--excitation-axis",
        "z",
        "--freq-min",
        str(FREQ_MIN),
        "--freq-max",
        str(FREQ_MAX),
        "--freq-step",
        str(FREQ_STEP),
        "--fixture-template",
        str(FIXTURE),
        "--np",
        str(NP),
        "--lattice-hauto",
        str(LATTICE_HAUTO),
        "--fixture-hauto",
        str(FIXTURE_HAUTO),
        "--solid-order",
        str(SOLID_ORDER),
        "--freq-linear-solver",
        FREQ_LINEAR_SOLVER if FREQ_LINEAR_SOLVER in ("direct", "iterative") else "direct",
    ]


def extract_one(cid: str) -> bool:
    jd = job_dir(cid)
    case_log = ROOT / "output" / "logs" / f"param_batch_comsol_{cid}.log"
    env = os.environ.copy()
    env["HU_BAI_COMSOL_JOBS_ROOT"] = str(COMSOL_BATCH / cid)
    env["COMSOL_BIN"] = COMSOL_BIN
    env["PYTHONPATH"] = str(ROOT)
    write_status(cid, "extracting")
    log(f"EXTRACT {cid}")
    rc = run_cmd(
        [PY, "-u", "scripts/comsol_extract_isolation.py", str(jd / f"{RUN_SLUG}_solved.mph")],
        case_log,
        env=env,
    )
    if rc != 0:
        log(f"WARN extract exit={rc} {cid}")
    csvp = jd / f"{RUN_SLUG}_transmissibility.csv"
    if csvp.is_file() and "FORMAT SAMPLE" not in csvp.read_text(encoding="utf-8", errors="ignore"):
        run_cmd([PY, "-u", "scripts/plot_comsol_vld.py", str(csvp)], case_log, env=env)
    if case_done(cid):
        log(f"DONE {cid}")
        err = jd / "_error.txt"
        if err.exists():
            err.unlink()
        write_status("", "")
        return True
    (jd / "_error.txt").write_text(
        f"incomplete after extract {datetime.now().isoformat()}\n", encoding="utf-8"
    )
    write_status(cid, "error")
    return False


def run_one(row: dict) -> bool:
    cid = row["case_id"]
    jd = job_dir(cid)
    jd.mkdir(parents=True, exist_ok=True)
    if case_done(cid) and not FORCE:
        log(f"SKIP done {cid}")
        return True

    env = os.environ.copy()
    env["HU_BAI_COMSOL_JOBS_ROOT"] = str(COMSOL_BATCH / cid)
    env["COMSOL_BIN"] = COMSOL_BIN
    env["PYTHONPATH"] = str(ROOT)

    mph = jd / f"{RUN_SLUG}.mph"
    case_log = ROOT / "output" / "logs" / f"param_batch_comsol_{cid}.log"
    args = common_args(cid, row["Af"], row["Q"], row["deq_mm"], row["cad_step"])

    if FORCE:
        clear_artifacts(jd)

    if not mph.is_file() or mph.stat().st_size < 1_000_000 or FORCE:
        log(f"BUILD {cid} Af={row['Af']} Q={row['Q']} deq={row['deq_mm']} np={NP}")
        write_status(cid, "building")
        rc = run_cmd(args + ["--build-only"], case_log, env=env)
        if rc != 0 or not mph.is_file():
            log(f"ERROR build failed {cid} exit={rc}")
            (jd / "_error.txt").write_text(f"build failed exit={rc}\n", encoding="utf-8")
            write_status(cid, "error")
            return False
    else:
        log(f"REUSE mph {cid}")

    solved = jd / f"{RUN_SLUG}_solved.mph"
    # Coarse/linear local-opt models can be <<50 MB; align with runner.py (~1 MB).
    min_solved = 1_000_000
    if not (solved.is_file() and solved.stat().st_size > min_solved) or FORCE:
        log(f"SOLVE {cid} (solve-only, np={NP})")
        write_status(cid, "solving")
        # Drop any previous solved for FORCE
        if FORCE and solved.exists():
            try:
                solved.unlink()
            except OSError:
                pass
        blog = jd / f"{RUN_SLUG}_batch.log"
        if FORCE and blog.exists():
            try:
                blog.unlink()
            except OSError:
                pass
        rc = run_cmd(args + ["--solve-only", str(mph)], case_log, env=env)
        solved_ok = solved.is_file() and solved.stat().st_size > min_solved
        blog_ok = blog.is_file() and blog.stat().st_size > 50
        if rc != 0 or not solved_ok:
            log(
                f"ERROR solve failed {cid} exit={rc} "
                f"solved={solved_ok} batchlog={blog_ok}"
            )
            (jd / "_error.txt").write_text(
                f"solve failed exit={rc} solved={solved_ok} batchlog={blog_ok}\n",
                encoding="utf-8",
            )
            write_status(cid, "error")
            return False
    else:
        log(f"REUSE solved {cid}")

    return extract_one(cid)


def main() -> int:
    if not Path(COMSOL_BIN).is_file():
        raise SystemExit(f"COMSOL_BIN missing: {COMSOL_BIN}")
    os.environ["COMSOL_BIN"] = COMSOL_BIN

    cad = find_cad_batch()
    # Ensure Unicode batch name path exists for scripts that hardcode 批量构型
    if cad.resolve() != CAD_BATCH.resolve():
        CAD_BATCH.parent.mkdir(parents=True, exist_ok=True)
        if not CAD_BATCH.exists():
            try:
                CAD_BATCH.symlink_to(cad, target_is_directory=True)
            except OSError:
                # Fallback: if index missing on CAD_BATCH, copy index only and rely on absolute cad_step
                pass

    ready = build_ready(cad)
    write_index(ready)
    if not ready:
        log("ABORT: no ready cases")
        return 1

    n_pts = int(round((FREQ_MAX - FREQ_MIN) / FREQ_STEP)) + 1
    log(
        f"=== Windows COMSOL queue np={NP} freq={FREQ_MIN}-{FREQ_MAX}/{FREQ_STEP} "
        f"({n_pts} pts/case) lattice_hauto={LATTICE_HAUTO} solid_order={SOLID_ORDER} "
        f"freq_solver={FREQ_LINEAR_SOLVER} slug={RUN_SLUG} cases={len(ready)} ==="
    )
    log("queue: " + " ".join(r["case_id"] for r in ready))
    log(f"COMSOL_BIN={COMSOL_BIN}")
    log(f"python={PY}")

    ensure_fixture()

    ok_n = err_n = 0
    for row in ready:
        try:
            if run_one(row):
                ok_n += 1
            else:
                err_n += 1
                log(f"CONTINUE after error {row['case_id']}")
        except Exception as exc:
            err_n += 1
            log(f"ERROR exception {row['case_id']}: {exc}")
            jd = job_dir(row["case_id"])
            jd.mkdir(parents=True, exist_ok=True)
            (jd / "_error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            write_status(row["case_id"], "error")

    write_status("", "")
    log(f"=== queue finished ok={ok_n} err={err_n} ===")
    return 0 if err_n == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
