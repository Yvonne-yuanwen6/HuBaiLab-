"""
Trimmed lattice fill of a square-outer / circular-inner frame domain.

Cartesian HuBai unit cells (undistorted interior) + Common(Ω); optional full_only gate.

  py -3 scripts/export_frame_trim_fill.py
  py -3 scripts/export_frame_trim_fill.py --mode intersect --skin-mm 2
  py -3 scripts/export_frame_trim_fill.py --mode full_only

Output: output/cad/_frame_trim_fill/  (not verified).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.design_domain import (
    cartesian_cell_centers,
    domain_from_step,
    gate_cell_centers,
    grid_counts_from_frame,
    make_frame_skins,
    make_square_minus_cylinder_domain,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape, ocp_translate_shape
from src.export.ocp_unitcell_fuse import (
    ocp_common,
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)
from src.export.unitcell_box_cut import export_unitcell_step_paper_box_cut
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def _ensure_unitcell_seed(
    seed_path: str,
    *,
    L: float,
    rod_d: float,
    Af: float,
    n_segments: int,
    Q: float = 0.0,
) -> dict:
    if os.path.isfile(seed_path):
        return {
            "seed_step": os.path.abspath(seed_path),
            "reused": True,
            "variant": "existing_seed",
        }
    gen = HuBaiLatticeGenerator(
        cell_size=float(L),
        rod_diameter=float(rod_d),
        amplitude=float(Af),
        period_factor=float(Q),
        n_segments=max(3, int(n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    print(f"Build seed Q={Q:g} ({gen.variant_name}) -> {seed_path}", flush=True)
    report = export_unitcell_step_paper_box_cut(
        nodes,
        beams,
        seed_path,
        polylines=polylines,
        cell_size_mm=float(L),
        n_segments_hint=max(3, int(n_segments)),
        period_factor=float(Q),
        rod_diameter_mm=float(rod_d),
        amplitude_mm=float(Af),
        solid_profile="circle",
    )
    return {
        "seed_step": os.path.abspath(seed_path),
        "reused": False,
        "variant": gen.variant_name,
        **{k: v for k, v in report.items() if k != "step_path"},
    }


def _trim_cell_to_domain(placed: Any, domain: Any) -> Any | None:
    try:
        clipped = ocp_common(placed, domain)
    except RuntimeError:
        return None
    if ocp_mass(clipped) <= 1e-6:
        return None
    return clipped


def _fuse_pair_robust(
    a: Any,
    b: Any,
    *,
    fuzzy_mm: float,
    label: str,
    allow_compound: bool = True,
) -> Any:
    """GlueShift → glue=off → larger fuzzy → optional compound (never abort)."""
    attempts: list[tuple[str, float]] = [
        ("shift", float(fuzzy_mm)),
        ("off", float(fuzzy_mm)),
        ("off", max(float(fuzzy_mm), 0.05)),
        ("off", max(float(fuzzy_mm), 0.1)),
    ]
    last_exc: Exception | None = None
    for glue, fuzzy in attempts:
        try:
            return ocp_fuse_pair(
                a,
                b,
                glue=glue,
                fuzzy_mm=float(fuzzy),
                label=f"{label}-{glue}-{fuzzy:g}",
            )
        except RuntimeError as exc:
            last_exc = exc
            print(
                f"  [WARN] {label}: fuse glue={glue} fuzzy={fuzzy:g} failed ({exc})",
                flush=True,
            )
    if allow_compound:
        print(
            f"  [WARN] {label}: boolean failed; packing as compound "
            f"(last={last_exc})",
            flush=True,
        )
        return _make_compound([a, b])
    raise RuntimeError(f"{label}: fuse failed ({last_exc})") from last_exc


def _try_heal(shape: Any) -> Any:
    try:
        healed = ocp_heal_fused_solid(shape)
        if ocp_mass(healed) >= 0.5 * max(ocp_mass(shape), 1e-9):
            return healed
        print(
            f"  [WARN] heal dropped mass {ocp_mass(shape):.1f}→{ocp_mass(healed):.1f}; "
            "keeping unhealed",
            flush=True,
        )
    except Exception as exc:
        print(f"  [WARN] heal skipped ({exc})", flush=True)
    return shape


def _fuse_shapes_sequential(
    shapes: list[Any],
    *,
    fuzzy_mm: float = 0.02,
    label: str = "frame-trim-fuse",
) -> Any:
    if not shapes:
        raise RuntimeError("no shapes to fuse")
    if len(shapes) == 1:
        return _try_heal(shapes[0])
    acc = shapes[0]
    for i, sh in enumerate(shapes[1:], start=2):
        acc = _fuse_pair_robust(
            acc,
            sh,
            fuzzy_mm=fuzzy_mm,
            label=f"{label}-{i}/{len(shapes)}",
        )
        print(f"  fused {i}/{len(shapes)} mass={ocp_mass(acc):.1f} mm3", flush=True)
    return _try_heal(acc)


def _fuse_shapes_pairwise_tree(
    shapes: list[Any],
    *,
    fuzzy_mm: float = 0.02,
    label: str = "pair-tree",
) -> Any:
    """Binary pairwise fuse (more stable than long sequential chains)."""
    if not shapes:
        raise RuntimeError("no shapes to fuse")
    level = list(shapes)
    round_i = 0
    while len(level) > 1:
        round_i += 1
        nxt: list[Any] = []
        for i in range(0, len(level), 2):
            if i + 1 >= len(level):
                nxt.append(level[i])
                continue
            fused = _fuse_pair_robust(
                level[i],
                level[i + 1],
                fuzzy_mm=fuzzy_mm,
                label=f"{label}-r{round_i}-{i // 2}",
            )
            nxt.append(fused)
        print(
            f"  {label}: round {round_i} → {len(nxt)} body(ies), "
            f"mass={sum(ocp_mass(s) for s in nxt):.1f} mm3",
            flush=True,
        )
        level = nxt
    return _try_heal(level[0])


def _fuse_shapes(
    shapes: list[Any],
    *,
    fuzzy_mm: float = 0.02,
    centers: list[tuple[float, float, float]] | None = None,
) -> Any:
    """
    Fuse trimmed cells. Prefer row-wise then pairwise tree when centres given;
    otherwise pairwise tree (avoids long sequential GlueShift collapse).
    """
    if not shapes:
        raise RuntimeError("no shapes to fuse")
    if len(shapes) == 1:
        return _try_heal(shapes[0])

    if centers is not None and len(centers) == len(shapes):
        by_y: dict[float, list[tuple[float, Any]]] = {}
        for sh, c in zip(shapes, centers):
            y_key = round(float(c[1]), 6)
            by_y.setdefault(y_key, []).append((float(c[0]), sh))
        rows: list[Any] = []
        for yi, y in enumerate(sorted(by_y.keys()), start=1):
            row_shapes = [sh for _, sh in sorted(by_y[y], key=lambda t: t[0])]
            print(
                f"  fuse row {yi}/{len(by_y)} y={y:g} ({len(row_shapes)} cell(s))",
                flush=True,
            )
            rows.append(
                _fuse_shapes_pairwise_tree(
                    row_shapes, fuzzy_mm=fuzzy_mm, label=f"row{yi}"
                )
            )
        if len(rows) == 1:
            return rows[0]
        print(f"  fuse {len(rows)} row-block(s)...", flush=True)
        return _fuse_shapes_pairwise_tree(rows, fuzzy_mm=fuzzy_mm, label="rows")

    return _fuse_shapes_pairwise_tree(shapes, fuzzy_mm=fuzzy_mm, label="cells")


def _unique_z_levels(
    centers: list[tuple[float, float, float]],
) -> list[float]:
    """Sorted unique cell-centre Z values (mm)."""
    return sorted({round(float(c[2]), 6) for c in centers})


def _centers_on_z(
    centers: list[tuple[float, float, float]],
    z_mm: float,
    *,
    tol_mm: float = 1e-4,
) -> list[tuple[float, float, float]]:
    return [c for c in centers if abs(float(c[2]) - float(z_mm)) <= tol_mm]


def _grid_has_axis_cells(
    centers: list[tuple[float, float, float]],
    *,
    tol_mm: float = 1e-6,
) -> bool:
    """True if any centre lies on x=0 or y=0 (odd nx/ny); blocks clean 4-fold split."""
    for c in centers:
        if abs(float(c[0])) <= tol_mm or abs(float(c[1])) <= tol_mm:
            return True
    return False


def _centers_quadrant_pp(
    centers: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """+x/+y open quadrant (exclusive of axes)."""
    return [c for c in centers if float(c[0]) > 0.0 and float(c[1]) > 0.0]


def _rotate_shape_z(shape: Any, angle_deg: float) -> Any:
    """Copy + rotate about global Z through origin."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf
    import math

    trsf = gp_Trsf()
    trsf.SetRotation(
        gp_Ax1(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0)),
        math.radians(float(angle_deg)),
    )
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def _fuse_quadrant_4fold(
    quadrant: Any,
    *,
    fuzzy_mm: float = 0.02,
) -> Any:
    """Fuse one +x/+y quadrant solid with 90/180/270° Z copies."""
    print(
        f"  4-fold rotate: ref quadrant mass={ocp_mass(quadrant):.1f} mm3",
        flush=True,
    )
    parts = [quadrant]
    for ang in (90.0, 180.0, 270.0):
        rot = _rotate_shape_z(quadrant, ang)
        print(
            f"  4-fold +{ang:g}° mass={ocp_mass(rot):.1f} mm3",
            flush=True,
        )
        parts.append(rot)
    return _fuse_shapes_pairwise_tree(parts, fuzzy_mm=fuzzy_mm, label="4fold")


