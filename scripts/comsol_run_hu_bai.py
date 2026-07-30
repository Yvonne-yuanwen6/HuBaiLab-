#!/usr/bin/env python3
"""Hu & Bai COMSOL: build vibration-isolation model from STEP and batch-solve."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.mph_builder import build_fixture_template_mph, build_mph_from_step, solve_mph
from src.comsol.runner import ComsolBatchRequest, run_batch
from src.export.cad_solid_paths import resolve_verified_solid_step
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import ensure_output_dirs


def _resolve_step(args: argparse.Namespace, gen: HuBaiLatticeGenerator) -> Path:
    if args.cad:
        step = Path(args.cad).resolve()
        if not step.is_file():
            raise FileNotFoundError(f"CAD not found: {step}")
        return step
    resolved = resolve_verified_solid_step(
        variant_name=gen.variant_name,
        cell_size_mm=args.cell_size,
        nx=args.cells,
        ny=args.cells,
        nz=args.nz or args.cells,
    )
    return Path(resolved).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hu & Bai COMSOL isolation: eigen + harmonic transmissibility from STEP."
    )
    parser.add_argument("--Q", type=float, default=0.0)
    parser.add_argument("--Af", type=float, default=2.0)
    parser.add_argument("--cells", type=int, default=4)
    parser.add_argument("--nz", type=int, default=None)
    parser.add_argument("--cell-size", type=float, default=20.0)
    parser.add_argument("--rod-diameter", type=float, default=2.0)
    parser.add_argument("--mesh-mm", type=float, default=None)
    parser.add_argument("--cad", default="", help="Lattice STEP (default: output/cad/verified/…)")
    parser.add_argument("--slug", default="")
    parser.add_argument(
        "--interface-coupling",
        default="",
        choices=("p1_continuity", "p2_contact_all", "p3_contact_auto"),
        help="Fig.2.8 interface strategy (default: p1_continuity)",
    )
    parser.add_argument("--np", type=int, default=4)
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--solve-only", metavar="MPH", default="")
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--eigen-only", action="store_true")
    parser.add_argument("--freq-only", action="store_true")
    parser.add_argument("--n-modes", type=int, default=None, help="Number of eigenmodes (default: settings)")
    parser.add_argument("--eigen-search", default="", help="eigwhich: sr, lr, lm, …")
    parser.add_argument("--eigen-shift", type=float, default=None, help="Shift-invert center frequency [Hz]")
    parser.add_argument("--freq-min", type=float, default=10.0)
    parser.add_argument("--freq-max", type=float, default=2000.0)
    parser.add_argument("--freq-step", type=float, default=10.0)
    parser.add_argument(
        "--base-accel",
        type=float,
        default=HuBaiComsolSettings().base_acceleration_m_s2,
        help="§2.4.3 prescribed base acceleration [m/s²] (default 0.98)",
    )
    parser.add_argument(
        "--base-disp-mm",
        type=float,
        default=None,
        help="Use displacement excitation instead of acceleration",
    )
    parser.add_argument(
        "--excitation-axis",
        choices=("x", "y", "z"),
        default=None,
        help="Excitation axis (thesis §2.4.3: y; repo Z-up STEP: z)",
    )
    parser.add_argument(
        "--physics-controlled-mesh",
        action="store_true",
        help="Use COMSOL hauto presets instead of Fig. 2.8 explicit hmax layered mesh",
    )
    parser.add_argument(
        "--lattice-hauto",
        type=int,
        default=None,
        help="Physics-controlled lattice autoMeshSize (default 4=Fine; try 5 if mesh fails)",
    )
    parser.add_argument(
        "--fixture-hauto",
        type=int,
        default=None,
        help="Physics-controlled fixture autoMeshSize (default 5=Normal)",
    )
    parser.add_argument(
        "--solid-order",
        type=int,
        choices=(1, 2),
        default=None,
        help="Solid Mechanics displacement order: 1=linear (low-RAM), 2=quadratic (default)",
    )
    parser.add_argument(
        "--freq-linear-solver",
        choices=("direct", "iterative"),
        default=None,
        help="Frequency study linear solver: direct (default) or iterative/GMRES (low-RAM)",
    )
    parser.add_argument(
        "--no-mesh",
        action="store_true",
        help="Build geometry + BCs + studies only; skip meshing (GUI inspection step)",
    )
    parser.add_argument(
        "--no-fig28",
        action="store_true",
        help="Lattice only — skip §2.4.3 shaker table + aluminum plate",
    )
    parser.add_argument(
        "--fig28",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--build-fixture-template",
        action="store_true",
        help="Build meshed table+plate template only (no lattice STEP)",
    )
    parser.add_argument(
        "--fixture-template",
        default="",
        help="Path to meshed fixture .mph (default: output/comsol_jobs/comsol_fixture_444/…)",
    )
    parser.add_argument(
        "--save-fixture-template",
        action="store_true",
        help="After inline fixture mesh, save template .mph for reuse",
    )
    parser.add_argument(
        "--no-top-payload",
        action="store_true",
        help="Skip 300 g experimental mass on output plate",
    )
    parser.add_argument("--comsol-bin", default="")
    args = parser.parse_args(argv)

    run_eigen = not args.freq_only
    run_freq = not args.eigen_only
    if args.eigen_only and args.freq_only:
        raise SystemExit("Use only one of --eigen-only / --freq-only")

    ensure_output_dirs()
    nz = args.nz if args.nz is not None else args.cells
    gen = HuBaiLatticeGenerator(
        cell_size=args.cell_size,
        rod_diameter=args.rod_diameter,
        amplitude=args.Af,
        period_factor=args.Q,
    )
    step_path = _resolve_step(args, gen) if not args.solve_only and not args.build_fixture_template else None

    defaults = HuBaiComsolSettings()
    excitation_type = "displacement" if args.base_disp_mm is not None else defaults.excitation_type
    fixture_tpl = args.fixture_template or str(defaults.fixture_template_mph)
    interface_coupling = args.interface_coupling or defaults.interface_coupling
    settings = HuBaiComsolSettings(
        Q=args.Q,
        amplitude_mm=args.Af,
        cell_size_mm=args.cell_size,
        rod_diameter_mm=args.rod_diameter,
        nx=args.cells,
        ny=args.cells,
        nz=nz,
        mesh_mm=args.mesh_mm if args.mesh_mm is not None else defaults.mesh_mm,
        physics_controlled_mesh=args.physics_controlled_mesh or defaults.physics_controlled_mesh,
        lattice_hauto=args.lattice_hauto if args.lattice_hauto is not None else defaults.lattice_hauto,
        fixture_hauto=args.fixture_hauto if args.fixture_hauto is not None else defaults.fixture_hauto,
        skip_mesh=args.no_mesh,
        run_eigen=run_eigen,
        run_frequency=run_freq,
        n_eigenmodes=args.n_modes if args.n_modes is not None else defaults.n_eigenmodes,
        eigen_search=args.eigen_search or defaults.eigen_search,
        eigen_shift_hz=args.eigen_shift if args.eigen_shift is not None else defaults.eigen_shift_hz,
        eigen_min_hz=defaults.eigen_min_hz,
        freq_min_hz=args.freq_min,
        freq_max_hz=args.freq_max,
        freq_step_hz=args.freq_step,
        excitation_type=excitation_type,
        excitation_axis=args.excitation_axis or defaults.excitation_axis,
        base_acceleration_m_s2=args.base_accel,
        base_displacement_mm=(
            args.base_disp_mm if args.base_disp_mm is not None else defaults.base_displacement_mm
        ),
        include_shaker_fixture=not args.no_fig28,
        step_path=str(step_path) if step_path else "",
        slug=args.slug,
        fixture_template_path=fixture_tpl,
        save_fixture_template=args.save_fixture_template,
        include_top_payload=defaults.include_top_payload and not args.no_top_payload,
        interface_coupling=interface_coupling,
        solid_displacement_order=(
            args.solid_order
            if args.solid_order is not None
            else defaults.solid_displacement_order
        ),
        freq_linear_solver=(
            args.freq_linear_solver
            if args.freq_linear_solver is not None
            else defaults.freq_linear_solver
        ),
    )
    slug = settings.default_slug()
    manifest_path = settings.write_manifest()

    print(f"Variant: {settings.variant_name}")
    print(f"Slug:    {slug}")
    print(f"Coupling: {settings.interface_coupling}")
    if step_path:
        print(f"STEP:    {step_path}")
    print(f"Material E={settings.youngs_modulus_mpa} MPa (linear ref), nu={settings.poisson}, rho={settings.density_kg_m3} kg/m^3")
    if settings.lattice_material_model.lower() in (
        "marlow_uniaxial",
        "marlow",
        "hyperelastic_marlow",
        "fig25",
    ):
        print(f"Lattice: Fig.2.5 Marlow uniaxial ({settings.tpu_tensile_curve_json})")
    if settings.skip_mesh:
        print("Mesh: skipped (--no-mesh, geometry-only for GUI check)")
    elif settings.physics_controlled_mesh:
        print(
            f"Mesh: physics-controlled hauto (lattice={settings.lattice_hauto}, "
            f"fixture={settings.fixture_hauto})"
        )
    elif settings.include_shaker_fixture:
        print(
            f"Mesh: Fig. 2.8 layered — lattice {settings.mesh_mm} mm, "
            f"table {settings.shaker_mesh_mm} mm"
            + (
                f", contact footprint {settings.table_contact_refine_hmax_mm} mm "
                f"(depth {settings.table_contact_refine_depth_mm} mm, "
                f"hgrad {settings.table_contact_refine_hgrad})"
                if settings.table_contact_refine
                else ""
            )
            + f", plate ≤{settings.top_plate_mesh_mm} mm"
        )
    else:
        print(f"Mesh: lattice hmax={settings.mesh_mm} mm (no fixture)")
    print(
        f"Discretization: solid order={settings.solid_displacement_order}; "
        f"freq linear solver={settings.freq_linear_solver}"
    )
    if settings.include_shaker_fixture:
        print(f"Fixture template: {settings.fixture_template_mph}")
    if settings.include_shaker_fixture and not args.build_fixture_template:
        print(
            f"§2.4.3 fixture: AISI4340 table {settings.shaker_table_size_xy_mm}×"
            f"{settings.shaker_table_height_mm} mm, "
            f"Al plate {settings.top_plate_xy_mm}×{settings.top_plate_thickness_mm} mm"
        )
        if settings.include_top_payload:
            print(f"Top payload: {settings.top_payload_mass_kg} kg (experimental mass)")
    elif not args.build_fixture_template:
        print("Fixture: OFF (--no-fig28, lattice-only)")
    if settings.run_frequency:
        if settings.excitation_type == "acceleration":
            print(
                f"Excitation: {settings.base_acceleration_m_s2} m/s^2 "
                f"on {settings.excitation_axis.upper()}-axis (sec 2.4.3)"
            )
        else:
            print(f"Excitation: displacement {settings.base_displacement_mm} mm")
    if settings.run_eigen:
        shift = (
            f"{settings.eigen_shift_hz} Hz"
            if settings.eigen_shift_hz is not None
            else "off"
        )
        print(
            f"Eigen:   {settings.n_eigenmodes} modes, "
            f"eigwhich={settings.eigen_search}, shift={shift}, "
            f"rank by mEff along {settings.excitation_axis.upper()}"
        )
    if settings.run_frequency:
        print(
            f"Freq:    {settings.freq_min_hz}–{settings.freq_max_hz} Hz "
            f"step {settings.freq_step_hz}"
        )
    print(f"Manifest: {manifest_path}")

    if args.manifest_only:
        return 0

    comsol_bin = args.comsol_bin or None
    mph_path: Path

    if args.build_fixture_template:
        build_fixture_template_mph(settings, comsol_bin=comsol_bin, cores=args.np)
        return 0

    if args.solve_only:
        mph_path = Path(args.solve_only).resolve()
        if not mph_path.is_file():
            raise FileNotFoundError(mph_path)
    else:
        assert step_path is not None
        mph_path = build_mph_from_step(
            settings,
            step_path,
            comsol_bin=comsol_bin,
            cores=args.np,
        )

    if args.build_only:
        return 0

    studies = []
    if settings.run_eigen:
        studies.append(settings.study_eigen_tag)
    if settings.run_frequency:
        studies.append(settings.study_freq_tag)

    if args.in_process:
        solve_mph(mph_path, settings, comsol_bin=comsol_bin, cores=args.np, studies=studies)
        return 0

    # Prefer a process that never held an MPh client during the long batch wait.
    # (ClientWebSocket SIGSEGV while waiting has falsely failed completed batches.)
    if not args.solve_only and not args.build_fixture_template:
        print(
            "  Note: for long batch solves, prefer separate "
            "`--build-only` then `--solve-only` processes.",
            flush=True,
        )

    for i, study in enumerate(studies):
        solved_path = settings.job_dir() / f"{slug}_solved.mph"
        request = ComsolBatchRequest(
            slug=slug,
            input_file=mph_path if i == 0 else solved_path,
            output_file=solved_path,
            study=study,
            np=args.np,
            continue_run=i > 0,
        )
        run_batch(
            request,
            comsol_bin=comsol_bin,
            background=args.background and i == len(studies) - 1,
            cwd=settings.job_dir(),
        )
        mph_path = solved_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
