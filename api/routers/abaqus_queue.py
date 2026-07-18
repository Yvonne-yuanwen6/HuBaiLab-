"""Simulation queue routes (serial submit with reorder)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.abaqus import (
    QueueAddRequest,
    QueueMoveRequest,
    QueueReorderRequest,
    QueueStateResponse,
)
from api.services import queue_manager

router = APIRouter(prefix="/api/abaqus/queue", tags=["abaqus-queue"])


def _as_response(state: dict) -> QueueStateResponse:
    return QueueStateResponse(**state)


@router.get("", response_model=QueueStateResponse)
def get_queue() -> QueueStateResponse:
    queue_manager.ensure_worker()
    return _as_response(queue_manager.get_queue())


@router.post("", response_model=QueueStateResponse)
def add_to_queue(body: QueueAddRequest) -> QueueStateResponse:
    queue_manager.ensure_worker()
    if not body.slugs:
        raise HTTPException(status_code=400, detail="slugs is required")
    state = queue_manager.add_slugs(
        body.slugs,
        target=body.target,
        cpus=body.cpus,
        memory_mb=body.memory_mb,
    )
    return _as_response(state)


@router.patch("/reorder", response_model=QueueStateResponse)
def reorder_queue(body: QueueReorderRequest) -> QueueStateResponse:
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids is required")
    return _as_response(queue_manager.reorder(body.ids))


@router.post("/start", response_model=QueueStateResponse)
def start_queue() -> QueueStateResponse:
    queue_manager.ensure_worker()
    return _as_response(queue_manager.set_running(True))


@router.post("/pause", response_model=QueueStateResponse)
def pause_queue() -> QueueStateResponse:
    return _as_response(queue_manager.set_running(False))


@router.post("/clear-finished", response_model=QueueStateResponse)
def clear_finished() -> QueueStateResponse:
    return _as_response(queue_manager.clear_finished())


@router.post("/{item_id}/move", response_model=QueueStateResponse)
def move_queue_item(item_id: str, body: QueueMoveRequest) -> QueueStateResponse:
    direction = (body.direction or "").strip().lower()
    if direction not in ("up", "down", "top", "bottom"):
        raise HTTPException(status_code=400, detail="direction must be up|down|top|bottom")
    return _as_response(queue_manager.move_item(item_id, direction))


@router.delete("/{item_id}", response_model=QueueStateResponse)
def delete_queue_item(item_id: str) -> QueueStateResponse:
    return _as_response(queue_manager.remove_item(item_id))
