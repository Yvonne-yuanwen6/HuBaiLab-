"""
Import WebPlotDigitizer (WPD) exports → HuBaiLab Fig.3.3 standard JSON.

Recommended workflow (most accurate):
  1. Open https://automeris.io/WebPlotDigitizer/
  2. Load thesis Fig.3.3 PNG
  3. Axes: XY, calibrate (0,0) and (0.8, 0.04) on plot corners
  4. Add 4 datasets (BCC / AF2Q05 / AF2Q1 / AF2Q15), trace each curve
  5. File → Export JSON (or export 4 CSVs)
  6. Save to data/reference/wpd/

  py -3 scripts/import_webplotdigitizer_fig33.py --json data/reference/wpd/fig33.json
  py -3 scripts/import_webplotdigitizer_fig33.py --csv-dir data/reference/wpd/csv
  py -3 scripts/plot_hu_bai_fig33_standard.py

WPD dataset names (any substring match):
  bcc, af2q05 / q0.5, af2q1 / q1, af2q15 / q1.5
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.postprocess.fig33_plot_style import enrich_fig33_series_densification

OUT_JSON = _ROOT / "data" / "hu_bai_fig33_experiment_traced.json"

# WPD name substring → our series key
NAME_MAP = (
    ("bcc", "bcc"),
    ("af2q0", "bcc"),
    ("q0", "bcc"),
    ("af2q05", "af2q05"),
    ("q05", "af2q05"),
    ("0.5", "af2q05"),
    ("af2q1", "af2q1"),
    ("q1", "af2q1"),
    ("af2q15", "af2q15"),
    ("q15", "af2q15"),
    ("1.5", "af2q15"),
)

SERIES_META = {
    "bcc": {"label": "BCC-实验", "color": "#7EC8E3"},
    "af2q05": {"label": "AF2Q05-实验", "color": "#1565C0"},
    "af2q1": {"label": "AF2Q1-实验", "color": "#F48FB1"},
    "af2q15": {"label": "AF2Q15-实验", "color": "#E53935"},
}


def _match_key(name: str) -> str | None:
    n = name.lower().replace(" ", "").replace("_", "").replace("-", "")
    # prefer longer / specific matches
    for pat, key in sorted(NAME_MAP, key=lambda x: -len(x[0])):
        if pat.replace(".", "") in n or pat in n:
            # avoid q1 matching q15 / q05
            if key == "af2q1" and ("q15" in n or "q05" in n or "1.5" in n or "af2q15" in n or "0.5" in n):
                continue
            if key == "bcc" and ("q05" in n or "q15" in n):
                continue
            if key == "bcc" and "q1" in n and "bcc" not in n:
                continue
            return key
    return None


TARGET_XMAX = 0.8
TARGET_YMAX = 0.04


def _axis_scale_from_wpd(raw: dict) -> tuple[float, float, float, float]:
    """Map WPD calibrated coords → thesis axes (0–0.8 strain, 0–0.04 MPa)."""
    axes_list = raw.get("axesColl") or []
    if not axes_list:
        return 1.0, 1.0, TARGET_XMAX, TARGET_YMAX
    cps = axes_list[0].get("calibrationPoints") or []
    dxs: list[float] = []
    dys: list[float] = []
    for cp in cps:
        try:
            dxs.append(float(cp.get("dx", 0)))
            dys.append(float(cp.get("dy", 0)))
        except (TypeError, ValueError):
            pass
    xmax = max(dxs) if dxs else 1.0
    ymax = max(dys) if dys else 1.0
    if xmax <= 0:
        xmax = 1.0
    if ymax <= 0:
        ymax = 1.0
    sx = TARGET_XMAX / xmax
    sy = TARGET_YMAX / ymax
    return sx, sy, xmax, ymax


def _rescale_points(vals: list, sx: float, sy: float) -> list[list[float]]:
    return [[float(v[0]) * sx, float(v[1]) * sy] for v in vals]


def _sort_dedupe(points: list[list[float]]) -> list[list[float]]:
    pts = sorted(((float(x), float(y)) for x, y in points), key=lambda p: p[0])
    out: list[list[float]] = []
    for x, y in pts:
        if x < -1e-6 or y < -1e-6:
            continue
        if out and x - out[-1][0] < 5e-4:
            continue
        out.append([round(x, 5), round(max(0.0, y), 5)])
    return out


def parse_wpd_json(path: Path) -> dict[str, list[list[float]]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    datasets: list[tuple[str, list]] = []

    # WPD 4.x project export
    if "version" in raw and "datasetColl" in raw:
        for ds in raw["datasetColl"]:
            name = ds.get("name", "unnamed")
            data = ds.get("data", [])
            vals = [d["value"][:2] for d in data if "value" in d and len(d["value"]) >= 2]
            datasets.append((name, vals))
    # older wpd-python format
    elif "wpd" in raw and "dataSeries" in raw["wpd"]:
        for ds in raw["wpd"]["dataSeries"]:
            name = ds.get("name", "unnamed")
            vals = [d["value"][:2] for d in ds.get("data", []) if "value" in d]
            datasets.append((name, vals))
    else:
        raise ValueError(f"Unrecognized WPD JSON structure: {path}")

    sx, sy, xmax, ymax = _axis_scale_from_wpd(raw)
    if abs(xmax - TARGET_XMAX) > 0.05 or abs(ymax - TARGET_YMAX) > 0.005:
        print(f"  axis rescale: WPD xmax={xmax} ymax={ymax} → strain×{sx:.4f}, stress×{sy:.4f}")

    out: dict[str, list[list[float]]] = {}
    for name, vals in datasets:
        key = _match_key(name)
        if not key:
            print(f"[WARN] skip dataset (rename to include bcc/af2q05/af2q1/af2q15): {name!r}")
            continue
        pts = _sort_dedupe(_rescale_points(vals, sx, sy))
        if key in out:
            print(f"[WARN] duplicate key {key}: merging {name!r}")
            out[key] = _sort_dedupe(out[key] + pts)
        else:
            out[key] = pts
            print(f"  {name!r} → {key}: {len(pts)} points")
    return out


def parse_wpd_csv_dir(csv_dir: Path) -> dict[str, list[list[float]]]:
    out: dict[str, list[list[float]]] = {}
    for csv_path in sorted(csv_dir.glob("*.csv")):
        name = csv_path.stem
        key = _match_key(name)
        if not key:
            print(f"[WARN] skip {csv_path.name}")
            continue
        pts: list[list[float]] = []
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        # skip header if present
        start = 1 if rows and not _is_float(rows[0][0]) else 0
        for row in rows[start:]:
            if len(row) < 2:
                continue
            try:
                pts.append([float(row[0]), float(row[1])])
            except ValueError:
                continue
        out[key] = _sort_dedupe(pts)
        print(f"  {csv_path.name} → {key}: {len(out[key])} points")
    return out


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def build_fig33_json(curves: dict[str, list[list[float]]], *, source: str) -> dict:
    series = {}
    for key in ("bcc", "af2q05", "af2q1", "af2q15"):
        meta = SERIES_META[key]
        pts = curves.get(key, [])
        entry = {"label": meta["label"], "color": meta["color"], "points": pts}
        entry = enrich_fig33_series_densification(entry, key)
        series[key] = entry
    return {
        "_comment": "Imported via scripts/import_webplotdigitizer_fig33.py — pixel-accurate from WPD",
        "source": source,
        "x_label": "应变",
        "y_label": "应力 (MPa)",
        "xlim": [0.0, 0.8],
        "ylim": [0.0, 0.04],
        "series": series,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import WebPlotDigitizer export for Fig.3.3")
    parser.add_argument("--json", type=Path, help="WPD project JSON export")
    parser.add_argument("--csv-dir", type=Path, help="Directory of WPD CSV exports (one per curve)")
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    args = parser.parse_args()

    if not args.json and not args.csv_dir:
        parser.error("Provide --json or --csv-dir")

    if args.json:
        if not args.json.is_file():
            print(f"Missing: {args.json}")
            return 1
        print(f"Import WPD JSON: {args.json}")
        curves = parse_wpd_json(args.json)
        source = str(args.json.relative_to(_ROOT)) if args.json.is_relative_to(_ROOT) else str(args.json)
    else:
        if not args.csv_dir.is_dir():
            print(f"Missing dir: {args.csv_dir}")
            return 1
        print(f"Import WPD CSV dir: {args.csv_dir}")
        curves = parse_wpd_csv_dir(args.csv_dir)
        source = str(args.csv_dir.relative_to(_ROOT)) if args.csv_dir.is_relative_to(_ROOT) else str(args.csv_dir)

    missing = [k for k in ("bcc", "af2q05", "af2q1", "af2q15") if k not in curves or not curves[k]]
    if missing:
        print(f"[ERROR] missing curves: {missing}")
        return 1

    data = build_fig33_json(curves, source=source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Wrote:", args.out)
    print("Next: py -3 scripts/plot_hu_bai_fig33_standard.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
