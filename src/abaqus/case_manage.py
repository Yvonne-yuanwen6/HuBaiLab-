"""Local/remote case stop and delete helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from src.paths import ACTIVE_CASE_JSON, PROJECT_ROOT, export_dir_for_slug, job_dir_for_slug, post_dir_for_slug


def _case_dirs(slug: str) -> list[Path]:
    return [
        export_dir_for_slug(slug),
        job_dir_for_slug(slug),
        post_dir_for_slug(slug),
    ]


def stop_local_job(slug: str) -> dict[str, object]:
    """Stop a job on this machine (bash script if available, else remove .lck)."""
    job_dir = job_dir_for_slug(slug)
    results: dict[str, object] = {"slug": slug, "target": "local", "removed_locks": []}

    bash = shutil.which("bash")
    if bash:
        script = PROJECT_ROOT / "scripts" / "linux" / "stop_paperbox_job.sh"
        if script.is_file():
            proc = subprocess.run(
                [bash, str(script), slug],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            results["exit_code"] = proc.returncode
            results["stdout"] = proc.stdout[-4000:]
            results["stderr"] = proc.stderr[-2000:]
            results["method"] = "stop_paperbox_job.sh"
            return results

    lck = job_dir / f"{slug}.lck"
    if lck.is_file():
        lck.unlink()
        results["removed_locks"].append(str(lck))
    results["method"] = "remove_lck_only"
    results["warning"] = "未找到 bash；仅删除本地 .lck，远程进程可能仍在运行"
    return results


def delete_local_case(slug: str, *, clear_active: bool = True) -> dict[str, object]:
    removed: list[str] = []
    for path in _case_dirs(slug):
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))

    cleared_active = False
    if clear_active and ACTIVE_CASE_JSON.is_file():
        try:
            data = json.loads(ACTIVE_CASE_JSON.read_text(encoding="utf-8"))
            if data.get("slug") == slug:
                ACTIVE_CASE_JSON.unlink(missing_ok=True)
                cleared_active = True
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "slug": slug,
        "target": "local",
        "removed_dirs": removed,
        "cleared_active_case": cleared_active,
    }
