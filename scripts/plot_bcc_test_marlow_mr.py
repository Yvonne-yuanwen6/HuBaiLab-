"""Overlay BCC test_marlow vs test_MR stress-strain curves."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

_CASES = (
    (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_test_marlow",
        "BCC Marlow (Fig.2.5)",
        "#1565C0",
        "-",
    ),
    (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_test_MR",
        "BCC Mooney-Rivlin (test data)",
        "#C62828",
        "--",
    ),
)


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    n = 0
    for slug, label, color, ls in _CASES:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        eps, sig = load_csv(str(csv))
        if not eps:
            continue
        n += 1
        ax.plot(eps, sig, color=color, ls=ls, lw=1.8, label=label)
        peak_i = sig.index(max(sig))
        print(f"{label}: {len(eps)} pts, peak={max(sig):.4f} MPa @ eps={eps[peak_i]:.3f}")

    if not n:
        print("[ERROR] no curves loaded")
        return 1

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("BCC 4×4×4 CAE C3D4 — Marlow vs Mooney-Rivlin (Hu & Bai TPU)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()

    out_dir = REPORTS_ROOT / "bcc_test_marlow_mr"
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "bcc_test_marlow_vs_MR.png"
    fig.savefig(png, dpi=160)
    print(f"Saved: {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
