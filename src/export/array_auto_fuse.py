"""
BCC-safe unit-cell OCC array fuse (does not replace export_sw inter-cell for SFBLS).

Fixes applied vs export_sw._fuse_occ_layer_volumes:
  - pairwise fuse results keep 3D volumes only;
  - stall fallback uses live post-pairwise tags (not stale pre-fuse tags);
  - sequential / stall paths use restrict_cleanup=True (never wipe unfused cells).

SFBLS Q>0 should continue using the SW stepwise pipeline; profiles below gate auto-fuse.
"""

from __future__ import annotations

import os
from typing import Any

# Q registry: extend when a variant is validated for OCC auto-fuse.
AUTO_FUSE_Q_PROFILES: dict[float, dict[str, Any]] = {
    0.0: {
        "label": "BCC (Q=0)",
        "auto_fuse_enabled": False,
        "recommended_route": "run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q 0",
        "notes": "ON HOLD: use SW stepwise. See docs/cad_fuse_routes.md.",
        "known_issues": [
            "legacy export_sw inter-cell: stale dimtag after pairwise stall (tag 12 crash)",
            "array_auto_fuse safe path: iz0 OK but 4x4x4 often stalls/exits silently on iz1+",
            "no checkpoint/resume; full re-run ~30-60 min",
        ],
    },
    0.5: {
        "label": "SFBLS Q=0.5",
        "auto_fuse_enabled": False,
        "notes": "Use run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 (SW stepwise).",
    },
    1.0: {
        "label": "SFBLS Q=1.0",
        "auto_fuse_enabled": False,
        "notes": "Use SW stepwise + verified merged STEP.",
    },
    1.5: {
        "label": "SFBLS Q=1.5",
        "auto_fuse_enabled": False,
        "notes": "Use SW stepwise; OCC inter-cell fuse fails.",
    },
}


def auto_fuse_profile_for_q(q: float) -> dict[str, Any]:
    key = round(float(q), 2)
    if key not in AUTO_FUSE_Q_PROFILES:
        raise ValueError(
            f"No auto-fuse profile for Q={q}. Known Q: {sorted(AUTO_FUSE_Q_PROFILES)}"
        )
    return AUTO_FUSE_Q_PROFILES[key]


def assert_auto_fuse_enabled(q: float) -> dict[str, Any]:
    profile = auto_fuse_profile_for_q(q)
    if not profile.get("auto_fuse_enabled"):
        raise RuntimeError(
            f"OCC auto-fuse is disabled for {profile['label']}. {profile.get('notes', '')}"
        )
    return profile


def _occ_volumes_3d(entities: list) -> list[tuple[int, int]]:
    return [(3, int(t)) for dim, t in entities if int(dim) == 3]


def _refresh_live_volumes(dimtags: list[tuple[int, int]]) -> list[tuple[int, int]]:
    from src.export.export_sw import _occ_list_volume_dimtags

    live = set(_occ_list_volume_dimtags())
    return [d for d in dimtags if d in live]


def _fuse_occ_layer_volumes_safe(
    dimtags: list[tuple[int, int]],
    *,
    progress_label: str = "inter-layer",
) -> list[tuple[int, int]]:
    """Pairwise tree fuse with safe stall fallback (BCC array blocks)."""
    import gmsh

    from src.export.export_sw import _occ_fuse_sequential, _occ_primary_volume

    current = _refresh_live_volumes(list(dimtags))
    if len(current) <= 1:
        return current

    level = 0
    max_levels = max(32, len(current) * 2)
    while len(current) > 1:
        if len(current) == 2:
            fused, _ = gmsh.model.occ.fuse([current[0]], [current[1]])
            gmsh.model.occ.synchronize()
            outs = _refresh_live_volumes(_occ_volumes_3d(fused))
            if outs:
                return outs if len(outs) == 1 else [_occ_primary_volume(outs)]
            print(
                f"  {progress_label}: final pair fuse empty; sequential fallback...",
                flush=True,
            )
            return _occ_fuse_sequential(
                _refresh_live_volumes(current),
                progress_label=progress_label,
                restrict_cleanup=True,
            )

        nxt: list[tuple[int, int]] = []
        for i in range(0, len(current), 2):
            if i + 1 < len(current):
                fused, _ = gmsh.model.occ.fuse([current[i]], [current[i + 1]])
                gmsh.model.occ.synchronize()
                nxt.extend(_occ_volumes_3d(fused))
            else:
                nxt.append(current[i])
        nxt = _refresh_live_volumes(nxt)
        level += 1
        print(
            f"  {progress_label}: level {level}, {len(current)} → {len(nxt)} volume(s)",
            flush=True,
        )
        if len(nxt) >= len(current) or level >= max_levels:
            print(
                f"  {progress_label}: stall at {len(nxt)} volume(s), sequential fuse...",
                flush=True,
            )
            stall_inputs = nxt if nxt else _refresh_live_volumes(current)
            return _occ_fuse_sequential(
                stall_inputs,
                progress_label=progress_label,
                restrict_cleanup=True,
            )
        current = nxt
    return current


