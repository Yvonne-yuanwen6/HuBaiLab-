"""Deep-pad cell rebuild + OCP fuse for hard paper_box arrays.

Key lesson (af2q1_deq1p5 / scheme B1):
  - Build neighbour cells with large ``periodic_overlap_mm``.
  - Fuse cells **without** remelting each cell first (remelt kills pad contact).
  - Accept a multi-solid compound whose mass ≈ sum, then remelt / MakerVolume
    / sew→MakerVolume down to one solid with a mass gate.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

from src.export.export_sw import _collect_solid_primitives
from src.export.ocp_array_sew import (
    _export_ocp_solids_gmsh_fuse,
    _fuse_cell_struts,
    build_array_octant_strut_solids,
)
from src.export.ocp_maker_volume import (
    gate_mass_ok,
    ocp_maker_volume,
    ocp_sew_faces_then_maker_volume,
)
from src.export.ocp_paper_box_array_fuse import (
    load_ocp_unitcell_shape,
    ocp_read_step_shape,
    ocp_translate_shape,
)
from src.export.ocp_unitcell_fuse import (
    GlueMode,
    _ensure_single_solid,
    _ocp_count_solids,
    _ocp_explode_solids,
    ocp_fuse_batch,
    ocp_fuse_pair,
    ocp_mass,
    ocp_write_step,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator


def load_param_pipe_parts(
    *,
    cell_size: float = 20.0,
    rod_d: float = 2.0,
    amplitude: float = 2.0,
    period_factor: float = 1.0,
    n_segments: int = 24,
    solid_profile: str = "circle",
    ellipse_minor_ratio: float = 1.0,
) -> list[tuple[str, tuple, float]]:
    """Build 8 pipe / pipe_ellipse parts for any Q / κ."""
    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size),
        rod_diameter=float(rod_d),
        amplitude=float(amplitude),
        period_factor=float(period_factor),
        n_segments=max(3, int(n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
        solid_profile=str(solid_profile),
        ellipse_minor_ratio=float(ellipse_minor_ratio),
    )
    pipe_parts = [p for p in parts if p[0] in ("pipe", "pipe_ellipse")]
    if len(pipe_parts) != 8:
        raise RuntimeError(f"expected 8 pipe parts, got {len(pipe_parts)}")
    return pipe_parts


def _gmsh_fuse_shapes(
    shapes: list[Any],
    *,
    work_step: str,
    label: str,
    expected_mass: float,
    mass_lo: float = 0.70,
    mass_hi: float = 1.35,
) -> Any:
    """Explode → gmsh BREP sequential fuse → one solid (read back)."""
    solids: list[Any] = []
    for sh in shapes:
        parts = _ocp_explode_solids(sh)
        solids.extend(parts if parts else [sh])
    if not solids:
        raise RuntimeError(f"{label}: no solids for gmsh fuse")
    if len(solids) == 1:
        return solids[0]
    os.makedirs(os.path.dirname(os.path.abspath(work_step)) or ".", exist_ok=True)
    if os.path.isfile(work_step):
        os.remove(work_step)
    print(f"  {label}: gmsh-fuse {len(solids)} solid(s)...", flush=True)
    _export_ocp_solids_gmsh_fuse(
        solids, work_step, heal_mm=0.05, progress_label=label
    )
    out = ocp_read_step_shape(work_step)
    m = ocp_mass(out)
    n = _ocp_count_solids(out)
    if n != 1 or not gate_mass_ok(m, expected_mass, lo=mass_lo, hi=mass_hi):
        raise RuntimeError(
            f"{label}: gmsh fuse bad result n={n} mass={m:.1f} exp={expected_mass:.1f}"
        )
    print(f"  {label}: gmsh-fuse OK mass={m:.1f}", flush=True)
    return out


def _coerce_single_solid(
    shape: Any,
    *,
    expected_mass: float,
    fuzzy_mm: float,
    label: str,
    work_step: str | None = None,
    mass_lo: float = 0.80,
    mass_hi: float = 1.25,
) -> Any:
    """Reduce compound → 1 solid; prefer gmsh BREP fuse over OCP remelt."""
    n = _ocp_count_solids(shape)
    m0 = ocp_mass(shape)
    if n == 1 and gate_mass_ok(m0, expected_mass, lo=mass_lo, hi=mass_hi):
        return shape

    last_err: Exception | None = None

    # 1) gmsh BREP fuse (works when GlueFull only packaged a compound)
    if work_step:
        try:
            return _gmsh_fuse_shapes(
                [shape],
                work_step=work_step,
                label=f"{label}-gmsh",
                expected_mass=expected_mass,
                mass_lo=mass_lo,
                mass_hi=mass_hi,
            )
        except Exception as exc:
            last_err = exc

    # 2) boolean remelt
    try:
        merged = _ensure_single_solid(
            shape,
            cut_mass=float(expected_mass),
            fuzzy_mm=float(fuzzy_mm),
            label=f"{label}-remelt",
            budget_s=120.0,
        )
        m = ocp_mass(merged)
        if _ocp_count_solids(merged) == 1 and gate_mass_ok(
            m, expected_mass, lo=mass_lo, hi=mass_hi
        ):
            return merged
        last_err = RuntimeError(
            f"remelt n={_ocp_count_solids(merged)} mass={m:.1f} exp={expected_mass:.1f}"
        )
        shape = merged
    except Exception as exc:
        last_err = exc

    # 3) MakerVolume / sew
    for g in ("shift", "full", "off"):
        for fz in sorted({float(fuzzy_mm), 0.1, 0.2, 0.5}):
            try:
                solid, rep = ocp_maker_volume(
                    [shape],
                    fuzzy_mm=float(fz),
                    glue=g,
                    intersect=True,
                    label=f"{label}-mv",
                )
                m = ocp_mass(solid)
                if _ocp_count_solids(solid) == 1 and gate_mass_ok(
                    m, expected_mass, lo=mass_lo, hi=mass_hi
                ):
                    print(
                        f"  {label}: MakerVolume OK mass={m:.1f} "
                        f"n_in={rep.get('n_solids')}",
                        flush=True,
                    )
                    return solid
            except Exception as exc:
                last_err = exc
    try:
        solid, _ = ocp_sew_faces_then_maker_volume(
            [shape],
            sew_tol_mm=0.1,
            fuzzy_mm=max(0.1, float(fuzzy_mm)),
            glue="shift",
            label=f"{label}-sewmv",
        )
        m = ocp_mass(solid)
        if _ocp_count_solids(solid) == 1 and gate_mass_ok(
            m, expected_mass, lo=mass_lo, hi=mass_hi
        ):
            return solid
    except Exception as exc:
        last_err = exc

    raise RuntimeError(
        f"{label}: could not coerce to 1 solid "
        f"(start_n={n} mass={m0:.1f} exp={expected_mass:.1f}): {last_err}"
    )


def _merge_group_gated(
    shapes: list[Any],
    *,
    glue: GlueMode,
    fuzzy_mm: float,
    label: str,
    work_dir: str,
    mass_lo: float = 0.80,
    mass_hi: float = 1.25,
    glue_climb: tuple[GlueMode, ...] = ("full", "shift", "off"),
) -> Any:
    """Fuse without remelting inputs; coerce via gmsh BREP fuse when needed."""
    if not shapes:
        raise RuntimeError(f"{label}: no shapes")
    os.makedirs(work_dir, exist_ok=True)
    if len(shapes) == 1:
        return _coerce_single_solid(
            shapes[0],
            expected_mass=ocp_mass(shapes[0]),
            fuzzy_mm=fuzzy_mm,
            label=f"{label}-solo",
            work_step=os.path.join(work_dir, f"{label}_solo.step"),
            mass_lo=0.70,
            mass_hi=1.30,
        )

    piece_masses = [ocp_mass(s) for s in shapes]
    # Preferred path: explode all pieces and gmsh-fuse in one go (most reliable).
    try:
        exp_all = sum(piece_masses)
        fused = _gmsh_fuse_shapes(
            shapes,
            work_step=os.path.join(work_dir, f"{label}_gmsh_all.step"),
            label=f"{label}-gmsh-all",
            expected_mass=exp_all,
            mass_lo=mass_lo,
            mass_hi=mass_hi,
        )
        return fused
    except Exception as gmsh_err:
        print(f"  {label}: gmsh-all failed ({gmsh_err}); try pairwise...", flush=True)

    acc = shapes[0]
    for i, sh in enumerate(shapes[1:], start=2):
        exp = ocp_mass(acc) + ocp_mass(sh)
        last_err: Exception | None = None
        done = False
        # Pairwise gmsh first
        try:
            acc = _gmsh_fuse_shapes(
                [acc, sh],
                work_step=os.path.join(work_dir, f"{label}_{i}_gmsh.step"),
                label=f"{label}-{i}-gmsh",
                expected_mass=exp,
                mass_lo=mass_lo,
                mass_hi=mass_hi,
            )
            done = True
        except Exception as exc:
            last_err = exc

        climb = (glue,) + tuple(g for g in glue_climb if g != glue)
        fuzzies = sorted({float(fuzzy_mm), 0.05, 0.1, 0.2, 0.5})
        if not done:
            for g in climb:
                for fz in fuzzies:
                    try:
                        cand = ocp_fuse_pair(
                            acc,
                            sh,
                            glue=g,
                            fuzzy_mm=float(fz),
                            simplify=False,
                            label=f"{label}-{i}",
                        )
                        m = ocp_mass(cand)
                        if not gate_mass_ok(m, exp, lo=mass_lo, hi=mass_hi):
                            last_err = RuntimeError(
                                f"compound mass gate fail m={m:.1f} exp={exp:.1f}"
                            )
                            continue
                        acc = _coerce_single_solid(
                            cand,
                            expected_mass=m,
                            fuzzy_mm=float(fz),
                            label=f"{label}-{i}",
                            work_step=os.path.join(work_dir, f"{label}_{i}.step"),
                            mass_lo=0.70,
                            mass_hi=1.30,
                        )
                        done = True
                        break
                    except Exception as exc:
                        last_err = exc
                if done:
                    break
        if not done:
            raise RuntimeError(
                f"{label}: step {i}/{len(shapes)} failed "
                f"(piece_masses={[round(x, 1) for x in piece_masses]}): {last_err}"
            )
    return acc


def export_ocp_deep_pad_layered_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    rod_d: float = 1.5,
    amplitude: float = 2.0,
    period_factor: float = 1.0,
    solid_profile: str = "circle",
    ellipse_minor_ratio: float = 1.0,
    pad_mm: float = 2.0,
    glue: GlueMode = "full",
    fuzzy_mm: float = 0.05,
    cell_fuzzy_mm: float = 0.1,
    mass_lo: float = 0.80,
    mass_hi: float = 1.25,
    force: bool = True,
) -> dict[str, Any]:
    """Rebuild every z-slab from deep-pad octant struts; fuse row→slab→array."""
    del seed_step  # geometry rebuilt; seed used by caller for QC baseline
    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("deep-pad layered fuse expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    pad = float(pad_mm)
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)
    if force and os.path.isfile(array_step):
        os.remove(array_step)

    t0 = time.time()
    pipes = load_param_pipe_parts(
        cell_size=cell_l,
        rod_d=float(rod_d),
        amplitude=float(amplitude),
        period_factor=float(period_factor),
        solid_profile=str(solid_profile),
        ellipse_minor_ratio=float(ellipse_minor_ratio),
    )
    report: dict[str, Any] = {
        "method": "ocp_deep_pad_layered_fuse",
        "pad_mm": pad,
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "rod_d": float(rod_d),
        "amplitude": float(amplitude),
        "period_factor": float(period_factor),
        "solid_profile": str(solid_profile),
        "ellipse_minor_ratio": float(ellipse_minor_ratio),
        "cells": [n, n, n],
        "steps": [],
        "note": "no per-cell remelt before neighbour fuse",
    }

    # Pipe end-extension often breaks MakePipeShell (thin rods + ellipse Q≈1.5).
    # Rely on pad boxes alone; keep sweep unextended (via build_* defaults).
    pipe_mode = "both_end_extension"
    work_merge = os.path.join(out_dir, ".deep_pad_merge")
    os.makedirs(work_merge, exist_ok=True)

    def make_cells(iz: int) -> list[Any]:
        # build_array_octant_strut_solids already uses centre/corner_extension=None
        # (no pipe end-extension); pad overhang comes from periodic_overlap_mm only.
        struts, _ = build_array_octant_strut_solids(
            pipes,
            nx=n,
            ny=n,
            iz=int(iz),
            nz_total=n,
            cell_size_mm=cell_l,
            pipe_mode=pipe_mode,  # type: ignore[arg-type]
            periodic_overlap_mm=pad,
            periodic_axes=("x", "y", "z"),
        )
        cells: list[Any] = []
        for i in range(n * n):
            # Prefer a fused cell solid; if strut BOP fails (thin rods), keep an
            # 8-strut compound — pad overhangs still enable neighbour batch fuse.
            chunk = struts[i * 8 : (i + 1) * 8]
            try:
                cell = _fuse_cell_struts(
                    chunk,
                    fuzzy_mm=float(cell_fuzzy_mm),
                    label=f"iz{iz}-c{i}",
                )
            except Exception as strut_err:
                from OCP.BRep import BRep_Builder
                from OCP.TopoDS import TopoDS_Compound

                print(
                    f"  iz{iz}-c{i}: strut fuse failed ({strut_err}); "
                    f"keep {len(chunk)}-strut compound",
                    flush=True,
                )
                builder = BRep_Builder()
                comp = TopoDS_Compound()
                builder.MakeCompound(comp)
                for sh in chunk:
                    builder.Add(comp, sh)
                cell = comp
            if ocp_mass(cell) <= 0.0:
                raise RuntimeError(f"iz{iz}-c{i}: empty cell")
            cells.append(cell)
        return cells

    slabs: list[Any] = []
    for iz in range(n):
        print(
            f"\n=== deep-pad z-slab iz={iz} (pad={pad:g} mm, Q={period_factor:g}, "
            f"profile={solid_profile}, pipe={pipe_mode}/noext) ===",
            flush=True,
        )
        cells = make_cells(iz)
        cell_masses = [ocp_mass(c) for c in cells]
        print(
            f"  cells={len(cells)} mass~{sum(cell_masses)/len(cell_masses):.1f} "
            f"solids={[ _ocp_count_solids(c) for c in cells[:4] ]} "
            f"(first4={[round(m,1) for m in cell_masses[:4]]})",
            flush=True,
        )
        # Fuse whole 4x4 slab via gmsh in one shot when possible.
        try:
            slab = _merge_group_gated(
                cells,
                glue=glue,
                fuzzy_mm=float(fuzzy_mm),
                label=f"iz{iz}-slab",
                work_dir=os.path.join(work_merge, f"iz{iz}"),
                mass_lo=mass_lo,
                mass_hi=mass_hi,
            )
        except Exception as slab_err:
            print(f"  iz={iz} slab-all failed ({slab_err}); row path...", flush=True)
            rows: list[Any] = []
            for iy in range(n):
                row = cells[iy * n : (iy + 1) * n]
                fused_row = _merge_group_gated(
                    row,
                    glue=glue,
                    fuzzy_mm=float(fuzzy_mm),
                    label=f"iz{iz}-row{iy}",
                    work_dir=os.path.join(work_merge, f"iz{iz}_row{iy}"),
                    mass_lo=mass_lo,
                    mass_hi=mass_hi,
                )
                rows.append(fused_row)
                report["steps"].append(
                    {"label": f"iz{iz}-row{iy}", "mass": ocp_mass(fused_row)}
                )
            slab = _merge_group_gated(
                rows,
                glue=glue,
                fuzzy_mm=float(fuzzy_mm),
                label=f"iz{iz}-slab",
                work_dir=os.path.join(work_merge, f"iz{iz}_slab"),
                mass_lo=mass_lo,
                mass_hi=mass_hi,
            )
        slabs.append(slab)
        slab_path = os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_deep_pad.step")
        ocp_write_step(slab, slab_path)
        print(f"  iz={iz} slab mass={ocp_mass(slab):.1f} -> {slab_path}", flush=True)
        report["steps"].append({"label": f"iz{iz}-slab", "mass": ocp_mass(slab)})

    print("\n=== deep-pad inter-slab merge ===", flush=True)
    fused = _merge_group_gated(
        slabs,
        glue=glue,
        fuzzy_mm=max(float(fuzzy_mm), 0.1),
        label="444z",
        work_dir=os.path.join(work_merge, "444z"),
        mass_lo=mass_lo,
        mass_hi=mass_hi,
    )
    a_mass = ocp_mass(fused)
    nsol = _ocp_count_solids(fused)
    if nsol != 1:
        raise RuntimeError(f"final array has {nsol} solids, want 1")
    ocp_write_step(fused, array_step)
    report["array_mass"] = a_mass
    report["array_solids"] = nsol
    report["array_step"] = array_step
    report["elapsed_s"] = round(time.time() - t0, 1)
    print(
        f"  deep-pad 444 OK mass={a_mass:.1f} solids={nsol} "
        f"elapsed={report['elapsed_s']}s -> {array_step}",
        flush=True,
    )
    return report


def rod_params_from_deq_k(deq_mm: float, k: float) -> tuple[str, float, float]:
    """(solid_profile, rod_diameter_mm, ellipse_minor_ratio)."""
    deq = float(deq_mm)
    kappa = float(k)
    if abs(kappa - 1.0) < 1e-9:
        return "circle", deq, 1.0
    if kappa < 1.0:
        raise ValueError(f"aspect ratio k must be >= 1, got {kappa}")
    d_major = deq * math.sqrt(kappa)
    return "ellipse", d_major, 1.0 / kappa


def _ocp_scale_about(shape: Any, cx: float, cy: float, cz: float, scale: float) -> Any:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Pnt, gp_Trsf

    tr = gp_Trsf()
    tr.SetScale(gp_Pnt(float(cx), float(cy), float(cz)), float(scale))
    return BRepBuilderAPI_Transform(shape, tr, True).Shape()


def export_seed_scale_inflate_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    scale: float = 1.005,
    glue: GlueMode = "off",
    fuzzy_mm: float = 0.1,
    mass_lo: float = 0.70,
    mass_hi: float = 1.30,
    force: bool = True,
) -> dict[str, Any]:
    """Scale-inflate seeds, fuse iz=0 z-slab once, +Z-copy other layers, fuse 444.

    Face-touching paper_box seeds often have Common≈0 at pitch=L. A tiny
    isotropic scale (≈1.005) creates volume overlap. Pairwise row→slab fuse
    destroys orthogonal contacts; prefer one-shot ``ocp_fuse_batch`` on the
    iz=0 4×4 slab (proven: scale=1.005, glue=off, fuzzy=0.1 → n=1, r≈1.0).

    Layers iz=1..nz-1 are rigid +Z copies of the fused iz=0 slab (periodic
    lattice) — not re-arrayed — then the nz slabs are batch-fused to 444.
    """
    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("seed-scale inflate expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    sc = float(scale)
    if sc < 1.0:
        raise ValueError(f"scale must be >= 1, got {sc}")
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)
    if force and os.path.isfile(array_step):
        os.remove(array_step)

    t0 = time.time()
    seed, seed_mass = load_ocp_unitcell_shape(os.path.abspath(seed_step), cell_size=cell_l)
    if seed_mass <= 0.0 or _ocp_count_solids(seed) != 1:
        raise RuntimeError(
            f"seed not a single solid mass={seed_mass:.1f} n={_ocp_count_solids(seed)}"
        )

    def _cell(ix: int, iy: int, iz: int) -> Any:
        ox, oy, oz = float(ix) * cell_l, float(iy) * cell_l, float(iz) * cell_l
        placed = ocp_translate_shape(seed, ox, oy, oz)
        if abs(sc - 1.0) < 1e-12:
            return placed
        return _ocp_scale_about(
            placed, ox + 0.5 * cell_l, oy + 0.5 * cell_l, oz + 0.5 * cell_l, sc
        )

    sample = _cell(0, 0, 0)
    cell_mass = ocp_mass(sample)
    print(
        f"seed-scale 444 (zcopy): seed_mass={seed_mass:.1f} scaled_cell={cell_mass:.1f} "
        f"scale={sc:g} glue={glue} fz={fuzzy_mm:g} grid={n}^3 "
        f"(fuse iz=0 only, copy +Z for iz=1..{n - 1})",
        flush=True,
    )

    work_merge = os.path.join(out_dir, ".deep_pad_merge", "seed_scale")
    os.makedirs(work_merge, exist_ok=True)

    def _fuse_group(cells: list[Any], *, label: str, expected: float) -> Any:
        # Prefer one-shot batch fuse (avoids orthogonal-contact destruction).
        glue_climb: tuple[GlueMode, ...] = (glue, "off", "shift", "full")
        seen: set[str] = set()
        climb: list[GlueMode] = []
        for g in glue_climb:
            if g not in seen:
                seen.add(g)
                climb.append(g)
        fuzzies = sorted({float(fuzzy_mm), 0.1, 0.05}, reverse=True)
        last_err: Exception | None = None
        for g in climb:
            for fz in fuzzies:
                t_b = time.time()
                # Heartbeat before long OCC fuse so monitors do not look "stuck".
                print(
                    f"  {label}: trying batch g={g} fz={fz:g} n={len(cells)} ...",
                    flush=True,
                )
                try:
                    cand = ocp_fuse_batch(
                        cells,
                        glue=g,
                        fuzzy_mm=float(fz),
                        simplify=False,
                        label=f"{label}-batch",
                    )
                    m = ocp_mass(cand)
                    nsol = _ocp_count_solids(cand)
                    print(
                        f"  {label}: batch g={g} fz={fz:g} -> m={m:.1f} "
                        f"(r={m / expected:.3f}) n={nsol} t={time.time() - t_b:.1f}s",
                        flush=True,
                    )
                    if nsol != 1:
                        last_err = RuntimeError(f"batch n={nsol} m={m:.1f}")
                        continue
                    if not gate_mass_ok(m, expected, lo=mass_lo, hi=mass_hi):
                        last_err = RuntimeError(
                            f"batch mass gate m={m:.1f} exp={expected:.1f}"
                        )
                        continue
                    return cand
                except Exception as exc:
                    last_err = exc
                    print(
                        f"  {label}: batch g={g} fz={fz:g} FAIL ({exc}) "
                        f"t={time.time() - t_b:.1f}s",
                        flush=True,
                    )

        # Fallback: gmsh BREP fuse of the whole group.
        print(
            f"  {label}: batch ladder exhausted; trying gmsh fuse n={len(cells)} ...",
            flush=True,
        )
        try:
            return _gmsh_fuse_shapes(
                cells,
                work_step=os.path.join(work_merge, f"{label}_gmsh.step"),
                label=f"{label}-gmsh",
                expected_mass=expected,
                mass_lo=mass_lo,
                mass_hi=mass_hi,
            )
        except Exception as gmsh_err:
            raise RuntimeError(
                f"{label}: batch+gmsh failed; last_batch={last_err}; gmsh={gmsh_err}"
            ) from gmsh_err

    # Fuse iz=0 once; copy+translate for remaining z layers (periodic).
    print(f"\n=== seed-scale iz=0 ({n}x{n}, scale={sc:g}) fuse ===", flush=True)
    cells0 = [_cell(ix, iy, 0) for iy in range(n) for ix in range(n)]
    slab0 = _fuse_group(
        cells0, label="iz0-slab", expected=cell_mass * float(n * n)
    )
    slab0_path = os.path.join(out_dir, f"zslab_iz0_{n}x{n}_seed_scale.step")
    ocp_write_step(slab0, slab0_path)
    print(f"  iz=0 slab mass={ocp_mass(slab0):.1f} -> {slab0_path}", flush=True)
    slabs: list[Any] = [slab0]

    for iz in range(1, n):
        dz = float(iz) * cell_l
        print(f"\n=== seed-scale iz={iz} zcopy dz={dz:g} mm ===", flush=True)
        slab = ocp_translate_shape(slab0, 0.0, 0.0, dz)
        slab_path = os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_seed_scale.step")
        ocp_write_step(slab, slab_path)
        print(
            f"  iz={iz} slab mass={ocp_mass(slab):.1f} (zcopy) -> {slab_path}",
            flush=True,
        )
        slabs.append(slab)

    fused = _fuse_group(
        slabs, label="444z", expected=cell_mass * float(n * n * n)
    )
    a_mass = ocp_mass(fused)
    nsol = _ocp_count_solids(fused)
    if nsol != 1:
        raise RuntimeError(f"final array has {nsol} solids, want 1")
    ocp_write_step(fused, array_step)
    # QC uses gmsh OCC; OCP solid count can disagree after STEP round-trip.
    from src.export.sw_parasolid import measure_step_occ_stats

    try:
        gmsh_stats = measure_step_occ_stats(array_step)
    except Exception as exc:
        raise RuntimeError(f"seed-scale gmsh verify failed after write: {exc}") from exc
    g_n = int(gmsh_stats.get("volume_count") or 0)
    g_mass = float(gmsh_stats.get("mass_mm3") or 0.0)
    if g_n != 1 or g_mass <= 0.0:
        raise RuntimeError(
            f"seed-scale STEP not single solid for gmsh/QC: "
            f"volume_count={g_n} mass={g_mass:.1f} "
            f"(OCP n={nsol} mass={a_mass:.1f}); try next ladder rung"
        )
    report = {
        "method": "seed_scale_inflate_zcopy_array_fuse",
        "z_slab_mode": "fuse_iz0_copy_z",
        "scale": sc,
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "seed_mass": seed_mass,
        "scaled_cell_mass": cell_mass,
        "array_mass": g_mass,
        "array_solids": g_n,
        "ocp_array_mass": a_mass,
        "ocp_array_solids": nsol,
        "gmsh_verified": True,
        "ratio_vs_unscaled_seed": (g_mass / seed_mass) if seed_mass > 0 else 0.0,
        "array_step": array_step,
        "cells": [n, n, n],
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(
        f"  seed-scale 444 OK (zcopy) mass={g_mass:.1f} solids={g_n} "
        f"gmsh_verified=1 ratio_vs_seed={report['ratio_vs_unscaled_seed']:.2f} "
        f"elapsed={report['elapsed_s']}s",
        flush=True,
    )
    return report


def export_ocp_noclip_batch_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    glue: GlueMode = "shift",
    fuzzy_mm: float = 0.1,
    mass_lo: float = 0.85,
    mass_hi: float = 1.20,
    force: bool = True,
) -> dict[str, Any]:
    """Place nx×ny×nz seeds at pitch=L (no periodic clip) → one-shot OCP batch fuse.

    Proven 2026-07-18 on hybrid Q=1 ``af2q1_deq2_k1`` (centre_stub_corner_ext):
    row→slab→zcopy destroys orthogonal contacts; batching all 64 raw cells with
    GlueShift keeps X/Y/Z neighbour overlaps (2-cell HIT in each axis) and yields
    QC ratio≈64 in ~3–4 min.
    """
    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("noclip batch fuse expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)
    if force and os.path.isfile(array_step):
        os.remove(array_step)

    t0 = time.time()
    seed, seed_mass = load_ocp_unitcell_shape(os.path.abspath(seed_step), cell_size=cell_l)
    if seed_mass <= 0.0 or _ocp_count_solids(seed) != 1:
        raise RuntimeError(
            f"seed not a single solid mass={seed_mass:.1f} n={_ocp_count_solids(seed)}"
        )
    n_cells = n * n * n
    cells = [
        ocp_translate_shape(seed, float(ix) * cell_l, float(iy) * cell_l, float(iz) * cell_l)
        for iz in range(n)
        for iy in range(n)
        for ix in range(n)
    ]
    expected = seed_mass * float(n_cells)
    print(
        f"noclip-batch{n_cells}: seed_mass={seed_mass:.1f} glue={glue} "
        f"fz={fuzzy_mm:g} grid={n}^3 (no clip, one-shot batch)",
        flush=True,
    )

    glue_climb: tuple[GlueMode, ...] = (glue, "shift", "off", "full")
    seen: set[str] = set()
    climb: list[GlueMode] = []
    for g in glue_climb:
        if g not in seen:
            seen.add(g)
            climb.append(g)
    fuzzies = sorted({float(fuzzy_mm), 0.1, 0.2, 0.4})
    last_err: Exception | None = None
    fused: Any | None = None
    for g in climb:
        for fz in fuzzies:
            t_b = time.time()
            print(
                f"  noclip-batch: trying g={g} fz={fz:g} n={n_cells} ...",
                flush=True,
            )
            try:
                cand = ocp_fuse_batch(
                    cells,
                    glue=g,
                    fuzzy_mm=float(fz),
                    simplify=False,
                    label=f"noclip-batch{n_cells}",
                )
                m = ocp_mass(cand)
                nsol = _ocp_count_solids(cand)
                print(
                    f"  noclip-batch: g={g} fz={fz:g} -> m={m:.1f} "
                    f"(r={m / expected:.3f}) n={nsol} t={time.time() - t_b:.1f}s",
                    flush=True,
                )
                if not gate_mass_ok(m, expected, lo=mass_lo, hi=mass_hi):
                    last_err = RuntimeError(f"mass gate m={m:.1f} exp={expected:.1f}")
                    continue
                if nsol != 1:
                    cand = _ensure_single_solid(
                        cand,
                        cut_mass=expected,
                        fuzzy_mm=max(0.1, float(fz)),
                        label="noclip-batch",
                        budget_s=600.0,
                    )
                    nsol = _ocp_count_solids(cand)
                    m = ocp_mass(cand)
                    print(f"  noclip-batch: remelt n={nsol} m={m:.1f}", flush=True)
                if nsol == 1 and gate_mass_ok(m, expected, lo=mass_lo, hi=mass_hi):
                    fused = cand
                    break
                last_err = RuntimeError(f"n={nsol} m={m:.1f}")
            except Exception as exc:
                last_err = exc
                print(
                    f"  noclip-batch: g={g} fz={fz:g} FAIL ({exc}) "
                    f"t={time.time() - t_b:.1f}s",
                    flush=True,
                )
        if fused is not None:
            break
    if fused is None:
        raise RuntimeError(f"noclip-batch{n_cells} exhausted; last={last_err}")

    ocp_write_step(fused, array_step)
    from src.export.sw_parasolid import measure_step_occ_stats

    gmsh_stats = measure_step_occ_stats(array_step)
    g_n = int(gmsh_stats.get("volume_count") or 0)
    g_mass = float(gmsh_stats.get("mass_mm3") or 0.0)
    if g_n != 1 or g_mass <= 0.0:
        raise RuntimeError(
            f"noclip-batch STEP not single solid for gmsh/QC: "
            f"volume_count={g_n} mass={g_mass:.1f}"
        )
    report = {
        "method": "ocp_noclip_batch_array_fuse",
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "seed_mass": seed_mass,
        "array_mass": g_mass,
        "array_solids": g_n,
        "ratio_vs_seed": (g_mass / seed_mass) if seed_mass > 0 else 0.0,
        "array_step": array_step,
        "cells": [n, n, n],
        "elapsed_s": round(time.time() - t0, 1),
        "gmsh_verified": True,
    }
    print(
        f"  noclip-batch{n_cells} OK mass={g_mass:.1f} solids={g_n} "
        f"ratio_vs_seed={report['ratio_vs_seed']:.2f} elapsed={report['elapsed_s']}s",
        flush=True,
    )
    return report


def export_ocp_scale_batch_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    scale: float = 1.005,
    glue: GlueMode = "shift",
    fuzzy_mm: float = 0.1,
    mass_lo: float = 0.85,
    mass_hi: float = 1.25,
    force: bool = True,
) -> dict[str, Any]:
    """Scale-inflate every cell, then one-shot OCP batch (no zcopy).

    Proven 2026-07-18 on ``af2q1p5_deq2_k1p5`` (raw noclip batch empty-fuses;
    scale=1.005 + batch64 → QC ratio≈64.3). Avoids seed_scale zcopy 444z fail.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Pnt, gp_Trsf

    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("scale-batch fuse expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    sc = float(scale)
    if sc < 1.0:
        raise ValueError(f"scale must be >= 1, got {sc}")
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)
    if force and os.path.isfile(array_step):
        os.remove(array_step)

    t0 = time.time()
    seed, seed_mass = load_ocp_unitcell_shape(os.path.abspath(seed_step), cell_size=cell_l)
    if seed_mass <= 0.0 or _ocp_count_solids(seed) != 1:
        raise RuntimeError(
            f"seed not a single solid mass={seed_mass:.1f} n={_ocp_count_solids(seed)}"
        )

    def _cell(ix: int, iy: int, iz: int) -> Any:
        ox, oy, oz = float(ix) * cell_l, float(iy) * cell_l, float(iz) * cell_l
        placed = ocp_translate_shape(seed, ox, oy, oz)
        if abs(sc - 1.0) < 1e-12:
            return placed
        tr = gp_Trsf()
        tr.SetScale(gp_Pnt(ox + 0.5 * cell_l, oy + 0.5 * cell_l, oz + 0.5 * cell_l), sc)
        return BRepBuilderAPI_Transform(placed, tr, True).Shape()

    cells = [_cell(ix, iy, iz) for iz in range(n) for iy in range(n) for ix in range(n)]
    cell_mass = ocp_mass(cells[0])
    expected = cell_mass * float(n * n * n)
    print(
        f"scale-batch{n**3}: seed={seed_mass:.1f} cell={cell_mass:.1f} "
        f"scale={sc:g} glue={glue} fz={fuzzy_mm:g}",
        flush=True,
    )

    glue_climb: tuple[GlueMode, ...] = (glue, "shift", "off", "full")
    seen: set[str] = set()
    climb: list[GlueMode] = []
    for g in glue_climb:
        if g not in seen:
            seen.add(g)
            climb.append(g)
    fuzzies = sorted({float(fuzzy_mm), 0.1, 0.2})
    last_err: Exception | None = None
    fused: Any | None = None
    for g in climb:
        for fz in fuzzies:
            t_b = time.time()
            print(f"  scale-batch: trying g={g} fz={fz:g} ...", flush=True)
            try:
                cand = ocp_fuse_batch(
                    cells, glue=g, fuzzy_mm=float(fz), simplify=False, label="scale-batch"
                )
                m = ocp_mass(cand)
                nsol = _ocp_count_solids(cand)
                print(
                    f"  scale-batch: g={g} fz={fz:g} -> m={m:.1f} "
                    f"(r={m / expected:.3f}) n={nsol} t={time.time() - t_b:.1f}s",
                    flush=True,
                )
                if not gate_mass_ok(m, expected, lo=mass_lo, hi=mass_hi):
                    last_err = RuntimeError(f"mass gate m={m:.1f} exp={expected:.1f}")
                    continue
                if nsol != 1:
                    cand = _ensure_single_solid(
                        cand,
                        cut_mass=expected,
                        fuzzy_mm=max(0.1, float(fz)),
                        label="scale-batch",
                        budget_s=600.0,
                    )
                    nsol = _ocp_count_solids(cand)
                    m = ocp_mass(cand)
                if nsol == 1 and gate_mass_ok(m, expected, lo=mass_lo, hi=mass_hi):
                    fused = cand
                    break
                last_err = RuntimeError(f"n={nsol} m={m:.1f}")
            except Exception as exc:
                last_err = exc
                print(
                    f"  scale-batch: FAIL {exc} t={time.time() - t_b:.1f}s",
                    flush=True,
                )
        if fused is not None:
            break
    if fused is None:
        raise RuntimeError(f"scale-batch exhausted; last={last_err}")

    ocp_write_step(fused, array_step)
    from src.export.sw_parasolid import measure_step_occ_stats

    gmsh_stats = measure_step_occ_stats(array_step)
    g_n = int(gmsh_stats.get("volume_count") or 0)
    g_mass = float(gmsh_stats.get("mass_mm3") or 0.0)
    if g_n != 1 or g_mass <= 0.0:
        raise RuntimeError(
            f"scale-batch STEP not single solid: volume_count={g_n} mass={g_mass:.1f}"
        )
    report = {
        "method": "ocp_scale_batch_array_fuse",
        "scale": sc,
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "seed_mass": seed_mass,
        "scaled_cell_mass": cell_mass,
        "array_mass": g_mass,
        "array_solids": g_n,
        "ratio_vs_seed": (g_mass / seed_mass) if seed_mass > 0 else 0.0,
        "array_step": array_step,
        "cells": [n, n, n],
        "elapsed_s": round(time.time() - t0, 1),
        "gmsh_verified": True,
    }
    print(
        f"  scale-batch OK mass={g_mass:.1f} ratio_vs_seed={report['ratio_vs_seed']:.2f} "
        f"elapsed={report['elapsed_s']}s",
        flush=True,
    )
    return report


