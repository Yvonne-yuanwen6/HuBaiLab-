"""Hu & Bai Fig.3.3 standard plot style (thesis experimental reference + sim overlay)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from src.paths import PROJECT_ROOT, REPORTS_ROOT
from src.postprocess.compression_curve import HU_BAI_PAPER_DENSIFICATION_STRAIN

FIG33_TRACED_JSON = PROJECT_ROOT / "data" / "hu_bai_fig33_experiment_traced.json"

# Fig.3.3 series key → HU_BAI_PAPER_DENSIFICATION_STRAIN key
FIG33_SERIES_PAPER_KEY = {
    "bcc": "bcc",
    "af2q05": "q0.5",
    "af2q1": "q1",
    "af2q15": "q1.5",
}

# Annotation offsets (data coords) to reduce label overlap
FIG33_DENSIFICATION_ANNOT = {
    "bcc": (-0.20, 0.007),
    "af2q05": (-0.22, -0.009),
    "af2q1": (-0.18, 0.007),
    "af2q15": (0.06, 0.007),
}

# Simulation overlay keys → legend suffix
SIM_LABEL_SUFFIX = "-仿真"

# Default sim colors (slightly darker / dashed vs experiment)
SIM_COLORS = {
    "bcc": "#0288D1",
    "af2q05": "#0D47A1",
    "af2q1": "#C2185B",
    "af2q15": "#B71C1C",
}

# High-contrast palette for exp/sim overlay (same hue per structure, linestyle distinguishes)
FIG33_OVERLAY_COLORS = {
    "bcc": "#00838F",  # teal
    "af2q05": "#1565C0",  # blue
    "af2q1": "#7B1FA2",  # purple
    "af2q15": "#C62828",  # red
}
FIG33_EXP_LINESTYLE = "-"
FIG33_SIM_LINESTYLE = "--"
FIG33_EXP_LINEWIDTH = 2.2
FIG33_SIM_LINEWIDTH = 2.0

# Multi-variant Q0.5 sweep overlay — high-contrast vs experiment #1565C0
IMPROVE_VARIANT_STYLES: dict[str, dict[str, Any]] = {
    "fig33_v2_el (baseline)": {"color": "#212121", "linestyle": "--", "linewidth": 2.0},
    "fig33_v2_paper": {"color": "#E65100", "linestyle": "-.", "linewidth": 2.0},
    "fig33_v2_ep": {"color": "#2E7D32", "linestyle": (0, (5, 1, 1, 1)), "linewidth": 2.0},
    "paperbox_settle5p": {"color": "#00838F", "linestyle": ":", "linewidth": 2.2},
    "fig33_v2_paper_dt1e4": {"color": "#C62828", "linestyle": (0, (3, 1)), "linewidth": 2.0},
}


def load_fig33_reference() -> dict[str, Any]:
    with open(FIG33_TRACED_JSON, encoding="utf-8") as f:
        return json.load(f)


def configure_matplotlib_chinese() -> None:
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 11,
        }
    )


FIG33_PAPER_YMAX_MPA = 0.04


def _nice_ymax(peak_mpa: float, *, paper_ymax: float = FIG33_PAPER_YMAX_MPA, margin: float = 0.08) -> float:
    """Round up peak stress for overlay plots (keep paper 0.04 when sim fits)."""
    if peak_mpa <= paper_ymax:
        return paper_ymax
    target = peak_mpa * (1.0 + margin)
    step = 0.02 if target <= 0.20 else 0.05
    import math

    return max(paper_ymax, math.ceil(target / step) * step)


def _y_ticks_for_ymax(ymax: float) -> list[float]:
    if ymax <= FIG33_PAPER_YMAX_MPA + 1e-9:
        return [i / 100 for i in range(int(ymax * 100) + 1)]
    step = 0.02 if ymax <= 0.20 else 0.05
    n = int(round(ymax / step))
    return [round(i * step, 4) for i in range(n + 1)]


def set_fig33_ylim(
    ax,
    ax_right,
    ymax: float,
    *,
    ref: dict[str, Any] | None = None,
) -> None:
    """Update Y limits and ticks on both axes (after overlay autoscale)."""
    ref = ref or load_fig33_reference()
    y0 = float(ref["ylim"][0])
    ymax = float(ymax)
    ticks = _y_ticks_for_ymax(ymax)
    ax.set_ylim(y0, ymax)
    ax.set_yticks(ticks)
    if ax_right is not None:
        ax_right.set_ylim(y0, ymax)
        ax_right.set_yticks(ticks)


def autoscale_fig33_ylim_for_overlay(
    ax,
    ax_right,
    stresses: Sequence[Sequence[float]],
    *,
    ref: dict[str, Any] | None = None,
) -> float:
    """Expand Y axis so dashed sim curves are not clipped (paper default is 0.04 MPa)."""
    ref = ref or load_fig33_reference()
    peak = FIG33_PAPER_YMAX_MPA
    for seq in stresses:
        if seq:
            peak = max(peak, max(float(s) for s in seq))
    ymax = _nice_ymax(peak)
    set_fig33_ylim(ax, ax_right, ymax, ref=ref)
    return ymax


def apply_fig33_axes_style(ax, ax_right=None, *, ref: dict[str, Any] | None = None, ymax: float | None = None) -> None:
    """Black boxed axes, thesis tick ranges."""
    ref = ref or load_fig33_reference()
    x0, x1 = ref["xlim"]
    y0, y1 = ref["ylim"]
    if ymax is not None:
        y1 = float(ymax)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xlabel(ref.get("x_label", "应变"))
    ax.set_ylabel(ref.get("y_label", "应力 (MPa)"))

    ax.set_xticks([i / 10 for i in range(int(x1 * 10) + 1)])
    ax.set_yticks(_y_ticks_for_ymax(y1))

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("black")
        spine.set_linewidth(1.2)

    ax.tick_params(direction="in", top=True, right=True, length=4, width=0.8)
    ax.grid(False)

    if ax_right is not None:
        ax_right.set_ylim(y0, y1)
        ax_right.set_yticks(_y_ticks_for_ymax(y1))
        ax_right.set_ylabel(ref.get("y_label", "应力 (MPa)"))
        ax_right.tick_params(direction="in", labelleft=False, labelright=True, length=4, width=0.8)
        for spine in ax_right.spines.values():
            spine.set_visible(True)
            spine.set_color("black")
            spine.set_linewidth(1.2)


def stress_at_strain(points: Sequence[Sequence[float]], strain: float) -> float | None:
    """Linear interpolate stress on digitized curve at given engineering strain."""
    if len(points) < 2:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    if strain < xs[0] or strain > xs[-1]:
        return None
    return float(np.interp(strain, xs, ys))


def paper_densification_for_series(series_key: str, points: Sequence[Sequence[float]]) -> dict[str, float] | None:
    """Paper §3.3.1 εd mapped onto experimental curve (strain from thesis, stress from WPD points)."""
    paper_key = FIG33_SERIES_PAPER_KEY.get(series_key)
    if not paper_key:
        return None
    ed = HU_BAI_PAPER_DENSIFICATION_STRAIN.get(paper_key)
    if ed is None:
        return None
    sd = stress_at_strain(points, ed)
    if sd is None:
        return None
    return {
        "densification_strain_paper": float(ed),
        "densification_stress_MPa": float(sd),
        "densification_marker": [float(ed), float(sd)],
    }


def enrich_fig33_series_densification(series: dict[str, Any], series_key: str) -> dict[str, Any]:
    """Attach paper εd marker to one series dict (in-place friendly)."""
    info = paper_densification_for_series(series_key, series.get("points") or [])
    if not info:
        return series
    out = dict(series)
    out.update(info)
    return out


def enrich_fig33_reference_densification(ref: dict[str, Any]) -> dict[str, Any]:
    """Ensure all series carry paper §3.3.1 densification markers."""
    out = dict(ref)
    series = dict(ref.get("series") or {})
    for key, s in series.items():
        series[key] = enrich_fig33_series_densification(s, key)
    out["series"] = series
    return out


def _interpolate_series_points(points: list[list[float]], n: int = 200) -> tuple[list[float], list[float]]:
    """Smooth anchor points for plotting (PCHIP)."""
    if len(points) < 2:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return xs, ys
    from scipy.interpolate import PchipInterpolator

    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    xi = np.linspace(xs[0], xs[-1], n)
    yi = PchipInterpolator(xs, ys)(xi)
    yi = np.clip(yi, 0.0, None)
    return xi.tolist(), yi.tolist()


def plot_fig33_experiment_series(
    ax,
    ref: dict[str, Any] | None = None,
    *,
    series_key: str = "af2q05",
    linewidth: float = 2.2,
    interpolate: bool = True,
) -> Any:
    """Plot one experimental reference curve (focused overlay, e.g. Q0.5 only)."""
    ref = ref or load_fig33_reference()
    s = ref["series"][series_key]
    pts = s["points"]
    if interpolate and len(pts) >= 3:
        xs, ys = _interpolate_series_points(pts)
    else:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
    return ax.plot(xs, ys, color=s["color"], linewidth=linewidth, label=s["label"], zorder=2)[0]


def plot_fig33_experiment(
    ax,
    ref: dict[str, Any] | None = None,
    *,
    show_densification: bool = False,
    linewidth: float = 1.8,
    interpolate: bool = True,
    color_map: dict[str, str] | None = None,
    linestyle: str | tuple = "-",
) -> list[Any]:
    """Plot hand-traced / digitized experimental reference curves."""
    ref = ref or load_fig33_reference()
    lines = []
    order = ("bcc", "af2q05", "af2q1", "af2q15")
    for key in order:
        s = ref["series"][key]
        pts = s["points"]
        if interpolate and len(pts) >= 3:
            xs, ys = _interpolate_series_points(pts)
        else:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
        color = (color_map or {}).get(key, s["color"])
        (ln,) = ax.plot(
            xs, ys, color=color, linewidth=linewidth, linestyle=linestyle, label=s["label"], zorder=2
        )
        lines.append(ln)

        if show_densification:
            marker_info = s if "densification_marker" in s else enrich_fig33_series_densification(s, key)
            if "densification_marker" not in marker_info:
                continue
            mx, my = marker_info["densification_marker"]
            ed = marker_info.get("densification_strain_paper", mx)
            dx, dy = FIG33_DENSIFICATION_ANNOT.get(key, (-0.18, 0.008))
            ax.plot(mx, my, "o", color=color, markersize=5, markeredgecolor="black", markeredgewidth=0.6, zorder=4)
            ax.axvline(ed, color=color, linestyle=":", alpha=0.35, linewidth=0.9, zorder=1)
            ax.annotate(
                f"致密化点\nεd={ed:.2f}",
                xy=(mx, my),
                xytext=(mx + dx, my + dy),
                fontsize=8,
                ha="left" if dx >= 0 else "right",
                va="bottom" if dy >= 0 else "top",
                arrowprops=dict(arrowstyle="->", color="black", lw=0.8),
            )
    return lines


def plot_fig33_simulation(
    ax,
    strains: Sequence[float],
    stresses: Sequence[float],
    *,
    key: str,
    label: str | None = None,
    ref: dict[str, Any] | None = None,
    color: str | None = None,
    linestyle: str | tuple = "--",
    linewidth: float = 1.6,
    alpha: float = 0.95,
) -> Any:
    """Overlay one simulation curve in Fig.3.3 style."""
    ref = ref or load_fig33_reference()
    exp = ref["series"].get(key, {})
    plot_color = color or SIM_COLORS.get(key, exp.get("color", "#333333"))
    lab = label or (exp.get("label", key).replace("-实验", "") + SIM_LABEL_SUFFIX)
    return ax.plot(
        list(strains),
        list(stresses),
        color=plot_color,
        linestyle=linestyle,
        linewidth=linewidth,
        alpha=alpha,
        label=lab,
        zorder=3,
    )[0]


def create_fig33_figure(
    figsize: tuple[float, float] = (7.2, 5.4),
    *,
    dpi: int = 150,
):
    """Return (fig, ax, ax_right) with Chinese font configured."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    configure_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax_right = ax.twinx()
    apply_fig33_axes_style(ax, ax_right)
    return fig, ax, ax_right


def save_fig33_figure(fig, path: Path | str | None = None) -> Path:
    out = Path(path) if path else REPORTS_ROOT / "hu_bai_fig33_experiment_standard.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=fig.dpi if hasattr(fig, "dpi") else 150, bbox_inches="tight", facecolor="white")
    return out
