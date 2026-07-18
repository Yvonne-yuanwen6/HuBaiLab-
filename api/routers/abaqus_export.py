"""Abaqus export / mesh task routes."""

from __future__ import annotations

import sys

from fastapi import APIRouter

from api.schemas.abaqus import ExportRequest, TaskResponse
from api.services.task_manager import start_task
from src.abaqus.settings import HuBaiAbaqusSettings

router = APIRouter(prefix="/api/abaqus", tags=["abaqus-export"])


def _python_command(settings: HuBaiAbaqusSettings) -> list[str]:
    argv = settings.to_export_argv()
    return [sys.executable, *argv]


@router.post("/export", response_model=TaskResponse)
def start_export(body: ExportRequest) -> TaskResponse:
    settings = HuBaiAbaqusSettings.from_dict(body.settings)
    task = start_task(_python_command(settings), slug=settings.slug_preview())
    return TaskResponse(**task)


@router.post("/mesh", response_model=TaskResponse)
def start_mesh(body: ExportRequest) -> TaskResponse:
    """Run the CAD→CAE mesh/export pipeline (same script as /export)."""
    data = dict(body.settings or {})
    # Prefer an explicit mesh location; default to server mesh when neither set.
    if not data.get("mesh_locally") and not data.get("mesh_on_server"):
        data["mesh_on_server"] = True
        data["mesh_locally"] = False
    settings = HuBaiAbaqusSettings.from_dict(data)
    task = start_task(_python_command(settings), slug=settings.slug_preview())
    return TaskResponse(**task)
