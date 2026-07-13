"""Abaqus job status, submit, sync routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.schemas.abaqus import (
    JobStatusResponse,
    StopRequest,
    SubmitRequest,
    SyncRemoteRequest,
    TaskResponse,
)
from api.services.remote import run_remote_stop, run_remote_submit, sync_remote_job_files
from api.services.task_manager import start_sync_result, start_task
from src.abaqus.case_manage import stop_local_job
from src.abaqus.job_status import inspect_job
from src.abaqus.sta_parser import format_eta
from src.paths import PROJECT_ROOT, job_dir_for_slug

router = APIRouter(prefix="/api/abaqus/jobs", tags=["abaqus-jobs"])


def _progress_to_response(slug: str, *, remote_watch: bool = False) -> JobStatusResponse:
    progress = inspect_job(slug, remote_watch=remote_watch)
    eta = None
    if progress.state.value == "RUNNING" and progress.step_time_s:
        eta = format_eta(progress.sim_time_s, progress.wall_seconds, progress.step_time_s)
    return JobStatusResponse(
        slug=slug,
        state=progress.state.value,
        failure_reason=progress.failure_reason,
        lck_exists=progress.lck_exists,
        frame=progress.frame,
        frames_total=progress.frames_total,
        sim_time_s=progress.sim_time_s,
        total_time_s=progress.total_time_s,
        ke=progress.ke,
        ie=progress.ie,
        progress_pct=progress.progress_pct,
        step_time_s=progress.step_time_s,
        target_strain=progress.target_strain,
        eta=eta,
    )


@router.get("/{slug}/status", response_model=JobStatusResponse)
def job_status(
    slug: str,
    sync_remote: bool = Query(False, description="Pull .sta/.lck from remote before parsing"),
    remote_host: str = "",
    remote_root: str = "",
) -> JobStatusResponse:
    if sync_remote:
        sync_remote_job_files(slug, remote_host=remote_host, remote_root=remote_root)
    return _progress_to_response(slug, remote_watch=sync_remote)


@router.get("/{slug}/logs")
def job_logs(slug: str, lines: int = 80) -> dict:
    job_dir = job_dir_for_slug(slug)
    sta = job_dir / f"{slug}.sta"
    submit_log = job_dir / f"{slug}_submit.log"
    result: dict = {"slug": slug, "sta_tail": "", "submit_log_tail": ""}
    if sta.is_file():
        text = sta.read_text(encoding="utf-8", errors="replace").splitlines()
        result["sta_tail"] = "\n".join(text[-lines:])
    if submit_log.is_file():
        text = submit_log.read_text(encoding="utf-8", errors="replace").splitlines()
        result["submit_log_tail"] = "\n".join(text[-lines:])
    return result


@router.post("/{slug}/submit", response_model=TaskResponse)
def submit_job(slug: str, body: SubmitRequest) -> TaskResponse:
    export_inp = PROJECT_ROOT / "output" / "export" / slug / f"{slug}.inp"
    if not export_inp.is_file():
        raise HTTPException(status_code=400, detail=f"Missing INP for slug: {slug}")

    if body.target == "remote":
        command = run_remote_submit(
            slug,
            cpus=body.cpus,
            memory_mb=body.memory_mb,
            recover=body.recover,
            restart_from=body.restart_from,
            background=body.background,
        )
    else:
        submit_sh = PROJECT_ROOT / "scripts" / "linux" / "submit_job.sh"
        command = [
            "bash",
            str(submit_sh),
            "--slug",
            slug,
            "--cpus",
            str(body.cpus),
            "--memory-mb",
            str(body.memory_mb),
        ]
        if body.recover:
            command.append("--recover")
        if body.restart_from:
            command.extend(["--restart-from", body.restart_from])
        if body.background:
            command.append("--background")

    task = start_task(command, slug=slug)
    return TaskResponse(**task)


@router.post("/{slug}/sync-remote")
def sync_remote(slug: str, body: SyncRemoteRequest | None = None) -> dict:
    body = body or SyncRemoteRequest()
    return sync_remote_job_files(
        slug,
        remote_host=body.remote_host,
        remote_root=body.remote_root,
    )


@router.post("/{slug}/stop", response_model=TaskResponse)
def stop_job(slug: str, body: StopRequest | None = None) -> TaskResponse:
    body = body or StopRequest()
    if body.target == "remote":
        command = run_remote_stop(slug, remote_host=body.remote_host, remote_root=body.remote_root)
        task = start_task(command, slug=slug)
        return TaskResponse(**task)

    result = stop_local_job(slug)
    return TaskResponse(**start_sync_result(slug=slug, result=result))
