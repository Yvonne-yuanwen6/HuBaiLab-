"""
Build one 4×4 z-slab layer from a fused unit-cell seed (stepwise QA).

Compound: isolated per-cell STEPs → merge (SolidWorks-safe, no 128-pipe path).
Fused: fuse each Y row (4 cells) → inter-row fuse into one solid.

Recommended order:
  1. py -3 scripts/export_pair_fuse_check.py --Q 1.0
  2. py -3 scripts/export_line_from_unitcell_seed.py --Q 1.0 --axis y --count 4
  3. py -3 scripts/export_zslab_layer_from_column.py --Q 1.0

  py -3 scripts/export_zslab_layer_from_column.py --Q 1.0 --compound
  py -3 scripts/export_zslab_layer_from_column.py --Q 1.0 --fuse-layer
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import (
    _lattice_cell_offset_xyz_mm,
    _occ_fuse_sequential,
    _occ_imported_volume_bbox,
    _occ_list_volume_dimtags,
    _rewrite_and_analyze_fused_step,
    export_unitcell_array_from_seed,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="4×4 z-slab from unit-cell seed")
_parser.add_argument("--Q", type=float, default=1.0)
_parser.add_argument("--seed", default="")
_parser.add_argument("--layer-nx", type=int, default=4)
_parser.add_argument("--layer-ny", type=int, default=4)
_parser.add_argument(
    "--compound",
    action=argparse.BooleanOptionalAction,
    default=True,
)
_parser.add_argument(
    "--fuse-layer",
    action=argparse.BooleanOptionalAction,
    default=False,
)
_parser.add_argument("--iz", type=int, default=0)
_parser.add_argument(
    "--origin-centered",
    action="store_true",
    help="Origin-centred block coords (default: anchor cell 0 at seed)",
)
_parser.add_argument("--nz-total", type=int, default=1)
_parser.add_argument("--out-dir", default="")
_args = _parser.parse_args()

L = 20.0
nx = int(_args.layer_nx)
ny = int(_args.layer_ny)
iz = int(_args.iz)
nz_total = max(1, int(_args.nz_total))
if nx != ny:
    raise SystemExit("[FAIL] layer-nx must equal layer-ny.")

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=2.0,
    amplitude=2.0,
    period_factor=float(_args.Q),
    n_segments=24,
)
gen.build_unitcell()

q_tag = str(_args.Q).replace(".", "p")
out_dir = _args.out_dir.strip() or os.path.join(str(CAD_ROOT), f"_stepwise_q{q_tag}")
os.makedirs(out_dir, exist_ok=True)

seed_step = _args.seed.strip() or os.path.join(
    str(CAD_ROOT),
    "_unitcell_check",
    f"unitcell_{gen.variant_name.lower()}_fused.step",
)
seed_step = os.path.abspath(seed_step)
if not os.path.isfile(seed_step):
    raise SystemExit(f"[FAIL] Seed not found: {seed_step}")

offsets: list[tuple[float, float, float]] = []
for iy in range(ny):
    for ix in range(nx):
        offsets.append(
            _lattice_cell_offset_xyz_mm(
                ix,
                iy,
                iz,
                nx=nx,
                ny=ny,
                nz=nz_total,
                cell_size=L,
                origin_centered=bool(_args.origin_centered),
            )
        )

do_fuse = bool(_args.fuse_layer) and not _args.compound
suffix = "compound" if _args.compound else "fused"
step_path = os.path.join(out_dir, f"zslab_iz{iz}_{nx}x{ny}_{suffix}_from_seed.step")
manifest_path = os.path.join(out_dir, f"zslab_iz{iz}_{nx}x{ny}_{suffix}_manifest.json")

print(
    f"Z-slab {'compound' if _args.compound else 'fused'}: "
    f"{gen.variant_name} {nx}x{ny} iz={iz}",
    flush=True,
)
print(f"  Seed: {seed_step}", flush=True)
print(f"  Out:  {step_path}", flush=True)

layer_fuse_status = "skipped"

if _args.compound:
    report = export_unitcell_array_from_seed(
        seed_step,
        step_path,
        offsets,
        fuse=False,
        compound_max_flatten=64,
    )
else:
    import gmsh

    from src.export.export_sw import (
        _configure_occ_for_fuse,
        _finalize_occ_step_write,
        export_unitcell_array_from_seed,
    )
    from src.mesh.occ_pipe import prune_occ_for_step_export

    work_dir = os.path.join(out_dir, f".__zslab_fuse_rows_iz{iz}")
    os.makedirs(work_dir, exist_ok=True)
    row_paths: list[str] = []

    print(f"  Phase 1: fuse {ny} row(s) of {nx} cell(s)...", flush=True)
    for iy in range(ny):
        row_offsets = [
            _lattice_cell_offset_xyz_mm(
                ix,
                iy,
                iz,
                nx=nx,
                ny=ny,
                nz=nz_total,
                cell_size=L,
                origin_centered=bool(_args.origin_centered),
            )
            for ix in range(nx)
        ]
        row_path = os.path.join(work_dir, f"row_iy{iy}_fused.step")
        export_unitcell_array_from_seed(
            seed_step,
            row_path,
            row_offsets,
            fuse=True,
            fuse_strategy="sequential",
        )
        row_paths.append(row_path)
        print(f"    row iy={iy} OK -> {row_path}", flush=True)

    print(f"  Phase 2: inter-row fuse ({len(row_paths)} row solid(s))...", flush=True)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("zslab_fused")
        for row_path in row_paths:
            gmsh.model.occ.importShapes(row_path)
        gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()
        row_vols = _occ_list_volume_dimtags()
        if len(row_vols) != ny:
            raise RuntimeError(f"Expected {ny} row volume(s), got {len(row_vols)}")
        if len(row_vols) > 1:
            _occ_fuse_sequential(
                row_vols,
                progress_label="zslab-inter-row",
                restrict_cleanup=True,
            )
        prune_occ_for_step_export()
        if len(_occ_list_volume_dimtags()) != 1:
            raise RuntimeError("Inter-row fuse did not yield 1 volume.")
        layer_fuse_status = "gmsh_ok"
        report = _finalize_occ_step_write(step_path, fuse=True, validate_step=False)
        xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
    except Exception as exc:
        layer_fuse_status = f"gmsh_failed:{exc}"
        raise
    finally:
        gmsh.finalize()
    report = _rewrite_and_analyze_fused_step(step_path, prior=report)
    report["method"] = "unitcell_seed_row_fused_layer"
    report["bbox_mm"] = {
        "x": [xmin, xmax],
        "y": [ymin, ymax],
        "z": [zmin, zmax],
    }

bbox = report.get("bbox_mm") or {}
span = {
    "x": float(bbox["x"][1]) - float(bbox["x"][0]) if bbox else 0.0,
    "y": float(bbox["y"][1]) - float(bbox["y"][0]) if bbox else 0.0,
    "z": float(bbox["z"][1]) - float(bbox["z"][0]) if bbox else 0.0,
}

manifest = {
    "structure": gen.variant_name,
    "seed_step": seed_step,
    "step_path": os.path.abspath(step_path),
    "iz": iz,
    "block": [nx, ny],
    "compound_mode": bool(_args.compound),
    "layer_fuse_status": layer_fuse_status,
    "method": report.get("method"),
    "solid_count": report.get("solid_count"),
    "product_count": report.get("product_count"),
    "step_solidworks_safe": report.get("solidworks_safe"),
    "span_mm": span,
}
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(
    f"  OK: span=({span['x']:.1f}, {span['y']:.1f}, {span['z']:.1f}) mm "
    f"solids={report.get('solid_count')} products={report.get('product_count')} "
    f"sw_safe={report.get('solidworks_safe')}",
    flush=True,
)
print(f"  Manifest: {manifest_path}", flush=True)
