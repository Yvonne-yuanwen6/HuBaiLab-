"""Compare COMSOL eigen vs harmonic-resonance peaks against thesis Table 3.3."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from src.comsol.eigen_extract import rank_modes_by_meff
from src.comsol.plot_isolation import pick_resonance_peaks, rows_to_series
from src.comsol.table33_reference import (
    CASE_LABELS,
    EIGEN_SLUGS,
    FREQ_SLUGS,
    paper_exp_hz,
    paper_sim_hz,
    resolve_case_key,
)


def error_pct(sim_hz: float, ref_hz: float | None) -> float | None:
    if ref_hz is None or ref_hz <= 0 or math.isnan(sim_hz):
        return None
    return 100.0 * (sim_hz - ref_hz) / ref_hz


def load_eigen_rows(csv_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            item: dict[str, Any] = {
                "mode": int(row["mode"]),
                "frequency_Hz": float(row["frequency_Hz"]),
            }
            if row.get("mEff_excitation") not in (None, ""):
                item["mEff_excitation"] = float(row["mEff_excitation"])
            if row.get("pf_excitation") not in (None, ""):
                item["pf_excitation"] = float(row["pf_excitation"])
            rows.append(item)
    return rows


def load_transmissibility_rows(csv_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            t_raw = row.get("transmissibility", row.get("T_eq320", "nan"))
            t = float(t_raw)
            if math.isnan(t):
                continue
            rows.append({"frequency_Hz": float(row["frequency_Hz"]), "transmissibility": t})
    return rows


def _cluster_first_three(physical: list[tuple[int, float]]) -> list[dict[str, Any]]:
    if not physical:
        return []
    clusters: list[dict[str, Any]] = []
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


def pick_eigen_top_three(
    eigen_rows: list[dict[str, Any]],
    *,
    min_hz: float = 1.0,
) -> tuple[list[dict[str, Any]], str]:
    """Return first three physical eigen modes (prefer mEff ranking)."""
    if any(r.get("mEff_excitation") is not None for r in eigen_rows):
        ranked = rank_modes_by_meff(eigen_rows, min_hz=min_hz, n=3)
        if ranked:
            return (
                [
                    {
                        "rank": i + 1,
                        "mode": r["mode"],
                        "freq_hz": r["frequency_Hz"],
                        "mEff_excitation": r.get("mEff_excitation"),
                    }
                    for i, r in enumerate(ranked)
                ],
                "mEff_excitation",
            )
    physical = [(r["mode"], r["frequency_Hz"]) for r in eigen_rows if r["frequency_Hz"] >= min_hz]
    clustered = _cluster_first_three(physical)
    return (
        [{"rank": i + 1, "mode": c["mode"], "freq_hz": c["freq_hz"]} for i, c in enumerate(clustered)],
        "frequency_cluster",
    )


def pick_harmonic_top_three(
    trans_rows: list[dict[str, Any]],
    *,
    min_hz: float = 1.0,
    min_sep_hz: float = 8.0,
) -> tuple[list[dict[str, Any]], str]:
    """Return first three resonance peaks from T(f) (local maxima by frequency)."""
    freqs, trans, _ = rows_to_series(trans_rows)
    peaks = pick_resonance_peaks(freqs, trans, min_hz=min_hz, min_sep_hz=min_sep_hz, n=3)
    method = "local_max_by_freq" if peaks else "none"
    if peaks and "method" not in peaks[0]:
        # pick_resonance_peaks fallback may omit method tag
        if len(freqs) >= 3 and peaks[0].get("rank") == 1:
            method = "local_max_by_freq"
    out = [
        {
            "rank": pk["rank"],
            "freq_hz": pk["freq_hz"],
            "transmissibility": pk.get("transmissibility"),
        }
        for pk in peaks
    ]
    if out and all(p.get("transmissibility") for p in out):
        # Detect global-top fallback: not sorted by frequency
        by_t = sorted(out, key=lambda x: -(x.get("transmissibility") or 0.0))
        if by_t[0]["freq_hz"] != out[0]["freq_hz"]:
            method = "top_by_T"
    return out, method


def _attach_paper_errors(
    modes: list[dict[str, Any]],
    *,
    paper_sim: list[float] | None,
    paper_exp: list[float] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, mode in enumerate(modes):
        sim_ref = paper_sim[i] if paper_sim and i < len(paper_sim) else None
        exp_ref = paper_exp[i] if paper_exp and i < len(paper_exp) else None
        row = dict(mode)
        row["paper_sim_hz"] = sim_ref
        row["paper_exp_hz"] = exp_ref
        row["error_vs_paper_sim_pct"] = error_pct(float(row["freq_hz"]), sim_ref)
        row["error_vs_paper_exp_pct"] = error_pct(float(row["freq_hz"]), exp_ref)
        out.append(row)
    return out


def compare_from_job_dir(
    job_dir: Path,
    *,
    slug: str = "",
    case_key: str | None = None,
    min_hz: float = 1.0,
    min_sep_hz: float = 8.0,
) -> dict[str, Any]:
    """Build eigen + harmonic Table 3.3 comparison for one job directory."""
    job_dir = job_dir.resolve()
    manifest: dict[str, Any] = {}
    manifest_path = job_dir / "case_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    slug = slug or manifest.get("slug", job_dir.name)
    if not case_key:
        geom = manifest.get("geometry", {})
        case_key = resolve_case_key(
            slug=slug,
            variant=str(geom.get("variant", "")),
            Q=geom.get("Q"),
        )

    eigen_path = job_dir / f"{slug}_eigenfrequencies.csv"
    trans_path = job_dir / f"{slug}_transmissibility.csv"

    eigen_rows = load_eigen_rows(eigen_path) if eigen_path.is_file() else []
    trans_rows = load_transmissibility_rows(trans_path) if trans_path.is_file() else []

    eigen_modes: list[dict[str, Any]] = []
    eigen_method = "missing"
    if eigen_rows:
        eigen_modes, eigen_method = pick_eigen_top_three(eigen_rows, min_hz=min_hz)

    harmonic_modes: list[dict[str, Any]] = []
    harmonic_method = "missing"
    if trans_rows:
        harmonic_modes, harmonic_method = pick_harmonic_top_three(
            trans_rows, min_hz=min_hz, min_sep_hz=min_sep_hz
        )

    paper_sim = paper_sim_hz(case_key)
    paper_exp = paper_exp_hz(case_key)

    return {
        "case_key": case_key,
        "label": CASE_LABELS.get(case_key or "", slug),
        "slug": slug,
        "job_dir": str(job_dir),
        "eigen_csv": str(eigen_path) if eigen_path.is_file() else None,
        "transmissibility_csv": str(trans_path) if trans_path.is_file() else None,
        "paper_table33_sim_hz": paper_sim,
        "paper_table33_exp_hz": paper_exp,
        "eigen": {
            "ranking_method": eigen_method,
            "n_modes_total": len(eigen_rows),
            "modes": _attach_paper_errors(eigen_modes, paper_sim=paper_sim, paper_exp=paper_exp),
        },
        "harmonic": {
            "pick_method": harmonic_method,
            "n_freq_points": len(trans_rows),
            "modes": _attach_paper_errors(harmonic_modes, paper_sim=paper_sim, paper_exp=paper_exp),
        },
        "hypothesis_note": (
            "If harmonic peaks match paper_sim_hz better than eigen modes, "
            "thesis Table 3.3 sim column may come from resonance (T peak) not eigen fn."
        ),
    }


def compare_batch_case(
    case_key: str,
    jobs_root: Path,
    *,
    min_hz: float = 1.0,
    min_sep_hz: float = 8.0,
) -> dict[str, Any]:
    """Merge eigen job + freq job for one Table 3.3 variant."""
    jobs_root = jobs_root.resolve()
    eigen_slug = EIGEN_SLUGS.get(case_key, "")
    freq_slug = FREQ_SLUGS.get(case_key, "")

    eigen_dir = jobs_root / eigen_slug if eigen_slug else None
    freq_dir = jobs_root / freq_slug if freq_slug else None

    eigen_part = (
        compare_from_job_dir(eigen_dir, slug=eigen_slug, case_key=case_key, min_hz=min_hz)
        if eigen_dir and eigen_dir.is_dir()
        else None
    )
    freq_part = (
        compare_from_job_dir(freq_dir, slug=freq_slug, case_key=case_key, min_hz=min_hz, min_sep_hz=min_sep_hz)
        if freq_dir and freq_dir.is_dir()
        else None
    )

    base = eigen_part or freq_part or {
        "case_key": case_key,
        "label": CASE_LABELS.get(case_key, case_key),
        "slug": eigen_slug or freq_slug,
        "paper_table33_sim_hz": paper_sim_hz(case_key),
        "paper_table33_exp_hz": paper_exp_hz(case_key),
    }

    merged: dict[str, Any] = {
        "case_key": case_key,
        "label": CASE_LABELS.get(case_key, case_key),
        "eigen_slug": eigen_slug or None,
        "freq_slug": freq_slug or None,
        "paper_table33_sim_hz": paper_sim_hz(case_key),
        "paper_table33_exp_hz": paper_exp_hz(case_key),
        "eigen": (eigen_part or {}).get("eigen", {"ranking_method": "missing", "modes": []}),
        "harmonic": (freq_part or {}).get("harmonic", {"pick_method": "missing", "modes": []}),
        "hypothesis_note": base.get("hypothesis_note"),
    }
    return merged


def write_compare_csv_batch(results: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "case",
                "rank",
                "method",
                "sim_hz",
                "paper_sim_hz",
                "err_vs_paper_sim_pct",
                "paper_exp_hz",
                "err_vs_paper_exp_pct",
                "extra",
            ]
        )
        for result in results:
            case = result.get("label", result.get("case_key", ""))
            for src, method_key in (("eigen", "ranking_method"), ("harmonic", "pick_method")):
                block = result.get(src, {})
                method = block.get(method_key, "")
                for row in block.get("modes", []):
                    extra = ""
                    if src == "eigen" and row.get("mode") is not None:
                        extra = f"mode={row['mode']}"
                    if src == "harmonic" and row.get("transmissibility") is not None:
                        extra = f"T={row['transmissibility']:.4g}"
                    w.writerow(
                        [
                            case,
                            row.get("rank"),
                            f"{src}:{method}",
                            f"{row['freq_hz']:.6g}",
                            row.get("paper_sim_hz") if row.get("paper_sim_hz") is not None else "",
                            f"{row['error_vs_paper_sim_pct']:+.2f}"
                            if row.get("error_vs_paper_sim_pct") is not None
                            else "",
                            row.get("paper_exp_hz") if row.get("paper_exp_hz") is not None else "",
                            f"{row['error_vs_paper_exp_pct']:+.2f}"
                            if row.get("error_vs_paper_exp_pct") is not None
                            else "",
                            extra,
                        ]
                    )


def write_compare_csv(result: dict[str, Any], path: Path) -> None:
    write_compare_csv_batch([result], path)


def print_compare_table(result: dict[str, Any]) -> None:
    label = result.get("label", result.get("case_key", ""))
    paper = result.get("paper_table33_sim_hz") or []
    paper_s = "/".join(f"{p:g}" for p in paper[:3]) if paper else "—"

    print(f"\n=== Table 3.3 comparison — {label} (paper sim: {paper_s} Hz) ===")
    print(
        f"{'Rank':>4} {'Eigen(Hz)':>10} {'E%':>7} "
        f"{'Harm(Hz)':>10} {'H%':>7} {'Paper':>8} {'T_peak':>8}"
    )
    print("-" * 62)

    eigen_by_rank = {m["rank"]: m for m in result.get("eigen", {}).get("modes", [])}
    harm_by_rank = {m["rank"]: m for m in result.get("harmonic", {}).get("modes", [])}
    for rank in range(1, 4):
        e = eigen_by_rank.get(rank)
        h = harm_by_rank.get(rank)
        paper_f = paper[rank - 1] if rank - 1 < len(paper) else None

        e_hz = f"{e['freq_hz']:.2f}" if e else "—"
        e_err = f"{e['error_vs_paper_sim_pct']:+.1f}" if e and e.get("error_vs_paper_sim_pct") is not None else "—"
        h_hz = f"{h['freq_hz']:.2f}" if h else "—"
        h_err = f"{h['error_vs_paper_sim_pct']:+.1f}" if h and h.get("error_vs_paper_sim_pct") is not None else "—"
        paper_str = f"{paper_f:g}" if paper_f is not None else "—"
        t_peak = f"{h['transmissibility']:.3g}" if h and h.get("transmissibility") is not None else "—"
        print(f"{rank:>4} {e_hz:>10} {e_err:>7} {h_hz:>10} {h_err:>7} {paper_str:>8} {t_peak:>8}")

    e_method = result.get("eigen", {}).get("ranking_method", "?")
    h_method = result.get("harmonic", {}).get("pick_method", "?")
    print(f"  eigen: {e_method}  |  harmonic: {h_method}")
