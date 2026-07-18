"""
4×4×4 array from paper box-cut unit-cell STEP.

Default: layered fuse — iz=0 (4×4) OCC fuse → copy iz=1..3 → merge to 1 solid.

  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 1.0
  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 0.5 --force
  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 0 --auto-only
  py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 1.0 --stepwise-only
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
    export_paper_box_layered_array_fuse,
    export_paper_box_zslab_compound,
    export_paper_box_zstack_compound,
    paper_box_seed_step,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(
    description="4×4×4 paper_box array fuse from unit-cell STEP (default: layered)"
)
_parser.add_argument("--Q", type=float, required=True)
_parser.add_argument("--cells", type=int, default=4)
_parser.add_argument("--L", type=float, default=20.0)
_parser.add_argument("--seed", default="", help="Override paper box-cut seed STEP")
_parser.add_argument("--out-dir", default="")
_parser.add_argument(
    "--force",
    action="store_true",
    help="Re-fuse / re-copy z-slabs even if STEP already exists",
)
_parser.add_argument(
    "--auto-only",
    action="store_true",
    help="Legacy: one-shot 64-cell OCC auto-fuse (requires 1-volume seed)",
)
_parser.add_argument(
    "--stepwise-only",
    action="store_true",
    help="Legacy: iz0 compound + SolidWorks manual merge instructions",
)
_parser.add_argument(
    "--sw-fused-layer",
    default="",
    help="After SW iz0 merge: path to fused 4×4 layer STEP for z-stack compound",
)
_parser.add_argument(
    "--strategy",
    default="row_sequential",
    choices=("row_sequential", "in_memory_block"),
    help="gmsh iz=0 z-slab fuse strategy (ignored when --backend ocp)",
)
_parser.add_argument(
    "--backend",
    default="ocp",
    choices=("ocp", "gmsh"),
    help="Fuse backend: ocp (GlueShift, Q1 OCP seed) or gmsh (legacy)",
)
_parser.add_argument(
    "--ocp-fuse-mode",
    default="hierarchical_batch",
    choices=("hierarchical_batch", "sequential"),
    help="OCP inter-cell fuse mode (sequential is more robust for Q>=1 ellipse)",
)
_parser.add_argument(
    "--ocp-row-fuzzy-mm",
    type=float,
    default=0.05,
    help="OCP fuzzy tolerance for within-row cell fuse (mm)",
)
_parser.add_argument(
    "--ocp-inter-row-fuzzy-mm",
    type=float,
    default=0.02,
    help="OCP fuzzy tolerance for inter-row / inter-slab fuse (mm)",
)
_args = _parser.parse_args()

modes = sum(bool(x) for x in (_args.auto_only, _args.stepwise_only))
if modes > 1:
    raise SystemExit("[FAIL] Use at most one of --auto-only / --stepwise-only")

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
    str(CAD_ROOT),
    f"_paper_box_array_q{q_tag}{'_ocp' if _args.backend == 'ocp' else ''}",
)
os.makedirs(out_dir, exist_ok=True)

if _args.backend == "ocp":
    from src.export.ocp_paper_box_array_fuse import resolve_paper_box_seed

    seed_step = resolve_paper_box_seed(q, _args.seed)
else:
    seed_step = _args.seed.strip() or paper_box_seed_step(q)
    seed_step = os.path.abspath(seed_step)
if not os.path.isfile(seed_step):
    raise SystemExit(f"[FAIL] Seed not found: {seed_step}")

slug = f"hu_bai_{variant}_L{int(L)}_{n}x{n}x{n}"
array_step = os.path.join(out_dir, f"{slug}_paper_box_array.step")
manifest_path = os.path.join(out_dir, f"{slug}_paper_box_array_manifest.json")

manifest: dict = {
    "Q": q,
    "variant": gen.variant_name,
    "seed_step": seed_step,
    "out_dir": os.path.abspath(out_dir),
    "cells": [n, n, n],
    "backend": _args.backend,
    "default_method": (
        "ocp_paper_box_layered_fuse"
        if _args.backend == "ocp"
        else "paper_box_layered_fuse"
    ),
}

if _args.auto_only:
    print(f"=== Auto OCC fuse: {gen.variant_name} {n}x{n}x{n} ===", flush=True)
    print(f"  Seed: {seed_step}", flush=True)
    print(f"  Out:  {array_step}", flush=True)
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
        raise SystemExit(
            f"[FAIL] Z extent {z_span:.1f} mm < expected ~{expected_z:.1f} mm"
        )
elif _args.stepwise_only:
    iz0_compound = os.path.join(
        out_dir, f"zslab_iz0_{n}x{n}_compound_from_paper_box.step"
    )
    zstack_compound = os.path.join(
        out_dir, f"zstack_{n}x{n}x{n}_paper_box_4layer_compound.step"
    )
    print(f"\n=== Stepwise compound: iz0 {n}x{n} ===", flush=True)
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
        print(f"\n=== Z-stack compound from SW fused layer ===", flush=True)
        zstack_report = export_paper_box_zstack_compound(
            sw_layer,
            zstack_compound,
            layers=n,
            cell_size=L,
        )
        manifest["stepwise"]["zstack_compound"] = zstack_report
        print(
            f"  OK: solids={zstack_report.get('solid_count')} "
            f"sw_safe={zstack_report.get('step_solidworks_safe')}",
            flush=True,
        )
else:
    print(
        f"=== Layered fuse ({_args.backend}): {gen.variant_name} {n}x{n}x{n} ===",
        flush=True,
    )
    print(f"  Seed: {seed_step}", flush=True)
    print(f"  Out:  {array_step}", flush=True)
    if _args.backend == "ocp":
        from src.export.ocp_paper_box_array_fuse import (
            export_ocp_paper_box_layered_array_fuse,
        )

        layered = export_ocp_paper_box_layered_array_fuse(
            seed_step,
            array_step,
            nx=n,
            ny=n,
            nz=n,
            cell_size=L,
            force=_args.force,
            inter_cell_fuse_mode=_args.ocp_fuse_mode,
            row_fuzzy_mm=float(_args.ocp_row_fuzzy_mm),
            inter_row_fuzzy_mm=float(_args.ocp_inter_row_fuzzy_mm),
        )
    else:
        layered = export_paper_box_layered_array_fuse(
            seed_step,
            array_step,
            nx=n,
            ny=n,
            nz=n,
            cell_size=L,
            force=_args.force,
            fuse_strategy=_args.strategy,
        )
    manifest["layered_fuse"] = layered
    merge = layered.get("array_merge") or {}
    print(
        f"\n  OK: vol={merge.get('fused_volume_count')} "
        f"sw_safe={merge.get('step_solidworks_safe')}",
        flush=True,
    )

with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(f"\nManifest: {manifest_path}", flush=True)
