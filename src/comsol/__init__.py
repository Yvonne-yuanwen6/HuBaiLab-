"""COMSOL Multiphysics — vibration isolation (MPh) + batch solve."""

from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.runner import (
    ComsolBatchRequest,
    build_batch_command,
    job_dir_for_slug,
    resolve_comsol_bin,
    run_batch,
    tail_batch_log,
)

__all__ = [
    "ComsolBatchRequest",
    "HuBaiComsolSettings",
    "build_batch_command",
    "job_dir_for_slug",
    "resolve_comsol_bin",
    "run_batch",
    "tail_batch_log",
]
