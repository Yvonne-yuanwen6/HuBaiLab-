"""
Validate fused solid STEP files before opening in SolidWorks.

Detects orphan pipe/cylinder construction geometry (many PRODUCT entries,
few solids) that causes SolidWorks to open dozens of windows and crash.

  py -3 scripts/validate_step_solidworks.py path/to/model.step
  py -3 scripts/validate_step_solidworks.py output/cad/solidworks/hu_bai/*.step
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.sw_parasolid import analyze_step_for_solidworks, count_step_products


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate STEP for SolidWorks import")
    parser.add_argument("steps", nargs="+", help="STEP file(s) or glob patterns")
    parser.add_argument(
        "--multi-body",
        action="store_true",
        help="Allow multiple fused bodies (still rejects orphan PRODUCT spam)",
    )
    args = parser.parse_args()

    paths: list[str] = []
    for item in args.steps:
        expanded = glob.glob(item) if any(c in item for c in "*?[]") else [item]
        paths.extend(expanded)
    if not paths:
        print("[ERROR] No STEP files matched.", file=sys.stderr)
        return 1

    failed = 0
    for step_path in sorted(set(os.path.abspath(p) for p in paths)):
        if not os.path.isfile(step_path):
            print(f"[SKIP] Not found: {step_path}")
            failed += 1
            continue
        try:
            report = analyze_step_for_solidworks(
                step_path,
                fused_single=not args.multi_body,
            )
            print(
                f"[OK] {step_path}\n"
                f"     PRODUCT={report['product_count']}  "
                f"MANIFOLD_SOLID_BREP={report['solid_count']}  "
                f"ADVANCED_BREP={report['has_advanced_brep']}"
            )
        except RuntimeError as exc:
            n_prod = count_step_products(step_path)
            print(f"[FAIL] {step_path}\n       {exc}\n       (PRODUCT count={n_prod})")
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
