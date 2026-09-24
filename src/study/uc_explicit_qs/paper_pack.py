"""Package mesh + quasi-static validation artifacts for paper figures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def write_paper_pack(
    *,
    report_dir: Path,
    study_name: str,
    cfg_dict: dict[str, Any],
    cases: list[dict[str, Any]],
    compare_paths: dict[str, str],
    elem_report: dict[str, Any] | None,
    lattice_params: dict[str, Any] | None = None,
) -> dict[str, str]:
    paper = report_dir / "paper"
    paper.mkdir(parents=True, exist_ok=True)

    mesh_val = {
        "purpose": "mesh_validation",
        "element_type": (cfg_dict.get("mesh") or {}).get("element_type"),
        "seed_mm": (cfg_dict.get("mesh") or {}).get("seed_mm"),
        "rods_per_diameter": (cfg_dict.get("mesh") or {}).get("rods_per_diameter"),
        "failed_element": elem_report,
        "notes": [
            "C3D4 discarded; C3D10M retained for curved-rod bending.",
            "Element 12488 located for prior distortion failure diagnostics.",
        ],
    }
    mesh_json = paper / "mesh_validation.json"
    mesh_json.write_text(json.dumps(mesh_val, indent=2, default=str), encoding="utf-8")

    qs_rows = []
    for c in cases:
        ev = c.get("evaluation_summary") or {}
        if not ev and c.get("evaluation"):
            ev = {
                "fu": (c["evaluation"] or {}).get("fu"),
                "energy": (c["evaluation"] or {}).get("energy"),
            }
        qs_rows.append(
            {
                "case_id": c.get("case_id"),
                "label": c.get("label"),
                "load_rate_mm_min": c.get("load_rate_mm_min"),
                "ms_dt_factor": c.get("ms_dt_factor"),
                "target_dt_s": c.get("target_dt_s"),
                "slug": c.get("slug"),
                "fu": ev.get("fu"),
                "energy": ev.get("energy"),
                "snap_proxy": c.get("snap_proxy"),
                "deform_pngs": c.get("deform_pngs"),
            }
        )
    qs_val = {
        "purpose": "quasi_static_validation",
        "ke_ie_limit": cfg_dict.get("ke_ie_limit", 0.05),
        "peak_force_tol": cfg_dict.get("peak_force_tol", 0.05),
        "baseline_case_id": cfg_dict.get("baseline_case_id", "A"),
        "natural_stable_dt_s": cfg_dict.get("natural_stable_dt_s"),
        "cases": qs_rows,
        "criteria": {
            "qs_pass": "max KE/IE (IE>1% peak) < 5%",
            "force_stable": "|ΔFpeak| vs baseline < 5%",
        },
    }
    qs_json = paper / "qs_validation.json"
    qs_json.write_text(json.dumps(qs_val, indent=2, default=str), encoding="utf-8")

    if lattice_params:
        (paper / "param_interface.json").write_text(
            json.dumps(lattice_params, indent=2), encoding="utf-8"
        )

    copied = {}
    for key, src in (compare_paths or {}).items():
        p = Path(src)
        if p.is_file():
            dst = paper / p.name
            shutil.copy2(p, dst)
            copied[key] = str(dst)

    # Copy per-case deform grids if present
    deform_dir = paper / "deform_snapshots"
    deform_dir.mkdir(exist_ok=True)
    n_deform = 0
    for c in cases:
        for png in c.get("deform_pngs") or []:
            src = Path(png)
            if src.is_file():
                shutil.copy2(src, deform_dir / src.name)
                n_deform += 1

    readme = paper / "README.md"
    readme.write_text(
        "\n".join(
            [
                f"# {study_name} — paper validation pack",
                "",
                "## Mesh validation",
                "- `mesh_validation.json` — C3D10M settings + elem 12488 location/quality",
                "",
                "## Quasi-static validation",
                "- `qs_validation.json` — KE/IE, AE/IE, peak force, ΔF vs baseline",
                f"- `{study_name}_compare.png` — F–U + energy ratio curves",
                "",
                "## Snap-through / deformation",
                "- `deform_snapshots/` — 0/30/60/100% deformed shapes",
                "",
                f"Copied compare artifacts: {list(copied)}",
                f"Deform PNGs copied: {n_deform}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[paper] wrote {paper}", flush=True)
    return {
        "paper_dir": str(paper),
        "mesh_validation_json": str(mesh_json),
        "qs_validation_json": str(qs_json),
        "readme": str(readme),
    }
