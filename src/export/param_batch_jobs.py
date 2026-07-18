"""Picklable CAD attempt jobs for process-timeout wrappers.

Kept separate so ``multiprocessing`` spawn can import workers without
re-entering the batch CLI ``__main__``.
"""

from __future__ import annotations

import os
from typing import Any


def unitcell_gmsh_job(payload: dict[str, Any]) -> dict[str, Any]:
    from src.export.unitcell_box_cut import export_unitcell_step_paper_box_cut
    from src.generator.hu_bai_bcc import HuBaiLatticeGenerator

    out_step = str(payload["out_step"])
    if os.path.isfile(out_step):
        os.remove(out_step)

    gen = HuBaiLatticeGenerator(
        cell_size=float(payload["cell_size_mm"]),
        rod_diameter=float(payload["rod_diameter_mm"]),
        amplitude=float(payload["amplitude_mm"]),
        period_factor=float(payload["period_factor"]),
        n_segments=int(payload["n_segments"]),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    return export_unitcell_step_paper_box_cut(
        nodes,
        beams,
        out_step,
        polylines=polylines,
        cell_size_mm=float(payload["cell_size_mm"]),
        n_segments_hint=int(payload["n_segments"]),
        period_factor=float(payload["period_factor"]),
        q1_mode=str(payload.get("q1_mode") or "auto"),
        both_end_extension=bool(payload.get("both_end_extension")),
        rod_diameter_mm=float(payload["rod_diameter_mm"]),
        amplitude_mm=float(payload["amplitude_mm"]),
        solid_profile=str(payload["solid_profile"]),
        ellipse_minor_ratio=float(payload.get("ellipse_minor_ratio") or 1.0),
        compression_axis=tuple(payload.get("compression_axis") or (0.0, 0.0, 1.0)),
        ellipse_align_to_compression=str(
            payload.get("ellipse_align_to_compression") or "minor"
        ),
    )


def unitcell_ocp_job(payload: dict[str, Any]) -> dict[str, Any]:
    from src.export.export_sw import _collect_solid_primitives
    from src.export.ocp_unitcell_fuse import export_q1_ocp_glue_unitcell
    from src.generator.hu_bai_bcc import HuBaiLatticeGenerator

    out_step = str(payload["out_step"])
    if os.path.isfile(out_step):
        os.remove(out_step)

    gen = HuBaiLatticeGenerator(
        cell_size=float(payload["cell_size_mm"]),
        rod_diameter=float(payload["rod_diameter_mm"]),
        amplitude=float(payload["amplitude_mm"]),
        period_factor=float(payload["period_factor"]),
        n_segments=int(payload["n_segments"]),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    profile = str(payload["solid_profile"])
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
        solid_profile=profile,
        ellipse_minor_ratio=float(payload.get("ellipse_minor_ratio") or 1.0),
        compression_axis=tuple(payload.get("compression_axis") or (0.0, 0.0, 1.0)),
        ellipse_align_to_compression=str(
            payload.get("ellipse_align_to_compression") or "minor"
        ),
    )
    pipe_parts = [p for p in parts if p[0] in ("pipe", "pipe_ellipse")]
    kwargs: dict[str, Any] = {
        "cell_size_mm": float(payload["cell_size_mm"]),
        "strategy": str(payload.get("strategy") or "sequential_glue_shift"),
        "fuzzy_mm": float(payload.get("fuzzy_mm") or 0.05),
        "pipe_mode": str(payload.get("pipe_mode") or "centre_stub"),
    }
    if payload.get("center_overlap_mm") is not None:
        kwargs["center_overlap_mm"] = float(payload["center_overlap_mm"])
    if payload.get("centre_extension_mm") is not None:
        kwargs["centre_extension_mm"] = float(payload["centre_extension_mm"])
        kwargs["corner_extension_mm"] = float(
            payload.get("corner_extension_mm") or payload["centre_extension_mm"]
        )
    if profile == "ellipse":
        kwargs["ellipse_sweep_mode"] = "frenet"
    return export_q1_ocp_glue_unitcell(pipe_parts, out_step, **kwargs)


def strut_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Export one paper-box octant-cut strut (+ optional pre-cut raw STEP)."""
    import importlib.util

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    mod_path = os.path.join(root, "scripts", "export_single_strut_paper_box_cut.py")
    spec = importlib.util.spec_from_file_location(
        "export_single_strut_paper_box_cut", mod_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load single-strut exporter: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out_step = str(payload["out_step"])
    if os.path.isfile(out_step):
        os.remove(out_step)
    raw_out = payload.get("raw_out_step")
    raw_out_s = str(raw_out) if raw_out else None
    if raw_out_s and os.path.isfile(raw_out_s):
        os.remove(raw_out_s)
    return mod.export_single_strut_paper_box_cut(
        period_factor=float(payload["period_factor"]),
        strut_index=int(payload.get("strut_index") or 1),
        cell_size_mm=float(payload.get("cell_size_mm") or 20.0),
        n_segments=int(payload.get("n_segments") or 24),
        rod_diameter=float(payload["rod_diameter_mm"]),
        amplitude=float(payload["amplitude_mm"]),
        out_path=out_step,
        raw_out_path=raw_out_s,
        origin_assembly=bool(payload.get("origin_assembly", True)),
        both_end_extension=bool(payload.get("both_end_extension", True)),
        centre_extension_mm=(
            float(payload["centre_extension_mm"])
            if payload.get("centre_extension_mm") is not None
            else None
        ),
        corner_extension_mm=(
            float(payload["corner_extension_mm"])
            if payload.get("corner_extension_mm") is not None
            else None
        ),
        solid_profile=str(payload.get("solid_profile") or "circle"),
        ellipse_minor_ratio=float(payload.get("ellipse_minor_ratio") or 1.0),
        compression_axis=tuple(payload.get("compression_axis") or (0.0, 0.0, 1.0)),
        ellipse_align_to_compression=str(
            payload.get("ellipse_align_to_compression") or "minor"
        ),
    )


def array_ocp_job(payload: dict[str, Any]) -> dict[str, Any]:
    from src.export.ocp_paper_box_array_fuse import (
        export_ocp_paper_box_layered_array_fuse,
    )

    work_array = str(payload["work_array"])
    if os.path.isfile(work_array):
        os.remove(work_array)
    return export_ocp_paper_box_layered_array_fuse(
        str(payload["seed_step"]),
        work_array,
        nx=int(payload["nx"]),
        ny=int(payload["ny"]),
        nz=int(payload["nz"]),
        cell_size=float(payload["cell_size"]),
        force=True,
        inter_cell_fuse_mode=str(payload.get("inter_cell_fuse_mode") or "sequential"),
        row_glue=str(payload.get("row_glue") or "full"),  # type: ignore[arg-type]
        row_fuzzy_mm=float(payload.get("row_fuzzy_mm") or 0.05),
        inter_row_glue=str(payload.get("inter_row_glue") or "shift"),  # type: ignore[arg-type]
        inter_row_fuzzy_mm=float(payload.get("inter_row_fuzzy_mm") or 0.05),
        periodic_overlap_mm=float(payload.get("periodic_overlap_mm") or 0.02),
        clip_to_periodic_box=bool(payload.get("clip_to_periodic_box", True)),
    )


def array_gmsh_job(payload: dict[str, Any]) -> dict[str, Any]:
    from src.export.paper_box_array_fuse import export_paper_box_layered_array_fuse

    work_array = str(payload["work_array"])
    if os.path.isfile(work_array):
        os.remove(work_array)
    return export_paper_box_layered_array_fuse(
        str(payload["seed_step"]),
        work_array,
        nx=int(payload["nx"]),
        ny=int(payload["ny"]),
        nz=int(payload["nz"]),
        cell_size=float(payload["cell_size"]),
        force=bool(payload.get("force", True)),
        fuse_strategy=str(payload.get("fuse_strategy") or "row_sequential"),
    )


def array_seed_gmsh_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Hard-case ladder: translate 1×1 seed grid → gmsh BREP fuse (no rebuild)."""
    from src.export.ocp_deep_pad_array_fuse import export_seed_translate_gmsh_array_fuse

    work_array = str(payload["work_array"])
    if os.path.isfile(work_array):
        os.remove(work_array)
    return export_seed_translate_gmsh_array_fuse(
        str(payload["seed_step"]),
        work_array,
        nx=int(payload["nx"]),
        ny=int(payload["ny"]),
        nz=int(payload["nz"]),
        cell_size=float(payload["cell_size"]),
        nudge_mm=float(payload.get("nudge_mm") or 0.0),
        force=True,
    )


def array_seed_scale_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Hard-case ladder: scale-inflate → fuse iz0 slab → +Z-copy → 444 fuse."""
    from src.export.ocp_deep_pad_array_fuse import export_seed_scale_inflate_array_fuse

    work_array = str(payload["work_array"])
    if os.path.isfile(work_array):
        os.remove(work_array)
    return export_seed_scale_inflate_array_fuse(
        str(payload["seed_step"]),
        work_array,
        nx=int(payload["nx"]),
        ny=int(payload["ny"]),
        nz=int(payload["nz"]),
        cell_size=float(payload["cell_size"]),
        scale=float(payload.get("scale") or 1.005),
        glue=str(payload.get("glue") or "off"),  # type: ignore[arg-type]
        fuzzy_mm=float(payload.get("fuzzy_mm") or 0.1),
        force=True,
    )


def array_noclip_batch_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Hard-case ladder: noclip place all cells → one-shot OCP batch fuse."""
    from src.export.ocp_deep_pad_array_fuse import export_ocp_noclip_batch_array_fuse

    work_array = str(payload["work_array"])
    if os.path.isfile(work_array):
        os.remove(work_array)
    return export_ocp_noclip_batch_array_fuse(
        str(payload["seed_step"]),
        work_array,
        nx=int(payload["nx"]),
        ny=int(payload["ny"]),
        nz=int(payload["nz"]),
        cell_size=float(payload["cell_size"]),
        glue=str(payload.get("glue") or "shift"),  # type: ignore[arg-type]
        fuzzy_mm=float(payload.get("fuzzy_mm") or 0.1),
        force=True,
    )


def array_scale_batch_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Hard-case ladder: scale-inflate cells → one-shot OCP batch (no zcopy)."""
    from src.export.ocp_deep_pad_array_fuse import export_ocp_scale_batch_array_fuse

    work_array = str(payload["work_array"])
    if os.path.isfile(work_array):
        os.remove(work_array)
    return export_ocp_scale_batch_array_fuse(
        str(payload["seed_step"]),
        work_array,
        nx=int(payload["nx"]),
        ny=int(payload["ny"]),
        nz=int(payload["nz"]),
        cell_size=float(payload["cell_size"]),
        scale=float(payload.get("scale") or 1.005),
        glue=str(payload.get("glue") or "shift"),  # type: ignore[arg-type]
        fuzzy_mm=float(payload.get("fuzzy_mm") or 0.1),
        force=True,
    )


def array_deep_pad_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Hard-case ladder: rebuild cells with deep periodic pad, then gated fuse."""
    from src.export.ocp_deep_pad_array_fuse import (
        export_ocp_deep_pad_layered_array_fuse,
        rod_params_from_deq_k,
    )

    work_array = str(payload["work_array"])
    if os.path.isfile(work_array):
        os.remove(work_array)
    deq = float(payload.get("deq_mm") or payload.get("rod_d") or 1.5)
    k = float(payload.get("k") or 1.0)
    profile, rod_d, minor = rod_params_from_deq_k(deq, k)
    if payload.get("solid_profile"):
        profile = str(payload["solid_profile"])
    if payload.get("rod_d") is not None and abs(k - 1.0) < 1e-9:
        rod_d = float(payload["rod_d"])
    if payload.get("ellipse_minor_ratio") is not None:
        minor = float(payload["ellipse_minor_ratio"])
    return export_ocp_deep_pad_layered_array_fuse(
        str(payload["seed_step"]),
        work_array,
        nx=int(payload["nx"]),
        ny=int(payload["ny"]),
        nz=int(payload["nz"]),
        cell_size=float(payload["cell_size"]),
        rod_d=float(rod_d),
        amplitude=float(payload.get("amplitude") or payload.get("Af") or 2.0),
        period_factor=float(payload.get("period_factor") or payload.get("Q") or 1.0),
        solid_profile=str(profile),
        ellipse_minor_ratio=float(minor),
        pad_mm=float(payload.get("pad_mm") or 2.0),
        glue=str(payload.get("glue") or "full"),  # type: ignore[arg-type]
        fuzzy_mm=float(payload.get("fuzzy_mm") or 0.05),
        cell_fuzzy_mm=float(payload.get("cell_fuzzy_mm") or 0.1),
        force=True,
    )
