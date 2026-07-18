"""Post-write STEP file size sanity checks (detect bloated / empty exports).

Empirical 4×4×4 L=20 paper_box / ellipse baselines (server, Jul 2026):
  Q=0   zslab ~8–11 MB, array ~33–39 MB  (CAE OK)
  Q=0.5 zslab ~14–15 MB, array ~54 MB     (CAE OK)
  Q=1   zslab ~98 MB, array ~387 MB       (CAE invalid geometry — bloated)

Checks log WARN/OK and append a JSONL record; abnormal size does not abort
by default (empty/missing files raise).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.paths import OUTPUT_ROOT, PROJECT_ROOT

_MIB = 1024 * 1024

# Soft bands: outside → status "warn" + note; empty/tiny → "error"
_BANDS: dict[str, dict[str, float]] = {
    "zslab": {"min_mib": 1.0, "warn_max_mib": 40.0, "bad_max_mib": 80.0},
    "array": {"min_mib": 5.0, "warn_max_mib": 120.0, "bad_max_mib": 250.0},
    "unitcell": {"min_mib": 0.05, "warn_max_mib": 25.0, "bad_max_mib": 60.0},
    "generic": {"min_mib": 0.01, "warn_max_mib": 200.0, "bad_max_mib": 400.0},
}

_DEFAULT_LOG = OUTPUT_ROOT / "logs" / "step_size_checks.jsonl"


@dataclass(frozen=True)
class StepSizeCheck:
    path: str
    role: str
    bytes: int
    mib: float
    status: str  # ok | warn | error
    note: str
    min_mib: float
    warn_max_mib: float
    bad_max_mib: float


def classify_step_role(path: str) -> str:
    name = os.path.basename(path).lower()
    if re.search(r"zslab_iz\d+", name) or "zslab_" in name:
        return "zslab"
    if "unitcell_" in name or name.startswith("unitcell"):
        return "unitcell"
    if "_array" in name or name.endswith("_array.step"):
        return "array"
    if "paper_box_array" in name:
        return "array"
    return "generic"


def check_step_file_size(
    path: str,
    *,
    role: str | None = None,
    log: bool = True,
    raise_on_error: bool = True,
    jsonl_path: str | Path | None = None,
) -> StepSizeCheck:
    """
    Inspect a written STEP file size against role bands.

    ``status``:
      - ok: within soft band
      - warn: oversized (likely BREP bloat / failed sew) — recorded, no raise
      - error: missing / empty / far too small — raises if ``raise_on_error``
    """
    abs_path = os.path.abspath(path)
    role_s = (role or classify_step_role(abs_path)).lower()
    band = _BANDS.get(role_s, _BANDS["generic"])
    min_mib = float(band["min_mib"])
    warn_max = float(band["warn_max_mib"])
    bad_max = float(band["bad_max_mib"])

    if not os.path.isfile(abs_path):
        result = StepSizeCheck(
            path=abs_path,
            role=role_s,
            bytes=0,
            mib=0.0,
            status="error",
            note="STEP file missing after write",
            min_mib=min_mib,
            warn_max_mib=warn_max,
            bad_max_mib=bad_max,
        )
        _emit(result, log=log, jsonl_path=jsonl_path)
        if raise_on_error:
            raise FileNotFoundError(result.note + f": {abs_path}")
        return result

    nbytes = int(os.path.getsize(abs_path))
    mib = nbytes / float(_MIB)

    if nbytes < 1024 or mib < min_mib:
        status = "error"
        note = (
            f"STEP abnormally small ({mib:.2f} MiB < {min_mib:.2f} MiB min "
            f"for role={role_s}) — likely truncated or empty export"
        )
    elif mib >= bad_max:
        status = "warn"
        note = (
            f"STEP size ABNORMAL ({mib:.1f} MiB >= {bad_max:.0f} MiB bad band "
            f"for role={role_s}; soft warn>{warn_max:.0f} MiB). "
            "Likely BREP bloat / sew failure — check geometry before CAE mesh. "
            "Ref: OK Q0 zslab~8–11MiB array~33–39MiB; Q0.5~14–15 / ~54; "
            "failed Q1 ellipse ~98 / ~387 MiB."
        )
    elif mib >= warn_max:
        status = "warn"
        note = (
            f"STEP size elevated ({mib:.1f} MiB > {warn_max:.0f} MiB warn band "
            f"for role={role_s}) — review sew quality / face count"
        )
    else:
        status = "ok"
        note = (
            f"STEP size OK ({mib:.2f} MiB; role={role_s} band "
            f"{min_mib:.2f}–{warn_max:.0f} MiB)"
        )

    result = StepSizeCheck(
        path=abs_path,
        role=role_s,
        bytes=nbytes,
        mib=round(mib, 3),
        status=status,
        note=note,
        min_mib=min_mib,
        warn_max_mib=warn_max,
        bad_max_mib=bad_max,
    )
    _emit(result, log=log, jsonl_path=jsonl_path)
    if raise_on_error and status == "error":
        raise RuntimeError(result.note)
    return result


def _emit(
    result: StepSizeCheck,
    *,
    log: bool,
    jsonl_path: str | Path | None,
) -> None:
    tag = result.status.upper()
    line = f"  [STEP-SIZE {tag}] {result.note}\n    path={result.path}"
    if log:
        print(line, flush=True)
    out = Path(jsonl_path) if jsonl_path else _DEFAULT_LOG
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = asdict(result)
        payload["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            rel = os.path.relpath(result.path, PROJECT_ROOT)
        except ValueError:
            rel = result.path
        payload["path_rel"] = rel
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        if log:
            print(f"  [STEP-SIZE] could not write log {out}: {exc}", flush=True)


def as_report_dict(result: StepSizeCheck) -> dict[str, Any]:
    return asdict(result)
