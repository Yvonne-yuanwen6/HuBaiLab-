"""Call Abaqus Python extractors and normalize CSV outputs."""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

from typing import Any

from src.study.uc_explicit_qs.submit_job import resolve_abaqus_cmd


def _abaqus_python(cfg: Any, script: Path, args: list[str]) -> None:
    abq = resolve_abaqus_cmd(cfg.abaqus_cmd)
    cmd = [abq, "python", str(script), *args]
    if abq.lower().endswith(".bat"):
        cmd = ["cmd", "/c", abq, "python", str(script), *args]
    env = os.environ.copy()
    simulia = Path(r"D:\Apps\SIMULIA\Commands")
    if simulia.is_dir():
        env["PATH"] = str(simulia) + os.pathsep + env.get("PATH", "")
    print("[extract]", " ".join(cmd[-6:]), flush=True)
    proc = subprocess.run(cmd, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"abaqus python failed rc={proc.returncode}: {script.name}")


def extract_case(
    root: Path,
    cfg: Any,
    slug: str,
    *,
    odb: Path,
    meta_json: Path,
) -> dict[str, str]:
    post_dir = root / "output" / "post" / slug
    post_dir.mkdir(parents=True, exist_ok=True)
    history_csv = post_dir / f"{slug}_history.csv"
    energy_csv = post_dir / f"{slug}_energy.csv"
    ss_csv = post_dir / f"{slug}_stress_strain.csv"
    ss_raw = post_dir / f"{slug}_stress_strain_raw.csv"

    # Combined RF3/U3/energies (preferred).
    uc_script = root / "scripts" / "extract_odb_uc_qs_py2.py"
    if uc_script.is_file():
        _abaqus_python(
            cfg,
            uc_script,
            [str(odb), str(history_csv), "Compression"],
        )
        # Also write energy-only CSV for downstream compatibility.
        _history_to_energy(history_csv, energy_csv)
    else:
        energy_script = root / "scripts" / "extract_odb_energy_py2.py"
        _abaqus_python(
            cfg,
            energy_script,
            [str(odb), str(energy_csv), "Compression"],
        )

    curve_script = root / "scripts" / "extract_stress_strain_from_odb.py"
    _abaqus_python(
        cfg,
        curve_script,
        [
            "--odb",
            str(odb),
            "--meta",
            str(meta_json),
            "--csv",
            str(ss_csv),
            "--raw-csv",
            str(ss_raw),
            "--force-mode",
            "paper",
            "--curve-method",
            "paper",
        ],
    )
    return {
        "post_dir": str(post_dir),
        "history_csv": str(history_csv) if history_csv.is_file() else "",
        "energy_csv": str(energy_csv),
        "stress_strain_csv": str(ss_csv),
        "stress_strain_raw_csv": str(ss_raw),
    }


def _history_to_energy(history_csv: Path, energy_csv: Path) -> None:
    if not history_csv.is_file():
        return
    with history_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    with energy_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time_s", "ALLKE_J", "ALLIE_J", "ALLAE_J"])
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "time_s": r.get("time_s", ""),
                    "ALLKE_J": r.get("ALLKE_J", r.get("ALLKE", "")),
                    "ALLIE_J": r.get("ALLIE_J", r.get("ALLIE", "")),
                    "ALLAE_J": r.get("ALLAE_J", r.get("ALLAE", "")),
                }
            )
