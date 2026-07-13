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
import math
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
    p.add_argument(
        "--solid-profile",
        choices=("circle", "ellipse"),
        default="circle",
        help="Strut cross-section profile",
    )
    p.add_argument(
        "--ellipse-minor-ratio",
        type=float,
        default=0.6,
        help="Ellipse minor/major radius ratio (ellipse profile only)",
    )
    p.add_argument(
        "--ellipse-align",
        choices=("minor", "major"),
        default="minor",
        help="Ellipse axis aligned to compression direction",
    )
    p.add_argument(
        "--compression-axis",
        choices=("x", "y", "z"),
        default="z",
        help="Compression axis for ellipse alignment",
    )
    p.add_argument(
        "--target-area-pi",
        action="store_true",
        help="Match circle d=2 mm area (pi mm^2); scale ellipse from nominal 2:1.2 ratio",
    )
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

    rod_d = float(args.rod_d)
    ellipse_minor_ratio = float(args.ellipse_minor_ratio)
    if args.target_area_pi:
        if str(args.solid_profile).lower() != "ellipse":
            raise ValueError("--target-area-pi requires --solid-profile ellipse")
        aspect = 2.0 / 1.2
        d_ell_minor = math.sqrt(4.0 * math.pi / math.pi / aspect)
        d_ell_major = aspect * d_ell_minor
        rod_d = d_ell_major
        ellipse_minor_ratio = d_ell_minor / d_ell_major
        print(
            f"  target area pi mm^2: ellipse d_major={d_ell_major:.4f} "
            f"d_minor={d_ell_minor:.4f} mm (circle reference d=2.0 mm)",
            flush=True,
        )

    comp_axis = {
        "x": (1.0, 0.0, 0.0),
        "y": (0.0, 1.0, 0.0),
        "z": (0.0, 0.0, 1.0),
    }[str(args.compression_axis).lower()]
    profile_tag = ""
    if str(args.solid_profile).lower() == "ellipse":
        profile_tag = "_ellipse_ellmin" if args.ellipse_align == "minor" else "_ellipse_ellmaj"
        if args.target_area_pi:
            profile_tag += "_eqarea"

    manifest: dict = {
        "out_dir": os.path.abspath(out_dir),
        "cell_size_mm": float(args.L),
        "solid_profile": str(args.solid_profile),
        "ellipse_minor_ratio": ellipse_minor_ratio,
        "ellipse_align": str(args.ellipse_align),
        "compression_axis": str(args.compression_axis),
        "target_area_pi": bool(args.target_area_pi),
        "cells": [],
    }

    for q in args.Q:
        gen = HuBaiLatticeGenerator(
            cell_size=float(args.L),
            rod_diameter=rod_d,
            amplitude=float(args.Af),
            period_factor=float(q),
            n_segments=max(3, int(args.n_segments)),
        )
        gen.build_unitcell()
        nodes, beams, polylines = gen.get_data(copy=True)
        slug = gen.variant_name.lower()
        if args.both_end_extension and is_q1_period(float(q)):
            out_step = os.path.join(
                out_dir,
                f"unitcell_{slug}_paper_box_both_ext{profile_tag}.step",
            )
        else:
            out_step = os.path.join(out_dir, f"unitcell_{slug}_paper_box{profile_tag}.step")
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
                solid_profile=str(args.solid_profile),
                ellipse_minor_ratio=ellipse_minor_ratio,
                compression_axis=comp_axis,
                ellipse_align_to_compression=str(args.ellipse_align),
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
