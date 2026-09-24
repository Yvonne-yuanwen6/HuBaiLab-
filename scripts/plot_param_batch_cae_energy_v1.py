#!/usr/bin/env python3
"""param_batch CAE 吸能指标表（不再出图）。

复用 src.postprocess.energy_absorption / densification（Hu & Bai §3.3）：
  Wv(ε)=∫σdε [J/cm³]
  η=Wv/σ*（σ*=截至当前的峰值应力）
  SEA=Wv/ρa（ρa=实体体积/包络体积，来自 CAD QC）
  εd=效率法致密化起点

只写 output/reports/param_batch/compare_cae_energy_v1/energy_metrics.csv / .json
（含 U@0.6 对照列）。图由
  scripts/plot_param_batch_energy_sweeps.py
  scripts/plot_param_batch_energy_decisions.py
生成。

Usage:
  py -3 scripts/plot_param_batch_cae_energy_v1.py
"""
from __future__ import annotations

import argparse
import csv
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
from src.postprocess.energy_absorption import analyze_energy_absorption, cumulative_volumetric_energy

from scripts.plot_param_batch_cae_compare import PANELS
from scripts.plot_param_batch_cae_compare_v2 import (
    COMPLETE_EMIN,
    NEAR_EMIN,
    STATUS_COLOR,
    STATUS_LABEL,
    _configure_style,
    classify_status,
    csv_path_for,
    load_batch_cases,
    load_curve,
    trapz_energy,
)

RUN_SLUG = "cae_tet0p6mm80_5mmin_paperbox"
BATCH_NAME = "param_batch"
DEFAULT_POST = PROJECT_ROOT / "output" / "post" / BATCH_NAME
DEFAULT_CAD = PROJECT_ROOT / "output" / "cad" / BATCH_NAME
DEFAULT_INDEX = DEFAULT_CAD / "_batch_index.json"
DEFAULT_OUT = REPORTS_ROOT / BATCH_NAME / "compare_cae_energy_v1"

# High-contrast palette (Wong-like + extras) — pair with linestyle, not color alone
PALETTE = (
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # bluish green
    "#CC79A7",  # reddish purple
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#000000",  # black
    "#882255",  # wine
    "#44AA99",  # teal
    "#117733",  # green
    "#AA4499",  # purple
    "#661100",  # brown
)

# Distinct dash patterns (matplotlib linestyle)
LINESTYLES: tuple = (
    "-",
    "--",
    "-.",
    ":",
    (0, (5, 1)),
    (0, (3, 1, 1, 1)),
    (0, (1, 1)),
    (0, (5, 1, 1, 1, 1, 1)),
    (0, (8, 2)),
    (0, (2, 1)),
    (0, (4, 1, 1, 1)),
    (0, (6, 2, 2, 2)),
)

MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*", "<", ">", "h", "8")

