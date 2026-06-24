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
    export_unitcell_array_from_seed,
)
from src.export.array_auto_fuse import _fuse_unitcell_array_inter_cell_safe
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
        if len(seed_vols) != 1:
            raise RuntimeError(
                f"Paper box seed must be 1 volume, got {len(seed_vols)}: {seed_step}"
            )
        seed_vol = seed_vols[0]

        cell_volumes: list[tuple[int, int]] = []
        for dx, dy, dz in offsets:
            if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
                cell_volumes.append(seed_vol)
                continue
            copied = list(gmsh.model.occ.copy([seed_vol]))
            gmsh.model.occ.translate(copied, float(dx), float(dy), float(dz))
            gmsh.model.occ.synchronize()
            cell_volumes.extend(copied)

        print(
            f"  Paper box array: {n_cells} cell(s) "
            f"({nx_i}x{ny_i}x{nz_i}, L={cell_l:g} mm)...",
            flush=True,
        )
        if n_cells > 1:
            print(
                f"  Inter-cell fuse (safe): {len(cell_volumes)} volume(s)...",
                flush=True,
            )
            _fuse_unitcell_array_inter_cell_safe(
                cell_volumes,
                nx=nx_i,
                ny=ny_i,
                nz=nz_i,
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
    n_cells = len(offsets)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(
            os.path.splitext(os.path.basename(path))[0] or "paper_box_zslab"
        )
        gmsh.model.occ.importShapes(seed_step)
        gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()

        seed_vols = _occ_list_volume_dimtags()
        if len(seed_vols) != 1:
            raise RuntimeError(
                f"Paper box seed must be 1 volume, got {len(seed_vols)}: {seed_step}"
            )
        seed_vol = seed_vols[0]

        cell_volumes: list[tuple[int, int]] = []
        for dx, dy, dz in offsets:
            if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
                cell_volumes.append(seed_vol)
                continue
            copied = list(gmsh.model.occ.copy([seed_vol]))
            gmsh.model.occ.translate(copied, float(dx), float(dy), float(dz))
            gmsh.model.occ.synchronize()
            cell_volumes.extend(copied)

        print(
            f"  Paper box z-slab iz={iz_i}: {n_cells} cell(s) "
            f"({nx_i}x{ny_i}, L={cell_l:g} mm)...",
            flush=True,
        )
        if n_cells > 1:
            _fuse_unitcell_array_inter_cell_safe(
                cell_volumes,
                nx=nx_i,
                ny=ny_i,
                nz=1,
                progress_label=f"paper-box-zslab-iz{iz_i}",
            )
            prune_occ_for_step_export()

        n_vol = len(gmsh.model.getEntities(3))
        if n_vol != 1:
            raise RuntimeError(
                f"Paper box z-slab iz={iz_i} produced {n_vol} volume(s), expected 1."
            )

        step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
        xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
    finally:
        gmsh.finalize()

    step_report = _rewrite_and_analyze_fused_step(path, prior=step_report)
    return {
        "step_path": path,
        "seed_step": seed_step,
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
        "method": "paper_box_zslab_fuse",
    }


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
