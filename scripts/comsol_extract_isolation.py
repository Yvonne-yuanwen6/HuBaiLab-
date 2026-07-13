#!/usr/bin/env python3
"""Extract eigenfrequencies and transmissibility from solved COMSOL isolation .mph."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import jpype

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from typing import Any

from src.comsol.eigen_extract import (
    EIGEN_CSV_FIELDS,
    extract_eigen_rows,
    rank_modes_by_meff,
    write_eigen_csv,
)
from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.mph_builder import _ensure_comsol_env, _import_mph


def _to_frequency_hz(value: object) -> float:
    """COMSOL may return complex eigenfrequencies; use |freq| for modes."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, complex):
        return float(abs(value))
    return float(value)


def _freq_array_to_hz(raw: object) -> list[float]:
    if hasattr(raw, "tolist"):
        items = raw.tolist()
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    flat: list[float] = []
    for item in items:
        if isinstance(item, (list, tuple)):
            flat.extend(_freq_array_to_hz(item))
        else:
            flat.append(_to_frequency_hz(item))
    return flat


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _probe_table_tags(java: Any) -> list[str]:
    try:
        return [str(t) for t in java.result().table().tags()]
    except Exception:
        return []


def _to_float(value: object) -> float:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, complex):
        return float(abs(value))
    return float(value)


def _read_probe_table(java: Any, tag: str) -> tuple[list[float], list[float]]:
    tbl = java.result().table(tag)
    nrows = int(tbl.getNRows())
    if nrows <= 0:
        return [], []
    freqs: list[float] = []
    vals: list[float] = []
    # COMSOL 5.6: prefer getColumn(); fall back to get(row, col).
    try:
        col0 = list(tbl.getColumn(0))
        col1 = list(tbl.getColumn(1))
        for f_raw, v_raw in zip(col0, col1, strict=False):
            freqs.append(_to_float(f_raw))
            vals.append(abs(_to_float(v_raw)))
        return freqs, vals
    except Exception:
        pass
    for i in range(nrows):
        freqs.append(_to_float(tbl.get(i, 0)))
        vals.append(abs(_to_float(tbl.get(i, 1))))
    return freqs, vals


def _ensure_ball_boundary_selection(
    comp: Any,
    tag: str,
    *,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    r_mm: float,
) -> None:
    """Runtime Ball selection for post-process integration (entitydim=2)."""
    tags = [str(t) for t in comp.selection().tags()]
    if tag in tags:
        comp.selection().remove(tag)
    comp.selection().create(tag, "Ball")
    sel = comp.selection(tag)
    sel.set("entitydim", jpype.JInt(2))
    sel.set("posx", f"{x_mm}[mm]")
    sel.set("posy", f"{y_mm}[mm]")
    sel.set("posz", f"{z_mm}[mm]")
    sel.set("r", f"{r_mm}[mm]")


def _boundary_average_ball(
    java: Any,
    settings: HuBaiComsolSettings,
    *,
    dset_tag: str,
    z_mm: float,
    half_xy_mm: float,
    expr: str,
    solnum: int,
    nint_tag: str,
) -> float:
    """Surface average on a horizontal face via Ball selection (post-process safe)."""
    comp = java.component("comp1")
    sel_tag = f"{nint_tag}_sel"
    r_mm = max(half_xy_mm * 1.414 - 1.0, 5.0)
    _ensure_ball_boundary_selection(
        comp, sel_tag, x_mm=0.0, y_mm=0.0, z_mm=z_mm, r_mm=r_mm
    )
    res = java.result()
    if nint_tag not in [str(t) for t in res.numerical().tags()]:
        nint = res.numerical().create(nint_tag, "AvSurface")
        nint.selection().named(sel_tag)
        nint.set("data", dset_tag)
        nint.set("expr", expr)
    else:
        nint = res.numerical(nint_tag)
        nint.selection().named(sel_tag)
    for key, val in (
        ("outersolnum", jpype.JArray(jpype.JInt)([int(solnum)])),
        ("solnum", str(solnum)),
    ):
        try:
            nint.set(key, val)
            break
        except Exception:
            continue
    raw = nint.getReal()
    return abs(_scalar_from_real(raw))


