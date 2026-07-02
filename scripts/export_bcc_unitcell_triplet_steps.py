"""
Generate 3 BCC unit-cell STEP solids in one folder (no junction spheres):
1) circular strut
2) ellipse with minor axis aligned to compression axis
3) ellipse with major axis aligned to compression axis

Tries gmsh OCC fuse first; on failure falls back to OCP GlueShift fuse.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.beam_utils import dedupe_beams
from src.export.export_sw import export_lattice_step_occ
from src.export.ocp_bcc_unitcell_fuse import export_ocp_bcc_unitcell_step, load_bcc_unitcell_pipe_parts
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs


def _build_unitcell(L: float, d_major: float) -> tuple[list, list, list]:
    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=d_major,
        amplitude=0.0,
        period_factor=0.0,
        n_segments=12,
    )
    gen.build_lattice(1, 1, 1)
    nodes, beams, polylines = gen.get_data()
    beams, _ = dedupe_beams(beams)
    return nodes, beams, polylines


def _axis_vec(axis: str) -> tuple[float, float, float]:
    return {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[axis]


def _export_one(
    *,
    out_step: str,
    nodes: list,
    beams: list,
    polylines: list,
    L: float,
    d_major: float,
    rod_diameter: float,
    solid_profile: str,
    minor_ratio: float,
    comp: tuple[float, float, float],
    ellipse_align: str,
    prefer_ocp: bool,
    ellipse_sweep_mode: str = "frenet",
) -> str:
    align = ellipse_align if solid_profile == "ellipse" else "minor"
    parts = load_bcc_unitcell_pipe_parts(
        cell_size=L,
        rod_diameter=rod_diameter,
        solid_profile=solid_profile,
        ellipse_minor_ratio=minor_ratio,
        compression_axis=comp,
        ellipse_align_to_compression=align,
    )

    if not prefer_ocp:
        try:
            report = export_lattice_step_occ(
                nodes,
                beams,
                out_step,
                polylines=polylines,
                junction_spheres=False,
                fuse=True,
                polyline_sweep="pipe",
                cell_size=L,
                solid_profile=solid_profile,
                ellipse_minor_ratio=minor_ratio,
                compression_axis=comp,
                ellipse_align_to_compression=align,
            )
            fused = int(report.get("fused_volume_count") or 0)
            if fused == 1 and os.path.isfile(out_step):
                return "gmsh_occ_fuse"
        except Exception as exc:
            print(f"  [WARN] gmsh fuse failed ({exc}); trying OCP...", flush=True)

    export_ocp_bcc_unitcell_step(
        out_step,
        cell_size=L,
        rod_diameter=rod_diameter,
        solid_profile=solid_profile,
        ellipse_minor_ratio=minor_ratio,
        compression_axis=comp,
        ellipse_align_to_compression=align,
        parts=parts,
        ellipse_sweep_mode=ellipse_sweep_mode,
    )
    return "ocp_glue_fuse"


def main() -> int:
    ensure_output_dirs()
    p = argparse.ArgumentParser(description="Export BCC unitcell step triplet")
    p.add_argument("--L", type=float, default=20.0, help="Cell size [mm]")
    p.add_argument("--d-major", type=float, default=2.0, help="Major diameter [mm]")
    p.add_argument("--d-minor", type=float, default=1.2, help="Minor diameter [mm]")
    p.add_argument("--compression-axis", choices=("x", "y", "z"), default="z")
    p.add_argument(
        "--out-dir",
        type=str,
        default=os.path.join(str(CAD_ROOT), "triplet_unitcell_bcc"),
        help="Output folder for the 3 STEP files",
    )
    p.add_argument("--ocp-only", action="store_true", help="Skip gmsh, use OCP fuse directly")
    p.add_argument(
        "--equal-area",
        action="store_true",
        help="Circular strut diameter = sqrt(d_major*d_minor) to match ellipse area",
    )
    p.add_argument(
        "--target-area-pi",
        action="store_true",
        help="All struts area = pi mm^2 (circle d=2; ellipse scaled from d_major:d_minor ratio)",
    )
    p.add_argument(
        "--cad-suffix",
        default="",
        help="Extra tag in STEP basename, e.g. cf for CorrectedFrenet sweep",
    )
    p.add_argument(
        "--parallel-transport-sweep",
        action="store_true",
        help="Elliptic struts: multi-profile parallel-transport sweep (no junction sphere)",
    )
    args = p.parse_args()
    if args.equal_area and args.target_area_pi:
        raise ValueError("Use only one of --equal-area or --target-area-pi")

    L = float(args.L)
    d_major = float(args.d_major)
    d_minor = float(args.d_minor)
    if d_major <= 0 or d_minor <= 0:
        raise ValueError("d-major and d-minor must be positive")
    if d_minor > d_major:
        raise ValueError("d-minor should be <= d-major")

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    nodes, beams, polylines = _build_unitcell(L, d_major)
    axis = str(args.compression_axis).lower()
    comp = _axis_vec(axis)
    minor_ratio = (0.5 * d_minor) / max(0.5 * d_major, 1e-12)
    d_circle = math.sqrt(d_major * d_minor)
    d_ell_major = d_major
    d_ell_minor = d_minor
    if args.target_area_pi:
        target_a = math.pi
        d_circle = 2.0
        aspect = d_major / d_minor
        d_ell_minor = math.sqrt(4.0 * target_a / math.pi / aspect)
        d_ell_major = aspect * d_ell_minor
        minor_ratio = d_ell_minor / d_ell_major
        print(
            f"  target area pi mm^2: circle d={d_circle:g}; "
            f"ellipse {d_ell_major:.4f}x{d_ell_minor:.4f} mm",
            flush=True,
        )
    eq_tag = "_Api" if args.target_area_pi else ("_eqarea" if args.equal_area else "")
    if args.cad_suffix.strip():
        suf = args.cad_suffix.strip().replace(" ", "_")
        eq_tag = f"{eq_tag}_{suf}" if eq_tag else f"_{suf}"
    base = f"hu_bai_bcc_unitcell_L{int(L)}_d{d_major:g}x{d_minor:g}{eq_tag}_{axis}"
    if args.equal_area:
        print(
            f"  equal-area circle: d={d_circle:.4f} mm "
            f"(A=pi*{d_major:g}*{d_minor:g}/4 = pi*{d_circle:.4f}^2/4)",
            flush=True,
        )

    sweep_mode = "parallel_transport" if args.parallel_transport_sweep else "frenet"
    if args.parallel_transport_sweep:
        print("  ellipse sweep: parallel_transport (multi-profile, no junction sphere)", flush=True)

    cases = [
        ("circular", "circle", "minor", d_circle if args.target_area_pi else (d_circle if args.equal_area else d_major)),
        ("ellipse_minor_align", "ellipse", "minor", d_ell_major),
        ("ellipse_major_align", "ellipse", "major", d_ell_major),
    ]
    print("Exporting BCC unitcell triplet (no junction spheres)...", flush=True)
    routes: list[tuple[str, str, str]] = []
    for suffix, profile, align, rod_d in cases:
        out_step = os.path.join(out_dir, f"{base}_{suffix}.step")
        route = _export_one(
            out_step=out_step,
            nodes=nodes,
            beams=beams,
            polylines=polylines,
            L=L,
            d_major=d_major,
            rod_diameter=rod_d,
            solid_profile=profile,
            minor_ratio=minor_ratio,
            comp=comp,
            ellipse_align=align,
            prefer_ocp=bool(args.ocp_only),
            ellipse_sweep_mode=sweep_mode,
        )
        routes.append((out_step, suffix, route))
        print(f"  OK [{route}] {out_step}", flush=True)

    print("\nTriplet STEP exported:")
    for path, suffix, route in routes:
        print(f"  {suffix} ({route}): {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
