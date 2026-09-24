"""BCC unit cell with explicit centre/corner junction cores (experiment only).

Design (Yang et al. grain-boundary analogy, single-topology special case):
  - Strut pipes optionally endpoint-shrunk near nodes (``L_shrink_*``).
  - Explicit sphere cores at cell centre and eight cube corners.
  - Corner cores are L³-clipped so only the in-cell portion remains (paper_box).
  - Final solid is L³ box-cut and fused; main-path batch recipes are untouched.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from src.export.export_sw import _collect_solid_primitives
from src.export.ocp_paper_box_array_fuse import export_ocp_paper_box_zslab_fuse
from src.export.ocp_unitcell_fuse import (
    _box_from_bounds,
    fuse_octant_shapes,
    ocp_common,
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_pipe_with_centre_stub,
    ocp_shape_topology,
    ocp_write_step_via_gmsh_brep_heal,
)
from src.export.unitcell_box_cut import (
    OCTANT_CENTER_OVERLAP_MM,
    _octant_bounds_from_corner_mm,
    extend_pipe_path_past_corner,
    octant_centre_path_extension_mm,
    unitcell_box_bounds_mm,
    unitcell_octant_corners_mm,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator


@dataclass(frozen=True)
class ExpNodeTransitionParams:
    """Tunable explicit-core transition zone (experiment)."""

    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 0.0
    n_segments: int = 24
    # Core radii as multiples of strut radius R = rod_d/2
    r_core_centre_factor: float = 1.25
    r_core_corner_factor: float = 1.10
    # Path endpoint shrink along chord [mm].
    # Use None to auto = 0.55 * corresponding core radius (guarantees pipe∩core).
    # For Q>0, auto becomes 0 (centre_stub already bridges the hub; shrink
    # fights octant fuse). Pass explicit values only when cores are oversized.
    l_shrink_centre_mm: float | None = None
    l_shrink_corner_mm: float | None = None
    # Q>0: build pipes with centre chord stub (+ optional corner path ext)
    use_centre_stub: bool | None = None  # None → auto True when Q!=0
    corner_extension_mm: float | None = None
    enable_centre_core: bool = True
    enable_corner_cores: bool = True
    # Unit-cell strut/core overlap needs real boolean (GlueOff); GlueShift
    # can silently drop overlapping rods (smoke: 8×52 → ~104 mm³).
    fuse_fuzzy_mm: float = 0.02
    glue: str = "off"


def _strut_radius(params: ExpNodeTransitionParams) -> float:
    return 0.5 * float(params.rod_d_mm)


def _core_radii_mm(params: ExpNodeTransitionParams) -> tuple[float, float]:
    r = _strut_radius(params)
    return (
        float(params.r_core_centre_factor) * r,
        float(params.r_core_corner_factor) * r,
    )


def _wants_centre_stub(params: ExpNodeTransitionParams) -> bool:
    if params.use_centre_stub is not None:
        return bool(params.use_centre_stub)
    return abs(float(params.period_factor)) > 1e-12


def _resolved_shrink_mm(params: ExpNodeTransitionParams) -> tuple[float, float]:
    """Shrink must be < core radius so open pipe ends stay inside the cores."""
    r_c, r_k = _core_radii_mm(params)
    sc = params.l_shrink_centre_mm
    sk = params.l_shrink_corner_mm
    # Q>0 + centre_stub: default shrink off (stub provides hub continuity).
    if sc is None:
        if _wants_centre_stub(params):
            sc = 0.0
        else:
            sc = 0.55 * r_c if params.enable_centre_core else 0.0
    if sk is None:
        if _wants_centre_stub(params):
            sk = 0.0
        else:
            sk = 0.55 * r_k if params.enable_corner_cores else 0.0
    sc = float(sc)
    sk = float(sk)
    if params.enable_centre_core and sc >= 0.95 * r_c and sc > 0.0:
        raise ValueError(
            f"l_shrink_centre_mm={sc:g} must be < ~0.95*R_core_centre={r_c:g} "
            "(pipe must penetrate centre core)"
        )
    if params.enable_corner_cores and sk >= 0.95 * r_k and sk > 0.0:
        raise ValueError(
            f"l_shrink_corner_mm={sk:g} must be < ~0.95*R_core_corner={r_k:g} "
            "(pipe must penetrate corner core)"
        )
    return sc, sk


def load_exp_pipe_parts(params: ExpNodeTransitionParams) -> list[tuple[str, tuple, float]]:
    gen = HuBaiLatticeGenerator(
        cell_size=float(params.cell_size_mm),
        rod_diameter=float(params.rod_d_mm),
        amplitude=float(params.amplitude_mm),
        period_factor=float(params.period_factor),
        n_segments=max(3, int(params.n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    _, pipes_only = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    pipe_parts = [p for p in pipes_only if p[0] == "pipe"]
    if len(pipe_parts) != 8:
        raise RuntimeError(f"expected 8 pipe parts, got {len(pipe_parts)}")
    return pipe_parts


def _shrink_polyline_endpoints(
    path_pts: tuple,
    *,
    shrink_centre_mm: float,
    shrink_corner_mm: float,
) -> tuple:
    """Trim chord-parameter ends; keep ≥3 samples for pipe sweep."""
    pts = np.asarray(path_pts, dtype=float)
    if pts.ndim != 2 or pts.shape[0] < 2:
        raise ValueError("pipe path needs ≥2 points")
    sc = max(0.0, float(shrink_centre_mm))
    sk = max(0.0, float(shrink_corner_mm))
    if sc <= 1e-12 and sk <= 1e-12:
        return tuple(tuple(float(v) for v in p) for p in pts)

    p0 = pts[0]
    p1 = pts[-1]
    chord = p1 - p0
    length = float(np.linalg.norm(chord))
    if length < 1e-9:
        return tuple(tuple(float(v) for v in p) for p in pts)
    if sc + sk >= 0.85 * length:
        raise ValueError(
            f"shrink too aggressive: centre={sc:g} corner={sk:g} chord={length:g} mm"
        )

    # Arc-length parameter along polyline
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total < 1e-9:
        return tuple(tuple(float(v) for v in p) for p in pts)
    s0 = sc
    s1 = total - sk
    if s1 <= s0 + 1e-6:
        raise ValueError("shrink left empty path")

    def _point_at(s: float) -> np.ndarray:
        s = float(np.clip(s, 0.0, total))
        if s <= 0.0:
            return pts[0].copy()
        if s >= total:
            return pts[-1].copy()
        i = int(np.searchsorted(cum, s, side="right") - 1)
        i = max(0, min(i, len(seg) - 1))
        t = (s - cum[i]) / max(seg[i], 1e-15)
        return (1.0 - t) * pts[i] + t * pts[i + 1]

    keep = [p for p, c in zip(pts, cum) if s0 < c < s1]
    new_pts = [_point_at(s0), *keep, _point_at(s1)]
    # Deduplicate nearly coincident samples
    cleaned: list[np.ndarray] = [new_pts[0]]
    for p in new_pts[1:]:
        if float(np.linalg.norm(p - cleaned[-1])) > 1e-6:
            cleaned.append(p)
    if len(cleaned) < 2:
        raise RuntimeError("shrink produced <2 path points")
    if len(cleaned) == 2:
        mid = 0.5 * (cleaned[0] + cleaned[1])
        cleaned = [cleaned[0], mid, cleaned[1]]
    return tuple(tuple(float(v) for v in p) for p in cleaned)


def _ocp_sphere(center: tuple[float, float, float], radius: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeSphere(
        gp_Pnt(float(center[0]), float(center[1]), float(center[2])),
        float(radius),
    ).Shape()


def _fuse_sequential(
    shapes: list[Any],
    *,
    glue: str,
    fuzzy_mm: float,
    label_prefix: str,
) -> Any:
    if not shapes:
        raise ValueError("no shapes to fuse")
    acc = shapes[0]
    for i, sh in enumerate(shapes[1:], start=2):
        acc = ocp_fuse_pair(
            acc,
            sh,
            glue=glue,  # type: ignore[arg-type]
            fuzzy_mm=float(fuzzy_mm),
            label=f"{label_prefix}-{i}",
        )
        m = ocp_mass(acc)
        if m <= 0.0:
            raise RuntimeError(f"{label_prefix}-{i}: fuse emptied solid")
    return acc


def _fuse_shapes_resilient(
    shapes: list[Any],
    *,
    cut_mass: float,
    label: str,
    cell_size_mm: float,
) -> Any:
    """Try several fuse strategies. GlueShift octant path only for exactly 8 solids."""
    errors: list[str] = []
    if len(shapes) == 8:
        try:
            merged, desc = fuse_octant_shapes(
                shapes,
                cut_mass=cut_mass,
                strategy="sequential_glue_shift",
                fuzzy_mm=1e-3,
                cell_size_mm=cell_size_mm,
            )
            print(f"  [exp] {label}: OK via {desc}", flush=True)
            return merged
        except Exception as exc:
            errors.append(f"sequential_glue_shift: {exc}")
            print(f"  [exp] {label}: sequential_glue_shift failed: {exc}", flush=True)

    for name, glue, fuzzy in (
        ("glue_off_0p02", "off", 0.02),
        ("glue_off_0p05", "off", 0.05),
        ("glue_shift_0p05", "shift", 0.05),
    ):
        try:
            merged = _fuse_sequential(
                shapes, glue=glue, fuzzy_mm=fuzzy, label_prefix=f"{label}-{name}"
            )
            merged_mass = ocp_mass(merged)
            if cut_mass > 0.0 and merged_mass < 0.85 * cut_mass:
                raise RuntimeError(
                    f"{name}: mass {merged_mass:.1f} < 85% of cut sum {cut_mass:.1f}"
                )
            print(
                f"  [exp] {label}: OK via {name} mass={merged_mass:.1f}",
                flush=True,
            )
            return merged
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"  [exp] {label}: {name} failed: {exc}", flush=True)
    raise RuntimeError(f"{label}: all fuse strategies failed: {errors}")


def build_exp_bcc_explicit_core_solid(
    params: ExpNodeTransitionParams,
) -> tuple[Any, dict[str, Any]]:
    """Build one origin-centred L³-cut solid with optional explicit junction cores."""
    pipe_parts = load_exp_pipe_parts(params)
    corners = unitcell_octant_corners_mm(params.cell_size_mm)
    box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
    r_c, r_k = _core_radii_mm(params)
    r_strut = _strut_radius(params)
    shrink_c, shrink_k = _resolved_shrink_mm(params)
    use_octant = abs(float(params.period_factor)) > 1e-12
    use_stub = _wants_centre_stub(params)
    auto_corner_ext = octant_centre_path_extension_mm(r_strut)
    corner_ext = (
        float(params.corner_extension_mm)
        if params.corner_extension_mm is not None
        else (auto_corner_ext if use_stub else 0.0)
    )

    cut_pipes: list[Any] = []
    pipe_mass_sum = 0.0
    for idx, part in enumerate(pipe_parts):
        path = part[1]
        radius = float(part[2])
        path = _shrink_polyline_endpoints(
            path,
            shrink_centre_mm=shrink_c,
            shrink_corner_mm=shrink_k,
        )
        if use_stub and corner_ext > 0.0:
            path = extend_pipe_path_past_corner(path, corner_ext)
        if use_stub:
            pipe_solid = ocp_pipe_with_centre_stub(path, radius)
        else:
            pipe_solid = ocp_pipe_along_points(path, radius)
        if use_octant:
            bounds = _octant_bounds_from_corner_mm(
                corners[idx],
                params.cell_size_mm,
                center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
            )
            cut = ocp_common(pipe_solid, _box_from_bounds(bounds))
        else:
            cut = ocp_common(pipe_solid, box)
        m = ocp_mass(cut)
        if m <= 0.0:
            raise RuntimeError(f"strut {idx + 1}: box/octant cut empty after shrink")
        cut_pipes.append(cut)
        pipe_mass_sum += m
        print(
            f"  [exp] strut {idx + 1}/8 cut mass={m:.2f} mm3 "
            f"(shrink c={shrink_c:g} k={shrink_k:g}, "
            f"{'octant' if use_octant else 'L3'}, "
            f"stub={use_stub}, corner_ext={corner_ext:g})",
            flush=True,
        )

    cores: list[Any] = []
    core_mass_sum = 0.0
    if params.enable_centre_core:
        sph = _ocp_sphere((0.0, 0.0, 0.0), r_c)
        sph = ocp_common(sph, box)
        m = ocp_mass(sph)
        if m <= 0.0:
            raise RuntimeError("centre core empty after box cut")
        cores.append(sph)
        core_mass_sum += m
        print(f"  [exp] centre core R={r_c:.3f} mm mass={m:.2f} mm3", flush=True)

    if params.enable_corner_cores:
        for i, corner in enumerate(corners, start=1):
            sph = _ocp_sphere(corner, r_k)
            sph = ocp_common(sph, box)
            m = ocp_mass(sph)
            if m <= 0.0:
                raise RuntimeError(f"corner core {i} empty after box cut")
            cores.append(sph)
            core_mass_sum += m
            print(
                f"  [exp] corner core {i}/8 at {corner} R={r_k:.3f} mm mass={m:.2f} mm3",
                flush=True,
            )

    print(
        f"  [exp] fusing {len(cut_pipes)} pipes + {len(cores)} cores "
        f"(Q={params.period_factor:g}, octant={use_octant})...",
        flush=True,
    )
    # Fuse pipes first (more stable), then attach cores.
    pipe_solid = _fuse_shapes_resilient(
        cut_pipes,
        cut_mass=pipe_mass_sum,
        label="pipes",
        cell_size_mm=params.cell_size_mm,
    )
    if cores:
        shapes = [pipe_solid, *cores]
        cut_mass = ocp_mass(pipe_solid) + core_mass_sum
        merged = _fuse_shapes_resilient(
            shapes,
            cut_mass=cut_mass,
            label="pipes+cores",
            cell_size_mm=params.cell_size_mm,
        )
    else:
        merged = pipe_solid

    # Final L³ clip (idempotent; guards fuse overhang)
    merged = ocp_common(merged, box)
    merged = ocp_heal_fused_solid(merged)
    merged_mass = ocp_mass(merged)
    if merged_mass <= 0.0:
        raise RuntimeError("explicit-core unit cell empty after final clip")

    topo = ocp_shape_topology(merged)
    n_solids = int(topo.get("solids") or 0)
    if n_solids != 1:
        raise RuntimeError(
            f"explicit-core unit cell expected 1 solid, got {n_solids} "
            f"(shrink c={shrink_c:g}/R_c={r_c:g}, k={shrink_k:g}/R_k={r_k:g}; "
            "increase core radius or reduce shrink so pipes penetrate cores)"
        )
    report: dict[str, Any] = {
        "experiment": "bcc_explicit_node_cores",
        "params": asdict(params),
        "strut_radius_mm": r_strut,
        "r_core_centre_mm": r_c,
        "r_core_corner_mm": r_k,
        "l_shrink_centre_resolved_mm": shrink_c,
        "l_shrink_corner_resolved_mm": shrink_k,
        "cut_mode": "octant" if use_octant else "L3",
        "centre_stub": use_stub,
        "corner_extension_mm": corner_ext,
        "pipe_cut_sum_mm3": pipe_mass_sum,
        "core_cut_sum_mm3": core_mass_sum,
        "merged_mass_mm3": merged_mass,
        "topology": topo,
        "main_path_untouched": True,
    }
    return merged, report


def build_exp_hub_fuse_solid(
    params: ExpNodeTransitionParams,
    *,
    force_centre_hub: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """Q>0 / hard SFBL S: fuse pipes onto a centre hub sphere, then corner cores.

    Af=2 Q=1.5 cannot octant/L³-pipe-merge reliably; the hub is both the
    connectivity bridge and the Yang-style transition core.
    """
    pipe_parts = load_exp_pipe_parts(params)
    corners = unitcell_octant_corners_mm(params.cell_size_mm)
    box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
    r_c, r_k = _core_radii_mm(params)
    r_strut = _strut_radius(params)

    if not (params.enable_centre_core or force_centre_hub):
        raise ValueError("hub fuse requires a centre hub")

    # Baseline may request a minimal hub (factor≈1.05) just for connectivity.
    hub_r = r_c if params.enable_centre_core else max(r_c, 1.05 * r_strut)
    acc = ocp_common(_ocp_sphere((0.0, 0.0, 0.0), hub_r), box)
    hub_mass = ocp_mass(acc)
    print(f"  [exp-hub] centre hub R={hub_r:.3f} mass={hub_mass:.2f}", flush=True)

    pipe_mass_sum = 0.0
    for idx, part in enumerate(pipe_parts):
        pipe = ocp_common(
            ocp_pipe_along_points(part[1], float(part[2])),
            box,
        )
        m = ocp_mass(pipe)
        if m <= 0.0:
            raise RuntimeError(f"hub fuse strut {idx + 1}: empty L3 cut")
        pipe_mass_sum += m
        acc = ocp_fuse_pair(
            acc,
            pipe,
            glue="off",
            fuzzy_mm=max(0.05, float(params.fuse_fuzzy_mm)),
            label=f"exp-hub-pipe-{idx + 1}",
        )
        merged_m = ocp_mass(acc)
        print(
            f"  [exp-hub] +strut {idx + 1}/8 pipe={m:.2f} merged={merged_m:.2f}",
            flush=True,
        )
        # Guard silent rod loss (OCC can return a thin remnant solid).
        min_expected = hub_mass + 0.55 * pipe_mass_sum
        if merged_m < min_expected:
            raise RuntimeError(
                f"hub fuse mass collapse after strut {idx + 1}: "
                f"{merged_m:.1f} < {min_expected:.1f} (raise R_core_centre)"
            )

    core_mass_sum = hub_mass
    if params.enable_corner_cores:
        for i, corner in enumerate(corners, start=1):
            sph = ocp_common(_ocp_sphere(corner, r_k), box)
            m = ocp_mass(sph)
            if m <= 0.0:
                raise RuntimeError(f"corner core {i} empty")
            core_mass_sum += m
            acc = ocp_fuse_pair(
                acc,
                sph,
                glue="off",
                fuzzy_mm=max(0.02, float(params.fuse_fuzzy_mm)),
                label=f"exp-hub-corner-{i}",
            )
            print(
                f"  [exp-hub] +corner {i}/8 R={r_k:.3f} mass={m:.2f} "
                f"merged={ocp_mass(acc):.2f}",
                flush=True,
            )

    acc = ocp_common(acc, box)
    acc = ocp_heal_fused_solid(acc)
    topo = ocp_shape_topology(acc)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"hub fuse expected 1 solid, got {topo.get('solids')}")

    report: dict[str, Any] = {
        "experiment": "bcc_hub_fuse_explicit_cores",
        "params": asdict(params),
        "strut_radius_mm": r_strut,
        "r_core_centre_mm": hub_r,
        "r_core_corner_mm": r_k if params.enable_corner_cores else 0.0,
        "pipe_cut_sum_mm3": pipe_mass_sum,
        "core_cut_sum_mm3": core_mass_sum,
        "merged_mass_mm3": ocp_mass(acc),
        "topology": topo,
        "cut_mode": "L3_hub_fuse",
        "main_path_untouched": True,
    }
    return acc, report


def export_exp_bcc_unitcell_explicit_cores(
    out_step: str,
    params: ExpNodeTransitionParams | None = None,
    *,
    write_manifest: bool = True,
) -> dict[str, Any]:
    """Export experimental 1×1 STEP (explicit cores). Never used by batch defaults."""
    params = params or ExpNodeTransitionParams()
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    print(f"\n=== EXP unitcell explicit cores → {out_step} ===", flush=True)
    # Q≥1: hub-first fuse (stable for Q=1.5 Af=2). Q=0 keeps L3/octant builder.
    if abs(float(params.period_factor)) >= 1.0 - 1e-12:
        solid, report = build_exp_hub_fuse_solid(params, force_centre_hub=True)
    else:
        solid, report = build_exp_bcc_explicit_core_solid(params)
    export_shape = ocp_heal_fused_solid(solid)
    step_rb = ocp_write_step_via_gmsh_brep_heal(export_shape, out_step)
    try:
        from src.export.sw_parasolid import recenter_step_bbox_to_origin

        recenter = recenter_step_bbox_to_origin(out_step)
    except Exception as exc:
        recenter = {"shifted": False, "error": str(exc)}

    report.update(
        {
            "step_path": out_step,
            "step_readback_topology": step_rb,
            "step_solid_ok": bool(step_rb.get("brep_valid")),
            "bbox_recenter": recenter,
        }
    )
    if write_manifest:
        man_path = os.path.splitext(out_step)[0] + "_manifest.json"
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        report["manifest_path"] = man_path
        print(f"  [exp] manifest → {man_path}", flush=True)
    print(
        f"  [exp] 1x1 mass={report['merged_mass_mm3']:.2f} mm3 "
        f"solids={report['topology'].get('solids')} "
        f"ok={report.get('step_solid_ok')}",
        flush=True,
    )
    return report


def export_exp_bcc_baseline_unitcell(
    out_step: str,
    params: ExpNodeTransitionParams | None = None,
    *,
    write_manifest: bool = True,
) -> dict[str, Any]:
    """Baseline 1×1 without visible cores.

    Q=0: local L³ pipe fuse.
    Q≥1: minimal centre hub (1.05R) for connectivity only — no corner cores.
    """
    params = params or ExpNodeTransitionParams()
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    if abs(float(params.period_factor)) < 1e-12:
        baseline = ExpNodeTransitionParams(
            cell_size_mm=params.cell_size_mm,
            rod_d_mm=params.rod_d_mm,
            amplitude_mm=params.amplitude_mm,
            period_factor=params.period_factor,
            n_segments=params.n_segments,
            r_core_centre_factor=params.r_core_centre_factor,
            r_core_corner_factor=params.r_core_corner_factor,
            l_shrink_centre_mm=0.0,
            l_shrink_corner_mm=0.0,
            enable_centre_core=False,
            enable_corner_cores=False,
            fuse_fuzzy_mm=params.fuse_fuzzy_mm,
            glue="off",
            use_centre_stub=False,
        )
        report = export_exp_bcc_unitcell_explicit_cores(
            out_step, baseline, write_manifest=write_manifest
        )
        report["experiment"] = "bcc_baseline_no_cores"
        if write_manifest and report.get("manifest_path"):
            with open(report["manifest_path"], "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
        return report

    # Minimal hub baseline for Q≥1 (esp. Q=1.5 Af=2).
    # Need R_c ≳ 2.0R for stable hub fuse; use same centre size as exp so the
    # visible delta is mainly corner cores (+ optional larger centre).
    baseline = ExpNodeTransitionParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=params.period_factor,
        n_segments=params.n_segments,
        r_core_centre_factor=max(2.0, float(params.r_core_centre_factor)),
        r_core_corner_factor=params.r_core_corner_factor,
        l_shrink_centre_mm=0.0,
        l_shrink_corner_mm=0.0,
        enable_centre_core=True,
        enable_corner_cores=False,
        fuse_fuzzy_mm=max(0.05, float(params.fuse_fuzzy_mm)),
        glue="off",
    )
    print(f"\n=== EXP baseline hub-min → {out_step} ===", flush=True)
    solid, report = build_exp_hub_fuse_solid(baseline, force_centre_hub=True)
    export_shape = ocp_heal_fused_solid(solid)
    step_rb = ocp_write_step_via_gmsh_brep_heal(export_shape, out_step)
    report.update(
        {
            "experiment": "bcc_baseline_min_hub",
            "step_path": out_step,
            "step_readback_topology": step_rb,
            "step_solid_ok": bool(step_rb.get("brep_valid")),
        }
    )
    if write_manifest:
        man_path = os.path.splitext(out_step)[0] + "_manifest.json"
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        report["manifest_path"] = man_path
    print(
        f"  [exp] baseline 1x1 mass={report['merged_mass_mm3']:.2f} mm3 → {out_step}",
        flush=True,
    )
    return report


def _export_exp_2x2x1_sequential_fallback(
    seed_step: str,
    array_step: str,
    *,
    cell_size_mm: float,
    fuzzy_mm: float = 0.05,
    glue: str = "shift",
) -> dict[str, Any]:
    """Minimal 2×2×1: load seed → 4 translates → sequential GlueShift fuse."""
    from src.export.export_sw import _lattice_cell_offset_xyz_mm
    from src.export.ocp_paper_box_array_fuse import (
        load_ocp_unitcell_shape,
        place_ocp_unitcell_grid,
    )

    seed_shape, seed_mass = load_ocp_unitcell_shape(
        seed_step,
        cell_size=float(cell_size_mm),
        rebuild_from_geometry=False,
    )
    offsets: list[tuple[float, float, float]] = []
    for iy in range(2):
        for ix in range(2):
            offsets.append(
                _lattice_cell_offset_xyz_mm(
                    ix,
                    iy,
                    0,
                    nx=2,
                    ny=2,
                    nz=1,
                    cell_size=float(cell_size_mm),
                    origin_centered=False,
                )
            )
    cells = place_ocp_unitcell_grid(
        seed_shape,
        offsets,
        cell_size=float(cell_size_mm),
        clip_to_periodic_box=False,
        clip_expand_mm=0.0,
    )
    print(
        f"  [exp fallback] sequential fuse 4 cells "
        f"(glue={glue}, fuzzy={fuzzy_mm:g}, seed_mass={seed_mass:.1f})...",
        flush=True,
    )
    fused = _fuse_sequential(
        list(cells),
        glue=glue,
        fuzzy_mm=float(fuzzy_mm),
        label_prefix="exp-2x2x1",
    )
    fused_mass = ocp_mass(fused)
    expected = 4.0 * float(seed_mass)
    ratio = fused_mass / expected if expected > 0.0 else 0.0
    if ratio < 0.90:
        raise RuntimeError(
            f"exp 2x2x1 fallback mass ratio {ratio:.3f} "
            f"(fused={fused_mass:.1f}, expected≈{expected:.1f})"
        )
    export_shape = ocp_heal_fused_solid(fused)
    step_rb = ocp_write_step_via_gmsh_brep_heal(export_shape, array_step)
    return {
        "step_path": os.path.abspath(array_step),
        "method": "exp_2x2x1_sequential_fallback",
        "seed_mass_mm3": seed_mass,
        "fused_mass_mm3": fused_mass,
        "mass_ratio": ratio,
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "step_readback_topology": step_rb,
        "cells": [2, 2, 1],
    }


def export_exp_bcc_zslab_2x2x1(
    seed_step: str,
    array_step: str,
    *,
    cell_size_mm: float = 20.0,
    force: bool = False,
) -> dict[str, Any]:
    """2×2×1 planar array via OCP z-slab fuse, with sequential fallback."""
    seed_step = os.path.abspath(seed_step)
    array_step = os.path.abspath(array_step)
    os.makedirs(os.path.dirname(array_step) or ".", exist_ok=True)
    print("\n=== EXP 2x2x1 z-slab fuse ===", flush=True)
    print(f"  seed:  {seed_step}", flush=True)
    print(f"  array: {array_step}", flush=True)
    if (not force) and os.path.isfile(array_step):
        print(f"  [skip] exists (use --force): {array_step}", flush=True)
        return {"step_path": array_step, "skipped": True, "cells": [2, 2, 1]}

    attempts: list[dict[str, Any]] = [
        {
            "inter_cell_fuse_mode": "sequential",
            "row_glue": "shift",
            "row_fuzzy_mm": 0.05,
            "inter_row_glue": "shift",
            "inter_row_fuzzy_mm": 0.05,
            "clip_to_periodic_box": False,
        },
        {
            "inter_cell_fuse_mode": "sequential",
            "row_glue": "full",
            "row_fuzzy_mm": 0.08,
            "inter_row_glue": "shift",
            "inter_row_fuzzy_mm": 0.05,
            "clip_to_periodic_box": False,
        },
        {
            "inter_cell_fuse_mode": "hierarchical_batch",
            "row_glue": "shift",
            "row_fuzzy_mm": 0.05,
            "inter_row_glue": "shift",
            "inter_row_fuzzy_mm": 0.05,
            "clip_to_periodic_box": True,
            "periodic_overlap_mm": 0.05,
        },
    ]

    errors: list[str] = []
    report: dict[str, Any] | None = None
    for i, kw in enumerate(attempts, start=1):
        try:
            print(f"  [exp] z-slab attempt {i}/{len(attempts)}: {kw}", flush=True)
            report = export_ocp_paper_box_zslab_fuse(
                seed_step,
                array_step,
                nx=2,
                ny=2,
                iz=0,
                nz_total=1,
                cell_size=float(cell_size_mm),
                periodic_overlap_mm=float(kw.get("periodic_overlap_mm", 0.02)),
                clip_to_periodic_box=bool(kw["clip_to_periodic_box"]),
                inter_cell_fuse_mode=str(kw["inter_cell_fuse_mode"]),
                row_glue=kw["row_glue"],  # type: ignore[arg-type]
                row_fuzzy_mm=float(kw["row_fuzzy_mm"]),
                inter_row_glue=kw["inter_row_glue"],  # type: ignore[arg-type]
                inter_row_fuzzy_mm=float(kw["inter_row_fuzzy_mm"]),
            )
            report["zslab_attempt"] = kw
            break
        except Exception as exc:
            msg = f"attempt {i}: {exc}"
            errors.append(msg)
            print(f"  [exp] z-slab failed: {msg}", flush=True)
            if os.path.isfile(array_step):
                try:
                    os.remove(array_step)
                except OSError:
                    pass

    if report is None:
        print("  [exp] z-slab ladder failed → sequential fallback", flush=True)
        report = _export_exp_2x2x1_sequential_fallback(
            seed_step,
            array_step,
            cell_size_mm=float(cell_size_mm),
        )
        report["zslab_errors"] = errors

    report["experiment"] = "bcc_explicit_cores_2x2x1"
    report["cells"] = [2, 2, 1]
    report["main_path_untouched"] = True
    man_path = os.path.splitext(array_step)[0] + "_manifest.json"
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    report["manifest_path"] = man_path
    return report


def default_exp_out_dir() -> str:
    from src.paths import CAD_ROOT, ensure_output_dirs

    ensure_output_dirs()
    path = os.path.join(str(CAD_ROOT), "_exp_node_transition")
    os.makedirs(path, exist_ok=True)
    return path
