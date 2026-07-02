"""
Paper Fig.2(a) check: one oblique wireframe per structure (BCC, Q0.5, Q1, Q1.5).

Uses the same Eq.2.1 path as HuBaiLatticeGenerator (Q=1: −A_f sin; other Q: +A_f sin).
Highlights the bottom-left strut: centre → corner (-L/2, -L/2, -L/2).

  py -3 scripts/plot_paper_unitcell_oblique_wireframes.py
"""
from __future__ import annotations

import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Line3DCollection

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import REPORTS_ROOT
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

L = 20.0
AF = 2.0
N_SEG = 48
H = 0.5 * L
# Paper / model: strut to (-,-,-) octant — 左下侧代表杆
HIGHLIGHT_CORNER = np.array([-H, -H, -H])

STRUCTURES = (
    (0.0, "BCC AF2Q0", "bcc"),
    (0.5, "SFBLS AF2Q0.5", "af2q05"),
    (1.0, "SFBLS AF2Q1", "af2q1"),
    (1.5, "SFBLS AF2Q1.5", "af2q15"),
)

COLORS = {
    "bcc": "#546E7A",
    "af2q05": "#1565C0",
    "af2q1": "#C2185B",
    "af2q15": "#E53935",
}


def _build(q: float):
    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=2.0,
        amplitude=AF,
        period_factor=q,
        n_segments=N_SEG,
    )
    gen.build_unitcell()
    return gen.get_data(copy=True)


def _node_dict(nodes) -> dict[int, tuple[float, float, float]]:
    return {int(n[0]): (float(n[1]), float(n[2]), float(n[3])) for n in nodes}


def _is_highlight_polyline(node_dict: dict, poly: dict, tol: float = 0.5) -> bool:
    pts = [np.array(node_dict[int(nid)], dtype=float) for nid in poly["nodes"]]
    end = pts[-1]
    return float(np.linalg.norm(end - HIGHLIGHT_CORNER)) < tol


def _rve_box_edges() -> list[tuple[np.ndarray, np.ndarray]]:
    h = H
    corners = [
        (-h, -h, -h),
        (h, -h, -h),
        (h, h, -h),
        (-h, h, -h),
        (-h, -h, h),
        (h, -h, h),
        (h, h, h),
        (-h, h, h),
    ]
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
    c = [np.array(p, dtype=float) for p in corners]
    return [(c[i], c[j]) for i, j in edges]


def _plot_one(ax, q: float, title: str, key: str, nodes, polylines) -> None:
    node_dict = _node_dict(nodes)
    color = COLORS.get(key, "#333333")

    # RVE paper box (dashed)
    for p0, p1 in _rve_box_edges():
        ax.plot(
            [p0[0], p1[0]],
            [p0[1], p1[1]],
            [p0[2], p1[2]],
            color="#999999",
            lw=0.8,
            ls=":",
            alpha=0.7,
        )

    for poly in polylines:
        pts = np.array([node_dict[int(nid)] for nid in poly["nodes"]])
        hl = _is_highlight_polyline(node_dict, poly)
        if hl:
            # Q=0 reference chord (dotted diagonal)
            ax.plot(
                [pts[0, 0], pts[-1, 0]],
                [pts[0, 1], pts[-1, 1]],
                [pts[0, 2], pts[-1, 2]],
                color="#888888",
                lw=1.0,
                ls=(0, (3, 3)),
                alpha=0.9,
            )
            ax.plot(
                pts[:, 0],
                pts[:, 1],
                pts[:, 2],
                color=color,
                lw=2.8,
                solid_capstyle="round",
                label="左下单杆 (-,-,-)",
            )
            ax.scatter(
                [pts[0, 0], pts[-1, 0]],
                [pts[0, 1], pts[-1, 1]],
                [pts[0, 2], pts[-1, 2]],
                c=["crimson", "black"],
                s=28,
                depthshade=False,
                zorder=5,
            )
        else:
            ax.plot(
                pts[:, 0],
                pts[:, 1],
                pts[:, 2],
                color=color,
                lw=1.0,
                alpha=0.35,
            )

    ax.scatter([0.0], [0.0], [0.0], c="crimson", s=36, depthshade=False, zorder=6)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    sin_sign = "−" if abs(q - 1.0) < 1e-9 else "+"
    ax.set_title(f"{title}\nQ={q:g}  f(s)={sin_sign}A_f sin(2πQs)", fontsize=10)
    # Oblique side view: left-bottom strut readable (论文屈曲杆对照视角)
    ax.view_init(elev=22, azim=-52)
    lim = H * 1.15
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_zlim(-lim, lim)
    try:
        ax.set_box_aspect((1, 1, 1))
    except AttributeError:
        pass
    ax.legend(loc="upper left", fontsize=7, framealpha=0.85)


def main() -> int:
    configure_matplotlib_chinese()
    out_dir = REPORTS_ROOT / "paper_unitcell_oblique"
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(12, 10), subplot_kw={"projection": "3d"})
    axes_flat = axes.ravel()

    for ax, (q, title, key) in zip(axes_flat, STRUCTURES):
        nodes, _beams, polylines = _build(q)
        _plot_one(ax, q, title, key, nodes, polylines)
        single = out_dir / f"unitcell_{key}_oblique.png"
        fig_i = plt.figure(figsize=(6, 5.5), dpi=150)
        ax_i = fig_i.add_subplot(111, projection="3d")
        _plot_one(ax_i, q, title, key, nodes, polylines)
        fig_i.tight_layout()
        fig_i.savefig(single, bbox_inches="tight", facecolor="white")
        plt.close(fig_i)
        print("Saved:", single)

    fig.suptitle(
        "论文 Fig.2(a) 对照 — 单胞线框（左下单杆加粗，虚线为 Q=0 弦线）",
        fontsize=12,
        y=0.98,
    )
    fig.tight_layout()
    combined = out_dir / "paper_unitcell_oblique_all.png"
    fig.savefig(combined, bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)
    print("Saved:", combined)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