def _fuse_z_copy_stack(
    slab: Any,
    z_levels: list[float],
    *,
    fuzzy_mm: float = 0.02,
) -> Any:
    """
    Fuse one z-slab, then translate-copy it to the remaining Z levels and fuse.

    Valid when the design domain is prismatic in Z (same XY cross-section at every
    height), so each layer after Common(Ω) is a rigid translate of the first.
    """
    if not z_levels:
        raise RuntimeError("no z levels for z-copy stack")
    if len(z_levels) == 1:
        return _try_heal(slab)

    z0 = float(z_levels[0])
    acc = slab
    print(
        f"  z-copy stack: ref slab z={z0:g} → {len(z_levels)} layer(s)",
        flush=True,
    )
    for i, z in enumerate(z_levels[1:], start=2):
        dz = float(z) - z0
        copied = ocp_translate_shape(slab, 0.0, 0.0, dz)
        print(
            f"  z-copy {i}/{len(z_levels)} dz={dz:g} mm "
            f"mass={ocp_mass(copied):.1f} mm3",
            flush=True,
        )
        acc = _fuse_pair_robust(
            acc,
            copied,
            fuzzy_mm=fuzzy_mm,
            label=f"frame-trim-zcopy-{i}/{len(z_levels)}",
        )
        print(
            f"  fused z-copy {i}/{len(z_levels)} mass={ocp_mass(acc):.1f} mm3",
            flush=True,
        )
    return _try_heal(acc)


