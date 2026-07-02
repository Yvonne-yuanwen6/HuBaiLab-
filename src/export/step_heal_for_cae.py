"""Gmsh OCC heal for verified STEP before Abaqus CAE tet mesh."""

from __future__ import annotations

import os
from typing import Any

from src.export.sw_parasolid import measure_step_occ_stats

HEAL_PRESETS: tuple[dict[str, Any], ...] = (
    {"label": "tol0.05_fixsmall", "distance_tol": 0.05, "fix_small": True},
    {"label": "tol0.01_fixsmall", "distance_tol": 0.01, "fix_small": True},
    {"label": "tol0.10_fixsmall", "distance_tol": 0.10, "fix_small": True},
    {"label": "tol0.05", "distance_tol": 0.05, "fix_small": False},
    {"label": "tol1e-5", "distance_tol": 1e-5, "fix_small": False},
)


def heal_step_once(
    in_step: str,
    out_step: str,
    *,
    distance_tol: float = 0.05,
    fix_small: bool = True,
) -> dict[str, Any]:
    import gmsh

    in_step = os.path.abspath(in_step)
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    before = measure_step_occ_stats(in_step)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("heal_cae")
        gmsh.model.occ.importShapes(in_step)
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise RuntimeError(f"no 3D volume in {in_step}")

        gmsh.model.occ.healShapes(
            tolerance=float(distance_tol),
            fixDegenerated=True,
            fixSmallEdges=bool(fix_small),
            fixSmallFaces=bool(fix_small),
            sewFaces=True,
            makeSolids=True,
        )
        gmsh.model.occ.synchronize()
        gmsh.model.occ.removeAllDuplicates()
        gmsh.model.occ.synchronize()

        vols = gmsh.model.getEntities(3)
        if len(vols) != 1:
            raise RuntimeError(f"expected 1 volume after heal, got {len(vols)}")

        gmsh.write(out_step)
    finally:
        gmsh.finalize()

    after = measure_step_occ_stats(out_step)
    ref_mass = float(before.get("mass_mm3") or 0.0)
    out_mass = float(after.get("mass_mm3") or 0.0)
    mass_ratio = (out_mass / ref_mass) if ref_mass > 1e-9 else 1.0
    return {
        "before": before,
        "after": after,
        "out_step": out_step,
        "mass_ratio": mass_ratio,
        "distance_tol": float(distance_tol),
        "fix_small": bool(fix_small),
    }


def heal_step_for_cae(
    in_step: str,
    out_dir: str,
    *,
    basename: str = "healed",
    presets: tuple[dict[str, Any], ...] | None = None,
    mass_ratio_min: float = 0.95,
    mass_ratio_max: float = 1.05,
) -> tuple[str, dict[str, Any]]:
    """
    Try heal presets; return (best_out_step, report).
    Picks the last preset that keeps a single volume and mass near the input.
    """
    presets = presets or HEAL_PRESETS
    in_step = os.path.abspath(in_step)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    before = measure_step_occ_stats(in_step)
    best_path = in_step
    best_report: dict[str, Any] = {
        "source_step": in_step,
        "preset": "none",
        "before": before,
        "after": before,
        "attempts": [],
    }

    for preset in presets:
        label = str(preset["label"])
        out_step = os.path.join(out_dir, f"{basename}_{label}.step")
        try:
            rep = heal_step_once(
                in_step,
                out_step,
                distance_tol=float(preset["distance_tol"]),
                fix_small=bool(preset.get("fix_small", True)),
            )
            rep["preset"] = label
            best_report["attempts"].append(rep)
            mr = float(rep["mass_ratio"])
            if mass_ratio_min <= mr <= mass_ratio_max:
                best_path = out_step
                best_report["preset"] = label
                best_report["after"] = rep["after"]
                best_report["mass_ratio"] = mr
                print(
                    f"  heal OK preset={label} mass_ratio={mr:.4f} "
                    f"faces={rep['after'].get('face_count')} -> {out_step}",
                    flush=True,
                )
            else:
                print(
                    f"  heal skip preset={label} mass_ratio={mr:.4f} out of range",
                    flush=True,
                )
        except Exception as exc:
            print(f"  heal FAIL preset={label}: {exc}", flush=True)
            best_report["attempts"].append({"preset": label, "error": str(exc)})

    best_report["healed_step"] = best_path
    best_report["used_heal"] = best_path != in_step
    return best_path, best_report
