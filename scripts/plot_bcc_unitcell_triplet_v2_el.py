"""Overlay stress-strain curves for BCC unit-cell triplet (V2 elastic)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import matplotlib.pyplot as plt

from src.paths import ABAQUS_POST, REPORTS_ROOT, ensure_output_dirs
from src.postprocess.compression_curve import estimate_densification_strain
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

CASES_DEFAULT = (
    ("圆杆 BCC", "cae_tet0p6mm70p_5mmin", "uc_circ_v2_el", "#1976D2"),
    ("椭圆短轴∥Z", "cae_tet0p6mm70p_5mmin", "uc_ellmin_v2_el", "#D32F2F"),
    ("椭圆长轴∥Z", "cae_tet0p6mm70p_5mmin", "uc_ellmaj_v2_el", "#388E3C"),
)
CASES_EQAREA = (
    ("圆杆 BCC (等面积)", "cae_tet0p6mm70p_5mmin", "uc_circ_eqa_v2_el", "#1976D2"),
    ("椭圆短轴∥Z", "cae_tet0p6mm70p_5mmin", "uc_ellmin_eqa_v2_el", "#D32F2F"),
    ("椭圆长轴∥Z", "cae_tet0p6mm70p_5mmin", "uc_ellmaj_eqa_v2_el", "#388E3C"),
)
CASES_AREA_PI = (
    ("圆杆 BCC (A=π)", "cae_tet0p6mm80p_5mmin", "uc_circ_api_v2_el", "#1976D2"),
    ("椭圆短轴∥Z", "cae_tet0p6mm80p_5mmin", "uc_ellmin_api_v2_el", "#D32F2F"),
    ("椭圆长轴∥Z", "cae_tet0p6mm80p_5mmin", "uc_ellmaj_api_v2_el", "#388E3C"),
)
CASES_AREA_PI_CF = (
    ("圆杆 BCC (A=π, CF)", "cae_tet0p6mm80p_5mmin", "uc_circ_api_cf_v2_el", "#1976D2"),
    ("椭圆短轴∥Z", "cae_tet0p6mm80p_5mmin", "uc_ellmin_api_cf_v2_el", "#D32F2F"),
    ("椭圆长轴∥Z", "cae_tet0p6mm80p_5mmin", "uc_ellmaj_api_cf_v2_el", "#388E3C"),
)
CASES_AREA_PI_PT = (
    ("圆杆 BCC (A=π, PT)", "cae_tet0p6mm80p_5mmin", "uc_circ_api_pt_v2_el", "#1976D2"),
    ("椭圆短轴∥Z", "cae_tet0p6mm80p_5mmin", "uc_ellmin_api_pt_v2_el", "#D32F2F"),
    ("椭圆长轴∥Z", "cae_tet0p6mm80p_5mmin", "uc_ellmaj_api_pt_v2_el", "#388E3C"),
)


def _slug(base_suffix: str, case_suffix: str) -> str:
    return f"hu_bai_bcc_af2q0_L20_1x1x1_solid_cad_f_{base_suffix}_{case_suffix}"


def _read_curve(csv_path: str) -> tuple[list[float], list[float]]:
    eps: list[float] = []
    sig: list[float] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                eps.append(float(row["engineering_strain"]))
                sig.append(float(row["engineering_stress_MPa"]))
            except (KeyError, ValueError, TypeError):
                continue
    if not eps:
        raise ValueError(f"empty curve: {csv_path}")
    return eps, sig


def _trim_through_common_yield(
    curves: list[tuple[str, list[float], list[float], str]],
    *,
    margin: float = 0.02,
) -> tuple[float, list[tuple[str, list[float], list[float], str]]]:
    """
    Trim curves to the strain where the last structure reaches densification onset.

    Uses estimate_densification_strain (Hu & Bai §3.3.1 / ISO 13314 style η peak).
    """
    limits: list[float] = []
    for _label, eps, sig, _color in curves:
        dens = estimate_densification_strain(eps, sig)
        ed = float(dens["densification_strain"])
        if ed == ed:  # noqa: PLR0124 — NaN check
            limits.append(ed)
    if not limits:
        return 1.0, curves
    xmax = max(limits) + float(margin)
    trimmed: list[tuple[str, list[float], list[float], str]] = []
    for label, eps, sig, color in curves:
        keep = [i for i, e in enumerate(eps) if e <= xmax]
        if not keep:
            keep = [0]
        trimmed.append(
            (
                label,
                [eps[i] for i in keep],
                [sig[i] for i in keep],
                color,
            )
        )
    return xmax, trimmed


def _pick_cases(args: argparse.Namespace) -> tuple[list[tuple[str, str, str, str]], str, str]:
    if args.area_pi_pt:
        cases = CASES_AREA_PI_PT
        title = "BCC unit cell triplet — A=π mm², parallel-transport sweep, CAE C3D4, 80% strain"
        default_png = str(REPORTS_ROOT / "bcc_unitcell_triplet" / "triplet_api_pt80_stress_strain.png")
    elif args.area_pi_cf:
        cases = CASES_AREA_PI_CF
        title = "BCC unit cell triplet — A=π mm², CorrectedFrenet, CAE C3D4, 80% strain"
        default_png = str(REPORTS_ROOT / "bcc_unitcell_triplet" / "triplet_api_cf80_stress_strain.png")
    elif args.area_pi:
        cases = CASES_AREA_PI
        title = "BCC unit cell triplet — A=π mm², CAE C3D4, 80% strain, self-contact"
        default_png = str(REPORTS_ROOT / "bcc_unitcell_triplet" / "triplet_api80_stress_strain.png")
    elif args.eq_area:
        cases = CASES_EQAREA
        title = "BCC unit cell triplet — V2 equal-area (elastic, 70% strain, self-contact)"
        default_png = str(REPORTS_ROOT / "bcc_unitcell_triplet" / "triplet_v2_el_eqarea_stress_strain.png")
    else:
        cases = CASES_DEFAULT
        title = "BCC unit cell triplet — V2 (elastic, 70% strain, self-contact)"
        default_png = str(REPORTS_ROOT / "bcc_unitcell_triplet" / "triplet_v2_el_stress_strain.png")
    return cases, title, default_png


def main() -> int:
    ensure_output_dirs()
    p = argparse.ArgumentParser(description="Plot BCC unitcell triplet V2 curves")
    p.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "bcc_unitcell_triplet" / "triplet_v2_el_stress_strain.png"),
    )
    p.add_argument("--write-json", default="")
    p.add_argument(
        "--eq-area",
        action="store_true",
        help="Plot equal-area triplet (d_circ=sqrt(d_major*d_minor))",
    )
    p.add_argument(
        "--area-pi",
        action="store_true",
        help="Plot A=pi mm^2 triplet at 80%% strain with densification markers",
    )
    p.add_argument(
        "--area-pi-cf",
        action="store_true",
        help="Plot A=pi CorrectedFrenet triplet at 80%% strain",
    )
    p.add_argument(
        "--area-pi-pt",
        action="store_true",
        help="Plot A=pi parallel-transport sweep triplet at 80%% strain",
    )
    p.add_argument(
        "--show-densification",
        action="store_true",
        help="Mark densification onset (default on for --area-pi / --area-pi-cf / --area-pi-pt)",
    )
    p.add_argument(
        "--to-common-yield",
        action="store_true",
        help="Trim x-axis to last densification onset among all curves (plateau compare)",
    )
    args = p.parse_args()
    flags = (args.eq_area, args.area_pi, args.area_pi_cf, args.area_pi_pt)
    if sum(bool(x) for x in flags) > 1:
        raise SystemExit("Use only one of --eq-area, --area-pi, --area-pi-cf, --area-pi-pt")

    show_dens = args.show_densification or args.area_pi or args.area_pi_cf or args.area_pi_pt
    cases, title, default_png = _pick_cases(args)
    if args.png == str(REPORTS_ROOT / "bcc_unitcell_triplet" / "triplet_v2_el_stress_strain.png"):
        args.png = default_png

    configure_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    manifest: dict[str, object] = {
        "cases": [],
        "equal_area": bool(args.eq_area),
        "area_pi": bool(args.area_pi),
        "area_pi_cf": bool(args.area_pi_cf),
        "area_pi_pt": bool(args.area_pi_pt),
        "to_common_yield": bool(args.to_common_yield),
    }

    raw_curves: list[tuple[str, str, str, list[float], list[float], str]] = []
    for label, base_suffix, case_suffix, color in cases:
        slug = _slug(base_suffix, case_suffix)
        csv_path = os.path.join(str(ABAQUS_POST), slug, f"{slug}_stress_strain.csv")
        if not os.path.isfile(csv_path):
            print(f"[WARN] missing CSV: {csv_path}", flush=True)
            continue
        eps, sig = _read_curve(csv_path)
        raw_curves.append((label, slug, csv_path, eps, sig, color))

    if not raw_curves:
        raise SystemExit("No stress-strain CSVs found.")

    xmax_limit = 1.0
    if args.to_common_yield:
        slim = [(lab, eps, sig, col) for lab, _slug, _csv, eps, sig, col in raw_curves]
        xmax_limit, slim = _trim_through_common_yield(slim)
        raw_curves = [
            (lab, slug, csv, eps, sig, col)
            for (lab, slug, csv, _e, _s, col), (_l, eps, sig, _c) in zip(raw_curves, slim)
        ]
        title = f"{title} (through common densification onset)"

    for label, slug, csv_path, eps, sig, color in raw_curves:
        eps_full, sig_full = _read_curve(csv_path)
        ax.plot(eps, sig, color=color, linewidth=2.0, label=label)
        case_info: dict[str, object] = {
            "label": label,
            "slug": slug,
            "csv": csv_path,
            "n_points": len(eps),
            "n_points_full": len(eps_full),
            "peak_stress_MPa": max(sig_full),
            "max_strain": max(eps_full),
        }
        if show_dens:
            dens = estimate_densification_strain(eps_full, sig_full)
            ed = dens["densification_strain"]
            sd = dens["densification_stress_MPa"]
            case_info["densification"] = dens
            if ed == ed and sd == sd:  # noqa: PLR0124 — NaN check
                ax.plot(ed, sd, "o", color=color, markersize=7, markeredgecolor="black", markeredgewidth=0.6, zorder=5)
                ax.annotate(
                    f"εd={ed:.2f}",
                    xy=(ed, sd),
                    xytext=(8, 8),
                    textcoords="offset points",
                    fontsize=8,
                    color=color,
                )
                print(f"{label}: peak={max(sig):.4f} MPa, eps_d={ed:.3f}, sig_d={sd:.4f}", flush=True)
            else:
                print(f"{label}: {len(eps)} pts, peak={max(sig):.4f} MPa (no eps_d)", flush=True)
        else:
            print(f"{label}: {len(eps)} pts, peak={max(sig):.4f} MPa", flush=True)
        manifest["cases"].append(case_info)

    manifest["xmax_limit"] = xmax_limit if args.to_common_yield else None

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")
    ax.set_xlim(left=0.0)
    if args.to_common_yield:
        ax.set_xlim(0.0, xmax_limit)

    out_png = os.path.abspath(args.png)
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    plt.close(fig)
    print(f"PNG: {out_png}", flush=True)

    if args.write_json:
        out_json = os.path.abspath(args.write_json)
        os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
        manifest["png"] = out_png
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"JSON: {out_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
