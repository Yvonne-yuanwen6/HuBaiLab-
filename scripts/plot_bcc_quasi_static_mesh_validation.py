"""
Plot BCC quasi-static energy + mesh-size F–u curves (Fig.2.10 style).

Energy: prefer post/*_energy.csv (from extract_odb_energy_py2.py); else parse .sta KE.
Force: convert engineering_stress_strain.csv via meta height/area.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.mesh.bcc_mesh_validation import BCC_MESH_SEED_LEVELS, slug_for_bcc_level
from src.paths import ABAQUS_JOBS, ABAQUS_POST, EXPORT_ROOT, REPORTS_ROOT
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese


def load_meta(slug: str) -> dict:
    p = EXPORT_ROOT / slug / f"{slug}_meta.json"
    if not p.is_file():
        return {"reference_height_mm": 80.0, "reference_area_mm2": 6400.0}
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def load_energy_csv(path: Path) -> list[tuple[float, float, float]]:
    rows: list[tuple[float, float, float]] = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                (
                    float(row["time_s"]),
                    float(row["ALLKE_J"]),
                    float(row["ALLIE_J"]),
                )
            )
    return rows


def load_force_disp(
    csv_path: Path,
    *,
    height_mm: float,
    area_mm2: float,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        has_u = "U3_mm" in fields or "displacement_mm" in fields
        has_rf = "RF3_N" in fields or "force_N" in fields
        for row in reader:
            if has_u and has_rf:
                u_key = "U3_mm" if "U3_mm" in fields else "displacement_mm"
                f_key = "RF3_N" if "RF3_N" in fields else "force_N"
                u = abs(float(row[u_key]))
                fr = abs(float(row[f_key]))
            elif "engineering_strain" in fields and "engineering_stress_MPa" in fields:
                u = abs(float(row["engineering_strain"])) * height_mm
                fr = abs(float(row["engineering_stress_MPa"])) * area_mm2
            else:
                continue
            pts.append((u, fr))
    return pts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-png",
        default=str(REPORTS_ROOT / "mesh_convergence" / "bcc_quasi_static_mesh_validation.png"),
    )
    parser.add_argument(
        "--out-json",
        default=str(REPORTS_ROOT / "mesh_convergence" / "bcc_quasi_static_mesh_validation.json"),
    )
    parser.add_argument("--energy-slug", default="")
    parser.add_argument(
        "--only-complete",
        action="store_true",
        help="Only plot levels whose .sta contains COMPLETED SUCCESSFULLY "
        "(skips partial CSVs from crashed jobs).",
    )
    parser.add_argument(
        "--ids",
        default="",
        help="Comma-separated level ids to include (e.g. s06,s07,s08,s10,s12).",
    )
    args = parser.parse_args()
    id_filter = {x.strip() for x in args.ids.split(",") if x.strip()}

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    configure_matplotlib_chinese()

    summary: dict = {"levels": [], "energy": {}}
    energy_slug = args.energy_slug or slug_for_bcc_level(BCC_MESH_SEED_LEVELS[0])
    energy_csv = ABAQUS_POST / energy_slug / f"{energy_slug}_energy.csv"
    if not energy_csv.is_file():
        print(f"[ERROR] missing energy CSV: {energy_csv}")
        print("  Run: abq python scripts/extract_odb_energy_py2.py ODB CSV")
        return 1
    energy_rows = load_energy_csv(energy_csv)
    if not energy_rows:
        print(f"[ERROR] empty energy CSV: {energy_csv}")
        return 1

    t = [r[0] for r in energy_rows]
    ke = [r[1] for r in energy_rows]
    ie = [r[2] for r in energy_rows]
    ratios_all = [abs(k) / i for k, i in zip(ke, ie) if i > 1e-9]
    ie_peak = max(ie) if ie else 0.0
    ratios_stable = [
        abs(k) / i for k, i in zip(ke, ie) if ie_peak > 0 and i > 0.01 * ie_peak
    ]
    max_ratio = max(ratios_stable) if ratios_stable else (
        max(ratios_all) if ratios_all else float("nan")
    )
    max_ratio_raw = max(ratios_all) if ratios_all else float("nan")
    summary["energy"] = {
        "slug": energy_slug,
        "max_ke_over_ie": max_ratio,
        "max_ke_over_ie_raw": max_ratio_raw,
        "n_points": len(energy_rows),
        "source": str(energy_csv),
        "ie_peak_J": ie_peak,
        "ke_peak_J": max(abs(k) for k in ke) if ke else 0.0,
    }

    fd_series: list[tuple[str, list[tuple[float, float]]]] = []
    for lv in BCC_MESH_SEED_LEVELS:
        if id_filter and lv["id"] not in id_filter:
            continue
        slug = slug_for_bcc_level(lv)
        meta = load_meta(slug)
        h = float(meta.get("reference_height_mm", 80.0))
        a = float(meta.get("reference_area_mm2", 6400.0))
        csv_path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        sta_path = ABAQUS_JOBS / slug / f"{slug}.sta"
        job_complete = False
        if sta_path.is_file():
            try:
                job_complete = "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta_path.read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                job_complete = False
        entry = {
            "id": lv["id"],
            "label": lv["label"],
            "seed_mm": lv["cae_seed_mm"],
            "slug": slug,
            "csv": str(csv_path),
            "status": "missing",
            "height_mm": h,
            "area_mm2": a,
            "job_complete": job_complete,
        }
        if args.only_complete and not job_complete:
            entry["status"] = "incomplete"
            if csv_path.is_file():
                pts = load_force_disp(csv_path, height_mm=h, area_mm2=a)
                if pts:
                    entry["n_points"] = len(pts)
            summary["levels"].append(entry)
            continue
        if csv_path.is_file():
            pts = load_force_disp(csv_path, height_mm=h, area_mm2=a)
            if pts:
                fd_series.append((lv["label"], pts))
                entry["status"] = "ok"
                entry["n_points"] = len(pts)
            else:
                entry["status"] = "empty_csv"
        summary["levels"].append(entry)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.4), dpi=160)
    ax1.plot(t, ie, color="#4FC3F7", linewidth=2.2, label="内能 ALLIE")
    ax1.plot(t, ke, color="#FF7043", linewidth=2.0, label="动能 ALLKE")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Energy (J)")
    ax1.set_title("(a) 准静态能量检查")
    ax1.legend(fontsize=9, loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.text(
        0.98,
        0.05,
        f"max KE/IE = {max_ratio * 100:.2f}%",
        transform=ax1.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85, edgecolor="#bbb"),
    )

    cmap = plt.cm.viridis
    n_fd = max(len(fd_series) - 1, 1)
    colors = [cmap(0.08 + 0.84 * i / n_fd) for i in range(len(fd_series))]
    for (lab, pts), c in zip(fd_series, colors):
        ax2.plot([p[0] for p in pts], [p[1] for p in pts], color=c, linewidth=1.5, label=lab)
    ax2.set_xlabel("Displacement (mm)")
    ax2.set_ylabel("Force (N)")
    ax2.set_title("(b) 网格尺寸敏感性")
    if fd_series:
        ax2.legend(
            title="mesh size (mm)",
            fontsize=7,
            title_fontsize=8,
            ncol=2 if len(fd_series) > 5 else 1,
            loc="upper left",
        )
    else:
        ax2.text(0.5, 0.5, "等待 mesh 工况 CSV…", ha="center", va="center", transform=ax2.transAxes)
    ax2.grid(True, alpha=0.3)

    if len(fd_series) >= 2:
        axins = ax2.inset_axes([0.45, 0.12, 0.50, 0.38])
        u_cut = 12.0
        for (lab, pts), c in zip(fd_series, colors):
            xs = [p[0] for p in pts if p[0] <= u_cut]
            ys = [p[1] for p in pts if p[0] <= u_cut]
            if xs:
                axins.plot(xs, ys, color=c, linewidth=1.0)
        axins.set_xlim(0, u_cut)
        axins.grid(True, alpha=0.25)
        axins.tick_params(labelsize=7)
        ax2.indicate_inset_zoom(axins, edgecolor="gray")

    fig.suptitle("BCC 4×4×4 准静态压缩能量响应与网格尺寸效应 (CAE C3D4)", fontsize=12)
    fig.tight_layout()
    out_png = Path(args.out_png)
    out_json = Path(args.out_json)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Saved:", out_png)
    print("Saved:", out_json)
    print(f"Energy max KE/IE = {max_ratio * 100:.3f}%  ({energy_slug})")
    print(f"Force–disp curves available: {len(fd_series)} / {len(BCC_MESH_SEED_LEVELS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
