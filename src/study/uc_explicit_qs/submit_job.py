"""Submit and monitor Abaqus/Explicit jobs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from typing import Any


def resolve_abaqus_cmd(configured: str = "abaqus") -> str:
    """Prefer explicit SIMULIA Commands path on Windows when bare name fails."""
    if configured and configured != "abaqus" and Path(configured).is_file():
        return configured
    candidates = [
        Path(r"D:\Apps\SIMULIA\Commands\abaqus.bat"),
        Path(r"C:\SIMULIA\Commands\abaqus.bat"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    # Fall back to PATH lookup
    from shutil import which

    hit = which("abaqus") or which("abaqus.bat")
    if hit:
        return hit
    return configured


def job_paths(root: Path, slug: str) -> dict[str, Path]:
    job_dir = root / "output" / "jobs" / slug
    return {
        "job_dir": job_dir,
        "inp": job_dir / f"{slug}.inp",
        "sta": job_dir / f"{slug}.sta",
        "odb": job_dir / f"{slug}.odb",
        "dat": job_dir / f"{slug}.dat",
        "lck": job_dir / f"{slug}.lck",
    }


def is_completed(sta: Path) -> bool:
    if not sta.is_file():
        return False
    txt = sta.read_text(encoding="utf-8", errors="ignore")
    return "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in txt


def is_oom(dat: Path) -> bool:
    if not dat.is_file():
        return False
    txt = dat.read_text(encoding="utf-8", errors="ignore")
    return (
        "out-of-memory" in txt.lower()
        or "memory allocation request failed" in txt.lower()
    )


def prepare_job_dir(root: Path, slug: str, export_inp: Path) -> dict[str, Path]:
    paths = job_paths(root, slug)
    paths["job_dir"].mkdir(parents=True, exist_ok=True)
    # Stale locks from killed/viewer sessions block resubmit.
    for lck in paths["job_dir"].glob("*.lck"):
        try:
            lck.unlink()
            print(f"[submit] removed stale lock {lck.name}", flush=True)
        except OSError as exc:
            print(f"[submit] WARN could not remove {lck}: {exc}", flush=True)
    shutil.copy2(export_inp, paths["inp"])
    return paths


def submit_job(
    root: Path,
    cfg: Any,
    slug: str,
    export_inp: Path,
    *,
    skip_if_completed: bool = True,
    double: str | None = None,
) -> dict:
    paths = prepare_job_dir(root, slug, Path(export_inp))
    if skip_if_completed and is_completed(paths["sta"]) and paths["odb"].is_file():
        print(f"[submit] SKIP {slug} already COMPLETED", flush=True)
        return {
            "slug": slug,
            "status": "skipped_completed",
            "job_dir": str(paths["job_dir"]),
            "odb": str(paths["odb"]),
            "sta": str(paths["sta"]),
        }

    abq = resolve_abaqus_cmd(cfg.abaqus_cmd)
    print(
        f"[submit] {slug} cpus={cfg.cpus} memory={cfg.memory_mb} "
        f"cwd={paths['job_dir']} abq={abq}",
        flush=True,
    )
    cmd = [
        abq,
        f"job={slug}",
        f"input={slug}.inp",
        f"cpus={cfg.cpus}",
        f"memory={cfg.memory_mb}",
        "interactive",
    ]
    # Explicit long QS jobs (no / weak mass scaling) often need DP to pass
    # the >20M-increment safeguard.
    dp = double or getattr(cfg, "abaqus_double", None)
    if dp:
        cmd.insert(-1, f"double={dp}")
    env = os.environ.copy()
    simulia = Path(r"D:\Apps\SIMULIA\Commands")
    if simulia.is_dir():
        env["PATH"] = str(simulia) + os.pathsep + env.get("PATH", "")
    # On Windows, .bat must run via cmd /c when CreateProcess cannot launch it.
    if abq.lower().endswith(".bat"):
        cmd = ["cmd", "/c", abq, *cmd[1:]]
    proc = subprocess.run(cmd, cwd=str(paths["job_dir"]), env=env, check=False)
    ok = is_completed(paths["sta"]) and paths["odb"].is_file()
    oom = is_oom(paths["dat"])
    if not ok:
        reason = "OOM" if oom else f"exit={proc.returncode}"
        raise RuntimeError(f"submit failed for {slug} ({reason})")
    print(f"[submit] DONE {slug}", flush=True)
    return {
        "slug": slug,
        "status": "completed",
        "job_dir": str(paths["job_dir"]),
        "odb": str(paths["odb"]),
        "sta": str(paths["sta"]),
        "returncode": proc.returncode,
    }
