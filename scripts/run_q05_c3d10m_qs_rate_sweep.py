#!/usr/bin/env python3
"""
Q0.5 unit-cell C3D10M Explicit quasi-static load-rate sweep.

Reuses Model-C mesh/physics; varies only load rate:
  R1   = baseline (default 5 mm/min)
  R5x  = 5× slower
  R10x = 10× slower

Examples:
  # Export all three INPs (reuse C3D10M mesh), then submit+post+compare:
  py -3 scripts/run_q05_c3d10m_qs_rate_sweep.py --mode all

  # Only export (no solve):
  py -3 scripts/run_q05_c3d10m_qs_rate_sweep.py --mode export

  # Mesh-convergence knobs (reserved):
  py -3 scripts/run_q05_c3d10m_qs_rate_sweep.py --mode export \\
      --element-type C3D10M --seed 0.5 --rods-per-diameter 4

  # Later 4×4×4 extension:
  py -3 scripts/run_q05_c3d10m_qs_rate_sweep.py --cells 4 --cad PATH_TO_444.step ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.study.uc_explicit_qs import StudyConfig, run_study
from src.study.uc_explicit_qs.config import MeshParams, PhysicsParams


DEFAULT_MESH = (
    _ROOT
    / "output"
    / "export"
    / "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d10m_r3"
    / "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d10m_r3_cae_mesh.inp"
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mode",
        default="all",
        choices=("export", "submit", "post", "compare", "all"),
        help="Pipeline stage(s). 'all' = export→submit→post→compare",
    )
    p.add_argument(
        "--only",
        default="",
        help="Comma-separated case ids to run (R1,R5x,R10x)",
    )
    p.add_argument("--baseline-rate", type=float, default=5.0, help="mm/min")
    p.add_argument(
        "--slowdowns",
        default="1,5,10",
        help="Comma-separated slowdown factors vs baseline (1=current speed)",
    )
    # Mesh convergence interface
    p.add_argument("--element-type", default="C3D10M", choices=("C3D4", "C3D10", "C3D10M"))
    p.add_argument("--seed", type=float, default=0.6, help="Global CAE seed [mm]")
    p.add_argument("--rods-per-diameter", type=float, default=3.0)
    p.add_argument(
        "--mesh-quality",
        default="lattice_curve",
        choices=("fast", "lattice", "lattice_contact", "lattice_curve", "paper"),
    )
    p.add_argument("--reuse-mesh-inp", default="", help="Reuse CAE mesh INP path")
    p.add_argument("--no-reuse-mesh", action="store_true")
    # Geometry / physics (kept identical across rates)
    p.add_argument("--Q", type=float, default=0.5)
    p.add_argument("--cells", type=int, default=1, help="1=unit cell; 4→4×4×4 later")
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-diameter", type=float, default=2.0)
    p.add_argument("--cad", default="")
    p.add_argument("--strain", type=float, default=0.80)
    p.add_argument("--material-model", default="neo_hooke")
    p.add_argument("--explicit-dt", type=float, default=5e-4)
    p.add_argument("--explicit-dt-mode", default="automatic", choices=("fixed", "automatic"))
    p.add_argument("--no-mass-scaling", action="store_true")
    p.add_argument("--mass-scaling-mode", default="", choices=("", "none", "uniform", "below_min"))
    p.add_argument("--mass-scaling-factor", type=float, default=None)
    p.add_argument("--mass-scaling-dt", type=float, default=None)
    p.add_argument("--ke-ie-limit", type=float, default=0.05)
    p.add_argument("--cpus", type=int, default=6)
    p.add_argument("--memory-mb", type=int, default=6144)
    p.add_argument("--study-name", default="q05_uc_c3d10m_qs_rate")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    os.environ.setdefault("PYTHONPATH", str(_ROOT))
    # Ensure abaqus on PATH for Windows sessions launched outside SIMULIA shell.
    simulia = Path(r"D:\Apps\SIMULIA\Commands")
    if simulia.is_dir():
        os.environ["PATH"] = str(simulia) + os.pathsep + os.environ.get("PATH", "")

    slowdowns = tuple(
        float(x.strip()) for x in args.slowdowns.split(",") if x.strip()
    )
    only = tuple(x.strip() for x in args.only.split(",") if x.strip()) or None

    reuse = None
    if not args.no_reuse_mesh:
        reuse = args.reuse_mesh_inp.strip() or (
            str(DEFAULT_MESH) if DEFAULT_MESH.is_file() else None
        )

    cad = args.cad.strip() or (
        "output/cad/verified/hu_bai_sfbls_af2q0p5_L20_1x1x1_paper_box_array.step"
    )

    cfg = StudyConfig(
        name=args.study_name,
        baseline_load_rate_mm_min=float(args.baseline_rate),
        rate_slowdown_factors=slowdowns,
        only_case_ids=only,
        cpus=int(args.cpus),
        memory_mb=int(args.memory_mb),
        ke_ie_limit=float(args.ke_ie_limit),
        mesh=MeshParams(
            element_type=args.element_type,
            seed_mm=float(args.seed),
            rods_per_diameter=float(args.rods_per_diameter),
            mesh_quality=args.mesh_quality,
            virtual_topology=True,
            reuse_mesh_inp=reuse,
        ),
        physics=PhysicsParams(
            Q=float(args.Q),
            cells=int(args.cells),
            L_mm=float(args.L),
            rod_diameter_mm=float(args.rod_diameter),
            cad_step=cad,
            material_model=args.material_model,
            strain=float(args.strain),
            explicit_dt=float(args.explicit_dt),
            explicit_dt_mode=args.explicit_dt_mode,
            contact_store_offsets=True,
            contact_settle=True,
            no_mass_scaling=bool(args.no_mass_scaling),
            mass_scaling_mode=(args.mass_scaling_mode or None),
            mass_scaling_factor=args.mass_scaling_factor,
            mass_scaling_dt=args.mass_scaling_dt,
        ),
    )

    print("=== Q05 C3D10M QS rate sweep ===", flush=True)
    print(json.dumps(cfg.to_dict(), indent=2, default=str), flush=True)
    print("cases:", [c.case_id for c in cfg.rate_cases()], flush=True)

    result = run_study(_ROOT, cfg, modes=(args.mode,))
    print(json.dumps({k: result[k] for k in ("study", "report_dir", "compare")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
