#!/usr/bin/env python3
"""Batch COMSOL isolation compare plots for 批量构型 (6 multi-panel PNGs).

Layouts (confirmed):
  A_Q_by_k.png          — 1×3: each κ, overlay Q curves
  A_k_by_Q.png          — 2×2: each Q, overlay κ curves
  B_Af.png              — 1×3: Af = 1 / 2 / 3
  B_deq.png             — 1×3: deq = 1.5 / 2 / 2.5
  S_metrics.png         — 2×2: peak-f, peak-VLD, iso-onset, band-width
  All_small_multiples.png — ~4×4: one VLD panel per case

Use --empty to force placeholder axes (no CSV required).
Without --empty, loads available CSVs and skips missing cases with a note.
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

BATCH_CAD = ROOT / "output" / "cad" / "批量构型"
BATCH_COMSOL = ROOT / "output" / "comsol_jobs" / "批量构型"
DEFAULT_OUT = BATCH_COMSOL / "_compare"
DEFAULT_RUN_SLUG = "fig28_p1_300g"

# Group A: Af=2, deq=2
Q_VALUES = (0.0, 0.5, 1.0, 1.5)
K_VALUES = (1.0, 1.5, 2.0)

# Group B anchors
AF_SWEEP = (1.0, 2.0, 3.0)  # Q=1, deq=2, k=1
DEQ_SWEEP = (1.5, 2.0, 2.5)  # Af=2, Q=1, k=1

Q_COLORS = {
    0.0: "#1565C0",
    0.5: "#2E7D32",
    1.0: "#E65100",
    1.5: "#6A1B9A",
}
K_COLORS = {
    1.0: "#1565C0",
    1.5: "#2E7D32",
    2.0: "#E65100",
}
AF_COLORS = {1.0: "#1565C0", 2.0: "#E65100", 3.0: "#6A1B9A"}
DEQ_COLORS = {1.5: "#1565C0", 2.0: "#E65100", 2.5: "#6A1B9A"}


def _fmt_num(x: float) -> str:
    if float(x).is_integer():
        return str(int(x))
    return str(x).replace(".", "p")


def case_id(*, Af: float, Q: float, deq: float, k: float) -> str:
    return f"af{_fmt_num(Af)}q{_fmt_num(Q)}_deq{_fmt_num(deq)}_k{_fmt_num(k)}"


def load_batch_index() -> dict:
    path = BATCH_CAD / "_batch_index.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"generation_order": [], "cases": {}}


def all_case_ids(index: dict) -> list[str]:
    order = list(index.get("generation_order") or [])
    if order:
        return order
    return sorted((index.get("cases") or {}).keys())


def csv_path_for(cid: str, run_slug: str) -> Path:
    return BATCH_COMSOL / cid / run_slug / f"{run_slug}_transmissibility.csv"


def read_trans_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or "FORMAT SAMPLE" in path.read_text(encoding="utf-8", errors="ignore")[:200]:
        return []
    return rows


def series_from_rows(rows: list[dict]) -> tuple[list[float], list[float], list[float]]:
    freqs: list[float] = []
    trans: list[float] = []
    vld: list[float] = []
    for row in rows:
        try:
            f = float(row["frequency_Hz"])
            t_raw = row.get("transmissibility") or row.get("T_eq320") or ""
            v_raw = row.get("VLD_dB") or ""
            t = float(t_raw) if t_raw not in ("", None) else float("nan")
            if v_raw not in ("", None):
                v = float(v_raw)
            elif t > 0 and t == t:
                v = 20.0 * math.log10(t)
            else:
                v = float("nan")
        except (KeyError, TypeError, ValueError):
            continue
        freqs.append(f)
        trans.append(t)
        vld.append(v)
    return freqs, trans, vld


def metrics_from_rows(rows: list[dict], *, fmax: float = 500.0) -> dict:
    peak_vld = float("nan")
    peak_f = float("nan")
    iso_onset = float("nan")
    band = 0.0
    in_band = False
    band_start = float("nan")
    for row in rows:
        try:
            f = float(row["frequency_Hz"])
            v = float(row.get("VLD_dB", "nan"))
        except (TypeError, ValueError):
            continue
        if f > fmax or math.isnan(v):
            continue
        if math.isnan(peak_vld) or v > peak_vld:
            peak_vld, peak_f = v, f
        if math.isnan(iso_onset) and v < 0.0:
            iso_onset = f
        if v < 0.0:
            if not in_band:
                in_band = True
                band_start = f
        elif in_band:
            band += f - band_start
            in_band = False
    if in_band and not math.isnan(band_start):
        band += fmax - band_start
    return {
        "peak_VLD_dB": peak_vld,
        "peak_VLD_freq_Hz": peak_f,
        "isolation_onset_Hz": iso_onset,
        "isolation_band_Hz": band,
    }


def _setup_mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

        configure_matplotlib_chinese()
    except Exception:
        pass
    return plt


def _style_vld_ax(ax, *, xmin: float, xmax: float, title: str = ""):
    ax.axhline(0.0, color="#757575", linestyle="--", linewidth=0.9)
    ax.set_xlim(xmin, xmax)
    ax.set_xlabel("频率 (Hz)")
    ax.set_ylabel("VLD (dB)  式 (3.6)")
    if title:
        ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.3)


def _empty_note(ax, text: str = "（空图预览 / 暂无 CSV）"):
    ax.text(
        0.5,
        0.5,
        text,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=10,
        color="#9E9E9E",
    )


def _plot_curve(ax, freqs, vld, *, color: str, label: str, empty: bool):
    if empty or not freqs:
        return None
    (line,) = ax.plot(freqs, vld, "-", color=color, linewidth=1.35, label=label)
    return line


def load_case_series(
    cid: str,
    run_slug: str,
    *,
    empty: bool,
    fmin: float,
    fmax: float,
) -> tuple[list[float], list[float], list[float], bool]:
    if empty:
        return [], [], [], False
    path = csv_path_for(cid, run_slug)
    if not path.is_file():
        return [], [], [], False
    rows = read_trans_csv(path)
    if not rows:
        return [], [], [], False
    freqs, trans, vld = series_from_rows(rows)
    keep = [(f, t, v) for f, t, v in zip(freqs, trans, vld) if fmin <= f <= fmax]
    if not keep:
        return [], [], [], False
    f2, t2, v2 = zip(*keep)
    return list(f2), list(t2), list(v2), True


def fig_A_Q_by_k(
    out: Path,
    *,
    run_slug: str,
    empty: bool,
    fmin: float,
    fmax: float,
) -> Path:
    plt = _setup_mpl()
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.2), sharey=True)
    for ax, k in zip(axes, K_VALUES):
        any_curve = False
        for q in Q_VALUES:
            cid = case_id(Af=2.0, Q=q, deq=2.0, k=k)
            freqs, _t, vld, ok = load_case_series(cid, run_slug, empty=empty, fmin=fmin, fmax=fmax)
            line = _plot_curve(ax, freqs, vld, color=Q_COLORS[q], label=f"Q={q:g}", empty=empty or not ok)
            if line is not None:
                any_curve = True
        _style_vld_ax(ax, xmin=fmin, xmax=fmax, title=f"κ = {k:g}  (Af=2, deq=2)")
        if empty:
            _empty_note(ax)
        elif not any_curve:
            _empty_note(ax, "暂无数据")
        else:
            ax.legend(fontsize=8, loc="best", frameon=True)
    fig.suptitle("组 A：固定 κ，扫 Q — VLD", fontsize=13, y=1.02)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig_A_k_by_Q(
    out: Path,
    *,
    run_slug: str,
    empty: bool,
    fmin: float,
    fmax: float,
) -> Path:
    plt = _setup_mpl()
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.0), sharex=True, sharey=True)
    for ax, q in zip(axes.ravel(), Q_VALUES):
        any_curve = False
        for k in K_VALUES:
            cid = case_id(Af=2.0, Q=q, deq=2.0, k=k)
            freqs, _t, vld, ok = load_case_series(cid, run_slug, empty=empty, fmin=fmin, fmax=fmax)
            line = _plot_curve(
                ax, freqs, vld, color=K_COLORS[k], label=f"κ={k:g}", empty=empty or not ok
            )
            if line is not None:
                any_curve = True
        _style_vld_ax(ax, xmin=fmin, xmax=fmax, title=f"Q = {q:g}  (Af=2, deq=2)")
        if empty:
            _empty_note(ax)
        elif not any_curve:
            _empty_note(ax, "暂无数据")
        else:
            ax.legend(fontsize=8, loc="best", frameon=True)
    fig.suptitle("组 A：固定 Q，扫 κ — VLD", fontsize=13, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig_B_Af(
    out: Path,
    *,
    run_slug: str,
    empty: bool,
    fmin: float,
    fmax: float,
) -> Path:
    plt = _setup_mpl()
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.0), sharey=True)
    for ax, af in zip(axes, AF_SWEEP):
        cid = case_id(Af=af, Q=1.0, deq=2.0, k=1.0)
        freqs, _t, vld, ok = load_case_series(cid, run_slug, empty=empty, fmin=fmin, fmax=fmax)
        _plot_curve(ax, freqs, vld, color=AF_COLORS[af], label=cid, empty=empty or not ok)
        _style_vld_ax(ax, xmin=fmin, xmax=fmax, title=f"Af = {af:g} mm  (Q=1, deq=2, κ=1)")
        if empty or not ok:
            _empty_note(ax, "（空图预览）" if empty else "暂无数据")
    fig.suptitle("组 B：扫 Af — VLD", fontsize=13, y=1.02)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig_B_deq(
    out: Path,
    *,
    run_slug: str,
    empty: bool,
    fmin: float,
    fmax: float,
) -> Path:
    plt = _setup_mpl()
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.0), sharey=True)
    for ax, deq in zip(axes, DEQ_SWEEP):
        cid = case_id(Af=2.0, Q=1.0, deq=deq, k=1.0)
        freqs, _t, vld, ok = load_case_series(cid, run_slug, empty=empty, fmin=fmin, fmax=fmax)
        _plot_curve(ax, freqs, vld, color=DEQ_COLORS[deq], label=cid, empty=empty or not ok)
        _style_vld_ax(ax, xmin=fmin, xmax=fmax, title=f"deq = {deq:g} mm  (Af=2, Q=1, κ=1)")
        if empty or not ok:
            _empty_note(ax, "（空图预览）" if empty else "暂无数据")
    fig.suptitle("组 B：扫 deq — VLD", fontsize=13, y=1.02)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig_S_metrics(
    out: Path,
    *,
    run_slug: str,
    empty: bool,
    fmin: float,
    fmax: float,
) -> Path:
    plt = _setup_mpl()
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.0))
    titles = [
        "主峰频率 (Hz)",
        "峰值 VLD (dB)",
        "隔振起始频率 (Hz)",
        "VLD<0 带宽 (Hz)",
    ]
    keys = [
        "peak_VLD_freq_Hz",
        "peak_VLD_dB",
        "isolation_onset_Hz",
        "isolation_band_Hz",
    ]
    x = list(Q_VALUES)
    width = 0.22

    for ax, title, key in zip(axes.ravel(), titles, keys):
        if empty:
            _empty_note(ax)
            ax.set_title(title, fontsize=11)
            ax.set_xlabel("Q")
            ax.set_xlim(-0.2, 1.7)
            ax.grid(True, alpha=0.3)
            continue
        for i, k in enumerate(K_VALUES):
            ys = []
            for q in Q_VALUES:
                cid = case_id(Af=2.0, Q=q, deq=2.0, k=k)
                path = csv_path_for(cid, run_slug)
                if path.is_file():
                    rows = read_trans_csv(path)
                    m = metrics_from_rows(rows, fmax=fmax) if rows else {}
                    ys.append(m.get(key, float("nan")))
                else:
                    ys.append(float("nan"))
            offsets = [xx + (i - 1) * width for xx in x]
            plot_x = []
            plot_y = []
            for xx, y in zip(offsets, ys):
                if isinstance(y, float) and math.isnan(y):
                    continue
                plot_x.append(xx)
                plot_y.append(y)
            if plot_x:
                ax.bar(
                    plot_x,
                    plot_y,
                    width=width,
                    color=K_COLORS[k],
                    label=f"κ={k:g}",
                    alpha=0.85,
                )
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("Q")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{q:g}" for q in Q_VALUES])
        ax.grid(True, axis="y", alpha=0.3)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=8, loc="best")
        if not handles:
            _empty_note(ax, "暂无数据")

    fig.suptitle(f"组 A 标量汇总（频段 {fmin:g}–{fmax:g} Hz）", fontsize=13, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig_all_small_multiples(
    out: Path,
    *,
    run_slug: str,
    empty: bool,
    fmin: float,
    fmax: float,
    case_ids: list[str],
) -> Path:
    plt = _setup_mpl()
    n = max(len(case_ids), 1)
    ncols = 4
    nrows = int(math.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(14.0, 3.1 * nrows), sharex=True, sharey=True)
    axes_flat = list(axes.ravel()) if hasattr(axes, "ravel") else [axes]
    for i, ax in enumerate(axes_flat):
        if i >= n:
            ax.axis("off")
            continue
        cid = case_ids[i]
        freqs, _t, vld, ok = load_case_series(cid, run_slug, empty=empty, fmin=fmin, fmax=fmax)
        _plot_curve(ax, freqs, vld, color="#1565C0", label=cid, empty=empty or not ok)
        _style_vld_ax(ax, xmin=fmin, xmax=fmax, title=cid)
        if empty or not ok:
            _empty_note(ax, "暂无数据" if not empty else "（空图预览）")
    fig.suptitle("全案 VLD 小多图总览", fontsize=13, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def write_summary_stub(out_dir: Path, case_ids: list[str], *, run_slug: str, empty: bool) -> Path:
    rows = []
    for cid in case_ids:
        path = csv_path_for(cid, run_slug)
        entry = {"case_id": cid, "csv": str(path.as_posix()), "has_csv": False}
        if not empty and path.is_file():
            data = read_trans_csv(path)
            if data:
                entry["has_csv"] = True
                entry.update(metrics_from_rows(data, fmax=500.0))
        rows.append(entry)
    out = out_dir / "_compare_summary.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量构型 COMSOL 对比图（6 PNG）")
    parser.add_argument("--empty", action="store_true", help="强制空图预览（不读 CSV）")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--run-slug", default=DEFAULT_RUN_SLUG)
    parser.add_argument("--fmin", type=float, default=10.0)
    parser.add_argument("--fmax", type=float, default=500.0)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = load_batch_index()
    case_ids = all_case_ids(index)
    if not case_ids:
        # fallback layout ids for empty preview
        case_ids = [
            case_id(Af=2.0, Q=q, deq=2.0, k=k) for k in K_VALUES for q in Q_VALUES
        ] + [
            case_id(Af=af, Q=1.0, deq=2.0, k=1.0) for af in (1.0, 3.0)
        ] + [
            case_id(Af=2.0, Q=1.0, deq=deq, k=1.0) for deq in (1.5, 2.5)
        ]

    paths = [
        fig_A_Q_by_k(
            out_dir / "A_Q_by_k.png",
            run_slug=args.run_slug,
            empty=args.empty,
            fmin=args.fmin,
            fmax=args.fmax,
        ),
        fig_A_k_by_Q(
            out_dir / "A_k_by_Q.png",
            run_slug=args.run_slug,
            empty=args.empty,
            fmin=args.fmin,
            fmax=args.fmax,
        ),
        fig_B_Af(
            out_dir / "B_Af.png",
            run_slug=args.run_slug,
            empty=args.empty,
            fmin=args.fmin,
            fmax=args.fmax,
        ),
        fig_B_deq(
            out_dir / "B_deq.png",
            run_slug=args.run_slug,
            empty=args.empty,
            fmin=args.fmin,
            fmax=args.fmax,
        ),
        fig_S_metrics(
            out_dir / "S_metrics.png",
            run_slug=args.run_slug,
            empty=args.empty,
            fmin=args.fmin,
            fmax=args.fmax,
        ),
        fig_all_small_multiples(
            out_dir / "All_small_multiples.png",
            run_slug=args.run_slug,
            empty=args.empty,
            fmin=args.fmin,
            fmax=args.fmax,
            case_ids=case_ids,
        ),
    ]
    summary = write_summary_stub(out_dir, case_ids, run_slug=args.run_slug, empty=args.empty)
    print("Wrote:")
    for p in paths:
        print(f"  {p}")
    print(f"  {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
