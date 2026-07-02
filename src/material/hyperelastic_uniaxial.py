"""Nominal uniaxial stress–stretch relations for hyperelastic screening (incompressible)."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np


def stretch_from_engineering_strain(eps: float | np.ndarray) -> float | np.ndarray:
    return 1.0 + np.asarray(eps, dtype=float)


def engineering_strain_from_stretch(lam: float | np.ndarray) -> float | np.ndarray:
    return np.asarray(lam, dtype=float) - 1.0


def nominal_stress_elastic(eps: float | np.ndarray, *, e_mpa: float) -> float | np.ndarray:
    return float(e_mpa) * np.asarray(eps, dtype=float)


def nominal_stress_neo_hooke(eps: float | np.ndarray, *, c10: float) -> float | np.ndarray:
    lam = stretch_from_engineering_strain(eps)
    return 2.0 * float(c10) * (lam**2 - lam ** (-2))


def nominal_stress_mooney_rivlin(eps: float | np.ndarray, *, c10: float, c01: float) -> float | np.ndarray:
    lam = stretch_from_engineering_strain(eps)
    return 2.0 * (lam - lam ** (-2)) * float(c10) + 2.0 * (1.0 - lam ** (-3)) * float(c01)


def nominal_stress_reduced_poly_n2(eps: float | np.ndarray, *, c10: float, c20: float) -> float | np.ndarray:
    lam = stretch_from_engineering_strain(eps)
    i1 = lam**2 + 2.0 * lam ** (-1)
    return 2.0 * (lam - lam ** (-2)) * (float(c10) + 2.0 * float(c20) * (i1 - 3.0))


def nominal_stress_ogden(eps: float | np.ndarray, *, mu: tuple[float, ...], alpha: tuple[float, ...]) -> float | np.ndarray:
    lam = stretch_from_engineering_strain(eps)
    out = np.zeros_like(lam, dtype=float)
    for m, a in zip(mu, alpha):
        if abs(a) < 1e-12:
            continue
        out += (2.0 * float(m) / float(a)) * (lam ** float(a) - lam ** (-0.5 * float(a)))
    return out


def curve_from_fn(
    fn: Callable[[np.ndarray], np.ndarray],
    *,
    eps_max: float,
    n: int = 400,
) -> list[tuple[float, float]]:
    xs = np.linspace(0.0, max(float(eps_max), 1e-9), int(n))
    ys = fn(xs)
    return [(float(x), float(y)) for x, y in zip(xs, ys)]


def marlow_curve_from_test_data(
    test_data: list[tuple[float, float]],
    *,
    eps_max: float,
    n: int = 400,
) -> list[tuple[float, float]]:
    """Marlow uniaxial path: interpolate the input nominal stress–strain data."""
    if not test_data:
        return []
    pts = sorted(test_data, key=lambda p: p[0])
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    grid = np.linspace(0.0, max(float(eps_max), xs[-1]), int(n))
    grid = np.clip(grid, xs[0], xs[-1])
    interp_y = np.interp(grid, xs, ys)
    return [(float(x), float(y)) for x, y in zip(grid, interp_y)]
