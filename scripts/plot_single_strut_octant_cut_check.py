"""
Q1 single-strut octant cut QA: centerline + 1/8 cut box + x/y/z=0 reference planes.

Checks whether the octant clip leaves the strut centred on (0,0,0) and how much
centre-plane overlap (pad) exists for later pairwise fuse.

  py -3 scripts/plot_single_strut_octant_cut_check.py
  py -3 scripts/plot_single_strut_octant_cut_check.py --combined
  py -3 scripts/plot_single_strut_octant_cut_check.py --per-strut
  py -3 scripts/plot_single_strut_octant_cut_check.py --strut 8 --single-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import _collect_solid_primitives
from src.export.unitcell_box_cut import (
    OCTANT_CENTER_OVERLAP_MM,
    _octant_bounds_from_corner_mm,
    unitcell_box_bounds_mm,
    unitcell_octant_corners_mm,
    unitcell_octant_nominal_bounds_mm,
    verify_unitcell_octant_partition_mm,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator, sinusoidal_path_points
from src.paths import CAD_ROOT, REPORTS_ROOT, ensure_output_dirs
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

L = 20.0
AF = 2.0
Q = 1.0
N_SEG = 48
H = 0.5 * L

CORNER_NAMES = (
    "1 (−,−,−)",
    "2 (+,−,−)",
    "3 (−,+,−)",
    "4 (+,+,−)",
    "5 (−,−,+)",
    "6 (+,−,+)",
    "7 (−,+,+)",
    "8 (+,+,+)",
)

STRUT_COLORS = (
    "#E53935",
    "#1E88E5",
    "#43A047",
    "#FB8C00",
    "#8E24AA",
    "#00ACC1",
    "#6D4C41",
    "#546E7A",
)


def _corner_tag(path_pts: tuple) -> str:
    x, y, z = (float(path_pts[-1][0]), float(path_pts[-1][1]), float(path_pts[-1][2]))
    sx = "p" if x > 0 else "m"
    sy = "p" if y > 0 else "m"
    sz = "p" if z > 0 else "m"
    return f"{sx}{sy}{sz}"


def _inside_bounds(p: np.ndarray, b: tuple[float, ...]) -> bool:
    xmin, xmax, ymin, ymax, zmin, zmax = b
    return (
        float(p[0]) >= xmin - 1e-9
        and float(p[0]) <= xmax + 1e-9
        and float(p[1]) >= ymin - 1e-9
        and float(p[1]) <= ymax + 1e-9
        and float(p[2]) >= zmin - 1e-9
        and float(p[2]) <= zmax + 1e-9
    )


def _clip_polyline_to_bounds(
    points: list[np.ndarray],
    bounds: tuple[float, ...],
) -> list[np.ndarray]:
    """Keep centreline samples inside octant bounds (inclusive)."""
    return [p for p in points if _inside_bounds(p, bounds)]


def _box_wireframe_corners(bounds: tuple[float, ...]) -> np.ndarray:
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    return np.array(
        [
            [xmin, ymin, zmin],
            [xmax, ymin, zmin],
            [xmax, ymax, zmin],
            [xmin, ymax, zmin],
            [xmin, ymin, zmax],
            [xmax, ymin, zmax],
            [xmax, ymax, zmax],
            [xmin, ymax, zmax],
        ]
    )


def _box_edges(corners: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    return [(corners[i], corners[j]) for i, j in edges]


def _reference_plane_quads(
    bounds: tuple[float, ...],
    *,
    corner: tuple[float, float, float],
    cell_bounds: tuple[float, ...],
) -> list[tuple[str, np.ndarray, str]]:
    """Semi-transparent quads on x=0 / y=0 / z=0 that bound this octant (exact bisectors)."""
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    sx, sy, sz = (
        (1 if corner[0] > 0 else -1),
        (1 if corner[1] > 0 else -1),
        (1 if corner[2] > 0 else -1),
    )
    quads: list[tuple[str, np.ndarray, str]] = []
    if sx < 0:
        quads.append(
            (
                "x=0 (邻块对接面)",
                np.array(
                    [
                        [0.0, ymin, zmin],
                        [0.0, ymax, zmin],
                        [0.0, ymax, zmax],
                        [0.0, ymin, zmax],
                    ]
                ),
                "#E53935",
            )
        )
    if sy < 0:
        quads.append(
            (
                "y=0",
                np.array(
                    [
                        [xmin, 0.0, zmin],
                        [xmax, 0.0, zmin],
                        [xmax, 0.0, zmax],
                        [xmin, 0.0, zmax],
                    ]
                ),
                "#43A047",
            )
        )
    if sz < 0:
        quads.append(
            (
                "z=0",
                np.array(
                    [
                        [xmin, ymin, 0.0],
                        [xmax, ymin, 0.0],
                        [xmax, ymax, 0.0],
                        [xmin, ymax, 0.0],
                    ]
                ),
                "#1E88E5",
            )
        )
    del cell_bounds
    return quads


def _cell_bisector_planes(cell_bounds: tuple[float, ...]) -> list[tuple[str, np.ndarray, str]]:
    """Full RVE x=0 / y=0 / z=0 reference planes through the cell centre."""
    xmin, xmax, ymin, ymax, zmin, zmax = cell_bounds
    return [
        (
            "x=0",
            np.array(
                [
                    [0.0, ymin, zmin],
                    [0.0, ymax, zmin],
                    [0.0, ymax, zmax],
                    [0.0, ymin, zmax],
                ]
            ),
            "#E53935",
        ),
        (
            "y=0",
            np.array(
                [
                    [xmin, 0.0, zmin],
                    [xmax, 0.0, zmin],
                    [xmax, 0.0, zmax],
                    [xmin, 0.0, zmax],
                ]
            ),
            "#43A047",
        ),
        (
            "z=0",
            np.array(
                [
                    [xmin, ymin, 0.0],
                    [xmax, ymin, 0.0],
                    [xmax, ymax, 0.0],
                    [xmin, ymax, 0.0],
                ]
            ),
            "#1E88E5",
        ),
    ]


def _rve_wireframe(cell_bounds: tuple[float, ...]) -> np.ndarray:
    xmin, xmax, ymin, ymax, zmin, zmax = cell_bounds
    return _box_wireframe_corners((xmin, xmax, ymin, ymax, zmin, zmax))


def _overlap_slab_boxes(
    bounds: tuple[float, ...],
    pad: float,
) -> list[tuple[str, np.ndarray]]:
    """Show thin overlap slabs extending pad past each centre plane."""
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    h = H
    slabs: list[tuple[str, np.ndarray]] = []
    tol = 1e-6
    if pad <= 0.0:
        return slabs
    if xmin < -tol:
        slabs.append(
            (
                f"x overlap [{xmin:g}, 0]",
                np.array(
                    [
                        [xmin, -h, -h],
                        [0.0, -h, -h],
                        [0.0, h, -h],
                        [xmin, h, -h],
                        [xmin, -h, h],
                        [0.0, -h, h],
                        [0.0, h, h],
                        [xmin, h, h],
                    ]
                ),
            )
        )
    if xmax > tol:
        slabs.append(
            (
                f"x overlap [0, {xmax:g}]",
                np.array(
                    [
                        [0.0, -h, -h],
                        [xmax, -h, -h],
                        [xmax, h, -h],
                        [0.0, h, -h],
                        [0.0, -h, h],
                        [xmax, -h, h],
                        [xmax, h, h],
                        [0.0, h, h],
                    ]
                ),
            )
        )
    if ymin < -tol:
        slabs.append(
            (
                f"y overlap [{ymin:g}, 0]",
                np.array(
                    [
                        [-h, ymin, -h],
                        [h, ymin, -h],
                        [h, 0.0, -h],
                        [-h, 0.0, -h],
                        [-h, ymin, h],
                        [h, ymin, h],
                        [h, 0.0, h],
                        [-h, 0.0, h],
                    ]
                ),
            )
        )
    if ymax > tol:
        slabs.append(
            (
                f"y overlap [0, {ymax:g}]",
                np.array(
                    [
                        [-h, 0.0, -h],
                        [h, 0.0, -h],
                        [h, ymax, -h],
                        [-h, ymax, -h],
                        [-h, 0.0, h],
                        [h, 0.0, h],
                        [h, ymax, h],
                        [-h, ymax, h],
                    ]
                ),
            )
        )
    if zmin < -tol:
        slabs.append(
            (
                f"z overlap [{zmin:g}, 0]",
                np.array(
                    [
                        [-h, -h, zmin],
                        [h, -h, zmin],
                        [h, h, zmin],
                        [-h, h, zmin],
                        [-h, -h, 0.0],
                        [h, -h, 0.0],
                        [h, h, 0.0],
                        [-h, h, 0.0],
                    ]
                ),
            )
        )
    if zmax > tol:
        slabs.append(
            (
                f"z overlap [0, {zmax:g}]",
                np.array(
                    [
                        [-h, -h, 0.0],
                        [h, -h, 0.0],
                        [h, h, 0.0],
                        [-h, h, 0.0],
                        [-h, -h, zmax],
                        [h, -h, zmax],
                        [h, h, zmax],
                        [-h, h, zmax],
                    ]
                ),
            )
        )
    return slabs


def _diagnostics(
    strut_idx: int,
    p0: np.ndarray,
    p1: np.ndarray,
    full_pts: list[np.ndarray],
    clipped_pts: list[np.ndarray],
    oct_bounds: tuple[float, ...],
    nominal_bounds: tuple[float, ...],
    pad: float,
) -> dict:
    xmin, xmax, ymin, ymax, zmin, zmax = oct_bounds
    nxmin, nxmax, nymin, nymax, nzmin, nzmax = nominal_bounds
    centre_err = float(np.linalg.norm(p0))
    inside_count = len(clipped_pts)
    first_out = None
    for i, p in enumerate(full_pts):
        if not _inside_bounds(p, oct_bounds):
            first_out = (i, p)
            break
    last_in = clipped_pts[-1] if clipped_pts else None
    report = {
        "strut_index": strut_idx,
        "corner_mm": [float(p1[0]), float(p1[1]), float(p1[2])],
        "centre_mm": [float(p0[0]), float(p0[1]), float(p0[2])],
        "centre_norm_mm": centre_err,
        "octant_bounds_mm": {
            "x": [xmin, xmax],
            "y": [ymin, ymax],
            "z": [zmin, zmax],
        },
        "nominal_octant_bounds_mm": {
            "x": [nxmin, nxmax],
            "y": [nymin, nymax],
            "z": [nzmin, nzmax],
        },
        "centre_overlap_pad_mm": pad,
        "centre_overlap_slab_mm_per_axis": pad,
        "pairwise_overlap_at_plane_mm": float(pad),
        "symmetric_half_overlap_mm": float(pad) / 2.0 if pad > 0.0 else 0.0,
        "n_centerline_total": len(full_pts),
        "n_centerline_inside_octant": inside_count,
        "mass_fraction_centerline": inside_count / max(len(full_pts), 1),
        "first_centerline_outside_index": first_out[0] if first_out else None,
        "first_centerline_outside_mm": (
            [float(first_out[1][0]), float(first_out[1][1]), float(first_out[1][2])]
            if first_out
            else None
        ),
        "clipped_endpoint_mm": (
            [float(last_in[0]), float(last_in[1]), float(last_in[2])] if last_in is not None else None
        ),
        "note": (
            "名义 1/8 虚拟立方体在 x/y/z=0 与 ±L/2 对齐；OCC 切/融时在 bisector 两侧各外扩 "
            f"pad/2={pad/2:g} mm（总重叠 pad={pad:g} mm）。"
        ),
    }
    return report


def _plot_check(
    *,
    strut_idx: int,
    full_pts: list[np.ndarray],
    clipped_pts: list[np.ndarray],
    oct_bounds: tuple[float, ...],
    nominal_bounds: tuple[float, ...],
    corner: tuple[float, float, float],
    cell_bounds: tuple[float, ...],
    pad: float,
    out_png: str,
    title: str,
) -> None:
    fig = plt.figure(figsize=(14, 6), dpi=150)

    ax3 = fig.add_subplot(1, 2, 1, projection="3d")
    axz = fig.add_subplot(1, 2, 2)

    # RVE wireframe (grey)
    rve_c = _rve_wireframe(cell_bounds)
    for a, b in _box_edges(rve_c):
        ax3.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            [a[2], b[2]],
            color="#9E9E9E",
            lw=0.8,
            alpha=0.7,
        )

    # Nominal 1/8 cube (exact x/y/z=0 split) + OCC cut box (pad extension)
    nom_c = _box_wireframe_corners(nominal_bounds)
    ax3.add_collection3d(
        Line3DCollection(
            _box_edges(nom_c),
            colors="#455A64",
            linewidths=1.6,
            linestyles="--",
        )
    )
    oct_c = _box_wireframe_corners(oct_bounds)
    oct_edges = _box_edges(oct_c)
    ax3.add_collection3d(
        Line3DCollection(oct_edges, colors="#FF9800", linewidths=2.0, linestyles="-")
    )

    # Overlap slabs (yellow, faint)
    for label, corners in _overlap_slab_boxes(oct_bounds, pad):
        faces = [
            [corners[0], corners[1], corners[2], corners[3]],
            [corners[4], corners[5], corners[6], corners[7]],
            [corners[0], corners[1], corners[5], corners[4]],
            [corners[2], corners[3], corners[7], corners[6]],
            [corners[1], corners[2], corners[6], corners[5]],
            [corners[0], corners[3], corners[7], corners[4]],
        ]
        ax3.add_collection3d(
            Poly3DCollection(
                faces,
                facecolors="#FFEB3B",
                edgecolors="#F9A825",
                alpha=0.12,
                linewidths=0.4,
            )
        )

    # Reference planes at exact x/y/z=0 (nominal bisectors)
    for name, quad, color in _reference_plane_quads(
        nominal_bounds,
        corner=corner,
        cell_bounds=cell_bounds,
    ):
        ax3.add_collection3d(
            Poly3DCollection(
                [quad],
                facecolors=color,
                edgecolors=color,
                alpha=0.22,
                linewidths=1.0,
            )
        )

    full_arr = np.array(full_pts)
    clip_arr = np.array(clipped_pts) if clipped_pts else np.empty((0, 3))

    ax3.plot(full_arr[:, 0], full_arr[:, 1], full_arr[:, 2], color="#B0BEC5", lw=1.5, ls=":", label="完整杆中心线")
    if len(clip_arr):
        ax3.plot(clip_arr[:, 0], clip_arr[:, 1], clip_arr[:, 2], color="#C2185B", lw=2.5, label="octant 内中心线")
    ax3.scatter([0.0], [0.0], [0.0], c="k", s=60, depthshade=False, label="胞心 (0,0,0)")
    ax3.scatter(
        [full_arr[-1, 0]],
        [full_arr[-1, 1]],
        [full_arr[-1, 2]],
        c="#546E7A",
        s=40,
        depthshade=False,
        label="角点",
    )

    ax3.set_xlabel("X (mm)")
    ax3.set_ylabel("Y (mm)")
    ax3.set_zlabel("Z (mm)")
    ax3.set_title(
        f"{title}\n3D — 灰虚=名义 1/8 立方  橙=OCC 切框  黄=overlap  红/绿/蓝=x/y/z=0"
    )
    lim = H * 1.05
    ax3.set_xlim(-lim, lim)
    ax3.set_ylim(-lim, lim)
    ax3.set_zlim(-lim, lim)
    try:
        ax3.set_box_aspect((1, 1, 1))
    except AttributeError:
        pass
    ax3.legend(loc="upper left", fontsize=7)

    # Zoom: X–Z through centre
    axz.plot(full_arr[:, 0], full_arr[:, 2], color="#B0BEC5", lw=1.5, ls=":", label="完整杆 (X–Z)")
    if len(clip_arr):
        axz.plot(clip_arr[:, 0], clip_arr[:, 2], color="#C2185B", lw=2.5, label="octant 内")
    axz.axvline(0.0, color="#E53935", lw=1.2, alpha=0.8, label="x=0 参考面")
    axz.axhline(0.0, color="#1E88E5", lw=1.2, alpha=0.8, label="z=0 参考面")
    xmin, xmax, _, _, zmin, zmax = oct_bounds
    axz.axvspan(xmin, 0.0, color="#FFEB3B", alpha=0.15, label=f"x overlap [{xmin:g},0]")
    axz.axhspan(zmin, 0.0, color="#FFF59D", alpha=0.15, label=f"z overlap [{zmin:g},0]")
    axz.scatter([0.0], [0.0], c="k", s=50, zorder=5)
    axz.scatter([full_arr[-1, 0]], [full_arr[-1, 2]], c="#546E7A", s=35, zorder=5)
    axz.set_aspect("equal")
    axz.grid(True, alpha=0.3)
    axz.set_xlabel("X (mm)")
    axz.set_ylabel("Z (mm)")
    axz.set_title("胞心附近 X–Z 投影（检查裁切面与中心线）")
    axz.set_xlim(-3.5, 3.5)
    axz.set_ylim(-3.5, 3.5)
    axz.legend(fontsize=7, loc="upper left")

    fig.suptitle(title, fontsize=12, y=0.98)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _plot_all_struts_combined(
    *,
    strut_series: list[dict],
    cell_bounds: tuple[float, ...],
    pad: float,
    out_png: str,
) -> None:
    """Eight octant-clipped struts + RVE + x/y/z=0 planes on one figure."""
    fig = plt.figure(figsize=(16, 7), dpi=150)
    ax3 = fig.add_subplot(1, 2, 1, projection="3d")
    axz = fig.add_subplot(1, 2, 2)

    rve_c = _rve_wireframe(cell_bounds)
    for a, b in _box_edges(rve_c):
        ax3.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            [a[2], b[2]],
            color="#757575",
            lw=1.0,
            alpha=0.85,
        )

    for name, quad, color in _cell_bisector_planes(cell_bounds):
        ax3.add_collection3d(
            Poly3DCollection(
                [quad],
                facecolors=color,
                edgecolors=color,
                alpha=0.10,
                linewidths=0.8,
            )
        )

    # Eight nominal 1/8 virtual cubes — exact alignment at x/y/z=0 and RVE faces
    for corner in unitcell_octant_corners_mm(L):
        nom = unitcell_octant_nominal_bounds_mm(corner, L)
        nom_edges = _box_edges(_box_wireframe_corners(nom))
        ax3.add_collection3d(
            Line3DCollection(
                nom_edges,
                colors="#78909C",
                linewidths=0.9,
                linestyles="--",
                alpha=0.85,
            )
        )

    pad_h = H
    overlap_style = dict(color="#FFEB3B", alpha=0.08, lw=0.6, ls="--")
    ax3.plot([-pad, pad], [-pad_h, -pad_h], [-pad_h, -pad_h], **overlap_style)
    ax3.text(pad * 1.2, -pad_h, -pad_h, f"pad={pad:g} mm", fontsize=7, color="#F57F17")

    for i, item in enumerate(strut_series):
        idx = int(item["strut_index"])
        color = STRUT_COLORS[i % len(STRUT_COLORS)]
        clip_arr = np.array(item["clipped_pts"])
        full_arr = np.array(item["full_pts"])
        tag = item["corner_tag"]
        label = f"{idx} {tag}"

        ax3.plot(
            clip_arr[:, 0],
            clip_arr[:, 1],
            clip_arr[:, 2],
            color=color,
            lw=2.2,
            label=label,
        )
        ax3.scatter(
            [full_arr[-1, 0]],
            [full_arr[-1, 1]],
            [full_arr[-1, 2]],
            c=[color],
            s=28,
            depthshade=False,
        )

        axz.plot(clip_arr[:, 0], clip_arr[:, 2], color=color, lw=2.0, label=label)
        axz.scatter([full_arr[-1, 0]], [full_arr[-1, 2]], c=[color], s=22, zorder=4)

    ax3.scatter([0.0], [0.0], [0.0], c="k", s=70, depthshade=False, label="胞心 (0,0,0)")
    axz.scatter([0.0], [0.0], c="k", s=55, zorder=6, label="胞心")
    axz.axvline(0.0, color="#E53935", lw=1.0, alpha=0.7)
    axz.axhline(0.0, color="#1E88E5", lw=1.0, alpha=0.7)
    axz.axvspan(-pad, pad, color="#FFEB3B", alpha=0.12)
    axz.axhspan(-pad, pad, color="#FFF59D", alpha=0.12)

    lim = H * 1.02
    ax3.set_xlim(-lim, lim)
    ax3.set_ylim(-lim, lim)
    ax3.set_zlim(-lim, lim)
    ax3.set_xlabel("X (mm)")
    ax3.set_ylabel("Y (mm)")
    ax3.set_zlabel("Z (mm)")
    ax3.set_title("8×名义 1/8 虚拟立方（虚线）+ 裁切杆 + RVE + x/y/z=0")
    try:
        ax3.set_box_aspect((1, 1, 1))
    except AttributeError:
        pass
    ax3.legend(loc="upper left", fontsize=7, ncol=2)

    axz.set_xlim(-4.0, 4.0)
    axz.set_ylim(-4.0, 4.0)
    axz.set_aspect("equal")
    axz.grid(True, alpha=0.3)
    axz.set_xlabel("X (mm)")
    axz.set_ylabel("Z (mm)")
    axz.set_title("胞心附近 X–Z（8 杆叠加，查对接缝）")
    axz.legend(fontsize=7, loc="upper left", ncol=2)

    fig.suptitle(
        f"AF2Q1 八杆 octant 总览 — 虚线=名义 1/8 立方（x/y/z=0 对齐），pad={pad:g} mm 仅用于 OCC 切框",
        fontsize=13,
        y=0.98,
    )
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _collect_strut_series(
    pipes: list,
    *,
    pad: float,
) -> list[dict]:
    series: list[dict] = []
    canonical_corners = unitcell_octant_corners_mm(L)
    for idx, part in enumerate(pipes, start=1):
        path_pts = part[1]
        p0 = np.asarray(path_pts[0], dtype=float)
        p1 = np.asarray(path_pts[-1], dtype=float)
        corner = canonical_corners[idx - 1]
        path_corner = tuple(float(v) for v in p1)
        if any(abs(path_corner[i] - corner[i]) > 1e-3 for i in range(3)):
            raise RuntimeError(
                f"strut {idx} endpoint {path_corner} != canonical octant corner {corner}"
            )
        nominal_bounds = unitcell_octant_nominal_bounds_mm(corner, L)
        oct_bounds = _octant_bounds_from_corner_mm(corner, L, center_overlap_mm=pad)
        full_pts = sinusoidal_path_points(
            p0,
            p1,
            amplitude=AF,
            period_factor=Q,
            n_segments=N_SEG,
        )
        clipped_pts = _clip_polyline_to_bounds(full_pts, oct_bounds)
        series.append(
            {
                "strut_index": idx,
                "corner_tag": _corner_tag(path_pts),
                "full_pts": full_pts,
                "clipped_pts": clipped_pts,
                "oct_bounds": oct_bounds,
                "nominal_bounds": nominal_bounds,
                "corner": corner,
                "p0": p0,
                "p1": p1,
            }
        )
    return series


def main() -> int:
    configure_matplotlib_chinese()
    ensure_output_dirs()

    p = argparse.ArgumentParser(description="Plot octant-cut struts vs reference planes")
    p.add_argument("--strut", type=int, default=1, help="1..8 for --single-only mode")
    p.add_argument("--pad", type=float, default=None, help="centre overlap mm (default: code constant)")
    p.add_argument("--export-step", action="store_true", help="Export cut strut STEP(s)")
    p.add_argument(
        "--per-strut",
        action="store_true",
        help="Also write 8 separate per-strut PNGs",
    )
    p.add_argument(
        "--single-only",
        action="store_true",
        help="Only plot one --strut (no combined figure)",
    )
    args = p.parse_args()

    pad = float(OCTANT_CENTER_OVERLAP_MM if args.pad is None else args.pad)
    cell_bounds = unitcell_box_bounds_mm(L)

    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=2.0,
        amplitude=AF,
        period_factor=Q,
        n_segments=N_SEG,
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    _, pipes_only = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    pipes = [p for p in pipes_only if p[0] == "pipe"]
    if not pipes:
        raise SystemExit("No pipe primitives.")

    out_dir = REPORTS_ROOT / "octant_cut_check"
    out_dir.mkdir(parents=True, exist_ok=True)

    strut_series = _collect_strut_series(pipes, pad=pad)
    do_combined = not args.single_only
    per_strut_indices: set[int] | None
    if args.single_only:
        per_strut_indices = {int(args.strut)}
    elif args.per_strut:
        per_strut_indices = set(range(1, 9))
    else:
        per_strut_indices = None

    if do_combined:
        combined_png = out_dir / "all_8_struts_octant_cut_check.png"
        _plot_all_struts_combined(
            strut_series=strut_series,
            cell_bounds=cell_bounds,
            pad=pad,
            out_png=str(combined_png),
        )
        print("Saved:", combined_png)

    all_reports: list[dict] = []
    for item in strut_series:
        idx = int(item["strut_index"])
        if per_strut_indices is not None and idx not in per_strut_indices:
            continue
        p0 = item["p0"]
        p1 = item["p1"]
        oct_bounds = item["oct_bounds"]
        nominal_bounds = item["nominal_bounds"]
        corner = item["corner"]
        full_pts = item["full_pts"]
        clipped_pts = item["clipped_pts"]
        tag = item["corner_tag"]
        title = f"AF2Q1 杆 {idx} {CORNER_NAMES[idx - 1]}  octant={tag}  pad={pad:g} mm"

        if per_strut_indices is not None:
            png = out_dir / f"strut_{idx:02d}_{tag}_octant_cut_check.png"
            _plot_check(
                strut_idx=idx,
                full_pts=full_pts,
                clipped_pts=clipped_pts,
                oct_bounds=oct_bounds,
                nominal_bounds=nominal_bounds,
                corner=corner,
                cell_bounds=cell_bounds,
                pad=pad,
                out_png=str(png),
                title=title,
            )
            print("Saved:", png)

        report = _diagnostics(
            idx, p0, p1, full_pts, clipped_pts, oct_bounds, nominal_bounds, pad
        )
        report["corner_tag"] = tag
        all_reports.append(report)

        if args.export_step and (per_strut_indices is None or idx in per_strut_indices):
            from scripts.export_single_strut_paper_box_cut import (
                export_single_strut_paper_box_cut,
            )

            step_dir = CAD_ROOT / "_single_strut_paper_box_cut"
            step_path = str(
                step_dir / f"single_strut_sfbls_af2q1_s{idx:02d}_{tag}_octant.step"
            )
            step_rep = export_single_strut_paper_box_cut(
                period_factor=Q,
                strut_index=idx,
                cell_size_mm=L,
                out_path=step_path,
            )
            report["step_path"] = step_rep["step_path"]
            report["cut_mass_mm3"] = step_rep["cut_mass_mm3"]
            print("STEP:", step_rep["step_path"])

    if do_combined:
        for item in strut_series:
            idx = int(item["strut_index"])
            if any(r["strut_index"] == idx for r in all_reports):
                continue
            report = _diagnostics(
                idx,
                item["p0"],
                item["p1"],
                item["full_pts"],
                item["clipped_pts"],
                item["oct_bounds"],
                item["nominal_bounds"],
                pad,
            )
            report["corner_tag"] = item["corner_tag"]
            all_reports.append(report)
    all_reports.sort(key=lambda r: int(r["strut_index"]))

    json_path = out_dir / "octant_cut_diagnostics.json"
    partition = verify_unitcell_octant_partition_mm(L, center_overlap_mm=pad)
    payload = {
        "variant": gen.variant_name,
        "Q": Q,
        "L_mm": L,
        "octant_center_overlap_mm": pad,
        "octant_partition": partition,
        "struts": all_reports,
        "why_merge_gaps": (
            "名义八立方体在 x/y/z=0 精确对齐；对称 bisector 重叠 pad/2+pad/2 供 OCC 融合。"
            f"当前 pad={pad:g} mm（每侧 {pad/2:g} mm）。"
        ),
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("Diagnostics:", json_path)

    r0 = all_reports[0]
    print(
        f"\n杆 {r0['strut_index']}: 胞心={r0['centre_mm']} (|r|={r0['centre_norm_mm']:.2e} mm) "
        f"octant x={r0['octant_bounds_mm']['x']} y={r0['octant_bounds_mm']['y']} "
        f"z={r0['octant_bounds_mm']['z']}"
    )
    print(
        f"  中心线: {r0['n_centerline_inside_octant']}/{r0['n_centerline_total']} 点在 octant 内; "
        f"邻块对接重叠带厚度 2×pad = {r0['pairwise_overlap_at_plane_mm']:.3f} mm"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
