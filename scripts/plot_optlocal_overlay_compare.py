#!/usr/bin/env python3
"""Overlay ref fig28_p1_300g vs local-opt fig28_p1_300g_optlocal for the 5 ref cases.

Reads backup CSVs (preferred) or live ref slug; writes per-case + summary PNGs under
output/comsol_jobs/批量构型/_compare_opt/.
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

BATCH = ROOT / "output" / "comsol_jobs" / "批量构型"
REF_CASES = [
    "af2q0_deq2_k1",
    "af2q0p5_deq2_k1",
    "af2q1p5_deq2_k1",
    "af2q0_deq2_k2",
    "af1q1_deq2_k1",
]
DEFAULT_REF_SLUG = "fig28_p1_300g"
DEFAULT_OPT_SLUG = "fig28_p1_300g_optlocal"
DEFAULT_BACKUP = BATCH / "_backup_ref_fig28_p1_300g_latest"


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


def _metrics(freqs: list[float], vld: list[float], fmax: float = 500.0) -> dict:
    peak_v, peak_f = float("nan"), float("nan")
    onset = float("nan")
    for f, v in zip(freqs, vld):
        if f > fmax:
            continue
        if math.isnan(peak_v) or v > peak_v:
            peak_v, peak_f = v, f
        if math.isnan(onset) and v < 0.0:
            onset = f
    return {"peak_VLD_dB": peak_v, "peak_f_Hz": peak_f, "iso_onset_Hz": onset}


def _ref_csv(cid: str, backup: Path, ref_slug: str) -> Path:
    p = backup / cid / ref_slug / f"{ref_slug}_transmissibility.csv"
    if p.is_file():
        return p
    return BATCH / cid / ref_slug / f"{ref_slug}_transmissibility.csv"


def _opt_csv(cid: str, opt_slug: str) -> Path:
    return BATCH / cid / opt_slug / f"{opt_slug}_transmissibility.csv"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref-slug", default=DEFAULT_REF_SLUG)
    ap.add_argument("--opt-slug", default=DEFAULT_OPT_SLUG)
    ap.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    ap.add_argument("--out", type=Path, default=BATCH / "_compare_opt")
    ap.add_argument("--fmax", type=float, default=500.0)
    args = ap.parse_args(argv)

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(f"matplotlib required: {exc}") from exc

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict] = []
    n_ok = 0

    n = len(REF_CASES)
    ncols = 3
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(12.5, 3.6 * nrows), sharex=True)
    axes_flat = list(axes.ravel()) if hasattr(axes, "ravel") else [axes]

    for i, cid in enumerate(REF_CASES):
        ax = axes_flat[i]
        ref_p = _ref_csv(cid, args.backup, args.ref_slug)
        opt_p = _opt_csv(cid, args.opt_slug)
        rf, rv = _read_series(ref_p)
        of, ov = _read_series(opt_p)
        rm = _metrics(rf, rv, args.fmax)
        om = _metrics(of, ov, args.fmax)
        row = {
            "case_id": cid,
            "ref_csv": str(ref_p),
            "opt_csv": str(opt_p),
            "ref_n": len(rf),
            "opt_n": len(of),
            "ref_peak_VLD_dB": rm["peak_VLD_dB"],
            "ref_peak_f_Hz": rm["peak_f_Hz"],
            "ref_iso_onset_Hz": rm["iso_onset_Hz"],
            "opt_peak_VLD_dB": om["peak_VLD_dB"],
            "opt_peak_f_Hz": om["peak_f_Hz"],
            "opt_iso_onset_Hz": om["iso_onset_Hz"],
        }
        if rf and of:
            n_ok += 1
            # peak Δ
            if not math.isnan(rm["peak_f_Hz"]) and not math.isnan(om["peak_f_Hz"]):
                row["d_peak_f_Hz"] = om["peak_f_Hz"] - rm["peak_f_Hz"]
            if not math.isnan(rm["peak_VLD_dB"]) and not math.isnan(om["peak_VLD_dB"]):
                row["d_peak_VLD_dB"] = om["peak_VLD_dB"] - rm["peak_VLD_dB"]
        summary_rows.append(row)

        if rf:
            ax.plot(rf, rv, color="#1565C0", lw=1.8, label=f"ref ({args.ref_slug})")
        if of:
            ax.plot(of, ov, color="#E65100", lw=1.6, ls="--", label=f"opt ({args.opt_slug})")
        ax.axhline(0.0, color="#9E9E9E", lw=0.8, ls=":")
        ax.set_xlim(0.0, args.fmax)
        ax.set_title(cid, fontsize=11)
        ax.set_ylabel("VLD [dB]")
        ax.grid(True, alpha=0.25)
        if rf or of:
            ax.legend(loc="best", fontsize=8)
        else:
            ax.text(0.5, 0.5, "no CSV", ha="center", va="center", transform=ax.transAxes)

        # per-case figure
        fig1, ax1 = plt.subplots(figsize=(7.2, 4.2))
        if rf:
            ax1.plot(rf, rv, color="#1565C0", lw=2.0, label="ref (backup)")
        if of:
            ax1.plot(of, ov, color="#E65100", lw=1.8, ls="--", label="opt local")
        ax1.axhline(0.0, color="#9E9E9E", lw=0.8, ls=":")
        ax1.set_xlim(0.0, args.fmax)
        ax1.set_xlabel("Frequency [Hz]")
        ax1.set_ylabel("VLD [dB]")
        ax1.set_title(f"{cid}: ref vs opt-local")
        ax1.grid(True, alpha=0.25)
        ax1.legend(loc="best")
        fig1.tight_layout()
        fig1.savefig(out / f"{cid}_overlay.png", dpi=140)
        plt.close(fig1)

    for j in range(i + 1, len(axes_flat)):
        axes_flat[j].axis("off")
    for ax in axes_flat[max(0, n - ncols) : n]:
        ax.set_xlabel("Frequency [Hz]")
    fig.suptitle(
        f"Ref vs opt-local overlay (iterative / linear / hauto=6 / np=1)",
        fontsize=13,
        y=1.01,
    )
    fig.tight_layout()
    multi = out / "overlay_5cases.png"
    fig.savefig(multi, dpi=150, bbox_inches="tight")
    plt.close(fig)

    summary_path = out / "overlay_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ref_slug": args.ref_slug,
                "opt_slug": args.opt_slug,
                "backup": str(args.backup),
                "n_with_both": n_ok,
                "cases": summary_rows,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {multi} ({n_ok}/{n} cases with both CSVs)")
    print(f"Wrote {summary_path}")
    return 0 if n_ok == n else (1 if n_ok == 0 else 0)


if __name__ == "__main__":
    raise SystemExit(main())
