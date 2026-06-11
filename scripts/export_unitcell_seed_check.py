"""
Export fused unit-cell STEP files for visual sweep QA in SolidWorks.

  py -3 scripts/export_unitcell_seed_check.py
  py -3 scripts/export_unitcell_seed_check.py --Q 1.5

Do not pass cell_size to export_lattice_step_occ here — see README
「单胞融合 STEP（SolidWorks QA，阵列前必做）」for why fuse-all drops struts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import export_lattice_step_occ
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def main() -> int:
    p = argparse.ArgumentParser(description="Export fused unit-cell STEPs for sweep check")
    p.add_argument("--Q", type=float, nargs="*", default=[0.5, 1.0, 1.5])
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    out_dir = args.out_dir or os.path.join(str(CAD_ROOT), "_unitcell_check")
    os.makedirs(out_dir, exist_ok=True)

    manifest: dict = {"out_dir": os.path.abspath(out_dir), "cells": []}

    for q in args.Q:
        gen = HuBaiLatticeGenerator(
            cell_size=20.0,
            rod_diameter=2.0,
            amplitude=float(args.Af),
            period_factor=float(q),
            n_segments=max(3, int(args.n_segments)),
        )
        gen.build_unitcell()
        nodes, beams, polylines = gen.get_data(copy=True)
        slug = gen.variant_name.lower()
        out_step = os.path.join(out_dir, f"unitcell_{slug}_fused.step")
        print(f"Q={q} ({gen.variant_name}) -> {out_step}", flush=True)
        try:
            # Do not pass cell_size here: that triggers array-safe fuse-all fallback
            # which drops ~2 struts in SolidWorks (pipe-first per-strut keeps all 8).
            report = export_lattice_step_occ(
                nodes,
                beams,
                out_step,
                polylines=polylines,
                junction_spheres=True,
                fuse=True,
            )
            sw_safe = report.get("step_solidworks_safe")
            fused_vol = report.get("fused_volume_count")
        except RuntimeError as exc:
            if not os.path.isfile(out_step):
                raise
            print(f"  [WARN] STEP written but validation failed: {exc}", flush=True)
            sw_safe = False
            fused_vol = None

        entry = {
            "Q": float(q),
            "variant": gen.variant_name,
            "step": os.path.abspath(out_step),
            "size_bytes": os.path.getsize(out_step),
            "fused_volume_count": fused_vol,
            "step_solidworks_safe": sw_safe,
            "fuse_strategy": "pipe-first per-strut + junction spheres (no array fuse-all)",
            "sweep": "pipe + CorrectedFrenet + spline wire + parallel-transport profile",
        }
        manifest["cells"].append(entry)
        print(
            f"  OK: vol={entry['fused_volume_count']} "
            f"sw_safe={entry['step_solidworks_safe']} "
            f"size={entry['size_bytes']}",
            flush=True,
        )

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nManifest: {manifest_path}", flush=True)
    print("Open the STEP files in SolidWorks and check rod radius + junction spheres.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
