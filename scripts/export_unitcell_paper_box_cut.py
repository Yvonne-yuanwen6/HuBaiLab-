"""
Export paper-style unit-cell STEPs: pipe sweep + virtual L³ hexahedron cut.

  py -3 scripts/export_unitcell_paper_box_cut.py
  py -3 scripts/export_unitcell_paper_box_cut.py --Q 0 1.0 1.5

Strut ends on the RVE boundary are planar cut faces (no junction spheres).
Uses the same pipe-first OCC sweep as export_unitcell_seed_check.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.unitcell_box_cut import export_unitcell_step_paper_box_cut
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator, is_q1_period
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Export paper-style unit-cell STEPs (virtual hexahedron cut)"
    )
    p.add_argument("--Q", type=float, nargs="*", default=[0.0, 0.5, 1.0, 1.5])
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0, help="Unit cell edge length [mm]")
    p.add_argument("--rod-d", type=float, default=2.0, help="Rod diameter [mm]")
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument(
        "--both-end-extension",
        action="store_true",
        help="Q=1: extend pipes at centre and corner before octant cut + fuse",
    )
    p.add_argument("--centre-extension-mm", type=float, default=None)
    p.add_argument("--corner-extension-mm", type=float, default=None)
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    out_dir = args.out_dir or os.path.join(str(CAD_ROOT), "_unitcell_paper_box_cut")
    os.makedirs(out_dir, exist_ok=True)

    manifest: dict = {
        "out_dir": os.path.abspath(out_dir),
        "cell_size_mm": float(args.L),
        "cells": [],
    }

    for q in args.Q:
        gen = HuBaiLatticeGenerator(
            cell_size=float(args.L),
            rod_diameter=float(args.rod_d),
            amplitude=float(args.Af),
            period_factor=float(q),
            n_segments=max(3, int(args.n_segments)),
        )
        gen.build_unitcell()
        nodes, beams, polylines = gen.get_data(copy=True)
        slug = gen.variant_name.lower()
        if args.both_end_extension and is_q1_period(float(q)):
            out_step = os.path.join(out_dir, f"unitcell_{slug}_paper_box_both_ext.step")
        else:
            out_step = os.path.join(out_dir, f"unitcell_{slug}_paper_box.step")
        print(f"Q={q} ({gen.variant_name}) -> {out_step}", flush=True)
        try:
            report = export_unitcell_step_paper_box_cut(
                nodes,
                beams,
                out_step,
                polylines=polylines,
                cell_size_mm=float(args.L),
                n_segments_hint=max(3, int(args.n_segments)),
                period_factor=float(q),
                both_end_extension=args.both_end_extension,
                centre_extension_mm=args.centre_extension_mm,
                corner_extension_mm=args.corner_extension_mm,
            )
        except RuntimeError as exc:
            if not os.path.isfile(out_step):
                raise
            print(f"  [WARN] STEP written but validation failed: {exc}", flush=True)
            report = {"step_solidworks_safe": False, "error": str(exc)}

        entry = {
            "Q": float(q),
            "variant": gen.variant_name,
            "step": os.path.abspath(out_step),
            "size_bytes": os.path.getsize(out_step) if os.path.isfile(out_step) else 0,
            **{k: v for k, v in report.items() if k != "step_path"},
        }
        manifest["cells"].append(entry)
        mass_ratio = entry.get("mass_ratio_after_cut")
        mass_str = f"{mass_ratio:.3f}" if isinstance(mass_ratio, (int, float)) else "?"
        print(
            f"  OK: vol={entry.get('fused_volume_count')} "
            f"sw_safe={entry.get('step_solidworks_safe')} "
            f"mass_cut={mass_str} "
            f"bbox_ok={entry.get('bbox_within_rve')} "
            f"size={entry.get('size_bytes')}",
            flush=True,
        )
        if entry.get("q1_paper_orientation"):
            print(f"  Q=1 path formula: {entry['q1_paper_orientation']}", flush=True)

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nManifest: {manifest_path}", flush=True)
    print(
        "Open STEPs in SolidWorks: open ONE file only → expect 1 part window, "
        "1 fused solid, 8 struts, flat caps on cell faces, no junction spheres.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
