"""COMSOL isolation curve plotting (VLD, transmissibility, peak markers)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence


def rows_to_series(rows: list[dict]) -> tuple[list[float], list[float], list[float]]:
    freqs = [float(r["frequency_Hz"]) for r in rows]
    trans = [float(r.get("transmissibility", r.get("T_eq320", "nan"))) for r in rows]
    if rows and "VLD_dB" in rows[0]:
        vld = [float(r["VLD_dB"]) for r in rows]
    else:
        vld = [20.0 * math.log10(t) if t > 0.0 else float("nan") for t in trans]
    return freqs, trans, vld


def pick_vld_peaks(
    freqs: Sequence[float],
    vld: Sequence[float],
    *,
    min_hz: float = 1.0,
    min_sep_hz: float = 8.0,
    n: int = 3,
) -> list[dict[str, float]]:
    """Local maxima on VLD(f) — resonance peaks (thesis Fig 3.20 / 3.22)."""
    data = [(float(f), float(v)) for f, v in zip(freqs, vld, strict=False) if v == v]
    if len(data) < 3:
        ranked = sorted([(f, v) for f, v in data if f >= min_hz], key=lambda x: -x[1])
        return [{"rank": i + 1, "freq_hz": f, "vld_dB": v} for i, (f, v) in enumerate(ranked[:n])]

    local: list[tuple[float, float]] = []
    for i in range(1, len(data) - 1):
        f, v = data[i]
        if f < min_hz:
            continue
        if v >= data[i - 1][1] and v >= data[i + 1][1]:
            local.append((f, v))

    if not local:
        ranked = sorted([(f, v) for f, v in data if f >= min_hz], key=lambda x: -x[1])
        return [{"rank": i + 1, "freq_hz": f, "vld_dB": v} for i, (f, v) in enumerate(ranked[:n])]

    local.sort(key=lambda x: x[0])
    clusters: list[dict[str, float]] = []
    for f, v in local:
        if not clusters or abs(f - clusters[-1]["freq_hz"]) >= min_sep_hz:
            clusters.append({"freq_hz": f, "vld_dB": v})
        elif v > clusters[-1]["vld_dB"]:
            clusters[-1] = {"freq_hz": f, "vld_dB": v}

    return [{"rank": i + 1, **cl} for i, cl in enumerate(clusters[:n])]


def pick_resonance_peaks(
    freqs: Sequence[float],
    trans: Sequence[float],
    *,
    min_hz: float = 1.0,
    min_sep_hz: float = 8.0,
    n: int = 3,
) -> list[dict[str, float]]:
    data = [(float(f), float(t)) for f, t in zip(freqs, trans, strict=False) if t == t and t > 0]
    if len(data) < 3:
        ranked = sorted([(f, t) for f, t in data if f >= min_hz], key=lambda x: -x[1])
        return [
            {"rank": i + 1, "freq_hz": f, "transmissibility": t}
            for i, (f, t) in enumerate(ranked[:n])
        ]

    local: list[tuple[float, float]] = []
    for i in range(1, len(data) - 1):
        f, t = data[i]
        if f < min_hz:
            continue
        if t >= data[i - 1][1] and t >= data[i + 1][1]:
            local.append((f, t))

    if not local:
        ranked = sorted([(f, t) for f, t in data if f >= min_hz], key=lambda x: -x[1])
        return [
            {"rank": i + 1, "freq_hz": f, "transmissibility": t}
            for i, (f, t) in enumerate(ranked[:n])
        ]

    local.sort(key=lambda x: x[0])
    clusters: list[dict[str, float]] = []
    for f, t in local:
        if not clusters or abs(f - clusters[-1]["freq_hz"]) >= min_sep_hz:
            clusters.append({"freq_hz": f, "transmissibility": t})
        elif t > clusters[-1]["transmissibility"]:
            clusters[-1] = {"freq_hz": f, "transmissibility": t}

    out: list[dict[str, float]] = []
    for i, cl in enumerate(clusters[:n], start=1):
        out.append({"rank": i, **cl})
    return out


def _annotate_peaks(ax: Any, peaks: list[dict[str, float]], *, y_key: str) -> None:
    for pk in peaks:
        f = pk["freq_hz"]
        y = pk[y_key] if y_key in pk else pk.get("transmissibility", float("nan"))
        if y != y:
            continue
        ax.axvline(f, color="#9E9E9E", linestyle=":", linewidth=0.9, alpha=0.7)
        ax.plot(f, y, "o", color="#F57C00", markersize=6, zorder=5)
        ax.annotate(
            f"{f:.1f} Hz",
            xy=(f, y),
            xytext=(6, 8),
            textcoords="offset points",
            fontsize=8,
            color="#E65100",
        )


def _annotate_paper_refs(ax: Any, paper_freqs: Sequence[float], ymax: float) -> None:
    colors = ("#1565C0", "#2E7D32", "#6A1B9A")
    for i, pf in enumerate(paper_freqs[:3]):
        ax.axvline(
            pf,
            color=colors[i % len(colors)],
            linestyle="--",
            linewidth=1.0,
            alpha=0.55,
            label=f"论文 fn{i + 1}={pf:g} Hz" if i == 0 else f"论文 fn{i + 1}={pf:g} Hz",
        )


def _autoscale_vld_ylim(
    vld: Sequence[float],
    peaks: Sequence[dict[str, float]] | None = None,
    *,
    pad_db: float = 5.0,
    min_span_db: float = 15.0,
) -> tuple[float, float]:
    """Y limits from data with padding; always bracket VLD=0 when in range."""
    vals = [float(v) for v in vld if v == v]
    if peaks:
        for pk in peaks:
            y = pk.get("vld_dB")
            if y is not None and y == y:
                vals.append(float(y))
    if not vals:
        return (-10.0, 10.0)
    lo, hi = min(vals), max(vals)
    lo = min(lo, 0.0)
    hi = max(hi, 0.0)
    span = max(hi - lo, min_span_db)
    pad = max(pad_db, 0.1 * span)
    return lo - pad, hi + pad


def plot_vld(
    rows: list[dict],
    out_png: Path,
    *,
    title: str = "",
    peaks: list[dict[str, float]] | None = None,
    paper_freqs: Sequence[float] | None = None,
    ylim: tuple[float, float] | None = None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    freqs, trans, vld = rows_to_series(rows)
    peaks = peaks or pick_vld_peaks(freqs, vld)

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.plot(freqs, vld, "-", color="#C62828", linewidth=1.5, label="VLD (仿真)")
    ax.axhline(0.0, color="#757575", linestyle="--", linewidth=1.0, label="VLD = 0 dB（隔振临界）")
    if paper_freqs:
        _annotate_paper_refs(ax, paper_freqs, max(vld) if vld else 0.0)
    _annotate_peaks(ax, peaks, y_key="vld_dB")
    ax.set_xlabel("频率 (Hz)")
    ax.set_ylabel("振动水平差 VLD (dB)  式 (3.6)")
    ax.set_title(title or "振动水平差–频率曲线")
    y0, y1 = ylim if ylim is not None else _autoscale_vld_ylim(vld, peaks)
    ax.set_ylim(y0, y1)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def plot_transmissibility(
    rows: list[dict],
    out_png: Path,
    *,
    title: str = "",
    peaks: list[dict[str, float]] | None = None,
    paper_freqs: Sequence[float] | None = None,
    logy: bool = True,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    freqs, trans, _ = rows_to_series(rows)
    peaks = peaks or pick_resonance_peaks(freqs, trans)

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    if logy:
        ax.semilogy(freqs, trans, "-", color="#1565C0", linewidth=1.5, label="传递率 T (仿真)")
        ax.axhline(1.0, color="#757575", linestyle="--", linewidth=1.0, label="T = 1")
    else:
        ax.plot(freqs, trans, "-", color="#1565C0", linewidth=1.5, label="传递率 T (仿真)")
        ax.axhline(1.0, color="#757575", linestyle="--", linewidth=1.0, label="T = 1")
    if paper_freqs:
        _annotate_paper_refs(ax, paper_freqs, max(trans) if trans else 1.0)
    _annotate_peaks(ax, peaks, y_key="transmissibility")
    ax.set_xlabel("频率 (Hz)")
    ax.set_ylabel("传递率 T（式 3.20）")
    ax.set_title(title or "振动传递率–频率曲线")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def plot_isolation_combo(
    rows: list[dict],
    out_png: Path,
    *,
    title: str = "",
    peaks: list[dict[str, float]] | None = None,
    paper_freqs: Sequence[float] | None = None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    freqs, trans, vld = rows_to_series(rows)
    peaks = peaks or pick_resonance_peaks(freqs, trans)

    fig, (ax_t, ax_v) = plt.subplots(2, 1, figsize=(8.0, 7.0), sharex=True)
    ax_t.semilogy(freqs, trans, "-", color="#1565C0", linewidth=1.5, label="T (仿真)")
    ax_t.axhline(1.0, color="#757575", linestyle="--", linewidth=1.0)
    _annotate_peaks(ax_t, peaks, y_key="transmissibility")
    ax_t.set_ylabel("传递率 T")
    ax_t.grid(True, which="both", alpha=0.3)
    ax_t.legend(loc="best", fontsize=9)

    ax_v.plot(freqs, vld, "-", color="#C62828", linewidth=1.5, label="VLD (仿真)")
    ax_v.axhline(0.0, color="#757575", linestyle="--", linewidth=1.0)
    vld_peaks = pick_vld_peaks(freqs, vld)
    _annotate_peaks(ax_v, vld_peaks, y_key="vld_dB")
    ax_v.set_xlabel("频率 (Hz)")
    ax_v.set_ylabel("VLD (dB)")
    y0, y1 = _autoscale_vld_ylim(vld, vld_peaks)
    ax_v.set_ylim(y0, y1)
    ax_v.grid(True, alpha=0.3)
    ax_v.legend(loc="best", fontsize=9)

    if paper_freqs:
        for ax in (ax_t, ax_v):
            _annotate_paper_refs(ax, paper_freqs, 0.0)

    if title:
        fig.suptitle(title, fontsize=11, y=1.01)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def export_isolation_plots(
    rows: list[dict],
    job_dir: Path,
    slug: str,
    *,
    title: str = "",
    paper_freqs: Sequence[float] | None = None,
    vld_only: bool = True,
) -> dict[str, str]:
    """Write thesis VLD–frequency PNG(s). T plots optional (vld_only=False)."""
    freqs, trans, vld = rows_to_series(rows)
    peaks = pick_vld_peaks(freqs, vld)
    vld_title = title or "振动水平差–频率曲线"
    outputs = {
        "vld_png": str(
            plot_vld(rows, job_dir / f"{slug}_vld.png", title=vld_title, peaks=peaks, paper_freqs=paper_freqs)
        ),
        "fig322_png": str(
            plot_vld(
                rows,
                job_dir / f"{slug}_fig322_vld.png",
                title=f"{vld_title}（Fig.3.20/3.22）",
                peaks=peaks,
                paper_freqs=paper_freqs,
            )
        ),
    }
    if not vld_only:
        t_peaks = pick_resonance_peaks(freqs, trans)
        outputs["transmissibility_png"] = str(
            plot_transmissibility(
                rows,
                job_dir / f"{slug}_transmissibility.png",
                title=title,
                peaks=t_peaks,
                paper_freqs=paper_freqs,
            )
        )
        outputs["combo_png"] = str(
            plot_isolation_combo(rows, job_dir / f"{slug}_isolation_combo.png", title=title, peaks=t_peaks, paper_freqs=paper_freqs)
        )
    return outputs