def _fuse_shapes_layered_by_z(
    shapes: list[Any],
    centers: list[tuple[float, float, float]],
    *,
    fuzzy_mm: float = 0.02,
) -> Any:
    """
    Fuse z-layers first, then stack layers (fallback when z-copy is disabled).

    ``shapes[i]`` must correspond to ``centers[i]``.
    """
    if len(shapes) != len(centers):
        raise RuntimeError(
            f"shape/center mismatch: {len(shapes)} shapes vs {len(centers)} centers"
        )
    if not shapes:
        raise RuntimeError("no shapes to fuse")

    by_z: dict[float, list[tuple[Any, tuple[float, float, float]]]] = {}
    for sh, c in zip(shapes, centers):
        z_key = round(float(c[2]), 6)
        by_z.setdefault(z_key, []).append((sh, c))

    z_keys = sorted(by_z.keys())
    print(
        f"  layered fuse: {len(z_keys)} z-slab(s), "
        f"{'/'.join(str(len(by_z[z])) for z in z_keys)} cells",
        flush=True,
    )
    slabs: list[Any] = []
    for zi, z in enumerate(z_keys, start=1):
        items = by_z[z]
        print(f"  slab {zi}/{len(z_keys)} z={z:g} ({len(items)} cell(s))", flush=True)
        slabs.append(
            _fuse_shapes(
                [sh for sh, _ in items],
                fuzzy_mm=fuzzy_mm,
                centers=[c for _, c in items],
            )
        )

    if len(slabs) == 1:
        return slabs[0]
    acc = slabs[0]
    for i, slab in enumerate(slabs[1:], start=2):
        acc = _fuse_pair_robust(
            acc,
            slab,
            fuzzy_mm=fuzzy_mm,
            label=f"frame-trim-slab-{i}/{len(slabs)}",
        )
        print(f"  fused slab {i}/{len(slabs)} mass={ocp_mass(acc):.1f} mm3", flush=True)
    return _try_heal(acc)


def _make_compound(shapes: list[Any]) -> Any:
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for sh in shapes:
        if sh is not None and ocp_mass(sh) > 0.0:
            builder.Add(comp, sh)
    return comp


