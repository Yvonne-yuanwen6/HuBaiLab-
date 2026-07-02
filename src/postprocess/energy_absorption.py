"""Energy absorption metrics from macroscopic compression curves (Hu & Bai §3.3)."""

from __future__ import annotations

from typing import Sequence

from src.postprocess.compression_curve import estimate_densification_strain
from src.postprocess.yield_strength import analyze_stress_strain_curve

# TPU matrix modulus from §2.3.2 / §2.4.1 (MPa)
HU_BAI_TPU_MATRIX_E_MPA = 25.0

# Experimental relative density ρa = ρ/ρ_tpu (thesis §2.3.2, Fig 2.4 typical values)
HU_BAI_PAPER_RELATIVE_DENSITY: dict[str, float] = {
    "bcc": 0.048,
    "af2q05": 0.047,
    "af2q1": 0.043,
    "af2q15": 0.045,
}


def cumulative_volumetric_energy(
    strains: Sequence[float],
    stresses_MPa: Sequence[float],
) -> list[float]:
    """
    Wv(ε) = ∫ σ dε.

    With σ in MPa and ε dimensionless, Wv is in J/cm³ (same numeric value as MPa·strain).
    """
    eps = [float(s) for s in strains]
    sig = [float(s) for s in stresses_MPa]
    wv = [0.0]
    for i in range(1, len(eps)):
        de = eps[i] - eps[i - 1]
        wv.append(wv[-1] + 0.5 * (sig[i] + sig[i - 1]) * de)
    return wv


def peak_stress_history(stresses_MPa: Sequence[float]) -> list[float]:
    running = 0.0
    out: list[float] = []
    for s in stresses_MPa:
        running = max(running, float(s))
        out.append(running)
    return out


def energy_absorption_efficiency(
    wv: Sequence[float],
    sigma_star: Sequence[float],
) -> list[float]:
    """η = Wv / σ* (Eq. 3.4); σ* = peak stress up to current strain."""
    eta: list[float] = []
    for w, s in zip(wv, sigma_star):
        eta.append(w / s if s > 1e-12 else 0.0)
    return eta


def specific_energy_absorption(
    wv_J_cm3: Sequence[float],
    relative_density: float,
) -> list[float]:
    """SEA = Wv / ρa (Eq. 3.3)."""
    rho_a = max(float(relative_density), 1e-9)
    return [w / rho_a for w in wv_J_cm3]


def normalized_energy_absorption(
    strains: Sequence[float],
    stresses_MPa: Sequence[float],
    *,
    matrix_E_MPa: float = HU_BAI_TPU_MATRIX_E_MPA,
) -> tuple[list[float], list[float]]:
    """
    Fig.3.13 axes: x = log10(σ/E_m), y = Wv/E_m.
    """
    import math

    wv = cumulative_volumetric_energy(strains, stresses_MPa)
    em = max(float(matrix_E_MPa), 1e-12)
    x = [math.log10(max(s, 1e-12) / em) for s in stresses_MPa]
    y = [w / em for w in wv]
    return x, y


def analyze_energy_absorption(
    strains: Sequence[float],
    stresses_MPa: Sequence[float],
    *,
    relative_density: float,
    matrix_E_MPa: float = HU_BAI_TPU_MATRIX_E_MPA,
) -> dict:
    eps = [float(s) for s in strains]
    sig = [float(s) for s in stresses_MPa]
    wv = cumulative_volumetric_energy(eps, sig)
    sigma_star = peak_stress_history(sig)
    sea = specific_energy_absorption(wv, relative_density)
    eta = energy_absorption_efficiency(wv, sigma_star)
    norm_x, norm_y = normalized_energy_absorption(eps, sig, matrix_E_MPa=matrix_E_MPa)
    dens = estimate_densification_strain(eps, sig)
    mech = analyze_stress_strain_curve(eps, sig)
    e_star = mech["elastic_modulus_MPa"] / max(float(relative_density), 1e-9)

    ed = dens["densification_strain"]
    ed_idx = max(range(len(eps)), key=lambda i: eps[i] if eps[i] <= ed else -1.0)
    return {
        "strains": eps,
        "stresses_MPa": sig,
        "Wv_J_cm3": wv,
        "SEA": sea,
        "eta": eta,
        "sigma_star_MPa": sigma_star,
        "normalized_x_log_sigma_over_E": norm_x,
        "normalized_y_Wv_over_E": norm_y,
        "densification": dens,
        "mechanics": mech,
        "relative_density": float(relative_density),
        "specific_modulus_MPa": float(e_star),
        "Wv_at_densification_J_cm3": float(wv[ed_idx]),
        "SEA_at_densification": float(sea[ed_idx]),
        "eta_at_densification": float(eta[ed_idx]),
        "matrix_E_MPa": float(matrix_E_MPa),
    }
