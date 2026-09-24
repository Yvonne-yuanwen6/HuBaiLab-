#!/usr/bin/env python3
"""
Q0.5 unit-cell C3D10M Explicit QS optimization (post-MS5).

Cases (C3D10M + retained MS family):
  A: 1.0 mm/min + MS5   (reuses completed MS5 job by default)
  B: 0.5 mm/min + MS5
  C: 0.5 mm/min + MS3

Also:
  - locates elem 12488 (coords / size / neighbor quality)
  - deformation snapshots at 0/30/60/100% for snap-through check
  - paper pack under output/reports/<study>/paper/

Examples:
  py -3 scripts/run_q05_c3d10m_qs_opt_sweep.py --mode export
  py -3 scripts/run_q05_c3d10m_qs_opt_sweep.py --mode all
  py -3 scripts/run_q05_c3d10m_qs_opt_sweep.py --mode submit --only B,C
  py -3 scripts/run_q05_c3d10m_qs_opt_sweep.py --mode post --only A
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

from src.study.uc_explicit_qs.config import (
    LatticeStudyParams,
    MeshParams,
    PhysicsParams,
    QsOptStudyConfig,
)
from src.study.uc_explicit_qs.pipeline import run_qs_opt_study


DEFAULT_MESH = (
    _ROOT
    / "output"
    / "export"
    / "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d10m_r3"
    / "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d10m_r3_cae_mesh.inp"
)
DEFAULT_A_SLUG = (
    "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_1mmin_uc_c3d10m_r3_MS5"
)
DEFAULT_NATURAL_DT = 4.767e-4


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mode",
        default="all",
        choices=("export", "submit", "post", "compare", "paper", "all"),
    )
    p.add_argument("--only", default="", help="Comma-separated case ids A,B,C")
    p.add_argument("--submit-order", default="A,B,C", help="Submit order")
    p.add_argument("--natural-stable-dt", type=float, default=DEFAULT_NATURAL_DT)
    p.add_argument("--element-type", default="C3D10M", choices=("C3D4", "C3D10", "C3D10M"))
    p.add_argument("--seed", type=float, default=0.6)
    p.add_argument("--rods-per-diameter", type=float, default=3.0)
    p.add_argument(
        "--mesh-quality",
        default="lattice_curve",
        choices=("fast", "lattice", "lattice_contact", "lattice_curve", "paper"),
    )
    p.add_argument("--reuse-mesh-inp", default="")
    p.add_argument("--no-reuse-mesh", action="store_true")
    p.add_argument("--reuse-a-slug", default=DEFAULT_A_SLUG)
    p.add_argument("--no-reuse-a", action="store_true", help="Force re-export Case A")
    p.add_argument("--Q", type=float, default=0.5)
    p.add_argument("--cells", type=int, default=1)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-diameter", type=float, default=2.0)
    p.add_argument("--cad", default="")
    p.add_argument("--strain", type=float, default=0.80)
    p.add_argument("--material-model", default="neo_hooke")
    p.add_argument("--ke-ie-limit", type=float, default=0.05)
    p.add_argument("--peak-force-tol", type=float, default=0.05)
    p.add_argument("--failed-elem", type=int, default=12488)
    p.add_argument("--cpus", type=int, default=6)
    p.add_argument("--memory-mb", type=int, default=6144)
    p.add_argument("--study-name", default="q05_uc_c3d10m_qs_opt")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    os.environ.setdefault("PYTHONPATH", str(_ROOT))
    simulia = Path(r"D:\Apps\SIMULIA\Commands")
    if simulia.is_dir():
        os.environ["PATH"] = str(simulia) + os.pathsep + os.environ.get("PATH", "")

    only = tuple(x.strip() for x in args.only.split(",") if x.strip()) or None
    if only is None and args.mode in ("submit", "all"):
        only = tuple(x.strip() for x in args.submit_order.split(",") if x.strip()) or None

    reuse = None
    if not args.no_reuse_mesh:
        reuse = args.reuse_mesh_inp.strip() or (
            str(DEFAULT_MESH) if DEFAULT_MESH.is_file() else None
        )

    cad = args.cad.strip() or (
        "output/cad/verified/hu_bai_sfbls_af2q0p5_L20_1x1x1_paper_box_array.step"
    )
    a_slug = None if args.no_reuse_a else (args.reuse_a_slug.strip() or None)

    cfg = QsOptStudyConfig(
        name=args.study_name,
        natural_stable_dt_s=float(args.natural_stable_dt),
        case_specs=(
            ("A", 1.0, 5.0, a_slug),
            ("B", 0.5, 5.0, None),
            ("C", 0.5, 3.0, None),
        ),
        only_case_ids=only,
        cpus=int(args.cpus),
        memory_mb=int(args.memory_mb),
        ke_ie_limit=float(args.ke_ie_limit),
        peak_force_tol=float(args.peak_force_tol),
        failed_elem_id=int(args.failed_elem),
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
            contact_store_offsets=True,
            contact_settle=True,
        ),
    )

    lattice = LatticeStudyParams(
        element_type=args.element_type,
        mesh_seed_mm=float(args.seed),
        rods_per_diameter=float(args.rods_per_diameter),
        mass_scaling_mode="below_min",
        loading_rate_mm_min=0.5,
        cells=int(args.cells),
    )
    report_dir = _ROOT / "output" / "reports" / args.study_name
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{args.study_name}_param_interface.json").write_text(
        json.dumps(
            {
                "lattice_study_params": lattice.to_dict(),
                "cases": [
                    {"id": c.case_id, "label": c.label, "dt": cfg.target_dt_s(c)}
                    for c in cfg.qs_opt_cases()
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=== Q05 C3D10M QS optimization (A/B/C) ===", flush=True)
    print(json.dumps(cfg.to_dict(), indent=2, default=str), flush=True)
    print(
        "cases:",
        [(c.case_id, c.label, cfg.target_dt_s(c), c.reuse_job_slug) for c in cfg.qs_opt_cases()],
        flush=True,
    )

    result = run_qs_opt_study(_ROOT, cfg, modes=(args.mode,))
    print(
        json.dumps(
            {k: result.get(k) for k in ("study", "report_dir", "paper_dir", "compare", "paper")},
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
