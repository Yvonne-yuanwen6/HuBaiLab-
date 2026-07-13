"""Parse Abaqus .sta progress lines (ported from watch_job_progress.ps1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

_FRAME_RE = re.compile(
    r"Output Field Frame Number\s+(\d+),\s+of\s+(\d+),\s+at step time\s+([\d.E+-]+)"
)
_INC_RE = re.compile(
    r"^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)\s+"
    r"([\d.E+-]+)\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)"
)


@dataclass(frozen=True)
class StaProgress:
    frame: int | None = None
    frames_total: int | None = None
    sim_time_s: float = 0.0
    total_time_s: float = 0.0
    ke: float | None = None
    ie: float | None = None
    wall_seconds: float = 0.0


def _parse_wall_time(text: str) -> float:
    try:
        parts = text.split(":")
        if len(parts) == 3:
            h, m, s = (int(parts[0]), int(parts[1]), int(parts[2]))
            return float(timedelta(hours=h, minutes=m, seconds=s).total_seconds())
    except (ValueError, TypeError):
        pass
    return 0.0


def parse_sta_line(line: str) -> dict | None:
    m = _FRAME_RE.search(line)
    if m:
        return {
            "kind": "frame",
            "frame": int(m.group(1)),
            "frames_total": int(m.group(2)),
            "sim_time_s": float(m.group(3)),
        }
    m = _INC_RE.match(line)
    if m:
        return {
            "kind": "inc",
            "sim_time_s": float(m.group(2)),
            "total_time_s": float(m.group(3)),
            "wall": m.group(4),
            "ke": float(m.group(7)),
            "ie": float(m.group(8)),
        }
    return None


def parse_sta_tail(sta_path: Path, *, tail_lines: int = 40) -> StaProgress | None:
    if not sta_path.is_file():
        return None
    try:
        lines = sta_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    sim_s = 0.0
    total_s = 0.0
    ke = None
    ie = None
    wall_sec = 0.0
    frame = None
    frames_total = None

    for line in lines[-tail_lines:]:
        parsed = parse_sta_line(line)
        if not parsed:
            continue
        if parsed["kind"] == "frame":
            frame = parsed["frame"]
            frames_total = parsed["frames_total"]
            if parsed["sim_time_s"] > sim_s:
                sim_s = parsed["sim_time_s"]
        elif parsed["kind"] == "inc":
            sim_s = parsed["sim_time_s"]
            total_s = parsed["total_time_s"]
            ke = parsed["ke"]
            ie = parsed["ie"]
            wall_sec = _parse_wall_time(parsed["wall"])

    return StaProgress(
        frame=frame,
        frames_total=frames_total,
        sim_time_s=sim_s,
        total_time_s=total_s,
        ke=ke,
        ie=ie,
        wall_seconds=wall_sec,
    )


def format_eta(sim_s: float, wall_sec: float, step_s: float) -> str:
    if sim_s <= 0.5:
        return "calculating..."
    rate = wall_sec / sim_s
    remain = max(0.0, step_s - sim_s)
    eta_sec = int(round(remain * rate))
    from datetime import datetime, timedelta

    return (datetime.now() + timedelta(seconds=eta_sec)).strftime("%m-%d %H:%M")