def _scalar_from_real(raw: object) -> float:
    """Flatten COMSOL getReal() / Java double[][] to one float."""
    if raw is None:
        return float("nan")
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    elif hasattr(raw, "__len__") and not isinstance(raw, (str, bytes)):
        try:
            nested: list = []
            for i in range(len(raw)):
                row = raw[i]
                if hasattr(row, "__len__") and not isinstance(row, (str, bytes)):
                    nested.append([float(row[j]) for j in range(len(row))])
                else:
                    nested.append(float(row))
            raw = nested
        except Exception:
            pass
    while isinstance(raw, (list, tuple)) and raw:
        if len(raw) == 1:
            raw = raw[0]
            continue
        first = raw[0]
        if isinstance(first, (list, tuple)):
            return _scalar_from_real(first)
        return float(first)
    return float(raw)


def _boundary_average(
    java: Any,
    *,
    dset_tag: str,
    sel_name: str,
    expr: str,
    solnum: int,
    nint_tag: str,
) -> float:
    res = java.result()
    if nint_tag not in [str(t) for t in res.numerical().tags()]:
        nint = res.numerical().create(nint_tag, "AvSurface")
        nint.selection().named(sel_name)
        nint.set("data", dset_tag)
        nint.set("expr", expr)
    else:
        nint = res.numerical(nint_tag)
    for key, val in (
        ("outersolnum", jpype.JArray(jpype.JInt)([int(solnum)])),
        ("solnum", str(solnum)),
    ):
        try:
            nint.set(key, val)
            break
        except Exception:
            continue
    raw = nint.getReal()
    return abs(_scalar_from_real(raw))


def _probe_selection_names(settings: HuBaiComsolSettings) -> tuple[str, str]:
    """Input (shaker table top) and output (plate top) boundary selections."""
    if settings.include_shaker_fixture:
        return "sel_table_top", "sel_plate_top"
    return "sel_base", "sel_top"


def _build_vld_row(
    frequency_hz: float,
    *,
    a_in: float,
    a_out: float,
    method: str = "",
) -> dict:
    """Build one CSV row: T = A_out/A_in, VLD = 20·log10(T) (thesis Eq. 3.6 / 3.20)."""
    denom = a_in if a_in > 1e-15 else float("nan")
    t = a_out / denom if denom == denom and denom > 1e-15 else float("nan")
    vld = 20.0 * math.log10(t) if t == t and t > 0.0 else float("nan")
    row = {
        "frequency_Hz": float(frequency_hz),
        "a_out_m_s2": float(a_out),
        "a_in_m_s2": float(a_in),
        "T_eq320": t,
        "transmissibility": t,
        "VLD_dB": vld,
    }
    if method:
        row["extract_method"] = method
    return row


def _rows_from_probe_pair(
    freqs: list[float],
    base_vals: list[float],
    top_vals: list[float],
    *,
    a_in_nom: float,
    method: str,
) -> list[dict]:
    rows: list[dict] = []
    for f, u_in, u_out in zip(freqs, base_vals, top_vals, strict=False):
        if "acc" in method:
            a_in = u_in if u_in > 1e-15 else a_in_nom
            a_out = u_out
        elif u_in > 1e-15:
            t = u_out / u_in
            a_in = a_in_nom
            a_out = a_in_nom * t
        else:
            a_in = a_in_nom
            a_out = 0.0
        rows.append(_build_vld_row(float(f), a_in=a_in, a_out=a_out, method=method))
    return rows


def _eval_mph_probe(model: Any, tag: str, solnum: int) -> float:
    import numpy as np

    raw = model.evaluate(tag, inner=[int(solnum)])
    arr = np.array(raw).ravel()
    if arr.size == 0:
        return float("nan")
    return abs(float(arr[0]))