def _fuse_unitcell_array_inter_cell_safe(
    cell_volumes: list[tuple[int, int]],
    *,
    nx: int,
    ny: int,
    nz: int,
    progress_label: str = "inter-cell",
) -> None:
    from src.mesh.occ_pipe import prune_occ_for_step_export
    from src.export.export_sw import _occ_fuse_dimtags, _occ_primary_volume

    n = len(cell_volumes)
    if n <= 1:
        return

    nx_i, ny_i, nz_i = int(nx), int(ny), int(nz)
    if nx_i * ny_i * nz_i != n:
        print(f"  {progress_label}: batch fuse {n} volume(s)...", flush=True)
        _occ_fuse_dimtags(cell_volumes)
        return

    if n <= 4:
        _fuse_occ_layer_volumes_safe(cell_volumes, progress_label=progress_label)
        return

    block_nx = min(2, nx_i)
    block_ny = min(2, ny_i)

    slab_cells: list[list[tuple[int, int]]] = [[] for _ in range(nz_i)]
    idx = 0
    for iz in range(nz_i):
        for _iy in range(ny_i):
            for _ix in range(nx_i):
                slab_cells[iz].append(cell_volumes[idx])
                idx += 1

    slab_vols: list[tuple[int, int]] = []
    for iz, cells in enumerate(slab_cells):
        if len(cells) == 1:
            slab_vols.append(cells[0])
            continue

        print(
            f"  {progress_label}: z-slab {iz} fuse {len(cells)} cell(s) "
            f"({block_nx}x{block_ny} blocks)...",
            flush=True,
        )
        block_vols: list[tuple[int, int]] = []
        for by in range(0, ny_i, block_ny):
            for bx in range(0, nx_i, block_nx):
                block: list[tuple[int, int]] = []
                for iy in range(by, min(by + block_ny, ny_i)):
                    for ix in range(bx, min(bx + block_nx, nx_i)):
                        block.append(cells[iy * nx_i + ix])
                if len(block) == 1:
                    block_vols.append(block[0])
                    continue
                blk_label = f"{progress_label}-z{iz}-b{bx // block_nx}_{by // block_ny}"
                fused_blk = _fuse_occ_layer_volumes_safe(block, progress_label=blk_label)
                prune_occ_for_step_export()
                block_vols.append(_occ_primary_volume(fused_blk))

        if len(block_vols) == 1:
            slab_vols.append(block_vols[0])
        else:
            slab_label = f"{progress_label}-z{iz}-slab"
            fused_slab = _fuse_occ_layer_volumes_safe(block_vols, progress_label=slab_label)
            prune_occ_for_step_export()
            slab_vols.append(_occ_primary_volume(fused_slab))

    if len(slab_vols) <= 1:
        return

    print(
        f"  {progress_label}: inter-slab fuse {len(slab_vols)} slab(s)...",
        flush=True,
    )
    _fuse_occ_layer_volumes_safe(slab_vols, progress_label=f"{progress_label}-slab")


