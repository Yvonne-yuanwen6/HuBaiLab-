"""Run CAD fuse/export attempts with a hard wall-clock timeout.

Native OCC / gmsh calls can hang indefinitely inside C++; thread timeouts cannot
interrupt them. Each attempt therefore runs in a child process that we terminate
(and kill if needed) when the budget is exceeded.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import time
import traceback
from typing import Any, Callable


class AttemptTimeoutError(TimeoutError):
    """Raised when a strategy attempt exceeded its wall-clock budget."""


def _worker(
    q: Any,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    try:
        result = fn(*args, **kwargs)
        q.put(("ok", result))
    except BaseException as exc:  # noqa: BLE001 — surface any child failure
        q.put(("err", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))


def run_with_timeout(
    fn: Callable[..., Any],
    /,
    *args: Any,
    timeout_s: float,
    label: str = "attempt",
    kill_grace_s: float = 5.0,
    **kwargs: Any,
) -> Any:
    """
    Execute ``fn(*args, **kwargs)`` in a fresh process.

    ``fn`` must be picklable (module-level). On timeout the child is terminated,
    then killed if it ignores SIGTERM.
    """
    timeout_s = float(timeout_s)
    if timeout_s <= 0:
        return fn(*args, **kwargs)

    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_worker,
        args=(q, fn, args, kwargs),
        name=f"timed:{label}"[:60],
        daemon=True,
    )
    t0 = time.monotonic()
    proc.start()
    proc.join(timeout_s)
    elapsed = time.monotonic() - t0

    if proc.is_alive():
        print(
            f"    TIMEOUT {label}: exceeded {timeout_s:.0f}s "
            f"(elapsed≈{elapsed:.0f}s) — kill and try next",
            flush=True,
        )
        proc.terminate()
        proc.join(kill_grace_s)
        if proc.is_alive():
            try:
                proc.kill()
            except AttributeError:
                os.kill(proc.pid, 9)  # type: ignore[arg-type]
            proc.join(kill_grace_s)
        raise AttemptTimeoutError(
            f"{label}: exceeded {timeout_s:.0f}s wall-clock budget "
            f"(elapsed≈{elapsed:.0f}s); skipped to next strategy"
        )

    if not q.empty():
        status, payload = q.get()
        if status == "ok":
            return payload
        raise RuntimeError(f"{label}: {payload}")

    if proc.exitcode not in (0, None):
        raise RuntimeError(
            f"{label}: child exited with code {proc.exitcode} and no result"
        )
    raise RuntimeError(f"{label}: child finished without returning a result")
