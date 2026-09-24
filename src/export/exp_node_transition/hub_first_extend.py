"""
Hub-first then extend unitcell (experiment isolation).

Build a smooth centre kernel (short stubs + rolling-ball canals), then grow
equal-R outer arms along the same SFBL centrelines to the cube corners.

Not the sphere connectivity assist in ``build_exp_hub_fuse_solid``.
Does not change batch / paper_box / hard CAD delivery defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.bcc_scheme_b_blend import (
    _clean_path,
    _cluster_indices,
    _point_at_arc_s,
    _remelt_to_one,
    _rolling_ball_centers_pair,
)
from src.export.exp_node_transition.centre_armpit_blend import (
    _angle_deg,
    _pick_acute_wedge_center,
    _unit,
)
from src.export.ocp_unitcell_fuse import (
    _box_from_bounds,
    ocp_common,
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_shape_topology,
)
from src.export.unitcell_box_cut import unitcell_box_bounds_mm


@dataclass
class HubFirstParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.0
    n_segments: int = 32
    # Hub stub arc length from cell centre (mm)
    s_hub_mm: float = 4.0
    # Outer arm starts this far before s_hub so fuse overlaps the kernel
    arm_overlap_mm: float = 1.2
    # Canal samples along hub stubs
    canal_s_start_mm: float = 1.0
    canal_s_end_mm: float | None = None  # default → 0.85 * s_hub
    canal_s_samples: int = 7
    # Acute pair selection (deg)
    pair_angle_min_deg: float = 5.0
    pair_angle_max_deg: float = 40.0  # keep acute cluster crotches, drop ~90°
    max_pairs: int = 8
    same_cluster_only: bool = True
    adjacent_in_cluster: bool = True
    # Rolling-ball blend radius as fraction of strut R
    r_blend_factor: float = 0.40
    penetrate_factor: float = 0.12
    # Hub sphere radius / strut R. Plan target is ~3–5 mm (R_strut=1 → 3.5).
    seed_sphere_factor: float = 3.5
    fuse_fuzzy_mm: float = 0.05
    # canal tool: "pipe" | "beads" | "auto"
    canal_tool: str = "beads"
    include_stubs: bool = False
    extend_full_pipes: bool = False
    canals_on_kernel: bool = True
    canals_after_extend: bool = False
    min_canal_dmass_mm3: float = 0.02
    max_span_mm: float = 26.0
    max_mass_drift_vs_stubs_mm3: float = 80.0


def _strut_r(params: HubFirstParams) -> float:
    return 0.5 * float(params.rod_d_mm)


def _path_arc_length(path_pts: tuple) -> float:
    P = np.asarray(path_pts, dtype=float)
    if len(P) < 2:
        return 0.0
    return float(np.sum(np.linalg.norm(np.diff(P, axis=0), axis=1)))


def _slice_path_by_arc(
    path_pts: tuple,
    s0_mm: float,
    s1_mm: float,
    *,
    min_pts: int = 3,
) -> tuple[tuple[float, float, float], ...]:
    """Extract polyline samples on arc interval [s0, s1] (inclusive ends)."""
    P = np.asarray(path_pts, dtype=float)
    if len(P) < 2:
        raise ValueError("path too short")
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    a = max(0.0, min(float(s0_mm), total))
    b = max(0.0, min(float(s1_mm), total))
    if b <= a + 1e-9:
        raise ValueError(f"empty arc slice [{a:g},{b:g}] total={total:g}")

    # densify: keep original vertices in range + endpoints
    pts: list[np.ndarray] = [_point_at_arc_s(path_pts, a)]
    for i in range(1, len(P) - 1):
        if a < float(cum[i]) < b:
            pts.append(P[i].copy())
    pts.append(_point_at_arc_s(path_pts, b))

    # drop near-duplicates
    cleaned: list[tuple[float, float, float]] = []
    for p in pts:
        t = (float(p[0]), float(p[1]), float(p[2]))
        if not cleaned or float(np.linalg.norm(np.asarray(t) - np.asarray(cleaned[-1]))) > 0.04:
            cleaned.append(t)
    if len(cleaned) < min_pts:
        # pad with mid samples
        mid = 0.5 * (a + b)
        extra = [
            _point_at_arc_s(path_pts, a),
            _point_at_arc_s(path_pts, mid),
            _point_at_arc_s(path_pts, b),
        ]
        cleaned = [
            (float(p[0]), float(p[1]), float(p[2])) for p in extra
        ]
    return tuple(cleaned)


def _centre_tangents(parts: list[tuple[str, tuple, float]]) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for _k, pts, _r in parts:
        P = np.asarray(pts, dtype=float)
        out.append(_unit(P[1] - P[0]))
    return out


def _bbox_span(shape: Any) -> tuple[float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return (xmax - xmin, ymax - ymin, zmax - zmin)


def _count_solids(shape: Any) -> int:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    n = 0
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        n += 1
        exp.Next()
    return n


def _fuse_ok(
    a: Any,
    b: Any,
    *,
    fuzzy_mm: float,
    label: str,
    mass_floor: float | None = None,
    min_dmass: float | None = None,
) -> Any:
    last: Exception | None = None
    ma = float(ocp_mass(a))
    mb = float(ocp_mass(b))
    # Heavy overlap (arms into a 3–5 mm hub) is expected; keep the larger body.
    soft_floor = max(ma, mb) * 0.92
    if mass_floor is not None:
        soft_floor = min(float(mass_floor), soft_floor)
    ladder = (
        ("off", float(fuzzy_mm)),
        ("off", max(float(fuzzy_mm), 0.08)),
        ("off", 0.15),
        ("off", 0.25),
        ("shift", 0.12),
    )
    for glue, fz in ladder:
        try:
            cand = ocp_fuse_pair(
                a,
                b,
                glue=glue,  # type: ignore[arg-type]
                fuzzy_mm=fz,
                label=label,
                simplify=False,
            )
            nsol = _count_solids(cand)
            if nsol > 1:
                cand = _remelt_to_one(
                    cand, fuzzy_mm=max(fz, 0.15), label=f"{label}-remelt"
                )
            if _count_solids(cand) != 1:
                raise RuntimeError(f"solids={_count_solids(cand)}")
            m = float(ocp_mass(cand))
            if m < soft_floor - 0.5:
                raise RuntimeError(f"mass collapse {m:.2f} < {soft_floor:.2f}")
            if min_dmass is not None and (m - ma) < float(min_dmass):
                raise RuntimeError(
                    f"tiny_dmass {m - ma:+.3f} < {float(min_dmass):.3f}"
                )
            return cand
        except Exception as exc:
            last = exc
            continue
    raise RuntimeError(f"{label}: fuse failed ({last})")


def _canal_solid(path_mm: list, radius_mm: float, *, tool: str) -> Any:
    """Build canal as continuous pipe or sphere beads along locus."""
    from src.export.exp_node_transition.bcc_explicit_cores import _ocp_sphere

    path = list(path_mm)
    if len(path) < 2:
        raise ValueError("canal path too short")
    if tool == "pipe":
        return ocp_pipe_along_points(tuple(path), float(radius_mm))
    # beads: every other sample to reduce BOP count
    pts = path[:: max(1, len(path) // 6)] or path
    if path[-1] not in pts:
        pts = list(pts) + [path[-1]]
    acc = None
    for i, p in enumerate(pts):
        sph = _ocp_sphere(p, float(radius_mm))
        if acc is None:
            acc = sph
        else:
            acc = ocp_fuse_pair(
                acc,
                sph,
                glue="off",
                fuzzy_mm=0.05,
                label=f"canal-bead-{i}",
                simplify=False,
            )
    assert acc is not None
    if _count_solids(acc) > 1:
        acc = _remelt_to_one(acc, fuzzy_mm=0.1, label="canal-beads-remelt")
    return acc


def _stub_fuse_order(parts: list[tuple[str, tuple, float]]) -> list[int]:
    """Same ±Z cluster first (pos then neg), azimuth order within cluster."""
    pos_i, neg_i = _cluster_indices(parts)
    samples = [_point_at_arc_s(p[1], 2.0) for p in parts]

    def az_sort(idxs: list[int]) -> list[int]:
        rows = [(float(np.arctan2(samples[i][1], samples[i][0])), i) for i in idxs]
        rows.sort()
        return [i for _, i in rows]

    return az_sort(pos_i) + az_sort(neg_i)


def plan_hub_acute_canals(
    parts: list[tuple[str, tuple, float]],
    params: HubFirstParams,
) -> list[dict[str, Any]]:
    """Acute strut–strut canals inside the hub radius (prefer same ±Z cluster)."""
    r = _strut_r(params)
    rf = float(params.r_blend_factor) * r
    pen = float(params.penetrate_factor) * r
    s_end = (
        float(params.canal_s_end_mm)
        if params.canal_s_end_mm is not None
        else 0.85 * float(params.s_hub_mm)
    )
    s_start = min(float(params.canal_s_start_mm), s_end - 0.2)
    s_vals = np.linspace(s_start, s_end, max(3, int(params.canal_s_samples)))
    tangents = _centre_tangents(parts)
    pos_i, neg_i = _cluster_indices(parts)
    samples = [_point_at_arc_s(p[1], 2.0) for p in parts]

    def az_sort(idxs: list[int]) -> list[int]:
        rows = [(float(np.arctan2(samples[i][1], samples[i][0])), i) for i in idxs]
        rows.sort()
        return [i for _, i in rows]

    cand: list[tuple[float, int, int, str]] = []
    if bool(params.adjacent_in_cluster):
        for _site, idxs in (("posZ", pos_i), ("negZ", neg_i)):
            ordered = az_sort(idxs)
            n = len(ordered)
            for k in range(n):
                i, j = ordered[k], ordered[(k + 1) % n]
                if i > j:
                    i, j = j, i
                ang = _angle_deg(tangents[i], tangents[j])
                if not (
                    float(params.pair_angle_min_deg)
                    < ang
                    < float(params.pair_angle_max_deg)
                ):
                    continue
                cand.append((ang, i, j, "same_cluster"))
    else:
        cluster_of = {i: "posZ" for i in pos_i}
        cluster_of.update({i: "negZ" for i in neg_i})
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                ang = _angle_deg(tangents[i], tangents[j])
                if not (
                    float(params.pair_angle_min_deg)
                    < ang
                    < float(params.pair_angle_max_deg)
                ):
                    continue
                same = cluster_of.get(i) == cluster_of.get(j)
                if bool(params.same_cluster_only) and not same:
                    continue
                site = "same_cluster" if same else "cross_cluster"
                cand.append((ang if same else ang + 200.0, i, j, site))
    cand.sort(key=lambda t: t[0])
    cand = cand[: max(1, int(params.max_pairs))] if cand else []

    specs: list[dict[str, Any]] = []
    for _rank, i, j, site in cand:
        ang = _angle_deg(tangents[i], tangents[j])
        path: list[tuple[float, float, float]] = []
        for s in s_vals:
            p0 = _point_at_arc_s(parts[i][1], float(s))
            p1 = _point_at_arc_s(parts[j][1], float(s))
            centers = _rolling_ball_centers_pair(
                p0, p1, strut_r=r, fillet_r=rf, penetrate=pen
            )
            if not centers:
                continue
            c = _pick_acute_wedge_center(centers, p0, p1)
            path.append((float(c[0]), float(c[1]), float(c[2])))
        cleaned = _clean_path(path, min_step=0.05)
        if len(cleaned) < 2:
            continue
        specs.append(
            {
                "pair": (int(i), int(j)),
                "angle_deg": float(ang),
                "site": site,
                "radius_mm": float(rf),
                "path_mm": cleaned,
                "n_pts": len(cleaned),
            }
        )
    if specs:
        return specs

    # Q≈1: same-cluster centre tangents are ~90°, acute crotch is Z-spine ↔ strut.
    from src.export.exp_node_transition.bcc_scheme_b_blend import (
        SchemeBParams,
        plan_scheme_b_canals,
    )

    sb = SchemeBParams(
        cell_size_mm=float(params.cell_size_mm),
        rod_d_mm=float(params.rod_d_mm),
        amplitude_mm=float(params.amplitude_mm),
        period_factor=float(params.period_factor),
        n_segments=int(params.n_segments),
        r_blend_factor=float(params.r_blend_factor),
        mode="spine_strut",
        s_start_mm=float(s_start),
        s_end_mm=float(s_end),
        s_samples=max(4, int(params.canal_s_samples)),
        penetrate_factor=float(params.penetrate_factor),
        both_armpits=False,
        fuse_fuzzy_mm=float(params.fuse_fuzzy_mm),
    )
    spine = plan_scheme_b_canals(parts, sb)
    out: list[dict[str, Any]] = []
    for sp in spine:
        out.append(
            {
                "pair": tuple(sp.get("pair") or (sp.get("strut"), sp.get("armpit_sign"))),
                "angle_deg": None,
                "site": "spine_strut",
                "radius_mm": float(sp["radius_mm"]),
                "path_mm": sp["path_mm"],
                "n_pts": int(sp["n_pts"]),
            }
        )
    print(
        f"  [hubFirst] adjacent canals empty; using {len(out)} spine_strut canals",
        flush=True,
    )
    return out


def _apply_canal_beads(
    acc: Any,
    sp: dict[str, Any],
    *,
    fuzzy_mm: float,
    min_dmass: float,
) -> tuple[Any, float]:
    """Fuse rolling-ball beads one-by-one (scheme-B style); skip empty hits."""
    from src.export.exp_node_transition.bcc_explicit_cores import _ocp_sphere

    path = list(sp["path_mm"])
    rf = float(sp["radius_mm"])
    pts = path[:: max(1, len(path) // 5)] or path
    if path and path[-1] not in pts:
        pts = list(pts) + [path[-1]]
    m0 = float(ocp_mass(acc))
    n_hit = 0
    for i, p in enumerate(pts):
        sph = _ocp_sphere(p, rf)
        try:
            trial = ocp_fuse_pair(
                acc,
                sph,
                glue="off",
                fuzzy_mm=float(fuzzy_mm),
                label=f"hubFirst-bead-{sp['pair'][0]}-{sp['pair'][1]}-{i}",
                simplify=False,
            )
            if _count_solids(trial) != 1:
                continue
            if float(ocp_mass(trial)) < float(ocp_mass(acc)) - 0.2:
                continue
            acc = trial
            n_hit += 1
        except Exception:
            continue
    d = float(ocp_mass(acc) - m0)
    if n_hit < 1 or d < float(min_dmass):
        raise RuntimeError(f"beads unused n_hit={n_hit} dmass={d:+.4f}")
    return acc, d


def build_smooth_hub_kernel(
    parts: list[tuple[str, tuple, float]],
    params: HubFirstParams,
) -> tuple[Any, dict[str, Any]]:
    """Sphere scaffold + acute canals (optional short stubs) → hub solid."""
    from src.export.exp_node_transition.bcc_explicit_cores import _ocp_sphere

    r = _strut_r(params)
    s_hub = float(params.s_hub_mm)
    fz = float(params.fuse_fuzzy_mm)
    box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
    stub_paths: list[dict[str, Any]] = []
    stub_mass = 0.0

    if float(params.seed_sphere_factor) <= 1e-9 and not bool(params.include_stubs):
        raise ValueError("hub kernel needs seed_sphere_factor>0 or include_stubs")

    acc: Any | None = None
    stub_mode = "sphere"
    if float(params.seed_sphere_factor) > 1e-9:
        acc = ocp_common(
            _ocp_sphere((0.0, 0.0, 0.0), float(params.seed_sphere_factor) * r),
            box,
        )
        print(
            f"  [hubFirst] seed sphere R={params.seed_sphere_factor * r:.3f} "
            f"mass={ocp_mass(acc):.2f} (connectivity only)",
            flush=True,
        )

    if bool(params.include_stubs):
        stubs: list[Any] = []
        for idx, (_k, pts, rr) in enumerate(parts):
            total = _path_arc_length(pts)
            s1 = min(s_hub, max(0.5, 0.35 * total))
            path = _slice_path_by_arc(pts, 0.0, s1)
            solid = ocp_common(ocp_pipe_along_points(path, float(rr)), box)
            m = float(ocp_mass(solid))
            if m <= 0.0:
                raise RuntimeError(f"hub stub {idx} empty")
            stubs.append(solid)
            stub_mass += m
            stub_paths.append(
                {"index": idx, "s_end_mm": s1, "n_pts": len(path), "mass_mm3": m}
            )
            print(
                f"  [hubFirst] stub {idx + 1}/8 s=0..{s1:.2f} mass={m:.2f}",
                flush=True,
            )
        order = _stub_fuse_order(parts)
        print(f"  [hubFirst] stub fuse order={order}", flush=True)
        try:
            if acc is None:
                acc = stubs[order[0]]
                rest = order[1:]
            else:
                rest = order
            for k, si in enumerate(rest, start=1):
                acc = _fuse_ok(
                    acc,
                    stubs[si],
                    fuzzy_mm=fz,
                    label=f"hubFirst-stub-{si + 1}",
                )
                print(
                    f"  [hubFirst] +stub {k}/{len(rest)} (idx={si}) "
                    f"merged={ocp_mass(acc):.2f}",
                    flush=True,
                )
            stub_mode = "stubs"
        except Exception as stub_exc:
            if acc is None:
                raise
            print(
                f"  [hubFirst] stub assemble failed ({stub_exc}); "
                f"keep sphere kernel + canals",
                flush=True,
            )
            stub_mode = "sphere_fallback"
            acc = ocp_common(
                _ocp_sphere((0.0, 0.0, 0.0), float(params.seed_sphere_factor) * r),
                box,
            )

    assert acc is not None
    mass_stubs = float(ocp_mass(acc))
    canals = plan_hub_acute_canals(parts, params)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if bool(params.canals_on_kernel) and canals:
        acc, applied, skipped = apply_planned_canals(acc, canals, params)

    acc = ocp_heal_fused_solid(acc)
    topo = ocp_shape_topology(acc, check_brep=True)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"hub kernel solids={topo.get('solids')}")
    report = {
        "s_hub_mm": s_hub,
        "stub_mode": stub_mode,
        "stub_paths": stub_paths,
        "stub_mass_mm3": stub_mass,
        "mass_after_stubs_mm3": mass_stubs,
        "mass_hub_mm3": float(ocp_mass(acc)),
        "n_canals_planned": len(canals),
        "n_canals_applied": len(applied),
        "n_canals_skipped": len(skipped),
        "canals_applied": applied,
        "canals_skipped": skipped,
        "topology": topo,
        "r_blend_mm": float(params.r_blend_factor) * r,
        "seed_sphere_r_mm": float(params.seed_sphere_factor) * r,
    }
    return acc, report


def build_outer_arms(
    parts: list[tuple[str, tuple, float]],
    params: HubFirstParams,
) -> list[tuple[int, Any, dict[str, Any]]]:
    """Equal-R pipe arms from (s_hub - overlap) to path end."""
    s_hub = float(params.s_hub_mm)
    overlap = float(params.arm_overlap_mm)
    box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
    arms: list[tuple[int, Any, dict[str, Any]]] = []
    for idx, (_k, pts, rr) in enumerate(parts):
        total = _path_arc_length(pts)
        s0 = max(0.15, s_hub - overlap)
        # Stay inside the L³ cube: centre→corner is (√3/2)*L ≈ 17.3 mm
        s1 = min(total, 0.5 * float(params.cell_size_mm) * 1.732 - 0.6)
        if s1 <= s0 + 0.3:
            raise RuntimeError(f"arm {idx}: path too short total={total:g}")
        path = _slice_path_by_arc(pts, s0, s1)
        solid = ocp_common(ocp_pipe_along_points(path, float(rr)), box)
        m = float(ocp_mass(solid))
        if m <= 0.0:
            raise RuntimeError(f"outer arm {idx} empty")
        meta = {
            "index": idx,
            "s0_mm": s0,
            "s1_mm": s1,
            "n_pts": len(path),
            "mass_mm3": m,
        }
        arms.append((idx, solid, meta))
        print(
            f"  [hubFirst] arm {idx + 1}/8 s={s0:.2f}..{s1:.2f} mass={m:.2f}",
            flush=True,
        )
    return arms


def apply_planned_canals(
    acc: Any,
    canals: list[dict[str, Any]],
    params: HubFirstParams,
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]]]:
    fz = float(params.fuse_fuzzy_mm)
    tool_pref = str(params.canal_tool or "auto").strip().lower()
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for sp in canals:
        pair = sp.get("pair")
        label = f"pair{pair}"
        tools = (
            ["pipe", "beads"]
            if tool_pref == "auto"
            else [tool_pref if tool_pref in ("pipe", "beads") else "beads"]
        )
        fused = False
        last_err: Exception | None = None
        for tool in tools:
            try:
                if tool == "beads":
                    trial, d = _apply_canal_beads(
                        acc,
                        sp,
                        fuzzy_mm=fz,
                        min_dmass=float(params.min_canal_dmass_mm3),
                    )
                else:
                    canal = _canal_solid(
                        sp["path_mm"], float(sp["radius_mm"]), tool="pipe"
                    )
                    trial = _fuse_ok(
                        acc,
                        canal,
                        fuzzy_mm=fz,
                        label=f"hubFirst-canal-{label}-pipe",
                    )
                    d = float(ocp_mass(trial) - ocp_mass(acc))
                    if d < float(params.min_canal_dmass_mm3):
                        raise RuntimeError(f"tiny_dmass {d:+.4f}")
                acc = trial
                applied.append(
                    {
                        "pair": sp.get("pair"),
                        "angle_deg": sp.get("angle_deg"),
                        "site": sp.get("site"),
                        "radius_mm": sp.get("radius_mm"),
                        "dmass_mm3": d,
                        "tool": tool,
                    }
                )
                ang = sp.get("angle_deg")
                ang_s = f"{ang:.1f}°" if ang is not None else "?"
                print(
                    f"  [hubFirst] +canal {label} θ={ang_s} "
                    f"site={sp.get('site')} tool={tool} d={d:+.3f}",
                    flush=True,
                )
                fused = True
                break
            except Exception as exc:
                last_err = exc
                continue
        if not fused:
            skipped.append(
                {
                    **{k: v for k, v in sp.items() if k != "path_mm"},
                    "reason": str(last_err)[:200] if last_err else "fail",
                }
            )
            print(f"  [hubFirst] skip canal {label}: {last_err}", flush=True)
    return acc, applied, skipped


def _extend_full_pipes(
    hub: Any,
    parts: list[tuple[str, tuple, float]],
    params: HubFirstParams,
) -> tuple[Any, list[dict[str, Any]]]:
    """Fuse eight full L³ pipes onto an existing hub (hub-fuse loop)."""
    box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
    acc = hub
    rows: list[dict[str, Any]] = []
    print("  [hubFirst] extend: full pipes onto hub", flush=True)
    for idx, (_k, pts, rr) in enumerate(parts):
        solid = ocp_common(ocp_pipe_along_points(pts, float(rr)), box)
        m = float(ocp_mass(solid))
        if m <= 0.0:
            raise RuntimeError(f"full pipe {idx + 1} empty")
        m_prev = float(ocp_mass(acc))
        last: Exception | None = None
        merged = None
        for fz in (max(0.05, float(params.fuse_fuzzy_mm)), 0.08, 0.12):
            try:
                cand = ocp_fuse_pair(
                    acc,
                    solid,
                    glue="off",
                    fuzzy_mm=fz,
                    label=f"hubFirst-fullpipe-{idx + 1}",
                    simplify=False,
                )
                if _count_solids(cand) != 1:
                    raise RuntimeError(f"solids={_count_solids(cand)}")
                mm = float(ocp_mass(cand))
                if mm < m_prev + 0.65 * m:
                    raise RuntimeError(
                        f"mass increment {mm - m_prev:.2f} < 0.65*pipe {0.65 * m:.2f}"
                    )
                merged = cand
                break
            except Exception as exc:
                last = exc
                continue
        if merged is None:
            raise RuntimeError(f"full pipe {idx + 1} fuse failed ({last})")
        acc = merged
        row = {
            "index": idx,
            "s0_mm": 0.0,
            "s1_mm": _path_arc_length(pts),
            "mass_mm3": m,
            "ok": True,
            "merged_mass_mm3": float(ocp_mass(acc)),
            "mode": "full_pipe",
        }
        rows.append(row)
        print(
            f"  [hubFirst] +pipe {idx + 1}/8 pipe={m:.2f} merged={row['merged_mass_mm3']:.2f}",
            flush=True,
        )
    return acc, rows


def fuse_hub_then_extend(
    params: HubFirstParams | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Build smooth hub kernel first, then grow the L³ cell onto it."""
    params = params or HubFirstParams()
    fp = ExpFilletParams(
        cell_size_mm=float(params.cell_size_mm),
        rod_d_mm=float(params.rod_d_mm),
        amplitude_mm=float(params.amplitude_mm),
        period_factor=float(params.period_factor),
        n_segments=int(params.n_segments),
        fuse_fuzzy_mm=float(params.fuse_fuzzy_mm),
    )
    parts = load_fillet_pipe_parts(fp)
    print(
        f"\n=== hub-first extend Q={params.period_factor:g} "
        f"s_hub={params.s_hub_mm:g} Rf/R={params.r_blend_factor:g} "
        f"Rhub={params.seed_sphere_factor * _strut_r(params):.2f} ===",
        flush=True,
    )
    hub, hub_rep = build_smooth_hub_kernel(parts, params)
    acc = hub
    arm_rows: list[dict[str, Any]] = []
    extend_mode = "outer_arms"
    fz = float(params.fuse_fuzzy_mm)

    try:
        if bool(params.extend_full_pipes):
            acc, arm_rows = _extend_full_pipes(hub, parts, params)
            extend_mode = "full_pipes"
        else:
            arms = build_outer_arms(parts, params)
            for idx, solid, meta in arms:
                m_arm = float(meta["mass_mm3"])
                acc = _fuse_ok(
                    acc,
                    solid,
                    fuzzy_mm=fz,
                    label=f"hubFirst-arm-{idx + 1}",
                    min_dmass=max(0.5, 0.12 * m_arm),
                )
                row = {**meta, "ok": True, "merged_mass_mm3": float(ocp_mass(acc))}
                arm_rows.append(row)
                print(
                    f"  [hubFirst] +arm {idx + 1}/8 merged={row['merged_mass_mm3']:.2f}",
                    flush=True,
                )
    except Exception as arm_exc:
        print(
            f"  [hubFirst] arm/pipe grow failed ({arm_exc}); "
            f"fallback: octant-fuse cell then union/canals",
            flush=True,
        )
        pipes, pmass, tag, _attempts = fuse_pipes_unitcell_bare_ladder(fp)
        print(f"  [hubFirst] bare cell mass={pmass:.2f} via {tag}", flush=True)
        try:
            acc = _fuse_ok(
                hub,
                pipes,
                fuzzy_mm=max(0.05, fz),
                label="hubFirst-kernel-into-cell",
            )
            extend_mode = f"kernel_union_bare_cell:{tag}"
        except Exception as union_exc:
            print(
                f"  [hubFirst] kernel∪cell failed ({union_exc}); "
                f"use bare cell + canals (still hard STEP)",
                flush=True,
            )
            acc = pipes
            extend_mode = f"bare_cell_then_canals:{tag}"
            hub_rep["fallback_union_error"] = str(union_exc)[:240]
            deferred = plan_hub_acute_canals(parts, params)
            if deferred:
                print(
                    f"  [hubFirst] canals on bare cell n={len(deferred)}",
                    flush=True,
                )
                acc, applied, skipped = apply_planned_canals(acc, deferred, params)
                hub_rep["n_canals_planned"] = len(deferred)
                hub_rep["n_canals_applied"] = len(applied)
                hub_rep["n_canals_skipped"] = len(skipped)
                hub_rep["canals_applied"] = applied
                hub_rep["canals_skipped"] = skipped
                hub_rep["canals_stage"] = "bare_cell_fallback"
        arm_rows = [
            {
                "ok": True,
                "mode": extend_mode,
                "cell_mass_mm3": pmass,
                "arm_error": str(arm_exc)[:240],
            }
        ]
    if bool(params.canals_after_extend) and hub_rep.get("canals_stage") != "bare_cell_fallback":
        deferred = plan_hub_acute_canals(parts, params)
        if deferred:
            print(f"  [hubFirst] canals after extend n={len(deferred)}", flush=True)
            acc, applied, skipped = apply_planned_canals(acc, deferred, params)
            hub_rep["n_canals_applied"] = int(hub_rep.get("n_canals_applied") or 0) + len(
                applied
            )
            hub_rep["n_canals_skipped"] = int(hub_rep.get("n_canals_skipped") or 0) + len(
                skipped
            )
            hub_rep["canals_applied"] = list(hub_rep.get("canals_applied") or []) + applied
            hub_rep["canals_skipped"] = list(hub_rep.get("canals_skipped") or []) + skipped
            hub_rep["canals_stage"] = "kernel+after_extend"

    box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
    acc = ocp_common(acc, box)
    acc = ocp_heal_fused_solid(acc)
    mass = float(ocp_mass(acc))
    topo = ocp_shape_topology(acc, check_brep=True)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"final solids={topo.get('solids')}")
    span = _bbox_span(acc)
    if any(span[k] > float(params.max_span_mm) for k in range(3)):
        raise RuntimeError(f"bbox explode {span}")

    report: dict[str, Any] = {
        "experiment": "hub_first_extend",
        "params": asdict(params),
        "hub": hub_rep,
        "arms": arm_rows,
        "merged_mass_mm3": mass,
        "topology": topo,
        "bbox_span_mm": span,
        "n_arms_ok": sum(1 for r in arm_rows if r.get("ok")),
        "extend_mode": extend_mode,
    }
    return acc, report


