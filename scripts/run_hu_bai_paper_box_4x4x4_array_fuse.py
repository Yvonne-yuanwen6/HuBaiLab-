"""
4×4×4 array from paper box-cut unit-cell STEP.

  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 0
  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 0.5 --auto-only
  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 1.0 --stepwise-only

Default: try OCC auto-fuse to one solid; on failure emit stepwise compound + SW instructions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.paper_box_array_fuse import (
    export_paper_box_array_auto_fuse,
    export_paper_box_zslab_compound,
    export_paper_box_zstack_compound,
    paper_box_seed_step,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(
    description="4×4×4 array fuse from paper box-cut unit-cell STEP"
)
_parser.add_argument("--Q", type=float, required=True)
_parser.add_argument("--cells", type=int, default=4)
_parser.add_argument("--L", type=float, default=20.0)
_parser.add_argument("--seed", default="", help="Override paper box-cut seed STEP")
_parser.add_argument("--out-dir", default="")
_parser.add_argument(
    "--auto-only",
    action="store_true",
    help="Only attempt OCC auto-fuse to one solid",
)
_parser.add_argument(
    "--stepwise-only",
    action="store_true",
    help="Skip auto-fuse; emit iz0 16-body compound + SW instructions",
)
_parser.add_argument(
    "--sw-fused-layer",
    default="",
    help="After SW iz0 merge: path to fused 4×4 layer STEP for z-stack compound",
)
_args = _parser.parse_args()

if _args.auto_only and _args.stepwise_only:
    raise SystemExit("[FAIL] Use only one of --auto-only / --stepwise-only")

q = float(_args.Q)
n = int(_args.cells)
L = float(_args.L)
gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=2.0,
    amplitude=2.0,
    period_factor=q,
    n_segments=24,
)
gen.build_unitcell()
variant = gen.variant_name.lower()
q_tag = str(q).replace(".", "p")

out_dir = _args.out_dir.strip() or os.path.join(
    str(CAD_ROOT), f"_paper_box_array_q{q_tag}"
)
os.makedirs(out_dir, exist_ok=True)

seed_step = _args.seed.strip() or paper_box_seed_step(q)
seed_step = os.path.abspath(seed_step)
if not os.path.isfile(seed_step):
    raise SystemExit(f"[FAIL] Seed not found: {seed_step}")

slug = f"hu_bai_{variant}_L{int(L)}_{n}x{n}x{n}"
array_step = os.path.join(out_dir, f"{slug}_paper_box_array.step")
iz0_compound = os.path.join(
    out_dir, f"zslab_iz0_{n}x{n}_compound_from_paper_box.step"
)
zstack_compound = os.path.join(
    out_dir, f"zstack_{n}x{n}x{n}_paper_box_4layer_compound.step"
)
manifest_path = os.path.join(out_dir, f"{slug}_paper_box_array_manifest.json")

manifest: dict = {
    "Q": q,
    "variant": gen.variant_name,
    "seed_step": seed_step,
    "out_dir": os.path.abspath(out_dir),
    "cells": [n, n, n],
    "auto_fuse": None,
    "stepwise": None,
}

auto_error: str | None = None
if not _args.stepwise_only:
    print(
        f"=== Auto OCC fuse: {gen.variant_name} {n}x{n}x{n} ===",
        flush=True,
    )
    print(f"  Seed: {seed_step}", flush=True)
    print(f"  Out:  {array_step}", flush=True)
    try:
        auto_report = export_paper_box_array_auto_fuse(
            seed_step,
            array_step,
            nx=n,
            ny=n,
            nz=n,
            cell_size=L,
        )
        bbox = auto_report.get("bbox_mm") or {}
        z_span = float(bbox.get("z", [0, 0])[1]) - float(bbox.get("z", [0, 0])[0])
        expected_z = n * L
        manifest["auto_fuse"] = auto_report
        print(
            f"  OK: vol={auto_report.get('fused_volume_count')} "
            f"sw_safe={auto_report.get('step_solidworks_safe')} "
            f"z_span={z_span:.1f}mm",
            flush=True,
        )
        if z_span < expected_z * 0.9:
            raise RuntimeError(
                f"Z extent {z_span:.1f} mm < expected ~{expected_z:.1f} mm"
            )
        if _args.auto_only:
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            print(f"\nManifest: {manifest_path}", flush=True)
            raise SystemExit(0)
        print("\nAuto-fuse succeeded; stepwise fallback skipped.", flush=True)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"Manifest: {manifest_path}", flush=True)
        raise SystemExit(0)
    except Exception as exc:
        auto_error = str(exc)
        manifest["auto_fuse"] = {"error": auto_error}
        print(f"  [FAIL] Auto-fuse: {exc}", flush=True)
        if _args.auto_only:
            raise SystemExit(1)

if _args.auto_only:
    raise SystemExit(1)

print(
    f"\n=== Stepwise compound: iz0 {n}x{n} (16 bodies) ===",
    flush=True,
)
print(f"  Seed: {seed_step}", flush=True)
print(f"  Out:  {iz0_compound}", flush=True)
stepwise_report = export_paper_box_zslab_compound(
    seed_step,
    iz0_compound,
    nx=n,
    ny=n,
    iz=0,
    nz_total=n,
    cell_size=L,
)
manifest["stepwise"] = {
    "iz0_compound": stepwise_report,
    "iz0_compound_path": os.path.abspath(iz0_compound),
}
print(
    f"  OK: solids={stepwise_report.get('solid_count')} "
    f"sw_safe={stepwise_report.get('step_solidworks_safe')}",
    flush=True,
)

verified_dir = os.path.join(str(CAD_ROOT), "verified")
suggested_iz0 = os.path.join(
    verified_dir, f"zslab_iz0_{n}x{n}_paper_box_sw_fused_{variant}.STEP"
)
print("\n=== SolidWorks Stage A (manual) ===", flush=True)
print(f"  1. Open: {iz0_compound}", flush=True)
print(f"  2. Combine -> Add ({n * n} bodies -> 1 solid)", flush=True)
print(f"  3. Save As: {suggested_iz0}", flush=True)

sw_layer = _args.sw_fused_layer.strip()
if sw_layer:
    sw_layer = os.path.abspath(sw_layer)
    if not os.path.isfile(sw_layer):
        raise SystemExit(f"[FAIL] SW fused layer not found: {sw_layer}")
    print(
        f"\n=== Z-stack compound from SW fused layer ===",
        flush=True,
    )
    print(f"  Seed: {sw_layer}", flush=True)
    print(f"  Out:  {zstack_compound}", flush=True)
    zstack_report = export_paper_box_zstack_compound(
        sw_layer,
        zstack_compound,
        layers=n,
        cell_size=L,
    )
    manifest["stepwise"]["zstack_compound"] = zstack_report
    manifest["stepwise"]["zstack_compound_path"] = os.path.abspath(zstack_compound)
    suggested_merged = os.path.join(
        verified_dir, f"{slug}_paper_box_merged.STEP"
    )
    print(
        f"  OK: solids={zstack_report.get('solid_count')} "
        f"sw_safe={zstack_report.get('step_solidworks_safe')}",
        flush=True,
    )
    print("\n=== SolidWorks Stage B (manual) ===", flush=True)
    print(f"  1. Open: {zstack_compound}", flush=True)
    print(f"  2. Combine -> Add ({n} bodies -> 1 solid)", flush=True)
    print(f"  3. Save As: {suggested_merged}", flush=True)
else:
    print("\nAfter Stage A, run:", flush=True)
    print(
        "  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py "
        f"--Q {q:g} --stepwise-only "
        f'--sw-fused-layer "{suggested_iz0}"',
        flush=True,
    )

if auto_error:
    print(f"\nNote: auto-fuse failed earlier ({auto_error})", flush=True)

with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(f"\nManifest: {manifest_path}", flush=True)