def _fuse_skins_onto_lattice(
    lattice: Any,
    inner_skin: Any,
    outer_skin: Any,
    *,
    fuzzy_mm: float,
    prefer_compound: bool | None = None,
) -> tuple[Any, dict]:
    """
    Attach skins. On large lattices OCC Fuse often collapses; use a multi-body
    compound (lattice + skins) so SW can Combine / see sealed walls.
    """
    mass0 = ocp_mass(lattice)
    # Empirically, single-layer ~4k mm3 fuses OK; 4×4×4 ~20k collapses.
    if prefer_compound is None:
        prefer_compound = mass0 > 8000.0
    report: dict = {"method": "fuse", "lattice_mass_mm3": mass0}

    if prefer_compound:
        print(
            f"  large lattice mass={mass0:.1f} mm3 → compound(lattice+skins) "
            "(skip boolean; open in SW and Combine if you need one body)",
            flush=True,
        )
        report["method"] = "compound_large_lattice"
        return _make_compound([lattice, inner_skin, outer_skin]), report

    from src.export.ocp_unitcell_fuse import ocp_cut

    print(f"  lattice before skin cut mass={mass0:.1f} mm3", flush=True)
    core = lattice
    try:
        core = ocp_cut(core, inner_skin, label="lattice_minus_inner_skin")
        print(f"  after cut inner skin mass={ocp_mass(core):.1f} mm3", flush=True)
    except RuntimeError as exc:
        print(f"  [WARN] cut inner skin skipped: {exc}", flush=True)
    try:
        core = ocp_cut(core, outer_skin, label="lattice_minus_outer_skin")
        print(f"  after cut outer skin mass={ocp_mass(core):.1f} mm3", flush=True)
    except RuntimeError as exc:
        print(f"  [WARN] cut outer skin skipped: {exc}", flush=True)

    core_mass = ocp_mass(core)
    if core_mass <= 0.05 * mass0:
        print(
            "  [WARN] lattice core too small after skin cuts; compound fallback",
            flush=True,
        )
        report["method"] = "compound_fallback_core_empty"
        return _make_compound([lattice, inner_skin, outer_skin]), report

    try:
        print(
            f"  fuse inner liner mass={ocp_mass(inner_skin):.1f} mm3",
            flush=True,
        )
        acc = ocp_fuse_pair(
            core,
            inner_skin,
            glue="off",
            fuzzy_mm=float(fuzzy_mm),
            simplify=False,
            label="frame-skin-inner",
        )
        m_inner = ocp_mass(acc)
        print(f"  after inner skin mass={m_inner:.1f} mm3", flush=True)
        if m_inner < 0.5 * (core_mass + ocp_mass(inner_skin) * 0.5):
            raise RuntimeError(f"inner skin fuse mass collapse ({m_inner:.1f} mm3)")
        print(
            f"  fuse outer frame mass={ocp_mass(outer_skin):.1f} mm3",
            flush=True,
        )
        acc = ocp_fuse_pair(
            acc,
            outer_skin,
            glue="off",
            fuzzy_mm=float(fuzzy_mm),
            simplify=False,
            label="frame-skin-outer",
        )
        m_outer = ocp_mass(acc)
        print(f"  after outer skin mass={m_outer:.1f} mm3", flush=True)
        if m_outer < mass0 + 0.2 * (ocp_mass(inner_skin) + ocp_mass(outer_skin)):
            raise RuntimeError(f"outer skin fuse mass collapse ({m_outer:.1f} mm3)")
        healed = ocp_heal_fused_solid(acc)
        if ocp_mass(healed) < 0.5 * ocp_mass(acc):
            print(
                f"  [WARN] heal dropped mass {ocp_mass(acc):.1f} -> "
                f"{ocp_mass(healed):.1f}; keeping unhealed",
                flush=True,
            )
            return acc, report
        return healed, report
    except RuntimeError as exc:
        print(
            f"  [WARN] skin boolean fuse failed ({exc}); compound fallback",
            flush=True,
        )
        report["method"] = "compound_fallback_fuse"
        report["fuse_error"] = str(exc)
        return _make_compound([lattice, inner_skin, outer_skin]), report


