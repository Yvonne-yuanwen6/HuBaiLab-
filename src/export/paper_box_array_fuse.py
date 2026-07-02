"""4×4×4 array fuse from paper box-cut unit-cell STEP seeds."""

from __future__ import annotations

import os
from typing import Any

from src.export.export_sw import (
    _configure_occ_for_fuse,
    _finalize_occ_step_write,
    _lattice_cell_offset_xyz_mm,
    _merge_step_solids_in_memory,
    _occ_imported_volume_bbox,
    _occ_list_volume_dimtags,
    _rewrite_and_analyze_fused_step,
    _write_translated_unitcell_step_copy,
    export_unitcell_array_from_seed,
)
from src.export.array_auto_fuse import _fuse_occ_layer_volumes_safe, _fuse_unitcell_array_inter_cell_safe
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.mesh.occ_pipe import prune_occ_for_step_export
from src.paths import CAD_ROOT


def paper_box_seed_step(
    q: float,
    *,
    seed_dir: str | None = None,
) -> str:
    """Path to verified paper box-cut unit-cell STEP for period factor ``q``."""
    gen = HuBaiLatticeGenerator(
        cell_size=20.0,
        rod_diameter=2.0,
        amplitude=2.0,
        period_factor=float(q),
        n_segments=24,
    )
    gen.build_unitcell()
    base = seed_dir or os.path.join(str(CAD_ROOT), "_unitcell_paper_box_cut")
    path = os.path.join(base, f"unitcell_{gen.variant_name.lower()}_paper_box.step")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Paper box-cut seed missing: {path}\n"
            "Run: py -3 scripts/export_unitcell_paper_box_cut.py --Q "
            f"{q:g}"
        )
    return os.path.abspath(path)


def _occ_place_paper_box_seed_volumes(
    seed_vols: list[tuple[int, int]],
    offsets: list[tuple[float, float, float]],
) -> list[tuple[int, int]]:
    """Place every seed volume at each grid offset (supports 1- or N-body seeds)."""
    import gmsh

    if not seed_vols:
        raise RuntimeError("Paper box seed has no volumes")
    cell_volumes: list[tuple[int, int]] = []
    for dx, dy, dz in offsets:
        if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
            cell_volumes.extend(seed_vols)
            continue
        copied = list(gmsh.model.occ.copy(seed_vols))
        gmsh.model.occ.translate(copied, float(dx), float(dy), float(dz))
        gmsh.model.occ.synchronize()
        cell_volumes.extend(copied)
    return cell_volumes


def _count_seed_volumes(seed_step: str) -> int:
    import gmsh

    seed_step = os.path.abspath(seed_step)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("seed_probe")
        gmsh.model.occ.importShapes(seed_step)
        gmsh.model.occ.synchronize()
        return len(_occ_list_volume_dimtags())
    finally:
        gmsh.finalize()


def _export_fused_paper_box_cell_at_offset(
    seed_step: str,
    path: str,
    offset: tuple[float, float, float],
    *,
    progress_label: str,
) -> None:
    """Fuse one multi-body unit cell in isolation, already translated to ``offset``."""
    import gmsh

    seed_step = os.path.abspath(seed_step)
    path = os.path.abspath(path)
    dx, dy, dz = offset
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "pb_cell")
        gmsh.model.occ.importShapes(seed_step)
        gmsh.model.occ.synchronize()
        vols = _occ_list_volume_dimtags()
        if abs(dx) > 1e-9 or abs(dy) > 1e-9 or abs(dz) > 1e-9:
            gmsh.model.occ.translate(vols, float(dx), float(dy), float(dz))
            gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()
        vols = _occ_list_volume_dimtags()
        if len(vols) > 1:
            _fuse_occ_layer_volumes_safe(vols, progress_label=progress_label)
            prune_occ_for_step_export()
        if len(gmsh.model.getEntities(3)) != 1:
            raise RuntimeError(
                f"{progress_label}: expected 1 volume after intra-cell fuse, "
                f"got {len(gmsh.model.getEntities(3))}"
            )
        _finalize_occ_step_write(path, fuse=True, validate_step=False)
    finally:
        gmsh.finalize()


