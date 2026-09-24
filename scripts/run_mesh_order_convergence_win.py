#!/usr/bin/env python3
"""Mesh / element-order convergence study (Windows, single case, serial).

Ablation ladder for judging whether fig28_p1_300g_optlocal drifts from the
finer/quadratic reference because of discretization (not physics):

  slug                 order  lattice_hauto  role
  -------------------- ------ -------------- ----------------
  fig28_p1_300g_optlocal   1       6         already available (coarse linear)
  conv_o2_h6               2       6         order only
  conv_o1_h5               1       5         mesh only (mild)
  conv_o1_h4               1       4         mesh only (ref density)
  conv_o2_h5               2       5         toward ref (optional, RAM-heavy)

Env:
  CONV_CASE_ID     default af2q0_deq2_k1
  CONV_VARIANTS    space-separated keys (default: o2_h6 o1_h5 o1_h4)
  CONV_FORCE       1 rebuild
  CONV_SKIP_OOM    1 skip remaining after a solve OOM/failure (default 1)
  BATCH_COMSOL_* / HU_BAI_COMSOL_* forwarded to the queue

Writes:
  output/comsol_jobs/param_batch/_convergence/{case}/manifest.json
"""
from __future__ import annotations

import json
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

BATCH = ROOT / "output" / "comsol_jobs" / "param_batch"
PY = str(ROOT / ".venv_comsol" / "Scripts" / "python.exe")
if not Path(PY).is_file():
    PY = sys.executable

CASE_ID = os.environ.get("CONV_CASE_ID", "af2q0_deq2_k1").strip()
FORCE = os.environ.get("CONV_FORCE", "1") == "1"
SKIP_AFTER_FAIL = os.environ.get("CONV_SKIP_OOM", "1") == "1"

# key -> (slug, solid_order, lattice_hauto, fixture_hauto, note)
VARIANTS: dict[str, dict] = {
    "o2_h6": {
        "slug": "conv_o2_h6",
        "solid_order": 2,
        "lattice_hauto": 6,
        "fixture_hauto": 5,
        "note": "quadratic @ opt mesh (order-only vs optlocal)",
    },
        "o1_h7": {
        "slug": "conv_o1_h7",
        "solid_order": 1,
        "lattice_hauto": 7,
        "fixture_hauto": 6,
        "note": "linear @ Coarser (reverse mesh control)",
    },
"o1_h5": {
        "slug": "conv_o1_h5",
        "solid_order": 1,
        "lattice_hauto": 5,
        "fixture_hauto": 5,
        "note": "linear @ Normal mesh (mesh-only mild)",
    },
    "o1_h4": {
        "slug": "conv_o1_h4",
        "solid_order": 1,
        "lattice_hauto": 4,
        "fixture_hauto": 5,
        "note": "linear @ Fine mesh (mesh-only to ref density)",
    },
        "o2_h8": {
        "slug": "conv_o2_h8",
        "solid_order": 2,
        "lattice_hauto": 8,
        "fixture_hauto": 6,
        "note": "quadratic @ Extra coarse (order-only, RAM-matched)",
    },
"o2_h5": {
        "slug": "conv_o2_h5",
        "solid_order": 2,
        "lattice_hauto": 5,
        "fixture_hauto": 5,
        "note": "quadratic @ Normal (toward ref; may OOM)",
    },
}

# Mesh-first then order: quadratic on ~650k elems may OOM on 16 GB.
DEFAULT_KEYS = ["o1_h5", "o1_h4", "o2_h6"]
KEYS = [k for k in os.environ.get("CONV_VARIANTS", "").split() if k] or DEFAULT_KEYS


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    out = ROOT / "output" / "logs" / "mesh_order_convergence_win.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def csv_ok(case: str, slug: str) -> bool:
    p = BATCH / case / slug / f"{slug}_transmissibility.csv"
    if not p.is_file() or p.stat().st_size < 200:
        return False
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if "FORMAT SAMPLE" in txt:
        return False
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return False
    n_data = len(lines) - 1 if "frequency" in lines[0].lower() else len(lines)
    # Short-band runs still need a usable curve (not 1–2 leftover points).
    return n_data >= 8


