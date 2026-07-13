"""Abaqus export task routes."""

from __future__ import annotations

from fastapi import APIRouter

from api.schemas.abaqus import ExportRequest, TaskResponse
from api.services.task_manager import get_task, start_task
from src.abaqus.settings import HuBaiAbaqusSettings

router = APIRouter(prefix="/api/abaqus", tags=["abaqus-export"])


@router.post("/export", response_model=TaskResponse)
def start_export(body: ExportRequest) -> TaskResponse:
    settings = HuBaiAbaqusSettings.from_dict(body.settings)
    command = settings.to_export_argv()
    task = start_task(command, slug=settings.slug_preview())
    return TaskResponse(**task)
