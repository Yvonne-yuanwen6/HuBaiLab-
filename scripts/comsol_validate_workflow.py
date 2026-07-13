#!/usr/bin/env python3
"""Validate HuBaiLab COMSOL pipeline against an official Application Library case.

Reproduces the eigenfrequency portion of COMSOL *Channel Beam* verification
(``Structural_Mechanics_Module/Verification_Examples/channel_beam``) using a
3D Solid Mechanics cantilever built via MPh — same build → batch/in-process
solve → eigen extract path as ``comsol_run_hu_bai.py``.

Usage:
  export PYTHONPATH=.
  python scripts/comsol_validate_workflow.py
  python scripts/comsol_validate_workflow.py --in-process --mesh-mm 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.validation.solid_cantilever import run_validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="COMSOL workflow validation (Channel Beam eigenfrequency reference)."
    )
    parser.add_argument("--comsol-bin", default="", help="COMSOL launcher path")
    parser.add_argument("--cores", type=int, default=2)
    parser.add_argument("--mesh-mm", type=float, default=5.0, help="Tet mesh hmax [mm]")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Solve via MPh in-process instead of comsol batch",
    )
    parser.add_argument(
        "--rtol",
        type=float,
        default=0.08,
        help="Max relative error for first bending mode (default 8%%)",
    )
    args = parser.parse_args(argv)

    report = run_validation(
        comsol_bin=args.comsol_bin or None,
        cores=args.cores,
        mesh_mm=args.mesh_mm,
        use_batch=not args.in_process,
        rtol=args.rtol,
    )

    print("\n=== COMSOL workflow validation ===", flush=True)
    print(json.dumps(report, indent=2), flush=True)
    f1 = report["first_mode"]
    print(
        f"\nFirst bending mode: computed={f1['computed_Hz']:.3f} Hz, "
        f"rect-beam theory={f1['analytical_rect_beam_Hz']:.3f} Hz, "
        f"official Channel Beam={f1['official_channel_beam_Hz']:.3f} Hz, "
        f"rel_error vs official={100.0 * (f1['rel_error_vs_official'] or 0):.2f}%",
        flush=True,
    )
    if report["pass"]:
        print("PASS — pipeline matches Channel Beam reference within tolerance.", flush=True)
        return 0
    print("FAIL — first mode outside tolerance; check COMSOL/MPh install.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
