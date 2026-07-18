"""Diagnose Q1.0 automatic fuse paths (unit cell + neighbor + write)."""

from __future__ import annotations

import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import (
    _collect_solid_primitives,
    _configure_occ_for_fuse,
    _lattice_cell_center_mm,
    _occ_fuse_sequential,
    _occ_fuse_unitcell_fuse_all,
    _occ_fuse_unitcell_pipe_first,
    _occ_list_volume_dimtags,
    _occ_neighbor_fuse_extends_x,
    _occ_primary_volume,
)
from src.export.sw_parasolid import count_step_products, count_step_solids
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.mesh.occ_pipe import prune_occ_for_step_export
from src.paths import CAD_ROOT

OUT = os.path.join(str(CAD_ROOT), "_stepwise_q1p0")
os.makedirs(OUT, exist_ok=True)
L = 20.0


def _write_step(path: str) -> str:
    import gmsh

    try:
        prune_occ_for_step_export()
        gmsh.write(path)
        return f"ok P={count_step_products(path)} S={count_step_solids(path)}"
    except Exception as exc:
        return f"write_fail:{type(exc).__name__}:{exc}"


def _neighbor_test(seed: str, axis: str) -> str:
    import gmsh

    gmsh.model.add("neighbor")
    gmsh.model.occ.importShapes(seed)
    gmsh.model.occ.synchronize()
    _configure_occ_for_fuse()
    vol = _occ_list_volume_dimtags()[0]
    bx0, _, _, bx1, _, _ = gmsh.model.occ.getBoundingBox(*vol)
    by0, _, _, by1, _, _ = gmsh.model.occ.getBoundingBox(*vol)
    span = float(bx1 - bx0) if axis == "x" else float(by1 - by0)
    dx = dy = 0.0
    if axis == "x":
        dx = L
    else:
        dy = L
    side = list(gmsh.model.occ.copy([vol]))
    gmsh.model.occ.translate(side, dx, dy, 0.0)
    gmsh.model.occ.synchronize()
    try:
        fused, _ = gmsh.model.occ.fuse([vol], side)
        gmsh.model.occ.synchronize()
        outs = [(3, int(t)) for dim, t in fused if dim == 3]
        if not outs:
            return f"{axis}: empty"
        keep = _occ_primary_volume(outs)
        bb = gmsh.model.occ.getBoundingBox(*keep)
        nspan = float(bb[3] - bb[0]) if axis == "x" else float(bb[4] - bb[1])
        tag = f"_diag_{axis}2_{os.path.basename(seed)}"
        msg = _write_step(os.path.join(OUT, tag))
        return f"{axis}: vols={len(outs)} span={nspan:.1f} (1={span:.1f}) {msg}"
    except Exception as exc:
        return f"{axis}: fuse_fail:{exc}"


def _line_fuse(seed: str, axis: str, n: int = 4) -> str:
    import gmsh

    gmsh.model.add("line")
    gmsh.model.occ.importShapes(seed)
    gmsh.model.occ.synchronize()
    _configure_occ_for_fuse()
    sv = _occ_list_volume_dimtags()[0]
    vols = []
    for i in range(n):
        off = _lattice_cell_center_mm(i, 4, L) - _lattice_cell_center_mm(0, 4, L)
        c = list(gmsh.model.occ.copy([sv]))
        if axis == "x" and abs(off) > 1e-9:
            gmsh.model.occ.translate(c, float(off), 0.0, 0.0)
        elif axis == "y" and abs(off) > 1e-9:
            gmsh.model.occ.translate(c, 0.0, float(off), 0.0)
        gmsh.model.occ.synchronize()
        vols.append(c[0])
    gmsh.model.occ.remove([sv], recursive=True)
    gmsh.model.occ.synchronize()
    try:
        fused = _occ_fuse_sequential(vols, progress_label=f"line-{axis}", restrict_cleanup=True)
        tag = f"_diag_line_{axis}{n}_{os.path.basename(seed)}"
        msg = _write_step(os.path.join(OUT, tag))
        return f"line-{axis}{n}: vols={len(fused)} {msg}"
    except Exception as exc:
        return f"line-{axis}{n}: fail:{exc}"


def build_unitcell(strategy: str, *, sweep: str = "pipe") -> str | None:
    import gmsh

    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=2.0,
        amplitude=2.0,
        period_factor=1.0,
        n_segments=24,
    )
    gen.build_unitcell()
    nodes, beams, polys = gen.get_data(copy=True)
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("uc")
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polys,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep=sweep,
    )
    print(f"\n=== {strategy} sweep={sweep} parts={len(parts)} ===", flush=True)
    try:
        if strategy == "pipe_first":
            vols = _occ_fuse_unitcell_pipe_first(parts, progress_label="pf")
        else:
            vols = _occ_fuse_unitcell_fuse_all(parts, progress_label="fa")
        seed = os.path.join(OUT, f"_diag_uc_{strategy}_{sweep}.step")
        msg = _write_step(seed)
        print(f"  unitcell: vols={len(vols)} {msg}", flush=True)
        okx = _occ_neighbor_fuse_extends_x(vols[0], L)
        print(f"  neighbor_x_extends: {okx}", flush=True)
        gmsh.finalize()
        return seed
    except Exception:
        traceback.print_exc()
        gmsh.finalize()
        return None


def main() -> int:
    for strategy in ("pipe_first", "fuse_all"):
        for sweep in ("pipe", "cylinder"):
            seed = build_unitcell(strategy, sweep=sweep)
            if not seed:
                continue
            import gmsh

            for axis in ("x", "y"):
                gmsh.initialize()
                gmsh.option.setNumber("General.Terminal", 0)
                print(f"  {_neighbor_test(seed, axis)}", flush=True)
                gmsh.finalize()
            for axis in ("y", "x"):
                gmsh.initialize()
                gmsh.option.setNumber("General.Terminal", 0)
                print(f"  {_line_fuse(seed, axis)}", flush=True)
                gmsh.finalize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