def export_lattice_step_occ_unitcell_array_auto(
    nodes: list,
    beams: list,
    path: str,
    *,
    nx: int,
    ny: int,
    nz: int,
    cell_size: float,
    polylines: list[dict] | None = None,
    junction_spheres: bool = True,
    polyline_sweep: str | None = None,
) -> dict[str, int | float | bool | str | list]:
    """Unit-cell array STEP with BCC-safe inter-cell OCC fuse."""
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "STEP export requires gmsh. Install: pip install gmsh"
        ) from exc

    from src.export.export_sw import (
        _collect_solid_primitives,
        _finalize_occ_step_write,
        _lattice_cell_center_mm,
        _occ_dimtags_from_parts,
        _occ_fuse_unitcell_solid_for_array,
        _occ_imported_volume_bbox,
    )
    from src.mesh.occ_pipe import prune_occ_for_step_export

    nx_i, ny_i, nz_i = int(nx), int(ny), int(nz)
    if min(nx_i, ny_i, nz_i) < 1:
        raise ValueError(f"nx/ny/nz must be >= 1, got {nx_i}x{ny_i}x{nz_i}")
    cell_l = float(cell_size)
    if cell_l <= 0.0:
        raise ValueError(f"cell_size must be positive, got {cell_l}")

    use_junction = junction_spheres
    if polyline_sweep is None:
        polyline_sweep = "pipe" if polylines else "cylinder"
    use_pipe = str(polyline_sweep).lower() == "pipe"

    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=use_junction,
        trim_for_junctions=False,
        polyline_sweep=polyline_sweep,
    )
    if not parts:
        raise ValueError("No solid primitives for unit cell.")

    cell_offsets: list[tuple[float, float, float]] = []
    for iz in range(nz_i):
        for iy in range(ny_i):
            for ix in range(nx_i):
                cell_offsets.append(
                    (
                        _lattice_cell_center_mm(ix, nx_i, cell_l),
                        _lattice_cell_center_mm(iy, ny_i, cell_l),
                        _lattice_cell_center_mm(iz, nz_i, cell_l),
                    )
                )

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n_cells = len(cell_offsets)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "lattice_uc_array_auto")

        n_uc_parts = len(parts)
        sweep_label = "pipe sweep" if use_pipe else "cylinder chain"
        print(
            f"  Unit cell fuse: {n_uc_parts} OCC solids "
            f"({sweep_label}, junction spheres={'on' if use_junction else 'off'})...",
            flush=True,
        )
        if n_uc_parts > 1:
            _occ_fuse_unitcell_solid_for_array(
                parts,
                progress_label="unitcell",
                cell_size=cell_l,
            )
        else:
            _occ_dimtags_from_parts(parts)
            gmsh.model.occ.synchronize()
        prune_occ_for_step_export()

        seed_vols = [(3, int(t)) for dim, t in gmsh.model.getEntities(3) if dim == 3]
        if len(seed_vols) != 1:
            raise RuntimeError(
                f"Unit cell fuse produced {len(seed_vols)} volume(s), expected 1."
            )
        seed_vol = seed_vols[0]
        print("  Unit cell fuse complete.", flush=True)

        cell_volumes: list[tuple[int, int]] = []
        for dx, dy, dz in cell_offsets:
            if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
                cell_volumes.append(seed_vol)
                continue
            copied = list(gmsh.model.occ.copy([seed_vol]))
            gmsh.model.occ.translate(copied, float(dx), float(dy), float(dz))
            gmsh.model.occ.synchronize()
            cell_volumes.extend(copied)

        print(
            f"  Array: {n_cells} cell solid(s) "
            f"({nx_i}x{ny_i}x{nz_i}, L={cell_l:.3g} mm)...",
            flush=True,
        )
        if n_cells > 1:
            print(f"  Inter-cell fuse (safe): {len(cell_volumes)} volume(s)...", flush=True)
            _fuse_unitcell_array_inter_cell_safe(
                cell_volumes,
                nx=nx_i,
                ny=ny_i,
                nz=nz_i,
                progress_label="inter-cell",
            )
            prune_occ_for_step_export()

        n_vol = len(gmsh.model.getEntities(3))
        if not n_vol:
            raise RuntimeError("Array fuse produced no volume; STEP would be empty.")
        if n_vol != 1:
            print(
                f"  [WARN] Array fuse produced {n_vol} separate solids (expected 1).",
                flush=True,
            )
        print("  Array fuse complete.", flush=True)

        step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
        fused_volume_count = int(step_report.get("solid_count", 0))
        xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
    finally:
        gmsh.finalize()

    pipe_count = sum(1 for k, *_ in parts if k == "pipe")
    return {
        "step_path": path,
        "solid_count": n_uc_parts,
        "unitcell_primitive_count": n_uc_parts,
        "cell_count": n_cells,
        "pipe_count": pipe_count,
        "polyline_sweep": polyline_sweep,
        "fused": True,
        "fused_volume_count": fused_volume_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
        "bbox_mm": {
            "x": [xmin, xmax],
            "y": [ymin, ymax],
            "z": [zmin, zmax],
        },
        "method": "gmsh_occ_unitcell_array_auto",
    }
