"""Background subprocess task manager."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.paths import OUTPUT_ROOT, PROJECT_ROOT, apply_local_cache_env

TASKS_DIR = OUTPUT_ROOT / "logs" / "ui_tasks"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_path(task_id: str) -> Path:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    return TASKS_DIR / f"{task_id}.json"


def _write_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = _task_path(task_id)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def get_task(task_id: str) -> dict[str, Any] | None:
    path = _task_path(task_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _run_subprocess(task_id: str, command: list[str], *, cwd: Path | None = None) -> None:
    log_out = _task_path(task_id).with_suffix(".stdout.log")
    log_err = _task_path(task_id).with_suffix(".stderr.log")
    payload = get_task(task_id) or {}
    payload["status"] = "running"
    payload["started_at"] = _now_iso()
    _write_task(task_id, payload)

    try:
        apply_local_cache_env()
        run_env = {**dict(**__import__("os").environ), "PYTHONPATH": str(PROJECT_ROOT)}
        with log_out.open("w", encoding="utf-8") as out_f, log_err.open("w", encoding="utf-8") as err_f:
            proc = subprocess.Popen(
                command,
                cwd=str(cwd or PROJECT_ROOT),
                stdout=out_f,
                stderr=err_f,
                env=run_env,
            )
            payload["pid"] = proc.pid
            _write_task(task_id, payload)
            exit_code = proc.wait()
        stdout_tail = log_out.read_text(encoding="utf-8", errors="replace")[-8000:] if log_out.is_file() else ""
        stderr_tail = log_err.read_text(encoding="utf-8", errors="replace")[-8000:] if log_err.is_file() else ""
        payload["status"] = "done" if exit_code == 0 else "failed"
        payload["exit_code"] = exit_code
        payload["stdout_tail"] = stdout_tail
        payload["stderr_tail"] = stderr_tail
        payload["finished_at"] = _now_iso()
        if exit_code != 0:
            payload["error"] = stderr_tail.strip() or f"Process exited with code {exit_code}"
    except Exception as exc:  # noqa: BLE001
        payload["status"] = "failed"
        payload["error"] = str(exc)
        payload["finished_at"] = _now_iso()
    _write_task(task_id, payload)


def start_task(
    command: list[str],
    *,
    slug: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    task_id = uuid.uuid4().hex[:12]
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": "pending",
        "command": command,
        "slug": slug,
        "created_at": _now_iso(),
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "error": None,
        "finished_at": None,
    }
    _write_task(task_id, payload)
    thread = threading.Thread(
        target=_run_subprocess,
        args=(task_id, command),
        kwargs={"cwd": cwd},
        daemon=True,
    )
    thread.start()
    return payload


def start_sync_result(*, slug: str | None = None, result: dict[str, Any]) -> dict[str, Any]:
    """Record an immediately-completed task (local sync operations)."""
    import json

    task_id = uuid.uuid4().hex[:12]
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": "done",
        "command": [],
        "slug": slug,
        "created_at": _now_iso(),
        "finished_at": _now_iso(),
        "exit_code": 0,
        "stdout_tail": json.dumps(result, ensure_ascii=False, indent=2),
        "stderr_tail": "",
        "error": None,
    }
    return _write_task(task_id, payload)


def start_python_script(script_rel: str, args: list[str], *, slug: str | None = None) -> dict[str, Any]:
    script = PROJECT_ROOT / script_rel
    command = [sys.executable, str(script), *args]
    return start_task(command, slug=slug)
