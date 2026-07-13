#!/usr/bin/env python3
"""Compare Fig.3.21 / Table 3.3 eigen frequencies: COMSOL vs thesis paper."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.eigen_extract import rank_modes_by_meff
from src.paths import COMSOL_JOBS_ROOT

# Table 3.3 thesis simulation values (Hz) — modes 1–3
# Only BCC confirmed from thesis; SFBLS — fill when Table 3.3 row verified
PAPER_TABLE33_SIM_HZ: dict[str, list[float] | None] = {
    "bcc": [14.8, 49.8, 68.4],
    "af2q05": None,
    "af2q1": None,
    "af2q15": None,
}

SLUGS: dict[str, str] = {
    "bcc": "comsol_fig321_bcc_444",
    "af2q05": "comsol_fig321_af2q05_444",
    "af2q1": "comsol_fig321_af2q1_444",
    "af2q15": "comsol_fig321_af2q15_444",
}

LABELS: dict[str, str] = {
    "bcc": "BCC Q=0",
    "af2q05": "SFBLS Q=0.5",
    "af2q1": "SFBLS Q=1.0",
    "af2q15": "SFBLS Q=1.5",
}


def load_eigen_rows(csv_path: Path) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            item = {
                "mode": int(row["mode"]),
                "frequency_Hz": float(row["frequency_Hz"]),
            }
            if row.get("mEff_excitation") not in (None, ""):
                item["mEff_excitation"] = float(row["mEff_excitation"])
            if row.get("pf_excitation") not in (None, ""):
                item["pf_excitation"] = float(row["pf_excitation"])
            rows.append(item)
    return rows


def cluster_first_three(physical: list[tuple[int, float]]) -> list[dict]:
    """Legacy: first three frequency clusters (skip near-degenerate repeats)."""
    if not physical:
        return []
    clusters: list[dict] = []
    tol = 0.05
    for mode, freq in physical:
        if not clusters:
            clusters.append({"mode": mode, "freq_hz": freq})
            continue
        last = clusters[-1]["freq_hz"]
        if abs(freq - last) / max(last, 1e-9) > tol:
            clusters.append({"mode": mode, "freq_hz": freq})
        if len(clusters) >= 3:
            break
    return clusters


def pick_top_three(rows: list[dict], *, min_hz: float) -> tuple[list[dict], str]:
    """Prefer mEff ranking; fall back to frequency-cluster heuristic."""
    if any(r.get("mEff_excitation") is not None for r in rows):
        ranked = rank_modes_by_meff(rows, min_hz=min_hz, n=3)
        if ranked:
            return (
                [
                    {
                        "mode": r["mode"],
                        "freq_hz": r["frequency_Hz"],
                        "mEff_excitation": r.get("mEff_excitation"),
                    }
                    for r in ranked
                ],
                "mEff_excitation",
            )
    physical = [(r["mode"], r["frequency_Hz"]) for r in rows if r["frequency_Hz"] >= min_hz]
    return cluster_first_three(physical), "frequency_cluster"


def compare_case(key: str, jobs_root: Path, *, min_hz: float) -> dict | None:
    slug = SLUGS[key]
    csv_path = jobs_root / slug / f"{slug}_eigenfrequencies.csv"
    if not csv_path.is_file():
        return None
    rows = load_eigen_rows(csv_path)
    sim_clusters, method = pick_top_three(rows, min_hz=min_hz)
    paper_list = PAPER_TABLE33_SIM_HZ.get(key)
    paper = paper_list or []
    out_rows = []
    for i, cl in enumerate(sim_clusters):
        paper_f = paper[i] if i < len(paper) else None
        sim_f = cl["freq_hz"]
        err_pct = None
        if paper_f is not None and paper_f > 0:
            err_pct = 100.0 * (sim_f - paper_f) / paper_f
        out_rows.append(
            {
                "mode_rank": i + 1,
                "comsol_mode": cl["mode"],
                "sim_hz": sim_f,
                "paper_hz": paper_f,
                "error_pct": err_pct,
                "mEff_excitation": cl.get("mEff_excitation"),
            }
        )
    n_physical = sum(1 for r in rows if r["frequency_Hz"] >= min_hz)
    return {
        "key": key,
        "label": LABELS[key],
        "slug": slug,
        "csv": str(csv_path),
        "n_physical": n_physical,
        "ranking_method": method,
        "modes": out_rows,
    }


def print_table(results: list[dict]) -> None:
    print("\n=== Fig.3.21 / Table 3.3 eigen comparison ===")
    print(f"{'Case':<14} {'Rank':>4} {'COMSOL#':>8} {'Sim(Hz)':>10} {'Paper(Hz)':>10} {'Err%':>8} {'mEff':>10}")
    print("-" * 72)
    for res in results:
        method = res.get("ranking_method", "?")
        for row in res["modes"]:
            paper = f"{row['paper_hz']:.2g}" if row["paper_hz"] is not None else "—"
            err = f"{row['error_pct']:+.1f}" if row["error_pct"] is not None else "—"
            meff = row.get("mEff_excitation")
            meff_s = f"{meff:.3g}" if meff is not None else "—"
            print(
                f"{res['label']:<14} {row['mode_rank']:>4} {row['comsol_mode']:>8} "
                f"{row['sim_hz']:>10.2f} {paper:>10} {err:>8} {meff_s:>10}"
            )
        if not res["modes"]:
            print(f"{res['label']:<14}    (no CSV / no ranked modes)")
        elif res.get("ranking_method"):
            print(f"  ({res['label']} ranking: {method})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare COMSOL eigen vs Table 3.3 paper.")
    parser.add_argument("--jobs-root", default=str(COMSOL_JOBS_ROOT))
    parser.add_argument("--min-hz", type=float, default=1.0)
    parser.add_argument("--out-json", default=str(COMSOL_JOBS_ROOT / "fig321_composite" / "fig321_eigen_vs_paper.json"))
    parser.add_argument("--pull-summary", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    jobs_root = Path(args.jobs_root)
    results = []
    for key in ("bcc", "af2q05", "af2q1", "af2q15"):
        r = compare_case(key, jobs_root, min_hz=args.min_hz)
        if r is not None:
            results.append(r)

    print_table(results)
    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"cases": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
