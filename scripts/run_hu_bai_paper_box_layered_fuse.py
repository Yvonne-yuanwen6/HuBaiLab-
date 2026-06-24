"""
Paper box-cut 4×4×4 array: fuse one 4×4 z-slab, copy along +Z, then merge.

Periodic lattice → all z-layers are identical up to a Z translation; only iz=0
needs OCC fuse (~1.5–2 h for Q=1.0). iz=1..3 are fast STEP copies.

  py -3 scripts/run_hu_bai_paper_box_layered_fuse.py --Q 1.0 --iz 0
  py -3 scripts/run_hu_bai_paper_box_layered_fuse.py --Q 1.0 --all
  py -3 scripts/run_hu_bai_paper_box_layered_fuse.py --Q 1.0 --merge-only
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
    export_paper_box_array_from_zslabs,
    export_paper_box_zslab_copies,
    export_paper_box_zslab_fuse,
    paper_box_seed_step,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(
    description="Paper box 4×4×4 array: fuse z-slabs separately, then merge"
)
_parser.add_argument("--Q", type=float, required=True)
_parser.add_argument("--cells", type=int, default=4)
_parser.add_argument("--L", type=float, default=20.0)
_parser.add_argument("--seed", default="", help="Override paper box-cut seed STEP")
_parser.add_argument("--out-dir", default="")
_parser.add_argument("--iz", type=int, default=None, help="Fuse one z-slab layer only")
_parser.add_argument(
    "--all",
    action="store_true",
    help="Fuse all z-slabs (skip existing), then merge to array STEP",
)
_parser.add_argument(
    "--merge-only",
    action="store_true",
    help="Only merge existing zslab_iz*.step files into array STEP",
)
_parser.add_argument(
    "--copy-layers",
    action="store_true",
    help="After iz=0 fuse, copy fused z-slab to iz=1..N-1 (fast; periodic lattice)",
)
_parser.add_argument(
    "--force",
    action="store_true",
    help="Re-fuse or re-copy z-slabs even if STEP already exists",
)
_args = _parser.parse_args()

if _args.copy_layers and _args.iz is not None:
    raise SystemExit("[FAIL] --copy-layers cannot be used with --iz")

if sum(bool(x) for x in (_args.iz is not None, _args.all, _args.merge_only)) != 1:
    raise SystemExit("[FAIL] Specify exactly one of --iz N / --all / --merge-only")

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
manifest_path = os.path.join(out_dir, f"{slug}_paper_box_layered_manifest.json")

zslab_paths = [
    os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_paper_box_fused.step")
    for iz in range(n)
]

manifest: dict = {
    "Q": q,
    "variant": gen.variant_name,
    "seed_step": seed_step,
    "out_dir": os.path.abspath(out_dir),
    "cells": [n, n, n],
    "method": "paper_box_layered_fuse",
    "zslabs": [],
    "array_merge": None,
}


def _zslab_report(path: str, report: dict) -> None:
    bbox = report.get("bbox_mm") or {}
    x_span = float(bbox.get("x", [0, 0])[1]) - float(bbox.get("x", [0, 0])[0])
    y_span = float(bbox.get("y", [0, 0])[1]) - float(bbox.get("y", [0, 0])[0])
    expected = n * L
    print(
        f"  OK iz={report.get('iz')}: vol={report.get('fused_volume_count')} "
        f"sw_safe={report.get('step_solidworks_safe')} "
        f"x={x_span:.1f} y={y_span:.1f} mm",
        flush=True,
    )
    if x_span < expected * 0.85 or y_span < expected * 0.85:
        raise RuntimeError(
            f"Z-slab bbox too small: x={x_span:.1f} y={y_span:.1f} "
            f"(expected ~{expected:.0f} mm)"
        )


def fuse_iz(iz: int) -> dict:
    path = zslab_paths[iz]
    if os.path.isfile(path) and not _args.force:
        print(f"  [skip] iz={iz} exists -> {path}", flush=True)
        return {"step_path": path, "iz": iz, "skipped": True}
    print(f"\n=== Fuse z-slab iz={iz} ===", flush=True)
    print(f"  Seed: {seed_step}", flush=True)
    print(f"  Out:  {path}", flush=True)
    report = export_paper_box_zslab_fuse(
        seed_step,
        path,
        nx=n,
        ny=n,
        iz=iz,
        nz_total=n,
        cell_size=L,
    )
    _zslab_report(path, report)
    return report


if _args.iz is not None:
    iz = int(_args.iz)
    if not (0 <= iz < n):
        raise SystemExit(f"--iz must be in [0, {n - 1}]")
    manifest["zslabs"].append(fuse_iz(iz))
elif _args.all:
    if _args.copy_layers:
        manifest["zslabs"].append(fuse_iz(0))
        ref = zslab_paths[0]
        copy_paths = zslab_paths[1:]
        if copy_paths:
            missing = [p for p in copy_paths if not os.path.isfile(p) or _args.force]
            if missing or _args.force:
                print(
                    f"\n=== Copy fused iz=0 -> iz=1..{n - 1} (dz={L} mm pitch) ===",
                    flush=True,
                )
                print(f"  Ref: {ref}", flush=True)
                to_copy = [
                    (iz, p)
                    for iz, p in enumerate(zslab_paths[1:], start=1)
                    if _args.force or not os.path.isfile(p)
                ]
                for iz, path in to_copy:
                    reports = export_paper_box_zslab_copies(
                        ref,
                        [path],
                        cell_size=L,
                        start_iz=iz,
                    )
                    manifest["zslabs"].append(reports[0])
            else:
                for iz in range(1, n):
                    print(f"  [skip] iz={iz} exists -> {zslab_paths[iz]}", flush=True)
    else:
        for iz in range(n):
            manifest["zslabs"].append(fuse_iz(iz))

if _args.all or _args.merge_only:
    missing = [p for p in zslab_paths if not os.path.isfile(p)]
    if missing:
        raise SystemExit(
            "[FAIL] Missing z-slab STEP(s):\n  "
            + "\n  ".join(missing)
            + "\nRun with --all or fuse each --iz first."
        )
    print(f"\n=== Merge {n} z-slabs -> array ===", flush=True)
    for iz, p in enumerate(zslab_paths):
        print(f"  input iz={iz}: {p}", flush=True)
    print(f"  Out: {array_step}", flush=True)
    merge_report = export_paper_box_array_from_zslabs(
        zslab_paths,
        array_step,
        progress_label="paper-box-inter-slab",
    )
    manifest["array_merge"] = merge_report
    print(
        f"  OK: vol={merge_report.get('fused_volume_count')} "
        f"sw_safe={merge_report.get('step_solidworks_safe')}",
        flush=True,
    )
    if int(merge_report.get("fused_volume_count") or 0) != 1:
        raise SystemExit("[FAIL] Array merge did not produce 1 solid.")

with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(f"\nManifest: {manifest_path}", flush=True)
