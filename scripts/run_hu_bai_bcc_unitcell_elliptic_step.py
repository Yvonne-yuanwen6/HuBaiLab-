"""
Export a single Hu & Bai BCC unit cell as a fused STEP solid with **elliptic struts**.

The ellipse **minor axis** is aligned with the compression direction (global axis),
projected onto each strut's cross-section plane (normal to the strut tangent).

Example:
  py -3 scripts/run_hu_bai_bcc_unitcell_elliptic_step.py --D-major 3.0 --D-minor 2.0 --compress-axis z
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.ocp_unitcell_fuse import (
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_write_step_via_gmsh_brep_heal,
    ocp_elliptic_pipe_along_points,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs


def _axis_vec(name: str) -> np.ndarray:
    n = str(name).strip().lower()
    if n == "x":
        return np.array([1.0, 0.0, 0.0], dtype=float)
    if n == "y":
        return np.array([0.0, 1.0, 0.0], dtype=float)
    if n == "z":
        return np.array([0.0, 0.0, 1.0], dtype=float)
    raise ValueError(f"Unknown axis: {name!r} (use x/y/z)")


def _major_axis_hint_from_compression(
    tangent: np.ndarray,
    compress_dir: np.ndarray,
) -> np.ndarray:
    """
    Build an in-plane axis for the ellipse *major* axis such that the *minor* axis
    aligns with compression direction.
    """
    t = np.asarray(tangent, dtype=float)
    t_n = float(np.linalg.norm(t))
    if t_n < 1e-12:
        return np.array([1.0, 0.0, 0.0], dtype=float)
    t = t / t_n

    c = np.asarray(compress_dir, dtype=float)
    c = c / max(1e-12, float(np.linalg.norm(c)))
    minor = c - float(np.dot(c, t)) * t
    mn = float(np.linalg.norm(minor))
    if mn < 1e-9:
        # Compression axis parallel to tangent; pick any stable orthogonal axis.
        g = np.array([0.0, 1.0, 0.0], dtype=float)
        minor = g - float(np.dot(g, t)) * t
        mn = float(np.linalg.norm(minor))
        if mn < 1e-9:
            g = np.array([1.0, 0.0, 0.0], dtype=float)
            minor = g - float(np.dot(g, t)) * t
            mn = float(np.linalg.norm(minor))
    minor = minor / max(1e-12, mn)
    major = np.cross(t, minor)
    mj = float(np.linalg.norm(major))
    if mj < 1e-12:
        return np.array([1.0, 0.0, 0.0], dtype=float)
    return major / mj


def main() -> None:
    ensure_output_dirs()

    ap = argparse.ArgumentParser(description="Hu & Bai BCC unit cell -> elliptic-strut fused STEP")
    ap.add_argument("--L", type=float, default=20.0, help="Cell size L [mm]")
    ap.add_argument("--Af", type=float, default=0.0, help="Sinusoid amplitude A_f [mm] (0 => straight BCC)")
    ap.add_argument("--Q", type=float, default=0.0, help="Period factor Q (0 => BCC)")
    ap.add_argument("--n-segments", type=int, default=24, help="Polyline segments for curved struts")
    ap.add_argument("--D-major", type=float, default=3.0, help="Ellipse major diameter [mm]")
    ap.add_argument("--D-minor", type=float, default=2.0, help="Ellipse minor diameter [mm] (compression-aligned)")
    ap.add_argument("--compress-axis", choices=("x", "y", "z"), default="z", help="Compression direction axis")
    ap.add_argument("--out", type=str, default="", help="Output STEP path (default: output/cad/...)")
    args = ap.parse_args()

    L = float(args.L)
    Dmaj = float(args.D_major)
    Dmin = float(args.D_minor)
    if Dmaj <= 0.0 or Dmin <= 0.0:
        raise SystemExit("D-major and D-minor must be positive.")

    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=1.0,  # not used for solid sweep; keep generator independent
        amplitude=float(args.Af),
        period_factor=float(args.Q),
        n_segments=max(4, int(args.n_segments)),
    )
    gen.build_unitcell()
    nodes, _beams, polylines = gen.get_data(copy=True)

    nid_to_xyz: dict[int, np.ndarray] = {
        int(nid): np.array([float(x), float(y), float(z)], dtype=float)
        for nid, x, y, z in nodes
    }

    compress_dir = _axis_vec(str(args.compress_axis))

    pipe_solids = []
    for poly in polylines:
        nids = poly.get("nodes") or []
        pts = [nid_to_xyz[int(n)] for n in nids if int(n) in nid_to_xyz]
        if len(pts) < 2:
            continue
        tangent0 = pts[1] - pts[0]
        major_hint = _major_axis_hint_from_compression(tangent0, compress_dir)
        solid = ocp_elliptic_pipe_along_points(
            tuple(tuple(float(v) for v in p) for p in pts),
            major_radius=0.5 * Dmaj,
            minor_radius=0.5 * Dmin,
            major_axis_hint=major_hint,
            open_at_start=False,
        )
        pipe_solids.append(solid)

    if not pipe_solids:
        raise SystemExit("No strut solids were generated (check generator output).")

    fused = pipe_solids[0]
    for s in pipe_solids[1:]:
        fused = ocp_fuse_pair(fused, s, glue="off", fuzzy_mm=1e-3, label="unitcell-ellipse-fuse")

    fused = ocp_heal_fused_solid(fused)

    slug = f"hu_bai_bcc_unitcell_ellipse_L{int(round(L))}_D{Dmaj:g}x{Dmin:g}_c{args.compress_axis}"
    out_path = str(args.out).strip()
    if not out_path:
        os.makedirs(str(CAD_ROOT), exist_ok=True)
        out_path = os.path.join(str(CAD_ROOT), f"{slug}.step")

    stats = ocp_write_step_via_gmsh_brep_heal(fused, out_path)
    print(f"OK: {out_path}")
    print(f"STEP readback: solids={stats.get('solids')} bytes={stats.get('step_bytes')}")


if __name__ == "__main__":
    main()

