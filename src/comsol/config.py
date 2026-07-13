"""COMSOL installation defaults for the art Linux workstation."""

from __future__ import annotations

import os

# Server install (art@172.20.200.93)
DEFAULT_COMSOL_BIN = "/home/art/APP/comsol56/multiphysics/bin/comsol"
DEFAULT_COMSOL_ROOT = "/home/art/APP/comsol56/multiphysics"

ENV_COMSOL_BIN = "COMSOL_BIN"
ENV_COMSOL_ROOT = "COMSOL_ROOT"


def comsol_bin_from_env() -> str | None:
    value = os.environ.get(ENV_COMSOL_BIN, "").strip()
    return value or None


def comsol_root_from_env() -> str | None:
    value = os.environ.get(ENV_COMSOL_ROOT, "").strip()
    return value or None
