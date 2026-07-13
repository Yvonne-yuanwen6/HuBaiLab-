"""Recycle bin API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.abaqus import TaskResponse, TrashItem
from api.services.task_manager import start_sync_result
from src.abaqus.trash import list_trash_items, purge_trash_item, restore_trash_item

router = APIRouter(prefix="/api/abaqus/trash", tags=["abaqus-trash"])


@router.get("", response_model=list[TrashItem])
def get_trash_list() -> list[TrashItem]:
    items: list[TrashItem] = []
    for raw in list_trash_items():
        tid = raw.get("trash_id")
        if not tid:
            continue
        items.append(TrashItem(**raw))
    return items


@router.post("/{trash_id}/restore", response_model=TaskResponse)
def restore_from_trash(trash_id: str) -> TaskResponse:
    try:
        result = restore_trash_item(trash_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskResponse(**start_sync_result(slug=str(result.get("slug")), result=result))


@router.delete("/{trash_id}", response_model=TaskResponse)
def purge_from_trash(trash_id: str) -> TaskResponse:
    try:
        result = purge_trash_item(trash_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskResponse(**start_sync_result(slug=str(result.get("slug")), result=result))
