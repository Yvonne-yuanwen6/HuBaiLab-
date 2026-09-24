#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 energy sweeps: stress-strain / Wv(eps) / eta(eps) triples.

Matches the existing Af, Q, and L10-L20 stress-strain overlays.
Metrics reuse Hu & Bai sec. 3.3 (src.postprocess.energy_absorption); definitions unchanged.

  py -3 scripts/plot_param_batch_energy_sweeps.py

Outputs (both output/reports/param_batch/ and output/reports/<BATCH>/):
  batch_cae_af_sweep_energy.png
  batch_cae_af_sweep_q1p5_energy.png
  batch_cae_q_sweep_energy.png
  L10_vs_L20_size_effect_energy.png
"""
from __future__ import annotations

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

from scripts.plot_param_batch_af_sweep import SERIES as AF_SERIES  # noqa: E402
from scripts.plot_param_batch_cae_compare import (  # noqa: E402
    BATCH_NAME,
    DEFAULT_POST,
    RUN_SLUG,
    _configure_style,
    csv_path_for,
    load_curve,
)
from scripts.plot_param_batch_L10_L20_size_effect import (  # noqa: E402
    find_l10_csv,
    find_l20_csv,
)
from src.paths import REPORTS_ROOT  # noqa: E402
from src.postprocess.energy_absorption import (  # noqa: E402
    analyze_energy_absorption,
    cumulative_volumetric_energy,
)

# Same ink as the Af stress-strain overlays, so the two figures cross-read.
_AF_COLORS = ("#1565C0", "#C62828", "#2E7D32", "#6A1B9A", "#E65100", "#00838F")
_AF_LINESTYLES = ("-", "--", "-.", ":", (0, (5, 1)), (0, (3, 1, 1, 1)))

# Q identity (Wong-like), shared by the Q sweep and the size-effect pair.
_Q_COLOR = {
    0.0: "#0072B2",
    0.5: "#009E73",
    1.0: "#D55E00",
    1.5: "#CC79A7",
}

Q_SWEEP: list[tuple[str, str, float]] = [
    ("af2q0_deq2_k1", "Q=0", 0.0),
    ("af2q0p5_deq2_k1", "Q=0.5", 0.5),
    ("af2q1_deq2_k1", "Q=1", 1.0),
    ("af2q1p5_deq2_k1", "Q=1.5", 1.5),
]

# (Q label, Q value, L10 case, L20 case) -- same pairs as the stress-strain size figure.
SIZE_PAIRS: list[tuple[str, float, str, str]] = [
    ("Q=0", 0.0, "af2q0_deq2_k1_L10", "af2q0_deq2_k1"),
    ("Q=1", 1.0, "af2q1_deq2_k1_L10", "af2q1_deq2_k1"),
    ("Q=1.5", 1.5, "af2q1p5_deq2_k1_L10", "af2q1p5_deq2_k1"),
]

_XLIM = (0.0, 0.82)
_SHADE_MAX = 4


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def _y_at(xs: list[float], ys: list[float], x: float) -> float | None:
    """Value on the plotted series at the last sample with strain <= x."""
    idx = -1
    for i, xv in enumerate(xs):
        if xv <= x + 1e-12:
            idx = i
        else:
            break
    if idx < 0:
        return None
    return float(ys[idx])


def _metrics(eps: list[float], sig: list[float]) -> dict[str, Any]:
    """Scalar energy summary. rho_a=1 so SEA is not reported here."""
    an = analyze_energy_absorption(eps, sig, relative_density=1.0)
    ed = float(an["densification"]["densification_strain"])
    wv = an["Wv_J_cm3"]
    eta = an["eta"]
    out: dict[str, Any] = {
        "n_points": len(eps),
        "emax": float(eps[-1]),
        "ed": ed if _finite(ed) else None,
        "Wv_ed": None,
        "eta_ed": None,
        "eta_max": float(max(eta)) if eta else None,
        "sigma_max_to_ed": None,
    }
    if not _finite(ed):
        return out
    out["Wv_ed"] = _y_at(eps, wv, ed)
    out["eta_ed"] = _y_at(eps, eta, ed)
    sig_to = [s for e, s in zip(eps, sig) if e <= ed + 1e-12]
    out["sigma_max_to_ed"] = float(max(sig_to)) if sig_to else None
    return out


def _mark_ed(ax, x: float, y: float, color: str) -> None:
    ax.scatter(
        [x],
        [y],
        s=58,
        zorder=5,
        color=color,
        edgecolors="white",
        linewidths=1.15,
        marker="o",
    )


def _style_axes(ax, ylabel: str, ymax: float) -> None:
    ax.set_xlim(*_XLIM)
    ax.set_ylim(0.0, ymax * 1.12 if ymax > 0 else 1.0)
    ax.set_xlabel(r"工程应变 $\varepsilon$")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)


def plot_triple(
    traces: list[dict[str, Any]],
    *,
    title: str,
    subtitle: str,
    out_name: str,
) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    _configure_style()
    shade = sum(1 for t in traces if t.get("eps")) <= _SHADE_MAX
    fig, axes = plt.subplots(1, 3, figsize=(13.6, 5.15), dpi=150)
    ax_s, ax_w, ax_e = axes
    ymax = [0.01, 0.01, 0.01]
    legend_handles: list[Line2D] = []
    rows: list[dict[str, Any]] = []

    for t in traces:
        color = t["color"]
        ls = t["ls"]
        label = t["label"]
        eps = t.get("eps")
        sig = t.get("sig")
        legend_handles.append(Line2D([0], [0], color=color, ls=ls, lw=2.0, label=label))
        row: dict[str, Any] = {
            "case_id": t.get("case_id"),
            "label": label,
            "scale": t.get("scale"),
            "available": bool(eps and sig),
        }
        if not eps or not sig:
            rows.append(row)
            continue

        wv = cumulative_volumetric_energy(eps, sig)
        an = analyze_energy_absorption(eps, sig, relative_density=1.0)
        eta = an["eta"]
        meta = _metrics(eps, sig)
        row.update(meta)
        ed = meta["ed"]

        ax_s.plot(eps, sig, color=color, ls=ls, lw=2.0)
        ax_w.plot(eps, wv, color=color, ls=ls, lw=2.0)
        ax_e.plot(eps, eta, color=color, ls=ls, lw=2.0)
        ymax[0] = max(ymax[0], max(sig))
        ymax[1] = max(ymax[1], max(wv))
        ymax[2] = max(ymax[2], max(eta))

        if shade and ed is not None:
            n = sum(1 for e in eps if e <= ed + 1e-12)
            if n >= 2:
                ax_s.fill_between(eps[:n], sig[:n], color=color, alpha=0.10, linewidth=0)

        if ed is not None:
            ys = (
                _y_at(eps, sig, ed),
                _y_at(eps, wv, ed),
                _y_at(eps, eta, ed),
            )
            for ax, y in zip(axes, ys):
                if y is not None:
                    _mark_ed(ax, ed, y, color)
        rows.append(row)

    _style_axes(ax_s, "工程应力 (MPa)", ymax[0])
    _style_axes(ax_w, r"体积吸能 $W_v$ (J/cm$^3$)", ymax[1])
    _style_axes(ax_e, r"吸能效率 $\eta = W_v / \sigma^*$", ymax[2])
    ax_s.set_title("应力-应变")
    ax_w.set_title(r"累积 $W_v$")
    ax_e.set_title(r"效率 $\eta$")

    legend_handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor="#455A64",
            markeredgecolor="white",
            markersize=8,
            linestyle="None",
            label=r"$\varepsilon_d$",
        )
    )
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=min(len(legend_handles), 7),
        frameon=False,
        fontsize=9,
        bbox_to_anchor=(0.5, 0.0),
    )
    fig.suptitle(f"{title}\n{subtitle}", fontsize=12)
    fig.tight_layout(rect=(0, 0.08, 1, 0.90))

    primary = REPORTS_ROOT / "param_batch" / out_name
    primary.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(primary, dpi=150)
    plt.close(fig)

    mirror = REPORTS_ROOT / BATCH_NAME / out_name
    mirror.parent.mkdir(parents=True, exist_ok=True)
    if mirror.resolve() != primary.resolve():
        shutil.copy2(primary, mirror)

    payload = {
        "title": title,
        "subtitle": subtitle,
        "png": str(primary),
        "shade_to_ed": shade,
        "notes": {
            "Wv": "integral sigma d(eps) [J/cm3]; sigma in MPa",
            "eta": "Wv/sigma* ; sigma* = running peak stress",
            "ed": "efficiency-method densification onset",
            "SEA": "not on these curves; rho_a is not applied",
        },
        "cases": rows,
    }
    for folder in (primary.parent, mirror.parent):
        (folder / Path(out_name).with_suffix(".json").name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    n_ok = sum(1 for r in rows if r["available"])
    print(f"Saved: {primary}  ({n_ok}/{len(rows)} curves)")
    return payload


def _af_traces(q: float) -> list[dict[str, Any]]:
    spec = AF_SERIES[q]
    traces: list[dict[str, Any]] = []
    for i, (cid, label) in enumerate(spec["cases"]):
        data = load_curve(csv_path_for(DEFAULT_POST, cid, RUN_SLUG))
        traces.append(
            {
                "case_id": cid,
                "label": label if data else f"{label} (无数据)",
                "color": _AF_COLORS[i % len(_AF_COLORS)],
                "ls": _AF_LINESTYLES[i % len(_AF_LINESTYLES)],
                "eps": data[0] if data else None,
                "sig": data[1] if data else None,
            }
        )
    return traces


def _q_traces() -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for cid, label, q in Q_SWEEP:
        data = load_curve(csv_path_for(DEFAULT_POST, cid, RUN_SLUG))
        traces.append(
            {
                "case_id": cid,
                "label": label if data else f"{label} (无数据)",
                "color": _Q_COLOR[q],
                "ls": "-",
                "eps": data[0] if data else None,
                "sig": data[1] if data else None,
            }
        )
    return traces


def _size_traces() -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for q_lbl, q, cid10, cid20 in SIZE_PAIRS:
        color = _Q_COLOR[q]
        for scale, cid, finder, ls in (
            ("L20", cid20, find_l20_csv, "-"),
            ("L10", cid10, find_l10_csv, "--"),
        ):
            path = finder(cid)
            data = load_curve(path) if path else None
            label = f"{q_lbl} {scale}"
            traces.append(
                {
                    "case_id": cid,
                    "scale": scale,
                    "label": label if data else f"{label} (无数据)",
                    "color": color,
                    "ls": ls,
                    "eps": data[0] if data else None,
                    "sig": data[1] if data else None,
                }
            )
    return traces


def main() -> int:
    protocol = r"Abaqus CAE · C3D4 · 压缩 80% · 5 mm/min · Neo-Hooke · 圆点=$\varepsilon_d$"
    jobs = [
        (
            _af_traces(1.0),
            r"Af 扫描吸能 · $Q=1$, deq=2, $\kappa=1$",
            f"{protocol} · 网格种子 0.6",
            "batch_cae_af_sweep_energy.png",
        ),
        (
            _af_traces(1.5),
            r"Af 扫描吸能 · $Q=1.5$, deq=2, $\kappa=1$",
            f"{protocol} · 网格种子 0.6 · 阴影积至 $\\varepsilon_d$",
            "batch_cae_af_sweep_q1p5_energy.png",
        ),
        (
            _q_traces(),
            r"Q 扫描吸能 · $Af=2$, deq=2, $\kappa=1$",
            f"{protocol} · 网格种子 0.6 · 阴影积至 $\\varepsilon_d$",
            "batch_cae_q_sweep_energy.png",
        ),
        (
            _size_traces(),
            r"尺度效应吸能 · $Af=2$, $\kappa=1$, deq$\propto L$",
            f"{protocol} · 实线 L20 网格种子 0.6 · 虚线 L10 网格种子 0.3",
            "L10_vs_L20_size_effect_energy.png",
        ),
    ]
    n_fail = 0
    for traces, title, subtitle, name in jobs:
        payload = plot_triple(traces, title=title, subtitle=subtitle, out_name=name)
        if not any(c["available"] for c in payload["cases"]):
            n_fail += 1
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
