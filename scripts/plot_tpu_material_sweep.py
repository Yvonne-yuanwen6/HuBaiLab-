"""
Overlay Fig.2.5 reference with available TPU material probe / direct-fit curves.

  py -3 scripts/plot_tpu_material_sweep.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.evaluate_tpu_material_fit import PROBE_PREFIX, load_csv_curve
from scripts.fit_tpu_hyperelastic_direct import OUT_DIR, fit_all, plot_overlay
from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON, load_tpu_fig25_uniaxial
from src.paths import ABAQUS_POST, REPORTS_ROOT


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig25-json", type=Path, default=DEFAULT_TPU_FIG25_JSON)
    ap.add_argument(
        "--include-direct-fit",
        action="store_true",
        help="Also run direct fit if direct_fit_report.json is missing",
    )
    args = ap.parse_args()

    ref = load_tpu_fig25_uniaxial(args.fig25_json)
    probe: dict[str, list[tuple[float, float]]] = {}
    for name in ("elastic", "neo_hooke", "marlow", "polynomial", "ogden_n2", "reduced_poly_n2"):
        slug = f"{PROBE_PREFIX}_{name}"
        pts = load_csv_curve(ABAQUS_POST / slug / f"{slug}_stress_strain.csv")
        if pts:
            probe[name] = pts

    report_path = OUT_DIR / "direct_fit_report.json"
    if report_path.is_file():
        import json

        raw = json.loads(report_path.read_text(encoding="utf-8"))
        report = {
            "best_model": raw.get("best_model"),
            "ranking_rmse": raw.get("ranking_rmse", []),
            "models": {
                k: {
                    "curve": load_csv_curve(OUT_DIR / f"{k}_stress_strain.csv"),
                    "score_full": v.get("score_full", {}),
                }
                for k, v in (raw.get("models") or {}).items()
            },
        }
    elif args.include_direct_fit:
        eps_max = max(e for e, _ in ref)
        report = fit_all(ref, eps_max=eps_max)
    else:
        report = {"best_model": None, "ranking_rmse": [], "models": {}}

    out_png = REPORTS_ROOT / "tpu_material_fit" / "tpu_material_probe_overlay.png"
    plot_overlay(ref, report, probe, out_png)
    print(f"Saved: {out_png}")
    if probe:
        print("Probe curves:", ", ".join(sorted(probe.keys())))
    else:
        print("No probe CSV found under output/post/tpu_mat_*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
