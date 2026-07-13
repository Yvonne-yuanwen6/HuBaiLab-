"""Run heavy native/OCP work in an isolated child process with a wall-clock limit."""

from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_IN_CHILD_ENV = "HU_BAI_WORK_GUARD_CHILD"


def default_ocp_array_timeout_sec(*, nx: int, ny: int, method: str) -> float:
    """Conservative wall limit: OCP fuse/sew can hang indefinitely without one."""
    n_cells = max(1, int(nx) * int(ny))
    method_l = str(method).strip().lower()
    per_cell = 90.0 if method_l in {"cell_glue", "cell_sew", "glue"} else 60.0
    return min(1800.0, 120.0 + n_cells * per_cell)


def _sleep_seconds(seconds: float) -> None:
    """Test helper: block for *seconds* (used by timeout self-checks)."""
    import time

    time.sleep(max(0.0, float(seconds)))


def _terminate_process(proc: mp.Process) -> None:
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(timeout=5.0)
    if not proc.is_alive():
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.kill()
    proc.join(timeout=5.0)


def _child_entry(
    result_queue: mp.Queue,
    module_name: str,
    func_name: str,
    kwargs: dict[str, Any],
) -> None:
    os.environ[_IN_CHILD_ENV] = "1"
    try:
        mod = __import__(module_name, fromlist=[func_name])
        func = getattr(mod, func_name)
        result_queue.put(("ok", func(**kwargs)))
    except Exception as exc:
        result_queue.put(
            (
                "err",
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
        )


def run_with_timeout(
    func: Callable[..., T],
    /,
    *args: Any,
    timeout_sec: float,
    label: str = "task",
    **kwargs: Any,
) -> T:
    """Execute *func* in a child process; kill the tree if it exceeds *timeout_sec*."""
    if args:
        raise TypeError("run_with_timeout: pass parameters as keywords for spawn pickling")
    return run_module_with_timeout(
        module_name=func.__module__,
        func_name=func.__name__,
        kwargs=kwargs,
        timeout_sec=timeout_sec,
        label=label,
    )


def run_module_with_timeout(
    *,
    module_name: str,
    func_name: str,
    kwargs: dict[str, Any],
    timeout_sec: float,
    label: str = "task",
) -> Any:
    """Spawn a child that imports *module_name*.*func_name*(**kwargs)."""
    if os.environ.get(_IN_CHILD_ENV) == "1":
        mod = __import__(module_name, fromlist=[func_name])
        return getattr(mod, func_name)(**kwargs)

    timeout = float(timeout_sec)
    if timeout <= 0:
        mod = __import__(module_name, fromlist=[func_name])
        return getattr(mod, func_name)(**kwargs)

    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_child_entry,
        args=(result_queue, module_name, func_name, kwargs),
        daemon=True,
    )
    proc.start()
    proc.join(timeout=timeout)
    if proc.is_alive():
        _terminate_process(proc)
        raise TimeoutError(
            f"{label} exceeded wall limit {timeout:g}s — child process terminated"
        )
    if result_queue.empty():
        raise RuntimeError(f"{label} child exited without result (code={proc.exitcode})")
    status, payload = result_queue.get_nowait()
    if status == "err":
        err = payload
        raise RuntimeError(
            f"{label} failed in child: {err['type']}: {err['message']}\n{err['traceback']}"
        )
    return payload