def run_variant(key: str) -> dict:
    spec = VARIANTS[key]
    slug = spec["slug"]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT),
            "BATCH_COMSOL_ONLY": CASE_ID,
            "BATCH_COMSOL_RUN_SLUG": slug,
            "BATCH_COMSOL_NP": env.get("BATCH_COMSOL_NP", "1"),
            "BATCH_COMSOL_LATTICE_HAUTO": str(spec["lattice_hauto"]),
            "BATCH_COMSOL_FIXTURE_HAUTO": str(spec["fixture_hauto"]),
            "BATCH_COMSOL_SOLID_ORDER": str(spec["solid_order"]),
            "BATCH_COMSOL_FREQ_LINEAR_SOLVER": env.get(
                "BATCH_COMSOL_FREQ_LINEAR_SOLVER", "iterative"
            ),
            "BATCH_COMSOL_FORCE": "1" if FORCE else "0",
            "BATCH_COMSOL_FREQ_MIN": env.get("BATCH_COMSOL_FREQ_MIN", "10"),
            "BATCH_COMSOL_FREQ_MAX": env.get("BATCH_COMSOL_FREQ_MAX", "500"),
            "BATCH_COMSOL_FREQ_STEP": env.get("BATCH_COMSOL_FREQ_STEP", "10"),
            # BCC Q=0: clamp plate; no clip needed
            "HU_BAI_COMSOL_CLIP_TOP": env.get("HU_BAI_COMSOL_CLIP_TOP", "0"),
            "HU_BAI_COMSOL_PLATE_Z": env.get("HU_BAI_COMSOL_PLATE_Z", "clamp"),
        }
    )
    if csv_ok(CASE_ID, slug) and not FORCE:
        log(f"SKIP {key} ({slug}) already has CSV")
        return {"key": key, **spec, "status": "skipped_done", "rc": 0}

    log(
        f"RUN {key} case={CASE_ID} slug={slug} "
        f"order={spec['solid_order']} hauto={spec['lattice_hauto']} — {spec['note']}"
    )
    proc = subprocess.run(
        [PY, "-u", "scripts/run_param_batch_comsol_queue_win.py"],
        cwd=str(ROOT),
        env=env,
        check=False,
    )
    ok = proc.returncode == 0 and csv_ok(CASE_ID, slug)
    status = "ok" if ok else "failed"
    log(f"END {key} status={status} rc={proc.returncode} csv={csv_ok(CASE_ID, slug)}")
    return {"key": key, **spec, "status": status, "rc": int(proc.returncode)}


def main() -> int:
    unknown = [k for k in KEYS if k not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown CONV_VARIANTS: {unknown}; choose from {list(VARIANTS)}")

    out_dir = BATCH / "_convergence" / CASE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    log(f"=== convergence study case={CASE_ID} variants={' '.join(KEYS)} ===")

    for key in KEYS:
        row = run_variant(key)
        results.append(row)
        if row["status"] == "failed" and SKIP_AFTER_FAIL:
            # Continue lighter variants? For OOM on heavy first, still try lighter.
            # Only abort remaining if this was a heavy quadratic fine mesh.
            if key in ("o2_h5", "o2_h4"):
                log(f"STOP after heavy failure {key}; lighter variants already scheduled earlier")
                break

    # Always try plot (partial OK)
    plot_rc = subprocess.run(
        [PY, "-u", "scripts/plot_convergence_overlay.py", "--case", CASE_ID],
        cwd=str(ROOT),
        check=False,
    )
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "case_id": CASE_ID,
        "variants_requested": KEYS,
        "results": results,
        "plot_rc": int(plot_rc.returncode),
        "baseline_slugs": {
            "ref_backup": "fig28_p1_300g",
            "optlocal": "fig28_p1_300g_optlocal",
        },
    }
    man_path = out_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"Wrote {man_path}")
    n_ok = sum(1 for r in results if r["status"] in ("ok", "skipped_done"))
    log(f"=== finished okish={n_ok}/{len(results)} ===")
    return 0 if n_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
