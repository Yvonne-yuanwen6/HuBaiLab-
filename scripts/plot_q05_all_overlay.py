"""Overlay all available Q=0.5 (SFBLS AF2Q0.5) stress-strain curves in output/post."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT
from src.postprocess.fig33_plot_style import (
    autoscale_fig33_ylim_for_overlay,
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_experiment_series,
    save_fig33_figure,
)

PREFIX = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_"

# Preferred display order (suffix after PREFIX); unknown suffixes sort last.
_LABEL_ORDER = {
    "cae_tet0p6mm80_5mmin_paperbox": "CAE baseline (settle15%)",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p": "CAE settle5p",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle": "CAE nosettle",
    "cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el": "fig33_v2 elastic",
    "cae_tet0p6mm80_5mmin_paperbox_fig33_v2_paper": "fig33_v2 Neo-Hooke",
    "cae_tet0p6mm80_5mmin_paperbox_fig33_v2_ep": "fig33_v2 elastoplastic",
    "cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow": "fig33_v2 Marlow",
    "cae_tet0p6mm80_5mmin_paperbox_fig33_snap_s78_el": "snap s78 elastic",
    "cae_tet0p6mm80_5mmin_paperbox_fig33_snap_s78_s0_08": "snap s78 s0=0.08",
    "cae_tet0p6mm80_5mmin_paperbox_fig33_snap_s78_s0_12": "snap s78 s0=0.12",
    "test_marlow": "test Marlow (Fig.2.5)",
    "test_MR": "test Mooney-Rivlin",
    "voxel0p6mm80_5mmin_autodt": "voxel 0.6 mm autodt",
    "voxel0p8mm75_15mmin": "voxel 0.8 mm 75% 15m/min",
    "voxel0p8mm80_15mmin_autodt": "voxel 0.8 mm 80% autodt",
    "voxel1mm80_25mmin": "voxel 1.0 mm 80% 25m/min",
    "voxel": "voxel (legacy slug)",
}

_LINESTYLES = ("-", "--", "-.", ":", (0, (3, 1, 1, 1)), (0, (5, 2)), (0, (1, 1)))


def _load_curve(path: Path) -> tuple[list[float], list[float]]:
    try:
        return load_csv(str(path))
    except KeyError:
        import csv

        strains: list[float] = []
        stresses: list[float] = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                e = row.get("engineering_strain") or row.get("\ufeffengineering_strain")
                s = row.get("engineering_stress_MPa")
                if e is None or s is None or str(e).strip() == "":
                    continue
                strains.append(float(e))
                stresses.append(float(s))
        return strains, stresses


def _slug_suffix(slug: str) -> str:
    if slug.startswith(PREFIX):
        return slug[len(PREFIX) :]
    return slug


def _label_for_slug(slug: str) -> str:
    suffix = _slug_suffix(slug)
    return _LABEL_ORDER.get(suffix, suffix.replace("_", " "))


def _discover_cases() -> list[tuple[str, str, Path]]:
    out: list[tuple[str, str, Path]] = []
    if not ABAQUS_POST.is_dir():
        return out
    for d in sorted(ABAQUS_POST.iterdir()):
        if not d.is_dir() or "sfbls_af2q0p5" not in d.name:
            continue
        slug = d.name
        for name in (f"{slug}_stress_strain.csv", f"{slug}_stress_strain_partial.csv"):
            p = d / name
            if p.is_file() and "raw" not in name:
                out.append((_label_for_slug(slug), slug, p))
                break
    order = {k: i for i, k in enumerate(_LABEL_ORDER)}
    out.sort(key=lambda x: (order.get(_slug_suffix(x[1]), 999), x[0]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Overlay all Q=0.5 stress-strain curves")
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "q05_all" / "q05_all_sim_overlay.png"),
    )
    parser.add_argument(
        "--png-with-exp",
        default=str(REPORTS_ROOT / "q05_all" / "q05_all_vs_fig33_exp.png"),
    )
    parser.add_argument("--no-exp", action="store_true", help="Skip experiment overlay figure")
    args = parser.parse_args()

    cases = _discover_cases()
    if not cases:
        print("[ERROR] no Q=0.5 CSV under output/post")
        return 1

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # --- all sim only ---
    fig, ax = plt.subplots(figsize=(12, 7))
    overlay_stresses: list[list[float]] = []
    loaded = 0
    for i, (label, slug, csv_path) in enumerate(cases):
        eps, sig = _load_curve(csv_path)
        if not eps:
            print(f"[WARN] empty curve: {label}")
            continue
        loaded += 1
        color = plt.cm.tab20(i % 20)
        ls = _LINESTYLES[i % len(_LINESTYLES)]
        ax.plot(eps, sig, color=color, ls=ls, lw=1.6, label=label)
        overlay_stresses.append(sig)
        peak_i = sig.index(max(sig))
        print(f"{label}: {len(eps)} pts, peak={max(sig):.4f} MPa @ eps={eps[peak_i]:.3f}")

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title(f"SFBLS Q=0.5 — all available sim curves ({loaded})")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=7, frameon=True)
    fig.tight_layout()
    out_sim = Path(args.png)
    out_sim.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_sim, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_sim}")

    if args.no_exp:
        return 0

    # --- with Fig.3.3 Q0.5 experiment ---
    ref = load_fig33_reference()
    fig2, ax2, ax_r = create_fig33_figure(figsize=(12, 7))
    plot_fig33_experiment_series(ax2, ref, series_key="af2q05")
    exp_stresses: list[list[float]] = []
    for i, (label, slug, csv_path) in enumerate(cases):
        eps, sig = _load_curve(csv_path)
        if not eps:
            print(f"[WARN] empty curve: {label}")
            continue
        color = plt.cm.tab20(i % 20)
        ls = _LINESTYLES[i % len(_LINESTYLES)]
        ax2.plot(eps, sig, color=color, ls=ls, lw=1.5, label=f"{label}")
        exp_stresses.append(sig)

    autoscale_fig33_ylim_for_overlay(ax2, ax_r, exp_stresses)
    ax2.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=7, frameon=True)
    ax2.set_title("AF2Q0.5 — Fig.3.3 实验 vs 全部已有仿真曲线")
    out_exp = save_fig33_figure(fig2, args.png_with_exp)
    print(f"Saved: {out_exp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