def run_one_mode(
    *,
    mode: str,
    domain: Any,
    domain_meta: dict,
    seed_shape: Any,
    centers_all: list[tuple[float, float, float]],
    L: float,
    out_dir: str,
    tag: str,
    fuzzy_mm: float,
    write_domain_step: bool,
    skins: tuple[Any, Any, dict] | None = None,
    z_copy_stack: bool = True,
    rotate_4fold: bool = True,
) -> dict:
    z_levels = _unique_z_levels(centers_all)
    use_z_copy = bool(z_copy_stack) and len(z_levels) > 1

    # Start from one z-layer (or full grid), then optionally +x/+y quadrant.
    if use_z_copy:
        layer_centers = _centers_on_z(centers_all, z_levels[0])
    else:
        layer_centers = list(centers_all)

    use_4fold = (
        bool(rotate_4fold)
        and not _grid_has_axis_cells(layer_centers)
        and len(_centers_quadrant_pp(layer_centers)) >= 1
        and len(_centers_quadrant_pp(layer_centers)) * 4 == len(layer_centers)
    )
    if use_4fold:
        work_centers = _centers_quadrant_pp(layer_centers)
        print(
            f"[{mode}] 4-fold shortcut: gate+trim+fuse "
            f"{len(work_centers)} cells in +x/+y quadrant"
            + (
                f" at z={z_levels[0]:g}, then rotate×4"
                if use_z_copy
                else ", then rotate×4"
            )
            + (f", then z-copy×{len(z_levels)}" if use_z_copy else ""),
            flush=True,
        )
    elif use_z_copy:
        work_centers = layer_centers
        print(
            f"[{mode}] z-copy shortcut: gate+trim+fuse "
            f"{len(work_centers)} cells at z={z_levels[0]:g}, "
            f"then copy ×{len(z_levels)} layers",
            flush=True,
        )
    else:
        work_centers = layer_centers

    kept, gate_reports = gate_cell_centers(
        work_centers, L, domain, mode=mode  # type: ignore[arg-type]
    )
    n_drop = len(work_centers) - len(kept)
    scale_xy = 4 if use_4fold else 1
    scale_z = len(z_levels) if use_z_copy else 1
    print(
        f"[{mode}] keep {len(kept)}/{len(work_centers)} cells "
        f"(drop {n_drop}"
        + (
            f"; quadrant×{scale_xy}"
            + (f"×z{scale_z}" if use_z_copy else "")
            + f", full grid {len(centers_all)}"
            if use_4fold or use_z_copy
            else ""
        )
        + ")",
        flush=True,
    )

    trimmed: list[Any] = []
    trim_centers: list[tuple[float, float, float]] = []
    trim_meta: list[dict] = []
    for c in kept:
        placed = ocp_translate_shape(seed_shape, c[0], c[1], c[2])
        clip = _trim_cell_to_domain(placed, domain)
        if clip is None:
            trim_meta.append({"center": c, "kept_after_common": False})
            continue
        m = ocp_mass(clip)
        trimmed.append(clip)
        trim_centers.append(c)
        trim_meta.append(
            {
                "center": c,
                "kept_after_common": True,
                "mass_mm3": m,
            }
        )
        print(
            f"  cell ({c[0]:g},{c[1]:g},{c[2]:g}) trim mass={m:.2f} mm3",
            flush=True,
        )

    if not trimmed:
        raise RuntimeError(f"mode={mode}: no cells survived Common(Ω)")

    print(
        f"  fuse work set ({len(trimmed)} cell(s))"
        + (" → 4-fold" if use_4fold else "")
        + (f" → z-copy×{len(z_levels)}" if use_z_copy else "")
        + "...",
        flush=True,
    )
    piece = _fuse_shapes(trimmed, fuzzy_mm=fuzzy_mm, centers=trim_centers)
    if use_4fold:
        piece = _fuse_quadrant_4fold(piece, fuzzy_mm=fuzzy_mm)
    if use_z_copy:
        fused = _fuse_z_copy_stack(piece, z_levels, fuzzy_mm=fuzzy_mm)
    else:
        fused = piece
    cells_after_common = len(trimmed) * scale_xy * scale_z

    topo = ocp_shape_topology(fused, count_faces=True, check_brep=True)
    out_step = os.path.join(out_dir, f"frame_trim_fill_{tag}_{mode}.step")
    ocp_write_step(fused, out_step)

    domain_step = None
    if write_domain_step:
        domain_step = os.path.join(out_dir, f"frame_domain_{tag}.step")
        if not os.path.isfile(domain_step):
            ocp_write_step(domain, domain_step)

    entry = {
        "mode": mode,
        "step": os.path.abspath(out_step),
        "size_bytes": os.path.getsize(out_step),
        "cells_considered": len(centers_all),
        "cells_gated_keep": len(kept) * scale_xy * scale_z,
        "cells_after_common": cells_after_common,
        "cells_dropped_gate": n_drop * scale_xy * scale_z,
        "z_copy_stack": use_z_copy,
        "rotate_4fold": use_4fold,
        "z_levels_mm": z_levels if use_z_copy else _unique_z_levels(trim_centers),
        "gate_reports": gate_reports,
        "trim_meta": trim_meta,
        "topology": topo,
        "domain_step": domain_step,
        "domain_meta": domain_meta,
        "ok": int(topo.get("solids") or 0) >= 1 and float(topo.get("mass_mm3") or 0) > 0,
    }
    print(
        f"[{mode}] STEP solids={topo.get('solids')} mass={topo.get('mass_mm3'):.1f} "
        f"brep={topo.get('brep_valid')} -> {out_step}",
        flush=True,
    )

    apply_skin = skins is not None and mode == "intersect"
    if apply_skin:
        inner_skin, outer_skin, skin_meta = skins
        try:
            skinned, skin_method = _fuse_skins_onto_lattice(
                fused, inner_skin, outer_skin, fuzzy_mm=fuzzy_mm
            )
            skin_topo = ocp_shape_topology(
                skinned, count_faces=False, check_brep=True
            )
            skin_step = os.path.join(
                out_dir, f"frame_trim_fill_{tag}_{mode}_skin.step"
            )
            ocp_write_step(skinned, skin_step)
            method = str(skin_method.get("method", "fuse"))
            fused_ok = (
                method == "fuse"
                and int(skin_topo.get("solids") or 0) == 1
                and float(skin_topo.get("mass_mm3") or 0)
                > float(topo.get("mass_mm3") or 0)
                + 0.2
                * float(
                    skin_meta["inner_liner_mass_mm3"]
                    + skin_meta["outer_frame_mass_mm3"]
                )
            )
            compound_ok = method.startswith("compound") and int(
                skin_topo.get("solids") or 0
            ) >= 2
            skin_ok = bool(fused_ok or compound_ok)
            entry["skin"] = {
                **skin_meta,
                **skin_method,
                "step": os.path.abspath(skin_step),
                "size_bytes": os.path.getsize(skin_step),
                "topology": skin_topo,
                "skin_ok": skin_ok,
            }
            # Lattice STEP is the primary deliverable; skin is best-effort.
            if not skin_ok:
                print(
                    f"[{mode}+skin] [WARN] skin QC failed "
                    f"(method={method}, solids={skin_topo.get('solids')}, "
                    f"mass={skin_topo.get('mass_mm3'):.1f})",
                    flush=True,
                )
            print(
                f"[{mode}+skin] method={method} solids={skin_topo.get('solids')} "
                f"mass={skin_topo.get('mass_mm3'):.1f} "
                f"brep={skin_topo.get('brep_valid')} -> {skin_step}",
                flush=True,
            )
        except Exception as exc:
            entry["skin"] = {**skin_meta, "error": str(exc), "skin_ok": False}
            print(
                f"[{mode}+skin] [WARN] skin fuse failed: {exc}; "
                f"lattice-only STEP kept",
                flush=True,
            )
    return entry


