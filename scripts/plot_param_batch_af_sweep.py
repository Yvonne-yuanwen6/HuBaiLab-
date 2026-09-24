#!/usr/bin/env python3
"""Standalone Af 扫描 stress-strain overlay (deq=2, k=1).

  py -3 scripts/plot_param_batch_af_sweep.py
  py -3 scripts/plot_param_batch_af_sweep.py --q 1.5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_param_batch_cae_compare import (  # noqa: E402
    BATCH_NAME,
    DEFAULT_POST,
    RUN_SLUG,
    _configure_style,
    csv_path_for,
    load_curve,
)
from src.paths import REPORTS_ROOT  # noqa: E402

# Af-only series at fixed Q / deq=2 / k=1
SERIES: dict[float, dict[str, Any]] = {
    1.0: {
        "out_name": "batch_cae_af_sweep_stress_strain.png",
        "cases": [
            ("af0p5q1_deq2_k1", "Af=0.5"),
            ("af1q1_deq2_k1", "Af=1"),
            ("af1p5q1_deq2_k1", "Af=1.5"),
            ("af2q1_deq2_k1", "Af=2"),
            ("af2p5q1_deq2_k1", "Af=2.5"),
            ("af3q1_deq2_k1", "Af=3"),
        ],
    },
    1.5: {
        "out_name": "batch_cae_af_sweep_q1p5_stress_strain.png",
        "cases": [
            ("af0p5q1p5_deq2_k1", "Af=0.5"),
            ("af1q1p5_deq2_k1", "Af=1"),
            ("af1p5q1p5_deq2_k1", "Af=1.5"),
            ("af2q1p5_deq2_k1", "Af=2"),
        ],
    },
}

_COLORS = ("#1565C0", "#C62828", "#2E7D32", "#6A1B9A", "#E65100", "#00838F")
_LINESTYLES = ("-", "--", "-.", ":", (0, (5, 1)), (0, (3, 1, 1, 1)))


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--q", type=float, default=1.0, choices=sorted(SERIES.keys()), help="fixed Q")
    args = ap.parse_args()
    q = float(args.q)
    spec = SERIES[q]
    af_series: list[tuple[str, str]] = list(spec["cases"])

    _configure_style()
    post_root = DEFAULT_POST
    out_png = REPORTS_ROOT / BATCH_NAME / str(spec["out_name"])
    out_json = out_png.with_suffix(".json")
    ascii_dir = REPORTS_ROOT / "param_batch"
    ascii_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.2, 5.2), dpi=150)
    rows: list[dict[str, Any]] = []
    plotted = 0
    ymax = 0.01

    for i, (cid, label) in enumerate(af_series):
        data = load_curve(csv_path_for(post_root, cid, RUN_SLUG))
        color = _COLORS[i % len(_COLORS)]
        ls = _LINESTYLES[i % len(_LINESTYLES)]
        if not data:
            ax.plot([], [], color=color, ls=ls, lw=1.8, label=f"{label} (n/a)")
            rows.append({"case_id": cid, "label": label, "available": False})
            continue
        eps, sig = data
        ax.plot(eps, sig, color=color, ls=ls, lw=2.0, label=label)
        plotted += 1
        ymax = max(ymax, max(sig))
        peak_i = max(range(len(sig)), key=lambda j: sig[j])

        def _at(target: float, e=eps, s=sig) -> float | None:
            for ee, ss in zip(e, s):
                if ee >= target:
                    return ss
            return None

        rows.append(
            {
                "case_id": cid,
                "label": label,
                "available": True,
                "n_points": len(eps),
                "peak_stress_MPa": sig[peak_i],
                "peak_strain": eps[peak_i],
                "stress_at_0.2": _at(0.2),
                "stress_at_0.4": _at(0.4),
                "final_stress_MPa": sig[-1],
                "final_strain": eps[-1],
            }
        )

    ax.set_xlim(0.0, 0.82)
    ax.set_ylim(0.0, ymax * 1.12)
    ax.set_xlabel(r"工程应变 $\varepsilon$")
    ax.set_ylabel("工程应力 (MPa)")
    q_lbl = "1.5" if abs(q - 1.5) < 1e-9 else f"{q:g}"
    ax.set_title(
        f"Af 扫描 · $Q={q_lbl}$, deq=2, $\\kappa=1$\n"
        "Abaqus CAE C3D4 · 网格种子 0.6 · 压缩 80% · 5 mm/min · Neo-Hooke"
    )
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150)
    plt.close(fig)

    payload = {
        "fixed": {"Q": q, "deq_mm": 2.0, "k": 1.0},
        "run_slug": RUN_SLUG,
        "n_plotted": plotted,
        "cases": rows,
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    import shutil

    for src in (out_png, out_json):
        shutil.copy2(src, ascii_dir / src.name)
        print("Saved:", ascii_dir / src.name)
    print(f"plotted={plotted}/{len(af_series)}")
    return 0 if plotted else 1


if __name__ == "__main__":
    raise SystemExit(main())
