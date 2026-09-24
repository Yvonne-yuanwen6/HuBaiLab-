"""Export compression INP via existing CAE tet export CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from src.study.uc_explicit_qs.config import (
    MassScaleCase,
    MassScaleStudyConfig,
    PhysicsParams,
    QsOptCase,
    QsOptStudyConfig,
    RateCase,
    StudyConfig,
    resolve_path,
)


def _python_cmd(root: Path) -> list[str]:
    venv = root / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return [str(venv)]
    return [sys.executable]


def _append_mass_scaling_argv(argv: list[str], phy: PhysicsParams) -> None:
    if phy.no_mass_scaling:
        argv.append("--no-mass-scaling")
    if phy.mass_scaling_mode:
        argv.extend(["--mass-scaling-mode", phy.mass_scaling_mode])
    if phy.mass_scaling_factor is not None:
        argv.extend(["--mass-scaling-factor", str(phy.mass_scaling_factor)])
    if phy.mass_scaling_dt is not None:
        argv.extend(["--mass-scaling-dt", str(phy.mass_scaling_dt)])


def _base_export_argv(
    root: Path,
    *,
    phy: PhysicsParams,
    mesh_element_type: str,
    mesh_seed_mm: float,
    mesh_rods: float,
    mesh_quality: str,
    mesh_vtopo: bool,
    case_suffix: str,
    load_rate_mm_min: float,
    mesh_inp: Path | None,
    reuse_mesh_cfg: str | None,
) -> list[str]:
    cad = resolve_path(root, phy.cad_step)
    script = root / "scripts" / "run_hu_bai_bcc_solid_cad_cae_tet_export.py"
    argv = [
        *_python_cmd(root),
        str(script),
        "--Q",
        str(phy.Q),
        "--Af",
        str(phy.Af),
        "--cells",
        str(phy.cells),
        "--L",
        str(phy.L_mm),
        "--rod-diameter",
        str(phy.rod_diameter_mm),
        "--cad",
        str(cad),
        "--profile",
        "fast",
        "--mesh-locally",
        "--cae-mesh-quality",
        mesh_quality,
        "--cae-seed",
        str(mesh_seed_mm),
        "--cae-element-type",
        mesh_element_type,
        "--cae-rods-per-diameter",
        str(mesh_rods),
        "--case-suffix",
        case_suffix,
        "--strain",
        str(phy.strain),
        "--load-rate-mm-min",
        str(load_rate_mm_min),
        "--explicit-dt",
        str(phy.explicit_dt),
        "--explicit-dt-mode",
        phy.explicit_dt_mode,
        "--contact-mode",
        phy.contact_mode,
        "--material-model",
        phy.material_model,
        "--contact-settle-fraction",
        str(phy.contact_settle_fraction),
    ]
    if mesh_vtopo:
        argv.append("--cae-virtual-topology")
    if phy.contact_store_offsets:
        argv.append("--contact-store-offsets")
    if phy.contact_settle:
        argv.append("--contact-settle")
    _append_mass_scaling_argv(argv, phy)

    reuse = mesh_inp
    if reuse is None and reuse_mesh_cfg:
        reuse = resolve_path(root, reuse_mesh_cfg)
    if reuse is not None and reuse.is_file():
        argv.extend(["--cae-mesh-inp", str(reuse)])
    return argv


def build_export_argv(
    root: Path,
    cfg: StudyConfig,
    case: RateCase,
    *,
    mesh_inp: Path | None = None,
) -> tuple[list[str], str]:
    """Return (argv, case_suffix) for a load-rate case."""
    phy = cfg.physics
    mesh = cfg.mesh
    strain_pct = int(round(float(phy.strain) * 100))
    suffix = case.suffix(mesh, strain_pct)
    argv = _base_export_argv(
        root,
        phy=phy,
        mesh_element_type=mesh.element_type,
        mesh_seed_mm=mesh.seed_mm,
        mesh_rods=mesh.rods_per_diameter,
        mesh_quality=mesh.mesh_quality,
        mesh_vtopo=mesh.virtual_topology,
        case_suffix=suffix,
        load_rate_mm_min=case.load_rate_mm_min,
        mesh_inp=mesh_inp,
        reuse_mesh_cfg=mesh.reuse_mesh_inp,
    )
    return argv, suffix


def build_mass_scale_export_argv(
    root: Path,
    cfg: MassScaleStudyConfig,
    case: MassScaleCase,
    *,
    mesh_inp: Path | None = None,
) -> tuple[list[str], str]:
    """Return (argv, case_suffix) for a mass-scaling case."""
    mesh = cfg.mesh
    phy = cfg.physics
    strain_pct = int(round(float(phy.strain) * 100))
    suffix = case.suffix(
        mesh,
        strain_pct=strain_pct,
        load_rate_mm_min=cfg.load_rate_mm_min,
    )
    target_dt = cfg.target_dt_s(case)
    if case.no_mass_scaling:
        phy_ms = replace(
            phy,
            no_mass_scaling=True,
            mass_scaling_mode="none",
            mass_scaling_factor=None,
            mass_scaling_dt=None,
        )
    else:
        phy_ms = replace(
            phy,
            no_mass_scaling=False,
            mass_scaling_mode="below_min",
            mass_scaling_factor=None,
            mass_scaling_dt=target_dt,
            # Keep automatic dt; BELOW MIN raises stable dt toward target.
            explicit_dt=float(target_dt) if target_dt is not None else phy.explicit_dt,
            explicit_dt_mode="automatic",
        )
    argv = _base_export_argv(
        root,
        phy=phy_ms,
        mesh_element_type=mesh.element_type,
        mesh_seed_mm=mesh.seed_mm,
        mesh_rods=mesh.rods_per_diameter,
        mesh_quality=mesh.mesh_quality,
        mesh_vtopo=mesh.virtual_topology,
        case_suffix=suffix,
        load_rate_mm_min=cfg.load_rate_mm_min,
        mesh_inp=mesh_inp,
        reuse_mesh_cfg=mesh.reuse_mesh_inp,
    )
    return argv, suffix


def read_active_slug(root: Path) -> str | None:
    active = root / "output" / "active_case.json"
    if not active.is_file():
        return None
    try:
        data = json.loads(active.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("slug") or data.get("case_slug")


def _finalize_export(
    root: Path,
    *,
    case_id: str,
    label: str,
    suffix: str,
    extra: dict | None = None,
) -> dict:
    slug = read_active_slug(root)
    if not slug:
        export_root = root / "output" / "export"
        cands = sorted(
            export_root.glob(f"*_{suffix}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not cands:
            raise FileNotFoundError(f"no export dir for suffix={suffix}")
        slug = cands[0].name

    export_dir = root / "output" / "export" / slug
    job_inp = export_dir / f"{slug}.inp"
    if not job_inp.is_file():
        raise FileNotFoundError(job_inp)
    txt = job_inp.read_text(encoding="utf-8", errors="ignore")
    if "ALLAE" not in txt:
        raise RuntimeError(f"ALLAE missing in {job_inp}")
    mesh_out = export_dir / f"{slug}_cae_mesh.inp"
    out = {
        "case_id": case_id,
        "label": label,
        "slug": slug,
        "suffix": suffix,
        "export_dir": str(export_dir),
        "job_inp": str(job_inp),
        "mesh_inp": str(mesh_out) if mesh_out.is_file() else None,
        "meta_json": str(export_dir / f"{slug}_meta.json"),
    }
    if extra:
        out.update(extra)
    return out


def export_case(
    root: Path,
    cfg: StudyConfig,
    case: RateCase,
    *,
    mesh_inp: Path | None = None,
) -> dict:
    """Run export; return paths + slug."""
    argv, suffix = build_export_argv(root, cfg, case, mesh_inp=mesh_inp)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    print(f"[export] {case.case_id} rate={case.load_rate_mm_min:g} mm/min", flush=True)
    print("  " + " ".join(argv[-14:]), flush=True)
    proc = subprocess.run(argv, cwd=str(root), env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"export failed for {case.case_id} rc={proc.returncode}")
    return _finalize_export(
        root,
        case_id=case.case_id,
        label=case.label,
        suffix=suffix,
        extra={"load_rate_mm_min": case.load_rate_mm_min},
    )


def export_mass_scale_case(
    root: Path,
    cfg: MassScaleStudyConfig,
    case: MassScaleCase,
    *,
    mesh_inp: Path | None = None,
) -> dict:
    argv, suffix = build_mass_scale_export_argv(root, cfg, case, mesh_inp=mesh_inp)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    target_dt = cfg.target_dt_s(case)
    print(
        f"[export] {case.case_id} {case.label} "
        f"rate={cfg.load_rate_mm_min:g} mm/min "
        f"target_dt={target_dt}",
        flush=True,
    )
    print("  " + " ".join(argv[-16:]), flush=True)
    proc = subprocess.run(argv, cwd=str(root), env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"export failed for {case.case_id} rc={proc.returncode}")
    return _finalize_export(
        root,
        case_id=case.case_id,
        label=case.label,
        suffix=suffix,
        extra={
            "load_rate_mm_min": cfg.load_rate_mm_min,
            "mass_scaling_mode": case.mode,
            "dt_factor_vs_natural": case.dt_factor_vs_natural,
            "target_dt_s": target_dt,
            "natural_stable_dt_s": cfg.natural_stable_dt_s,
            "no_mass_scaling": case.no_mass_scaling,
        },
    )


def build_qs_opt_export_argv(
    root: Path,
    cfg: QsOptStudyConfig,
    case: QsOptCase,
    *,
    mesh_inp: Path | None = None,
) -> tuple[list[str], str]:
    mesh = cfg.mesh
    phy = cfg.physics
    strain_pct = int(round(float(phy.strain) * 100))
    suffix = case.suffix(mesh, strain_pct=strain_pct)
    target_dt = cfg.target_dt_s(case)
    phy_ms = replace(
        phy,
        no_mass_scaling=False,
        mass_scaling_mode="below_min",
        mass_scaling_factor=None,
        mass_scaling_dt=target_dt,
        explicit_dt=float(target_dt),
        explicit_dt_mode="automatic",
    )
    argv = _base_export_argv(
        root,
        phy=phy_ms,
        mesh_element_type=mesh.element_type,
        mesh_seed_mm=mesh.seed_mm,
        mesh_rods=mesh.rods_per_diameter,
        mesh_quality=mesh.mesh_quality,
        mesh_vtopo=mesh.virtual_topology,
        case_suffix=suffix,
        load_rate_mm_min=case.load_rate_mm_min,
        mesh_inp=mesh_inp,
        reuse_mesh_cfg=mesh.reuse_mesh_inp,
    )
    return argv, suffix


def export_qs_opt_case(
    root: Path,
    cfg: QsOptStudyConfig,
    case: QsOptCase,
    *,
    mesh_inp: Path | None = None,
) -> dict:
    """Export or alias an existing completed job (Case A → MS5)."""
    if case.reuse_job_slug:
        slug = case.reuse_job_slug
        export_dir = root / "output" / "export" / slug
        job_inp = export_dir / f"{slug}.inp"
        job_odb = root / "output" / "jobs" / slug / f"{slug}.odb"
        if not job_inp.is_file() and not job_odb.is_file():
            raise FileNotFoundError(
                f"reuse_job_slug={slug} missing export INP and job ODB"
            )
        # Prefer existing export; if only job exists, use job INP.
        if not job_inp.is_file():
            job_inp = root / "output" / "jobs" / slug / f"{slug}.inp"
            export_dir = job_inp.parent
        mesh_out = export_dir / f"{slug}_cae_mesh.inp"
        if not mesh_out.is_file():
            # Fall back to study default mesh path
            mesh_out = Path(cfg.mesh.reuse_mesh_inp) if cfg.mesh.reuse_mesh_inp else mesh_out
            if mesh_out and not mesh_out.is_absolute():
                mesh_out = root / mesh_out
        print(f"[export] {case.case_id} REUSE slug={slug}", flush=True)
        return {
            "case_id": case.case_id,
            "label": case.label,
            "slug": slug,
            "suffix": "REUSE",
            "export_dir": str(export_dir),
            "job_inp": str(job_inp),
            "mesh_inp": str(mesh_out) if mesh_out and Path(mesh_out).is_file() else None,
            "meta_json": str(export_dir / f"{slug}_meta.json"),
            "load_rate_mm_min": case.load_rate_mm_min,
            "ms_dt_factor": case.ms_dt_factor,
            "target_dt_s": cfg.target_dt_s(case),
            "reused": True,
        }

    argv, suffix = build_qs_opt_export_argv(root, cfg, case, mesh_inp=mesh_inp)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    target_dt = cfg.target_dt_s(case)
    print(
        f"[export] {case.case_id} {case.label} target_dt={target_dt:g}",
        flush=True,
    )
    print("  " + " ".join(argv[-16:]), flush=True)
    proc = subprocess.run(argv, cwd=str(root), env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"export failed for {case.case_id} rc={proc.returncode}")
    return _finalize_export(
        root,
        case_id=case.case_id,
        label=case.label,
        suffix=suffix,
        extra={
            "load_rate_mm_min": case.load_rate_mm_min,
            "ms_dt_factor": case.ms_dt_factor,
            "target_dt_s": target_dt,
            "natural_stable_dt_s": cfg.natural_stable_dt_s,
            "mass_scaling_mode": "below_min",
            "reused": False,
        },
    )
