"""Eigenfrequency extraction with participation-factor ranking (COMSOL SME)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.comsol.hu_bai_settings import HuBaiComsolSettings

EIGEN_CSV_FIELDS = (
    "mode",
    "frequency_Hz",
    "mEff_excitation",
    "pf_excitation",
    "excitation_axis",
)

_FREQ_EXPR = "abs(freq)"


def _to_float(value: object) -> float:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, complex):
        return float(abs(value))
    return float(value)


def _flatten(raw: object) -> list[float]:
    if hasattr(raw, "tolist"):
        items = raw.tolist()
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    flat: list[float] = []
    for item in items:
        if isinstance(item, (list, tuple)):
            flat.extend(_flatten(item))
        else:
            flat.append(_to_float(item))
    return flat


def freq_array_to_hz(raw: object) -> list[float]:
    return _flatten(raw)


def participation_exprs(
    settings: HuBaiComsolSettings,
    *,
    mpf_tag: str = "mpf1",
) -> tuple[str, str]:
    axis = {"x": "X", "y": "Y", "z": "Z"}.get(settings.excitation_axis.lower(), "Z")
    return f"{mpf_tag}.mEffL{axis}", f"{mpf_tag}.pfL{axis}"


def resolve_eigen_dataset(java: Any, *, study_tag: str = "std_eigen") -> str:
    """Return eigen solution dataset tag (COMSOL 5.6: Eigenfrequency or Solution from eigen study)."""
    res = java.result()
    tags = [str(t) for t in res.dataset().tags()]
    for tag in tags:
        try:
            if "Eigen" in str(res.dataset(tag).getType()):
                return tag
        except Exception:
            continue
    for tag in tags:
        try:
            ds = res.dataset(tag)
            sol = str(ds.getString("solution"))
            if study_tag in sol or "eigen" in sol.lower():
                return tag
        except Exception:
            continue
    return tags[0] if tags else ""


def _get_eval_global(java: Any, gev_tag: str) -> Any | None:
    res = java.result()
    tags = [str(t) for t in res.numerical().tags()]
    if gev_tag not in tags:
        try:
            return res.numerical().create(gev_tag, "EvalGlobal")
        except Exception:
            return None
    return res.numerical(gev_tag)


def count_eigen_solutions(
    java: Any,
    *,
    dset_tag: str,
    max_modes: int,
    gev_tag: str = "gev_count_modes",
) -> int:
    """Count stored eigen solnums via EvalGlobal(abs(freq))."""
    if not dset_tag:
        return 0
    gev = _get_eval_global(java, gev_tag)
    if gev is None:
        return 0
    try:
        gev.set("data", dset_tag)
        gev.set("expr", [_FREQ_EXPR])
    except Exception:
        return 0

    n = 0
    for solnum in range(1, max_modes + 1):
        try:
            gev.set("solnum", str(solnum))
            gev.getReal()
            n = solnum
        except Exception:
            break
    return n


def _eval_global_series(
    java: Any,
    *,
    dset_tag: str,
    expr: str,
    n_modes: int,
    gev_tag: str,
) -> list[float] | None:
    if not dset_tag or not expr or n_modes <= 0:
        return None
    gev = _get_eval_global(java, gev_tag)
    if gev is None:
        return None
    try:
        gev.set("data", dset_tag)
        gev.set("expr", [expr])
    except Exception:
        return None

    vals: list[float] = []
    for solnum in range(1, n_modes + 1):
        try:
            gev.set("solnum", str(solnum))
            raw = gev.getReal()
            if hasattr(raw, "tolist"):
                raw = raw.tolist()
            if isinstance(raw, (list, tuple)) and raw:
                cell = raw[0][0] if isinstance(raw[0], (list, tuple)) else raw[0]
                vals.append(_to_float(cell))
            else:
                vals.append(_to_float(raw))
        except Exception:
            break
    return vals if len(vals) == n_modes else None


def _read_participation_table(java: Any, n_modes: int) -> tuple[list[float] | None, list[float] | None]:
    """Fallback: read auto-generated Participation Factors table."""
    res = java.result()
    table_tags = [str(t) for t in res.table().tags()]
    candidates = [t for t in table_tags if "par" in t.lower() or "mpf" in t.lower()]
    if not candidates:
        candidates = table_tags

    for tag in candidates:
        try:
            tbl = res.table(tag)
            try:
                ncol = int(tbl.getNCols())
                nrows = int(tbl.getNRows())
            except Exception:
                continue
            if ncol < 2 or nrows < n_modes:
                continue
            headers = []
            for i in range(ncol):
                try:
                    headers.append(str(tbl.getColumnHeader(i)))
                except Exception:
                    headers.append(f"col{i}")

            meff_col = pf_col = None
            for i, h in enumerate(headers):
                hl = h.lower()
                if "meff" in hl and ("lz" in hl or "z" in hl or "l z" in hl):
                    meff_col = i
                if "pf" in hl and ("lz" in hl or "z" in hl or "l z" in hl):
                    pf_col = i
            if meff_col is None:
                for i, h in enumerate(headers):
                    if "meff" in h.lower():
                        meff_col = i
                        break
            if pf_col is None:
                for i, h in enumerate(headers):
                    if "pf" in h.lower() and "norm" not in h.lower():
                        pf_col = i
                        break
            if meff_col is None:
                continue

            meff = [abs(_to_float(tbl.get(i, meff_col))) for i in range(n_modes)]
            pf = None
            if pf_col is not None:
                pf = [_to_float(tbl.get(i, pf_col)) for i in range(n_modes)]
            return meff, pf
        except Exception:
            continue
    return None, None


def extract_eigen_rows(
    model: Any,
    java: Any,
    settings: HuBaiComsolSettings,
    *,
    mpf_tag: str = "mpf1",
) -> list[dict]:
    """Eigen modes in solver order (solnum = mode index); no frequency sorting."""
    dset = resolve_eigen_dataset(java, study_tag=settings.study_eigen_tag)
    max_modes = max(settings.n_eigenmodes, 1) + 5
    n_modes = count_eigen_solutions(java, dset_tag=dset, max_modes=max_modes)

    freqs: list[float] | None = None
    if n_modes > 0:
        freqs = _eval_global_series(
            java,
            dset_tag=dset,
            expr=_FREQ_EXPR,
            n_modes=n_modes,
            gev_tag="gev_extract_freq",
        )

    if not freqs and dset:
        try:
            freqs = freq_array_to_hz(model.evaluate("freq", dataset=dset))
            n_modes = len(freqs)
        except Exception:
            freqs = None

    if not freqs:
        raise RuntimeError(
            "Could not extract eigen frequencies from dataset "
            f"{dset!r} — check eigen study solved and EvalGlobal abs(freq) works"
        )

    if n_modes == 0:
        return []

    meff_expr, pf_expr = participation_exprs(settings, mpf_tag=mpf_tag)
    meff_vals: list[float] | None = None
    pf_vals: list[float] | None = None

    for expr, store_name in ((meff_expr, "meff"), (pf_expr, "pf")):
        series = _eval_global_series(
            java,
            dset_tag=dset,
            expr=expr,
            n_modes=n_modes,
            gev_tag=f"gev_extract_{store_name}",
        )
        if store_name == "meff" and series is not None:
            meff_vals = [abs(v) for v in series]
        if store_name == "pf" and series is not None:
            pf_vals = series

    if meff_vals is None:
        try:
            meff_raw = model.evaluate(meff_expr)
            meff_vals = [abs(v) for v in _flatten(meff_raw)]
            if len(meff_vals) != n_modes:
                meff_vals = None
        except Exception:
            meff_vals = None

    if pf_vals is None:
        try:
            pf_raw = model.evaluate(pf_expr)
            pf_vals = _flatten(pf_raw)
            if len(pf_vals) != n_modes:
                pf_vals = None
        except Exception:
            pf_vals = None

    if meff_vals is None:
        meff_tbl, pf_tbl = _read_participation_table(java, n_modes)
        meff_vals = meff_tbl
        if pf_vals is None:
            pf_vals = pf_tbl

    rows: list[dict] = []
    for i, freq in enumerate(freqs):
        solnum = i + 1
        rows.append(
            {
                "mode": solnum,
                "frequency_Hz": freq,
                "mEff_excitation": meff_vals[i] if meff_vals and i < len(meff_vals) else None,
                "pf_excitation": pf_vals[i] if pf_vals and i < len(pf_vals) else None,
                "excitation_axis": settings.excitation_axis.lower(),
            }
        )
    return rows


def rank_modes_by_meff(
    rows: list[dict],
    *,
    min_hz: float = 1.0,
    n: int = 3,
) -> list[dict]:
    """Top-N modes by |mEff| along excitation axis (skip near-zero frequencies)."""
    ranked = [
        r
        for r in rows
        if r["frequency_Hz"] >= min_hz and r.get("mEff_excitation") is not None
    ]
    ranked.sort(key=lambda r: abs(float(r["mEff_excitation"])), reverse=True)
    out: list[dict] = []
    for rank, row in enumerate(ranked[:n], start=1):
        out.append(
            {
                "rank_mEff": rank,
                "mode": row["mode"],
                "frequency_Hz": row["frequency_Hz"],
                "mEff_excitation": row["mEff_excitation"],
                "pf_excitation": row.get("pf_excitation"),
            }
        )
    return out


def write_eigen_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(EIGEN_CSV_FIELDS), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
