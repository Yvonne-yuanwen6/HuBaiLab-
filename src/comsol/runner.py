"""Run COMSOL Multiphysics in batch mode (.mph solve)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from src.paths import COMSOL_BATCH_PREFS_DIR, COMSOL_DEFAULT_BIN, COMSOL_JOBS_ROOT, PROJECT_ROOT


@dataclass(frozen=True)
class ComsolBatchRequest:
    """One COMSOL batch invocation."""

    slug: str
    input_file: Path
    output_file: Path | None = None
    study: str | None = None
    job_tag: str | None = None
    np: int = 8
    mpmode: str | None = None
    continue_run: bool = False
    extra_args: Sequence[str] = field(default_factory=tuple)


def resolve_comsol_bin(explicit: str | None = None) -> str:
    """Return COMSOL launcher path (env COMSOL_BIN > explicit > default > PATH)."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"COMSOL binary not found: {explicit}")
        return str(path)

    env_bin = os.environ.get("COMSOL_BIN", "").strip()
    if env_bin:
        path = Path(env_bin)
        if not path.is_file():
            raise FileNotFoundError(f"COMSOL_BIN points to missing file: {env_bin}")
        return str(path)

    default = Path(COMSOL_DEFAULT_BIN)
    if default.is_file():
        return str(default)

    found = shutil.which("comsol")
    if found:
        return found

    raise FileNotFoundError(
        "COMSOL binary not found. Set COMSOL_BIN or install at "
        f"{COMSOL_DEFAULT_BIN}"
    )


def job_dir_for_slug(slug: str) -> Path:
    job_dir = COMSOL_JOBS_ROOT / slug
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def _repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_batch_command(
    request: ComsolBatchRequest,
    *,
    comsol_bin: str | None = None,
    batchlog: Path | None = None,
) -> list[str]:
    """Assemble ``comsol batch`` argv for subprocess."""
    bin_path = resolve_comsol_bin(comsol_bin)
    job_dir = job_dir_for_slug(request.slug)
    input_path = Path(request.input_file).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Missing input file: {input_path}")

    job_input = job_dir / input_path.name
    if input_path.resolve() != job_input.resolve():
        shutil.copy2(input_path, job_input)

    if request.output_file is None:
        suffix = input_path.suffix or ".mph"
        output_path = job_dir / f"{request.slug}_solved{suffix}"
    else:
        output_path = Path(request.output_file).resolve()

    log_path = batchlog or (job_dir / f"{request.slug}_batch.log")
    tmp_dir = job_dir / "tmp"
    recovery_dir = job_dir / "recovery"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    recovery_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [
        bin_path,
        "batch",
        "-prefsdir",
        str(COMSOL_BATCH_PREFS_DIR),
        "-tmpdir",
        str(tmp_dir),
        "-recoverydir",
        str(recovery_dir),
        "-inputfile",
        str(job_input),
        "-outputfile",
        str(output_path),
        "-batchlog",
        str(log_path),
        "-np",
        str(request.np),
    ]
    if request.mpmode:
        cmd.extend(["-mpmode", request.mpmode])
    if request.study:
        cmd.extend(["-study", request.study])
    if request.job_tag:
        cmd.extend(["-job", request.job_tag])
    if request.continue_run:
        cmd.append("-continue")
    cmd.extend(request.extra_args)
    return cmd


def run_batch(
    request: ComsolBatchRequest,
    *,
    comsol_bin: str | None = None,
    background: bool = False,
    cwd: Path | None = None,
) -> subprocess.Popen[bytes] | subprocess.CompletedProcess[bytes]:
    """Run one batch job; foreground (check=True) or background (returns Popen)."""
    input_path = Path(request.input_file).resolve()
    job_dir = job_dir_for_slug(request.slug)
    job_input = job_dir / input_path.name
    if not job_input.is_file():
        if input_path.resolve() != job_input.resolve():
            shutil.copy2(input_path, job_input)

    log_path = job_dir / f"{request.slug}_batch.log"
    cmd = build_batch_command(request, comsol_bin=comsol_bin, batchlog=log_path)
    run_cwd = cwd or job_dir

    print(f"  Job dir: {job_dir}", flush=True)
    print(f"  Running: {' '.join(cmd)}", flush=True)
    if background:
        with open(log_path, "a", encoding="utf-8") as log_fp:
            proc = subprocess.Popen(
                cmd,
                cwd=run_cwd,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
            )
        print(f"  Background PID={proc.pid}", flush=True)
        print(f"  Log: {log_path}", flush=True)
        return proc

    return subprocess.run(cmd, cwd=run_cwd, check=True)


def tail_batch_log(slug: str, *, lines: int = 40) -> str:
    """Return the last *lines* of the batch log for *slug*."""
    log_path = job_dir_for_slug(slug) / f"{slug}_batch.log"
    if not log_path.is_file():
        return f"(no log yet: {_repo_rel(log_path)})"

    content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not content:
        return "(empty log)"
    return "\n".join(content[-lines:])


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Submit a COMSOL batch job (.mph).")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--input", required=True, help="Input .mph")
    parser.add_argument("--output", default="")
    parser.add_argument("--study", default="", help="Study tag, e.g. std1")
    parser.add_argument("--job", dest="job_tag", default="")
    parser.add_argument("--np", type=int, default=8)
    parser.add_argument("--mpmode", default="", choices=["", "throughput", "turnaround", "owner"])
    parser.add_argument("--continue", dest="continue_run", action="store_true")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--comsol-bin", default="")
    args = parser.parse_args(argv)

    request = ComsolBatchRequest(
        slug=args.slug,
        input_file=Path(args.input),
        output_file=Path(args.output) if args.output else None,
        study=args.study or None,
        job_tag=args.job_tag or None,
        np=args.np,
        mpmode=args.mpmode or None,
        continue_run=args.continue_run,
    )
    run_batch(request, comsol_bin=args.comsol_bin or None, background=args.background)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
