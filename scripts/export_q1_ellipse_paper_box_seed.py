"""
Export elliptic-strut unit-cell STEP (equal area vs circle d=2 mm).

For Q=1.0 / Q=1.5 (and other high-Q SFBLS), tries multiple routes:
- Q=1.0: gmsh octant (standard + both_end), OCP glue (centre_stub + both_end)
- Q=1.5: OCP glue only when --skip-gmsh (gmsh intra-fuse hangs on ellipse)

  py -3 scripts/export_q1_ellipse_paper_box_seed.py --Q 1.0
  py -3 scripts/export_q1_ellipse_paper_box_seed.py --Q 1.5
"""

from __future__ import annotations

import argparse
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import _collect_solid_primitives
from src.export.ocp_unitcell_fuse import FuseStrategy, export_q1_ocp_glue_unitcell
from src.export.paper_box_array_fuse import _count_seed_volumes
from src.export.unitcell_box_cut import export_unitcell_step_paper_box_cut
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def _eqarea_ellipse_params() -> tuple[float, float, float]:
    aspect = 2.0 / 1.2
    d_ell_minor = math.sqrt(4.0 * math.pi / math.pi / aspect)
    d_ell_major = aspect * d_ell_minor
    minor_ratio = d_ell_minor / d_ell_major
    return d_ell_major, d_ell_minor, minor_ratio