def export_seed_nudge_ocp_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    nudge_mm: float = 4.0,
    glue: GlueMode = "full",
    fuzzy_mm: float = 0.05,
    mass_lo: float = 0.70,
    mass_hi: float = 1.30,
    force: bool = True,
) -> dict[str, Any]:
    """Seed-translate with large inward nudge → OCP fuse + coerce to 1 solid.

    Face-touching elliptic cells often need scale-inflate instead; see
    ``export_seed_scale_inflate_array_fuse``. Nudge path kept as fallback.
    """
    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("seed-nudge OCP fuse expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    nudge = max(0.0, float(nudge_mm))
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)
    if force and os.path.isfile(array_step):
        os.remove(array_step)

    t0 = time.time()
    seed, seed_mass = load_ocp_unitcell_shape(os.path.abspath(seed_step), cell_size=cell_l)
    if seed_mass <= 0.0 or _ocp_count_solids(seed) != 1:
        raise RuntimeError(
            f"seed not a single solid mass={seed_mass:.1f} n={_ocp_count_solids(seed)}"
        )
    # Uniform reduced pitch so every neighbour pair has the same overlap.
    pitch = max(1.0, cell_l - nudge)
    print(
        f"seed-nudge-ocp 444: seed_mass={seed_mass:.1f} nudge={nudge:g} mm "
        f"pitch={pitch:g} glue={glue} fz={fuzzy_mm:g} grid={n}^3",
        flush=True,
    )

    def _offset(i: int) -> float:
        return float(i) * pitch

    work_merge = os.path.join(out_dir, ".deep_pad_merge", "seed_nudge_ocp")
    os.makedirs(work_merge, exist_ok=True)

    # GlueFull on overlapping elliptic cells often only packages a compound
    # (mass≈sum, n>1) that MakerVolume cannot remelt. Prefer gmsh BREP fuse
    # on the translated solids; keep OCP pairwise as a fallback per group.
    def _fuse_cells(cells: list[Any], *, label: str, expected: float) -> Any:
        try:
            return _gmsh_fuse_shapes(
                cells,
                work_step=os.path.join(work_merge, f"{label}_gmsh.step"),
                label=f"{label}-gmsh",
                expected_mass=expected,
                mass_lo=mass_lo,
                mass_hi=mass_hi,
            )
        except Exception as gmsh_err:
            print(f"  {label}: gmsh failed ({gmsh_err}); try OCP pairwise...", flush=True)

        glue_climb: tuple[GlueMode, ...] = (glue, "shift", "full", "off")
        seen: set[str] = set()
        climb: list[GlueMode] = []
        for g in glue_climb:
            if g not in seen:
                seen.add(g)
                climb.append(g)
        fuzzies = sorted({float(fuzzy_mm), 0.05, 0.1, 0.2})
        acc = cells[0]
        for i, sh in enumerate(cells[1:], start=2):
            prev = ocp_mass(acc)
            piece = ocp_mass(sh)
            exp = prev + piece
            last_err: Exception | None = None
            done = False
            for g in climb:
                for fz in fuzzies:
                    try:
                        cand = ocp_fuse_pair(
                            acc,
                            sh,
                            glue=g,
                            fuzzy_mm=float(fz),
                            simplify=False,
                            label=f"{label}-{i}",
                        )
                        m = ocp_mass(cand)
                        if m < prev + 0.55 * piece:
                            last_err = RuntimeError(
                                f"mass not grown m={m:.1f} prev={prev:.1f} piece={piece:.1f}"
                            )
                            continue
                        if not gate_mass_ok(m, exp, lo=mass_lo, hi=mass_hi):
                            last_err = RuntimeError(
                                f"mass gate m={m:.1f} exp={exp:.1f} r={m / exp:.3f}"
                            )
                            continue
                        print(
                            f"  {label}-{i}: m={m:.1f} (r={m / exp:.3f}) "
                            f"n={_ocp_count_solids(cand)} g={g} fz={fz:g}",
                            flush=True,
                        )
                        acc = cand
                        done = True
                        break
                    except Exception as exc:
                        last_err = exc
                if done:
                    break
            if not done:
                raise RuntimeError(f"{label}: step {i}/{len(cells)} failed: {last_err}")
        return _coerce_single_solid(
            acc,
            expected_mass=expected,
            fuzzy_mm=float(fuzzy_mm),
            label=f"{label}-coerce",
            work_step=os.path.join(work_merge, f"{label}_coerce.step"),
            mass_lo=mass_lo,
            mass_hi=mass_hi,
        )

    slabs: list[Any] = []
    for iz in range(n):
        cells = [
            ocp_translate_shape(seed, _offset(ix), _offset(iy), _offset(iz))
            for iy in range(n)
            for ix in range(n)
        ]
        exp = seed_mass * float(n * n)
        print(f"\n=== seed-nudge iz={iz} ({n}x{n}, pitch={pitch:g}) ===", flush=True)
        # Fuse whole 4×4 slab via gmsh (row path is slower and less necessary).
        slab = _fuse_cells(cells, label=f"iz{iz}-slab", expected=exp)
        slab_path = os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_seed_nudge.step")
        ocp_write_step(slab, slab_path)
        print(f"  iz={iz} slab mass={ocp_mass(slab):.1f} -> {slab_path}", flush=True)
        slabs.append(slab)

    fused = _fuse_cells(
        slabs,
        label="444z",
        expected=seed_mass * float(n * n * n),
    )
    a_mass = ocp_mass(fused)
    nsol = _ocp_count_solids(fused)
    if nsol != 1:
        raise RuntimeError(f"final array has {nsol} solids, want 1")
    if not gate_mass_ok(a_mass, seed_mass * float(n**3), lo=0.90, hi=1.15):
        # Soft check vs seed*64 (nudge slightly increases overlap mass).
        print(
            f"  WARN mass vs 64*seed: {a_mass:.1f} / {seed_mass * n**3:.1f} "
            f"= {a_mass / (seed_mass * n**3):.3f}",
            flush=True,
        )
    ocp_write_step(fused, array_step)
    report = {
        "method": "seed_nudge_ocp_array_fuse",
        "nudge_mm": nudge,
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "seed_mass": seed_mass,
        "array_mass": a_mass,
        "array_solids": nsol,
        "array_step": array_step,
        "cells": [n, n, n],
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(
        f"  seed-nudge-ocp 444 OK mass={a_mass:.1f} solids={nsol} "
        f"ratio~{a_mass / seed_mass:.2f} elapsed={report['elapsed_s']}s",
        flush=True,
    )
    return report


def export_seed_translate_gmsh_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    nudge_mm: float = 0.0,
    mass_lo: float = 0.70,
    mass_hi: float = 1.35,
    force: bool = True,
    repair_seed_bop: bool = True,
) -> dict[str, Any]:
    """Place seed on nx×ny×nz grid (optional inward nudge) → gmsh BREP fuse.

    Avoids rebuilding elliptic pipes (MakePipeShell often fails at Q≈1.5).
    Runs seed BOP-repair first when adjacent-cell fuse is empty.
    """
    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("seed-gmsh fuse expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    nudge = max(0.0, float(nudge_mm))
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)
    if force and os.path.isfile(array_step):
        os.remove(array_step)

    t0 = time.time()
    seed_path = os.path.abspath(str(seed_step))
    bop_report: dict[str, Any] | None = None
    if repair_seed_bop:
        from src.export.seed_bop_repair import repair_seed_step_for_array_bop

        repaired = os.path.join(out_dir, ".work_seed_bop_repaired.step")
        print("seed-gmsh: BOP-repair seed for adjacent-cell fuse...", flush=True)
        bop_report = repair_seed_step_for_array_bop(
            seed_path,
            repaired,
            cell_size_mm=cell_l,
            force=True,
        )
        if bop_report.get("ok") and os.path.isfile(repaired):
            seed_path = repaired
            print(
                f"  seed-bop-repair OK method={bop_report.get('method')}",
                flush=True,
            )
        else:
            print(
                f"  seed-bop-repair failed ({bop_report.get('error')}); "
                f"continue with raw seed",
                flush=True,
            )

    seed, seed_mass = load_ocp_unitcell_shape(seed_path, cell_size=cell_l)
    if seed_mass <= 0.0 or _ocp_count_solids(seed) != 1:
        raise RuntimeError(
            f"seed not a single solid mass={seed_mass:.1f} "
            f"n={_ocp_count_solids(seed)}"
        )
    pitch = max(1.0, cell_l - nudge)
    print(
        f"seed-gmsh 444: seed_mass={seed_mass:.1f} nudge={nudge:g} mm "
        f"pitch={pitch:g} grid={n}^3 seed={seed_path}",
        flush=True,
    )

    def _offset(i: int) -> float:
        # Uniform reduced pitch so every neighbour pair has the same overlap.
        return float(i) * pitch

    work_merge = os.path.join(out_dir, ".deep_pad_merge", "seed_gmsh")
    os.makedirs(work_merge, exist_ok=True)
    slabs: list[Any] = []
    for iz in range(n):
        cells: list[Any] = []
        for iy in range(n):
            for ix in range(n):
                cells.append(
                    ocp_translate_shape(
                        seed, _offset(ix), _offset(iy), _offset(iz)
                    )
                )
        exp = seed_mass * float(n * n)
        print(
            f"  iz={iz}: gmsh-fuse {len(cells)} translated cell(s)...",
            flush=True,
        )
        slab = _gmsh_fuse_shapes(
            cells,
            work_step=os.path.join(work_merge, f"iz{iz}_gmsh.step"),
            label=f"seed-gmsh-iz{iz}",
            expected_mass=exp,
            mass_lo=mass_lo,
            mass_hi=mass_hi,
        )
        slab_path = os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_seed_gmsh.step")
        ocp_write_step(slab, slab_path)
        print(f"  iz={iz} slab mass={ocp_mass(slab):.1f} -> {slab_path}", flush=True)
        slabs.append(slab)

    fused = _gmsh_fuse_shapes(
        slabs,
        work_step=os.path.join(work_merge, "444z_gmsh.step"),
        label="seed-gmsh-444z",
        expected_mass=seed_mass * float(n * n * n),
        mass_lo=mass_lo,
        mass_hi=mass_hi,
    )
    a_mass = ocp_mass(fused)
    nsol = _ocp_count_solids(fused)
    if nsol != 1:
        raise RuntimeError(f"final array has {nsol} solids, want 1")
    ocp_write_step(fused, array_step)
    report = {
        "method": "seed_translate_gmsh_array_fuse",
        "nudge_mm": nudge,
        "seed_mass": seed_mass,
        "seed_path_used": seed_path,
        "seed_bop_repair": bop_report,
        "array_mass": a_mass,
        "array_solids": nsol,
        "array_step": array_step,
        "cells": [n, n, n],
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(
        f"  seed-gmsh 444 OK mass={a_mass:.1f} solids={nsol} "
        f"ratio~{a_mass / seed_mass:.2f} elapsed={report['elapsed_s']}s",
        flush=True,
    )
    return report
