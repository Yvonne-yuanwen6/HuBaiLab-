#!/usr/bin/env python3
"""Overlay ref / optlocal / convergence variants for one case (mesh-order study)."""
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
BACKUP = BATCH / "_backup_ref_fig28_p1_300g_latest"
REF_SLUG = "fig28_p1_300g"
OPT_SLUG = "fig28_p1_300g_optlocal"

VARIANT_META = {
    "o1_h6": {"order": 1, "hauto": 6, "label": "opt o1/h6", "color": "#E65100", "ls": "--"},
    "o1_h5": {"order": 1, "hauto": 5, "label": "conv o1/h5", "color": "#2E7D32", "ls": "-"},
    "o1_h4": {"order": 1, "hauto": 4, "label": "conv o1/h4", "color": "#00695C", "ls": "-"},
    "o2_h6": {"order": 2, "hauto": 6, "label": "conv o2/h6", "color": "#6A1B9A", "ls": "-."},
    "o2_h5": {"order": 2, "hauto": 5, "label": "conv o2/h5", "color": "#4527A0", "ls": "-."},
    "o2_h4": {"order": 2, "hauto": 4, "label": "conv o2/h4", "color": "#311B92", "ls": ":"},
}


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


def _local_peaks(
    freqs: list[float], vld: list[float], *, fmax: float = 500.0, n: int = 5
) -> list[dict]:
    """Simple local-max peaks (strict neighbors), skip f<=15 Hz DC/artifact band."""
    pts = [(f, v) for f, v in zip(freqs, vld) if 15.0 < f <= fmax and not math.isnan(v)]
    peaks: list[dict] = []
    for i in range(1, len(pts) - 1):
        f, v = pts[i]
        if v >= pts[i - 1][1] and v >= pts[i + 1][1]:
            peaks.append({"f_Hz": f, "VLD_dB": v})
    peaks.sort(key=lambda p: -p["VLD_dB"])
    return peaks[:n]


def _csv_path(case: str, slug: str, *, backup_ref: bool = False) -> Path:
    if backup_ref:
        p = BACKUP / case / REF_SLUG / f"{REF_SLUG}_transmissibility.csv"
        if p.is_file():
            return p
    return BATCH / case / slug / f"{slug}_transmissibility.csv"


def _l2_vs_ref(
    rf: list[float], rv: list[float], of: list[float], ov: list[float], fmax: float
) -> float:
    """RMSE of VLD on common freq grid (nearest-neighbor on opt)."""
    if not rf or not of:
        return float("nan")
    errs: list[float] = []
    for f, v in zip(rf, rv):
        if f > fmax:
            continue
        # nearest
        j = min(range(len(of)), key=lambda k: abs(of[k] - f))
        if abs(of[j] - f) > 1e-6 and abs(of[j] - f) > 5.0:
            continue
        errs.append((ov[j] - v) ** 2)
    if not errs:
        return float("nan")
    return math.sqrt(sum(errs) / len(errs))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", default="af2q0_deq2_k1")
    ap.add_argument("--variants", nargs="+", default=["o1_h5", "o1_h4", "o2_h6"])
    ap.add_argument("--fmax", type=float, default=500.0)
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output dir (default: .../_compare_conv/<case>)",
    )
    args = ap.parse_args(argv)

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(f"matplotlib required: {exc}") from exc

    out = args.out or (BATCH / "_compare_conv" / args.case)
    out.mkdir(parents=True, exist_ok=True)

    series: dict[str, tuple[list[float], list[float]]] = {}
    ref_p = _csv_path(args.case, REF_SLUG, backup_ref=True)
    opt_p = _csv_path(args.case, OPT_SLUG)
    series["ref"] = _read_series(ref_p)
    series["opt"] = _read_series(opt_p)
    for key in args.variants:
        series[key] = _read_series(_csv_path(args.case, f"conv_{key}"))

    rf, rv = series["ref"]
    summary: dict = {
        "case_id": args.case,
        "ref_csv": str(ref_p),
        "opt_csv": str(opt_p),
        "fmax_Hz": args.fmax,
        "curves": {},
    }

    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    if rf:
        ax.plot(rf, rv, color="#1565C0", lw=2.2, label="ref (quad / fine, backup)")
    of, ov = series["opt"]
    if of:
        ax.plot(of, ov, color="#E65100", lw=1.8, ls="--", label="optlocal o1/h6")
    for key in args.variants:
        f, v = series[key]
        meta = VARIANT_META.get(key, {"label": key, "color": "#424242", "ls": "-"})
        if f:
            ax.plot(f, v, color=meta["color"], lw=1.6, ls=meta["ls"], label=meta["label"])

    ax.axhline(0.0, color="#9E9E9E", lw=0.8, ls=":")
    ax.set_xlim(0.0, args.fmax)
    ax.set_xlabel("Frequency [Hz]")
    ax.set_ylabel("VLD [dB]")
    ax.set_title(f"{args.case}: mesh/order convergence vs ref")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    png = out / f"{args.case}_convergence_overlay.png"
    fig.savefig(png, dpi=150)
    plt.close(fig)

    # Metrics
    for name, (f, v) in series.items():
        rmse = _l2_vs_ref(rf, rv, f, v, args.fmax) if name != "ref" else 0.0
        peaks = _local_peaks(f, v, fmax=args.fmax)
        summary["curves"][name] = {
            "n": len(f),
            "rmse_vs_ref_dB": rmse,
            "peaks": peaks,
            "present": bool(f),
        }

    # Rank by RMSE (lower = closer to ref)
    ranked = sorted(
        (
            (k, summary["curves"][k]["rmse_vs_ref_dB"])
            for k in summary["curves"]
            if k != "ref" and summary["curves"][k]["present"]
            and not math.isnan(summary["curves"][k]["rmse_vs_ref_dB"])
        ),
        key=lambda kv: kv[1],
    )
    summary["rank_by_rmse_vs_ref"] = [{"slug": k, "rmse_dB": r} for k, r in ranked]
    if ranked:
        best = ranked[0][0]
        summary["closest_to_ref"] = best
        summary["judgment"] = (
            "Curves that refine mesh (hauto↓) or raise order (→2) should move toward ref. "
            f"Closest available curve to ref by VLD RMSE: {best}."
        )
        if "opt" in dict(ranked) and ranked[0][0] != "opt":
            summary["judgment"] += (
                " Optlocal is NOT the closest — treat it as a coarse RAM compromise."
            )

    js = out / f"{args.case}_convergence_summary.json"
    js.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {png}")
    print(f"Wrote {js}")
    if ranked:
        print("RMSE vs ref (dB), best→worst:")
        for k, r in ranked:
            print(f"  {k:12s}  {r:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
