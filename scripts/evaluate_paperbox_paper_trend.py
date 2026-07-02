"""Score one paperbox stress-strain curve vs Hu & Bai Fig.3.3 trends."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.analyze_paperbox_snapthrough import detect_snapthrough
from src.paths import ABAQUS_POST
from src.postprocess.compression_curve import (
    HU_BAI_PAPER_DENSIFICATION_STRAIN,
    estimate_densification_strain,
)

PAPER_STRESS_MAX_MPA = 0.04
PEAK_STRESS_PASS_MAX_MPA = 0.10
PEAK_STRESS_PASS_MIN_MPA = 0.008
EARLY_STRAIN = 0.20

# Paper early-phase ordering (higher stress = stiffer): Q1 > Q0.5 ≈ Q1.5 > BCC
Q_ORDER = {"q1": 4, "q1.5": 3, "q0.5": 2, "bcc": 1}


def load_curve(slug: str) -> list[tuple[float, float]]:
    path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
    if not path.is_file():
        return []
    pts: list[tuple[float, float]] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pts.append((float(row["engineering_strain"]), float(row["engineering_stress_MPa"])))
    return pts


def interp(pts: list[tuple[float, float]], target: float) -> float | None:
    if not pts:
        return None
    for i in range(1, len(pts)):
        e0, s0 = pts[i - 1]
        e1, s1 = pts[i]
        if e1 >= target:
            if e1 == e0:
                return s1
            return s0 + (s1 - s0) * (target - e0) / (e1 - e0)
    return None


def q_key_from_slug(slug: str) -> str | None:
    if "bcc_af2q0_" in slug:
        return "bcc"
    if "sfbls_af2q0p5_" in slug:
        return "q0.5"
    if "sfbls_af2q1p5_" in slug:
        return "q1.5"
    if "sfbls_af2q1_" in slug:
        return "q1"
    return None


def evaluate_slug(slug: str) -> dict:
    pts = load_curve(slug)
    qk = q_key_from_slug(slug)
    out: dict = {"slug": slug, "q_key": qk, "csv_found": bool(pts)}
    if not pts:
        out["pass"] = False
        out["reason"] = "missing_csv"
        return out

    eps = [p[0] for p in pts]
    sig = [p[1] for p in pts]
    snap = detect_snapthrough(eps, sig)
    dens = estimate_densification_strain(eps, sig)
    peak_i = max(range(len(sig)), key=lambda i: sig[i])
    s_early = interp(pts, EARLY_STRAIN)

    out.update(
        {
            "n_points": len(pts),
            "peak_stress_MPa": sig[peak_i],
            "peak_strain": eps[peak_i],
            "stress_at_0.20_MPa": s_early,
            "has_snapthrough": snap.get("has_snapthrough", False),
            "snapthrough_drop_fraction": snap.get("drop_fraction"),
            "densification_strain": dens["densification_strain"],
            "paper_densification_strain": HU_BAI_PAPER_DENSIFICATION_STRAIN.get(qk or ""),
        }
    )

    reasons: list[str] = []
    if out["peak_stress_MPa"] > PEAK_STRESS_PASS_MAX_MPA:
        reasons.append(f"peak {out['peak_stress_MPa']:.4f} MPa > {PEAK_STRESS_PASS_MAX_MPA} (paper ~{PAPER_STRESS_MAX_MPA})")
    if out["peak_stress_MPa"] < PEAK_STRESS_PASS_MIN_MPA:
        reasons.append(f"peak {out['peak_stress_MPa']:.4f} MPa too low")

    if not out["has_snapthrough"]:
        reasons.append("no snap-through (soft warning)")

    out["pass"] = len([r for r in reasons if not r.startswith("no snap")]) == 0
    out["reason"] = "; ".join(reasons) if reasons else "ok"
    out["hard_pass"] = out["pass"] and out["has_snapthrough"]
    return out


def check_early_ranking(slugs: list[str]) -> dict:
    """Return ranking_ok if available Q curves follow paper order at ε=0.20."""
    stresses: dict[str, float] = {}
    for slug in slugs:
        pts = load_curve(slug)
        qk = q_key_from_slug(slug)
        if not pts or not qk:
            continue
        s = interp(pts, EARLY_STRAIN)
        if s is not None:
            stresses[qk] = s

    if len(stresses) < 2:
        return {"ranking_ok": None, "stress_at_0.20": stresses, "note": "need >=2 Q curves"}

    ordered = sorted(stresses.items(), key=lambda kv: Q_ORDER.get(kv[0], 0), reverse=True)
    actual = sorted(stresses.items(), key=lambda kv: kv[1], reverse=True)
    ranking_ok = [a[0] for a in actual] == [o[0] for o in ordered]
    return {
        "ranking_ok": ranking_ok,
        "stress_at_0.20": stresses,
        "expected_order": [o[0] for o in ordered],
        "actual_order": [a[0] for a in actual],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--compare-slugs",
        default="",
        help="Comma-separated slugs for early-phase ranking check",
    )
    parser.add_argument("--write-json", default="")
    args = parser.parse_args()

    report = evaluate_slug(args.slug)
    compare = [s.strip() for s in args.compare_slugs.split(",") if s.strip()]
    all_slugs = list(dict.fromkeys([args.slug] + compare))
    rank = check_early_ranking(all_slugs)
    report["ranking"] = rank

    if rank["ranking_ok"] is False:
        report["pass"] = False
        report["reason"] = (report.get("reason") or "") + f"; early ranking wrong {rank['actual_order']} vs {rank['expected_order']}"

    print(json.dumps(report, indent=2))
    if args.write_json:
        os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
        with open(args.write_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
