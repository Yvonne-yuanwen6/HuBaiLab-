"""Orchestrate export → submit → extract → metrics → compare."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from src.study.uc_explicit_qs.config import (
    MassScaleStudyConfig,
    QsOptStudyConfig,
    StudyConfig,
    resolve_path,
)
from src.study.uc_explicit_qs.deform_snapshots import (
    plot_deform_snapshots,
    summarize_snap_proxy,
)
from src.study.uc_explicit_qs.export_case import (
    export_case,
    export_mass_scale_case,
    export_qs_opt_case,
)
from src.study.uc_explicit_qs.extract_results import extract_case
from src.study.uc_explicit_qs.locate_element import write_element_report
from src.study.uc_explicit_qs.metrics import evaluate_case
from src.study.uc_explicit_qs.paper_pack import write_paper_pack
from src.study.uc_explicit_qs.plot_compare import (
    write_comparison,
    write_mass_scale_comparison,
    write_qs_opt_comparison,
)
from src.study.uc_explicit_qs.submit_job import (
    is_completed,
    job_paths,
    resolve_abaqus_cmd,
    submit_job,
)


def run_study(
    root: Path,
    cfg: StudyConfig,
    *,
    modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    do = tuple(modes or cfg.modes)
    if "all" in do:
        do = ("export", "submit", "post", "compare")

    report_dir = root / "output" / "reports" / cfg.name
    report_dir.mkdir(parents=True, exist_ok=True)
    state_path = report_dir / f"{cfg.name}_state.json"

    state: dict[str, Any] = {
        "study": cfg.name,
        "config": cfg.to_dict(),
        "cases": {},
    }
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.setdefault("cases", {})
        except (OSError, json.JSONDecodeError):
            pass

    # Prefer shared mesh from config, else first successful mesh in this study.
    shared_mesh: Path | None = None
    if cfg.mesh.reuse_mesh_inp:
        shared_mesh = resolve_path(root, cfg.mesh.reuse_mesh_inp)
        if not shared_mesh.is_file():
            print(f"[warn] reuse_mesh_inp missing: {shared_mesh}", flush=True)
            shared_mesh = None

    cases_out: list[dict[str, Any]] = []
    for rate_case in cfg.rate_cases():
        entry = dict(state.get("cases", {}).get(rate_case.case_id) or {})
        entry.update(
            {
                "case_id": rate_case.case_id,
                "label": rate_case.label,
                "load_rate_mm_min": rate_case.load_rate_mm_min,
            }
        )

        if "export" in do:
            mesh_for_export = shared_mesh
            info = export_case(root, cfg, rate_case, mesh_inp=mesh_for_export)
            entry.update(info)
            if info.get("mesh_inp") and shared_mesh is None:
                shared_mesh = Path(info["mesh_inp"])
            state["cases"][rate_case.case_id] = entry
            _save_state(state_path, state)

        slug = entry.get("slug")
        if not slug:
            raise RuntimeError(f"{rate_case.case_id}: missing slug — run export first")

        if "submit" in do:
            job = submit_job(
                root,
                cfg,
                slug,
                Path(entry["job_inp"]),
            )
            entry["job"] = job
            state["cases"][rate_case.case_id] = entry
            _save_state(state_path, state)

        if "post" in do:
            odb = root / "output" / "jobs" / slug / f"{slug}.odb"
            meta = Path(entry.get("meta_json") or "")
            if not meta.is_file():
                meta = root / "output" / "export" / slug / f"{slug}_meta.json"
            paths = extract_case(root, cfg, slug, odb=odb, meta_json=meta)
            entry["post"] = paths
            evaluation = evaluate_case(
                stress_strain_csv=Path(paths["stress_strain_csv"]),
                energy_csv=Path(paths["energy_csv"]),
                ke_ie_limit=cfg.ke_ie_limit,
            )
            # Drop heavy arrays from state.json; keep for compare stage in-memory.
            entry["evaluation_summary"] = {
                "fu": evaluation["fu"],
                "energy": evaluation["energy"],
            }
            entry["_evaluation_full"] = evaluation
            state["cases"][rate_case.case_id] = {
                k: v for k, v in entry.items() if not k.startswith("_")
            }
            _save_state(state_path, state)

        cases_out.append(entry)

    compare_paths: dict[str, str] = {}
    if "compare" in do:
        compare_cases = []
        for entry in cases_out:
            c = dict(entry)
            if "_evaluation_full" in c:
                c["evaluation"] = c.pop("_evaluation_full")
            elif "post" in c:
                # Recompute from CSV if only summary in state
                c["evaluation"] = evaluate_case(
                    stress_strain_csv=Path(c["post"]["stress_strain_csv"]),
                    energy_csv=Path(c["post"]["energy_csv"]),
                    ke_ie_limit=cfg.ke_ie_limit,
                )
            compare_cases.append(c)
        compare_paths = write_comparison(
            compare_cases,
            report_dir,
            study_name=cfg.name,
            ke_ie_limit=cfg.ke_ie_limit,
        )
        state["compare"] = compare_paths
        _save_state(state_path, state)

    return {
        "study": cfg.name,
        "report_dir": str(report_dir),
        "state_json": str(state_path),
        "cases": [
            {k: v for k, v in e.items() if not k.startswith("_")} for e in cases_out
        ],
        "compare": compare_paths,
    }


def run_mass_scale_study(
    root: Path,
    cfg: MassScaleStudyConfig,
    *,
    modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Mass-scaling sensitivity: MS0 (none) / MS5 / MS10 at fixed load rate."""
    root = Path(root).resolve()
    do = tuple(modes or cfg.modes)
    if "all" in do:
        do = ("export", "submit", "post", "compare")

    report_dir = root / "output" / "reports" / cfg.name
    report_dir.mkdir(parents=True, exist_ok=True)
    state_path = report_dir / f"{cfg.name}_state.json"

    state: dict[str, Any] = {
        "study": cfg.name,
        "config": cfg.to_dict(),
        "cases": {},
    }
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.setdefault("cases", {})
        except (OSError, json.JSONDecodeError):
            pass

    shared_mesh: Path | None = None
    if cfg.mesh.reuse_mesh_inp:
        shared_mesh = resolve_path(root, cfg.mesh.reuse_mesh_inp)
        if not shared_mesh.is_file():
            print(f"[warn] reuse_mesh_inp missing: {shared_mesh}", flush=True)
            shared_mesh = None

    cases_out: list[dict[str, Any]] = []
    for ms_case in cfg.mass_scale_cases():
        entry = dict(state.get("cases", {}).get(ms_case.case_id) or {})
        entry.update(
            {
                "case_id": ms_case.case_id,
                "label": ms_case.label,
                "load_rate_mm_min": cfg.load_rate_mm_min,
                "mass_scaling_mode": ms_case.mode,
                "dt_factor_vs_natural": ms_case.dt_factor_vs_natural,
                "target_dt_s": cfg.target_dt_s(ms_case),
                "natural_stable_dt_s": cfg.natural_stable_dt_s,
                "no_mass_scaling": ms_case.no_mass_scaling,
            }
        )

        if "export" in do:
            info = export_mass_scale_case(
                root, cfg, ms_case, mesh_inp=shared_mesh
            )
            entry.update(info)
            if info.get("mesh_inp") and shared_mesh is None:
                shared_mesh = Path(info["mesh_inp"])
            state["cases"][ms_case.case_id] = entry
            _save_state(state_path, state)

        slug = entry.get("slug")
        if not slug:
            raise RuntimeError(f"{ms_case.case_id}: missing slug — run export first")

        if "submit" in do:
            try:
                # No-MS Explicit QS often exceeds Abaqus' 20M-inc SP limit.
                dp = "both" if ms_case.no_mass_scaling else None
                job = submit_job(
                    root, cfg, slug, Path(entry["job_inp"]), double=dp
                )
                entry["job"] = job
            except RuntimeError as exc:
                entry["job"] = {"slug": slug, "status": "failed", "error": str(exc)}
                print(f"[submit] FAIL {ms_case.case_id}: {exc}", flush=True)
            state["cases"][ms_case.case_id] = entry
            _save_state(state_path, state)

        if "post" in do:
            odb = root / "output" / "jobs" / slug / f"{slug}.odb"
            if not odb.is_file():
                entry["post"] = {"status": "missing_odb"}
                print(f"[post] SKIP {ms_case.case_id}: no ODB", flush=True)
            else:
                meta = Path(entry.get("meta_json") or "")
                if not meta.is_file():
                    meta = root / "output" / "export" / slug / f"{slug}_meta.json"
                paths = extract_case(root, cfg, slug, odb=odb, meta_json=meta)
                entry["post"] = paths
                evaluation = evaluate_case(
                    stress_strain_csv=Path(paths["stress_strain_csv"]),
                    energy_csv=Path(paths["energy_csv"]),
                    ke_ie_limit=cfg.ke_ie_limit,
                )
                entry["evaluation_summary"] = {
                    "fu": evaluation["fu"],
                    "energy": evaluation["energy"],
                }
                entry["_evaluation_full"] = evaluation
            state["cases"][ms_case.case_id] = {
                k: v for k, v in entry.items() if not k.startswith("_")
            }
            _save_state(state_path, state)

        cases_out.append(entry)

    compare_paths: dict[str, str] = {}
    if "compare" in do:
        compare_cases = []
        for entry in cases_out:
            c = dict(entry)
            if "_evaluation_full" in c:
                c["evaluation"] = c.pop("_evaluation_full")
            elif c.get("post") and c["post"].get("stress_strain_csv"):
                c["evaluation"] = evaluate_case(
                    stress_strain_csv=Path(c["post"]["stress_strain_csv"]),
                    energy_csv=Path(c["post"]["energy_csv"]),
                    ke_ie_limit=cfg.ke_ie_limit,
                )
            else:
                continue
            compare_cases.append(c)
        if compare_cases:
            compare_paths = write_mass_scale_comparison(
                compare_cases,
                report_dir,
                study_name=cfg.name,
                ke_ie_limit=cfg.ke_ie_limit,
                peak_force_tol=cfg.peak_force_tol,
                baseline_case_id=cfg.baseline_case_id,
            )
            state["compare"] = compare_paths
            _save_state(state_path, state)

    return {
        "study": cfg.name,
        "report_dir": str(report_dir),
        "state_json": str(state_path),
        "cases": [
            {k: v for k, v in e.items() if not k.startswith("_")} for e in cases_out
        ],
        "compare": compare_paths,
    }