def fuse_paper_box_unitcell_seed_to_one(
    seed_step: str,
    path: str,
    *,
    progress_label: str = "paper-box-unitcell",
) -> str:
    """Fuse multi-body paper_box unit-cell seed → single-volume STEP (Q1.5 z-slab path)."""
    seed_step = os.path.abspath(seed_step)
    path = os.path.abspath(path)
    n_in = _count_seed_volumes(seed_step)
    if n_in <= 1:
        return seed_step
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    print(
        f"  {progress_label}: fuse {n_in} strut(s) -> 1 unit-cell volume...",
        flush=True,
    )
    _export_fused_paper_box_cell_at_offset(
        seed_step,
        path,
        (0.0, 0.0, 0.0),
        progress_label=progress_label,
    )
    return path


def _paper_box_zslab_work_dir(out_path: str) -> str:
    """Checkpoint dir for per-cell / per-row z-slab fuse (resumable)."""
    return os.path.join(os.path.dirname(os.path.abspath(out_path)) or ".", ".work_zslab_cells")


def _export_paper_box_zslab_cell_steps(
    seed_for_slab: str,
    work_dir: str,
    offsets: list[tuple[float, float, float]],
    *,
    progress_label: str,
    resume: bool = True,
) -> list[str]:
    """Translate 1-volume seed to each grid offset; write one STEP per cell."""
    os.makedirs(work_dir, exist_ok=True)
    n_cells = len(offsets)
    cell_steps: list[str] = []
    for idx, (dx, dy, dz) in enumerate(offsets):
        cell_path = os.path.join(work_dir, f"cell_{idx:03d}.step")
        if resume and os.path.isfile(cell_path):
            print(
                f"  {progress_label}: cell {idx + 1}/{n_cells} [skip]",
                flush=True,
            )
        else:
            print(
                f"  {progress_label}: cell {idx + 1}/{n_cells} "
                f"offset=({dx:g},{dy:g},{dz:g})",
                flush=True,
            )
            _write_translated_unitcell_step_copy(
                seed_for_slab,
                cell_path,
                dx,
                dy,
                dz,
            )
        cell_steps.append(cell_path)
    return cell_steps


def _fuse_paper_box_zslab_row_sequential(
    seed_for_slab: str,
    path: str,
    *,
    nx: int,
    ny: int,
    iz: int,
    nz_total: int,
    cell_size: float,
    progress_label: str,
    resume: bool = True,
    work_dir: str | None = None,
) -> tuple[dict[str, Any], tuple[float, float, float, float, float, float]]:
    """
    Resumable iz z-slab: per-cell STEPs → fuse each x-row (nx cells) → fuse rows.

    Avoids loading 16 cells + block-tree inter-cell fuse in one session (Q1 BFF fail).
    """
    path = os.path.abspath(path)
    nx_i, ny_i = int(nx), int(ny)
    iz_i = int(iz)
    cell_l = float(cell_size)
    work_dir = work_dir or _paper_box_zslab_work_dir(path)
    rows_dir = os.path.join(work_dir, "rows")
    os.makedirs(rows_dir, exist_ok=True)

    offsets: list[tuple[float, float, float]] = []
    for iy in range(ny_i):
        for ix in range(nx_i):
            offsets.append(
                _lattice_cell_offset_xyz_mm(
                    ix,
                    iy,
                    iz_i,
                    nx=nx_i,
                    ny=ny_i,
                    nz=int(nz_total),
                    cell_size=cell_l,
                    origin_centered=False,
                )
            )

    print(
        f"  {progress_label}: phase 1 — export {len(offsets)} cell STEP(s)...",
        flush=True,
    )
    cell_steps = _export_paper_box_zslab_cell_steps(
        seed_for_slab,
        work_dir,
        offsets,
        progress_label=f"{progress_label}-cell",
        resume=resume,
    )

    row_steps: list[str] = []
    for iy in range(ny_i):
        row_path = os.path.join(rows_dir, f"row_iy{iy}_fused.step")
        row_cells = cell_steps[iy * nx_i : (iy + 1) * nx_i]
        if resume and os.path.isfile(row_path):
            print(
                f"  {progress_label}: row iy={iy} [skip] -> {row_path}",
                flush=True,
            )
        else:
            print(
                f"  {progress_label}: row iy={iy} fuse {len(row_cells)} cell(s)...",
                flush=True,
            )
            _fuse_paper_box_zslab_from_cell_steps(
                row_cells,
                row_path,
                nx=nx_i,
                ny=1,
                iz=iz_i,
                progress_label=f"{progress_label}-row{iy}",
            )
        row_steps.append(row_path)

    if resume and os.path.isfile(path):
        print(f"  {progress_label}: final z-slab [skip] -> {path}", flush=True)
        import gmsh

        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("zslab_probe")
            gmsh.model.occ.importShapes(path)
            gmsh.model.occ.synchronize()
            step_report = {"solid_count": len(gmsh.model.getEntities(3))}
            bbox = _occ_imported_volume_bbox()
        finally:
            gmsh.finalize()
        return step_report, bbox

    print(
        f"  {progress_label}: phase 3 — inter-row fuse {len(row_steps)} row(s)...",
        flush=True,
    )
    return _fuse_paper_box_zslab_from_cell_steps(
        row_steps,
        path,
        nx=1,
        ny=ny_i,
        iz=iz_i,
        progress_label=f"{progress_label}-inter-row",
    )


