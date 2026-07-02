"""
Digitize Hu & Bai Fig.3.3 experimental curves from the reference PNG (pixel → data).

Place the thesis figure at:
  data/reference/hu_bai_fig33_experiment.png

Then:
  py -3 scripts/digitize_hu_bai_fig33.py
  py -3 scripts/digitize_hu_bai_fig33.py --calibrate   # click plot corners once
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_IMAGE = _ROOT / "data" / "reference" / "hu_bai_fig33_experiment.png"
DEFAULT_OUT = _ROOT / "data" / "hu_bai_fig33_experiment_traced.json"
CALIB_PATH = _ROOT / "data" / "hu_bai_fig33_plot_calibration.json"

# Default plot box fractions (tuned for typical thesis single-column figure)
DEFAULT_CALIB = {
    "x0_frac": 0.115,
    "x1_frac": 0.905,
    "y0_frac": 0.125,
    "y1_frac": 0.905,
    "xlim": [0.0, 0.8],
    "ylim": [0.0, 0.04],
}

SERIES = {
    "bcc": {
        "label": "BCC-实验",
        "color": "#7EC8E3",
        "mask": lambda r, g, b: (b > 145) & (g > 165) & (r < 140) & (b > r + 20),
    },
    "af2q05": {
        "label": "AF2Q05-实验",
        "color": "#1565C0",
        "mask": lambda r, g, b: (b > 120) & (r < 90) & (g < 130) & (b > r + 50) & (b > g + 10),
    },
    "af2q1": {
        "label": "AF2Q1-实验",
        "color": "#F48FB1",
        "mask": lambda r, g, b: (r > 210) & (g > 120) & (g < 210) & (b > 120) & (b < 210) & (r > g),
    },
    "af2q15": {
        "label": "AF2Q15-实验",
        "color": "#E53935",
        "mask": lambda r, g, b: (r > 170) & (g < 110) & (b < 110) & (r > g + 40) & (r > b + 40),
    },
}


def load_rgb(path: Path) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("Pillow required: pip install pillow") from e
    return np.array(Image.open(path).convert("RGB"))


def load_calib() -> dict:
    if CALIB_PATH.is_file():
        with open(CALIB_PATH, encoding="utf-8") as f:
            return json.load(f)
    return dict(DEFAULT_CALIB)


def save_calib(calib: dict) -> None:
    CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2)
    print("Wrote calibration:", CALIB_PATH)


def pixel_to_data(px: float, py: float, w: int, h: int, calib: dict) -> tuple[float, float]:
    x0 = calib["x0_frac"] * w
    x1 = calib["x1_frac"] * w
    y0 = calib["y0_frac"] * h
    y1 = calib["y1_frac"] * h
    xmin, xmax = calib["xlim"]
    ymin, ymax = calib["ylim"]
    strain = xmin + (px - x0) / (x1 - x0) * (xmax - xmin)
    stress = ymin + (y1 - py) / (y1 - y0) * (ymax - ymin)
    return float(strain), float(stress)


def data_to_pixel(strain: float, stress: float, w: int, h: int, calib: dict) -> tuple[float, float]:
    x0 = calib["x0_frac"] * w
    x1 = calib["x1_frac"] * w
    y0 = calib["y0_frac"] * h
    y1 = calib["y1_frac"] * h
    xmin, xmax = calib["xlim"]
    ymin, ymax = calib["ylim"]
    px = x0 + (strain - xmin) / (xmax - xmin) * (x1 - x0)
    py = y1 - (stress - ymin) / (ymax - ymin) * (y1 - y0)
    return float(px), float(py)


def extract_curve(rgb: np.ndarray, mask_fn, calib: dict, *, n_x: int = 161) -> list[list[float]]:
    h, w = rgb.shape[:2]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    m = mask_fn(r, g, b)
    # suppress legend / inset text regions (top-left)
    lx0 = int(calib.get("legend_x0_frac", 0.115) * w)
    ly1 = int(calib.get("legend_y1_frac", 0.42) * h)
    m[:ly1, : int(0.45 * w)] = False
    # suppress inset photo band (center-right)
    m[int(0.15 * h) : int(0.85 * h), int(0.35 * w) :] &= False

    xs = np.linspace(calib["xlim"][0], calib["xlim"][1], n_x)
    pts: list[list[float]] = []
    for x in xs:
        px, _ = data_to_pixel(x, 0.0, w, h, calib)
        col = int(np.clip(px, 0, w - 1))
        col_mask = m[:, max(0, col - 2) : min(w, col + 3)]
        if not col_mask.any():
            continue
        rows = np.where(col_mask.any(axis=1))[0]
        # curve is upper envelope in plot (lower pixel y = higher stress)
        row = int(rows[np.argmin(rows)])
        strain, stress = pixel_to_data(col, row, w, h, calib)
        if calib["ylim"][0] <= stress <= calib["ylim"][1] * 1.02:
            pts.append([round(strain, 4), round(max(0.0, stress), 5)])
    return _dedupe_monotonic(pts)


def _dedupe_monotonic(pts: list[list[float]]) -> list[list[float]]:
    if not pts:
        return pts
    out = [pts[0]]
    for p in pts[1:]:
        if p[0] > out[-1][0]:
            out.append(p)
    return out


def digitize_all(image_path: Path, calib: dict) -> dict:
    rgb = load_rgb(image_path)
    h, w = rgb.shape[:2]
    series_out = {}
    for key, spec in SERIES.items():
        pts = extract_curve(rgb, spec["mask"], calib)
        entry = {"label": spec["label"], "color": spec["color"], "points": pts}
        from src.postprocess.fig33_plot_style import enrich_fig33_series_densification

        entry = enrich_fig33_series_densification(entry, key)
        series_out[key] = entry
        print(f"{key}: {len(pts)} points, last={pts[-1] if pts else None}")
    return {
        "_comment": "Digitized from PNG via scripts/digitize_hu_bai_fig33.py",
        "source_image": str(image_path.relative_to(_ROOT)) if image_path.is_relative_to(_ROOT) else str(image_path),
        "calibration": calib,
        "x_label": "应变",
        "y_label": "应力 (MPa)",
        "xlim": calib["xlim"],
        "ylim": calib["ylim"],
        "series": series_out,
    }


def run_calibrate(image_path: Path) -> None:
    import matplotlib.pyplot as plt

    rgb = load_rgb(image_path)
    h, w = rgb.shape[:2]
    calib = load_calib()
    clicks: list[tuple[float, float]] = []

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(rgb)
    ax.set_title("Click: bottom-left plot corner, then top-right plot corner")

    def onclick(event):
        if event.xdata is None:
            return
        clicks.append((event.xdata, event.ydata))
        ax.plot(event.xdata, event.ydata, "r+", ms=12)
        fig.canvas.draw_idle()
        if len(clicks) == 2:
            (x0, y0), (x1, y1) = clicks
            calib["x0_frac"] = x0 / w
            calib["x1_frac"] = x1 / w
            calib["y0_frac"] = y1 / h  # bottom in image coords
            calib["y1_frac"] = y0 / h  # top
            save_calib(calib)
            plt.close(fig)

    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()


def validate_overlay(image_path: Path, data: dict, out_png: Path) -> None:
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import apply_fig33_axes_style, configure_matplotlib_chinese

    configure_matplotlib_chinese()
    rgb = load_rgb(image_path)
    calib = data.get("calibration", load_calib())
    h, w = rgb.shape[:2]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.imshow(rgb, extent=[0, w, h, 0], alpha=0.35, zorder=0)
    ax2 = ax.twinx()
    apply_fig33_axes_style(ax, ax2, ref=data)

    for key in ("bcc", "af2q05", "af2q1", "af2q15"):
        pts = data["series"][key]["points"]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        px = [data_to_pixel(x, y, w, h, calib)[0] for x, y in zip(xs, ys)]
        py = [data_to_pixel(x, y, w, h, calib)[1] for x, y in zip(xs, ys)]
        ax.plot(px, py, "k-", lw=0.8, alpha=0.7)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    print("Validation overlay:", out_png)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    image_path = Path(args.image)
    if args.calibrate:
        if not image_path.is_file():
            print(f"Missing image: {image_path}")
            return 1
        run_calibrate(image_path)
        return 0

    if not image_path.is_file():
        print(f"Missing reference image: {image_path}")
        print("Save the thesis Fig.3.3 PNG there, then re-run.")
        return 1

    calib = load_calib()
    data = digitize_all(image_path, calib)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Wrote:", out)

    if args.validate:
        validate_overlay(image_path, data, _ROOT / "output" / "reports" / "hu_bai_fig33_digitize_validation.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
