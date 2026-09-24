"""Compare plots + summary table for rate / mesh QS studies."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


def write_comparison(
    cases: list[dict[str, Any]],
    out_dir: Path,
    *,
    study_name: str,
    ke_ie_limit: float = 0.05,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ["#1565C0", "#E65100", "#2E7D32", "#6A1B9A", "#00838F"]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.2))
    ax_fu, ax_ke, ax_ae, ax_tab = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    table_rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases):
        color = colors[i % len(colors)]
        cid = case.get("case_id", f"C{i}")
        label = case.get("label", cid)
        eval_ = case.get("evaluation") or {}
        fu = eval_.get("fu") or {}
        en = eval_.get("energy") or {}
        pts = eval_.get("fu_points") or []
        erows = eval_.get("energy_rows") or []

        if pts:
            ax_fu.plot(
                [p[0] for p in pts],
                [p[1] for p in pts],
                color=color,
                lw=1.8,
                label=f"{cid}: {label}",
            )
        if erows:
            t = [r["t"] for r in erows]
            ke_ratio = [
                100.0 * r["ke"] / r["ie"] if r["ie"] > 1e-9 else float("nan")
                for r in erows
            ]
            ax_ke.plot(t, ke_ratio, color=color, lw=1.5, label=cid)
            if any(r.get("ae") is not None for r in erows):
                ae_ratio = [
                    (
                        100.0 * abs(r["ae"]) / r["ie"]
                        if r.get("ae") is not None and r["ie"] > 1e-9
                        else float("nan")
                    )
                    for r in erows
                ]
                ax_ae.plot(t, ae_ratio, color=color, lw=1.5, label=cid)

        ke_pct = en.get("max_ke_ie_ie_gt_1pct_peak")
        ae_pct = en.get("max_ae_ie")
        row = {
            "case_id": cid,
            "label": label,
            "load_rate_mm_min": case.get("load_rate_mm_min"),
            "slug": case.get("slug"),
            "K0_N_per_mm": fu.get("initial_stiffness_N_per_mm"),
            "peak_force_N": fu.get("peak_force_N"),
            "snap_u_mm": fu.get("snap_u_mm"),
            "snap_force_N": fu.get("snap_force_N"),
            "KE_IE_pct": (100.0 * ke_pct) if isinstance(ke_pct, (int, float)) else None,
            "AE_IE_pct": (100.0 * ae_pct) if isinstance(ae_pct, (int, float)) else None,
            "qs_pass": en.get("qs_pass"),
            "qs_warning": en.get("qs_warning"),
        }
        table_rows.append(row)
        if en.get("qs_warning"):
            print(f"[QS WARN] {cid}: {en['qs_warning']}", flush=True)

    ax_fu.set_xlabel("U (mm)")
    ax_fu.set_ylabel("F (N)")
    ax_fu.set_title("Force–displacement")
    ax_fu.grid(True, alpha=0.3)
    ax_fu.legend(fontsize=8)

    ax_ke.axhline(100.0 * ke_ie_limit, color="#C62828", ls="--", lw=1.1, label="5%")
    ax_ke.set_xlabel("time (s)")
    ax_ke.set_ylabel("KE/IE (%)")
    ax_ke.set_title("ALLKE / ALLIE")
    ax_ke.grid(True, alpha=0.3)
    ax_ke.legend(fontsize=8)

    ax_ae.axhline(100.0 * ke_ie_limit, color="#C62828", ls="--", lw=1.1, label="5%")
    ax_ae.set_xlabel("time (s)")
    ax_ae.set_ylabel("AE/IE (%)")
    ax_ae.set_title("ALLAE / ALLIE")
    ax_ae.grid(True, alpha=0.3)
    ax_ae.legend(fontsize=8)

    ax_tab.axis("off")
    lines = [
        "id   rate   K0     Fpeak   Usnap   KE/IE%  AE/IE%  QS",
        "--------------------------------------------------------",
    ]
    for r in table_rows:
        def _fmt(v: Any, nd: int = 3) -> str:
            if v is None or (isinstance(v, float) and not math.isfinite(v)):
                return "  nan"
            return f"{float(v):.{nd}g}"

        lines.append(
            f"{r['case_id']:<4} {_fmt(r['load_rate_mm_min'], 3):>5} "
            f"{_fmt(r['K0_N_per_mm']):>6} {_fmt(r['peak_force_N']):>7} "
            f"{_fmt(r['snap_u_mm']):>6} {_fmt(r['KE_IE_pct'], 2):>6} "
            f"{_fmt(r['AE_IE_pct'], 2):>6} "
            f"{'Y' if r['qs_pass'] else 'N'}"
        )
    ax_tab.text(
        0.02,
        0.98,
        "\n".join(lines),
        va="top",
        family="monospace",
        fontsize=9,
        transform=ax_tab.transAxes,
    )

    fig.suptitle(f"{study_name} — load-rate QS sweep", fontsize=12)
    fig.tight_layout()
    png = out_dir / f"{study_name}_compare.png"
    fig.savefig(png, dpi=140)

    json_path = out_dir / f"{study_name}_compare.json"
    # Strip heavy point arrays from JSON dump
    slim = []
    for case in cases:
        c = {k: v for k, v in case.items() if k != "evaluation"}
        ev = case.get("evaluation") or {}
        c["evaluation"] = {
            "fu": ev.get("fu"),
            "energy": {
                k: v
                for k, v in (ev.get("energy") or {}).items()
                if k not in ("")
            },
        }
        slim.append(c)
    json_path.write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")

    csv_path = out_dir / f"{study_name}_compare_table.csv"
    fields = [
        "case_id",
        "label",
        "load_rate_mm_min",
        "slug",
        "K0_N_per_mm",
        "peak_force_N",
        "snap_u_mm",
        "snap_force_N",
        "KE_IE_pct",
        "AE_IE_pct",
        "qs_pass",
        "qs_warning",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in table_rows:
            w.writerow(r)

    print(f"[compare] wrote {png}", flush=True)
    print(f"[compare] wrote {csv_path}", flush=True)
    return {
        "png": str(png),
        "json": str(json_path),
        "csv": str(csv_path),
    }


def write_mass_scale_comparison(
    cases: list[dict[str, Any]],
    out_dir: Path,
    *,
    study_name: str,
    ke_ie_limit: float = 0.05,
    peak_force_tol: float = 0.05,
    baseline_case_id: str = "MS0",
) -> dict[str, str]:
    """Compare mass-scaling variants; accept MS if |ΔFpeak|/F0 < peak_force_tol."""
    out_dir.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Baseline peak force
    f0 = None
    for case in cases:
        if case.get("case_id") == baseline_case_id:
            fu = (case.get("evaluation") or {}).get("fu") or {}
            f0 = fu.get("peak_force_N")
            break
    if f0 is None and cases:
        fu = (cases[0].get("evaluation") or {}).get("fu") or {}
        f0 = fu.get("peak_force_N")

    colors = ["#1565C0", "#E65100", "#2E7D32", "#6A1B9A", "#00838F"]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.2))
    ax_fu, ax_ke, ax_ae, ax_tab = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    table_rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases):
        color = colors[i % len(colors)]
        cid = case.get("case_id", f"C{i}")
        label = case.get("label", cid)
        eval_ = case.get("evaluation") or {}
        fu = eval_.get("fu") or {}
        en = eval_.get("energy") or {}
        pts = eval_.get("fu_points") or []
        erows = eval_.get("energy_rows") or []

        if pts:
            ax_fu.plot(
                [p[0] for p in pts],
                [p[1] for p in pts],
                color=color,
                lw=1.8,
                label=f"{cid}: {label}",
            )
        if erows:
            t = [r["t"] for r in erows]
            ke_ratio = [
                100.0 * r["ke"] / r["ie"] if r["ie"] > 1e-9 else float("nan")
                for r in erows
            ]
            ax_ke.plot(t, ke_ratio, color=color, lw=1.5, label=cid)
            if any(r.get("ae") is not None for r in erows):
                ae_ratio = [
                    (
                        100.0 * abs(r["ae"]) / r["ie"]
                        if r.get("ae") is not None and r["ie"] > 1e-9
                        else float("nan")
                    )
                    for r in erows
                ]
                ax_ae.plot(t, ae_ratio, color=color, lw=1.5, label=cid)

        ke_pct = en.get("max_ke_ie_ie_gt_1pct_peak")
        ae_pct = en.get("max_ae_ie")
        fpeak = fu.get("peak_force_N")
        dF_pct = None
        ms_ok = None
        if (
            isinstance(f0, (int, float))
            and isinstance(fpeak, (int, float))
            and abs(float(f0)) > 1e-12
            and math.isfinite(float(fpeak))
        ):
            dF_pct = 100.0 * abs(float(fpeak) - float(f0)) / abs(float(f0))
            ms_ok = dF_pct < 100.0 * peak_force_tol

        row = {
            "case_id": cid,
            "label": label,
            "load_rate_mm_min": case.get("load_rate_mm_min"),
            "mass_scaling_mode": case.get("mass_scaling_mode"),
            "target_dt_s": case.get("target_dt_s"),
            "dt_factor_vs_natural": case.get("dt_factor_vs_natural"),
            "slug": case.get("slug"),
            "K0_N_per_mm": fu.get("initial_stiffness_N_per_mm"),
            "peak_force_N": fpeak,
            "dFpeak_vs_MS0_pct": dF_pct,
            "ms_acceptable": ms_ok,
            "snap_u_mm": fu.get("snap_u_mm"),
            "snap_force_N": fu.get("snap_force_N"),
            "KE_IE_pct": (100.0 * ke_pct) if isinstance(ke_pct, (int, float)) else None,
            "AE_IE_pct": (100.0 * ae_pct) if isinstance(ae_pct, (int, float)) else None,
            "qs_pass": en.get("qs_pass"),
            "qs_warning": en.get("qs_warning"),
        }
        table_rows.append(row)
        if en.get("qs_warning"):
            print(f"[QS WARN] {cid}: {en['qs_warning']}", flush=True)
        if ms_ok is False:
            print(
                f"[MS WARN] {cid}: |ΔFpeak|={dF_pct:.2f}% ≥ "
                f"{100.0 * peak_force_tol:.1f}% vs {baseline_case_id}",
                flush=True,
            )
        elif ms_ok is True and cid != baseline_case_id:
            print(
                f"[MS OK] {cid}: |ΔFpeak|={dF_pct:.2f}% < "
                f"{100.0 * peak_force_tol:.1f}% vs {baseline_case_id}",
                flush=True,
            )

    ax_fu.set_xlabel("U (mm)")
    ax_fu.set_ylabel("F (N)")
    ax_fu.set_title("Force–displacement")
    ax_fu.grid(True, alpha=0.3)
    ax_fu.legend(fontsize=8)

    ax_ke.axhline(100.0 * ke_ie_limit, color="#C62828", ls="--", lw=1.1, label="5%")
    ax_ke.set_xlabel("time (s)")
    ax_ke.set_ylabel("KE/IE (%)")
    ax_ke.set_title("ALLKE / ALLIE")
    ax_ke.grid(True, alpha=0.3)
    ax_ke.legend(fontsize=8)

    ax_ae.axhline(100.0 * ke_ie_limit, color="#C62828", ls="--", lw=1.1, label="5%")
    ax_ae.set_xlabel("time (s)")
    ax_ae.set_ylabel("AE/IE (%)")
    ax_ae.set_title("ALLAE / ALLIE")
    ax_ae.grid(True, alpha=0.3)
    ax_ae.legend(fontsize=8)

    ax_tab.axis("off")
    lines = [
        "id   dt×nat  K0     Fpeak  dF%   KE/IE  AE/IE  QS  MS",
        "-----------------------------------------------------------",
    ]

    def _fmt(v: Any, nd: int = 3) -> str:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return "  nan"
        return f"{float(v):.{nd}g}"

    for r in table_rows:
        fac = r.get("dt_factor_vs_natural")
        fac_s = "0" if fac is None else _fmt(fac, 2)
        ms_s = (
            "-"
            if r["ms_acceptable"] is None
            else ("Y" if r["ms_acceptable"] else "N")
        )
        lines.append(
            f"{r['case_id']:<4} {fac_s:>6} {_fmt(r['K0_N_per_mm']):>6} "
            f"{_fmt(r['peak_force_N']):>6} {_fmt(r['dFpeak_vs_MS0_pct'], 2):>5} "
            f"{_fmt(r['KE_IE_pct'], 2):>5} {_fmt(r['AE_IE_pct'], 2):>5} "
            f"{'Y' if r['qs_pass'] else 'N':>3} {ms_s:>3}"
        )
    ax_tab.text(
        0.02,
        0.98,
        "\n".join(lines),
        va="top",
        family="monospace",
        fontsize=8.5,
        transform=ax_tab.transAxes,
    )

    fig.suptitle(
        f"{study_name} — mass-scaling QS (rate fixed; MS OK if |ΔF|<{100*peak_force_tol:.0f}%)",
        fontsize=11,
    )
    fig.tight_layout()
    png = out_dir / f"{study_name}_compare.png"
    fig.savefig(png, dpi=140)

    json_path = out_dir / f"{study_name}_compare.json"
    slim = []
    for case in cases:
        c = {k: v for k, v in case.items() if k != "evaluation"}
        ev = case.get("evaluation") or {}
        c["evaluation"] = {"fu": ev.get("fu"), "energy": ev.get("energy")}
        slim.append(c)
    # Attach acceptance summary
    summary = {
        "baseline_case_id": baseline_case_id,
        "baseline_peak_force_N": f0,
        "peak_force_tol": peak_force_tol,
        "ke_ie_limit": ke_ie_limit,
        "table": table_rows,
    }
    json_path.write_text(
        json.dumps({"summary": summary, "cases": slim}, indent=2, default=str),
        encoding="utf-8",
    )

    csv_path = out_dir / f"{study_name}_compare_table.csv"
    fields = [
        "case_id",
        "label",
        "load_rate_mm_min",
        "mass_scaling_mode",
        "target_dt_s",
        "dt_factor_vs_natural",
        "slug",
        "K0_N_per_mm",
        "peak_force_N",
        "dFpeak_vs_MS0_pct",
        "ms_acceptable",
        "snap_u_mm",
        "snap_force_N",
        "KE_IE_pct",
        "AE_IE_pct",
        "qs_pass",
        "qs_warning",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in table_rows:
            w.writerow(r)

    print(f"[compare] wrote {png}", flush=True)
    print(f"[compare] wrote {csv_path}", flush=True)
    return {
        "png": str(png),
        "json": str(json_path),
        "csv": str(csv_path),
    }


def write_qs_opt_comparison(
    cases: list[dict[str, Any]],
    out_dir: Path,
    *,
    study_name: str,
    ke_ie_limit: float = 0.05,
    peak_force_tol: float = 0.05,
    baseline_case_id: str = "A",
) -> dict[str, str]:
    """Compare QS-opt A/B/C: KE/IE<5% and |ΔFpeak| vs baseline <5%."""
    out_dir.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f0 = None
    for case in cases:
        if case.get("case_id") == baseline_case_id:
            fu = (case.get("evaluation") or {}).get("fu") or {}
            f0 = fu.get("peak_force_N")
            break
    if f0 is None and cases:
        fu = (cases[0].get("evaluation") or {}).get("fu") or {}
        f0 = fu.get("peak_force_N")

    colors = ["#1565C0", "#E65100", "#2E7D32", "#6A1B9A"]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.2))
    ax_fu, ax_ke, ax_ae, ax_tab = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]
    table_rows: list[dict[str, Any]] = []

    for i, case in enumerate(cases):
        color = colors[i % len(colors)]
        cid = case.get("case_id", f"C{i}")
        label = case.get("label", cid)
        eval_ = case.get("evaluation") or {}
        fu = eval_.get("fu") or {}
        en = eval_.get("energy") or {}
        pts = eval_.get("fu_points") or []
        erows = eval_.get("energy_rows") or []

        if pts:
            ax_fu.plot(
                [p[0] for p in pts],
                [p[1] for p in pts],
                color=color,
                lw=1.8,
                label=f"{cid}: {label}",
            )
        if erows:
            t = [r["t"] for r in erows]
            ax_ke.plot(
                t,
                [
                    100.0 * r["ke"] / r["ie"] if r["ie"] > 1e-9 else float("nan")
                    for r in erows
                ],
                color=color,
                lw=1.5,
                label=cid,
            )
            ax_ae.plot(
                t,
                [
                    (
                        100.0 * abs(r["ae"]) / r["ie"]
                        if r.get("ae") is not None and r["ie"] > 1e-9
                        else float("nan")
                    )
                    for r in erows
                ],
                color=color,
                lw=1.5,
                label=cid,
            )

        ke_pct = en.get("max_ke_ie_ie_gt_1pct_peak")
        ae_pct = en.get("max_ae_ie")
        fpeak = fu.get("peak_force_N")
        dF_pct = None
        force_ok = None
        if (
            isinstance(f0, (int, float))
            and isinstance(fpeak, (int, float))
            and abs(float(f0)) > 1e-12
            and math.isfinite(float(fpeak))
        ):
            dF_pct = 100.0 * abs(float(fpeak) - float(f0)) / abs(float(f0))
            force_ok = dF_pct < 100.0 * peak_force_tol

        row = {
            "case_id": cid,
            "label": label,
            "load_rate_mm_min": case.get("load_rate_mm_min"),
            "ms_dt_factor": case.get("ms_dt_factor"),
            "target_dt_s": case.get("target_dt_s"),
            "slug": case.get("slug"),
            "K0_N_per_mm": fu.get("initial_stiffness_N_per_mm"),
            "peak_force_N": fpeak,
            "dFpeak_vs_baseline_pct": dF_pct,
            "force_change_ok": force_ok,
            "KE_IE_pct": (100.0 * ke_pct) if isinstance(ke_pct, (int, float)) else None,
            "AE_IE_pct": (100.0 * ae_pct) if isinstance(ae_pct, (int, float)) else None,
            "qs_pass": en.get("qs_pass"),
            "qs_warning": en.get("qs_warning"),
        }
        table_rows.append(row)
        if en.get("qs_warning"):
            print(f"[QS WARN] {cid}: {en['qs_warning']}", flush=True)
        if force_ok is False:
            print(
                f"[ΔF WARN] {cid}: |ΔFpeak|={dF_pct:.2f}% ≥ {100*peak_force_tol:.1f}% "
                f"vs {baseline_case_id}",
                flush=True,
            )

    ax_fu.set_xlabel("U (mm)")
    ax_fu.set_ylabel("F (N)")
    ax_fu.set_title("Force–displacement")
    ax_fu.grid(True, alpha=0.3)
    ax_fu.legend(fontsize=8)

    ax_ke.axhline(100.0 * ke_ie_limit, color="#C62828", ls="--", lw=1.1, label="5%")
    ax_ke.set_xlabel("time (s)")
    ax_ke.set_ylabel("KE/IE (%)")
    ax_ke.set_title("ALLKE / ALLIE")
    ax_ke.grid(True, alpha=0.3)
    ax_ke.legend(fontsize=8)

    ax_ae.axhline(100.0 * ke_ie_limit, color="#C62828", ls="--", lw=1.1, label="5%")
    ax_ae.set_xlabel("time (s)")
    ax_ae.set_ylabel("AE/IE (%)")
    ax_ae.set_title("ALLAE / ALLIE")
    ax_ae.grid(True, alpha=0.3)
    ax_ae.legend(fontsize=8)

    ax_tab.axis("off")

    def _fmt(v: Any, nd: int = 3) -> str:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return " nan"
        return f"{float(v):.{nd}g}"

    lines = [
        "id  rate  MSx   K0    Fpeak  dF%  KE/IE AE/IE QS ΔF",
        "-------------------------------------------------------",
    ]
    for r in table_rows:
        lines.append(
            f"{r['case_id']:<3} {_fmt(r['load_rate_mm_min'], 2):>5} "
            f"{_fmt(r['ms_dt_factor'], 2):>4} {_fmt(r['K0_N_per_mm']):>6} "
            f"{_fmt(r['peak_force_N']):>6} {_fmt(r['dFpeak_vs_baseline_pct'], 2):>5} "
            f"{_fmt(r['KE_IE_pct'], 2):>5} {_fmt(r['AE_IE_pct'], 2):>5} "
            f"{'Y' if r['qs_pass'] else 'N':>2} "
            f"{'-' if r['force_change_ok'] is None else ('Y' if r['force_change_ok'] else 'N'):>2}"
        )
    ax_tab.text(
        0.02,
        0.98,
        "\n".join(lines),
        va="top",
        family="monospace",
        fontsize=8.5,
        transform=ax_tab.transAxes,
    )
    fig.suptitle(
        f"{study_name} — QS opt (KE/IE<{100*ke_ie_limit:.0f}%, |ΔF|<{100*peak_force_tol:.0f}% vs {baseline_case_id})",
        fontsize=11,
    )
    fig.tight_layout()
    png = out_dir / f"{study_name}_compare.png"
    fig.savefig(png, dpi=140)

    json_path = out_dir / f"{study_name}_compare.json"
    slim = []
    for case in cases:
        c = {k: v for k, v in case.items() if k != "evaluation"}
        ev = case.get("evaluation") or {}
        c["evaluation"] = {"fu": ev.get("fu"), "energy": ev.get("energy")}
        slim.append(c)
    json_path.write_text(
        json.dumps(
            {
                "summary": {
                    "baseline_case_id": baseline_case_id,
                    "baseline_peak_force_N": f0,
                    "ke_ie_limit": ke_ie_limit,
                    "peak_force_tol": peak_force_tol,
                    "table": table_rows,
                },
                "cases": slim,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    csv_path = out_dir / f"{study_name}_compare_table.csv"
    fields = [
        "case_id",
        "label",
        "load_rate_mm_min",
        "ms_dt_factor",
        "target_dt_s",
        "slug",
        "K0_N_per_mm",
        "peak_force_N",
        "dFpeak_vs_baseline_pct",
        "force_change_ok",
        "KE_IE_pct",
        "AE_IE_pct",
        "qs_pass",
        "qs_warning",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in table_rows:
            w.writerow(r)

    print(f"[compare] wrote {png}", flush=True)
    print(f"[compare] wrote {csv_path}", flush=True)
    return {"png": str(png), "json": str(json_path), "csv": str(csv_path)}