def _extract_freq_via_probe_tables(java: Any, a_in_nom: float) -> list[dict]:
    """Read COMSOL probe result tables (tbl_pb_*)."""
    pairs = (
        ("tbl_pb_base_acc", "tbl_pb_top_acc", "probe_table_acc"),
        ("tbl_pb_base", "tbl_pb_top", "probe_table_disp"),
    )
    for base_tag, top_tag, method in pairs:
        base_f, base_v = _read_probe_table(java, base_tag)
        top_f, top_v = _read_probe_table(java, top_tag)
        if not base_f or not top_f:
            continue
        if len(base_f) != len(top_f):
            print(f"  WARN: probe table length mismatch {base_tag} vs {top_tag}")
            continue
        rows = _rows_from_probe_pair(base_f, base_v, top_v, a_in_nom=a_in_nom, method=method)
        if rows:
            print(f"  Freq: {method} ({len(rows)} points) from {base_tag}/{top_tag}")
            return rows
    return []


def _extract_freq_via_bulk_probes(model: Any, settings: HuBaiComsolSettings) -> list[dict]:
    """Evaluate pb_base/pb_top for all frequency points in one pass (~20 s)."""
    import numpy as np

    freqs = np.array(model.evaluate("freq")).ravel()
    if freqs.size == 0:
        return []

    a_in_nom = settings.base_acceleration_m_s2
    pairs = (
        ("pb_base_acc", "pb_top_acc", "bulk_probe_acc"),
        ("pb_base", "pb_top", "bulk_probe_disp"),
    )
    for base_tag, top_tag, method in pairs:
        try:
            base_v = np.abs(np.array(model.evaluate(base_tag)).ravel())
            top_v = np.abs(np.array(model.evaluate(top_tag)).ravel())
        except Exception:
            continue
        n = min(freqs.size, base_v.size, top_v.size)
        if n == 0:
            continue
        rows: list[dict] = []
        n_out = 0
        for f, u_in, u_out in zip(freqs[:n], base_v[:n], top_v[:n], strict=False):
            if "acc" in method:
                if u_in > 1e-12 and u_out > 1e-15:
                    rows.append(_build_vld_row(float(f), a_in=u_in, a_out=u_out, method=method))
                    n_out += 1
                else:
                    rows.append(_build_vld_row(float(f), a_in=a_in_nom, a_out=0.0, method=method))
            elif u_in > 1e-15 and u_out > 1e-15:
                t = u_out / u_in
                rows.append(
                    _build_vld_row(float(f), a_in=a_in_nom, a_out=a_in_nom * t, method=method)
                )
                n_out += 1
            else:
                rows.append(_build_vld_row(float(f), a_in=a_in_nom, a_out=0.0, method=method))
        if n_out > 0:
            print(f"  Freq: {method} ({n} points, output nonzero at {n_out})", flush=True)
            return rows
        if np.any(top_v[:n] > 1e-15):
            continue
        print(
            f"  WARN: {top_tag} all zero ({n} points) — check sel_plate_top / plate bonding in .mph",
            flush=True,
        )
    return []


def _extract_freq_via_mph_probes(model: Any, settings: HuBaiComsolSettings) -> list[dict]:
    """Per-point mph probe loop — slow on large .mph; prefer _extract_freq_via_bulk_probes."""
    return _extract_freq_via_bulk_probes(model, settings)


