"""
Angle-driven adaptive STEP export (experiment).

Pipeline (STEP-first, stable):
  1. Read-only angle detect + node classify
  2. Always fuse bare pipes → solid STEP (ladder recipes)
  3. Attach node-level Rf suggestions in manifest (blend executor later)

Does not touch batch / paper_box defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.StlAPI import StlAPI_Writer

from src.export.exp_node_transition.angle_node_classify import (
    AngleClassifyParams,
    export_angle_classify_case,
    run_angle_classify,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_unitcell_fuse import (
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)


def _write_stl(shape: Any, path: str, *, deflection_mm: float = 0.25) -> None:
    BRepMesh_IncrementalMesh(shape, float(deflection_mm))
    ok = bool(StlAPI_Writer().Write(shape, os.path.abspath(path)))
    if not ok or not os.path.isfile(path) or os.path.getsize(path) < 100:
        raise RuntimeError(f"STL write failed: {path}")


def export_adaptive_angle_step(
    params: AngleClassifyParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
    write_markers: bool = True,
    write_stl: bool = True,
) -> dict[str, Any]:
    """
    Stable STEP deliverable + angle/class report.

    Returns a dict with paths, topology, masses, and per-node Rf table.
    """
    params = params or AngleClassifyParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = str(q).replace(".", "p")
    slug = (
        f"exp_adaptAngle_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_1x1"
    )
    step_path = os.path.join(out_dir, f"{slug}.step")
    stl_path = os.path.join(out_dir, f"{slug}.stl")
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")

    if (
        not force
        and os.path.isfile(step_path)
        and os.path.getsize(step_path) > 1000
        and os.path.isfile(man_path)
    ):
        with open(man_path, encoding="utf-8") as f:
            cached = json.load(f)
        print(f"  [adaptAngle] reuse {step_path}", flush=True)
        return cached

    # --- 1) classify + markers STL (one SW window) ---
    classify_rep = export_angle_classify_case(
        params, out_dir=out_dir, write_markers=write_markers
    )
    tangents, pairs, nodes = run_angle_classify(params)

    # --- 2) bare fuse (must succeed for STEP) ---
    fp = ExpFilletParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=params.period_factor,
        n_segments=params.n_segments,
    )
    print("  [adaptAngle] bare fuse ...", flush=True)
    shape, mass, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    topo = ocp_shape_topology(shape)
    if int(topo.get("solids") or 0) != 1 or mass <= 0.0:
        raise RuntimeError(f"bare fuse not a solid: topo={topo} mass={mass}")

    ocp_write_step(shape, step_path)
    if write_stl:
        try:
            _write_stl(shape, stl_path)
        except Exception as exc:
            print(f"  [adaptAngle] STL warn: {exc}", flush=True)
            stl_path = ""

    # --- 3) node-level Rf policy table ---
    policy: list[dict[str, Any]] = []
    for n in nodes:
        policy.append(
            {
                "node_id": n.node_id,
                "node_class": n.node_class,
                "xyz_mm": list(n.xyz_mm),
                "valence": n.valence,
                "theta_min_deg": n.theta_min_deg,
                "theta_mean_deg": n.theta_mean_deg,
                "r_blend_mm": n.r_blend_suggest_mm,
                "skip_fillet": n.skip_fillet,
                "blend_action": (
                    "skip"
                    if n.skip_fillet
                    else "pending_executor"
                ),
                "notes": n.notes,
            }
        )

    manifest: dict[str, Any] = {
        "experiment": "adaptive_angle_step",
        "note": (
            "STEP = bare pipe fuse (stable, 1 solid, one SW window). "
            "markers = STL only (one window). "
            "Never open old *_markers.step (assembly / many windows)."
        ),
        "params": asdict(params),
        "step_path": os.path.abspath(step_path),
        "stl_path": os.path.abspath(stl_path) if stl_path else None,
        "markers_stl": classify_rep.marker_step,
        "marker_step": None,
        "classify_report": classify_rep.json_path,
        "fuse": {
            "method": fuse_tag,
            "mass_mm3": float(mass),
            "topology": topo,
            "attempts": fuse_attempts,
        },
        "summary": classify_rep.summary,
        "node_policy": policy,
        "n_pair_angles": len(pairs),
        "n_struts": len(tangents),
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n=== ADAPT ANGLE STEP Q={q:g} ===", flush=True)
    print(f"  STEP: {step_path}  mass={mass:.3f}  fuse={fuse_tag}", flush=True)
    if classify_rep.marker_step:
        print(f"  markers STL (1 window): {classify_rep.marker_step}", flush=True)
    print(f"  policy nodes={len(policy)}", flush=True)
    for p in policy:
        print(
            f"    {p['node_id']}: {p['node_class']} "
            f"θ_min={p['theta_min_deg']:.1f}° Rf={p['r_blend_mm']:.3f} "
            f"action={p['blend_action']}",
            flush=True,
        )
    print(f"  manifest: {man_path}", flush=True)
    return manifest