def export_hub_first_extend(
    params: HubFirstParams | None = None,
    *,
    out_dir: str | None = None,
    write_step: bool = True,
) -> dict[str, Any]:
    """Build + optional hard STEP under experiment out dir."""
    params = params or HubFirstParams()
    out_dir = out_dir or os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_hub_first_extend"
    )
    os.makedirs(out_dir, exist_ok=True)
    q = float(params.period_factor)
    qslug = f"{q:.1f}".replace(".", "p")
    slug = (
        f"exp_hubFirst_af{int(round(params.amplitude_mm))}q{qslug}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_shub{str(params.s_hub_mm).replace('.', 'p')}"
        f"_rf{str(params.r_blend_factor).replace('.', 'p')}_1x1"
    )
    shape, report = fuse_hub_then_extend(params)
    report["slug"] = slug
    report["out_dir"] = os.path.abspath(out_dir)
    if write_step:
        step_path = os.path.join(out_dir, f"{slug}.step")
        # Prefer direct OCP write; fall back to gmsh heal if needed
        try:
            from src.export.exp_node_transition.acute_slot_fillet import (
                _write_step_hard_solid,
            )

            _write_step_hard_solid(
                shape,
                step_path,
                mass_ref=float(report["merged_mass_mm3"]),
                max_drift=2.5,
                max_span_mm=float(params.max_span_mm) + 1.0,
            )
            report["step_path"] = os.path.abspath(step_path)
            report["step_solid_ok"] = True
            report["step_route"] = "hard_solid_gate"
        except Exception as exc:
            print(f"  [hubFirst] hard STEP gate failed ({exc}); try gmsh heal...", flush=True)
            from src.export.ocp_unitcell_fuse import ocp_write_step_via_gmsh_brep_heal

            rb = ocp_write_step_via_gmsh_brep_heal(shape, step_path)
            report["step_path"] = os.path.abspath(step_path)
            report["step_readback"] = rb
            report["step_solid_ok"] = bool(rb.get("brep_valid")) and int(
                rb.get("solids") or 0
            ) == 1
            report["step_route"] = "gmsh_brep_heal"
            report["step_gate_error"] = str(exc)[:300]
        try:
            from src.export.sw_parasolid import recenter_step_bbox_to_origin

            report["bbox_recenter"] = recenter_step_bbox_to_origin(step_path)
        except Exception as exc:
            report["bbox_recenter"] = {"shifted": False, "error": str(exc)}

    man_path = os.path.join(out_dir, f"{slug}_manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    report["manifest_path"] = os.path.abspath(man_path)
    print(
        f"  [hubFirst] OK mass={report['merged_mass_mm3']:.2f} "
        f"canals={report['hub']['n_canals_applied']}/"
        f"{report['hub']['n_canals_planned']} "
        f"→ {report.get('step_path') or man_path}",
        flush=True,
    )
    return report