def _extract_deform_frames(
    root: Path,
    cfg: Any,
    slug: str,
    odb: Path,
    *,
    fractions: tuple[float, ...],
) -> Path:
    out_dir = root / "output" / "post" / slug / "deform_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    script = root / "scripts" / "extract_odb_deform_frames_py2.py"
    abq = resolve_abaqus_cmd(getattr(cfg, "abaqus_cmd", "abaqus"))
    frac_s = ",".join(str(x) for x in fractions)
    cmd = [
        abq,
        "python",
        str(script),
        str(odb),
        str(out_dir),
        "--fractions",
        frac_s,
        "--step",
        "Compression",
    ]
    if abq.lower().endswith(".bat"):
        cmd = ["cmd", "/c", *cmd]
    env = os.environ.copy()
    simulia = Path(r"D:\Apps\SIMULIA\Commands")
    if simulia.is_dir():
        env["PATH"] = str(simulia) + os.pathsep + env.get("PATH", "")
    print(f"[deform] {slug} fractions={frac_s}", flush=True)
    proc = subprocess.run(cmd, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"deform extract failed rc={proc.returncode}")
    return out_dir


def run_qs_opt_study(
    root: Path,
    cfg: QsOptStudyConfig,
    *,
    modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """QS optimization A/B/C: rate × mild MS on C3D10M."""
    root = Path(root).resolve()
    do = tuple(modes or cfg.modes)
    if "all" in do:
        do = ("export", "submit", "post", "compare", "paper")

    report_dir = root / "output" / "reports" / cfg.name
    report_dir.mkdir(parents=True, exist_ok=True)
    state_path = report_dir / f"{cfg.name}_state.json"
    paper_dir = report_dir / "paper"

    state: dict[str, Any] = {
        "study": cfg.name,
        "config": cfg.to_dict(),
        "cases": {},
    }
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.setdefault("cases", {})
        except (OSError, json.JSONDecodeError):
            pass

    shared_mesh: Path | None = None
    if cfg.mesh.reuse_mesh_inp:
        shared_mesh = resolve_path(root, cfg.mesh.reuse_mesh_inp)
        if not shared_mesh.is_file():
            print(f"[warn] reuse_mesh_inp missing: {shared_mesh}", flush=True)
            shared_mesh = None

    # Mesh validation / failed element (always refresh on export/paper/all)
    elem_report = None
    if shared_mesh and shared_mesh.is_file():
        elem_path = report_dir / f"elem_{cfg.failed_elem_id}_location.json"
        elem_report = write_element_report(
            shared_mesh, int(cfg.failed_elem_id), elem_path, L_mm=cfg.physics.L_mm
        )
        state["failed_element"] = elem_report
        _save_state(state_path, state)

    cases_out: list[dict[str, Any]] = []
    for qs_case in cfg.qs_opt_cases():
        entry = dict(state.get("cases", {}).get(qs_case.case_id) or {})
        entry.update(
            {
                "case_id": qs_case.case_id,
                "label": qs_case.label,
                "load_rate_mm_min": qs_case.load_rate_mm_min,
                "ms_dt_factor": qs_case.ms_dt_factor,
                "target_dt_s": cfg.target_dt_s(qs_case),
                "natural_stable_dt_s": cfg.natural_stable_dt_s,
                "reuse_job_slug": qs_case.reuse_job_slug,
            }
        )

        if "export" in do:
            info = export_qs_opt_case(root, cfg, qs_case, mesh_inp=shared_mesh)
            entry.update(info)
            if info.get("mesh_inp") and shared_mesh is None:
                shared_mesh = Path(info["mesh_inp"])
            state["cases"][qs_case.case_id] = entry
            _save_state(state_path, state)

        slug = entry.get("slug")
        if not slug:
            raise RuntimeError(f"{qs_case.case_id}: missing slug — run export first")

        if "submit" in do:
            # Skip solve when reusing a completed job (Case A → MS5).
            paths = job_paths(root, slug)
            if qs_case.reuse_job_slug and is_completed(paths["sta"]) and paths["odb"].is_file():
                entry["job"] = {
                    "slug": slug,
                    "status": "skipped_reused",
                    "odb": str(paths["odb"]),
                }
                print(f"[submit] SKIP {qs_case.case_id} reused completed {slug}", flush=True)
            else:
                try:
                    job = submit_job(root, cfg, slug, Path(entry["job_inp"]))
                    entry["job"] = job
                except RuntimeError as exc:
                    entry["job"] = {"slug": slug, "status": "failed", "error": str(exc)}
                    print(f"[submit] FAIL {qs_case.case_id}: {exc}", flush=True)
            state["cases"][qs_case.case_id] = entry
            _save_state(state_path, state)

        if "post" in do:
            odb = root / "output" / "jobs" / slug / f"{slug}.odb"
            if not odb.is_file():
                entry["post"] = {"status": "missing_odb"}
                print(f"[post] SKIP {qs_case.case_id}: no ODB", flush=True)
            else:
                meta = Path(entry.get("meta_json") or "")
                if not meta.is_file():
                    meta = root / "output" / "export" / slug / f"{slug}_meta.json"
                paths = extract_case(root, cfg, slug, odb=odb, meta_json=meta)
                entry["post"] = paths
                evaluation = evaluate_case(
                    stress_strain_csv=Path(paths["stress_strain_csv"]),
                    energy_csv=Path(paths["energy_csv"]),
                    ke_ie_limit=cfg.ke_ie_limit,
                )
                entry["evaluation_summary"] = {
                    "fu": evaluation["fu"],
                    "energy": evaluation["energy"],
                }
                entry["snap_proxy"] = summarize_snap_proxy(evaluation.get("fu_points") or [])
                entry["_evaluation_full"] = evaluation
                # Deformation snapshots for snap-through judgment
                try:
                    deform_dir = _extract_deform_frames(
                        root,
                        cfg,
                        slug,
                        odb,
                        fractions=cfg.snapshot_fractions,
                    )
                    pngs = plot_deform_snapshots(
                        deform_dir,
                        report_dir / "deform",
                        case_id=qs_case.case_id,
                        title_prefix=f"{cfg.name} ",
                    )
                    entry["deform_dir"] = str(deform_dir)
                    entry["deform_pngs"] = pngs
                except Exception as exc:  # noqa: BLE001 — keep post going
                    print(f"[deform] WARN {qs_case.case_id}: {exc}", flush=True)
                    entry["deform_error"] = str(exc)
            state["cases"][qs_case.case_id] = {
                k: v for k, v in entry.items() if not k.startswith("_")
            }
            _save_state(state_path, state)

        cases_out.append(entry)

    compare_paths: dict[str, str] = {}
    if "compare" in do:
        compare_cases = []
        for entry in cases_out:
            c = dict(entry)
            if "_evaluation_full" in c:
                c["evaluation"] = c.pop("_evaluation_full")
            elif c.get("post") and c["post"].get("stress_strain_csv"):
                c["evaluation"] = evaluate_case(
                    stress_strain_csv=Path(c["post"]["stress_strain_csv"]),
                    energy_csv=Path(c["post"]["energy_csv"]),
                    ke_ie_limit=cfg.ke_ie_limit,
                )
            else:
                continue
            compare_cases.append(c)
        if compare_cases:
            compare_paths = write_qs_opt_comparison(
                compare_cases,
                report_dir,
                study_name=cfg.name,
                ke_ie_limit=cfg.ke_ie_limit,
                peak_force_tol=cfg.peak_force_tol,
                baseline_case_id=cfg.baseline_case_id,
            )
            state["compare"] = compare_paths
            _save_state(state_path, state)

    paper_paths: dict[str, str] = {}
    if "paper" in do or "compare" in do:
        # Refresh elem report if missing
        if elem_report is None and shared_mesh and shared_mesh.is_file():
            elem_report = write_element_report(
                shared_mesh,
                int(cfg.failed_elem_id),
                report_dir / f"elem_{cfg.failed_elem_id}_location.json",
                L_mm=cfg.physics.L_mm,
            )
        paper_paths = write_paper_pack(
            report_dir=report_dir,
            study_name=cfg.name,
            cfg_dict=cfg.to_dict(),
            cases=[
                {k: v for k, v in e.items() if not k.startswith("_")} for e in cases_out
            ],
            compare_paths=compare_paths or state.get("compare") or {},
            elem_report=elem_report or state.get("failed_element"),
            lattice_params={
                "element_type": cfg.mesh.element_type,
                "mesh_seed_mm": cfg.mesh.seed_mm,
                "rods_per_diameter": cfg.mesh.rods_per_diameter,
                "mass_scaling": "BELOW MIN dt = factor × natural_stable_dt",
                "natural_stable_dt_s": cfg.natural_stable_dt_s,
                "cases": [
                    {
                        "id": c.case_id,
                        "rate_mm_min": c.load_rate_mm_min,
                        "ms_factor": c.ms_dt_factor,
                    }
                    for c in cfg.qs_opt_cases()
                ],
            },
        )
        state["paper"] = paper_paths
        _save_state(state_path, state)

    return {
        "study": cfg.name,
        "report_dir": str(report_dir),
        "paper_dir": str(paper_dir),
        "state_json": str(state_path),
        "cases": [
            {k: v for k, v in e.items() if not k.startswith("_")} for e in cases_out
        ],
        "compare": compare_paths,
        "paper": paper_paths,
    }


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