def _extract_freq_via_mph_probes_slow(model: Any, settings: HuBaiComsolSettings) -> list[dict]:
    """Evaluate pb_base / pb_top probe variables per frequency solution."""
    import numpy as np

    freqs = np.array(model.evaluate("freq")).ravel()
    if freqs.size == 0:
        return []

    a_in_nom = settings.base_acceleration_m_s2
    pairs = (
        ("pb_base", "pb_top", "mph_probe_disp"),
        ("pb_base_acc", "pb_top_acc", "mph_probe_acc"),
    )
    for base_tag, top_tag, method in pairs:
        rows: list[dict] = []
        n_out_nonzero = 0
        total = int(freqs.size)
        for i, f in enumerate(freqs, start=1):
            try:
                u_in = _eval_mph_probe(model, base_tag, i)
                u_out = _eval_mph_probe(model, top_tag, i)
            except Exception:
                rows = []
                break
            if u_out > 1e-15:
                n_out_nonzero += 1
            if "acc" in method:
                if u_in > 1e-15:
                    rows.append(_build_vld_row(float(f), a_in=u_in, a_out=u_out, method=method))
                elif u_out > 0:
                    rows.append(_build_vld_row(float(f), a_in=a_in_nom, a_out=u_out, method=method))
                else:
                    rows.append(_build_vld_row(float(f), a_in=a_in_nom, a_out=0.0, method=method))
            else:
                if u_in > 1e-15:
                    t = u_out / u_in
                    rows.append(
                        _build_vld_row(
                            float(f),
                            a_in=a_in_nom,
                            a_out=a_in_nom * t,
                            method=method,
                        )
                    )
                else:
                    rows.append(_build_vld_row(float(f), a_in=a_in_nom, a_out=0.0, method=method))
            if i == 1 or i % 20 == 0 or i == total:
                print(f"  mph_probe progress: {i}/{total} ({base_tag}/{top_tag})", flush=True)
        if rows and n_out_nonzero > 0:
            print(f"  Freq: {method} ({len(rows)} points, output nonzero at {n_out_nonzero})")
            return rows
    return []


def _set_numerical_solnum(nint: Any, solnum: int) -> None:
    for key, val in (
        ("outersolnum", jpype.JArray(jpype.JInt)([int(solnum)])),
        ("solnum", str(solnum)),
    ):
        try:
            nint.set(key, val)
            return
        except Exception:
            continue


class _SurfaceSampler:
    """Reuse one AvSurface/MaxSurface node — avoids 146× create/remove overhead."""

    def __init__(
        self,
        java: Any,
        *,
        dset_tag: str,
        sel_name: str,
        expr: str,
        tag: str,
        op: str = "AvSurface",
    ) -> None:
        res = java.result()
        if tag in [str(t) for t in res.numerical().tags()]:
            res.numerical().remove(tag)
        self._nint = res.numerical().create(tag, op)
        self._nint.selection().named(sel_name)
        self._nint.set("data", dset_tag)
        self._nint.set("expr", expr)

    def at(self, solnum: int) -> float:
        _set_numerical_solnum(self._nint, solnum)
        return abs(_scalar_from_real(self._nint.getReal()))


def _boundary_surface_value(
    java: Any,
    *,
    dset_tag: str,
    sel_name: str,
    expr: str,
    solnum: int,
    nint_tag: str,
    op: str = "AvSurface",
) -> float:
    res = java.result()
    if nint_tag in [str(t) for t in res.numerical().tags()]:
        res.numerical().remove(nint_tag)
    nint = res.numerical().create(nint_tag, op)
    nint.selection().named(sel_name)
    nint.set("data", dset_tag)
    nint.set("expr", expr)
    _set_numerical_solnum(nint, solnum)
    return abs(_scalar_from_real(nint.getReal()))


