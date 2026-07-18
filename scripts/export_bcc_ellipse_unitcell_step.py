"""
Export a single-cell BCC solid STEP with **elliptical** struts.

Ellipse short axis is aligned to the compression direction (default +Z) by choosing
the profile orientation so that the *minor axis* follows the projection of +Z onto
each strut's cross-section plane.

Usage:
  py -3 scripts/export_bcc_ellipse_unitcell_step.py
  py -3 scripts/export_bcc_ellipse_unitcell_step.py --d-major 2.0 --d-minor 1.2
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.beam_utils import dedupe_beams
from src.export.export_sw import export_lattice_step_occ
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs


def main() -> int:
    ensure_output_dirs()

    p = argparse.ArgumentParser(description="BCC unit cell STEP with elliptical struts")
    p.add_argument("--L", type=float, default=20.0, help="Cell size [mm]")
    p.add_argument("--Q", type=float, default=0.0, help="Period factor Q (0=BCC)")
    p.add_argument("--Af", type=float, default=0.0, help="Amplitude A_f [mm] (0 for straight BCC)")
    p.add_argument("--d-major", type=float, default=2.0, help="Ellipse major diameter [mm]")
    p.add_argument("--d-minor", type=float, default=1.2, help="Ellipse minor diameter [mm] (compression axis)")
    p.add_argument(
        "--compression-axis",
        choices=("x", "y", "z"),
        default="z",
        help="Compression direction (minor axis aligns to this)",
    )
    p.add_argument("--no-fuse", action="store_true", help="Write multi-body STEP (fast)")
    args = p.parse_args()

    L = float(args.L)
    d_major = float(args.d_major)
    d_minor = float(args.d_minor)
    if d_major <= 0 or d_minor <= 0:
        raise ValueError("d-major and d-minor must be positive")

    axis = str(args.compression_axis).lower()
    comp = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[axis]

    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=d_major,  # generator uses this for radius bookkeeping; geometry here is overridden in STEP
        amplitude=float(args.Af),
        period_factor=float(args.Q),
        n_segments=12,
    )
    gen.build_lattice(1, 1, 1)
    nodes, beams, polylines = gen.get_data()
    beams, _ = dedupe_beams(beams)

    # Use major axis as the reference radius; minor is a ratio.
    ellipse_minor_ratio = (0.5 * d_minor) / max(0.5 * d_major, 1e-12)
    slug = f"hu_bai_bcc_L{int(L)}_1x1x1_ellipse_d{d_major:g}x{d_minor:g}_{axis}"

    out_dir = os.path.join(str(CAD_ROOT), "tmp")
    os.makedirs(out_dir, exist_ok=True)
    out_step = os.path.join(out_dir, f"{slug}.step")

    report = export_lattice_step_occ(
        nodes,
        beams,
        out_step,
        polylines=polylines,
        junction_spheres=False,
        fuse=not bool(args.no_fuse),
        polyline_sweep="pipe",
        cell_size=L,
        # New knobs:
        solid_profile="ellipse",
        ellipse_minor_ratio=float(ellipse_minor_ratio),
        compression_axis=comp,
    )

    print()
    print("BCC elliptical unit-cell STEP written:")
    print(f"  STEP: {out_step}")
    print(f"  Profile: ellipse d_major={d_major:g} mm, d_minor={d_minor:g} mm (minor along +{axis.upper()})")
    print(f"  Fused: {report.get('fused')} (volumes after fuse: {report.get('fused_volume_count')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

