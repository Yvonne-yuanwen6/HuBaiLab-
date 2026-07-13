"""Build and solve a 3D solid cantilever eigenfrequency model (MPh workflow smoke test)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jpype

from src.comsol.eigen_extract import extract_eigen_rows, write_eigen_csv
from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.mph_builder import _ensure_comsol_env, _import_mph
from src.comsol.runner import ComsolBatchRequest, run_batch
from src.comsol.validation.channel_beam_reference import (
    CHANNEL_BEAM_OFFICIAL_MODES,
    CantileverSolidSpec,
    analytical_bending_hz,
    reference_bending_modes,
)
from src.paths import COMSOL_JOBS_ROOT, ensure_output_dirs


SLUG = "comsol_validate_channel_beam_solid"


def _box_boundary_selection(
    comp: Any,
    tag: str,
    *,
    x_mm: float,
    half_y_mm: float,
    half_z_mm: float,
    band_mm: float = 0.05,
) -> None:
    tags = [str(t) for t in comp.selection().tags()]
    if tag in tags:
        comp.selection().remove(tag)
    comp.selection().create(tag, "Box")
    sel = comp.selection(tag)
    sel.set("entitydim", jpype.JInt(2))
    sel.set("xmin", f"{x_mm - band_mm}[mm]")
    sel.set("xmax", f"{x_mm + band_mm}[mm]")
    sel.set("ymin", f"{-half_y_mm}[mm]")
    sel.set("ymax", f"{half_y_mm}[mm]")
    sel.set("zmin", f"{-half_z_mm}[mm]")
    sel.set("zmax", f"{half_z_mm}[mm]")
    try:
        sel.set("condition", "allvertices")
    except Exception:
        pass


def build_solid_cantilever_mph(
    spec: CantileverSolidSpec,
    *,
    out_mph: Path,
    comsol_bin: str | None = None,
    cores: int = 2,
    mesh_mm: float = 5.0,
    n_modes: int = 8,
) -> Path:
    """Create .mph: Solid Mechanics + Eigenfrequency on a fixed-free rectangular beam."""
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)

    out_mph = Path(out_mph).resolve()
    out_mph.parent.mkdir(parents=True, exist_ok=True)

    print(f"  Validation model: solid cantilever L={spec.length_mm:g} mm", flush=True)
    client = mph.start(cores=cores)
    model = client.create(SLUG)
    java = model.java

    java.component().create("comp1", True)
    comp = java.component("comp1")
    comp.geom().create("geom1", 3)
    geom = comp.geom("geom1")
    geom.lengthUnit("mm")

    blk = geom.feature().create("blk1", "Block")
    blk.set(
        "size",
        [f"{spec.length_mm}[mm]", f"{spec.width_mm}[mm]", f"{spec.height_mm}[mm]"],
    )
    blk.set(
        "pos",
        [
            "0[mm]",
            f"{-0.5 * spec.width_mm}[mm]",
            f"{-0.5 * spec.height_mm}[mm]",
        ],
    )
    blk.set("base", "corner")
    geom.run()

    comp.material().create("mat1", "Common")
    mat = comp.material("mat1")
    mat.selection().all()
    mat.propertyGroup("def").set("youngsmodulus", f"{spec.youngs_pa}[Pa]")
    mat.propertyGroup("def").set("poissonsratio", str(spec.poisson))
    mat.propertyGroup("def").set("density", f"{spec.density_kg_m3}[kg/m^3]")

    comp.physics().create("solid", "SolidMechanics", "geom1")
    solid = comp.physics("solid")

    _box_boundary_selection(
        comp,
        "sel_fixed",
        x_mm=0.0,
        half_y_mm=0.5 * spec.width_mm,
        half_z_mm=0.5 * spec.height_mm,
    )
    fix = solid.create("fix1", "Fixed", jpype.JInt(2))
    fix.selection().named("sel_fixed")

    comp.common().create("mpf1", "ParticipationFactors")

    java.study().create("std1")
    eigen = java.study("std1").create("eig1", "Eigenfrequency")
    eigen.set("neigs", str(n_modes))
    eigen.set("eigwhich", "lm")
    try:
        eigen.set("shiftactive", "on")
        eigen.set("shift", "10[Hz]")
    except Exception:
        pass

    mesh = comp.mesh().create("mesh1", "geom1")
    mesh.create("size1", "Size").set("hmax", f"{mesh_mm}[mm]")
    mesh.create("ftet1", "FreeTet")
    mesh.run()

    model.save(out_mph)
    client.remove(model)
    print(f"  Saved validation .mph: {out_mph}", flush=True)
    return out_mph


def solve_and_extract(
    mph_path: Path,
    *,
    comsol_bin: str | None = None,
    cores: int = 2,
    use_batch: bool = True,
    np_batch: int = 2,
) -> tuple[Path, list[dict]]:
    """Solve eigen study (batch or in-process) and extract frequency rows."""
    solved = mph_path.with_name(f"{mph_path.stem}_solved.mph")

    if use_batch:
        request = ComsolBatchRequest(
            slug=SLUG,
            input_file=mph_path,
            output_file=solved,
            study="std1",
            np=np_batch,
        )
        run_batch(request, comsol_bin=comsol_bin, background=False)
    else:
        mph = _import_mph()
        _ensure_comsol_env(comsol_bin)
        client = mph.start(cores=cores)
        model = client.load(str(mph_path))
        # MPh model.solve() can fail to resolve study tags on some installs; Java API is reliable.
        model.java.study("std1").run()
        model.save(solved)
        client.remove(model)

    settings = HuBaiComsolSettings(
        excitation_axis="z",
        n_eigenmodes=20,
        run_eigen=True,
        run_frequency=False,
    )
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)
    client = mph.start(cores=1)
    model = client.load(str(solved))
    rows = extract_eigen_rows(model, model.java, settings, mpf_tag="mpf1")
    client.remove(model)
    return solved, rows


def compare_to_reference(
    rows: list[dict],
    spec: CantileverSolidSpec,
    *,
    rtol: float = 0.08,
) -> dict:
    """Compare computed eigenfrequencies to Channel Beam and rectangular-beam theory."""
    freqs = sorted(
        [abs(float(r["frequency_Hz"])) for r in rows if abs(float(r["frequency_Hz"])) > 1.0]
    )
    official = CHANNEL_BEAM_OFFICIAL_MODES
    official_f1 = float(official[0]["comsol_Hz"])
    analytical_f1 = analytical_bending_hz(spec, mode_index=0)

    f1_computed = freqs[0] if freqs else None
    err_vs_official = (
        abs(f1_computed - official_f1) / official_f1 if f1_computed is not None else None
    )
    err_vs_analytical = (
        abs(f1_computed - analytical_f1) / analytical_f1 if f1_computed is not None else None
    )

    comparisons: list[dict] = []
    for i, off in enumerate(official[:5]):
        target = float(off["comsol_Hz"])
        if not freqs:
            best = None
            err = None
        else:
            best = min(freqs, key=lambda f: abs(f - target))
            err = abs(best - target) / target if target else None
        comparisons.append(
            {
                "mode": off["mode"],
                "type": off["type"],
                "official_comsol_Hz": target,
                "official_analytical_Hz": float(off["analytical_Hz"]),
                "closest_computed_Hz": best,
                "rel_error_vs_official": err,
                "pass": err is not None and err <= rtol,
            }
        )

    overall_pass = err_vs_official is not None and err_vs_official <= rtol

    return {
        "slug": SLUG,
        "official_reference": "Structural_Mechanics_Module/Verification_Examples/channel_beam",
        "official_url": "https://www.comsol.com/model/channel-beam-8520",
        "spec": {
            "length_m": spec.length_m,
            "width_m": spec.width_m,
            "height_m": spec.height_m,
            "youngs_pa": spec.youngs_pa,
            "poisson": spec.poisson,
            "density_kg_m3": spec.density_kg_m3,
            "inertia_weak_m4": spec.inertia_weak_m4,
            "area_m2": spec.area_m2,
        },
        "all_frequencies_Hz": freqs,
        "comparisons": comparisons,
        "first_mode": {
            "analytical_rect_beam_Hz": analytical_f1,
            "official_channel_beam_Hz": official_f1,
            "computed_Hz": f1_computed,
            "rel_error_vs_official": err_vs_official,
            "rel_error_vs_analytical": err_vs_analytical,
        },
        "rtol": rtol,
        "pass": overall_pass,
    }


def run_validation(
    *,
    comsol_bin: str | None = None,
    cores: int = 2,
    mesh_mm: float = 5.0,
    use_batch: bool = True,
    rtol: float = 0.08,
) -> dict:
    """End-to-end: build → solve → extract → compare."""
    ensure_output_dirs()
    job_dir = COMSOL_JOBS_ROOT / SLUG
    job_dir.mkdir(parents=True, exist_ok=True)

    spec = CantileverSolidSpec()
    mph_path = job_dir / f"{SLUG}.mph"

    build_solid_cantilever_mph(
        spec,
        out_mph=mph_path,
        comsol_bin=comsol_bin,
        cores=cores,
        mesh_mm=mesh_mm,
    )
    solved, rows = solve_and_extract(
        mph_path,
        comsol_bin=comsol_bin,
        cores=cores,
        use_batch=use_batch,
    )
    write_eigen_csv(job_dir / f"{SLUG}_eigenfrequencies.csv", rows)

    report = compare_to_reference(rows, spec, rtol=rtol)
    report["mph"] = str(mph_path)
    report["solved_mph"] = str(solved)
    report_path = job_dir / f"{SLUG}_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_json"] = str(report_path)
    return report
