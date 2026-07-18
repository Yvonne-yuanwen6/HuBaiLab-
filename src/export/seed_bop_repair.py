"""Repair a visually-OK unitcell STEP so OpenCASCADE Boolean can fuse neighbors.

Some OCP GlueShift seeds import fine in SolidWorks / report vol=1, but
``BRepAlgoAPI_Fuse(seed, translate(seed, L))`` returns mass≈0. gmsh OCC
healShapes / BREP roundtrip often produces a BOP-friendly solid.

Gate: adjacent-cell fuse must keep ≥95% of 2× seed mass.
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from src.export.ocp_unitcell_fuse import (
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
    ocp_write_step_via_gmsh_brep_heal,
)
from src.export.step_heal_for_cae import HEAL_PRESETS, heal_step_once


def probe_adjacent_cell_fuse(
    seed_step: str,
    *,
    cell_size_mm: float = 20.0,
    glue: str = "off",
    fuzzy_mm: float = 0.05,
    min_mass_ratio: float = 0.95,
) -> dict[str, Any]:
    """Fuse seed with a +X neighbour; report whether Boolean keeps mass."""
    from src.export.ocp_paper_box_array_fuse import (
        load_ocp_unitcell_shape,
        ocp_translate_shape,
    )

    seed_step = os.path.abspath(seed_step)
    shape, seed_mass = load_ocp_unitcell_shape(seed_step, cell_size=float(cell_size_mm))
    neighbour = ocp_translate_shape(shape, float(cell_size_mm), 0.0, 0.0)
    try:
        fused = ocp_fuse_pair(
            shape,
            neighbour,
            glue=glue,  # type: ignore[arg-type]
            fuzzy_mm=float(fuzzy_mm),
            simplify=False,
            label="seed-bop-gate",
        )
        fused_mass = ocp_mass(fused)
        topo = ocp_shape_topology(fused, count_faces=False, check_brep=False)
        expected = 2.0 * float(seed_mass)
        ratio = fused_mass / expected if expected > 1e-9 else 0.0
        ok = ratio >= float(min_mass_ratio) and int(topo.get("solids") or 0) >= 1
        return {
            "ok": bool(ok),
            "seed_mass_mm3": float(seed_mass),
            "fused_mass_mm3": float(fused_mass),
            "expected_mm3": float(expected),
            "mass_ratio": float(ratio),
            "solids": int(topo.get("solids") or 0),
            "glue": glue,
            "fuzzy_mm": float(fuzzy_mm),
        }
    except Exception as exc:
        return {
            "ok": False,
            "seed_mass_mm3": float(seed_mass),
            "error": str(exc),
            "glue": glue,
            "fuzzy_mm": float(fuzzy_mm),
        }


def _gate_seed(path: str, *, cell_size_mm: float) -> dict[str, Any]:
    """Try a few glue/fuzzy combos for the 2-cell gate."""
    last: dict[str, Any] = {"ok": False}
    for glue, fz in (
        ("off", 0.05),
        ("shift", 0.05),
        ("off", 0.1),
        ("shift", 0.1),
        ("off", 0.2),
    ):
        last = probe_adjacent_cell_fuse(
            path,
            cell_size_mm=cell_size_mm,
            glue=glue,
            fuzzy_mm=fz,
        )
        if last.get("ok"):
            return last
    return last


def repair_seed_step_for_array_bop(
    in_step: str,
    out_step: str,
    *,
    cell_size_mm: float = 20.0,
    force: bool = False,
) -> dict[str, Any]:
    """
    Produce ``out_step`` that passes the adjacent-cell Boolean gate.

    Strategy order:
      1. already-good (gate on ``in_step`` / existing ``out_step``)
      2. gmsh healShapes presets (``step_heal_for_cae``)
      3. OCP load → ShapeFix heal → gmsh BREP STEP write
      4. OCP load → direct STEP rewrite
    """
    in_step = os.path.abspath(in_step)
    out_step = os.path.abspath(out_step)
    if not os.path.isfile(in_step):
        raise FileNotFoundError(in_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    report: dict[str, Any] = {
        "in_step": in_step,
        "out_step": out_step,
        "attempts": [],
    }

    if (not force) and os.path.isfile(out_step) and os.path.getsize(out_step) > 1024:
        gate = _gate_seed(out_step, cell_size_mm=cell_size_mm)
        report["attempts"].append({"label": "reuse_out", "gate": gate})
        if gate.get("ok"):
            report["ok"] = True
            report["method"] = "reuse_out"
            report["gate"] = gate
            return report

    gate0 = _gate_seed(in_step, cell_size_mm=cell_size_mm)
    report["attempts"].append({"label": "raw_in", "gate": gate0})
    if gate0.get("ok"):
        if os.path.abspath(in_step) != out_step:
            shutil.copy2(in_step, out_step)
        report["ok"] = True
        report["method"] = "raw_in"
        report["gate"] = gate0
        return report

    work = out_step + ".__heal_try__.step"
    for preset in HEAL_PRESETS:
        label = f"gmsh_heal_{preset['label']}"
        print(f"  seed-bop-repair: try {label}...", flush=True)
        try:
            if os.path.isfile(work):
                os.remove(work)
            heal_step_once(
                in_step,
                work,
                distance_tol=float(preset["distance_tol"]),
                fix_small=bool(preset["fix_small"]),
            )
            gate = _gate_seed(work, cell_size_mm=cell_size_mm)
            report["attempts"].append({"label": label, "gate": gate})
            if gate.get("ok"):
                os.replace(work, out_step)
                report["ok"] = True
                report["method"] = label
                report["gate"] = gate
                return report
        except Exception as exc:
            report["attempts"].append({"label": label, "error": str(exc)})
            print(f"    FAIL {label}: {exc}", flush=True)

    # OCP reload + ShapeFix + BREP/gmsh write
    try:
        from src.export.ocp_paper_box_array_fuse import load_ocp_unitcell_shape

        print("  seed-bop-repair: try ocp_heal_gmsh_brep...", flush=True)
        shape, _ = load_ocp_unitcell_shape(in_step, cell_size=float(cell_size_mm))
        shape = ocp_heal_fused_solid(shape)
        if os.path.isfile(work):
            os.remove(work)
        ocp_write_step_via_gmsh_brep_heal(shape, work, fast_readback=False)
        gate = _gate_seed(work, cell_size_mm=cell_size_mm)
        report["attempts"].append({"label": "ocp_heal_gmsh_brep", "gate": gate})
        if gate.get("ok"):
            os.replace(work, out_step)
            report["ok"] = True
            report["method"] = "ocp_heal_gmsh_brep"
            report["gate"] = gate
            return report
    except Exception as exc:
        report["attempts"].append({"label": "ocp_heal_gmsh_brep", "error": str(exc)})
        print(f"    FAIL ocp_heal_gmsh_brep: {exc}", flush=True)

    try:
        from src.export.ocp_paper_box_array_fuse import load_ocp_unitcell_shape

        print("  seed-bop-repair: try ocp_direct_rewrite...", flush=True)
        shape, _ = load_ocp_unitcell_shape(in_step, cell_size=float(cell_size_mm))
        shape = ocp_heal_fused_solid(shape)
        if os.path.isfile(work):
            os.remove(work)
        ocp_write_step(shape, work)
        gate = _gate_seed(work, cell_size_mm=cell_size_mm)
        report["attempts"].append({"label": "ocp_direct_rewrite", "gate": gate})
        if gate.get("ok"):
            os.replace(work, out_step)
            report["ok"] = True
            report["method"] = "ocp_direct_rewrite"
            report["gate"] = gate
            return report
    except Exception as exc:
        report["attempts"].append({"label": "ocp_direct_rewrite", "error": str(exc)})
        print(f"    FAIL ocp_direct_rewrite: {exc}", flush=True)

    if os.path.isfile(work):
        try:
            os.remove(work)
        except OSError:
            pass
    report["ok"] = False
    report["error"] = "all seed BOP-repair routes failed adjacent-cell gate"
    return report
