"""Load Fig.2.5 TPU tensile test data (WPD) for Abaqus Marlow hyperelastic."""
from __future__ import annotations

import json
from pathlib import Path

from src.paths import PROJECT_ROOT

DEFAULT_TPU_FIG25_JSON = PROJECT_ROOT / "data" / "hu_bai_tpu_fig25_tensile_traced.json"


def _ensure_origin_anchor(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Marlow / hyperelastic test data must include undeformed reference (0, 0)."""
    if not pts:
        return pts
    e0, s0 = pts[0]
    if e0 > 1e-4:
        return [(0.0, 0.0), *pts]
    if abs(e0) <= 1e-4 and abs(s0) > 1e-4:
        return [(0.0, 0.0), *pts[1:]]
    return pts


def load_tpu_fig25_uniaxial(
    path: Path | str | None = None,
    *,
    stress_scale: float = 1.0,
) -> list[tuple[float, float]]:
    """Return (engineering_strain, engineering_stress_MPa) for *Uniaxial Test Data.

    ``stress_scale`` multiplies engineering stress only (strain unchanged). Use to
    soften/stiffen Marlow input relative to traced Fig.2.5 when lattice curves
    are systematically offset vs Fig.3.3 while keeping C3D4 mesh fixed.
    """
    p = Path(path) if path else DEFAULT_TPU_FIG25_JSON
    if not p.is_file():
        raise FileNotFoundError(f"TPU Fig.2.5 traced JSON missing: {p}")
    scale = float(stress_scale)
    if scale <= 0.0:
        raise ValueError(f"stress_scale must be > 0, got {scale}")
    data = json.loads(p.read_text(encoding="utf-8"))
    pts = [(float(a), float(b) * scale) for a, b in data.get("points") or []]
    pts = _ensure_origin_anchor(pts)
    if len(pts) < 3:
        raise ValueError(f"Too few points in {p}")
    return pts
