#!/usr/bin/env python3
"""L10 seed-0.3 paperbox Q-sweep overlay (af2 · deq=2 · k=1).

  py -3 scripts/plot_param_batch_L10_tet0p3_q_sweep.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_param_batch_cae_compare import (  # noqa: E402
    _configure_style,
    csv_path_for,
    load_curve,
)
from src.paths import PROJECT_ROOT, REPORTS_ROOT  # noqa: E402

RUN_SLUG = "cae_tet0p3mm80_5mmin_paperbox"
BATCH = "param_batch"
POST_ROOT = PROJECT_ROOT / "output" / "post" / BATCH
OUT_DIR = REPORTS_ROOT / BATCH
OUT_PNG = OUT_DIR / "L10_tet0p3_q_sweep_stress_strain.png"

CASES: list[tuple[str, str]] = [
    ("af2q0_deq2_k1_L10", "Q=0"),
    ("af2q1_deq2_k1_L10", "Q=1"),
    ("af2q1p5_deq2_k1_L10", "Q=1.5"),
]
_COLORS = ("#1565C0", "#C62828", "#2E7D32")
_LINESTYLES = ("-", "--", "-.")


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()
    fig, ax = plt.subplots(figsize=(7.2, 5.2), dpi=150)
    rows: list[dict[str, Any]] = []
    plotted = 0
    ymax = 0.01

    for i, (cid, label) in enumerate(CASES):
        path = csv_path_for(POST_ROOT, cid, RUN_SLUG)
        data = load_curve(path)
        color = _COLORS[i % len(_COLORS)]
        ls = _LINESTYLES[i % len(_LINESTYLES)]
        if not data:
            ax.plot([], [], color=color, ls=ls, lw=1.8, label=f"{label} (pending)")
            rows.append({"case_id": cid, "label": label, "available": False, "csv": str(path)})
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
    ax.set_title(
        r"L10 Q 扫描 · $Af=2$, deq=2$\rightarrow$1 mm, $\kappa=1$" + "\n"
        "CAE C3D4 · 网格种子 0.3 · 压缩 80% (32 mm) · 5 mm/min · Neo-Hooke"
    )
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=150)
    plt.close(fig)

    payload = {
        "batch": BATCH,
        "run_slug": RUN_SLUG,
        "n_plotted": plotted,
        "cases": rows,
    }
    out_json = OUT_PNG.with_suffix(".json")
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Saved:", OUT_PNG)
    print("Saved:", out_json)
    print(f"plotted={plotted}/{len(CASES)}")
    return 0 if plotted else 1


if __name__ == "__main__":
    raise SystemExit(main())
