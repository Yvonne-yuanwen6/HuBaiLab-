#!/usr/bin/env python3
"""Retry the 5 failed fig28_p1_300g_local cases with cascading strategies.

Priority after clip/pairtol fixes:
  1) CLIP=1 + clamp + hauto 6/7  — flatten tips so Form Assembly gets auto ap2
  2) clamp + coarser hauto 7/8   — mesh fails that already had auto ap2
  3) raise + CLIP=0              — last resort for stubborn ap2
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

PY = str(ROOT / ".venv_comsol" / "Scripts" / "python.exe")
if not Path(PY).is_file():
    PY = sys.executable

BATCH = ROOT / "output" / "comsol_jobs" / "param_batch"
SLUG = os.environ.get("BATCH_COMSOL_RUN_SLUG", "fig28_p1_300g_local")
LOG = ROOT / "output" / "logs" / "param_batch_comsol_local_retry5.log"

# Mesh-fail cases first (clip not required); ap2/bonding cases after.
CASES = [
    "af2q1_deq2_k2",
    "af2q1p5_deq2_k2",
    "af2q1p5_deq2_k1p5",
    "af2q0p5_deq2_k1p5",
    "af2q0_deq2_k1p5",
]

# Per-case strategy lists: (label, order, hauto, fixture_hauto, plate_z, clip, pair_tol)
STRATEGIES: dict[str, list[tuple[str, int, int, int, str, str, str]]] = {
    # ap2 OK previously; fail was Java heap OOM on Box selection (Xmx2g).
    # Prefer clip-simplify + coarse mesh after heap bump.
    "af2q1_deq2_k2": [
        ("s1_clip_h7", 1, 7, 6, "clamp", "1", "1e-4"),
        ("s2_h8", 1, 8, 6, "clamp", "0", "1e-4"),
        ("s3_h7", 1, 7, 6, "clamp", "0", "1e-4"),
    ],
    "af2q1p5_deq2_k2": [
        ("s1_clip_h7", 1, 7, 6, "clamp", "1", "1e-4"),
        ("s2_h8", 1, 8, 6, "clamp", "0", "1e-4"),
        ("s3_clip_h8", 1, 8, 6, "clamp", "1", "1e-4"),
    ],
    "af2q1p5_deq2_k1p5": [
        ("s1_clip_h7", 1, 7, 6, "clamp", "1", "1e-4"),
        ("s2_h8", 1, 8, 6, "clamp", "0", "1e-4"),
        ("s3_clip_h8", 1, 8, 6, "clamp", "1", "2e-4"),
    ],
    # Missing ap2: Intersection clip + clamp
    "af2q0p5_deq2_k1p5": [
        ("s1_clip_h6", 1, 6, 6, "clamp", "1", "1e-4"),
        ("s2_clip_h7", 1, 7, 6, "clamp", "1", "2e-4"),
        ("s3_raise_h7", 1, 7, 6, "raise", "0", "1e-4"),
    ],
    # BCC shallow tip: Intersection clip first (Difference was a no-op)
    "af2q0_deq2_k1p5": [
        ("s1_clip_h6", 1, 6, 6, "clamp", "1", "2e-4"),
        ("s2_clip_h7", 1, 7, 6, "clamp", "1", "2e-4"),
        ("s3_pairtol_h7", 1, 7, 6, "clamp", "0", "5e-4"),
    ],
}


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def csv_ok(cid: str) -> bool:
    p = BATCH / cid / SLUG / f"{SLUG}_transmissibility.csv"
    if not p.is_file() or p.stat().st_size < 200:
        return False
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if "FORMAT SAMPLE" in txt:
        return False
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return False
    n = len(lines) - 1 if "frequency" in lines[0].lower() else len(lines)
    return n >= 8


def run_one(
    cid: str,
    *,
    label: str,
    order: int,
    hauto: int,
    fixture_hauto: int,
    plate_z: str,
    clip: str,
    pair_tol: str,
) -> bool:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT),
            "BATCH_COMSOL_ONLY": cid,
            "BATCH_COMSOL_RUN_SLUG": SLUG,
            "BATCH_COMSOL_NP": "1",
            "BATCH_COMSOL_SOLID_ORDER": str(order),
            "BATCH_COMSOL_LATTICE_HAUTO": str(hauto),
            "BATCH_COMSOL_FIXTURE_HAUTO": str(fixture_hauto),
            "BATCH_COMSOL_FREQ_LINEAR_SOLVER": "direct",
            "BATCH_COMSOL_FORCE": "1",
            "BATCH_COMSOL_FREQ_MIN": "10",
            "BATCH_COMSOL_FREQ_MAX": "500",
            "BATCH_COMSOL_FREQ_STEP": "20",
            "HU_BAI_COMSOL_CLIP_TOP": clip,
            "HU_BAI_COMSOL_PLATE_Z": plate_z,
            "HU_BAI_COMSOL_PAIR_TOL": pair_tol,
        }
    )
    log(
        f"TRY {cid} [{label}] order={order} hauto={hauto}/{fixture_hauto} "
        f"plate={plate_z} clip={clip} pairtol={pair_tol}"
    )
    proc = subprocess.run(
        [PY, "-u", "scripts/run_param_batch_comsol_queue_win.py"],
        cwd=str(ROOT),
        env=env,
        check=False,
    )
    ok = csv_ok(cid)
    log(f"END {cid} [{label}] exit={proc.returncode} csv_ok={ok}")
    return ok


def main() -> int:
    raw = os.environ.get("BATCH_COMSOL_ONLY", "").strip()
    cases = [x for x in raw.split() if x] if raw else list(CASES)
    log(f"=== retry5c start slug={SLUG} cases={len(cases)} ===")
    ok_all: list[str] = []
    miss_all: list[str] = []

    for cid in cases:
        if csv_ok(cid):
            log(f"SKIP {cid} (already has CSV)")
            ok_all.append(cid)
            continue
        strat = STRATEGIES.get(
            cid,
            [
                ("s1_clip_h7", 1, 7, 6, "clamp", "1", "1e-4"),
                ("s2_h8", 1, 8, 6, "clamp", "0", "1e-4"),
            ],
        )
        done = False
        for label, order, hauto, fh, plate, clip, ptol in strat:
            if run_one(
                cid,
                label=label,
                order=order,
                hauto=hauto,
                fixture_hauto=fh,
                plate_z=plate,
                clip=clip,
                pair_tol=ptol,
            ):
                ok_all.append(cid)
                done = True
                break
        if not done:
            log(f"FAIL {cid} after {len(strat)} strategies")
            miss_all.append(cid)

    log(f"=== retry5c finished ok={len(ok_all)} miss={len(miss_all)} ===")
    if ok_all:
        log("ok: " + " ".join(ok_all))
    if miss_all:
        log("still missing: " + " ".join(miss_all))
    return 0 if not miss_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
