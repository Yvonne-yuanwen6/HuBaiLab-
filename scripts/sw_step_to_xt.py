"""
Convert a STEP solid to Parasolid X_T via SolidWorks (Windows + pywin32).

  py -3 scripts/sw_step_to_xt.py path/to/model.step
  py -3 scripts/sw_step_to_xt.py path/to/model.step -o path/to/model.x_t

SolidWorks should be installed. If COM import fails, open the STEP in SolidWorks
manually and use File → Save As → Parasolid (*.x_t).
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.sw_parasolid import analyze_step_for_solidworks, convert_step_to_xt, solidworks_com_available


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert STEP to Parasolid X_T (SolidWorks COM)")
    parser.add_argument("step", help="Input STEP file")
    parser.add_argument("-o", "--output", help="Output X_T path (default: same name .x_t)")
    parser.add_argument("--visible", action="store_true", help="Show SolidWorks window")
    args = parser.parse_args()

    step_path = os.path.abspath(args.step)
    if not os.path.isfile(step_path):
        print(f"[ERROR] Not found: {step_path}", file=sys.stderr)
        return 1

    if args.output:
        xt_path = os.path.abspath(args.output)
    else:
        root, _ = os.path.splitext(step_path)
        xt_path = root + ".x_t"

    if not solidworks_com_available():
        print(
            "[ERROR] SolidWorks is not running. Start SolidWorks first, then re-run.\n"
            "Or open the STEP manually: File → Save As → Parasolid (*.x_t).",
            file=sys.stderr,
        )
        return 1

    try:
        report = analyze_step_for_solidworks(step_path, fused_single=True)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(
        f"STEP OK: {report['product_count']} PRODUCT, "
        f"{report['solid_count']} MANIFOLD_SOLID_BREP",
        flush=True,
    )

    convert_step_to_xt(step_path, xt_path, visible=args.visible)
    print(f"X_T written: {xt_path} ({os.path.getsize(xt_path)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
