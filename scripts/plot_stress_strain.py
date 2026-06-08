"""
Plot engineering stress-strain curve (curve only by default).

  .venv\\Scripts\\python.exe scripts\\plot_stress_strain.py
  .venv\\Scripts\\python.exe scripts\\plot_stress_strain.py --csv output\\abaqus\\post\\full\\stress_strain_full.csv --png output\\abaqus\\post\\full\\stress_strain_full.png
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.naming import load_case_manifest
from src.paths import OUTPUT_ROOT
from src.postprocess.yield_strength import analyze_stress_strain_curve, save_yield_properties


def _default_stress_strain_paths() -> tuple[str, str]:
    active = OUTPUT_ROOT / "active_case.json"
    if active.is_file():
        data = load_case_manifest(active)
        return data["stress_strain_csv"], data["stress_strain_png"]
    slug = "str_a45_L10_Oh0p5_rf0p5_rs0p4_rv0p6_q"
    post = OUTPUT_ROOT / "abaqus" / "post" / slug
    return str(post / f"{slug}_stress_strain.csv"), str(post / f"{slug}_stress_strain.png")


def load_csv(path: str) -> tuple[list[float], list[float]]:
    strains: list[float] = []
    stresses: list[float] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            strains.append(float(row["engineering_strain"]))
            stresses.append(float(row["engineering_stress_MPa"]))
    return strains, stresses


def load_yield(path: str | None, strains: list[float], stresses: list[float]) -> dict[str, float]:
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return analyze_stress_strain_curve(strains, stresses)


def plot_curve(
    strains: list[float],
    stresses: list[float],
    *,
    save_path: str | None,
    show: bool,
    annotate_yield: bool = False,
    yield_props: dict[str, float] | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(strains, stresses, "b-", linewidth=1.8)

    if annotate_yield and yield_props:
        E = yield_props.get("elastic_modulus_MPa", 0.0)
        b = yield_props.get("elastic_intercept_MPa", 0.0)
        off = yield_props.get("offset_strain", 0.002)
        ys = yield_props.get("yield_stress_MPa", math.nan)
        ye = yield_props.get("yield_strain", math.nan)
        us = yield_props.get("ultimate_stress_MPa", math.nan)
        ue = yield_props.get("ultimate_strain", math.nan)

        if strains and E > 0:
            e_max = max(strains) * 1.05
            e_line = [0.0, e_max]
            ax.plot(e_line, [E * e + b for e in e_line], "g--", linewidth=1.0, label=f"Elastic E={E:.3f} MPa")
            ax.plot(
                e_line,
                [E * (e - off) + b for e in e_line],
                "m--",
                linewidth=1.0,
                label="0.2% offset",
            )
        if not math.isnan(ys) and not math.isnan(ye):
            ax.plot(ye, ys, "ro", markersize=7, label=f"Yield {ys:.4f} MPa")
        if not math.isnan(us) and not math.isnan(ue):
            ax.plot(ue, us, "k^", markersize=7, label=f"Ultimate {us:.4f} MPa")
        ax.legend(loc="best", fontsize=8)

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("Lattice structure — stress-strain curve")
    ax.grid(True, alpha=0.35)
    fig.tight_layout()

    if save_path:
        save_path = os.path.abspath(save_path)
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        if os.path.isfile(save_path):
            try:
                os.remove(save_path)
            except OSError:
                pass
        fig.savefig(save_path, dpi=150)
        print("Saved:", save_path)
    if show:
        plt.show()
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot stress-strain curve")
    _csv_default, _png_default = _default_stress_strain_paths()
    parser.add_argument("--csv", default=_csv_default)
    parser.add_argument("--png", default=_png_default)
    parser.add_argument(
        "--annotate-yield",
        action="store_true",
        help="Add elastic line, 0.2%% offset, yield/ultimate markers",
    )
    parser.add_argument(
        "--yield-json",
        default="",
        help="Only used with --annotate-yield",
    )
    parser.add_argument("--no-show", action="store_true")
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"[ERROR] Not found: {args.csv}")
        return 1

    args.csv = os.path.abspath(args.csv)
    if args.png:
        args.png = os.path.abspath(args.png)

    strains, stresses = load_csv(args.csv)
    if not strains:
        print("[ERROR] Empty CSV")
        return 1

    props = None
    if args.annotate_yield:
        yield_path = args.yield_json
        if not yield_path and "stress_strain" in args.csv:
            yield_path = os.path.splitext(args.csv)[0].replace(
                "stress_strain", "yield_properties"
            ) + ".json"
        try:
            props = load_yield(yield_path if yield_path and os.path.isfile(yield_path) else None, strains, stresses)
        except Exception as exc:
            print(f"[WARN] Yield: {exc}")

    plot_curve(
        strains,
        stresses,
        save_path=args.png,
        show=not args.no_show,
        annotate_yield=args.annotate_yield,
        yield_props=props,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
