#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 energy decision figures from compare_cae_energy_v1/energy_metrics.csv.

Does not recompute Hu & Bai metrics. Rank uses rank_eligible (complete or near_complete).

  py -3 scripts/plot_param_batch_energy_decisions.py

Outputs (param_batch/ and the batch report dir):
  energy_bars_by_axis.png
  energy_pareto_deq2.png
  energy_pareto_deq.png
  energy_heatmap_Qk.png
  energy_heatmap_AfQ.png
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_param_batch_cae_compare_v2 import BATCH_NAME  # noqa: E402
from src.paths import REPORTS_ROOT  # noqa: E402

_Q_COLOR = {
    0.0: "#0072B2",
    0.5: "#009E73",
    1.0: "#D55E00",
    1.5: "#CC79A7",
}
_K_MARKER = {1.0: "o", 1.5: "s", 2.0: "D"}
_AF_COLORS = ("#1565C0", "#C62828", "#2E7D32", "#6A1B9A", "#E65100", "#00838F")
_DEQ_COLOR = {1.5: "#6A1B9A", 2.0: "#E65100", 2.5: "#1565C0"}

_METRICS = (
    ("Wv_ed", r"$W_v$ @ $\varepsilon_d$ (J/cm$^3$)"),
    ("SEA_ed", r"比吸能 SEA = $W_v/\rho_a$ @ $\varepsilon_d$"),
    ("eta_max", r"$\eta_{\mathrm{max}}$"),
)
_HEAT = (
    ("Wv_ed", r"$W_v$ @ $\varepsilon_d$"),
    ("SEA_ed", r"比吸能 SEA @ $\varepsilon_d$"),
    ("ed", r"$\varepsilon_d$"),
    ("eta_max", r"$\eta_{\mathrm{max}}$"),
)


def _configure_style() -> None:
    try:
        from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

        configure_matplotlib_chinese()
    except Exception:
        pass


def _close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) < 1e-6


def _f(text: str | None) -> float | None:
    if text is None or text == "":
        return None
    try:
        v = float(text)
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    return v


def load_rows() -> list[dict[str, Any]]:
    path = REPORTS_ROOT / BATCH_NAME / "compare_cae_energy_v1" / "energy_metrics.csv"
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            if raw.get("case_id", "").endswith("_L10"):
                continue
            row: dict[str, Any] = {
                "case_id": raw["case_id"],
                "Af": _f(raw["Af"]),
                "Q": _f(raw["Q"]),
                "deq_mm": _f(raw["deq_mm"]),
                "k": _f(raw["k"]),
                "status": raw["status"],
                "rank_eligible": raw["rank_eligible"] == "True",
            }
            for key in (
                "rho_a",
                "ed",
                "sigma_max_to_ed",
                "Wv_ed",
                "SEA_ed",
                "eta_max",
            ):
                row[key] = _f(raw.get(key))
            rows.append(row)
    return rows


def _eligible(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["rank_eligible"] and r["Wv_ed"] is not None]


def _match(
    rows: list[dict[str, Any]],
    *,
    af: float | None = None,
    q: float | None = None,
    deq: float | None = None,
    k: float | None = None,
) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if af is not None and not _close(r["Af"], af):
            continue
        if q is not None and not _close(r["Q"], q):
            continue
        if deq is not None and not _close(r["deq_mm"], deq):
            continue
        if k is not None and not _close(r["k"], k):
            continue
        out.append(r)
    return out


def _label(r: dict[str, Any]) -> str:
    star = "*" if r["status"] == "near_complete" else ""
    return f"{r['case_id']}{star}"


