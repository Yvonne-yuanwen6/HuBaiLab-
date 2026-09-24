#!/usr/bin/env python3
"""param_batch CAE 压缩对比 P0 图集（不含隔振）。

输出目录默认：output/reports/param_batch/compare_cae_v2/
  00_readiness_matrix.png
  01_cae_curves_refresh.png
  02_cae_Qk_heatmaps.png
  03_cae_metric_bars.png
  metrics_table.csv / metrics_table.json

规则：
  - complete (εmax≥0.78): 实线；进排序/热图全指标
  - near_complete (0.70≤εmax<0.78): 实线+标注；进排序/热图（注）
  - partial (有曲线但 εmax<0.70): 虚线+截断；不进 σ_peak / U 排名；热图仅填已达应变指标
  - missing: n/a / 灰格

Usage:
  py -3 scripts/plot_param_batch_cae_compare_v2.py
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.paths import PROJECT_ROOT, REPORTS_ROOT

RUN_SLUG = "cae_tet0p6mm80_5mmin_paperbox"
BATCH_NAME = "param_batch"
DEFAULT_POST = PROJECT_ROOT / "output" / "post" / BATCH_NAME
DEFAULT_CAD_INDEX = PROJECT_ROOT / "output" / "cad" / BATCH_NAME / "_batch_index.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / BATCH_NAME / "compare_cae_v2"

COMPLETE_EMIN = 0.78
NEAR_EMIN = 0.70

# Reuse panel layout from v1
from scripts.plot_param_batch_cae_compare import PANELS  # noqa: E402

_COLORS = (
    "#1565C0",
    "#C62828",
    "#2E7D32",
    "#6A1B9A",
    "#E65100",
    "#00838F",
    "#455A64",
)

STATUS_LABEL = {
    "complete": "完整",
    "near_complete": "近完整",
    "partial": "半截",
    "missing": "缺失",
}
STATUS_COLOR = {
    "complete": "#2E7D32",
    "near_complete": "#F9A825",
    "partial": "#EF6C00",
    "missing": "#BDBDBD",
}


def _configure_style() -> None:
    try:
        from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

        configure_matplotlib_chinese()
    except Exception:
        pass


def load_batch_cases(index_path: Path) -> list[dict[str, Any]]:
    data = json.loads(index_path.read_text(encoding="utf-8"))
    order = data.get("generation_order") or list(data["cases"].keys())
    rows = []
    for cid in order:
        meta = data["cases"][cid]
        rows.append(
            {
                "case_id": cid,
                "Af": float(meta["Af"]),
                "Q": float(meta["Q"]),
                "deq_mm": float(meta["deq_mm"]),
                "k": float(meta["k"]),
            }
        )
    return rows


def csv_path_for(post_root: Path, case_id: str, run_slug: str) -> Path:
    return post_root / case_id / run_slug / f"{run_slug}_stress_strain.csv"


def load_curve(csv_path: Path) -> tuple[list[float], list[float]] | None:
    if not csv_path.is_file():
        return None
    from scripts.plot_stress_strain import load_csv

    eps, sig = load_csv(str(csv_path))
    if not eps or not sig:
        return None
    return eps, sig


def stress_at(eps: list[float], sig: list[float], target: float) -> float | None:
    """Linear-interpolated engineering stress at exact target strain."""
    if not eps or eps[-1] < target - 1e-6:
        return None
    if target <= eps[0]:
        return sig[0]
    for i in range(1, len(eps)):
        if eps[i] >= target:
            e0, e1 = eps[i - 1], eps[i]
            s0, s1 = sig[i - 1], sig[i]
            if e1 == e0:
                return s1
            t = (target - e0) / (e1 - e0)
            return s0 + t * (s1 - s0)
    return sig[-1]


def mean_stress_band(
    eps: list[float], sig: list[float], lo: float, hi: float
) -> float | None:
    vals = [s for e, s in zip(eps, sig) if lo <= e <= hi]
    if not vals:
        return None
    return sum(vals) / len(vals)


def trapz_energy(eps: list[float], sig: list[float], e_cap: float) -> float | None:
    """∫ σ dε up to min(e_cap, εmax); None if εmax < e_cap * 0.98 (incomplete for that cap)."""
    if not eps or eps[-1] < e_cap * 0.98:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for e, s in zip(eps, sig):
        if e <= e_cap:
            xs.append(e)
            ys.append(s)
        else:
            # linear interpolate to e_cap
            if xs:
                e0, s0 = xs[-1], ys[-1]
                t = (e_cap - e0) / (e - e0) if e != e0 else 0.0
                xs.append(e_cap)
                ys.append(s0 + t * (s - s0))
            break
    if len(xs) < 2:
        return None
    area = 0.0
    for i in range(1, len(xs)):
        area += 0.5 * (ys[i] + ys[i - 1]) * (xs[i] - xs[i - 1])
    return area


def classify_status(emax: float | None) -> str:
    if emax is None:
        return "missing"
    if emax >= COMPLETE_EMIN:
        return "complete"
    if emax >= NEAR_EMIN:
        return "near_complete"
    return "partial"


def build_metrics(
    cases: list[dict[str, Any]],
    post_root: Path,
    run_slug: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meta in cases:
        cid = meta["case_id"]
        path = csv_path_for(post_root, cid, run_slug)
        curve = load_curve(path)
        row: dict[str, Any] = {
            **meta,
            "csv": str(path) if path.is_file() else None,
            "available": curve is not None,
            "n_points": None,
            "emax": None,
            "smax": None,
            "smax_strain": None,
            "s02": None,
            "s04": None,
            "s06": None,
            "s_plat": None,
            "dens_ratio": None,
            "U_0p6": None,
            "U_0p8": None,
            "status": "missing",
            "rank_eligible": False,
        }
        if not curve:
            rows.append(row)
            continue
        eps, sig = curve
        emax = eps[-1]
        peak_i = max(range(len(sig)), key=lambda i: sig[i])
        s04 = stress_at(eps, sig, 0.4)
        s075 = stress_at(eps, sig, 0.75)
        dens = None
        if s04 is not None and s075 is not None and s04 > 1e-12:
            dens = s075 / s04
        status = classify_status(emax)
        row.update(
            {
                "available": True,
                "n_points": len(eps),
                "emax": emax,
                "smax": sig[peak_i],
                "smax_strain": eps[peak_i],
                "s02": stress_at(eps, sig, 0.2),
                "s04": s04,
                "s06": stress_at(eps, sig, 0.6),
                "s_plat": mean_stress_band(eps, sig, 0.3, 0.5),
                "dens_ratio": dens,
                "U_0p6": trapz_energy(eps, sig, 0.6),
                "U_0p8": trapz_energy(eps, sig, 0.8),
                "status": status,
                "rank_eligible": status in ("complete", "near_complete"),
                "_curve": curve,
            }
        )
        rows.append(row)
    return rows


def write_metrics_table(rows: list[dict[str, Any]], out_dir: Path) -> None:
    export_keys = [
        "case_id",
        "Af",
        "Q",
        "deq_mm",
        "k",
        "status",
        "rank_eligible",
        "n_points",
        "emax",
        "smax",
        "smax_strain",
        "s02",
        "s04",
        "s06",
        "s_plat",
        "dens_ratio",
        "U_0p6",
        "U_0p8",
        "csv",
    ]
    clean = [{k: r.get(k) for k in export_keys} for r in rows]
    js = out_dir / "metrics_table.json"
    js.write_text(
        json.dumps(
            {
                "run_slug": RUN_SLUG,
                "complete_emin": COMPLETE_EMIN,
                "near_emin": NEAR_EMIN,
                "notes": {
                    "s_plat": "mean engineering stress for ε∈[0.3,0.5]",
                    "dens_ratio": "σ(0.75)/σ(0.4)",
                    "U": "∫σ dε (MPa) up to listed strain; None if curve short",
                    "rank_eligible": "complete or near_complete only",
                },
                "cases": clean,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    csv_path = out_dir / "metrics_table.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=export_keys)
        w.writeheader()
        for r in clean:
            w.writerow(r)


def plot_readiness(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    _configure_style()

    cols = ["CSV", "εmax", "点数", "状态", "可排名"]
    n = len(rows)
    fig_h = max(5.5, 0.38 * n + 1.8)
    fig, ax = plt.subplots(figsize=(10.5, fig_h), dpi=150)
    ax.set_xlim(0, len(cols))
    ax.set_ylim(0, n)
    ax.invert_yaxis()
    ax.set_xticks([i + 0.5 for i in range(len(cols))])
    ax.set_xticklabels(cols, fontsize=11)
    ax.set_yticks([i + 0.5 for i in range(n)])
    ax.set_yticklabels([r["case_id"] for r in rows], fontsize=9, fontfamily="monospace")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for i, r in enumerate(rows):
        st = r["status"]
        base = STATUS_COLOR[st]
        cells = [
            ("有" if r["available"] else "无", base if r["available"] else "#E0E0E0"),
            (
                f"{r['emax']:.3f}" if r["emax"] is not None else "—",
                base if r["emax"] is not None else "#E0E0E0",
            ),
            (
                str(r["n_points"]) if r["n_points"] is not None else "—",
                base if r["n_points"] is not None else "#E0E0E0",
            ),
            (STATUS_LABEL[st], base),
            ("是" if r["rank_eligible"] else "否", "#C8E6C9" if r["rank_eligible"] else "#EEEEEE"),
        ]
        for j, (text, color) in enumerate(cells):
            ax.add_patch(
                plt.Rectangle((j, i), 1, 1, facecolor=color, edgecolor="white", lw=1.5, alpha=0.85)
            )
            ax.text(j + 0.5, i + 0.5, text, ha="center", va="center", fontsize=9)

    ax.set_title(
        f"param_batch · CAE 压缩就绪矩阵  ·  {RUN_SLUG}",
        fontsize=13,
        pad=10,
    )
    legend = [
        Patch(facecolor=STATUS_COLOR[k], edgecolor="none", label=STATUS_LABEL[k], alpha=0.85)
        for k in ("complete", "near_complete", "partial", "missing")
    ]
    ax.legend(handles=legend, loc="upper right", bbox_to_anchor=(1.0, -0.02), ncol=4, frameon=False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_curves_refresh(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()
    by_id = {r["case_id"]: r for r in rows}

    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.4), dpi=150, sharex=True)
    for ax, (title, series) in zip(axes.ravel(), PANELS):
        plotted_any = False
        ymax = 0.01
        for i, (cid, label) in enumerate(series):
            r = by_id.get(cid)
            color = _COLORS[i % len(_COLORS)]
            if not r or not r.get("_curve"):
                ax.plot([], [], color=color, ls=":", lw=1.5, label=f"{label} (n/a)")
                continue
            eps, sig = r["_curve"]
            st = r["status"]
            if st == "partial":
                ls, lw = "--", 1.8
                lab = f"{label} (半截 ε={r['emax']:.2f})"
            elif st == "near_complete":
                ls, lw = "-", 1.8
                lab = f"{label} (~{r['emax']*100:.0f}%)"
            else:
                ls, lw = "-", 1.8
                lab = label
            ax.plot(eps, sig, color=color, ls=ls, lw=lw, label=lab)
            plotted_any = True
            ymax = max(ymax, max(sig))
            if st == "partial":
                ax.axvline(r["emax"], color=color, ls=":", lw=1.0, alpha=0.7)
        ax.set_title(title, fontsize=11, pad=6)
        ax.set_xlabel("工程应变")
        ax.set_ylabel("工程应力 (MPa)")
        ax.grid(True, alpha=0.35)
        ax.set_xlim(0.0, 0.80)
        ax.set_ylim(0.0, ymax * 1.12 if plotted_any else 0.04)
        ax.legend(loc="upper left", fontsize=7.5, framealpha=0.9)

    fig.suptitle(
        f"param_batch CAE 压缩扫参叠线（刷新）· 完整实线 / 半截虚线  ·  {RUN_SLUG}",
        fontsize=12.5,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _heatmap_grid(
    rows: list[dict[str, Any]],
    metric_key: str,
    *,
    require_rank: bool,
) -> tuple[list[float], list[float], list[list[float | None]], list[list[str]]]:
    """Group A: Af=2, deq=2 → Q rows × k cols."""
    q_vals = [0.0, 0.5, 1.0, 1.5]
    k_vals = [1.0, 1.5, 2.0]
    by_qk = {}
    for r in rows:
        if abs(r["Af"] - 2.0) > 1e-9 or abs(r["deq_mm"] - 2.0) > 1e-9:
            continue
        by_qk[(r["Q"], r["k"])] = r
    z: list[list[float | None]] = []
    annot: list[list[str]] = []
    for q in q_vals:
        zr: list[float | None] = []
        ar: list[str] = []
        for k in k_vals:
            r = by_qk.get((q, k))
            if not r or r["status"] == "missing":
                zr.append(None)
                ar.append("—")
                continue
            val = r.get(metric_key)
            if val is None:
                zr.append(None)
                ar.append("n/a" if r["status"] == "partial" else "—")
                continue
            if require_rank and not r["rank_eligible"]:
                zr.append(None)
                ar.append(f"半截\n({r['emax']:.2f})")
                continue
            zr.append(float(val))
            note = ""
            if r["status"] == "near_complete":
                note = "*"
            if metric_key in ("s02", "s04", "s06", "smax", "s_plat"):
                ar.append(f"{val:.4f}{note}")
            elif metric_key == "dens_ratio":
                ar.append(f"{val:.2f}{note}")
            else:
                ar.append(f"{val:.4g}{note}")
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
        ("σ @ ε=0.2 (MPa)", "s02", False),
        ("σ @ ε=0.4 (MPa)", "s04", False),
        ("σ_peak (MPa)", "smax", True),
        ("致密化比 σ(0.75)/σ(0.4)", "dens_ratio", True),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 9.0), dpi=150)
    for ax, (title, key, req) in zip(axes.ravel(), panels):
        q_vals, k_vals, z, annot = _heatmap_grid(rows, key, require_rank=req)
        arr = np.array(
            [[(np.nan if v is None else v) for v in row] for row in z], dtype=float
        )
        cmap = plt.cm.YlOrRd.copy()
        cmap.set_bad("#EEEEEE")
        im = ax.imshow(arr, cmap=cmap, aspect="auto")
        ax.set_xticks(range(len(k_vals)))
        ax.set_xticklabels([f"k={k:g}" for k in k_vals])
        ax.set_yticks(range(len(q_vals)))
        ax.set_yticklabels([f"Q={q:g}" for q in q_vals])
        ax.set_title(title, fontsize=11)
        for i in range(len(q_vals)):
            for j in range(len(k_vals)):
                txt = annot[i][j]
                val = z[i][j]
                color = "#212121" if val is None or val < (np.nanmax(arr) * 0.55 if np.isfinite(arr).any() else 0) else "#FAFAFA"
                ax.text(j, i, txt, ha="center", va="center", fontsize=8, color=color)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    fig.suptitle(
        "组 A（Af=2, deq=2）· Q×κ 压缩指标热图\n"
        "灰格=缺失/半截未达；* = 近完整(~78%)；σ_peak/致密化比仅完整+近完整",
        fontsize=12,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_metric_bars(rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()

    eligible = [r for r in rows if r["rank_eligible"]]
    panels = [
        ("峰值工程应力 σ_peak (MPa)", "smax"),
        ("平台应力 σ_plat  ε∈[0.3,0.5] 均值 (MPa)", "s_plat"),
        ("吸能 U = ∫σ dε 至 ε=0.6 (MPa)", "U_0p6"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 5.8), dpi=150)
    for ax, (title, key) in zip(axes, panels):
        items = [r for r in eligible if r.get(key) is not None]
        items.sort(key=lambda r: float(r[key]), reverse=True)
        if not items:
            ax.set_title(title)
            ax.text(0.5, 0.5, "无数据", ha="center", va="center", transform=ax.transAxes)
            continue
        labels = [
            r["case_id"] + ("*" if r["status"] == "near_complete" else "")
            for r in items
        ]
        vals = [float(r[key]) for r in items]
        colors = [
            STATUS_COLOR["near_complete"]
            if r["status"] == "near_complete"
            else "#1565C0"
            for r in items
        ]
        y = range(len(items))
        ax.barh(list(y), vals, color=colors, height=0.72)
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels, fontsize=8, fontfamily="monospace")
        ax.invert_yaxis()
        ax.set_title(title, fontsize=10)
        ax.grid(True, axis="x", alpha=0.35)
        for yi, v in zip(y, vals):
            ax.text(v, yi, f"  {v:.4g}", va="center", fontsize=8)
        # pad xlim for labels
        ax.set_xlim(0, max(vals) * 1.25)

    fig.suptitle(
        "READY 压缩指标排序（仅完整 + 近完整；半截不进）  ·  * = 近完整",
        fontsize=12.5,
        y=0.98,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="param_batch CAE 压缩对比 P0")
    ap.add_argument("--post-root", type=str, default=str(DEFAULT_POST))
    ap.add_argument("--index", type=str, default=str(DEFAULT_CAD_INDEX))
    ap.add_argument("--run-slug", type=str, default=RUN_SLUG)
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    post_root = Path(args.post_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = load_batch_cases(Path(args.index))
    rows = build_metrics(cases, post_root, args.run_slug)

    write_metrics_table(rows, out_dir)
    plot_readiness(rows, out_dir / "00_readiness_matrix.png")
    plot_curves_refresh(rows, out_dir / "01_cae_curves_refresh.png")
    plot_qk_heatmaps(rows, out_dir / "02_cae_Qk_heatmaps.png")
    plot_metric_bars(rows, out_dir / "03_cae_metric_bars.png")

    # drop heavy curves from console summary
    n = {st: sum(1 for r in rows if r["status"] == st) for st in STATUS_LABEL}
    print(f"status counts: {n}")
    print(f"Wrote P0 pack → {out_dir}")
    for name in (
        "00_readiness_matrix.png",
        "01_cae_curves_refresh.png",
        "02_cae_Qk_heatmaps.png",
        "03_cae_metric_bars.png",
        "metrics_table.csv",
        "metrics_table.json",
    ):
        p = out_dir / name
        print(f"  {'OK' if p.is_file() else 'MISSING':7s} {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
