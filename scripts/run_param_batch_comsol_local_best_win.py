#!/usr/bin/env python3
"""Serial local-best COMSOL batch for remaining param_batch cases (Windows).

Strategy (本机尽量靠谱):
  Pass A — solid_order=2, lattice_hauto=6, fixture_hauto=6, np=1, Direct,
            freq 10–500 / step 20, plate=clamp, CLIP_TOP=0
  Pass B — retry failures with solid_order=1, lattice_hauto=6 (proven local path)

Slug: fig28_p1_300g_local (does not overwrite ref fig28_p1_300g).

Env overrides: BATCH_COMSOL_ONLY, BATCH_COMSOL_FORCE, CONV-style knobs via BATCH_*.
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
LOG = ROOT / "output" / "logs" / "param_batch_comsol_local_best.log"

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


def csv_ok(cid: str, slug: str = SLUG) -> bool:
    p = BATCH / cid / slug / f"{slug}_transmissibility.csv"
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


def run_pass(
    cases: list[str],
    *,
    order: int,
    hauto: int,
    fixture_hauto: int,
    label: str,
) -> list[str]:
    """Run queue for given cases; return list still missing CSV."""
    if not cases:
        return []
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT),
            "BATCH_COMSOL_ONLY": " ".join(cases),
            "BATCH_COMSOL_RUN_SLUG": SLUG,
            "BATCH_COMSOL_NP": env.get("BATCH_COMSOL_NP", "1"),
            "BATCH_COMSOL_SOLID_ORDER": str(order),
            "BATCH_COMSOL_LATTICE_HAUTO": str(hauto),
            "BATCH_COMSOL_FIXTURE_HAUTO": str(fixture_hauto),
            "BATCH_COMSOL_FREQ_LINEAR_SOLVER": "direct",
            "BATCH_COMSOL_FORCE": env.get("BATCH_COMSOL_FORCE", "1"),
            "BATCH_COMSOL_FREQ_MIN": env.get("BATCH_COMSOL_FREQ_MIN", "10"),
            "BATCH_COMSOL_FREQ_MAX": env.get("BATCH_COMSOL_FREQ_MAX", "500"),
            "BATCH_COMSOL_FREQ_STEP": env.get("BATCH_COMSOL_FREQ_STEP", "20"),
            "HU_BAI_COMSOL_CLIP_TOP": "0",
            "HU_BAI_COMSOL_PLATE_Z": "clamp",
        }
    )
    log(
        f"=== PASS {label}: order={order} hauto={hauto}/{fixture_hauto} "
        f"slug={SLUG} cases={len(cases)} ==="
    )
    log("queue: " + " ".join(cases))
    proc = subprocess.run(
        [PY, "-u", "scripts/run_param_batch_comsol_queue_win.py"],
        cwd=str(ROOT),
        env=env,
        check=False,
    )
    log(f"PASS {label} queue exit={proc.returncode}")
    missing = [c for c in cases if not csv_ok(c)]
    ok = [c for c in cases if csv_ok(c)]
    log(f"PASS {label} ok={len(ok)} missing={len(missing)}")
    if ok:
        log("  ok: " + " ".join(ok))
    if missing:
        log("  missing: " + " ".join(missing))
    return missing


def main() -> int:
    raw = os.environ.get("BATCH_COMSOL_ONLY", "").strip()
    cases = [x for x in raw.split() if x] if raw else list(DEFAULT_REMAINING)
    # Skip already-good
    todo = [c for c in cases if not csv_ok(c)]
    skip = [c for c in cases if csv_ok(c)]
    log(f"=== local-best batch start slug={SLUG} requested={len(cases)} ===")
    if skip:
        log("already have CSV, skip: " + " ".join(skip))
    if not todo:
        log("nothing to do")
        return 0

    # Pass A: quadratic coarse (尽量靠谱)
    missing = run_pass(
        todo, order=2, hauto=6, fixture_hauto=6, label="A_quad_h6"
    )
    # Pass B: linear proven fallback
    if missing:
        missing = run_pass(
            missing, order=1, hauto=6, fixture_hauto=5, label="B_lin_h6"
        )

    final_ok = [c for c in cases if csv_ok(c)]
    final_miss = [c for c in cases if not csv_ok(c)]
    log(
        f"=== local-best finished ok={len(final_ok)}/{len(cases)} "
        f"missing={len(final_miss)} ==="
    )
    if final_miss:
        log("still missing: " + " ".join(final_miss))
    return 0 if not final_miss else 1


if __name__ == "__main__":
    raise SystemExit(main())
