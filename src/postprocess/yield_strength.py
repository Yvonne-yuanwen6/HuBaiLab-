"""Macroscopic yield / ultimate points on engineering stress-strain curves."""

from __future__ import annotations

import json
import os
from typing import Sequence


def _linear_fit(strains: Sequence[float], stresses: Sequence[float]) -> tuple[float, float]:
    """Least-squares slope and intercept (stress = slope * strain + intercept)."""
    n = len(strains)
    if n < 2:
        return 0.0, 0.0
    sx = sy = sxx = sxy = 0.0
    for x, y in zip(strains, stresses):
        sx += x
        sy += y
        sxx += x * x
        sxy += x * y
    den = n * sxx - sx * sx
    if abs(den) < 1e-18:
        return 0.0, float(stresses[0]) if stresses else 0.0
    slope = (n * sxy - sx * sy) / den
    intercept = (sy - slope * sx) / n
    return float(slope), float(intercept)


def analyze_stress_strain_curve(
    strains: Sequence[float],
    stresses: Sequence[float],
    *,
    offset_strain: float = 0.002,
    elastic_fit_fraction: float = 0.25,
) -> dict[str, float]:
    """
  0.2% offset yield (macroscopic), elastic modulus, ultimate stress/strain.

  Returns MPa for stresses, dimensionless strain.
  """
    if len(strains) < 5:
        raise ValueError("Need at least 5 points for yield analysis")

    eps = [float(s) for s in strains]
    sig = [float(s) for s in stresses]

    n_fit = max(5, min(len(eps) - 2, int(len(eps) * elastic_fit_fraction)))
    E, b = _linear_fit(eps[:n_fit], sig[:n_fit])
    if E <= 1e-12:
        E = _linear_fit(eps, sig)[0]

    # 0.2% offset: sigma = E * (eps - offset) + b  (parallel to elastic line)
    yield_strain = yield_stress = float("nan")
    for i in range(1, len(eps)):
        if eps[i] < offset_strain:
            continue
        line = E * (eps[i] - offset_strain) + b
        if sig[i] >= line and sig[i - 1] < E * (eps[i - 1] - offset_strain) + b:
            # linear interpolate between i-1 and i
            e0, e1 = eps[i - 1], eps[i]
            s0, s1 = sig[i - 1], sig[i]
            l0 = E * (e0 - offset_strain) + b
            l1 = line
            den = (s1 - s0) - (l1 - l0)
            if abs(den) > 1e-18:
                t = (l0 - s0) / den
                t = max(0.0, min(1.0, t))
                yield_strain = e0 + t * (e1 - e0)
                yield_stress = s0 + t * (s1 - s0)
            else:
                yield_strain, yield_stress = eps[i], sig[i]
            break

    # Proportional limit: first point deviating >2% from elastic line
    prop_strain = prop_stress = float("nan")
    for i in range(1, len(eps)):
        pred = E * eps[i] + b
        if pred > 1e-12 and abs(sig[i] - pred) / pred > 0.02:
            prop_strain, prop_stress = eps[i], sig[i]
            break

    u_idx = max(range(len(sig)), key=lambda i: sig[i])
    ult_strain, ult_stress = eps[u_idx], sig[u_idx]

    return {
        "elastic_modulus_MPa": E,
        "elastic_intercept_MPa": b,
        "offset_strain": offset_strain,
        "yield_stress_MPa": yield_stress,
        "yield_strain": yield_strain,
        "proportional_limit_stress_MPa": prop_stress,
        "proportional_limit_strain": prop_strain,
        "ultimate_stress_MPa": ult_stress,
        "ultimate_strain": ult_strain,
        "max_strain": max(eps),
        "max_stress_MPa": max(sig),
    }


def save_yield_properties(props: dict[str, float], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(props, f, indent=2, ensure_ascii=False)
        f.write("\n")
