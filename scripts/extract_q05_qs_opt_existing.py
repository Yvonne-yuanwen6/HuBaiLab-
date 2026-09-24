#!/usr/bin/env python3
"""Extract / summarize completed QS-opt cases (A, B)."""
from __future__ import annotations

import json
from pathlib import Path

from src.study.uc_explicit_qs.deform_snapshots import summarize_snap_proxy
from src.study.uc_explicit_qs.metrics import evaluate_case

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "output" / "reports" / "q05_uc_c3d10m_qs_opt"

CASES = [
    ("A", "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_1mmin_uc_c3d10m_r3_MS5", 1.0, 5),
    ("B", "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_0p5mmin_uc_c3d10m_r3_BMS5", 0.5, 5),
]


def main() -> int:
    rows = []
    f0 = None
    for cid, slug, rate, ms in CASES:
        post = ROOT / "output" / "post" / slug
        ss = post / f"{slug}_stress_strain.csv"
        en = post / f"{slug}_energy.csv"
        ev = evaluate_case(stress_strain_csv=ss, energy_csv=en, ke_ie_limit=0.05)
        fu, e = ev["fu"], ev["energy"]
        if f0 is None:
            f0 = float(fu["peak_force_N"])
        dF = 100.0 * abs(float(fu["peak_force_N"]) - f0) / abs(f0)
        snap = summarize_snap_proxy(ev["fu_points"])
        ke = 100.0 * float(e["max_ke_ie_ie_gt_1pct_peak"])
        ae = 100.0 * float(e["max_ae_ie"] or 0.0)
        row = {
            "case_id": cid,
            "label": f"{rate:g} mm/min + MS{ms}",
            "slug": slug,
            "load_rate_mm_min": rate,
            "ms_dt_factor": ms,
            "peak_force_N": fu["peak_force_N"],
            "K0_N_per_mm": fu["initial_stiffness_N_per_mm"],
            "KE_IE_pct": ke,
            "AE_IE_pct": ae,
            "qs_pass": e["qs_pass"],
            "dFpeak_vs_A_pct": dF,
            "force_change_ok": dF < 5.0,
            "snap_proxy": snap,
            "history_csv": str(post / f"{slug}_history.csv"),
            "stress_strain_csv": str(ss),
            "energy_csv": str(en),
            "deform_index": str(post / "deform_frames" / "deform_frames_index.csv"),
        }
        rows.append(row)
        print(
            f"{cid}: Fpeak={fu['peak_force_N']:.2f} N  "
            f"K0={fu['initial_stiffness_N_per_mm']:.3f}  "
            f"KE/IE={ke:.2f}%  AE/IE={ae:.2f}%  "
            f"dF vs A={dF:.2f}%  QS={e['qs_pass']}  "
            f"snap={snap.get('snap_detected')}"
        )

    out = {
        "study": "q05_uc_c3d10m_qs_opt",
        "note": "C (0.5 mm/min + MS3) incomplete due to MPI abort; extracted A/B only.",
        "criteria": {"ke_ie_limit": 0.05, "peak_force_tol": 0.05, "baseline": "A"},
        "cases": rows,
        "artifacts": {
            "compare_png": str(REP / "q05_uc_c3d10m_qs_opt_compare.png"),
            "compare_csv": str(REP / "q05_uc_c3d10m_qs_opt_compare_table.csv"),
            "paper_dir": str(REP / "paper"),
            "elem_12488": str(REP / "elem_12488_location.json"),
            "deform_dir": str(REP / "deform"),
        },
    }
    REP.mkdir(parents=True, exist_ok=True)
    path = REP / "extracted_summary.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