Q_COLOR = {
    0.0: "#0072B2",
    0.5: "#009E73",
    1.0: "#D55E00",
    1.5: "#CC79A7",
}
K_MARKER = {1.0: "o", 1.5: "s", 2.0: "D"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def relative_density_from_qc(cad_root: Path, case_id: str) -> float | None:
    """ρa = V_solid / V_envelope from CAD QC (prefer array bbox; fallback 80³ mm envelope)."""
    qc_path = cad_root / case_id / f"{case_id}_qc.json"
    if not qc_path.is_file():
        return None
    try:
        d = _read_json(qc_path)
        qc = d.get("qc") or {}
        arr = qc.get("array")
        v_solid = None
        v_box = None
        if isinstance(arr, dict):
            if arr.get("mass_mm3") is not None:
                v_solid = float(arr["mass_mm3"])
            bb = arr.get("bbox_mm")
            if isinstance(bb, dict):
                v_box = (
                    (bb["x"][1] - bb["x"][0])
                    * (bb["y"][1] - bb["y"][0])
                    * (bb["z"][1] - bb["z"][0])
                )
        if v_solid is None and qc.get("mass_mm3") is not None:
            v_solid = float(qc["mass_mm3"])
        if v_solid is None:
            uc = qc.get("unitcell") or {}
            if uc.get("mass_mm3") is not None:
                v_solid = float(uc["mass_mm3"]) * 64.0  # 4×4×4
        if v_box is None or v_box <= 0:
            # Nominal 4×4×4 with L=20 mm → 80 mm cube (slightly under true bbox)
            v_box = 80.0 ** 3
        if v_solid is None or v_solid <= 0 or v_box <= 0:
            return None
        return v_solid / v_box
    except Exception:
        return None


def build_energy_rows(
    cases: list[dict[str, Any]],
    post_root: Path,
    cad_root: Path,
    run_slug: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meta in cases:
        cid = meta["case_id"]
        path = csv_path_for(post_root, cid, run_slug)
        curve = load_curve(path)
        rho = relative_density_from_qc(cad_root, cid)
        row: dict[str, Any] = {
            **meta,
            "csv": str(path) if path.is_file() else None,
            "rho_a": rho,
            "status": "missing",
            "rank_eligible": False,
            "emax": None,
            "n_points": None,
            "ed": None,
            "sigma_at_ed": None,
            "sigma_max_to_ed": None,
            "Wv_ed": None,
            "SEA_ed": None,
            "eta_max": None,
            "U_0p6": None,
            "_curve": None,
            "_analysis": None,
        }
        if not curve:
            rows.append(row)
            continue
        eps, sig = curve
        emax = eps[-1]
        status = classify_status(emax)
        row.update(
            {
                "status": status,
                "rank_eligible": status in ("complete", "near_complete"),
                "emax": emax,
                "n_points": len(eps),
                "U_0p6": trapz_energy(eps, sig, 0.6),
                "_curve": curve,
            }
        )
        if rho is None or not math.isfinite(rho) or rho <= 0:
            # still allow Wv without SEA
            rho_use = 1.0
            rho_ok = False
        else:
            rho_use = rho
            rho_ok = True
        try:
            an = analyze_energy_absorption(eps, sig, relative_density=rho_use)
        except Exception:
            rows.append(row)
            continue
        ed = float(an["densification"]["densification_strain"])
        if not math.isfinite(ed):
            rows.append(row)
            continue
        # index at / just below ed
        ed_idx = max(range(len(eps)), key=lambda i: eps[i] if eps[i] <= ed + 1e-12 else -1.0)
        sigma_max_to_ed = max(sig[: ed_idx + 1]) if ed_idx >= 0 else None
        eta = an["eta"]
        eta_max = max(eta) if eta else None
        row.update(
            {
                "ed": ed,
                "sigma_at_ed": float(an["densification"]["densification_stress_MPa"]),
                "sigma_max_to_ed": float(sigma_max_to_ed) if sigma_max_to_ed is not None else None,
                "Wv_ed": float(an["Wv_at_densification_J_cm3"]),
                "SEA_ed": float(an["SEA_at_densification"]) if rho_ok else None,
                "eta_max": float(eta_max) if eta_max is not None else None,
                "_analysis": an,
                "rho_ok": rho_ok,
            }
        )
        # partial: keep curves for overlay but wipe rank metrics used in bars/scatter
        if not row["rank_eligible"]:
            # keep ed/eta for diagnostics on partial if curve long enough for densification
            pass
        rows.append(row)
    return rows


def write_metrics(rows: list[dict[str, Any]], out_dir: Path) -> None:
    keys = [
        "case_id",
        "Af",
        "Q",
        "deq_mm",
        "k",
        "status",
        "rank_eligible",
        "rho_a",
        "emax",
        "n_points",
        "ed",
        "sigma_at_ed",
        "sigma_max_to_ed",
        "Wv_ed",
        "SEA_ed",
        "eta_max",
        "U_0p6",
        "csv",
    ]
    clean = [{k: r.get(k) for k in keys} for r in rows]
    (out_dir / "energy_metrics.json").write_text(
        json.dumps(
            {
                "run_slug": RUN_SLUG,
                "notes": {
                    "Wv": "∫σ dε to εd [J/cm³]; σ in MPa",
                    "eta": "Wv/σ* (Hu & Bai Eq.3.4); σ*=running peak stress",
                    "SEA": "Wv/ρa (Eq.3.3); ρa=V_solid/V_bbox from CAD QC",
                    "ed": "densification onset via efficiency method",
                    "U_0p6": "fixed-strain control ∫σdε to 0.6 (None if short)",
                    "rank_eligible": "complete or near_complete only for bars/scatter ranking",
                },
                "cases": clean,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with (out_dir / "energy_metrics.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in clean:
            w.writerow(r)


def _style_for(
    row: dict[str, Any], i: int, *, with_markers: bool = False
) -> dict[str, Any]:
    """Color + linestyle (+ optional marker) — do not rely on color alone."""
    color = PALETTE[i % len(PALETTE)]
    ls = LINESTYLES[i % len(LINESTYLES)]
    marker = MARKERS[i % len(MARKERS)]
    st = row["status"]
    base = row.get("_label", row["case_id"])
    if st == "partial":
        lab = f"{base} (半截)"
        lw = 1.6
    elif st == "near_complete":
        lab = f"{base}*"
        lw = 2.0
    else:
        lab = base
        lw = 2.0
    return {
        "color": color,
        "ls": ls,
        "lw": lw,
        "marker": marker if with_markers else None,
        "key_marker": marker,  # always keep for εd key points
        "label": lab,
    }


def _plot_curve(ax, xs, ys, style: dict[str, Any]) -> None:
    """Curve identity = color + linestyle only (no mid-curve dots, so εd stays clear)."""
    ax.plot(
        xs,
        ys,
        color=style["color"],
        ls=style["ls"],
        lw=style["lw"],
        label=style["label"],
        solid_capstyle="round",
    )


def _mark_keypoint(
    ax,
    x: float,
    y: float,
    style: dict[str, Any],
    *,
    size: float = 110,
) -> None:
    """High-visibility εd (or other) key marker: dark halo + white rim + filled face."""
    m = style.get("key_marker") or style.get("marker") or "o"
    # outer halo
    ax.scatter(
        [x],
        [y],
        s=size * 1.55,
        marker=m,
        facecolors="none",
        edgecolors="#111111",
        linewidths=2.4,
        zorder=6,
    )
    # filled core
    ax.scatter(
        [x],
        [y],
        s=size,
        marker=m,
        facecolors=style["color"],
        edgecolors="white",
        linewidths=1.6,
        zorder=7,
    )


def plot_ss_shaded(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()
    by_id = {r["case_id"]: r for r in rows}
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.4), dpi=150, sharex=True)
    for ax, (title, series) in zip(axes.ravel(), PANELS):
        ymax = 0.01
        any_plot = False
        for i, (cid, label) in enumerate(series):
            r = by_id.get(cid)
            if not r or not r.get("_curve"):
                ax.plot(
                    [],
                    [],
                    color=PALETTE[i % len(PALETTE)],
                    ls=LINESTYLES[i % len(LINESTYLES)],
                    label=f"{label} (n/a)",
                )
                continue
            eps, sig = r["_curve"]
            style = _style_for({**r, "_label": label}, i, with_markers=False)
            _plot_curve(ax, eps, sig, style)
            ed = r.get("ed")
            if ed is not None and math.isfinite(ed) and r["rank_eligible"]:
                xs = [e for e in eps if e <= ed]
                ys = sig[: len(xs)]
                if len(xs) >= 2:
                    ax.fill_between(xs, ys, color=style["color"], alpha=0.12, linewidth=0)
                # key point on curve at εd
                y_ed = r.get("sigma_at_ed")
                if y_ed is None and xs:
                    y_ed = ys[-1]
                if y_ed is not None:
                    _mark_keypoint(ax, float(ed), float(y_ed), style, size=95)
            any_plot = True
            ymax = max(ymax, max(sig))
        ax.set_title(title, fontsize=11, pad=6)
        ax.set_xlabel("工程应变 ε")
        ax.set_ylabel("工程应力 (MPa)")
        ax.set_xlim(0, 0.8)
        ax.set_ylim(0, ymax * 1.12 if any_plot else 0.04)
        ax.grid(True, alpha=0.35)
        ax.legend(loc="upper left", fontsize=7.5, framealpha=0.9)
    fig.suptitle(
        "A1 · 应力–应变 + 吸能阴影（线型区分曲线；大标记=εd 关键点）",
        fontsize=12.5,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_w_vs_strain(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    _configure_style()
    fig, ax = plt.subplots(figsize=(11.2, 6.4), dpi=150)
    style_i = 0
    for r in rows:
        if not r.get("_curve"):
            continue
        eps, sig = r["_curve"]
        wv = cumulative_volumetric_energy(eps, sig)
        lab = r["case_id"]
        if r["status"] == "partial":
            lab += " (半截)"
        elif r["status"] == "near_complete":
            lab += "*"
        style = _style_for({**r, "_label": lab}, style_i, with_markers=False)
        _plot_curve(ax, eps, wv, style)
        ed = r.get("ed")
        if ed is not None and r["rank_eligible"] and math.isfinite(ed):
            w_ed = r.get("Wv_ed")
            if w_ed is not None:
                _mark_keypoint(ax, float(ed), float(w_ed), style, size=120)
        style_i += 1
    ax.set_xlabel("工程应变 ε")
    ax.set_ylabel("累积体积吸能 Wv (J/cm³)")
    ax.set_xlim(0, 0.8)
    ax.grid(True, alpha=0.35)
    handles, labels = ax.get_legend_handles_labels()
    handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="#D55E00",
            markeredgecolor="#111111",
            markeredgewidth=1.4,
            markersize=10,
            linestyle="None",
            label="εd 关键点",
        )
    )
    labels.append("εd 关键点")
    ax.legend(handles, labels, loc="upper left", fontsize=7.2, ncol=2, framealpha=0.92)
    ax.set_title("A2 · 累积吸能 Wv(ε)（颜色+线型；大标记=εd）")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_eta_vs_strain(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    _configure_style()
    fig, ax = plt.subplots(figsize=(11.2, 6.4), dpi=150)
    style_i = 0
    for r in rows:
        an = r.get("_analysis")
        if not an:
            continue
        eps = an["strains"]
        eta = an["eta"]
        lab = r["case_id"]
        if r["status"] == "partial":
            lab += " (半截)"
        elif r["status"] == "near_complete":
            lab += "*"
        style = _style_for({**r, "_label": lab}, style_i, with_markers=False)
        _plot_curve(ax, eps, eta, style)
        ed = r.get("ed")
        if ed is not None and math.isfinite(ed):
            idx = max(range(len(eps)), key=lambda j: eps[j] if eps[j] <= ed + 1e-12 else -1.0)
            _mark_keypoint(ax, float(eps[idx]), float(eta[idx]), style, size=125)
        style_i += 1
    ax.set_xlabel("工程应变 ε")
    ax.set_ylabel("吸能效率 η = Wv / σ*")
    ax.set_xlim(0, 0.8)
    ax.grid(True, alpha=0.35)
    handles, labels = ax.get_legend_handles_labels()
    handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="#D55E00",
            markeredgecolor="#111111",
            markeredgewidth=1.4,
            markersize=10,
            linestyle="None",
            label="εd 关键点",
        )
    )
    labels.append("εd 关键点")
    ax.legend(handles, labels, loc="upper left", fontsize=7.2, ncol=2, framealpha=0.92)
    ax.set_title("A3 · 效率 η(ε)（颜色+线型；大标记=εd 致密化起点）")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_bars(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()
    eligible = [r for r in rows if r["rank_eligible"]]
    panels = [
        ("体积吸能 Wv @ εd (J/cm³)", "Wv_ed"),
        ("比吸能 SEA = Wv/ρa @ εd", "SEA_ed"),
        ("对照：U = ∫σdε 至 ε=0.6 (J/cm³)", "U_0p6"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(14.8, 5.8), dpi=150)
    for ax, (title, key) in zip(axes, panels):
        items = [r for r in eligible if r.get(key) is not None]
        items.sort(key=lambda r: float(r[key]), reverse=True)
        if not items:
            ax.set_title(title)
            ax.text(0.5, 0.5, "无数据", ha="center", va="center", transform=ax.transAxes)
            continue
        labels = [
            r["case_id"] + ("*" if r["status"] == "near_complete" else "") for r in items
        ]
        vals = [float(r[key]) for r in items]
        colors = [
            STATUS_COLOR["near_complete"] if r["status"] == "near_complete" else "#1565C0"
            for r in items
        ]
        y = list(range(len(items)))
        ax.barh(y, vals, color=colors, height=0.72)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8, fontfamily="monospace")
        ax.invert_yaxis()
        ax.set_title(title, fontsize=10)
        ax.grid(True, axis="x", alpha=0.35)
        ax.set_xlim(0, max(vals) * 1.28)
        for yi, v in zip(y, vals):
            ax.text(v, yi, f"  {v:.4g}", va="center", fontsize=8)
    fig.suptitle(
        "B1 · READY 吸能排序（仅完整+近完整；半截不进）  ·  * = 近完整",
        fontsize=12.5,
        y=0.98,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_scatter(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    _configure_style()
    fig, ax = plt.subplots(figsize=(8.8, 6.6), dpi=150)
    eligible = [
        r
        for r in rows
        if r["rank_eligible"] and r.get("SEA_ed") is not None and r.get("sigma_max_to_ed") is not None
    ]
    for r in eligible:
        q = float(r["Q"])
        k = float(r["k"])
        color = Q_COLOR.get(q, "#455A64")
        marker = K_MARKER.get(k, "o")
        ax.scatter(
            r["sigma_max_to_ed"],
            r["SEA_ed"],
            c=color,
            marker=marker,
            s=70,
            zorder=3,
            edgecolors="white",
            linewidths=0.6,
        )
        ax.annotate(
            r["case_id"].replace("_deq2", "").replace("_deq1p5", "_d1.5"),
            (r["sigma_max_to_ed"], r["SEA_ed"]),
            textcoords="offset points",
            xytext=(5, 4),
            fontsize=7,
        )
    ax.set_xlabel("至 εd 的最大应力 σ_max (MPa)")
    ax.set_ylabel("SEA @ εd  (= Wv/ρa)")
    ax.grid(True, alpha=0.35)
    ax.set_title("B2 · 理想吸能器视角：高 SEA、低 σ_max（左上更优）")
    # legends
    q_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=8, label=f"Q={q:g}")
        for q, c in Q_COLOR.items()
    ]
    k_handles = [
        Line2D(
            [0],
            [0],
            marker=m,
            color="w",
            markerfacecolor="#455A64",
            markersize=8,
            label=f"k={k:g}",
        )
        for k, m in K_MARKER.items()
    ]
    leg1 = ax.legend(handles=q_handles, loc="upper right", title="周期 Q", fontsize=8)
    ax.add_artist(leg1)
    ax.legend(handles=k_handles, loc="lower right", title="截面 κ", fontsize=8)
    # guide arrow annotation
    if eligible:
        ax.annotate(
            "更优 →",
            xy=(0.02, 0.98),
            xycoords="axes fraction",
            ha="left",
            va="top",
            fontsize=9,
            color="#616161",
        )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _qk_grid(
    rows: list[dict[str, Any]], key: str
) -> tuple[list[float], list[float], list[list[float | None]], list[list[str]]]:
    q_vals = [0.0, 0.5, 1.0, 1.5]
    k_vals = [1.0, 1.5, 2.0]
    by = {}
    for r in rows:
        if abs(r["Af"] - 2.0) > 1e-9 or abs(r["deq_mm"] - 2.0) > 1e-9:
            continue
        by[(r["Q"], r["k"])] = r
    z: list[list[float | None]] = []
    annot: list[list[str]] = []
    for q in q_vals:
        zr: list[float | None] = []
        ar: list[str] = []
        for k in k_vals:
            r = by.get((q, k))
            if not r or r["status"] == "missing":
                zr.append(None)
                ar.append("—")
                continue
            if not r["rank_eligible"]:
                zr.append(None)
                ar.append(f"半截\n({r['emax']:.2f})")
                continue
            val = r.get(key)
            if val is None or (isinstance(val, float) and not math.isfinite(val)):
                zr.append(None)
                ar.append("—")
                continue
            zr.append(float(val))
            if key == "ed":
                ar.append(f"{val:.3f}")
            elif key == "eta_max":
                ar.append(f"{val:.3f}")
            else:
                ar.append(f"{val:.4g}")
        z.append(zr)
        annot.append(ar)
    return q_vals, k_vals, z, annot


def plot_qk_heatmaps(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _configure_style()
    panels = [
        ("Wv @ εd (J/cm³)", "Wv_ed"),
        ("SEA @ εd", "SEA_ed"),
        ("εd（效率法）", "ed"),
        ("η_max", "eta_max"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 9.0), dpi=150)
    for ax, (title, key) in zip(axes.ravel(), panels):
        q_vals, k_vals, z, annot = _qk_grid(rows, key)
        arr = np.array([[(np.nan if v is None else v) for v in row] for row in z], dtype=float)
        cmap = plt.cm.YlGnBu.copy()
        cmap.set_bad("#EEEEEE")
        im = ax.imshow(arr, cmap=cmap, aspect="auto")
        ax.set_xticks(range(len(k_vals)))
        ax.set_xticklabels([f"k={k:g}" for k in k_vals])
        ax.set_yticks(range(len(q_vals)))
        ax.set_yticklabels([f"Q={q:g}" for q in q_vals])
        ax.set_title(title, fontsize=11)
        finite = arr[np.isfinite(arr)]
        thr = float(np.nanpercentile(finite, 55)) if finite.size else 0.0
        for i in range(len(q_vals)):
            for j in range(len(k_vals)):
                val = z[i][j]
                color = "#FAFAFA" if val is not None and val >= thr else "#212121"
                ax.text(j, i, annot[i][j], ha="center", va="center", fontsize=8, color=color)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle(
        "B3 · 组 A（Af=2, deq=2）Q×κ 吸能指标热图\n灰格=缺失/半截不参排",
        fontsize=12,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="param_batch CAE 吸能指标表")
    ap.add_argument("--post-root", type=str, default=str(DEFAULT_POST))
    ap.add_argument("--cad-root", type=str, default=str(DEFAULT_CAD))
    ap.add_argument("--index", type=str, default=str(DEFAULT_INDEX))
    ap.add_argument("--run-slug", type=str, default=RUN_SLUG)
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = load_batch_cases(Path(args.index))
    rows = build_energy_rows(cases, Path(args.post_root), Path(args.cad_root), args.run_slug)
    write_metrics(rows, out_dir)

    n = {st: sum(1 for r in rows if r["status"] == st) for st in STATUS_LABEL}
    print(f"status counts: {n}")
    print(f"Wrote energy metrics → {out_dir}")
    for name in ("energy_metrics.csv", "energy_metrics.json"):
        p = out_dir / name
        print(f"  {'OK' if p.is_file() else 'MISSING':7s} {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
