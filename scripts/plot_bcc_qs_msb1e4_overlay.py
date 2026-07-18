#!/usr/bin/env python3
"""Overlay BCC Fig.3.3 experiment vs qs smoke sims (msb1e4 / ms50 / nh)."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT
from src.postprocess.fig33_plot_style import (
    FIG33_EXP_LINEWIDTH,
    FIG33_OVERLAY_COLORS,
    autoscale_fig33_ylim_for_overlay,
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_simulation,
    save_fig33_figure,
)

SLUGS = {
    "marlow_msb1e4": (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_qs_sm12_marlow_msb1e4",
        "BCC Marlow BELOW_MIN dt=1e-4-仿真",
        "#C62828",
        "--",
    ),
    "marlow_ms50": (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_qs_sm12_marlow_ms50",
        "BCC Marlow BELOW_MIN dt=5e-4 ×50-仿真",
        "#E65100",
        "-.",
    ),
    "nh_msb1e4": (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_qs_sm12_nh_msb1e4",
        "BCC Neo-Hooke BELOW_MIN dt=1e-4-仿真",
        "#1565C0",
        ":",
    ),
}


def _load_energy(path: Path) -> tuple[list[float], list[float]]:
    t: list[float] = []
    ratio: list[float] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ie = float(row.get("ALLIE_J") or row.get("ALLIE") or 0.0)
            ke = abs(float(row.get("ALLKE_J") or row.get("ALLKE") or 0.0))
            tt = float(row.get("time_s") or row.get("time") or 0.0)
            t.append(tt)
            ratio.append((ke / ie) if ie > 1e-9 else 0.0)
    return t, ratio


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "mesh_convergence" / "bcc_qs_msb1e4_vs_fig33.png"),
    )
    ap.add_argument(
        "--energy-png",
        default=str(REPORTS_ROOT / "mesh_convergence" / "bcc_qs_msb1e4_ke_ie.png"),
    )
    args = ap.parse_args()

    import matplotlib.pyplot as plt
    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    ref = load_fig33_reference()
    bcc_pts = ref["series"]["bcc"]["points"]
    e_exp = [p[0] for p in bcc_pts]
    s_exp = [p[1] for p in bcc_pts]

    fig, ax = plt.subplots(figsize=(7.4, 5.0), dpi=160)
    ax.plot(
        e_exp,
        s_exp,
        color=FIG33_OVERLAY_COLORS["bcc"],
        lw=FIG33_EXP_LINEWIDTH,
        label="BCC-实验 (Fig.3.3)",
        zorder=2,
    )

    for _key, (slug, label, color, ls) in SLUGS.items():
        csv_path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv_path.is_file():
            print(f"[WARN] missing {csv_path}")
            continue
        eps, sig = load_csv(str(csv_path))
        ax.plot(eps, sig, color=color, linestyle=ls, linewidth=2.0, label=label, zorder=3)
        print(f"loaded {slug}: n={len(eps)} eps_max={max(eps):.3f} peak={max(sig):.5f} MPa")

    ax.axvline(0.12, color="#9E9E9E", linestyle=":", linewidth=1.0, zorder=0)
    ax.set_xlim(0.0, 0.14)
    ax.set_ylim(0.0, 0.005)
    ax.set_xlabel("应变")
    ax.set_ylabel("应力 (MPa)")
    ax.set_title("BCC Fig.3.3 实验 vs 准静态材料/质量缩放冒烟（ε≤0.12，纵轴放大）")
    ax.text(0.121, 0.0046, "smoke ε=0.12", color="#616161", fontsize=9, va="top")
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.grid(True, alpha=0.2)
    for spine in ax.spines.values():
        spine.set_color("black")
    Path(args.png).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(args.png, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {args.png}")
    _ = (create_fig33_figure, plot_fig33_simulation, save_fig33_figure, autoscale_fig33_ylim_for_overlay, load_csv)

    # KE/IE panel for marlow_msb1e4
    import matplotlib.pyplot as plt

    epath = (
        ABAQUS_POST
        / SLUGS["marlow_msb1e4"][0]
        / f"{SLUGS['marlow_msb1e4'][0]}_energy.csv"
    )
    if epath.is_file():
        t, r = _load_energy(epath)
        fig2, ax2 = plt.subplots(figsize=(7.2, 4.2))
        ax2.plot(t, [100.0 * x for x in r], color="#C62828", lw=1.8, label="Marlow msb1e4")
        ax2.axhline(5.0, color="#212121", ls="--", lw=1.2, label="论文准静态门槛 5%")
        ax2.set_xlabel("时间 (s)")
        ax2.set_ylabel("KE/IE (%)")
        ax2.set_title("Marlow BELOW_MIN dt=1e-4：动能/内能比")
        ax2.set_ylim(0, max(12.0, min(50.0, 100.0 * max(r) * 1.1)))
        ax2.legend(frameon=False)
        ax2.grid(True, alpha=0.25)
        Path(args.energy_png).parent.mkdir(parents=True, exist_ok=True)
        fig2.tight_layout()
        fig2.savefig(args.energy_png, dpi=160)
        plt.close(fig2)
        print(f"wrote {args.energy_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
