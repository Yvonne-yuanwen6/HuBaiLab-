"""
Experiment pipeline: adaptive scheme-A fillet for BCC/SFBLS (isolated).

Does not modify ``run_param_batch_step_generate`` or paper_box defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

import numpy as np

from src.export.exp_node_transition.adaptive_fillet import (
    AdaptiveFilletConfig,
    AdaptiveNodeSpec,
    NodeClass,
    adaptive_r_blend_mm,
    bcc_array_shared_corner_nodes,
    filter_fillet_targets,
    plan_summary,
    plan_unitcell_interior_nodes,
    radius_ladder_mm,
)
from src.export.exp_node_transition.bcc_explicit_cores import (
    ExpNodeTransitionParams,
    build_exp_hub_fuse_solid,
    default_exp_out_dir,
    export_exp_bcc_zslab_2x2x1,
)
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    _collect_edges_near_nodes,
    _fuse_pipes_unitcell,
    _strut_radius,
    _try_fillet,
    apply_junction_fillets,
    export_exp_bcc_fillet_unitcell,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import (
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_readback_step,
    ocp_shape_topology,
    ocp_write_step,
    ocp_write_step_via_gmsh_brep_heal,
)


def _exp_write_stl(shape: Any, path: str, *, deflection_mm: float = 0.25) -> dict[str, Any]:
    """Exp-only STL for visual check when STEP solid roundtrip fails."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    BRepMesh_IncrementalMesh(shape, float(deflection_mm))
    ok = bool(StlAPI_Writer().Write(shape, os.path.abspath(path)))
    if not ok or not os.path.isfile(path) or os.path.getsize(path) < 100:
        raise RuntimeError(f"STL write failed: {path}")
    return {"stl_path": os.path.abspath(path), "stl_bytes": os.path.getsize(path)}