def _fuse_paper_box_zslab_from_cell_steps(
    cell_steps: list[str],
    path: str,
    *,
    nx: int,
    ny: int,
    iz: int,
    progress_label: str,
) -> tuple[dict[str, Any], tuple[float, float, float, float, float, float]]:
    """Inter-cell fuse pre-merged cell STEPs (each already at grid offset) → one z-slab."""
    import gmsh

    from src.export.export_sw import _occ_fuse_sequential, _occ_remove_all_volumes_except

    path = os.path.abspath(path)
    n_cells = len(cell_steps)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(
            os.path.splitext(os.path.basename(path))[0] or "paper_box_zslab"
        )
        for cs in cell_steps:
            gmsh.model.occ.importShapes(os.path.abspath(cs))
        gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()
        vols = _occ_list_volume_dimtags()
        if len(vols) > 1:
            # Pre-merged unit cells: sequential fuse avoids orphan volumes from
            # block pairwise (Q1.5-style full 4×4 slab).
            print(
                f"  {progress_label}: sequential inter-cell fuse "
                f"{len(vols)} cell(s)...",
                flush=True,
            )
            united = _occ_fuse_sequential(
                vols,
                progress_label=progress_label,
                restrict_cleanup=True,
            )
            prune_occ_for_step_export()
            if len(united) != 1:
                raise RuntimeError(
                    f"{progress_label}: inter-cell fuse produced "
                    f"{len(united)} volume(s), expected 1."
                )
            _occ_remove_all_volumes_except(united[0])
        if len(gmsh.model.getEntities(3)) != 1:
            raise RuntimeError(
                f"{progress_label}: z-slab produced "
                f"{len(gmsh.model.getEntities(3))} volume(s), expected 1."
            )
        step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
        bbox = _occ_imported_volume_bbox()
    finally:
        gmsh.finalize()
    return step_report, bbox


def lattice_block_offsets_mm(
    nx: int,
    ny: int,
    nz: int,
    cell_size: float,
    *,
    origin_centered: bool = False,
) -> list[tuple[float, float, float]]:
    """Cell translate offsets (anchor cell 0 at seed when ``origin_centered=False``)."""
    offsets: list[tuple[float, float, float]] = []
    for iz in range(int(nz)):
        for iy in range(int(ny)):
            for ix in range(int(nx)):
                offsets.append(
                    _lattice_cell_offset_xyz_mm(
                        ix,
                        iy,
                        iz,
                        nx=int(nx),
                        ny=int(ny),
                        nz=int(nz),
                        cell_size=float(cell_size),
                        origin_centered=origin_centered,
                    )
                )
    return offsets