def run_frame_trim_fill(
    *,
    S: float = 80.0,
    H: float | None = None,
    R_hole: float = 25.0,
    L: float = 20.0,
    nx: int | None = None,
    ny: int | None = None,
    nz: int | None = None,
    rod_d: float = 2.0,
    Af: float = 2.0,
    Q: float = 0.0,
    n_segments: int = 12,
    mode: str = "intersect",
    fuzzy_mm: float = 0.02,
    skin_mm: float = 2.0,
    inner_wall_mm: float | None = None,
    outer_wall_mm: float | None = None,
    out_dir: str = "",
    seed_step: str = "",
    domain_step: str = "",
    write_domain: bool = True,
    auto_grid_from_frame: bool = True,
    snap_frame_to_grid: bool = False,
    fit_height_to_layers: bool = False,
    fit_outer_to_grid: bool = False,
    z_copy_stack: bool = True,
    rotate_4fold: bool = True,
) -> int:
    """Run trim-fill from a parameter dict (used by CLI and the manual main script)."""
    L = float(L)
    S = float(S)
    if H is None:
        H = S
    H = float(H)
    H_requested = H
    S_requested = S

    grid_meta: dict | None = None
    if auto_grid_from_frame or nx is None or ny is None or nz is None:
        nx, ny, nz, grid_meta = grid_counts_from_frame(
            side_mm=S, height_mm=H, cell_size_mm=L
        )
        print(
            f"auto grid from frame: S={S:g} H={H:g} L={L:g} → {nx}x{ny}x{nz} "
            f"(lattice span {nx*L:g}×{ny*L:g}×{nz*L:g})",
            flush=True,
        )
        # Frame height H is never snapped: always keep the user value.
        # Optional snap only adjusts outer side S so XY cells tile exactly.
        if snap_frame_to_grid and grid_meta is not None:
            if grid_meta.get("snapped_xy"):
                S = float(grid_meta["side_span_mm"])
                print(f"  snap S → {S:g} mm (= nx*L); H kept at {H:g} mm", flush=True)
            if grid_meta.get("snapped_z"):
                print(
                    f"  note: nz*L={grid_meta['height_span_mm']:g} ≠ H={H:g}; "
                    f"frame height kept at H (no snap)",
                    flush=True,
                )
    else:
        nx, ny, nz = int(nx), int(ny), int(nz)

    if fit_outer_to_grid:
        S = float(nx) * L
        print(f"fit_outer_to_grid: S={S:g} mm", flush=True)
    if fit_height_to_layers:
        H = float(nz) * L
        print(f"fit_height_to_layers: H={H:g} mm (overrides requested {H_requested:g})", flush=True)
    else:
        H = H_requested
        print(f"frame height H={H:g} mm (as set)", flush=True)

    R = float(R_hole)

    out_dir = out_dir or os.path.join(str(CAD_ROOT), "_frame_trim_fill")
    os.makedirs(out_dir, exist_ok=True)

    if nx * ny * nz > 16:
        print(
            f"[WARN] cell count {nx * ny * nz} > 16; fuse may be slow",
            flush=True,
        )

    if domain_step:
        domain, domain_meta = domain_from_step(domain_step)
        tag = "custom"
    else:
        domain, domain_meta = make_square_minus_cylinder_domain(
            side_mm=S,
            height_mm=H,
            hole_radius_mm=R,
        )
        tag = f"S{S:g}_H{H:g}_R{R:g}_L{L:g}_{nx}x{ny}x{nz}"

    print(
        f"Domain {domain_meta.get('kind')} mass={domain_meta.get('mass_mm3'):.1f} mm3",
        flush=True,
    )

    q_tag = str(float(Q)).replace(".", "p")
    seed_path = seed_step or os.path.join(
        out_dir, f"unitcell_L{L:g}_d{rod_d:g}_Q{q_tag}_seed.step"
    )
    shared = os.path.join(
        str(CAD_ROOT),
        "_unitcell_cyl_hole",
        f"unitcell_bcc_L{L:g}_d{rod_d:g}_Q0_seed.step",
    )
    if not seed_step and abs(float(Q)) < 1e-12 and os.path.isfile(shared):
        seed_path = shared

    seed_report = _ensure_unitcell_seed(
        seed_path,
        L=L,
        rod_d=float(rod_d),
        Af=float(Af),
        n_segments=int(n_segments),
        Q=float(Q),
    )
    seed_shape = ocp_read_step_shape(seed_report["seed_step"])
    print(
        f"Seed mass={ocp_mass(seed_shape):.2f} mm3 from {seed_report['seed_step']}",
        flush=True,
    )

    centers = cartesian_cell_centers(nx, ny, nz, L)
    modes = (
        ["intersect", "full_only"]
        if str(mode) == "both"
        else [str(mode)]
    )

    skins = None
    skin_mm = float(skin_mm)
    t_in = float(inner_wall_mm) if inner_wall_mm is not None else skin_mm
    t_out = float(outer_wall_mm) if outer_wall_mm is not None else skin_mm
    if t_in > 0.0 and t_out > 0.0 and not domain_step:
        inner_skin, outer_skin, skin_meta = make_frame_skins(
            side_mm=S,
            height_mm=H,
            hole_radius_mm=R,
            inner_wall_mm=t_in,
            outer_wall_mm=t_out,
        )
        skins = (inner_skin, outer_skin, skin_meta)
        print(
            f"Walls inner={t_in:g} outer={t_out:g} mm "
            f"(H={H:g}) inner_vol={skin_meta['inner_liner_mass_mm3']:.1f} "
            f"outer_vol={skin_meta['outer_frame_mass_mm3']:.1f} mm3",
            flush=True,
        )
    elif (t_in > 0.0) != (t_out > 0.0):
        raise ValueError(
            f"set both walls > 0 or both = 0 (got inner={t_in:g}, outer={t_out:g})"
        )
    elif (t_in > 0.0 or t_out > 0.0) and domain_step:
        print(
            "[WARN] wall thickness ignored with domain_step (square−cylinder skins only)",
            flush=True,
        )

    manifest: dict = {
        "out_dir": os.path.abspath(out_dir),
        "S_mm": S,
        "S_requested_mm": S_requested,
        "H_mm": H,
        "H_requested_mm": H_requested,
        "R_hole_mm": R,
        "L_mm": L,
        "Q": float(Q),
        "skin_mm": skin_mm,
        "inner_wall_mm": t_in,
        "outer_wall_mm": t_out,
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "auto_grid_from_frame": bool(auto_grid_from_frame),
        "grid_meta": grid_meta,
        "centers": centers,
        "seed": seed_report,
        "domain_meta": domain_meta,
        "runs": [],
    }

    write_domain_once = bool(write_domain)
    for one_mode in modes:
        entry = run_one_mode(
            mode=one_mode,
            domain=domain,
            domain_meta=domain_meta,
            seed_shape=seed_shape,
            centers_all=centers,
            L=L,
            out_dir=out_dir,
            tag=tag,
            fuzzy_mm=float(fuzzy_mm),
            write_domain_step=write_domain_once,
            skins=skins,
            # Custom domain STEP may not be prismatic / 4-fold — disable shortcuts.
            z_copy_stack=bool(z_copy_stack) and not bool(domain_step),
            rotate_4fold=bool(rotate_4fold) and not bool(domain_step),
        )
        write_domain_once = False
        manifest["runs"].append(entry)

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nManifest: {manifest_path}", flush=True)

    bad = [r for r in manifest["runs"] if not r.get("ok")]
    skin_warn = [
        r
        for r in manifest["runs"]
        if r.get("ok") and r.get("skin") and not r["skin"].get("skin_ok", True)
    ]
    if bad:
        print(f"[FAIL] {len(bad)} mode(s) failed", flush=True)
        return 1
    if skin_warn:
        print(
            f"[OK lattice] {len(skin_warn)} skin attachment(s) used compound/fallback; "
            "open *_intersect.step or *_intersect_skin.step in SW",
            flush=True,
        )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Cartesian trim-fill of square−cylinder frame with HuBai cells"
    )
    p.add_argument("--S", type=float, default=80.0, help="Outer square side [mm]")
    p.add_argument("--H", type=float, default=None, help="Frame height [mm]; default = S")
    p.add_argument("--R-hole", type=float, default=25.0, help="Inner hole radius [mm]")
    p.add_argument("--L", type=float, default=20.0, help="Unit cell edge [mm]")
    p.add_argument(
        "--nx",
        type=int,
        default=None,
        help="Override X count (default: auto from S/L)",
    )
    p.add_argument(
        "--ny",
        type=int,
        default=None,
        help="Override Y count (default: auto from S/L)",
    )
    p.add_argument(
        "--nz",
        type=int,
        default=None,
        help="Override Z count (default: auto from H/L)",
    )
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--Q", type=float, default=0.0)
    p.add_argument("--n-segments", type=int, default=12)
    p.add_argument(
        "--mode",
        choices=("intersect", "full_only", "both"),
        default="intersect",
        help="Cell gate: intersect (trim+skin), full_only, or both",
    )
    p.add_argument("--fuzzy-mm", type=float, default=0.02)
    p.add_argument(
        "--skin-mm",
        type=float,
        default=2.0,
        help="Default wall thickness for both skins [mm]; 0 disables (overridden by --inner/--outer-wall-mm)",
    )
    p.add_argument(
        "--inner-wall-mm",
        type=float,
        default=None,
        help="Inner cylinder liner thickness [mm]; default = --skin-mm",
    )
    p.add_argument(
        "--outer-wall-mm",
        type=float,
        default=None,
        help="Outer square frame wall thickness [mm]; default = --skin-mm",
    )
    p.add_argument("--out-dir", default="")
    p.add_argument("--seed-step", default="")
    p.add_argument(
        "--domain-step",
        default="",
        help="Optional arbitrary domain STEP (skips square−cylinder construction)",
    )
    p.add_argument(
        "--write-domain",
        action="store_true",
        default=True,
        help="Also write domain STEP once",
    )
    p.add_argument(
        "--manual-grid",
        action="store_true",
        help="Do not auto-derive nx/ny/nz from S/H/L (require --nx/--ny/--nz)",
    )
    p.add_argument(
        "--snap-s-to-grid",
        action="store_true",
        help="Snap outer side S to nx*L when S is not an integer multiple of L (H is never snapped)",
    )
    args = p.parse_args()
    auto = not bool(args.manual_grid)
    if args.manual_grid and (args.nx is None or args.ny is None or args.nz is None):
        p.error("--manual-grid requires --nx --ny --nz")
    return run_frame_trim_fill(
        S=float(args.S),
        H=None if args.H is None else float(args.H),
        R_hole=float(args.R_hole),
        L=float(args.L),
        nx=None if args.nx is None else int(args.nx),
        ny=None if args.ny is None else int(args.ny),
        nz=None if args.nz is None else int(args.nz),
        rod_d=float(args.rod_d),
        Af=float(args.Af),
        Q=float(args.Q),
        n_segments=int(args.n_segments),
        mode=str(args.mode),
        fuzzy_mm=float(args.fuzzy_mm),
        skin_mm=float(args.skin_mm),
        inner_wall_mm=None if args.inner_wall_mm is None else float(args.inner_wall_mm),
        outer_wall_mm=None if args.outer_wall_mm is None else float(args.outer_wall_mm),
        out_dir=str(args.out_dir),
        seed_step=str(args.seed_step),
        domain_step=str(args.domain_step),
        write_domain=bool(args.write_domain),
        auto_grid_from_frame=auto,
        snap_frame_to_grid=bool(args.snap_s_to_grid),
        fit_height_to_layers=False,
        fit_outer_to_grid=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