def _pareto(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Minimize sigma_max, maximize SEA."""
    front: list[dict[str, Any]] = []
    for p in points:
        dominated = False
        for q in points:
            if q is p:
                continue
            better_or_eq = q["sigma_max_to_ed"] <= p["sigma_max_to_ed"] and q["SEA_ed"] >= p["SEA_ed"]
            strictly = q["sigma_max_to_ed"] < p["sigma_max_to_ed"] or q["SEA_ed"] > p["SEA_ed"]
            if better_or_eq and strictly:
                dominated = True
                break
        if not dominated:
            front.append(p)
    front.sort(key=lambda r: r["sigma_max_to_ed"])
    return front


def _save(fig, out_name: str) -> Path:
    primary = REPORTS_ROOT / "param_batch" / out_name
    primary.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(primary, dpi=150)
    mirror = REPORTS_ROOT / BATCH_NAME / out_name
    mirror.parent.mkdir(parents=True, exist_ok=True)
    if mirror.resolve() != primary.resolve():
        shutil.copy2(primary, mirror)
    print("Saved:", primary)
    return primary


def plot_bars(rows: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _configure_style()
    af_rows = sorted(_match(_eligible(rows), q=1.0, deq=2.0, k=1.0), key=lambda r: r["Af"])
    q_rows = sorted(_match(_eligible(rows), af=2.0, deq=2.0, k=1.0), key=lambda r: r["Q"])
    k_pool = _match(_eligible(rows), af=2.0, deq=2.0)
    qs = [0.0, 0.5, 1.0, 1.5]
    ks = [1.0, 1.5, 2.0]

    fig, axes = plt.subplots(3, 3, figsize=(12.8, 9.4), dpi=150)
    slices = (
        (r"Af 扫描 · $Q=1$, deq=2, $\kappa=1$", "af", af_rows),
        (r"Q 扫描 · $Af=2$, deq=2, $\kappa=1$", "q", q_rows),
        (r"$\kappa$ 扫描 · $Af=2$, deq=2", "k", k_pool),
    )
    for r_i, (row_title, kind, data) in enumerate(slices):
        for c_i, (key, ylab) in enumerate(_METRICS):
            ax = axes[r_i][c_i]
            if kind != "k":
                labels = [f"{('Af' if kind == 'af' else 'Q')}={v:g}" for v in (
                    [d["Af"] if kind == "af" else d["Q"] for d in data]
                )]
                # rebuild labels cleanly
                if kind == "af":
                    labels = [f"Af={d['Af']:g}" for d in data]
                    colors = [_AF_COLORS[i % len(_AF_COLORS)] for i in range(len(data))]
                else:
                    labels = [f"Q={d['Q']:g}" for d in data]
                    colors = [_Q_COLOR.get(d["Q"], "#455A64") for d in data]
                vals = [d[key] for d in data]
                x = np.arange(len(vals))
                ax.bar(x, vals, color=colors, width=0.72)
                ax.set_xticks(x)
                ax.set_xticklabels(labels, fontsize=8)
            else:
                width = 0.18
                x = np.arange(len(ks))
                for j, q in enumerate(qs):
                    vals = []
                    for k in ks:
                        hit = [
                            d
                            for d in data
                            if _close(d["Q"], q) and _close(d["k"], k) and d[key] is not None
                        ]
                        vals.append(hit[0][key] if hit else np.nan)
                    offset = (j - 1.5) * width
                    ax.bar(
                        x + offset,
                        vals,
                        width=width,
                        color=_Q_COLOR[q],
                        label=f"Q={q:g}" if c_i == 0 else None,
                    )
                ax.set_xticks(x)
                ax.set_xticklabels([rf"$\kappa={k:g}$" for k in ks], fontsize=8)
                if c_i == 0:
                    ax.legend(frameon=False, fontsize=7, ncol=2)
            finite = [v for v in (
                [d[key] for d in data] if kind != "k" else [d[key] for d in data if d[key] is not None]
            ) if v is not None]
            if finite:
                ax.set_ylim(0, max(finite) * 1.18)
            ax.set_ylabel(ylab, fontsize=8)
            ax.grid(True, axis="y", alpha=0.3)
            if c_i == 1:
                ax.set_title(row_title, fontsize=10)
    fig.suptitle(
        r"按扫描轴的吸能指标  ·  * 为近完整（$Q=1,\kappa=1.5$ 已纳入）" + "\n"
        r"比吸能 SEA 用 CAD 质检 的 $\rho_a$（指标表）  ·  $Q=1,\kappa=2$ 缺失",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    _save(fig, "energy_bars_by_axis.png")
    plt.close(fig)


def plot_pareto_deq2(rows: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    _configure_style()
    pts = [
        r
        for r in _match(_eligible(rows), deq=2.0)
        if r["SEA_ed"] is not None and r["sigma_max_to_ed"] is not None
    ]
    front = _pareto(pts)
    fig, ax = plt.subplots(figsize=(8.6, 6.5), dpi=150)
    for r in pts:
        ax.scatter(
            r["sigma_max_to_ed"],
            r["SEA_ed"],
            c=_Q_COLOR.get(r["Q"], "#455A64"),
            marker=_K_MARKER.get(r["k"], "o"),
            s=36 + 28 * float(r["Af"]),
            zorder=3,
            edgecolors="white",
            linewidths=0.6,
        )
    if len(front) >= 2:
        ax.plot(
            [r["sigma_max_to_ed"] for r in front],
            [r["SEA_ed"] for r in front],
            color="#9E9E9E",
            lw=1.0,
            ls="--",
            zorder=2,
        )
    for r in front:
        short = r["case_id"].replace("_deq2", "")
        if r["status"] == "near_complete":
            short += "*"
        ax.annotate(
            short,
            (r["sigma_max_to_ed"], r["SEA_ed"]),
            textcoords="offset points",
            xytext=(5, 4),
            fontsize=7,
        )
    ax.set_xlabel(r"至 $\varepsilon_d$ 的 $\sigma_{\mathrm{max}}$ (MPa)")
    ax.set_ylabel(r"比吸能 SEA @ $\varepsilon_d$")
    ax.set_title(r"deq=2 帕累托  ·  左上更优  ·  虚线=非支配前沿")
    ax.grid(True, alpha=0.3)
    q_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=c, markersize=8, label=f"Q={q:g}")
        for q, c in _Q_COLOR.items()
    ]
    k_handles = [
        Line2D(
            [0],
            [0],
            marker=m,
            color="none",
            markerfacecolor="#455A64",
            markersize=8,
            label=f"k={k:g}",
        )
        for k, m in _K_MARKER.items()
    ]
    leg1 = ax.legend(handles=q_handles, loc="upper right", title="Q", fontsize=8, frameon=False)
    ax.add_artist(leg1)
    ax.legend(handles=k_handles, loc="lower right", title=r"$\kappa$  ·  点大小 $\sim Af$", fontsize=8, frameon=False)
    fig.tight_layout()
    _save(fig, "energy_pareto_deq2.png")
    plt.close(fig)


def plot_pareto_deq(rows: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()
    pts = [
        r
        for r in _match(_eligible(rows), af=2.0, q=1.0, k=1.0)
        if r["SEA_ed"] is not None and r["sigma_max_to_ed"] is not None
    ]
    pts.sort(key=lambda r: r["deq_mm"])
    front = _pareto(pts)
    fig, ax = plt.subplots(figsize=(6.6, 5.2), dpi=150)
    for r in pts:
        ax.scatter(
            r["sigma_max_to_ed"],
            r["SEA_ed"],
            c=_DEQ_COLOR.get(r["deq_mm"], "#455A64"),
            s=90,
            zorder=3,
            edgecolors="white",
        )
        ax.annotate(
            f"deq={r['deq_mm']:g}",
            (r["sigma_max_to_ed"], r["SEA_ed"]),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=9,
        )
    if len(front) >= 2:
        ax.plot(
            [r["sigma_max_to_ed"] for r in front],
            [r["SEA_ed"] for r in front],
            color="#9E9E9E",
            lw=1.0,
            ls="--",
            zorder=2,
        )
    ax.set_xlabel(r"至 $\varepsilon_d$ 的 $\sigma_{\mathrm{max}}$ (MPa)")
    ax.set_ylabel(r"比吸能 SEA @ $\varepsilon_d$")
    ax.set_title(r"deq 扫描帕累托 · $Af=2$, $Q=1$, $\kappa=1$" + "\n" + r"左上更优")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    _save(fig, "energy_pareto_deq.png")
    plt.close(fig)


def _heat_grid(
    rows: list[dict[str, Any]],
    y_key: str,
    y_vals: list[float],
    x_key: str,
    x_vals: list[float],
    metric: str,
    fixed: dict[str, float],
) -> tuple[list[list[float | None]], list[list[str]]]:
    z: list[list[float | None]] = []
    annot: list[list[str]] = []
    for yv in y_vals:
        zr: list[float | None] = []
        ar: list[str] = []
        for xv in x_vals:
            kwargs = dict(fixed)
            kwargs[y_key] = yv
            kwargs[x_key] = xv
            # _match uses af/q/deq/k names
            hit = _match(rows, **kwargs)  # type: ignore[arg-type]
            if not hit or not hit[0]["rank_eligible"] or hit[0].get(metric) is None:
                zr.append(None)
                ar.append("-")
            else:
                val = float(hit[0][metric])
                zr.append(val)
                ar.append(f"{val:.3g}")
        z.append(zr)
        annot.append(ar)
    return z, annot


def _draw_heat(
    rows: list[dict[str, Any]],
    *,
    y_name: str,
    y_vals: list[float],
    x_name: str,
    x_vals: list[float],
    fixed: dict[str, float],
    title: str,
    out_name: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _configure_style()
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 8.8), dpi=150)
    key_of = {"Af": "af", "Q": "q", "k": "k", "deq": "deq"}
    for ax, (metric, mtitle) in zip(axes.ravel(), _HEAT):
        z, annot = _heat_grid(
            rows,
            key_of[y_name],
            y_vals,
            key_of[x_name],
            x_vals,
            metric,
            fixed,
        )
        arr = np.array([[np.nan if v is None else v for v in row] for row in z], dtype=float)
        cmap = plt.cm.YlGnBu.copy()
        cmap.set_bad("#E6E6E6")
        im = ax.imshow(arr, cmap=cmap, aspect="auto")
        ax.set_xticks(range(len(x_vals)))
        if x_name == "k":
            ax.set_xticklabels([rf"$\kappa={v:g}$" for v in x_vals], fontsize=8)
        else:
            ax.set_xticklabels([f"{x_name}={v:g}" for v in x_vals], fontsize=8)
        ax.set_yticks(range(len(y_vals)))
        ax.set_yticklabels([f"{y_name}={v:g}" for v in y_vals], fontsize=8)
        ax.set_title(mtitle, fontsize=11)
        finite = arr[np.isfinite(arr)]
        thr = float(np.nanpercentile(finite, 55)) if finite.size else 0.0
        for i in range(len(y_vals)):
            for j in range(len(x_vals)):
                val = z[i][j]
                color = "#FAFAFA" if val is not None and val >= thr else "#212121"
                ax.text(j, i, annot[i][j], ha="center", va="center", fontsize=8, color=color)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle(title, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save(fig, out_name)
    plt.close(fig)


def main() -> int:
    rows = load_rows()
    if not rows:
        print("no rows")
        return 1
    plot_bars(rows)
    plot_pareto_deq2(rows)
    plot_pareto_deq(rows)
    _draw_heat(
        rows,
        y_name="Q",
        y_vals=[0.0, 0.5, 1.0, 1.5],
        x_name="k",
        x_vals=[1.0, 1.5, 2.0],
        fixed={"af": 2.0, "deq": 2.0},
        title=r"$Q\times\kappa$ 吸能  ·  $Af=2$, deq=2  ·  灰格=缺失",
        out_name="energy_heatmap_Qk.png",
    )
    _draw_heat(
        rows,
        y_name="Q",
        y_vals=[0.0, 0.5, 1.0, 1.5],
        x_name="Af",
        x_vals=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        fixed={"k": 1.0, "deq": 2.0},
        title=r"$Af\times Q$ 吸能  ·  $\kappa=1$, deq=2  ·  灰格=未仿真",
        out_name="energy_heatmap_AfQ.png",
    )
    summary = {
        "source": "compare_cae_energy_v1/energy_metrics.csv",
        "n_rows": len(rows),
        "n_rank": len(_eligible(rows)),
    }
    out = REPORTS_ROOT / "param_batch" / "energy_decisions.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    mirror = REPORTS_ROOT / BATCH_NAME / "energy_decisions.json"
    if mirror.resolve() != out.resolve():
        shutil.copy2(out, mirror)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
