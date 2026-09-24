#!/usr/bin/env python3
"""Compare Q0.5 unit-cell C3D4-r3 / C3D4-r5 / C3D10M-r3: F-U + energy (ALLKE/ALLIE/ALLAE)."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "reports" / "q05_uc_elem_mesh_study"

CASES = [
    (
        "A",
        "C3D4 rods/d=3",
        "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d4_r3",
        "#1565C0",
    ),
    (
        "B",
        "C3D4 rods/d=5",
        "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p4mm80_5mmin_uc_c3d4_r5",
        "#E65100",
    ),
    (
        "C",
        "C3D10M rods/d=3",
        "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d10m_r3",
        "#2E7D32",
    ),
]


def _f(row: dict, *keys: str) -> float | None:
    for k in keys:
        if k in row and row[k] not in ("", None):
            try:
                return float(row[k])
            except ValueError:
                pass
    return None


def load_fu(path: Path) -> list[tuple[float, float]]:
    if not path.is_file():
        return []
    pts: list[tuple[float, float]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            u = _f(row, "U3_mm", "displacement_mm")
            fr = _f(row, "RF3_N", "force_N")
            if u is None or fr is None:
                eps = _f(row, "engineering_strain")
                sig = _f(row, "engineering_stress_MPa")
                if eps is None or sig is None:
                    continue
                # UC L=20, area ~ L^2 = 400 mm^2 for engineering F from stress
                u = abs(eps) * 20.0
                fr = abs(sig) * 400.0
            pts.append((abs(u), abs(fr)))
    return pts


def load_energy(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = _f(row, "time_s", "time") or 0.0
            ke = abs(_f(row, "ALLKE_J", "ALLKE") or 0.0)
            ie = _f(row, "ALLIE_J", "ALLIE") or 0.0
            ae = _f(row, "ALLAE_J", "ALLAE")
            rows.append({"t": t, "ke": ke, "ie": ie, "ae": ae})
    return rows


def metrics_fu(pts: list[tuple[float, float]]) -> dict:
    if len(pts) < 3:
        return {"ok": False}
    # initial stiffness: linear fit on first points with u in (0.2, 1.0] mm
    early = [(u, f) for u, f in pts if 0.2 < u <= 1.0]
    if len(early) < 2:
        early = pts[1 : min(8, len(pts))]
    k = float("nan")
    if len(early) >= 2:
        u0, f0 = early[0]
        u1, f1 = early[-1]
        if abs(u1 - u0) > 1e-9:
            k = (f1 - f0) / (u1 - u0)
    peak_f = max(f for _, f in pts)
    peak_u = max((u for u, f in pts if f == peak_f), default=float("nan"))
    # snap: first local max then drop > 8% of peak
    snap_u = float("nan")
    snap_f = float("nan")
    for i in range(2, len(pts) - 2):
        u, f = pts[i]
        if f >= pts[i - 1][1] and f >= pts[i + 1][1] and f > 0.5 * peak_f:
            # look ahead for drop
            later = pts[i + 1 : i + 20]
            if later and min(x[1] for x in later) < 0.92 * f:
                snap_u, snap_f = u, f
                break
    return {
        "ok": True,
        "n": len(pts),
        "u_max_mm": pts[-1][0],
        "initial_stiffness_N_per_mm": k,
        "peak_force_N": peak_f,
        "peak_u_mm": peak_u,
        "snap_u_mm": snap_u,
        "snap_force_N": snap_f,
    }


def metrics_energy(rows: list[dict]) -> dict:
    if not rows:
        return {"ok": False}
    ratios_ke = []
    ratios_ae = []
    for r in rows:
        if r["ie"] > 1e-9:
            ratios_ke.append(r["ke"] / r["ie"])
            if r["ae"] is not None:
                ratios_ae.append(abs(r["ae"]) / r["ie"])
    n = len(ratios_ke)
    tail = ratios_ke[max(0, int(0.05 * n)) :] if n else []
    max_tail = max(tail) if tail else (max(ratios_ke) if ratios_ke else float("nan"))
    max_ae = max(ratios_ae) if ratios_ae else float("nan")
    return {
        "ok": True,
        "n": len(rows),
        "max_ke_ie_after_5pct": max_tail,
        "qs_pass": bool(math.isfinite(max_tail) and max_tail < 0.05),
        "max_ae_ie": max_ae if ratios_ae else None,
        "allie_peak_J": max(r["ie"] for r in rows),
        "allke_peak_J": max(r["ke"] for r in rows),
        "allae_peak_J": (
            max(abs(r["ae"]) for r in rows if r["ae"] is not None)
            if any(r["ae"] is not None for r in rows)
            else None
        ),
    }


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    ax_fu, ax_ke, ax_ae, ax_tab = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    for cid, label, slug, color in CASES:
        fu_path = ROOT / "output" / "post" / slug / f"{slug}_stress_strain.csv"
        if not fu_path.is_file():
            # try hot / raw
            for alt in (
                f"{slug}_stress_strain_hot.csv",
                f"{slug}_stress_strain_raw.csv",
            ):
                p = ROOT / "output" / "post" / slug / alt
                if p.is_file():
                    fu_path = p
                    break
        en_path = ROOT / "output" / "post" / slug / f"{slug}_energy.csv"
        pts = load_fu(fu_path)
        en = load_energy(en_path)
        fu_m = metrics_fu(pts)
        en_m = metrics_energy(en)
        entry = {
            "id": cid,
            "label": label,
            "slug": slug,
            "fu_csv": str(fu_path) if fu_path.is_file() else None,
            "energy_csv": str(en_path) if en_path.is_file() else None,
            "fu": fu_m,
            "energy": en_m,
        }
        summary.append(entry)
        if pts:
            ax_fu.plot(
                [p[0] for p in pts],
                [p[1] for p in pts],
                color=color,
                lw=1.8,
                label=f"{cid}: {label}",
            )
        if en:
            t = [r["t"] for r in en]
            ratio = [
                (100.0 * r["ke"] / r["ie"] if r["ie"] > 1e-9 else float("nan"))
                for r in en
            ]
            ax_ke.plot(t, ratio, color=color, lw=1.6, label=cid)
            if any(r["ae"] is not None for r in en):
                ae_ratio = [
                    (
                        100.0 * abs(r["ae"]) / r["ie"]
                        if r["ae"] is not None and r["ie"] > 1e-9
                        else float("nan")
                    )
                    for r in en
                ]
                ax_ae.plot(t, ae_ratio, color=color, lw=1.6, label=cid)

    ax_fu.set_xlabel("U (mm)")
    ax_fu.set_ylabel("F (N)")
    ax_fu.set_title("F–U")
    ax_fu.grid(True, alpha=0.3)
    ax_fu.legend(fontsize=8)

    ax_ke.axhline(5.0, color="#C62828", ls="--", lw=1.0, label="5%")
    ax_ke.set_xlabel("time (s)")
    ax_ke.set_ylabel("KE/IE (%)")
    ax_ke.set_title("ALLKE / ALLIE")
    ax_ke.grid(True, alpha=0.3)
    ax_ke.legend(fontsize=8)

    ax_ae.axhline(5.0, color="#C62828", ls="--", lw=1.0, label="5%")
    ax_ae.set_xlabel("time (s)")
    ax_ae.set_ylabel("AE/IE (%)")
    ax_ae.set_title("ALLAE / ALLIE")
    ax_ae.grid(True, alpha=0.3)
    ax_ae.legend(fontsize=8)

    ax_tab.axis("off")
    lines = ["id  K0(N/mm)  Fpeak(N)  Usnap(mm)  KE/IE%  AE/IE%  QS"]
    for e in summary:
        fu = e["fu"]
        en = e["energy"]
        if not fu.get("ok"):
            lines.append(f"{e['id']}  (no F-U yet)")
            continue
        ke_pct = (
            100.0 * en["max_ke_ie_after_5pct"]
            if en.get("ok") and en.get("max_ke_ie_after_5pct") is not None
            else float("nan")
        )
        ae_pct = (
            100.0 * en["max_ae_ie"]
            if en.get("ok") and en.get("max_ae_ie") is not None
            else float("nan")
        )
        qs = "Y" if en.get("qs_pass") else ("N" if en.get("ok") else "?")
        lines.append(
            f"{e['id']}  {fu['initial_stiffness_N_per_mm']:.3g}  "
            f"{fu['peak_force_N']:.3g}  {fu['snap_u_mm']:.3g}  "
            f"{ke_pct:.2f}  {ae_pct:.2f}  {qs}"
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

    fig.suptitle("Q0.5 unit cell — element / mesh study", fontsize=12)
    fig.tight_layout()
    png = OUT / "q05_uc_elem_mesh_compare.png"
    fig.savefig(png, dpi=140)
    js = OUT / "q05_uc_elem_mesh_compare.json"
    js.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("wrote", png)
    print("wrote", js)
    for e in summary:
        print(
            e["id"],
            e["label"],
            "fu_ok=",
            e["fu"].get("ok"),
            "energy_ok=",
            e["energy"].get("ok"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
