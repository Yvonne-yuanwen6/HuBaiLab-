"""Abaqus job state detection (ported from scripts/submit_helpers.ps1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.abaqus.sta_parser import parse_sta_tail
from src.paths import ABAQUS_JOBS, export_dir_for_slug, job_dir_for_slug


class JobState(str, Enum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class JobProgress:
    state: JobState
    slug: str
    sta_path: Path
    odb_path: Path
    lck_exists: bool
    failure_reason: str | None = None
    frame: int | None = None
    frames_total: int | None = None
    sim_time_s: float = 0.0
    total_time_s: float = 0.0
    ke: float | None = None
    ie: float | None = None
    wall_seconds: float = 0.0
    progress_pct: float = 0.0
    step_time_s: float | None = None
    target_strain: float | None = None


def _read_sta(sta_path: Path) -> str:
    if not sta_path.is_file():
        return ""
    return sta_path.read_text(encoding="utf-8", errors="replace")


def is_job_completed(sta_path: Path, odb_path: Path) -> bool:
    if not sta_path.is_file() or not odb_path.is_file():
        return False
    return "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in _read_sta(sta_path)


def get_sta_failure_summary(sta_path: Path | None) -> str | None:
    if sta_path is None or not sta_path.is_file():
        return None
    text = _read_sta(sta_path)
    if not text:
        return None
    if "deformation speed/wave speed" in text:
        return "deformation_speed"
    if "THE ANALYSIS HAS NOT BEEN COMPLETED" in text:
        return "not_completed"
    if "***ERROR" in text:
        return "abaqus_error"
    if "SOLUTION PROGRESS" in text:
        return "incomplete"
    return None


def detect_job_state(
    *,
    slug: str,
    job_dir: Path | None = None,
    remote_watch: bool = False,
) -> JobState:
    job_dir = job_dir or job_dir_for_slug(slug)
    sta = job_dir / f"{slug}.sta"
    odb = job_dir / f"{slug}.odb"
    lck = job_dir / f"{slug}.lck"

    if remote_watch and sta.is_file():
        if "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in _read_sta(sta):
            return JobState.COMPLETED

    if lck.is_file():
        return JobState.RUNNING

    if is_job_completed(sta, odb):
        return JobState.COMPLETED

    if sta.is_file() and not lck.is_file():
        text = _read_sta(sta)
        if "THE ANALYSIS HAS NOT BEEN COMPLETED" in text:
            return JobState.FAILED
        if "deformation speed/wave speed" in text:
            return JobState.FAILED
        if "***ERROR" in text:
            return JobState.FAILED

    if sta.is_file():
        return JobState.STOPPED
    return JobState.WAITING


def _load_meta(slug: str) -> dict | None:
    meta_path = export_dir_for_slug(slug) / f"{slug}_meta.json"
    if not meta_path.is_file():
        return None
    import json

    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def inspect_job(
    slug: str,
    *,
    remote_watch: bool = False,
    step_time_s: float | None = None,
    target_strain: float | None = None,
) -> JobProgress:
    job_dir = job_dir_for_slug(slug)
    sta = job_dir / f"{slug}.sta"
    odb = job_dir / f"{slug}.odb"
    lck = job_dir / f"{slug}.lck"

    meta = _load_meta(slug)
    step_time = step_time_s
    strain = target_strain
    if meta:
        if step_time is None and meta.get("step_time"):
            step_time = float(meta["step_time"])
        if strain is None and meta.get("reference_height_mm", 0) > 0:
            strain = float(meta.get("compression_displacement", 0)) / float(meta["reference_height_mm"])
        if meta.get("restart_continue"):
            rc = meta["restart_continue"]
            strain = float(rc.get("target_strain", strain or 0))
        elif meta.get("loading") and meta["loading"].get("continue_source_strain"):
            pass

    state = detect_job_state(slug=slug, job_dir=job_dir, remote_watch=remote_watch)
    failure = None
    if state == JobState.FAILED:
        failure = get_sta_failure_summary(sta)

    parsed = parse_sta_tail(sta) if sta.is_file() else None
    sim_s = parsed.sim_time_s if parsed else 0.0
    total_s = parsed.total_time_s if parsed else 0.0
    step_time = step_time or 480.0
    pct = min(100.0, 100.0 * sim_s / step_time) if step_time > 0 else 0.0

    return JobProgress(
        state=state,
        slug=slug,
        sta_path=sta,
        odb_path=odb,
        lck_exists=lck.is_file(),
        failure_reason=failure,
        frame=parsed.frame if parsed else None,
        frames_total=parsed.frames_total if parsed else None,
        sim_time_s=sim_s,
        total_time_s=total_s,
        ke=parsed.ke if parsed else None,
        ie=parsed.ie if parsed else None,
        wall_seconds=parsed.wall_seconds if parsed else 0.0,
        progress_pct=pct,
        step_time_s=step_time,
        target_strain=strain,
    )


def list_job_slugs() -> list[str]:
    if not ABAQUS_JOBS.is_dir():
        return []
    slugs: set[str] = set()
    for path in ABAQUS_JOBS.rglob("*.sta"):
        slugs.add(path.stem)
    for path in ABAQUS_JOBS.iterdir():
        if path.is_dir():
            slugs.add(path.name)
    return sorted(slugs)
