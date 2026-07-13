"""FastAPI dependencies."""

from __future__ import annotations

from pathlib import Path

from src.paths import PROJECT_ROOT

PROJECT_ROOT_PATH = PROJECT_ROOT


def get_project_root() -> Path:
    return PROJECT_ROOT_PATH