def _load_ellipse_parts(
    *,
    L: float,
    Af: float,
    period_factor: float,
    n_segments: int,
    ellipse_align: str,
) -> tuple[list, list, list, list]:
    d_major, _, minor_ratio = _eqarea_ellipse_params()
    comp = (0.0, 0.0, 1.0)
    gen = HuBaiLatticeGenerator(
        cell_size=float(L),
        rod_diameter=d_major,
        amplitude=float(Af),
        period_factor=float(period_factor),
        n_segments=max(3, int(n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
        solid_profile="ellipse",
        ellipse_minor_ratio=minor_ratio,
        compression_axis=comp,
        ellipse_align_to_compression=str(ellipse_align),
    )
    pipe_parts = [p for p in parts if p[0] in ("pipe", "pipe_ellipse")]
    if len(pipe_parts) != 8:
        raise RuntimeError(f"expected 8 pipe parts, got {len(pipe_parts)}")
    return nodes, beams, polylines, pipe_parts


def _seed_ok(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        return int(_count_seed_volumes(path)) == 1
    except Exception:
        return False


def main() -> int:
    p = argparse.ArgumentParser(description="Elliptic paper_box unit-cell seed (multi-route)")
    p.add_argument("--Q", type=float, default=1.0, help="Period factor (1.0, 1.5, …)")
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument("--fuzzy-mm", type=float, default=0.02)
    p.add_argument("--out-step", default="")
    p.add_argument(
        "--skip-gmsh",
        action="store_true",
        help="Skip gmsh both_end route (use for Q=1.5 where gmsh intra-fuse hangs)",
    )
    p.add_argument(
        "--ellipse-align",
        choices=("minor", "major"),
        default="minor",
        help="Ellipse axis aligned to compression direction (+Z)",
    )
    p.add_argument(
        "--out-dir",
        default="",
        help="Seed output directory (default: output/cad/_unitcell_paper_box_cut_ellipse_eqarea[_ellmaj])",
    )
    p.add_argument(
        "--ocp-only",
        action="store_true",
        help="Skip gmsh; sweep OCP glue strategies (both_end_extension only for elliptic)",
    )
    args = p.parse_args()

    q = float(args.Q)
    ellipse_align = str(args.ellipse_align).strip().lower()
    align_tag = "ellmin" if ellipse_align == "minor" else "ellmaj"
    d_major, d_minor, _ = _eqarea_ellipse_params()
    print(
        f"  target area pi mm^2: ellipse d_major={d_major:.4f} "
        f"d_minor={d_minor:.4f} mm (circle reference d=2.0 mm)",
        flush=True,
    )

    gen = HuBaiLatticeGenerator(
        cell_size=float(args.L),
        rod_diameter=d_major,
        amplitude=float(args.Af),
        period_factor=q,
        n_segments=max(3, int(args.n_segments)),
    )
    gen.build_unitcell()
    slug = gen.variant_name.lower()

    default_dir = os.path.join(
        str(CAD_ROOT),
        "_unitcell_paper_box_cut_ellipse_eqarea"
        if ellipse_align == "minor"
        else "_unitcell_paper_box_cut_ellipse_eqarea_ellmaj",
    )
    out_dir = os.path.abspath(args.out_dir.strip() or default_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_step = args.out_step.strip() or os.path.join(
        out_dir,
        f"unitcell_{slug}_paper_box_ellipse_{align_tag}_eqarea.step",
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_step)) or ".", exist_ok=True)

    if _seed_ok(out_step):
        print(f"  skip (vol=1 exists): {out_step}", flush=True)
        return 0

    nodes, beams, polylines, pipe_parts = _load_ellipse_parts(
        L=args.L,
        Af=args.Af,
        period_factor=q,
        n_segments=args.n_segments,
        ellipse_align=ellipse_align,
    )
    _, _, minor_ratio = _eqarea_ellipse_params()
    comp = (0.0, 0.0, 1.0)

    def _gmsh_export(*, both_end: bool, q1_mode: str = "fuse") -> dict:
        return export_unitcell_step_paper_box_cut(
            nodes,
            beams,
            out_step,
            polylines=polylines,
            cell_size_mm=float(args.L),
            n_segments_hint=max(3, int(args.n_segments)),
            period_factor=q,
            q1_mode=q1_mode,
            both_end_extension=both_end,
            rod_diameter_mm=d_major,
            amplitude_mm=float(args.Af),
            solid_profile="ellipse",
            ellipse_minor_ratio=minor_ratio,
            compression_axis=comp,
            ellipse_align_to_compression=ellipse_align,
        )

    _OCP_STRATEGIES: tuple[FuseStrategy, ...] = (
        "sequential_glue_shift",
        "sequential_glue_full",
        "batch_glue_shift",
        "batch_glue_full",
        "x_layer_glue_shift",
        "x_layer_glue_full",
    )
    _OCP_FUZZY = (0.02, 0.05, 0.1) if args.ocp_only else (float(args.fuzzy_mm),)

    def _ocp_export(
        *,
        pipe_mode: str,
        sweep: str,
        strategy: FuseStrategy = "sequential_glue_shift",
        fuzzy_mm: float | None = None,
    ) -> dict:
        return export_q1_ocp_glue_unitcell(
            pipe_parts,
            out_step,
            cell_size_mm=float(args.L),
            strategy=strategy,
            fuzzy_mm=float(fuzzy_mm if fuzzy_mm is not None else args.fuzzy_mm),
            pipe_mode=pipe_mode,
            ellipse_sweep_mode=sweep,
        )

    attempts: list[tuple[str, object]] = []
    skip_gmsh = args.skip_gmsh or args.ocp_only
    if not skip_gmsh:
        if abs(q - 1.0) < 1e-9:
            attempts.append(("gmsh_q1_octant", lambda: _gmsh_export(both_end=False)))
        attempts.append(("gmsh_both_end_extension", lambda: _gmsh_export(both_end=True)))
    if args.ocp_only:
        for sweep in ("parallel_transport", "frenet"):
            for strategy in _OCP_STRATEGIES:
                for fuzzy in _OCP_FUZZY:
                    tag = f"ocp_{sweep[:2]}_{strategy}_f{fuzzy:g}"
                    attempts.append(
                        (
                            tag,
                            lambda s=sweep, st=strategy, fz=fuzzy: _ocp_export(
                                pipe_mode="both_end_extension",
                                sweep=s,
                                strategy=st,
                                fuzzy_mm=fz,
                            ),
                        )
                    )
    else:
        attempts.extend(
            [
                (
                    "ocp_pt_centre_stub",
                    lambda: _ocp_export(pipe_mode="centre_stub", sweep="parallel_transport"),
                ),
                (
                    "ocp_frenet_centre_stub",
                    lambda: _ocp_export(pipe_mode="centre_stub", sweep="frenet"),
                ),
                (
                    "ocp_pt_both_end_extension",
                    lambda: _ocp_export(
                        pipe_mode="both_end_extension", sweep="parallel_transport"
                    ),
                ),
                (
                    "ocp_frenet_both_end_extension",
                    lambda: _ocp_export(pipe_mode="both_end_extension", sweep="frenet"),
                ),
            ]
        )

    errors: list[str] = []
    for label, fn in attempts:
        if os.path.isfile(out_step):
            os.remove(out_step)
        print(f"\n=== Q={q} elliptic seed try: {label} ===", flush=True)
        try:
            report = fn()
            vols = int(_count_seed_volumes(out_step))
            fused = int(report.get("fused_volume_count") or vols or 0)
            if vols != 1:
                raise RuntimeError(f"expected 1 volume, got {vols} (report fused={fused})")
            print(
                f"  OK [{label}]: {out_step} "
                f"mass={report.get('merged_mass_mm3') or report.get('mass_mm3_after_cut')}",
                flush=True,
            )
            return 0
        except Exception as exc:
            msg = f"{label}: {exc}"
            print(f"  FAIL {msg}", flush=True)
            errors.append(msg)
            if os.path.isfile(out_step):
                try:
                    os.remove(out_step)
                except OSError:
                    pass

    raise SystemExit(
        f"Q={q} elliptic seed export failed:\n  " + "\n  ".join(errors)
    )


if __name__ == "__main__":
    raise SystemExit(main())
