"""
Import WebPlotDigitizer export for thesis Fig.2.5 TPU tensile σ–ε curve.

  py -3 scripts/import_webplotdigitizer_tpu_fig25.py
  py -3 scripts/import_webplotdigitizer_tpu_fig25.py --json data/reference/wpd/TPU曲线.json
  py -3 scripts/plot_tpu_fig25_wpd.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_WPD = _ROOT / "data" / "reference" / "wpd" / "TPU曲线.json"
OUT_JSON = _ROOT / "data" / "hu_bai_tpu_fig25_tensile_traced.json"

# Thesis §2.3.2 / Fig.2.5 reference scalars (validation only)
PAPER_E_MPA = 25.0
PAPER_YIELD_MPA = 4.69
PAPER_RHO_KG_M3 = 1135.0


def parse_wpd_tpu(path: Path) -> list[tuple[float, float]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    pts: list[tuple[float, float]] = []
    for ds in raw.get("datasetColl") or []:
        for d in ds.get("data") or []:
            if "value" not in d or len(d["value"]) < 2:
                continue
            e, s = float(d["value"][0]), float(d["value"][1])
            pts.append((e, s))
    if not pts:
        raise ValueError(f"No points in WPD JSON: {path}")
    return pts


def _dedupe_strain(pts: list[tuple[float, float]], *, min_de: float = 0.008) -> list[tuple[float, float]]:
    pts = sorted(pts, key=lambda p: (p[0], -p[1]))
    out: list[tuple[float, float]] = []
    for e, s in pts:
        if e < -1e-6 or s < -0.05:
            continue
        if out and e - out[-1][0] < min_de:
            if s > out[-1][1]:
                out[-1] = (e, s)
            continue
        out.append((e, max(0.0, s)))
    return out


def filter_loading_branch(
    pts: list[tuple[float, float]],
    *,
    eps_max: float = 6.5,
    stress_max: float = 15.0,
) -> list[tuple[float, float]]:
    """Keep monotonic loading branch; drop WPD vertical-line junk and post-peak drop."""
    pts = [(e, s) for e, s in pts if 0.0 <= e <= eps_max and 0.0 <= s <= stress_max]
    pts = _dedupe_strain(pts)

    if not pts:
        return []

    peak_i = max(range(len(pts)), key=lambda i: pts[i][1])
    pts = pts[: peak_i + 1]

    # Drop isolated low-stress points in the high-strain tail (mis-clicks)
    cleaned: list[tuple[float, float]] = []
    run_max = 0.0
    for e, s in pts:
        if s + 0.35 < run_max and e > 0.4:
            continue
        run_max = max(run_max, s)
        cleaned.append((e, s))

    if cleaned and cleaned[0][0] > 1e-4:
        cleaned.insert(0, (0.0, 0.0))
    return cleaned


def interp(pts: list[tuple[float, float]], target: float) -> float | None:
    for i in range(1, len(pts)):
        e0, s0 = pts[i - 1]
        e1, s1 = pts[i]
        if e1 >= target:
            if e1 == e0:
                return s1
            return s0 + (s1 - s0) * (target - e0) / (e1 - e0)
    return None


def secant_modulus(pts: list[tuple[float, float]], eps: float) -> float | None:
    s = interp(pts, eps)
    if s is None or eps <= 1e-9:
        return None
    return s / eps


def build_traced_json(
    pts: list[tuple[float, float]],
    *,
    source: str,
    wpd_axes: dict | None = None,
) -> dict:
    peak_i = max(range(len(pts)), key=lambda i: pts[i][1])
    return {
        "_comment": "Fig.2.5 TPU matrix tensile — WPD import for Abaqus hyperelastic test data",
        "source": source,
        "figure": "Fig.2.5 TPU基体材料拉伸应力应变曲线",
        "x_label": "工程应变",
        "y_label": "工程应力 (MPa)",
        "xlim": [0.0, max(6.5, pts[-1][0] if pts else 6.5)],
        "ylim": [0.0, max(14.0, pts[peak_i][1] * 1.05 if pts else 14.0)],
        "paper_scalars": {
            "E_MPa_tensile": PAPER_E_MPA,
            "yield_MPa_tensile": PAPER_YIELD_MPA,
            "density_kg_m3": PAPER_RHO_KG_M3,
        },
        "wpd_axes_calibration": wpd_axes or {},
        "points": [[round(e, 5), round(s, 5)] for e, s in pts],
        "peak": {
            "engineering_strain": round(pts[peak_i][0], 5),
            "engineering_stress_MPa": round(pts[peak_i][1], 5),
        },
        "validation": {
            "stress_at_eps_0.05_MPa": interp(pts, 0.05),
            "stress_at_eps_0.10_MPa": interp(pts, 0.10),
            "stress_at_eps_0.50_MPa": interp(pts, 0.50),
            "secant_E_at_0.05_MPa": secant_modulus(pts, 0.05),
            "secant_E_at_0.10_MPa": secant_modulus(pts, 0.10),
            "n_points": len(pts),
        },
        "abaqus_notes": {
            "material_model": "Hyperelastic test data (uniaxial) or Marlow",
            "strain_type": "engineering / nominal",
            "recommended_for_lattice_compression": "Use ε≤0.8 region cautiously; curve calibrated to tensile failure",
        },
    }


def wpd_axes_summary(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    axes = (raw.get("axesColl") or [{}])[0]
    cps = axes.get("calibrationPoints") or []
    dx = [float(cp["dx"]) for cp in cps if "dx" in cp]
    dy = [float(cp["dy"]) for cp in cps if "dy" in cp]
    return {
        "x_max_calibrated": max(dx) if dx else None,
        "y_max_calibrated": max(dy) if dy else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=DEFAULT_WPD)
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    args = parser.parse_args()

    if not args.json.is_file():
        print(f"Missing: {args.json}")
        return 1

    raw_n = len(parse_wpd_tpu(args.json))
    pts = filter_loading_branch(parse_wpd_tpu(args.json))
    if len(pts) < 8:
        print(f"[ERROR] too few points after filter: {len(pts)} (raw {raw_n})")
        return 1

    source = str(args.json.relative_to(_ROOT)) if args.json.is_relative_to(_ROOT) else str(args.json)
    out = build_traced_json(pts, source=source, wpd_axes=wpd_axes_summary(args.json))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    v = out["validation"]
    print(f"WPD raw points: {raw_n} → filtered loading branch: {len(pts)}")
    print(f"Peak: {out['peak']['engineering_stress_MPa']:.3f} MPa @ eps={out['peak']['engineering_strain']:.3f}")
    print(f"eps=0.05: stress={v['stress_at_eps_0.05_MPa']:.3f} MPa, secant E={v['secant_E_at_0.05_MPa']:.1f} MPa")
    print(f"eps=0.10: stress={v['stress_at_eps_0.10_MPa']:.3f} MPa, secant E={v['secant_E_at_0.10_MPa']:.1f} MPa")
    print(f"eps=0.50: stress={v['stress_at_eps_0.50_MPa']:.3f} MPa (paper yield ~{PAPER_YIELD_MPA} MPa)")
    print("Wrote:", args.out)
    print("Next: py -3 scripts/plot_tpu_fig25_wpd.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