def _exp_soft_step_readback(path: str) -> dict[str, Any]:
    """Read STEP without requiring a solid (shared-fillet may demote to shell)."""
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    if reader.ReadFile(os.path.abspath(path)) != 1:
        raise RuntimeError(f"STEP read failed: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    stats = ocp_shape_topology(shape, count_faces=False, check_brep=False)
    stats["step_path"] = os.path.abspath(path)
    return stats


def _exp_write_step_prefer_ocp(
    shape: Any,
    path: str,
    *,
    mass_ref_mm3: float | None = None,
    also_stl: bool = True,
) -> dict[str, Any]:
    """
    Exp-only STEP write for filleted solids.

    Multi-corner MakeFillet on Q=1.5 arrays often yields BRepCheck-invalid solids
    that STEP stores as shells (volume preserved). Accept shell readback when mass
    matches; always write companion STL for visual verification.
    Does not change main-path batch export defaults.
    """
    mass_in = float(ocp_mass(shape))
    print(f"  [exp-export] OCP direct STEP → {path}", flush=True)
    ocp_write_step(shape, path)
    step_bytes = os.path.getsize(path) if os.path.isfile(path) else 0
    rb = _exp_soft_step_readback(path)
    rb["export_route"] = "ocp_direct_exp"
    rb["step_bytes"] = step_bytes
    rb["mass_inmem_mm3"] = mass_in
    n_solids = int(rb.get("solids") or 0)
    mass_rb = float(rb.get("mass_mm3") or 0.0)
    ref = float(mass_ref_mm3) if mass_ref_mm3 is not None else mass_in
    mass_ok = mass_rb > 0.5 * max(ref, 1.0) and abs(mass_rb - ref) / max(ref, 1.0) < 0.05
    if n_solids == 1:
        rb["step_ok"] = True
        rb["step_note"] = "solid_roundtrip"
    elif mass_ok and int(rb.get("shells") or 0) >= 1:
        rb["step_ok"] = True
        rb["step_note"] = (
            "shell_roundtrip_volume_ok: OCC fillet BRep invalid → STEP shell; "
            "use companion STL for visual check"
        )
        print(f"  [exp-export] STEP shell OK (volume~{mass_rb:.2f} mm3)", flush=True)
    else:
        rb["step_ok"] = False
        rb["step_note"] = f"bad readback solids={n_solids} mass={mass_rb}"
        raise RuntimeError(rb["step_note"])

    if also_stl:
        stl_path = os.path.splitext(path)[0] + ".stl"
        try:
            rb.update(_exp_write_stl(shape, stl_path))
            print(f"  [exp-export] STL → {stl_path}", flush=True)
        except Exception as exc:
            rb["stl_error"] = str(exc)
            print(f"  [exp-export] STL FAIL ({exc})", flush=True)
    return rb


def _fillet_params_from_adaptive(
    *,
    cell_size_mm: float,
    rod_d_mm: float,
    amplitude_mm: float,
    period_factor: float,
    n_segments: int,
    cfg: AdaptiveFilletConfig,
    r_blend_mm: float,
) -> ExpFilletParams:
    r = 0.5 * float(rod_d_mm)
    factor = float(r_blend_mm) / max(r, 1e-9)
    ladder = tuple(max(0.05, x / max(r, 1e-9)) for x in radius_ladder_mm(r_blend_mm, cfg))
    return ExpFilletParams(
        cell_size_mm=float(cell_size_mm),
        rod_d_mm=float(rod_d_mm),
        amplitude_mm=float(amplitude_mm),
        period_factor=float(period_factor),
        n_segments=int(n_segments),
        r_blend_factor=factor,
        edge_select_factor=float(cfg.edge_select_factor),
        fillet_centre=True,
        fillet_corners=False,
        array_fillet_shared_corners=True,
        r_blend_fallback_factors=ladder if ladder else (factor, 0.35, 0.25, 0.15),
    )


def build_unitcell_solid_for_fillet(
    *,
    cell_size_mm: float,
    rod_d_mm: float,
    amplitude_mm: float,
    period_factor: float,
    n_segments: int,
    cfg: AdaptiveFilletConfig,
) -> tuple[Any, dict[str, Any]]:
    """Build 1×1 solid without design spheres (plan A: bare pipe first).

    Hub is only used when ``cfg.q_gt0_hub_factor > 0`` *and* the bare ladder fails.
    Default hub factor is 0 (disabled).
    """
    fp = ExpFilletParams(
        cell_size_mm=cell_size_mm,
        rod_d_mm=rod_d_mm,
        amplitude_mm=amplitude_mm,
        period_factor=period_factor,
        n_segments=n_segments,
        fillet_centre=False,
        fillet_corners=False,
    )
    meta: dict[str, Any] = {"connectivity_assist": None, "bare_attempts": []}

    print("  [plan-A] bare pipe fuse ladder (no design sphere)...", flush=True)
    try:
        solid, mass, method, attempts = fuse_pipes_unitcell_bare_ladder(fp)
        meta.update(
            {
                "seed_method": method,
                "mass_mm3": mass,
                "bare_attempts": attempts,
                "hub_used": False,
            }
        )
        return solid, meta
    except Exception as bare_exc:
        meta["bare_attempts"] = getattr(bare_exc, "attempts", None)
        meta["bare_error"] = str(bare_exc)
        print(f"  [plan-A] bare ladder FAILED: {bare_exc}", flush=True)

    hub_f = float(cfg.q_gt0_hub_factor)
    if hub_f <= 1e-12:
        raise RuntimeError(
            "bare pipe fuse failed and hub is disabled (q_gt0_hub_factor=0). "
            f"bare_error={meta.get('bare_error')}"
        )

    print(
        f"  [plan-A] hub fallback R/R_strut={hub_f:g} (explicit assist only)...",
        flush=True,
    )
    hub = ExpNodeTransitionParams(
        cell_size_mm=cell_size_mm,
        rod_d_mm=rod_d_mm,
        amplitude_mm=amplitude_mm,
        period_factor=period_factor,
        n_segments=n_segments,
        r_core_centre_factor=hub_f,
        enable_centre_core=True,
        enable_corner_cores=False,
        l_shrink_centre_mm=0.0,
        l_shrink_corner_mm=0.0,
        fuse_fuzzy_mm=0.05,
        glue="off",
    )
    solid, hub_rep = build_exp_hub_fuse_solid(hub, force_centre_hub=True)
    meta.update(
        {
            "seed_method": "exp_hub_assist_q_gt0_fallback",
            "hub_used": True,
            "connectivity_assist": {
                "type": "centre_hub",
                "r_factor": hub_f,
                "note": (
                    "Fallback only after bare ladder failed. "
                    "Not the desired node-smoothing geometry."
                ),
            },
            "hub_report": {
                k: hub_rep[k]
                for k in (
                    "merged_mass_mm3",
                    "r_core_centre_mm",
                    "pipe_cut_sum_mm3",
                    "topology",
                )
                if k in hub_rep
            },
            "mass_mm3": hub_rep.get("merged_mass_mm3"),
        }
    )
    return solid, meta


def fillet_nodes_with_ladder(
    shape: Any,
    specs: list[AdaptiveNodeSpec],
    cfg: AdaptiveFilletConfig,
    *,
    label: str,
) -> tuple[Any, dict[str, Any]]:
    """Fillet all given nodes; per-node adaptive r with fallback ladder."""
    # Use max adaptive r among nodes as starting Add radius, but select edges
    # near all nodes. Ladder tries global scales of the max r0.
    if not specs:
        raise ValueError("no nodes to fillet")
    r0s = [adaptive_r_blend_mm(s, cfg) for s in specs]
    r0 = float(max(r0s)) if r0s else 0.0
    if r0 <= 1e-9:
        raise RuntimeError(f"{label}: all target r_blend are zero (nothing to fillet)")
    node_pts = [np.array(s.xyz_mm, dtype=float) for s in specs]
    select_r = float(cfg.edge_select_factor) * float(min(s.r_min_strut_mm for s in specs))
    edges = _collect_edges_near_nodes(shape, node_pts=node_pts, select_radius_mm=select_r)
    print(
        f"  [adaptive:{label}] nodes={len(specs)} edges={len(edges)} "
        f"r0_max={r0:.3f} select_r={select_r:.3f}",
        flush=True,
    )
    if not edges:
        raise RuntimeError(f"{label}: no edges near planned nodes")

    errors: list[str] = []
    for rad in radius_ladder_mm(r0, cfg):
        try:
            out = _try_fillet(shape, edges, rad)
            topo = ocp_shape_topology(out)
            if int(topo.get("solids") or 0) != 1:
                raise RuntimeError(f"solids={topo.get('solids')}")
            # Prefer blends that add material; skip near-zero / negative mass deltas
            # unless this is the last ladder rung (handled below by accepting).
            dmass = float(ocp_mass(out)) - float(ocp_mass(shape))
            rep = {
                "label": label,
                "r_blend_mm_used": rad,
                "r0_max_mm": r0,
                "n_edges": len(edges),
                "n_nodes": len(specs),
                "mass_mm3": ocp_mass(out),
                "mass_delta_mm3": dmass,
                "topology": topo,
                "node_plan": plan_summary(specs, cfg),
            }
            if dmass < -0.05:
                raise RuntimeError(f"mass_delta={dmass:.3f} (fillet should not remove mass)")
            print(
                f"  [adaptive:{label}] OK r={rad:.3f} mass={rep['mass_mm3']:.2f} "
                f"dmass={dmass:+.3f} brep_valid={topo.get('brep_valid')}",
                flush=True,
            )
            return out, rep
        except Exception as exc:
            errors.append(f"r={rad:g}: {exc}")
            print(f"  [adaptive:{label}] fail r={rad:g}: {exc}", flush=True)
    raise RuntimeError(f"{label}: fillet ladder failed: {errors}")


def export_adaptive_fillet_case(
    *,
    period_factor: float,
    amplitude_mm: float = 2.0,
    rod_d_mm: float = 2.0,
    cell_size_mm: float = 20.0,
    n_segments: int = 32,
    nx: int = 2,
    ny: int = 2,
    nz: int = 1,
    cfg: AdaptiveFilletConfig | None = None,
    out_dir: str | None = None,
    force: bool = False,
    unitcell_only: bool = False,
) -> dict[str, Any]:
    """
    Adaptive A pipeline (exp only):
      1) bare 1×1 (no hub) → optional interior fillet (off for Q>0 by default)
      2) unless unitcell_only: 2×2×1 fuse → shared-corner fillet
    """
    import shutil

    cfg = cfg or AdaptiveFilletConfig()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(period_factor)
    q_tag = str(q).replace(".", "p")
    if abs(q - round(q)) < 1e-9:
        q_tag = str(int(round(q)))
    slug = (
        f"exp_adaptA_af{int(round(amplitude_mm))}q{q_tag}"
        f"_L{int(round(cell_size_mm))}_d{str(rod_d_mm).replace('.', 'p')}"
        f"_k{str(cfg.k_blend).replace('.', 'p')}"
    )
    if float(cfg.q_gt0_hub_factor) <= 1e-12:
        slug += "_noHub"
    else:
        slug += f"_hub{str(cfg.q_gt0_hub_factor).replace('.', 'p')}"
    if abs(q) > 1e-12 and not cfg.fillet_q_gt0_interior:
        slug += "_bareCentre"

    r_strut = 0.5 * float(rod_d_mm)
    interior_plan = plan_unitcell_interior_nodes(
        cell_size_mm=cell_size_mm,
        strut_radius_mm=r_strut,
        period_factor=q,
        cfg=cfg,
    )
    fillet_targets = filter_fillet_targets(
        interior_plan, period_factor=q, cfg=cfg
    )

    step_1x1 = os.path.join(out_dir, f"{slug}_1x1_clean.step")
    pre_1x1 = os.path.join(out_dir, f"{slug}_1x1_pre_fillet.step")
    step_1x1_filleted = os.path.join(out_dir, f"{slug}_1x1_interiorFillet.step")
    report: dict[str, Any] = {
        "experiment": "adaptive_scheme_a_fillet",
        "slug": slug,
        "main_path_untouched": True,
        "config": asdict(cfg),
        "interior_plan": plan_summary(interior_plan, cfg),
        "fillet_targets": plan_summary(fillet_targets, cfg),
        "q15_topology_note": (
            "Q>0 centre = Z-spine + ±Z 4-rod clusters (~12°); "
            "not BCC 8-way star. Default: no large centre fillet."
            if abs(q) > 1e-12
            else None
        ),
        "runs": {},
    }

    print(f"\n=== ADAPTIVE-A 1x1 Q={q:g} → {step_1x1} ===", flush=True)
    if force or not os.path.isfile(step_1x1):
        solid, seed_meta = build_unitcell_solid_for_fillet(
            cell_size_mm=cell_size_mm,
            rod_d_mm=rod_d_mm,
            amplitude_mm=amplitude_mm,
            period_factor=period_factor,
            n_segments=n_segments,
            cfg=cfg,
        )
        mass0 = ocp_mass(solid)
        try:
            step_pre_rb = _exp_write_step_prefer_ocp(
                ocp_heal_fused_solid(solid),
                pre_1x1,
                mass_ref_mm3=mass0,
                also_stl=True,
            )
        except Exception:
            step_pre_rb = ocp_write_step_via_gmsh_brep_heal(
                ocp_heal_fused_solid(solid), pre_1x1
            )

        if fillet_targets:
            solid_for_fillet = ocp_read_step_shape(pre_1x1)
            filleted, frep = fillet_nodes_with_ladder(
                solid_for_fillet, fillet_targets, cfg, label="interior_targets"
            )
            step_rb = _exp_write_step_prefer_ocp(
                filleted,
                step_1x1_filleted,
                mass_ref_mm3=ocp_mass(filleted),
                also_stl=True,
            )
            shutil.copy2(step_1x1_filleted, step_1x1)
            stl_src = step_1x1_filleted.replace(".step", ".stl")
            if os.path.isfile(stl_src):
                shutil.copy2(stl_src, step_1x1.replace(".step", ".stl"))
            report["runs"]["unitcell"] = {
                "step_path": step_1x1,
                "pre_fillet_step": pre_1x1,
                "filleted_step": step_1x1_filleted,
                "seed_meta": seed_meta,
                "mass_pre_mm3": mass0,
                "fillet": frep,
                "mass_after_mm3": ocp_mass(filleted),
                "step_readback": step_rb,
                "pre_readback": step_pre_rb,
            }
        else:
            shutil.copy2(pre_1x1, step_1x1)
            pre_stl = pre_1x1.replace(".step", ".stl")
            if os.path.isfile(pre_stl):
                shutil.copy2(pre_stl, step_1x1.replace(".step", ".stl"))
            print(
                "  [plan] skipped interior fillet "
                f"(fillet_q_gt0_interior={cfg.fillet_q_gt0_interior}; "
                f"targets={len(fillet_targets)})",
                flush=True,
            )
            report["runs"]["unitcell"] = {
                "step_path": step_1x1,
                "pre_fillet_step": pre_1x1,
                "seed_meta": seed_meta,
                "mass_pre_mm3": mass0,
                "fillet": {
                    "skipped": True,
                    "reason": "q_gt0_bare_centre_default",
                    "planned_nodes": plan_summary(interior_plan, cfg),
                    "fillet_targets": [],
                },
                "mass_after_mm3": mass0,
                "step_readback": step_pre_rb,
            }
    else:
        print(f"  [skip] {step_1x1}", flush=True)
        report["runs"]["unitcell"] = {"step_path": step_1x1, "skipped": True}

    if unitcell_only:
        man = os.path.join(out_dir, f"{slug}_manifest.json")
        with open(man, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        report["manifest_path"] = man
        print(f"\n=== ADAPTIVE-A unitcell-only summary → {man} ===", flush=True)
        return report

    if nz != 1:
        raise ValueError("adaptive array smoke supports nz=1 only for now")
    if nx != 2 or ny != 2:
        print(f"  [WARN] zslab helper is 2x2; requested {nx}x{ny}x{nz}", flush=True)

    shared = bcc_array_shared_corner_nodes(
        cell_size_mm=cell_size_mm,
        strut_radius_mm=r_strut,
        nx=nx,
        ny=ny,
        nz=nz,
        min_multiplicity=cfg.min_shared_multiplicity,
    )
    report["shared_plan"] = plan_summary(shared, cfg)

    step_arr = os.path.join(out_dir, f"{slug}_2x2x1_sharedFillet.step")
    pre_arr = os.path.join(out_dir, f"{slug}_2x2x1_pre_sharedFillet.step")
    print(f"\n=== ADAPTIVE-A array fuse+shared fillet → {step_arr} ===", flush=True)

    if force or not os.path.isfile(step_arr):
        fuse_rep = export_exp_bcc_zslab_2x2x1(
            report["runs"]["unitcell"]["step_path"],
            pre_arr,
            cell_size_mm=cell_size_mm,
            force=force,
        )
        shape = ocp_read_step_shape(pre_arr)
        mass_pre = ocp_mass(shape)
        filleted, frep = fillet_nodes_with_ladder(
            shape, shared, cfg, label="periodic_shared"
        )
        step_rb = _exp_write_step_prefer_ocp(
            filleted, step_arr, mass_ref_mm3=ocp_mass(filleted), also_stl=True
        )
        report["runs"]["array"] = {
            "step_path": step_arr,
            "stl_path": step_rb.get("stl_path"),
            "pre_shared_fillet_step": pre_arr,
            "fuse_report": fuse_rep,
            "mass_pre_mm3": mass_pre,
            "fillet": frep,
            "mass_after_mm3": ocp_mass(filleted),
            "mass_delta_mm3": ocp_mass(filleted) - mass_pre,
            "step_readback": step_rb,
        }
    else:
        report["runs"]["array"] = {"step_path": step_arr, "skipped": True}

    man = os.path.join(out_dir, f"{slug}_manifest.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    report["manifest_path"] = man
    print(f"\n=== ADAPTIVE-A summary → {man} ===", flush=True)
    return report
