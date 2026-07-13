"""SSH/scp helpers for remote Abaqus jobs."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.paths import HUBAI_REMOTE_HOST, HUBAI_REMOTE_ROOT, PROJECT_ROOT


def _ssh_base(remote_host: str) -> list[str]:
    cmd = ["ssh"]
    key = os.environ.get("HU_BAI_SSH_KEY", "").strip()
    if key:
        cmd.extend(["-i", key])
    cmd.append(remote_host)
    return cmd


def _scp_base() -> list[str]:
    cmd = ["scp"]
    key = os.environ.get("HU_BAI_SSH_KEY", "").strip()
    if key:
        cmd.extend(["-i", key])
    return cmd


def _remote_file_exists(host: str, remote_path: str) -> bool | None:
    """Return whether a remote path exists; None if SSH check failed."""
    try:
        proc = subprocess.run(
            [*_ssh_base(host), f"test -f {shlex.quote(remote_path)}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return None


def _scp_remote_file(remote: str, local_path: Path) -> bool:
    cmd = [*_scp_base(), remote, str(local_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return proc.returncode == 0 and local_path.is_file()
    except (subprocess.SubprocessError, OSError):
        return local_path.is_file()


def sync_remote_job_files(
    slug: str,
    *,
    remote_host: str = "",
    remote_root: str = "",
    local_root: Path | None = None,
) -> dict[str, bool]:
    host = remote_host or HUBAI_REMOTE_HOST
    root = remote_root or HUBAI_REMOTE_ROOT
    local = local_root or PROJECT_ROOT
    job_dir = local / "output" / "jobs" / slug
    export_dir = local / "output" / "export" / slug
    job_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, bool] = {}
    remote_job = f"{host}:{root}/output/jobs/{slug}"
    results[f"{slug}.sta"] = _scp_remote_file(f"{remote_job}/{slug}.sta", job_dir / f"{slug}.sta")
    results[f"{slug}_meta.json"] = _scp_remote_file(
        f"{host}:{root}/output/export/{slug}/{slug}_meta.json",
        export_dir / f"{slug}_meta.json",
    )

    lck_local = job_dir / f"{slug}.lck"
    lck_remote = f"{root}/output/jobs/{slug}/{slug}.lck"
    lck_exists_remote = _remote_file_exists(host, lck_remote)
    if lck_exists_remote is True:
        results[f"{slug}.lck"] = _scp_remote_file(f"{remote_job}/{slug}.lck", lck_local)
    elif lck_exists_remote is False:
        if lck_local.is_file():
            try:
                lck_local.unlink()
            except OSError:
                pass
        results[f"{slug}.lck"] = False
    else:
        # SSH unreachable: try scp but do not delete a local .lck on failure.
        results[f"{slug}.lck"] = _scp_remote_file(f"{remote_job}/{slug}.lck", lck_local)

    return results


def list_remote_job_slugs(
    *,
    remote_host: str = "",
    remote_root: str = "",
) -> list[str]:
    """List slug directories on remote output/jobs (one ssh call)."""
    host = remote_host or HUBAI_REMOTE_HOST
    root = remote_root or HUBAI_REMOTE_ROOT
    remote_cmd = f"ls -1 {shlex.quote(root)}/output/jobs 2>/dev/null"
    try:
        proc = subprocess.run(
            [*_ssh_base(host), remote_cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def list_remote_running_slugs(
    *,
    remote_host: str = "",
    remote_root: str = "",
) -> list[str]:
    """Slugs with .lck on remote (running jobs)."""
    host = remote_host or HUBAI_REMOTE_HOST
    root = remote_root or HUBAI_REMOTE_ROOT
    remote_cmd = (
        f"find {shlex.quote(root)}/output/jobs -maxdepth 2 -name '*.lck' -printf '%f\\n' 2>/dev/null "
        r"| sed 's/\.lck$//'"
    )
    try:
        proc = subprocess.run(
            [*_ssh_base(host), remote_cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if proc.returncode != 0:
        return []
    return sorted({line.strip() for line in proc.stdout.splitlines() if line.strip()})


def slugs_for_sync_output(
    *,
    remote_host: str = "",
    remote_root: str = "",
    max_slugs: int = 30,
) -> tuple[list[str], list[str]]:
    """Return (slugs_to_scp, remote_job_slugs_discovered)."""
    from src.paths import ACTIVE_CASE_JSON

    remote_jobs = list_remote_job_slugs(remote_host=remote_host, remote_root=remote_root)
    remote_running = list_remote_running_slugs(remote_host=remote_host, remote_root=remote_root)

    slugs: list[str] = []
    seen: set[str] = set()

    def add(slug: str) -> None:
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)

    if ACTIVE_CASE_JSON.is_file():
        try:
            active = json.loads(ACTIVE_CASE_JSON.read_text(encoding="utf-8"))
            if isinstance(active, dict) and active.get("slug"):
                add(str(active["slug"]))
        except (json.JSONDecodeError, OSError):
            pass

    for slug in remote_running:
        add(slug)
    for slug in remote_jobs[:max_slugs]:
        add(slug)

    local_jobs = PROJECT_ROOT / "output" / "jobs"
    if local_jobs.is_dir():
        for d in local_jobs.iterdir():
            if d.is_dir():
                add(d.name)

    return slugs[:max_slugs], remote_jobs


def sync_remote_output_batch(
    slugs: list[str] | None = None,
    *,
    remote_host: str = "",
    remote_root: str = "",
    max_workers: int = 6,
    max_slugs: int = 30,
) -> dict[str, object]:
    """Pull .sta/.lck/_meta.json for multiple slugs (parallel scp)."""
    remote_jobs: list[str] = []
    if slugs is None:
        slugs, remote_jobs = slugs_for_sync_output(
            remote_host=remote_host,
            remote_root=remote_root,
            max_slugs=max_slugs,
        )
    if not slugs:
        return {
            "slug_count": 0,
            "synced_slugs": 0,
            "remote_job_count": len(remote_jobs),
            "remote_jobs": remote_jobs,
            "results": {},
        }

    results: dict[str, dict[str, bool | str]] = {}
    workers = max(1, min(max_workers, len(slugs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                sync_remote_job_files,
                slug,
                remote_host=remote_host,
                remote_root=remote_root,
            ): slug
            for slug in slugs
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                results[slug] = fut.result()
            except (subprocess.SubprocessError, OSError) as exc:
                results[slug] = {"error": str(exc)}

    synced = sum(
        1
        for r in results.values()
        if not r.get("error") and any(v is True for k, v in r.items() if k != "error")
    )
    return {
        "slug_count": len(slugs),
        "synced_slugs": synced,
        "remote_job_count": len(remote_jobs),
        "remote_jobs": remote_jobs,
        "results": results,
    }


def run_remote_submit(
    slug: str,
    *,
    cpus: int = 48,
    memory_mb: int = 262144,
    recover: bool = False,
    restart_from: str = "",
    background: bool = True,
    remote_host: str = "",
    remote_root: str = "",
) -> list[str]:
    host = remote_host or HUBAI_REMOTE_HOST
    root = remote_root or HUBAI_REMOTE_ROOT
    remote_cmd = (
        f"cd {root} && export PYTHONPATH=. && "
        f"bash scripts/linux/submit_job.sh --slug {slug} "
        f"--cpus {cpus} --memory-mb {memory_mb}"
    )
    if recover:
        remote_cmd += " --recover"
    if restart_from:
        remote_cmd += f" --restart-from {restart_from}"
    if background:
        remote_cmd += " --background"
    return [*_ssh_base(host), remote_cmd]


def run_remote_stop(
    slug: str,
    *,
    remote_host: str = "",
    remote_root: str = "",
) -> list[str]:
    host = remote_host or HUBAI_REMOTE_HOST
    root = remote_root or HUBAI_REMOTE_ROOT
    slug_q = shlex.quote(slug)
    remote_cmd = f"cd {shlex.quote(root)} && bash scripts/linux/stop_paperbox_job.sh {slug_q}"
    return [*_ssh_base(host), remote_cmd]


def run_remote_trash(
    slug: str,
    trash_id: str,
    *,
    remote_host: str = "",
    remote_root: str = "",
) -> list[str]:
    host = remote_host or HUBAI_REMOTE_HOST
    root = remote_root or HUBAI_REMOTE_ROOT
    slug_q = shlex.quote(slug)
    tid_q = shlex.quote(trash_id)
    remote_cmd = (
        f"cd {shlex.quote(root)} && "
        f"mkdir -p output/trash/{tid_q} && "
        f"for kind in export jobs post; do "
        f"src=output/$kind/{slug_q}; "
        f'[ -d "$src" ] && mv "$src" "output/trash/{tid_q}/$kind"; '
        f"done"
    )
    return [*_ssh_base(host), remote_cmd]


def run_remote_delete(
    slug: str,
    *,
    remote_host: str = "",
    remote_root: str = "",
) -> list[str]:
    host = remote_host or HUBAI_REMOTE_HOST
    root = remote_root or HUBAI_REMOTE_ROOT
    slug_q = shlex.quote(slug)
    remote_cmd = (
        f"cd {shlex.quote(root)} && "
        f"rm -rf output/export/{slug_q} output/jobs/{slug_q} output/post/{slug_q}"
    )
    return [*_ssh_base(host), remote_cmd]

