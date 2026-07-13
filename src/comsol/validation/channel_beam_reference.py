"""Reference data from COMSOL Structural Mechanics verification *Channel Beam*.

Official Application Library path:
``Structural_Mechanics_Module/Verification_Examples/channel_beam``

We reproduce the eigenfrequency study with a **3D solid** cantilever of the same
length and material, using a rectangular cross-section whose weak-axis bending
stiffness matches the channel's ``Iyy``.  The first bending mode should agree
with the official Table 2 value (~21 Hz) within a few percent (solid vs beam
theory / mesh).

See: https://www.comsol.com/model/channel-beam-8520
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# COMSOL Channel Beam verification — Table 2 (first modes, Hz)
CHANNEL_BEAM_OFFICIAL_MODES: tuple[dict[str, float | int | str], ...] = (
    {"mode": 1, "type": "first_y_bending", "analytical_Hz": 21.02, "comsol_Hz": 21.04},
    {"mode": 2, "type": "first_z_bending", "analytical_Hz": 51.96, "comsol_Hz": 51.96},
    {"mode": 3, "type": "first_torsion", "analytical_Hz": 128.3, "comsol_Hz": 128.4},
    {"mode": 4, "type": "second_y_bending", "analytical_Hz": 131.7, "comsol_Hz": 131.8},
    {"mode": 5, "type": "second_z_bending", "analytical_Hz": 325.5, "comsol_Hz": 325.7},
)

# Euler-Bernoulli cantilever roots β_n L  →  k_n = β_n  (COMSOL verification doc Eq. 5)
CANTILEVER_BETA: tuple[float, ...] = (1.875104, 4.694091, 7.854757, 10.995541, 14.137168)


@dataclass(frozen=True)
class CantileverSolidSpec:
    """Rectangular solid cantilever aligned with COMSOL Channel Beam material/length."""

    length_m: float = 1.0
    width_m: float = 0.025  # global Y
    height_m: float = 0.050  # global Z
    youngs_pa: float = 210e9
    poisson: float = 0.25
    density_kg_m3: float = 7800.0
    # Weak-axis second moment (bending in Z, about Y): Iyy = W H³ / 12
    inertia_weak_m4: float | None = None
    area_m2: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "area_m2", self.width_m * self.height_m)
        if self.inertia_weak_m4 is None:
            object.__setattr__(
                self,
                "inertia_weak_m4",
                self.width_m * self.height_m**3 / 12.0,
            )

    @property
    def length_mm(self) -> float:
        return self.length_m * 1000.0

    @property
    def width_mm(self) -> float:
        return self.width_m * 1000.0

    @property
    def height_mm(self) -> float:
        return self.height_m * 1000.0


def analytical_bending_hz(
    spec: CantileverSolidSpec,
    *,
    mode_index: int = 0,
    inertia_m4: float | None = None,
) -> float:
    """Cantilever bending eigenfrequency (Hz) from Euler-Bernoulli beam theory."""
    if mode_index < 0 or mode_index >= len(CANTILEVER_BETA):
        raise IndexError(f"mode_index {mode_index} out of range")
    kn = CANTILEVER_BETA[mode_index]
    i_val = inertia_m4 if inertia_m4 is not None else spec.inertia_weak_m4
    rad_s = (kn / (2.0 * math.pi)) * math.sqrt(
        spec.youngs_pa * i_val / (spec.density_kg_m3 * spec.area_m2 * spec.length_m**4)
    )
    # kn/(2π) * sqrt(EI/(ρAL⁴))  — COMSOL Channel Beam verification Eq. (5)
    return (kn / (2.0 * math.pi)) * math.sqrt(
        spec.youngs_pa * i_val / (spec.density_kg_m3 * spec.area_m2 * spec.length_m**4)
    )


def reference_bending_modes(spec: CantileverSolidSpec, n: int = 3) -> list[dict]:
    """First *n* analytical bending frequencies for weak-axis bending."""
    rows: list[dict] = []
    for i in range(n):
        hz = analytical_bending_hz(spec, mode_index=i)
        rows.append(
            {
                "mode_index": i + 1,
                "analytical_Hz": hz,
                "official_mode1_Hz": CHANNEL_BEAM_OFFICIAL_MODES[0]["analytical_Hz"]
                if i == 0
                else None,
            }
        )
    return rows