def export_paper_box_array_auto_fuse(
    seed_step: str,
    path: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
) -> dict[str, Any]:
    """
    Copy paper box-cut seed to an nx×ny×nz grid and safe OCC inter-cell fuse → 1 solid.
    """
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "Paper box array fuse requires gmsh. Install: pip install gmsh"
        ) from exc

    seed_step = os.path.abspath(seed_step)
    path = os.path.abspath(path)
    nx_i, ny_i, nz_i = int(nx), int(ny), int(nz)
    cell_l = float(cell_size)
    offsets = lattice_block_offsets_mm(
        nx_i, ny_i, nz_i, cell_l, origin_centered=False
    )
    n_cells = len(offsets)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "paper_box_array")
        gmsh.model.occ.importShapes(seed_step)
        gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()

        seed_vols = _occ_list_volume_dimtags()
        if not seed_vols:
            raise RuntimeError(f"Paper box seed has no volumes: {seed_step}")
        cell_volumes = _occ_place_paper_box_seed_volumes(seed_vols, offsets)

        print(
            f"  Paper box array: {n_cells} cell(s) "
            f"({nx_i}x{ny_i}x{nz_i}, L={cell_l:g} mm, "
            f"seed_vols={len(seed_vols)})...",
            flush=True,
        )
        if len(cell_volumes) > len(seed_vols):
            _fuse_unitcell_array_inter_cell_safe(
                cell_volumes,
                nx=nx_i,
                ny=ny_i,
                nz=nz_i,
                volumes_per_cell=len(seed_vols),
                progress_label="paper-box-inter-cell",
            )
            prune_occ_for_step_export()

        n_vol = len(gmsh.model.getEntities(3))
        if n_vol != 1:
            raise RuntimeError(
                f"Paper box array auto-fuse produced {n_vol} volume(s), expected 1."
            )

        step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
        xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
    finally:
        gmsh.finalize()

    step_report = _rewrite_and_analyze_fused_step(path, prior=step_report)
    return {
        "step_path": path,
        "seed_step": seed_step,
        "cell_count": n_cells,
        "fused_volume_count": int(step_report.get("solid_count", 0)),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "bbox_mm": {
            "x": [xmin, xmax],
            "y": [ymin, ymax],
            "z": [zmin, zmax],
        },
        "method": "paper_box_seed_auto_fuse",
    }


def export_paper_box_zslab_fuse(
    seed_step: str,
    path: str,
    *,
    nx: int = 4,
    ny: int = 4,
    iz: int = 0,
    nz_total: int = 4,
    cell_size: float = 20.0,
    fuse_strategy: str = "row_sequential",
    resume: bool = True,
) -> dict[str, Any]:
    """Fuse one nx×ny z-slab from paper box-cut seed → single solid STEP."""
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "Paper box z-slab fuse requires gmsh. Install: pip install gmsh"
        ) from exc

    seed_step = os.path.abspath(seed_step)
    path = os.path.abspath(path)
    nx_i, ny_i = int(nx), int(ny)
    iz_i = int(iz)
    cell_l = float(cell_size)
    n_cells = nx_i * ny_i
    strategy = str(fuse_strategy).strip().lower() or "row_sequential"

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    seed_vol_count = _count_seed_volumes(seed_step)
    progress_label = f"paper-box-zslab-iz{iz_i}"

    if seed_vol_count > 1:
        merged_seed = os.path.join(
            _paper_box_zslab_work_dir(path),
            "unitcell_merged_1vol.step",
        )
        seed_for_slab = fuse_paper_box_unitcell_seed_to_one(
            seed_step,
            merged_seed,
            progress_label=f"{progress_label}-unitcell",
        )
        seed_vol_count = 1
    else:
        seed_for_slab = seed_step

    print(
        f"  Paper box z-slab iz={iz_i}: {n_cells} cell(s) "
        f"({nx_i}x{ny_i}, L={cell_l:g} mm, strategy={strategy})...",
        flush=True,
    )

    if strategy in ("row_sequential", "row", "sequential"):
        step_report, bbox = _fuse_paper_box_zslab_row_sequential(
            seed_for_slab,
            path,
            nx=nx_i,
            ny=ny_i,
            iz=iz_i,
            nz_total=int(nz_total),
            cell_size=cell_l,
            progress_label=progress_label,
            resume=resume,
        )
        xmin, ymin, zmin, xmax, ymax, zmax = bbox
        method = "paper_box_zslab_row_sequential"
    elif strategy in ("in_memory_block", "block", "legacy"):
        offsets: list[tuple[float, float, float]] = []
        for iy in range(ny_i):
            for ix in range(nx_i):
                offsets.append(
                    _lattice_cell_offset_xyz_mm(
                        ix,
                        iy,
                        iz_i,
                        nx=nx_i,
                        ny=ny_i,
                        nz=int(nz_total),
                        cell_size=cell_l,
                        origin_centered=False,
                    )
                )
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(
                os.path.splitext(os.path.basename(path))[0] or "paper_box_zslab"
            )
            gmsh.model.occ.importShapes(seed_for_slab)
            gmsh.model.occ.synchronize()
            _configure_occ_for_fuse()

            seed_vols = _occ_list_volume_dimtags()
            if not seed_vols:
                raise RuntimeError(f"Paper box seed has no volumes: {seed_for_slab}")
            cell_volumes = _occ_place_paper_box_seed_volumes(seed_vols, offsets)

            if len(cell_volumes) > 1:
                print(
                    f"  {progress_label}: inter-cell fuse {len(cell_volumes)} cell(s) "
                    f"({nx_i}x{ny_i} block tree)...",
                    flush=True,
                )
                _fuse_unitcell_array_inter_cell_safe(
                    cell_volumes,
                    nx=nx_i,
                    ny=ny_i,
                    nz=1,
                    volumes_per_cell=1,
                    progress_label=progress_label,
                )
                prune_occ_for_step_export()

            n_vol = len(gmsh.model.getEntities(3))
            if n_vol != 1:
                raise RuntimeError(
                    f"Paper box z-slab iz={iz_i} produced {n_vol} volume(s), expected 1."
                )

            step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
            xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
            method = "paper_box_zslab_fuse_merged_seed"
        finally:
            gmsh.finalize()
    else:
        raise ValueError(
            f"Unknown fuse_strategy {fuse_strategy!r}; "
            "use row_sequential or in_memory_block"
        )

    step_report = _rewrite_and_analyze_fused_step(path, prior=step_report)
    return {
        "step_path": path,
        "seed_step": seed_step,
        "merged_seed_step": seed_for_slab,
        "iz": iz_i,
        "cell_count": n_cells,
        "fused_volume_count": int(step_report.get("solid_count", 0)),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "bbox_mm": {
            "x": [xmin, xmax],
            "y": [ymin, ymax],
            "z": [zmin, zmax],
        },
        "method": method,
        "fuse_strategy": strategy,
        "seed_volume_count": seed_vol_count,
    }