def _extract_freq_via_boundary(
    model: Any,
    java: Any,
    settings: HuBaiComsolSettings,
) -> list[dict]:
    """Input/output boundary averages on sel_table_top → sel_plate_top (thesis probes)."""
    import numpy as np

    freqs = np.array(model.evaluate("freq")).ravel()
    if freqs.size == 0:
        return []

    dset_tag = _resolve_freq_dataset(java, settings.study_freq_tag)
    base_sel, top_sel = _probe_selection_names(settings)
    disp = settings.excitation_displacement_expr
    a_in_nom = settings.base_acceleration_m_s2
    rows: list[dict] = []
    n_out_nonzero = 0

    base_w = _SurfaceSampler(
        java, dset_tag=dset_tag, sel_name=base_sel, expr=f"abs({disp})", tag="pp_base_w"
    )
    top_w = _SurfaceSampler(
        java, dset_tag=dset_tag, sel_name=top_sel, expr=f"abs({disp})", tag="pp_top_w"
    )
    top_w_max = _SurfaceSampler(
        java,
        dset_tag=dset_tag,
        sel_name=top_sel,
        expr=f"abs({disp})",
        tag="pp_top_wmax",
        op="MaxSurface",
    )

    total = int(freqs.size)
    for i, f in enumerate(freqs, start=1):
        try:
            w_in = base_w.at(i)
            w_out = top_w.at(i)
            if w_out < 1e-15:
                w_out = top_w_max.at(i)
        except Exception:
            break

        if w_in > 1e-15 and w_out > 1e-15:
            t = w_out / w_in
            rows.append(
                _build_vld_row(float(f), a_in=a_in_nom, a_out=a_in_nom * t, method="boundary_disp")
            )
            n_out_nonzero += 1
        else:
            rows.append(_build_vld_row(float(f), a_in=a_in_nom, a_out=0.0, method="boundary"))

        if i == 1 or i % 10 == 0 or i == total:
            print(f"  boundary progress: {i}/{total} freq={float(f):.1f} Hz", flush=True)

    if rows and n_out_nonzero > 0:
        print(
            f"  Freq: boundary input/output ({len(rows)} points, "
            f"{base_sel}→{top_sel}, output nonzero at {n_out_nonzero})",
            flush=True,
        )
        return rows
    return []


def _extract_freq_via_inner(
    model: Any,
    settings: HuBaiComsolSettings,
) -> list[dict]:
    """Deprecated fallback — domain field max is NOT valid for thesis VLD."""
    return []


def _resolve_freq_dataset(java: Any, study_tag: str) -> str:
    tags = [str(t) for t in java.result().dataset().tags()]
    if not tags:
        raise RuntimeError("no result datasets in mph")
    for tag in tags:
        try:
            ds = java.result().dataset(tag)
            sol = str(ds.getString("solution"))
            if study_tag in sol or "freq" in sol.lower():
                return tag
        except Exception:
            continue
    return tags[-1]


