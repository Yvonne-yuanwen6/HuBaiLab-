#!/usr/bin/env python3
"""
Q0.5 unit-cell C3D10M Explicit mass-scaling sensitivity sweep.

Fixed: C3D10M mesh, geometry, material, BC, load rate (default 1 mm/min).
Vary mass scaling only:
  MS0  = no mass scaling
  MS5  = auto BELOW MIN → 5× natural stable Δt
  MS10 = auto BELOW MIN → 10× natural stable Δt

Also locates failed element 12488 from the prior R10x run (coords + region).

Examples:
  py -3 scripts/run_q05_c3d10m_qs_mass_scale_sweep.py --mode export
  py -3 scripts/run_q05_c3d10m_qs_mass_scale_sweep.py --mode all
  py -3 scripts/run_q05_c3d10m_qs_mass_scale_sweep.py --mode all --only MS0,MS5

Parameter interface for later 4×4×4:
  --element-type --seed --rods-per-diameter --load-rate
  --mass-scale-factors --natural-stable-dt --cells --cad
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
    MassScaleStudyConfig,
    MeshParams,
    PhysicsParams,
)
from src.study.uc_explicit_qs.locate_element import write_element_report
from src.study.uc_explicit_qs.pipeline import run_mass_scale_study


DEFAULT_MESH = (
    _ROOT
    / "output"
    / "export"
    / "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d10m_r3"
    / "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_5mmin_uc_c3d10m_r3_cae_mesh.inp"
)

# Natural stable dt from prior C3D10M STA (s).
DEFAULT_NATURAL_DT = 4.767e-4
FAILED_ELEM_ID = 12488


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mode",
        default="all",
        choices=("export", "submit", "post", "compare", "all", "locate"),
        help="'locate' only writes elem 12488 report; 'all' runs full pipeline",
    )
    p.add_argument("--only", default="", help="Comma-separated case ids (MS0,MS5,MS10)")
    p.add_argument("--load-rate", type=float, default=1.0, help="mm/min (fixed across MS)")
    p.add_argument(
        "--mass-scale-factors",
        default="0,5,10",
        help="0=no MS; N=BELOW MIN dt = N× natural stable dt",
    )
    p.add_argument(
        "--submit-order",
        default="MS10,MS5,MS0",
        help="Submit order (fastest first). Empty = factor order.",
    )
    p.add_argument(
        "--natural-stable-dt",
        type=float,
        default=DEFAULT_NATURAL_DT,
        help="Unscaled stable time increment [s] from STA",
    )
    # Shared UC→444 interface
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
    p.add_argument("--Q", type=float, default=0.5)
    p.add_argument("--cells", type=int, default=1, help="1=UC; 4→4×4×4 later")
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-diameter", type=float, default=2.0)
    p.add_argument("--cad", default="")
    p.add_argument("--strain", type=float, default=0.80)
    p.add_argument("--material-model", default="neo_hooke")
    p.add_argument("--explicit-dt", type=float, default=5e-4)
    p.add_argument("--explicit-dt-mode", default="automatic", choices=("fixed", "automatic"))
    p.add_argument("--ke-ie-limit", type=float, default=0.05)
    p.add_argument("--peak-force-tol", type=float, default=0.05)
    p.add_argument("--cpus", type=int, default=6)
    p.add_argument("--memory-mb", type=int, default=6144)
    p.add_argument("--study-name", default="q05_uc_c3d10m_qs_mass_scale")
    p.add_argument("--failed-elem", type=int, default=FAILED_ELEM_ID)
    return p.parse_args()


def _locate_failed_elem(mesh: Path, elem_id: int, report_dir: Path, L_mm: float) -> dict:
    out = report_dir / f"elem_{elem_id}_location.json"
    info = write_element_report(mesh, elem_id, out, L_mm=L_mm)
    print(f"[locate] elem {elem_id} → {out}", flush=True)
    print(json.dumps(info, indent=2), flush=True)
    return info


def main() -> int:
    args = _parse_args()
    os.environ.setdefault("PYTHONPATH", str(_ROOT))
    simulia = Path(r"D:\Apps\SIMULIA\Commands")
    if simulia.is_dir():
        os.environ["PATH"] = str(simulia) + os.pathsep + os.environ.get("PATH", "")

    factors = tuple(
        float(x.strip()) for x in args.mass_scale_factors.split(",") if x.strip()
    )
    only = tuple(x.strip() for x in args.only.split(",") if x.strip()) or None
    # Prefer fastest jobs first when submitting (override with --only / --submit-order).
    if only is None and args.mode in ("submit", "all"):
        order = tuple(x.strip() for x in args.submit_order.split(",") if x.strip())
        if order:
            only = order

    reuse = None
    if not args.no_reuse_mesh:
        reuse = args.reuse_mesh_inp.strip() or (
            str(DEFAULT_MESH) if DEFAULT_MESH.is_file() else None
        )

    cad = args.cad.strip() or (
        "output/cad/verified/hu_bai_sfbls_af2q0p5_L20_1x1x1_paper_box_array.step"
    )

    report_dir = _ROOT / "output" / "reports" / args.study_name
    report_dir.mkdir(parents=True, exist_ok=True)

    # Always emit lattice param interface snapshot for 444 reuse.
    lattice = LatticeStudyParams(
        element_type=args.element_type,
        mesh_seed_mm=float(args.seed),
        rods_per_diameter=float(args.rods_per_diameter),
        mass_scaling_mode="sweep",  # documented as multi-case
        mass_scaling_dt_s=None,
        loading_rate_mm_min=float(args.load_rate),
        cells=int(args.cells),
    )
    (report_dir / f"{args.study_name}_param_interface.json").write_text(
        json.dumps(
            {
                "lattice_study_params": lattice.to_dict(),
                "mass_scale_dt_factors": list(factors),
                "natural_stable_dt_s": float(args.natural_stable_dt),
                "notes": {
                    "element_type": "C3D10M preferred for curved rods",
                    "mesh_size": "seed_mm + rods_per_diameter",
                    "mass_scaling": "none | BELOW MIN dt = factor × natural_stable_dt",
                    "loading_rate": "mm/min; prefer ≤1 after rate study",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    mesh_for_locate = Path(reuse) if reuse else DEFAULT_MESH
    if args.mode == "locate" or args.mode == "all":
        if mesh_for_locate.is_file():
            _locate_failed_elem(
                mesh_for_locate,
                int(args.failed_elem),
                report_dir,
                float(args.L),
            )
        else:
            print(f"[locate] mesh missing: {mesh_for_locate}", flush=True)
        if args.mode == "locate":
            return 0

    cfg = MassScaleStudyConfig(
        name=args.study_name,
        load_rate_mm_min=float(args.load_rate),
        natural_stable_dt_s=float(args.natural_stable_dt),
        mass_scale_dt_factors=factors,
        only_case_ids=only,
        cpus=int(args.cpus),
        memory_mb=int(args.memory_mb),
        ke_ie_limit=float(args.ke_ie_limit),
        peak_force_tol=float(args.peak_force_tol),
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
        ),
    )

    print("=== Q05 C3D10M QS mass-scaling sweep ===", flush=True)
    print(json.dumps(cfg.to_dict(), indent=2, default=str), flush=True)
    print(
        "cases:",
        [
            (
                c.case_id,
                c.label,
                cfg.target_dt_s(c),
            )
            for c in cfg.mass_scale_cases()
        ],
        flush=True,
    )

    result = run_mass_scale_study(_ROOT, cfg, modes=(args.mode,))
    print(
        json.dumps(
            {k: result[k] for k in ("study", "report_dir", "compare")},
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
