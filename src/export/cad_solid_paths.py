"""Resolve CAD solid paths (STEP / X_T) for Abaqus export."""

from __future__ import annotations

import os


def resolve_step_and_xt(cad_path: str) -> tuple[str, str | None]:
    """
    Return (step_path, xt_path_or_none).

    Mesher uses STEP; X_T is kept for manifest / manual Abaqus import.
    """
    cad_path = os.path.abspath(cad_path)
    if not os.path.isfile(cad_path):
        raise FileNotFoundError(cad_path)

    ext = os.path.splitext(cad_path)[1].lower()
    if ext in (".step", ".stp"):
        xt = os.path.splitext(cad_path)[0] + ".x_t"
        return cad_path, xt if os.path.isfile(xt) else None
    if ext == ".x_t":
        step = os.path.splitext(cad_path)[0] + ".step"
        if not os.path.isfile(step):
            raise FileNotFoundError(
                f"No sibling STEP for {cad_path}. Export fused STEP first "
                "(run_hu_bai_bcc_sw_export.py --cells N)."
            )
        return step, cad_path
    raise ValueError(f"Unsupported CAD extension: {cad_path}")
