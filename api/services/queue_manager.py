"""Persistent serial simulation queue for the Web UI."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.paths import OUTPUT_ROOT, PROJECT_ROOT, job_dir_for_slug

QUEUE_PATH = OUTPUT_ROOT / "logs" / "ui_sim_queue.json"

_lock = threading.RLock()
_worker_started = False
_worker_stop = threading.Event()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict[str, Any]:
    return {"running": False, "items": []}


def _read_state() -> dict[str, Any]:
    if not QUEUE_PATH.is_file():
        return _default_state()
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    data.setdefault("running", False)
    data.setdefault("items", [])
    return data


def _write_state(state: dict[str, Any]) -> dict[str, Any]:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Renormalize order
    items = sorted(state.get("items") or [], key=lambda x: int(x.get("order", 0)))
    for i, item in enumerate(items):
        item["order"] = i
    state["items"] = items
    QUEUE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return state


def get_queue() -> dict[str, Any]:
    with _lock:
        return _write_state(_read_state())


def add_slugs(
    slugs: list[str],
    *,
    target: str = "remote",
    cpus: int = 48,
    memory_mb: int = 262144,
) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        existing = {str(i.get("slug")) for i in state["items"] if i.get("status") in ("pending", "running")}
        order = len(state["items"])
        for raw in slugs:
            slug = (raw or "").strip()
            if not slug or slug in existing:
                continue
            export_inp = PROJECT_ROOT / "output" / "export" / slug / f"{slug}.inp"
            if not export_inp.is_file():
                continue
            state["items"].append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "slug": slug,
                    "cpus": int(cpus),
                    "memory_mb": int(memory_mb),
                    "target": target or "remote",
                    "status": "pending",
                    "order": order,
                    "created_at": _now_iso(),
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "task_id": None,
                }
            )
            existing.add(slug)
            order += 1
        return _write_state(state)


def reorder(ids: list[str]) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        by_id = {i["id"]: i for i in state["items"]}
        new_items: list[dict[str, Any]] = []
        for idx, item_id in enumerate(ids):
            item = by_id.pop(item_id, None)
            if item is None:
                continue
            # Do not reorder a currently running item relative to itself; still allow position update.
            item["order"] = idx
            new_items.append(item)
        # Append any leftover (unknown ids omitted)
        for item in by_id.values():
            item["order"] = len(new_items)
            new_items.append(item)
        state["items"] = new_items
        return _write_state(state)


def move_item(item_id: str, direction: str) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        items = sorted(state["items"], key=lambda x: int(x.get("order", 0)))
        idx = next((i for i, it in enumerate(items) if it["id"] == item_id), -1)
        if idx < 0:
            return _write_state(state)
        item = items[idx]
        if item.get("status") == "running":
            return _write_state(state)
        if direction == "up" and idx > 0:
            items[idx], items[idx - 1] = items[idx - 1], items[idx]
        elif direction == "down" and idx < len(items) - 1:
            items[idx], items[idx + 1] = items[idx + 1], items[idx]
        elif direction == "top":
            items.pop(idx)
            items.insert(0, item)
        elif direction == "bottom":
            items.pop(idx)
            items.append(item)
        state["items"] = items
        return _write_state(state)


def remove_item(item_id: str) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        state["items"] = [
            i
            for i in state["items"]
            if i["id"] != item_id or i.get("status") == "running"
        ]
        return _write_state(state)


def clear_finished() -> dict[str, Any]:
    with _lock:
        state = _read_state()
        state["items"] = [i for i in state["items"] if i.get("status") in ("pending", "running")]
        return _write_state(state)


def set_running(running: bool) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        state["running"] = bool(running)
        return _write_state(state)


def _job_still_active(slug: str) -> bool:
    """Heuristic: .lck present or recent sta with RUNNING is active."""
    job_dir = job_dir_for_slug(slug)
    if (job_dir / f"{slug}.lck").is_file():
        return True
    try:
        from src.abaqus.job_status import inspect_job

        progress = inspect_job(slug, remote_watch=False)
        return progress.state.value == "RUNNING"
    except Exception:  # noqa: BLE001
        return False


def _submit_item(item: dict[str, Any]) -> str | None:
    """Submit one queue item; returns task_id."""
    from api.services.remote import run_remote_submit
    from api.services.task_manager import start_task

    slug = item["slug"]
    target = item.get("target") or "remote"
    cpus = int(item.get("cpus") or 48)
    memory_mb = int(item.get("memory_mb") or 262144)
    if target == "remote":
        command = run_remote_submit(
            slug,
            cpus=cpus,
            memory_mb=memory_mb,
            recover=False,
            restart_from="",
            background=True,
        )
    else:
        submit_sh = PROJECT_ROOT / "scripts" / "linux" / "submit_job.sh"
        command = [
            "bash",
            str(submit_sh),
            "--slug",
            slug,
            "--cpus",
            str(cpus),
            "--memory-mb",
            str(memory_mb),
            "--background",
        ]
    task = start_task(command, slug=slug)
    return task.get("task_id")


def _mark_item(item_id: str, **updates: Any) -> None:
    with _lock:
        state = _read_state()
        for item in state["items"]:
            if item["id"] == item_id:
                item.update(updates)
                break
        _write_state(state)


def _parse_started_ts(item: dict[str, Any]) -> float:
    raw = item.get("started_at") or ""
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _worker_tick() -> None:
    state = get_queue()
    if not state.get("running"):
        return

    running_items = [i for i in state["items"] if i.get("status") == "running"]
    if running_items:
        current = running_items[0]
        slug = current["slug"]
        task_id = current.get("task_id")
        from api.services.task_manager import get_task

        if task_id:
            t = get_task(task_id)
            if t and t.get("status") in ("pending", "running"):
                # Submit still in flight — keep waiting.
                return
            if t and t.get("status") == "failed":
                _mark_item(
                    current["id"],
                    status="failed",
                    finished_at=_now_iso(),
                    error=t.get("error") or "submit failed",
                )
                return

        # Grace period: Abaqus may not have written .lck yet.
        if time.time() - _parse_started_ts(current) < 90:
            return

        if _job_still_active(slug):
            return

        try:
            from src.abaqus.job_status import inspect_job

            st = inspect_job(slug, remote_watch=False).state.value
            if st in ("FAILED", "ABORTED"):
                _mark_item(
                    current["id"],
                    status="failed",
                    finished_at=_now_iso(),
                    error=st,
                )
            elif st == "COMPLETED":
                _mark_item(current["id"], status="done", finished_at=_now_iso(), error=None)
            elif st == "WAITING":
                # Submit finished but job never started — treat as failed after grace.
                _mark_item(
                    current["id"],
                    status="failed",
                    finished_at=_now_iso(),
                    error="job never started (WAITING)",
                )
            else:
                _mark_item(current["id"], status="done", finished_at=_now_iso(), error=None)
        except Exception:  # noqa: BLE001
            _mark_item(current["id"], status="done", finished_at=_now_iso())
        return

    pending = sorted(
        [i for i in state["items"] if i.get("status") == "pending"],
        key=lambda x: int(x.get("order", 0)),
    )
    if not pending:
        return
    nxt = pending[0]
    try:
        task_id = _submit_item(nxt)
        _mark_item(
            nxt["id"],
            status="running",
            started_at=_now_iso(),
            task_id=task_id,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_item(
            nxt["id"],
            status="failed",
            finished_at=_now_iso(),
            error=str(exc),
        )


def _worker_loop() -> None:
    while not _worker_stop.is_set():
        try:
            _worker_tick()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)


def ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
        t = threading.Thread(target=_worker_loop, name="sim-queue-worker", daemon=True)
        t.start()
