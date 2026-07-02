"""Score mesh-convergence variants vs Fig.3.3 Q0.5 experiment."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.analyze_paperbox_snapthrough import detect_snapthrough
from scripts.evaluate_paperbox_q05_trend import evaluate_q05
from src.mesh.mesh_convergence import FIG33_Q05_KEY, Q05_MESH_CONVERGENCE_LEVELS, slug_for_q05_level
from src.paths import ABAQUS_POST, EXPORT_ROOT, REPORTS_ROOT
from src.postprocess.compression_curve import estimate_densification_strain
from src.postprocess.fig33_plot_style import load_fig33_reference, stress_at_strain


def _load_pts(slug: str) -> list[tuple[float, float]]:
    path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
    if not path.is_file():
        return []
    pts: list[tuple[float, float]] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pts.append((float(row["engineering_strain"]), float(row["engineering_stress_MPa"])))
    return pts


def _interp(pts: list[tuple[float, float]], target: float) -> float | None:
    for i in range(1, len(pts)):
        e0, s0 = pts[i - 1]
        e1, s1 = pts[i]
        if e1 >= target:
            if e1 == e0:
                return s1
            return s0 + (s1 - s0) * (target - e0) / (e1 - e0)
    return None


def rmse_vs_fig33(slug: str) -> float | None:
    ref = load_fig33_reference()
    ref_pts = ref["series"][FIG33_Q05_KEY]["points"]
    pts = _load_pts(slug)
    if len(pts) < 5:
        return None
    errs: list[float] = []
    for i in range(1, 33):
        e = i / 40.0
        rs = stress_at_strain(ref_pts, e)
        ss = _interp(pts, e)
        if rs is None or ss is None:
            continue
        errs.append((ss - rs) ** 2)
    if len(errs) < 10:
        return None
    return math.sqrt(sum(errs) / len(errs))


def mesh_stats_for_slug(slug: str) -> dict:
    manifest = EXPORT_ROOT / slug / "case_manifest.json"
    mesh_manifest = EXPORT_ROOT / slug / f"{slug}_cae_mesh_manifest.json"
    out: dict = {"slug": slug}
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        mesh = data.get("mesh") or {}
        out.update(
            {
                "node_count": mesh.get("node_count"),
                "element_count": mesh.get("element_count"),
                "cae_seed_mm": mesh.get("cae_seed_mm"),
                "cae_mesh_quality": mesh.get("cae_mesh_quality"),
                "cae_rods_per_diameter": mesh.get("cae_rods_per_diameter"),
            }
        )
    if mesh_manifest.is_file():
        mm = json.loads(mesh_manifest.read_text(encoding="utf-8"))
        out["mesh_manifest"] = mm
        out.setdefault("node_count", mm.get("node_count"))
        out.setdefault("element_count", mm.get("element_count"))
    return out


def evaluate_level(level: dict) -> dict:
    slug = slug_for_q05_level(level)
    row: dict = {
        "level_id": level["id"],
        "label": level["label"],
        "slug": slug,
        "mesh_params": {
            "cae_seed_mm": level["cae_seed_mm"],
            "cae_rods_per_diameter": level["cae_rods_per_diameter"],
            "cae_mesh_quality": level["cae_mesh_quality"],
        },
    }
    row.update(mesh_stats_for_slug(slug))

    pts = _load_pts(slug)
    row["csv_found"] = bool(pts)
    if not pts:
        row["status"] = "missing_csv"
        return row

    eps = [p[0] for p in pts]
    sig = [p[1] for p in pts]
    peak_i = max(range(len(sig)), key=lambda i: sig[i])
    snap = detect_snapthrough(eps, sig, band_lo=0.65, band_hi=0.78)
    dens = estimate_densification_strain(eps, sig)
    row.update(
        {
            "n_points": len(pts),
            "peak_stress_MPa": sig[peak_i],
            "peak_strain": eps[peak_i],
            "stress_at_0.20_MPa": _interp(pts, 0.20),
            "stress_at_0.55_MPa": _interp(pts, 0.55),
            "stress_at_0.70_MPa": _interp(pts, 0.70),
            "rmse_vs_fig33": rmse_vs_fig33(slug),
            "has_snapthrough": snap.get("has_snapthrough", False),
            "snapthrough_drop_fraction": snap.get("drop_fraction"),
            "densification_strain": dens["densification_strain"],
        }
    )
    trend = evaluate_q05(slug)
    row["q05_trend_pass"] = trend.get("q05_trend_pass")
    row["q05_trend_reason"] = trend.get("reason")
    row["status"] = "ok"
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-json",
        default=str(REPORTS_ROOT / "mesh_convergence" / "q05_mesh_convergence.json"),
    )
    parser.add_argument("--level", default="", help="Single level id (default: all)")
    args = parser.parse_args()

    levels = list(Q05_MESH_CONVERGENCE_LEVELS)
    if args.level:
        levels = [lv for lv in levels if lv["id"] == args.level]
        if not levels:
            print(f"[ERROR] unknown level {args.level!r}")
            return 1

    rows = [evaluate_level(lv) for lv in levels]
    for row in rows:
        rmse = row.get("rmse_vs_fig33")
        rmse_s = f"{rmse:.5f}" if rmse is not None else "n/a"
        ne = row.get("element_count", "?")
        print(
            f"{row['level_id']}: elems={ne} rmse={rmse_s} "
            f"peak={row.get('peak_stress_MPa', 'n/a')} snap={row.get('has_snapthrough')}"
        )

    os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
    with open(args.write_json, "w", encoding="utf-8") as f:
        json.dump({"levels": rows}, f, indent=2, ensure_ascii=False)
    print("Wrote:", args.write_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