def export_paper_box_layered_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    zslab_paths: list[str] | None = None,
    force: bool = False,
    fuse_strategy: str = "row_sequential",
) -> dict[str, Any]:
    """
    Default 4×4×4 paper_box route: fuse iz=0 z-slab, copy layers, merge to 1 solid.

    Periodic lattice → iz=1..N-1 are translated copies of fused iz=0.
    """
    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("layered array fuse expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)

    if zslab_paths is None:
        zslab_paths = [
            os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_paper_box_fused.step")
            for iz in range(n)
        ]

    manifest: dict[str, Any] = {
        "method": "paper_box_layered_fuse",
        "seed_step": os.path.abspath(seed_step),
        "array_step": array_step,
        "cells": [n, n, n],
        "zslabs": [],
        "array_merge": None,
    }

    iz0_path = zslab_paths[0]
    if force or not os.path.isfile(iz0_path):
        print(f"\n=== Layered fuse iz=0 ({n}x{n}) ===", flush=True)
        print(f"  Seed: {seed_step}", flush=True)
        print(f"  Out:  {iz0_path}", flush=True)
        iz0_report = export_paper_box_zslab_fuse(
            seed_step,
            iz0_path,
            nx=n,
            ny=n,
            iz=0,
            nz_total=n,
            cell_size=cell_l,
            fuse_strategy=fuse_strategy,
            resume=not force,
        )
        manifest["zslabs"].append(iz0_report)
    else:
        print(f"  [skip] iz=0 exists -> {iz0_path}", flush=True)
        manifest["zslabs"].append({"step_path": iz0_path, "iz": 0, "skipped": True})

    copy_paths = zslab_paths[1:]
    if copy_paths:
        to_copy = [
            (iz, path)
            for iz, path in enumerate(zslab_paths[1:], start=1)
            if force or not os.path.isfile(path)
        ]
        if to_copy:
            print(
                f"\n=== Copy fused iz=0 -> iz=1..{n - 1} (dz={cell_l} mm) ===",
                flush=True,
            )
            for iz, path in to_copy:
                reports = export_paper_box_zslab_copies(
                    iz0_path,
                    [path],
                    cell_size=cell_l,
                    start_iz=iz,
                )
                manifest["zslabs"].append(reports[0])
        else:
            for iz, path in enumerate(zslab_paths[1:], start=1):
                print(f"  [skip] iz={iz} exists -> {path}", flush=True)

    missing = [p for p in zslab_paths if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(
            "Missing z-slab STEP(s) before merge:\n  " + "\n  ".join(missing)
        )

    print(f"\n=== Merge {n} z-slabs -> array ===", flush=True)
    for iz, path in enumerate(zslab_paths):
        print(f"  input iz={iz}: {path}", flush=True)
    print(f"  Out: {array_step}", flush=True)
    merge_report = export_paper_box_array_from_zslabs(
        zslab_paths,
        array_step,
        progress_label="paper-box-inter-slab",
    )
    manifest["array_merge"] = merge_report
    if int(merge_report.get("fused_volume_count") or 0) != 1:
        raise RuntimeError(
            f"Array merge produced {merge_report.get('fused_volume_count')} volume(s), "
            "expected 1."
        )
    return manifest


def export_paper_box_array_from_zslabs(
    zslab_steps: list[str],
    path: str,
    *,
    progress_label: str = "paper-box-inter-slab",
) -> dict[str, Any]:
    """Merge independently fused paper-box z-slab STEPs → one array solid."""
    zslab_steps = [os.path.abspath(p) for p in zslab_steps]
    path = os.path.abspath(path)
    for p in zslab_steps:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Missing z-slab STEP: {p}")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    print(
        f"  Paper box inter-slab merge: {len(zslab_steps)} slab(s)...",
        flush=True,
    )
    step_report = _merge_step_solids_in_memory(
        zslab_steps,
        path,
        progress_label=progress_label,
    )
    step_report = _rewrite_and_analyze_fused_step(path, prior=step_report)
    return {
        "step_path": path,
        "zslab_inputs": zslab_steps,
        "fused_volume_count": int(step_report.get("solid_count", 0)),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "method": "paper_box_zslab_merge",
    }


def export_paper_box_zslab_copies(
    fused_zslab_step: str,
    out_paths: list[str],
    *,
    cell_size: float = 20.0,
    start_iz: int = 0,
) -> list[dict[str, Any]]:
    """Copy one fused 4×4 z-slab along +Z (periodic lattice: layers differ only by dz)."""
    fused_zslab_step = os.path.abspath(fused_zslab_step)
    if not os.path.isfile(fused_zslab_step):
        raise FileNotFoundError(f"Missing fused z-slab: {fused_zslab_step}")
    if not out_paths:
        return []

    cell_l = float(cell_size)
    reports: list[dict[str, Any]] = []
    for i, path in enumerate(out_paths):
        iz = int(start_iz) + i
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        dz = float(iz) * cell_l
        print(
            f"  Paper box z-slab copy iz={iz}: dz={dz:g} mm -> {path}",
            flush=True,
        )
        report = export_unitcell_array_from_seed(
            fused_zslab_step,
            path,
            [(0.0, 0.0, dz)],
            fuse=False,
            compound_max_flatten=64,
        )
        report["method"] = "paper_box_zslab_copy"
        report["iz"] = iz
        report["source_step"] = fused_zslab_step
        reports.append(report)
    return reports


def export_paper_box_zslab_compound(
    seed_step: str,
    path: str,
    *,
    nx: int = 4,
    ny: int = 4,
    iz: int = 0,
    nz_total: int = 4,
    cell_size: float = 20.0,
) -> dict[str, Any]:
    """16-body iz layer compound (SW manual combine route)."""
    offsets: list[tuple[float, float, float]] = []
    for iy in range(int(ny)):
        for ix in range(int(nx)):
            offsets.append(
                _lattice_cell_offset_xyz_mm(
                    ix,
                    iy,
                    int(iz),
                    nx=int(nx),
                    ny=int(ny),
                    nz=int(nz_total),
                    cell_size=float(cell_size),
                    origin_centered=False,
                )
            )
    report = export_unitcell_array_from_seed(
        seed_step,
        path,
        offsets,
        fuse=False,
        compound_max_flatten=64,
    )
    report["method"] = "paper_box_zslab_compound"
    report["seed_step"] = os.path.abspath(seed_step)
    return report


def export_paper_box_zstack_compound(
    fused_layer_step: str,
    path: str,
    *,
    layers: int = 4,
    cell_size: float = 20.0,
) -> dict[str, Any]:
    """4-layer compound from one fused 4×4 z-slab (SW manual merge route)."""
    offsets = [(0.0, 0.0, float(iz) * float(cell_size)) for iz in range(int(layers))]
    report = export_unitcell_array_from_seed(
        fused_layer_step,
        path,
        offsets,
        fuse=False,
        compound_max_flatten=64,
    )
    report["method"] = "paper_box_zstack_compound"
    report["seed_step"] = os.path.abspath(fused_layer_step)
    return report
