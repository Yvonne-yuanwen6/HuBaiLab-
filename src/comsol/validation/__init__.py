"""COMSOL workflow validation against official Application Library benchmarks."""

from src.comsol.validation.channel_beam_reference import (
    CHANNEL_BEAM_OFFICIAL_MODES,
    CantileverSolidSpec,
    analytical_bending_hz,
)

__all__ = [
    "CHANNEL_BEAM_OFFICIAL_MODES",
    "CantileverSolidSpec",
    "analytical_bending_hz",
]
