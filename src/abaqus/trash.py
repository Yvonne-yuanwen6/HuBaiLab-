"""Recycle bin for Abaqus case directories (export / jobs / post)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.paths import (
    ACTIVE_CASE_JSON,
    ABAQUS_JOBS,
    ABAQUS_POST,
    EXPORT_ROOT,
    TRASH_ROOT,
    export_dir_for_slug,
    job_dir_for_slug,
    post_dir_for_slug,
)

_META_NAME = "trash_meta.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_trash_id(slug: str) -> str:
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    safe = slug.replace("/", "_")[:120]
    return f"{safe}__{ts}"


def trash_dir_for_id(trash_id: str) -> Path:
    return TRASH_ROOT / trash_id


def _read_meta(trash_dir: Path) -> dict | None:
    path = trash_dir / _META_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_meta(trash_dir: Path, payload: dict) -> None:
    trash_dir.mkdir(parents=True, exist_ok=True)
    (trash_dir / _META_NAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _move_if_exists(src: Path, dst: Path, moved: list[str]) -> None:
    if not src.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))
    moved.append(str(src))


def trash_local_case(slug: str, *, clear_active: bool = True) -> dict[str, object]:
    """Move export/jobs/post into output/trash/{trash_id}/."""
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    trash_id = make_trash_id(slug)
    trash_dir = trash_dir_for_id(trash_id)
    trash_dir.mkdir(parents=True, exist_ok=True)

    moved: list[str] = []
    parts: dict[str, bool] = {}
    for label, src, sub in (
        ("export", export_dir_for_slug(slug), "export"),
        ("jobs", job_dir_for_slug(slug), "jobs"),
        ("post", post_dir_for_slug(slug), "post"),
    ):
        parts[label] = src.is_dir()
        _move_if_exists(src, trash_dir / sub, moved)

    if not moved:
        if trash_dir.is_dir() and not any(trash_dir.iterdir()):
            trash_dir.rmdir()
        return {
            "slug": slug,
            "trash_id": None,
            "moved_dirs": [],
            "warning": "没有找到可移入回收站的目录",
        }

    cleared_active = False
    if clear_active and ACTIVE_CASE_JSON.is_file():
        try:
            data = json.loads(ACTIVE_CASE_JSON.read_text(encoding="utf-8"))
            if data.get("slug") == slug:
                ACTIVE_CASE_JSON.unlink(missing_ok=True)
                cleared_active = True
        except (json.JSONDecodeError, OSError):
            pass

    meta = {
        "trash_id": trash_id,
        "slug": slug,
        "deleted_at": _now_iso(),
        "deleted_at_ts": datetime.now().timestamp(),
        "deleted_at_label": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "had_export": parts["export"],
        "had_jobs": parts["jobs"],
        "had_post": parts["post"],
        "moved_dirs": moved,
        "cleared_active_case": cleared_active,
    }
    _write_meta(trash_dir, meta)
    return {"slug": slug, "trash_id": trash_id, **meta}


def list_trash_items() -> list[dict]:
    if not TRASH_ROOT.is_dir():
        return []
    items: list[dict] = []
    for entry in sorted(TRASH_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not entry.is_dir():
            continue
        meta = _read_meta(entry)
        if meta:
            items.append(meta)
            continue
        # Legacy folder without meta
        trash_id = entry.name
        slug = trash_id.split("__")[0] if "__" in trash_id else trash_id
        items.append(
            {
                "trash_id": trash_id,
                "slug": slug,
                "deleted_at_label": datetime.fromtimestamp(entry.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "had_export": (entry / "export").is_dir(),
                "had_jobs": (entry / "jobs").is_dir(),
                "had_post": (entry / "post").is_dir(),
            }
        )
    return items


def restore_trash_item(trash_id: str) -> dict[str, object]:
    trash_dir = trash_dir_for_id(trash_id)
    if not trash_dir.is_dir():
        raise FileNotFoundError(f"Trash item not found: {trash_id}")

    meta = _read_meta(trash_dir) or {}
    slug = meta.get("slug") or trash_id.split("__")[0]

    restored: list[str] = []
    conflicts: list[str] = []
    for label, dst in (
        ("export", export_dir_for_slug(slug)),
        ("jobs", job_dir_for_slug(slug)),
        ("post", post_dir_for_slug(slug)),
    ):
        src = trash_dir / label
        if not src.is_dir():
            continue
        if dst.exists():
            conflicts.append(str(dst))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        restored.append(str(dst))

    if conflicts:
        raise FileExistsError(
            f"目标路径已存在，无法还原: {', '.join(conflicts)}"
        )

    remaining = [p for p in trash_dir.iterdir() if p.name != _META_NAME]
    if not remaining:
        shutil.rmtree(trash_dir, ignore_errors=True)

    return {"trash_id": trash_id, "slug": slug, "restored_dirs": restored}


def purge_trash_item(trash_id: str) -> dict[str, object]:
    trash_dir = trash_dir_for_id(trash_id)
    if not trash_dir.is_dir():
        raise FileNotFoundError(f"Trash item not found: {trash_id}")
    meta = _read_meta(trash_dir) or {"trash_id": trash_id}
    shutil.rmtree(trash_dir)
    return {"trash_id": trash_id, "slug": meta.get("slug"), "purged": True}
