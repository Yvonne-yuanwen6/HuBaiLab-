"""Shared task status and dashboard routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from api.routers.abaqus_cases import case_activity_ts, list_cases_impl, select_dashboard_cases
from api.schemas.abaqus import DashboardSummary, SyncOutputResponse, TaskResponse
from api.services.remote import sync_remote_output_batch
from api.services.task_manager import get_task
from src.abaqus.trash import list_trash_items
from src.paths import ACTIVE_CASE_JSON

router = APIRouter(tags=["tasks"])

_DASHBOARD_HINT_LOCAL = (
    "仪表盘统计来自本机 output/。勾选「同步服务器 output」后点击刷新，将从服务器 scp 状态文件并纳入服务器 jobs 目录中的算例。"
)
_DASHBOARD_HINT_SYNCED = (
    "已从服务器同步：纳入远程 output/jobs 中的算例，并 scp .sta/.lck/_meta.json 到本机后统计。"
)


@router.get("/api/tasks/{task_id}", response_model=TaskResponse)
def task_status(task_id: str) -> TaskResponse:
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**task)


@router.post(
    "/api/abaqus/sync-output",
    response_model=SyncOutputResponse,
    tags=["abaqus-cases"],
    summary="同步服务器 output 状态文件",
)
def sync_output() -> SyncOutputResponse:
    """Pull remote job status files (non-blocking for dashboard GET)."""
    result = sync_remote_output_batch()
    return SyncOutputResponse(**result)


@router.get(
    "/api/abaqus/dashboard",
    response_model=DashboardSummary,
    tags=["abaqus-cases"],
)
def dashboard(
    discover_remote: bool = Query(
        False,
        description="Include remote output/jobs slugs in stats (after sync-output)",
    ),
) -> DashboardSummary:
    case_list = list_cases_impl(discover_remote=discover_remote)
    cases = case_list.cases
    running = sum(1 for c in cases if c.status == "RUNNING")
    completed = sum(1 for c in cases if c.status == "COMPLETED")
    failed = sum(1 for c in cases if c.status == "FAILED")
    active = None
    if ACTIVE_CASE_JSON.is_file():
        try:
            active = json.loads(ACTIVE_CASE_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            active = None
    recent = select_dashboard_cases(cases)
    return DashboardSummary(
        active_case=active,
        running_count=running,
        completed_count=completed,
        failed_count=failed,
        trash_count=len(list_trash_items()),
        recent_cases=recent,
        data_source="local+remote" if discover_remote else "local",
        data_source_label="本机 + 已同步远程" if discover_remote else "本机 output/",
        hint=_DASHBOARD_HINT_SYNCED if discover_remote else _DASHBOARD_HINT_LOCAL,
    )
