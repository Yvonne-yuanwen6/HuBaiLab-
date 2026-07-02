"""Load Fig.2.5 TPU tensile test data (WPD) for Abaqus Marlow hyperelastic."""
from __future__ import annotations

import json
from pathlib import Path

from src.paths import PROJECT_ROOT

DEFAULT_TPU_FIG25_JSON = PROJECT_ROOT / "data" / "hu_bai_tpu_fig25_tensile_traced.json"


def load_tpu_fig25_uniaxial(path: Path | str | None = None) -> list[tuple[float, float]]:
    """Return (engineering_strain, engineering_stress_MPa) for *Uniaxial Test Data."""
    p = Path(path) if path else DEFAULT_TPU_FIG25_JSON
    if not p.is_file():
        raise FileNotFoundError(f"TPU Fig.2.5 traced JSON missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    pts = [(float(a), float(b)) for a, b in data.get("points") or []]
    if len(pts) < 3:
        raise ValueError(f"Too few points in {p}")
    return pts
