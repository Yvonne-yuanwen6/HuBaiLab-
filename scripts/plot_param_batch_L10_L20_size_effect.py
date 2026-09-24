#!/usr/bin/env python3
"""Size-effect overlay: L10 seed-0.3 vs L20 seed-0.6 (similar-scale mesh).

Pairs Af=2, deq∝L, κ=1 paperbox CAE curves where both scales have CSV.

  py -3 scripts/plot_param_batch_L10_L20_size_effect.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_param_batch_cae_compare import _configure_style, load_curve  # noqa: E402
from src.paths import PROJECT_ROOT, REPORTS_ROOT  # noqa: E402

SLUG_L10 = "cae_tet0p3mm80_5mmin_paperbox"
SLUG_L20 = "cae_tet0p6mm80_5mmin_paperbox"
POST_L10 = PROJECT_ROOT / "output" / "post" / "param_batch"
POST_L20 = PROJECT_ROOT / "output" / "post" / "param_batch"
OUT_DIR = REPORTS_ROOT / "param_batch"
OUT_PNG = OUT_DIR / "L10_vs_L20_size_effect_stress_strain.png"

# (Q label, L10 case_id, L20 case_id)
PAIRS: list[tuple[str, str, str]] = [
    ("Q=0", "af2q0_deq2_k1_L10", "af2q0_deq2_k1"),
    ("Q=1", "af2q1_deq2_k1_L10", "af2q1_deq2_k1"),
    ("Q=1.5", "af2q1p5_deq2_k1_L10", "af2q1p5_deq2_k1"),
]

COLOR_L10 = "#C62828"
COLOR_L20 = "#1565C0"


def find_l20_csv(case_id: str) -> Path | None:
    p = POST_L20 / case_id / SLUG_L20 / f"{SLUG_L20}_stress_strain.csv"
    return p if p.is_file() else None


def find_l10_csv(case_id: str) -> Path | None:
    p = POST_L10 / case_id / SLUG_L10 / f"{SLUG_L10}_stress_strain.csv"
    return p if p.is_file() else None


def _at(eps: list[float], sig: list[float], target: float) -> float | None:
    for e, s in zip(eps, sig):
        if e >= target:
            return s
    return None


def _summary(cid: str, scale: str, eps: list[float], sig: list[float]) -> dict[str, Any]:
    peak_i = max(range(len(sig)), key=lambda j: sig[j])
    return {
        "case_id": cid,
        "scale": scale,
        "n_points": len(eps),
        "peak_stress_MPa": sig[peak_i],
        "peak_strain": eps[peak_i],
        "stress_at_0.2": _at(eps, sig, 0.2),
        "stress_at_0.4": _at(eps, sig, 0.4),
        "final_stress_MPa": sig[-1],
        "final_strain": eps[-1],
    }


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _configure_style()

    available: list[tuple[str, str, str, list[float], list[float], list[float], list[float]]] = []
    skipped: list[dict[str, Any]] = []
    for q_lbl, cid10, cid20 in PAIRS:
        p10 = find_l10_csv(cid10)
        p20 = find_l20_csv(cid20)
        d10 = load_curve(p10) if p10 else None
        d20 = load_curve(p20) if p20 else None
        if not d10 or not d20:
            skipped.append(
                {
                    "Q": q_lbl,
                    "L10": str(p10) if p10 else None,
                    "L20": str(p20) if p20 else None,
                    "L10_ok": bool(d10),
                    "L20_ok": bool(d20),
                }
            )
            continue
        available.append((q_lbl, cid10, cid20, d10[0], d10[1], d20[0], d20[1]))

    if not available:
        print("No L10+L20 pairs available")
        return 1

    n = len(available)
    fig, axes = plt.subplots(1, n, figsize=(4.6 * n + 0.6, 4.8), dpi=150, squeeze=False)
    rows: list[dict[str, Any]] = []

    for ax, (q_lbl, cid10, cid20, e10, s10, e20, s20) in zip(axes[0], available):
        ax.plot(e20, s20, color=COLOR_L20, ls="-", lw=2.0, label="L20 · 网格种子 0.6")
        ax.plot(e10, s10, color=COLOR_L10, ls="--", lw=2.0, label="L10 · 网格种子 0.3")
        ymax = max(max(s10), max(s20))
        ax.set_xlim(0.0, 0.82)
        ax.set_ylim(0.0, ymax * 1.12)
        ax.set_xlabel(r"工程应变 $\varepsilon$")
        ax.set_ylabel("工程应力 (MPa)")
        ax.set_title(q_lbl)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper left", frameon=False, fontsize=8)
        rows.append(
            {
                "Q": q_lbl,
                "L10": _summary(cid10, "L10", e10, s10),
                "L20": _summary(cid20, "L20", e20, s20),
                "ratio_s02_L10_over_L20": (
                    None
                    if _at(e10, s10, 0.2) is None or _at(e20, s20, 0.2) in (None, 0)
                    else _at(e10, s10, 0.2) / _at(e20, s20, 0.2)  # type: ignore[operator]
                ),
            }
        )

    fig.suptitle(
        r"尺度效应 · $Af=2$, $\kappa=1$, deq$\propto L$ · paperbox CAE" + "\n"
        "L20: 网格种子 0.6 / 64 mm · L10: 网格种子 0.3 / 32 mm · 压缩 80% · 5 mm/min · Neo-Hooke",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=150)
    plt.close(fig)

    payload = {
        "out": str(OUT_PNG),
        "slug_L10": SLUG_L10,
        "slug_L20": SLUG_L20,
        "n_panels": n,
        "pairs": rows,
        "skipped": skipped,
    }
    out_json = OUT_PNG.with_suffix(".json")
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Saved:", OUT_PNG)
    print("Saved:", out_json)
    print(f"panels={n} skipped={len(skipped)}")
    for sk in skipped:
        print("  skip", sk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
