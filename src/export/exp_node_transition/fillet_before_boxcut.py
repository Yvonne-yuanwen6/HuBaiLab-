"""
Isolated experiment: longer hub edges before MakeFillet.

Raw / L³-only extended-pipe fuse collapses for Q≥1 (OCC). Viable variant:
octant cut with *larger* ``center_overlap`` (less aggressive hub trim) → fuse →
MakeFillet → hard STEP. Outer faces stay at ±L/2 (already L³ RVE).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _assign_edge_for_slot,
    _bbox_span,
    _q_slug,
    _write_step_hard_solid,
    apply_slot_fillets,
    build_slots_for_params,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    load_fillet_pipe_parts,
)
from src.export.ocp_unitcell_fuse import (
    FuseStrategy,
    build_q1_octant_cut_shapes,
    fuse_octant_shapes,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)


def _slot_edge_stats(shape: Any, params: SlotFilletParams) -> list[dict[str, Any]]:
    slots = build_slots_for_params(params)
    rows: list[dict[str, Any]] = []
    used: set[tuple[float, float, float]] = set()
    for slot in slots:
        info = _assign_edge_for_slot(
            shape, slot, params, used_mids=used, max_edge_len_mm=None
        )
        rows.append(
            {
                "slot_id": slot.slot_id,
                "pair": [slot.i, slot.j],
                "theta_deg": float(slot.theta_deg),
                "assigned": info is not None,
                "length_mm": float(info["length_mm"]) if info else None,
            }
        )
    return rows


def _min_mean_max(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "mean": None, "max": None}
    return {
        "min": float(min(values)),
        "mean": float(sum(values) / len(values)),
        "max": float(max(values)),
    }


def _as_single_solid_safe(shape: Any) -> Any:
    from src.export.exp_node_transition.acute_slot_fillet import _as_single_solid

    try:
        return _as_single_solid(shape)
    except Exception:
        return shape


def fuse_octant_with_overlap(
    fp: ExpFilletParams,
    *,
    center_overlap_mm: float,
    pipe_mode: str = "both_end_extension",
    strategy: FuseStrategy = "sequential_glue_shift",
    fuzzy_mm: float = 0.02,
) -> tuple[Any, float, str, float]:
    """Octant-cut (variable hub overlap) + glue fuse. Returns shape, mass, tag, cut_sum."""
    parts = load_fillet_pipe_parts(fp)
    cuts, _pipe_ref, cut_sum = build_q1_octant_cut_shapes(
        parts,
        float(fp.cell_size_mm),
        center_overlap_mm=float(center_overlap_mm),
        pipe_mode=pipe_mode,  # type: ignore[arg-type]
    )
    merged, desc = fuse_octant_shapes(
        cuts,
        cut_mass=float(cut_sum),
        strategy=strategy,
        fuzzy_mm=float(fuzzy_mm),
        cell_size_mm=float(fp.cell_size_mm),
    )
    merged = ocp_heal_fused_solid(merged)
    mass = float(ocp_mass(merged))
    tag = f"octant_ov{center_overlap_mm:g}_{pipe_mode}_{strategy}"
    return merged, mass, f"{tag}|{desc}", float(cut_sum)


def fuse_overlap_ladder(
    fp: ExpFilletParams,
    *,
    overlaps: tuple[float, ...] = (2.0, 1.0, 4.0, 0.5, 0.02),
    pipe_mode: str = "both_end_extension",
) -> tuple[Any, float, str, float, float]:
    """Try center_overlap values; return first successful fuse."""
    q = abs(float(fp.period_factor))
    strategies: list[tuple[FuseStrategy, float]] = [
        ("sequential_glue_shift", 0.02),
        ("sequential_glue_full", 0.08),
        ("batch_glue_shift", 0.02),
    ]
    if q >= 1.0:
        # Q≥1: both_end first (matches bare ladder)
        pass
    last_exc: Exception | None = None
    for ov in overlaps:
        for strategy, fuzzy in strategies:
            tag = f"ov={ov:g} {strategy} f={fuzzy:g}"
            try:
                print(f"  [preBox] try {tag} ...", flush=True)
                fused, mass, fuse_tag, cut_sum = fuse_octant_with_overlap(
                    fp,
                    center_overlap_mm=float(ov),
                    pipe_mode=pipe_mode,
                    strategy=strategy,
                    fuzzy_mm=fuzzy,
                )
                return fused, mass, fuse_tag, float(ov), cut_sum
            except Exception as exc:
                last_exc = exc
                print(f"  [preBox] FAIL {tag}: {exc}", flush=True)
    raise RuntimeError(f"overlap fuse ladder failed; last={last_exc}")


def export_fillet_before_boxcut(
    params: SlotFilletParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
    pipe_mode: str = "both_end_extension",
    overlaps: tuple[float, ...] = (2.0, 1.0, 4.0, 0.5, 0.02),
    compare_baseline_ov: float | None = 0.02,
) -> dict[str, Any]:
    """
    Large-overlap octant fuse → MakeFillet → hard STEP.

    ``compare_baseline_ov``: also fuse with default overlap for edge-length delta.
    """
    params = params or SlotFilletParams()
    q = float(params.period_factor)
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    rf_tag = str(params.r_blend_factor).replace(".", "p")
    slug = (
        f"exp_preBoxFillet_af{int(round(params.amplitude_mm))}q{_q_slug(q)}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_rf{rf_tag}_1x1"
    )
    step_path = os.path.join(out_dir, f"{slug}.step")
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")

    if (
        not force
        and os.path.isfile(step_path)
        and os.path.getsize(step_path) > 1000
        and os.path.isfile(man_path)
    ):
        with open(man_path, encoding="utf-8") as f:
            return json.load(f)

    fp = ExpFilletParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=q,
        n_segments=params.n_segments,
    )

    edge_base: list[dict[str, Any]] = []
    lens_base: list[float] = []
    mass_base = None
    if compare_baseline_ov is not None:
        print(
            f"  [preBox] baseline ov={compare_baseline_ov:g} Q={q:g} ...",
            flush=True,
        )
        try:
            base, mass_base, _, _ = fuse_octant_with_overlap(
                fp,
                center_overlap_mm=float(compare_baseline_ov),
                pipe_mode=pipe_mode,
            )
            edge_base = _slot_edge_stats(base, params)
            lens_base = [
                r["length_mm"] for r in edge_base if r.get("length_mm") is not None
            ]
            print(
                f"  [preBox] baseline mass={mass_base:.2f} "
                f"edge={_min_mean_max(lens_base)}",
                flush=True,
            )
        except Exception as exc:
            print(f"  [preBox] baseline FAIL: {exc}", flush=True)

    print(f"  [preBox] overlap ladder Q={q:g} ...", flush=True)
    fused, mass_fused, fuse_tag, used_ov, cut_sum = fuse_overlap_ladder(
        fp, overlaps=overlaps, pipe_mode=pipe_mode
    )
    span_fused = _bbox_span(fused)
    edge_pre = _slot_edge_stats(fused, params)
    lens_pre = [r["length_mm"] for r in edge_pre if r.get("length_mm") is not None]
    print(
        f"  [preBox] fused ov={used_ov:g} mass={mass_fused:.2f} span={span_fused} "
        f"edge={_min_mean_max(lens_pre)} vs baseline={_min_mean_max(lens_base)}",
        flush=True,
    )

    print("  [preBox] MakeFillet ...", flush=True)
    filleted, fil_info = apply_slot_fillets(
        fused,
        params,
        max_edge_len_mm=None,
        max_span_factor=1.35,
    )
    filleted = _as_single_solid_safe(filleted)
    mass_fil = float(ocp_mass(filleted))
    span_fil = _bbox_span(filleted)
    topo_fil = ocp_shape_topology(filleted, check_brep=True)

    hard_ok = False
    hard_err: str | None = None
    readback = None
    try:
        readback = _write_step_hard_solid(
            filleted,
            step_path,
            mass_ref=mass_fil,
            max_drift=max(float(params.max_step_mass_drift_mm3), 1.2),
            max_span_mm=float(params.cell_size_mm) * 1.15,
        )
        hard_ok = True
    except Exception as exc:
        hard_err = str(exc)[:400]
        ocp_write_step(filleted, step_path)

    manifest: dict[str, Any] = {
        "method": "large_overlap_octant_fillet",
        "note": (
            "Raw extended-pipe fuse (no octant) collapses for Q>=1; "
            "this path uses larger center_overlap instead."
        ),
        "step_path": os.path.abspath(step_path),
        "period_factor": q,
        "params": asdict(params),
        "pipe_mode": pipe_mode,
        "fuse_tag": fuse_tag,
        "center_overlap_mm": used_ov,
        "masses_mm3": {
            "octant_cut_sum": cut_sum,
            "fused": mass_fused,
            "filleted": mass_fil,
            "baseline_ov002": mass_base,
            "dm_fillet_vs_fused": mass_fil - mass_fused,
        },
        "spans_mm": {
            "fused": list(span_fused),
            "filleted": list(span_fil),
        },
        "edge_lengths_mm": {
            "baseline_ov002": edge_base,
            "large_overlap": edge_pre,
            "baseline_min_mean_max": _min_mean_max(lens_base),
            "large_overlap_min_mean_max": _min_mean_max(lens_pre),
        },
        "fillet": fil_info,
        "filleted_topology": topo_fil,
        "hard_step_ok": hard_ok,
        "hard_step_error": hard_err,
    }
    if readback is not None:
        rb_topo = ocp_shape_topology(readback, check_brep=True)
        manifest["step_readback"] = {
            "mass_mm3": float(ocp_mass(readback)),
            "topology": rb_topo,
            "brep_valid": bool(rb_topo.get("brep_valid")),
        }

    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(
        f"  [preBox] DONE Q={q:g} ov={used_ov:g} hard={hard_ok} "
        f"mass={mass_fil:.2f} dm={mass_fil - mass_fused:+.3f} "
        f"valid={topo_fil.get('brep_valid')} → {step_path}",
        flush=True,
    )
    return manifest
