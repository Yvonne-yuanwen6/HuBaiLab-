#!/usr/bin/env python3
"""Overlay ref / optlocal / convergence ablation CSVs and score distance-to-ref.

Judgment heuristic (same FE model):
  - Interpolate VLD onto common 10–fmax grid
  - RMSE vs ref backup; smaller = closer to finer/quadratic baseline
  - Local peak freqs (3-point maxima, skip endpoints) for qualitative drift

Usage:
  python scripts/plot_convergence_overlay.py --case af2q0_deq2_k1
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BATCH = ROOT / "output" / "comsol_jobs" / "param_batch"
DEFAULT_BACKUP = BATCH / "_backup_ref_fig28_p1_300g_latest"

SERIES_SPEC = [
    ("ref", "fig28_p1_300g", "#1565C0", "-", 2.2, True),
    ("optlocal o1/h6", "fig28_p1_300g_optlocal", "#E65100", "--", 1.8, False),
    ("conv o2/h6", "conv_o2_h6", "#2E7D32", "-.", 1.8, False),
    ("conv o2/h8", "conv_o2_h8", "#558B2F", "-.", 1.8, False),
    ("conv o1/h7", "conv_o1_h7", "#7B1FA2", ":", 1.6, False),
    ("conv o1/h5", "conv_o1_h5", "#6A1B9A", ":", 1.8, False),
    ("conv o1/h4", "conv_o1_h4", "#00838F", "--", 1.6, False),
    ("conv o2/h5", "conv_o2_h5", "#C62828", "-", 1.4, False),
]


def _read_series(path: Path) -> tuple[list[float], list[float]]:
    if not path.is_file():
        return [], []
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    freqs: list[float] = []
    vld: list[float] = []
    for row in rows:
        try:
            f = float(row["frequency_Hz"])
            v_raw = row.get("VLD_dB") or ""
            t_raw = row.get("transmissibility") or row.get("T_eq320") or ""
            if v_raw not in ("", None):
                v = float(v_raw)
            else:
                t = float(t_raw)
                v = 20.0 * math.log10(t) if t > 0 else float("nan")
        except (KeyError, TypeError, ValueError):
            continue
        if math.isnan(v):
            continue
        freqs.append(f)
        vld.append(v)
    return freqs, vld


def _csv_path(case: str, slug: str, backup: Path, *, is_ref: bool) -> Path:
    if is_ref:
        p = backup / case / slug / f"{slug}_transmissibility.csv"
        if p.is_file():
            return p
    return BATCH / case / slug / f"{slug}_transmissibility.csv"


def _interp(freqs: list[float], vld: list[float], grid: list[float]) -> list[float]:
    if len(freqs) < 2:
        return [float("nan")] * len(grid)
    out: list[float] = []
    for g in grid:
        if g < freqs[0] or g > freqs[-1]:
            out.append(float("nan"))
            continue
        # linear interpolate
        i = 0
        while i + 1 < len(freqs) and freqs[i + 1] < g:
            i += 1
        if freqs[i] == freqs[i + 1]:
            out.append(vld[i])
            continue
        t = (g - freqs[i]) / (freqs[i + 1] - freqs[i])
        out.append(vld[i] * (1 - t) + vld[i + 1] * t)
    return out


def _rmse(a: list[float], b: list[float]) -> float:
    s = 0.0
    n = 0
    for x, y in zip(a, b):
        if math.isnan(x) or math.isnan(y):
            continue
        s += (x - y) ** 2
        n += 1
    return math.sqrt(s / n) if n else float("nan")


def _local_peaks(
    freqs: list[float], vld: list[float], *, fmin: float = 15.0, fmax: float = 500.0
) -> list[tuple[float, float]]:
    """Return up to 3 local maxima (f, VLD), ignoring very-low-f endpoint artifacts."""
    peaks: list[tuple[float, float]] = []
    for i in range(1, len(freqs) - 1):
        f = freqs[i]
        if f < fmin or f > fmax:
            continue
        if vld[i] >= vld[i - 1] and vld[i] >= vld[i + 1] and vld[i] > 0.0:
            peaks.append((f, vld[i]))
    peaks.sort(key=lambda p: p[1], reverse=True)
    return peaks[:3]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", default="af2q0_deq2_k1")
    ap.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    ap.add_argument("--fmax", type=float, default=500.0)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(f"matplotlib required: {exc}") from exc

    out = args.out or (BATCH / "_convergence" / args.case)
    out.mkdir(parents=True, exist_ok=True)

    grid = [float(f) for f in range(10, int(args.fmax) + 1, 10)]
    loaded: list[dict] = []
    ref_interp: list[float] | None = None

    for label, slug, color, ls, lw, is_ref in SERIES_SPEC:
        path = _csv_path(args.case, slug, args.backup, is_ref=is_ref)
        freqs, vld = _read_series(path)
        if not freqs:
            loaded.append(
                {
                    "label": label,
                    "slug": slug,
                    "path": str(path),
                    "n": 0,
                    "rmse_vs_ref": None,
                    "peaks": [],
                }
            )
            continue
        interp = _interp(freqs, vld, grid)
        if is_ref:
            ref_interp = interp
        rmse = _rmse(interp, ref_interp) if ref_interp is not None and not is_ref else 0.0
        peaks = _local_peaks(freqs, vld, fmax=args.fmax)
        loaded.append(
            {
                "label": label,
                "slug": slug,
                "path": str(path),
                "n": len(freqs),
                "freqs": freqs,
                "vld": vld,
                "interp": interp,
                "rmse_vs_ref_dB": rmse,
                "peaks": [{"f_Hz": f, "VLD_dB": v} for f, v in peaks],
                "color": color,
                "ls": ls,
                "lw": lw,
                "is_ref": is_ref,
            }
        )

    # Plot
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    for row in loaded:
        if row["n"] == 0:
            continue
        ax.plot(
            row["freqs"],
            row["vld"],
            color=row["color"],
            ls=row["ls"],
            lw=row["lw"],
            label=row["label"]
            + (
                ""
                if row["is_ref"]
                else f"  RMSE={row['rmse_vs_ref_dB']:.2f} dB"
            ),
        )
    ax.axhline(0.0, color="#9E9E9E", lw=0.8, ls=":")
    ax.set_xlim(0.0, args.fmax)
    ax.set_xlabel("Frequency [Hz]")
    ax.set_ylabel("VLD [dB]")
    ax.set_title(f"{args.case}: mesh/order convergence vs ref")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    png = out / "convergence_overlay.png"
    fig.savefig(png, dpi=150)
    plt.close(fig)

    # Ranking (exclude ref / missing)
    ranked = sorted(
        [r for r in loaded if r["n"] > 0 and not r["is_ref"]],
        key=lambda r: (
            float("inf")
            if r["rmse_vs_ref_dB"] is None or math.isnan(r["rmse_vs_ref_dB"])
            else r["rmse_vs_ref_dB"]
        ),
    )
    judgment = {
        "case_id": args.case,
        "fmax_Hz": args.fmax,
        "ref_slug": "fig28_p1_300g",
        "metric": "RMSE(VLD_dB) on 10–fmax / 10 Hz grid vs ref backup",
        "ranking_closest_to_ref": [
            {"label": r["label"], "slug": r["slug"], "rmse_vs_ref_dB": r["rmse_vs_ref_dB"]}
            for r in ranked
        ],
        "series": [
            {
                "label": r["label"],
                "slug": r["slug"],
                "n": r["n"],
                "path": r["path"],
                "rmse_vs_ref_dB": r.get("rmse_vs_ref_dB"),
                "peaks": r.get("peaks"),
            }
            for r in loaded
        ],
        "interpretation": (
            "If refining mesh (h6→h5→h4) and/or raising order (o1→o2) reduces RMSE "
            "toward ref, the reference (quadratic/fine) is the better estimate of the "
            "converged FE solution; optlocal is a coarse approximation."
        ),
    }
    if ranked:
        best = ranked[0]
        judgment["closest_variant"] = best["slug"]
        judgment["verdict"] = (
            f"Closest ablation to ref: {best['label']} "
            f"(RMSE {best['rmse_vs_ref_dB']:.2f} dB). "
            "Prefer ref over optlocal for quantitative claims if RMSE drops with refine/order."
        )
    else:
        judgment["verdict"] = "No ablation CSVs yet — run run_mesh_order_convergence_win.py first."

    summary = out / "convergence_summary.json"
    summary.write_text(json.dumps(judgment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {png}")
    print(f"Wrote {summary}")
    print(judgment.get("verdict", ""))
    return 0 if any(r["n"] > 0 and not r["is_ref"] for r in loaded) else 1


if __name__ == "__main__":
    raise SystemExit(main())
