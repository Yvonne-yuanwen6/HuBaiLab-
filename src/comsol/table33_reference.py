"""Table 3.3 reference frequencies from Hu & Bai thesis (simulation + experiment)."""

from __future__ import annotations

# Simulation column (Hz) — modes 1–3 (BCC confirmed from thesis Table 3.3)
PAPER_TABLE33_SIM_HZ: dict[str, list[float]] = {
    "bcc": [14.8, 49.8, 68.4],
    "af2q05": [15.4, 53.9, 94.3],
    "af2q1": [29.1, 44.4, 94.2],
    "af2q15": [15.4, 40.6, 67.8],
}

# Experiment column (Hz) — modes 1–3 (thesis Table 3.3)
PAPER_TABLE33_EXP_HZ: dict[str, list[float]] = {
    "bcc": [14.0, 46.8, 68.1],
    "af2q05": [18.0, 53.1, 90.1],
    "af2q1": [30.0, 47.6, 90.9],
    "af2q15": [16.0, 44.3, 63.6],
}

CASE_LABELS: dict[str, str] = {
    "bcc": "BCC Q=0",
    "af2q05": "SFBLS Q=0.5",
    "af2q1": "SFBLS Q=1.0",
    "af2q15": "SFBLS Q=1.5",
}

EIGEN_SLUGS: dict[str, str] = {
    "bcc": "comsol_fig321_bcc_444",
    "af2q05": "comsol_fig321_af2q05_444",
    "af2q1": "comsol_fig321_af2q1_444",
    "af2q15": "comsol_fig321_af2q15_444",
}

FREQ_SLUGS: dict[str, str] = {
    "bcc": "comsol_fig321_bcc_444_mesh_p1_300g_f5_150",
    "af2q05": "comsol_fig321_af2q05_444_mesh_p1_300g_f5_150",
    "af2q1": "comsol_fig321_af2q1_444_mesh_p1_300g_f5_150",
    "af2q15": "comsol_fig321_af2q15_444_mesh_p1_300g_f5_150",
}

# Slug substring hints when manifest key is absent
_SLUG_HINTS: tuple[tuple[str, str], ...] = (
    ("bcc", "bcc"),
    ("af2q05", "af2q05"),
    ("af2q1", "af2q1"),
    ("af2q15", "af2q15"),
    ("af0q0", "bcc"),
    ("af2q0", "bcc"),
)


def resolve_case_key(*, slug: str = "", variant: str = "", Q: float | None = None) -> str | None:
    """Map job slug / manifest fields to Table 3.3 case key."""
    text = f"{slug} {variant}".lower()
    for hint, key in _SLUG_HINTS:
        if hint in text:
            return key
    if Q is not None:
        q_map = {0.0: "bcc", 0.5: "af2q05", 1.0: "af2q1", 1.5: "af2q15"}
        return q_map.get(float(Q))
    return None


def paper_sim_hz(key: str | None) -> list[float] | None:
    if not key:
        return None
    return PAPER_TABLE33_SIM_HZ.get(key)


def paper_exp_hz(key: str | None) -> list[float] | None:
    if not key:
        return None
    return PAPER_TABLE33_EXP_HZ.get(key)