def extract_isolation_results(
    mph_path: Path,
    settings: HuBaiComsolSettings,
    *,
    comsol_bin: str | None = None,
    force_boundary: bool = False,
) -> dict:
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)
    job_dir = settings.job_dir()
    out: dict = {"mph": str(mph_path.resolve())}

    client = mph.start(cores=1)
    model = client.load(str(mph_path))
    java = model.java

    if settings.run_eigen:
        try:
            rows = extract_eigen_rows(model, java, settings, mpf_tag=settings.eigen_mpf_tag)
            csv_path = job_dir / f"{settings.default_slug()}_eigenfrequencies.csv"
            write_eigen_csv(csv_path, rows)
            ranked = rank_modes_by_meff(
                rows, min_hz=settings.eigen_min_hz, n=5
            )
            out["eigen_csv"] = str(csv_path)
            out["eigenfrequencies_Hz"] = [r["frequency_Hz"] for r in rows[:10]]
            out["eigen_ranked_by_mEff"] = ranked
            print(f"  Eigen: {len(rows)} modes (solver order) → {csv_path}")
            if ranked:
                print("  Top modes by mEff (excitation axis):")
                for r in ranked[:3]:
                    print(
                        f"    rank {r['rank_mEff']}: solnum={r['mode']}, "
                        f"f={r['frequency_Hz']:.4g} Hz, mEff={r['mEff_excitation']:.4g}"
                    )
            else:
                physical = [r for r in rows if r["frequency_Hz"] >= settings.eigen_min_hz]
                print(f"  Physical (≥{settings.eigen_min_hz} Hz): {len(physical)} modes")
                if physical:
                    print(f"  First physical (Hz): {[r['frequency_Hz'] for r in physical[:5]]}")
        except Exception as exc:
            print(f"  Eigen extract skipped: {exc}")

    if settings.run_frequency:
        try:
            a_in_nom = settings.base_acceleration_m_s2
            freq_rows: list[dict] = []
            extract_method = ""

            for extractor, label in (
                (lambda: _extract_freq_via_boundary(model, java, settings), "boundary"),
                (lambda: _extract_freq_via_bulk_probes(model, settings), "bulk_probe"),
                (lambda: _extract_freq_via_probe_tables(java, a_in_nom), "probe_table"),
            ):
                print(f"  Trying extract: {label}...", flush=True)
                try:
                    freq_rows = extractor()
                except Exception as exc:
                    print(f"  Freq extract {label} failed: {exc}")
                    freq_rows = []
                if freq_rows:
                    extract_method = label
                    break

            if not freq_rows and force_boundary:
                print("  Trying extract: boundary (retry)...", flush=True)
                try:
                    freq_rows = _extract_freq_via_boundary(model, java, settings)
                    if freq_rows:
                        extract_method = "boundary"
                except Exception as exc:
                    print(f"  Freq extract boundary failed: {exc}")

            if not freq_rows:
                tables = _probe_table_tags(java)
                if tables:
                    print(f"  Freq: probe tables present but empty/unreadable: {tables[:8]}")
                print(
                    "  ERROR: no valid VLD data — need input/output probes "
                    "(sel_table_top → sel_plate_top). Field-max fallback disabled."
                )
            else:
                csv_path = job_dir / f"{settings.default_slug()}_transmissibility.csv"
                fields = [
                    "frequency_Hz",
                    "a_out_m_s2",
                    "a_in_m_s2",
                    "T_eq320",
                    "transmissibility",
                    "VLD_dB",
                    "extract_method",
                ]
                for row in freq_rows:
                    row.setdefault("extract_method", extract_method)
                _write_csv(csv_path, fields, freq_rows)
                out["transmissibility_csv"] = str(csv_path)
                out["extract_method"] = extract_method
                vld_path = job_dir / f"{settings.default_slug()}_vld.csv"
                _write_csv(
                    vld_path,
                    ["frequency_Hz", "VLD_dB", "a_in_m_s2", "a_out_m_s2", "extract_method"],
                    [
                        {
                            "frequency_Hz": r["frequency_Hz"],
                            "VLD_dB": r["VLD_dB"],
                            "a_in_m_s2": r["a_in_m_s2"],
                            "a_out_m_s2": r["a_out_m_s2"],
                            "extract_method": r.get("extract_method", extract_method),
                        }
                        for r in freq_rows
                    ],
                )
                out["vld_csv"] = str(vld_path)
                valid = [r for r in freq_rows if r["VLD_dB"] == r["VLD_dB"]]
                print(f"  VLD (Eq.3.6): {len(valid)}/{len(freq_rows)} valid points → {vld_path}")
                print(f"  Data CSV (includes T for Table 3.3): {csv_path}")
        except Exception as exc:
            print(f"  Freq extract skipped: {exc}")

    summary_path = job_dir / f"{settings.default_slug()}_isolation_summary.json"
    summary_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    out["summary_json"] = str(summary_path)
    client.remove(model)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract COMSOL isolation results.")
    parser.add_argument("mph", help="Solved .mph path")
    parser.add_argument("--slug", default="")
    parser.add_argument("--comsol-bin", default="")
    parser.add_argument(
        "--force-boundary",
        action="store_true",
        help="Run slow boundary-avg fallback (~3 min) when bulk probes fail",
    )
    args = parser.parse_args(argv)

    mph_path = Path(args.mph).resolve()
    if not mph_path.is_file():
        raise SystemExit(f"Not found: {mph_path}")

    manifest = mph_path.parent / "case_manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        sdict = data.get("settings", {})
        settings = HuBaiComsolSettings(**{k: v for k, v in sdict.items() if k in HuBaiComsolSettings.__dataclass_fields__})
    else:
        settings = HuBaiComsolSettings(slug=args.slug or mph_path.stem.replace("_solved", ""))

    extract_isolation_results(
        mph_path,
        settings,
        comsol_bin=args.comsol_bin or None,
        force_boundary=args.force_boundary,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
