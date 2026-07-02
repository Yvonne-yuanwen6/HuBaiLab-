"""OCP octant-cut + Glue fuse for a single BCC unit cell (no junction spheres)."""

from __future__ import annotations

import os
from typing import Any

from src.export.beam_utils import dedupe_beams
from src.export.export_sw import _collect_solid_primitives
from src.export.ocp_unitcell_fuse import export_q1_ocp_glue_unitcell
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator


def load_bcc_unitcell_pipe_parts(
    *,
    cell_size: float = 20.0,
    rod_diameter: float = 2.0,
    solid_profile: str = "circle",
    ellipse_minor_ratio: float = 0.6,
    compression_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    ellipse_align_to_compression: str = "minor",
) -> list[tuple[str, tuple, float]]:
    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size),
        rod_diameter=float(rod_diameter),
        amplitude=0.0,
        period_factor=0.0,
        n_segments=12,
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data()
    beams, _ = dedupe_beams(beams)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
        solid_profile=solid_profile,
        ellipse_minor_ratio=ellipse_minor_ratio,
        compression_axis=compression_axis,
        ellipse_align_to_compression=ellipse_align_to_compression,
    )
    pipe_parts = [p for p in parts if p[0] in ("pipe", "pipe_ellipse")]
    if len(pipe_parts) != 8:
        raise RuntimeError(f"expected 8 BCC pipe parts, got {len(pipe_parts)}")
    return pipe_parts


def export_ocp_bcc_unitcell_step(
    out_step: str,
    *,
    cell_size: float = 20.0,
    rod_diameter: float = 2.0,
    solid_profile: str = "circle",
    ellipse_minor_ratio: float = 0.6,
    compression_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    ellipse_align_to_compression: str = "minor",
    fuzzy_mm: float = 0.02,
    parts: list[tuple[str, tuple, float]] | None = None,
    ellipse_sweep_mode: str = "frenet",
) -> dict[str, Any]:
    """
  BCC unit cell via octant box cut + OCP GlueShift fuse (no junction spheres).

  Straight 2-point BCC struts use ``both_end_extension`` pipe mode.
  """
    if parts is None:
        parts = load_bcc_unitcell_pipe_parts(
            cell_size=cell_size,
            rod_diameter=rod_diameter,
            solid_profile=solid_profile,
            ellipse_minor_ratio=ellipse_minor_ratio,
            compression_axis=compression_axis,
            ellipse_align_to_compression=ellipse_align_to_compression,
        )
    print(
        f"  OCP BCC octant fuse: {len(parts)} strut(s), profile={solid_profile}, "
        "no junction spheres...",
        flush=True,
    )
    report = export_q1_ocp_glue_unitcell(
        parts,
        out_step,
        cell_size_mm=float(cell_size),
        strategy="sequential_glue_shift",
        fuzzy_mm=float(fuzzy_mm),
        pipe_mode="both_end_extension",
        ellipse_sweep_mode=ellipse_sweep_mode,  # type: ignore[arg-type]
    )
    report["method"] = "ocp_bcc_octant_glue_fuse"
    report["solid_profile"] = solid_profile
    report["ellipse_sweep_mode"] = ellipse_sweep_mode
    return report
