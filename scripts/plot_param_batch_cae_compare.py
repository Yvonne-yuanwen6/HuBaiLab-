#!/usr/bin/env python3
"""2×3 stress-strain compare for 批量构型 Abaqus CAE batch.

Layout:
  (a) Q sweep · k=1 circle
  (b) Q sweep · k=2 ellipse
  (c) Q sweep · k=1.5 ellipse
  (d) κ sweep · Q=0
  (e) κ sweep · Q=0.5
  (f) Af + deq @ Q=1

Usage:
  # Preview layout with synthetic curves (no ODB/csv needed)
  py -3 scripts/plot_param_batch_cae_compare.py --demo

  # Real data from local post tree (after scp)
  py -3 scripts/plot_param_batch_cae_compare.py

  # Custom roots
  py -3 scripts/plot_param_batch_cae_compare.py \\
    --post-root output/post/批量构型 \\
    --out output/reports/批量构型/batch_cae_stress_strain_compare.png
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.paths import PROJECT_ROOT, REPORTS_ROOT

RUN_SLUG = "cae_tet0p6mm80_5mmin_paperbox"
BATCH_NAME = "批量构型"
DEFAULT_POST = PROJECT_ROOT / "output" / "post" / BATCH_NAME
DEFAULT_OUT = REPORTS_ROOT / BATCH_NAME / "batch_cae_stress_strain_compare.png"

# Panel definitions: title, list of (case_id, legend_label)
PANELS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "(a) Q sweep · k=1 (circle)",
        [
            ("af2q0_deq2_k1", "Q=0"),
            ("af2q0p5_deq2_k1", "Q=0.5"),
            ("af2q1_deq2_k1", "Q=1"),
            ("af2q1p5_deq2_k1", "Q=1.5"),
        ],
    ),
    (
        "(b) Q sweep · k=2 (ellipse)",
        [
            ("af2q0_deq2_k2", "Q=0"),
            ("af2q0p5_deq2_k2", "Q=0.5"),
            ("af2q1_deq2_k2", "Q=1"),
            ("af2q1p5_deq2_k2", "Q=1.5"),
        ],
    ),
    (
        "(c) Q sweep · k=1.5 (ellipse)",
        [
            ("af2q0_deq2_k1p5", "Q=0"),
            ("af2q0p5_deq2_k1p5", "Q=0.5"),
            ("af2q1_deq2_k1p5", "Q=1"),
            ("af2q1p5_deq2_k1p5", "Q=1.5"),
        ],
    ),
    (
        "(d) κ sweep · Q=0",
        [
            ("af2q0_deq2_k1", "k=1"),
            ("af2q0_deq2_k1p5", "k=1.5"),
            ("af2q0_deq2_k2", "k=2"),
        ],
    ),
    (
        "(e) κ sweep · Q=0.5",
        [
            ("af2q0p5_deq2_k1", "k=1"),
            ("af2q0p5_deq2_k1p5", "k=1.5"),
            ("af2q0p5_deq2_k2", "k=2"),
        ],
    ),
    (
        "(f) Af + deq @ Q=1, k=1",
        [
            ("af1q1_deq2_k1", "Af=1"),
            ("af2q1_deq2_k1", "Af=2"),
            ("af3q1_deq2_k1", "Af=3"),
            ("af2q1_deq1p5_k1", "deq=1.5"),
            ("af2q1_deq2p5_k1", "deq=2.5"),
        ],
    ),
]

_COLORS = (
    "#1565C0",
    "#C62828",
    "#2E7D32",
    "#6A1B9A",
    "#E65100",
    "#00838F",
    "#455A64",
)
_LINESTYLES = ("-", "--", "-.", ":", (0, (5, 1)), (0, (3, 1, 1, 1)))


def _configure_style() -> None:
    try:
        from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

        configure_matplotlib_chinese()
    except Exception:
        pass


def csv_path_for(post_root: Path, case_id: str, run_slug: str) -> Path:
    return post_root / case_id / run_slug / f"{run_slug}_stress_strain.csv"


def load_curve(csv: Path) -> tuple[list[float], list[float]] | None:
    if not csv.is_file():
        return None
    from scripts.plot_stress_strain import load_csv

    eps, sig = load_csv(str(csv))
    if not eps or not sig:
        return None
    return eps, sig


def _demo_curve(
    *,
    plateau: float,
    dens_eps: float = 0.55,
    n: int = 160,
) -> tuple[list[float], list[float]]:
    """Synthetic engineering curve for layout preview."""
    eps = [i / (n - 1) * 0.80 for i in range(n)]
    sig: list[float] = []
    for e in eps:
        if e < 0.05:
            s = plateau * (e / 0.05) * 0.35
        elif e < dens_eps:
            s = plateau * (0.85 + 0.15 * math.sin(8 * e))
        else:
            t = (e - dens_eps) / max(0.80 - dens_eps, 1e-6)
            s = plateau * (1.0 + 2.2 * t * t)
        sig.append(max(0.0, s))
    return eps, sig


def _demo_curves_for_case(case_id: str) -> tuple[list[float], list[float]] | None:
    meta = {
        "af2q0_deq2_k1": (0.018, 0.50),
        "af2q0p5_deq2_k1": (0.022, 0.48),
        "af2q1_deq2_k1": (0.028, 0.45),
        "af2q1p5_deq2_k1": (0.024, 0.47),
        "af2q0_deq2_k2": (0.021, 0.52),
        "af2q0p5_deq2_k2": (0.026, 0.50),
        "af2q1_deq2_k2": (0.032, 0.46),
        "af2q1p5_deq2_k2": (0.027, 0.48),
        "af2q0_deq2_k1p5": (0.019, 0.51),
        "af2q0p5_deq2_k1p5": (0.024, 0.49),
        "af2q1_deq2_k1p5": (0.030, 0.455),
        "af2q1p5_deq2_k1p5": (0.025, 0.475),
        "af1q1_deq2_k1": (0.020, 0.48),
        "af3q1_deq2_k1": (0.034, 0.44),
        "af2q1_deq1p5_k1": (0.016, 0.50),
        "af2q1_deq2p5_k1": (0.036, 0.43),
    }
    # Mirror known gaps so the missing annotation is visible in DEMO
    if case_id in ("af2q1_deq2_k1", "af2q1_deq1p5_k1"):
        return None
    plateau, dens = meta.get(case_id, (0.02, 0.5))
    return _demo_curve(plateau=plateau, dens_eps=dens)


def collect_curves(
    post_root: Path,
    run_slug: str,
    *,
    demo: bool,
) -> dict[str, tuple[list[float], list[float]] | None]:
    needed: set[str] = set()
    for _, series in PANELS:
        for cid, _ in series:
            needed.add(cid)
    out: dict[str, tuple[list[float], list[float]] | None] = {}
    for cid in sorted(needed):
        if demo:
            out[cid] = _demo_curves_for_case(cid)
        else:
            out[cid] = load_curve(csv_path_for(post_root, cid, run_slug))
    return out


def _panel_ylim(curves: list[tuple[list[float], list[float]]]) -> tuple[float, float]:
    ymax = 0.01
    for _, sig in curves:
        if sig:
            ymax = max(ymax, max(sig))
    return 0.0, ymax * 1.12


def plot_compare(
    curves: dict[str, tuple[list[float], list[float]] | None],
    out_path: Path,
    *,
    demo: bool,
    global_ylim: bool,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()

    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.2), dpi=150, sharex=True)
    axes_flat = list(axes.ravel())

    all_sig: list[float] = []
    if global_ylim:
        for c in curves.values():
            if c and c[1]:
                all_sig.extend(c[1])
    g_ymax = (max(all_sig) * 1.12) if all_sig else 0.04

    for ax, (title, series) in zip(axes_flat, PANELS):
        plotted: list[tuple[list[float], list[float]]] = []
        # Keep legend order; missing cases get a legend entry but no curve.
        for i, (cid, label) in enumerate(series):
            data = curves.get(cid)
            color = _COLORS[i % len(_COLORS)]
            ls = _LINESTYLES[i % len(_LINESTYLES)]
            if not data:
                ax.plot([], [], color=color, ls=ls, lw=1.7, label=f"{label} (n/a)")
                continue
            eps, sig = data
            ax.plot(eps, sig, color=color, ls=ls, lw=1.7, label=label)
            plotted.append((eps, sig))

        ax.set_title(title, fontsize=11, pad=6)
        ax.set_xlabel("Engineering strain")
        ax.set_ylabel("Engineering stress (MPa)")
        ax.grid(True, alpha=0.35)
        ax.set_xlim(0.0, 0.80)
        if plotted:
            if global_ylim:
                ax.set_ylim(0.0, g_ymax)
            else:
                y0, y1 = _panel_ylim(plotted)
                ax.set_ylim(y0, y1)
        else:
            ax.set_ylim(0.0, 0.04)
        ax.legend(loc="upper left", fontsize=8, framealpha=0.9)

    tag = (
        "DEMO (synthetic curves)"
        if demo
        else "Abaqus CAE C3D4 · 0.6 mm · 80% · 5 mm/min · Neo-Hooke"
    )
    fig.suptitle(f"批量构型 CAE 压缩对比  ·  {tag}", fontsize=13, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def write_summary_json(
    curves: dict[str, tuple[list[float], list[float]] | None],
    out_json: Path,
    *,
    demo: bool,
) -> None:
    rows: list[dict[str, Any]] = []
    for cid, data in sorted(curves.items()):
        if not data:
            rows.append({"case_id": cid, "available": False})
            continue
        eps, sig = data
        peak_i = max(range(len(sig)), key=lambda i: sig[i])

        def _at(target: float, e=eps, s=sig) -> float | None:
            for ee, ss in zip(e, s):
                if ee >= target:
                    return ss
            return None

        rows.append(
            {
                "case_id": cid,
                "available": True,
                "n_points": len(eps),
                "peak_stress_MPa": sig[peak_i],
                "peak_strain": eps[peak_i],
                "stress_at_0.2": _at(0.2),
                "stress_at_0.4": _at(0.4),
            }
        )
    payload = {"demo": demo, "run_slug": RUN_SLUG, "cases": rows}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="批量构型 CAE 2×3 stress-strain compare")
    ap.add_argument("--demo", action="store_true", help="Synthetic curves for layout preview")
    ap.add_argument("--post-root", type=str, default=str(DEFAULT_POST))
    ap.add_argument("--run-slug", type=str, default=RUN_SLUG)
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    ap.add_argument(
        "--global-ylim",
        action="store_true",
        help="Share y-axis max across all panels (default: per-panel)",
    )
    args = ap.parse_args()

    post_root = Path(args.post_root)
    out_path = Path(args.out)
    if args.demo and out_path == DEFAULT_OUT:
        out_path = REPORTS_ROOT / BATCH_NAME / "batch_cae_stress_strain_compare_DEMO.png"

    curves = collect_curves(post_root, args.run_slug, demo=args.demo)
    n_ok = sum(1 for v in curves.values() if v)
    n_miss = sum(1 for v in curves.values() if not v)
    print(f"curves available={n_ok} missing={n_miss} demo={args.demo}")

    saved = plot_compare(
        curves,
        out_path,
        demo=args.demo,
        global_ylim=bool(args.global_ylim),
    )
    summary = saved.with_suffix(".json")
    write_summary_json(curves, summary, demo=args.demo)
    print("Saved:", saved)
    print("Summary:", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
