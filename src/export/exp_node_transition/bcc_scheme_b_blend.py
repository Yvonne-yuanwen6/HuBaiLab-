"""
Scheme B canal (experiment): rolling-ball crotch blends for Q>0 — no MakeFillet.

Default ``mode=spine_strut``: canals sit in the Z-spine ↔ departing-strut
*armpits* (the concave crotches highlighted in SW), not between adjacent
ring struts and not as a convex hub fill.

Does not touch batch / paper_box defaults.
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
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import (
    ocp_fuse_pair,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_shape_topology,
    ocp_write_step,
)


@dataclass
class SchemeBParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.5
    n_segments: int = 32
    # Fillet / rolling-ball radius as fraction of strut R
    r_blend_factor: float = 0.35
    # spine_strut = Z-spine ↔ each departing strut armpit (correct for Q>0)
    # adjacent = between neighbouring struts in the ±Z ring (legacy, wrong site)
    mode: str = "spine_strut"
    # For legacy adjacent mode only
    side: str = "outer"
    s_start_mm: float = 3.20
    s_end_mm: float = 4.80
    s_samples: int = 5
    # Pull canal centre into solids (×R) for robust Boolean
    penetrate_factor: float = 0.10
    # Place both ±tangential armpits per strut (spine_strut); False = + only
    both_armpits: bool = False
    fuse_fuzzy_mm: float = 0.03
    min_dmass_mm3: float = 0.03
    max_span_grow_mm: float = 2.5
    fuse_passes: int = 2


def _strut_r(p: SchemeBParams) -> float:
    return 0.5 * float(p.rod_d_mm)


def _point_at_arc_s(path_pts: tuple, s_mm: float) -> np.ndarray:
    P = np.asarray(path_pts, dtype=float)
    if len(P) < 2:
        raise ValueError("path too short")
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    s = min(max(float(s_mm), 0.0), total)
    i = int(np.searchsorted(cum, s, side="right") - 1)
    i = max(0, min(i, len(P) - 2))
    t0, t1 = float(cum[i]), float(cum[i + 1])
    if t1 <= t0 + 1e-12:
        return P[i].copy()
    a = (s - t0) / (t1 - t0)
    return (1.0 - a) * P[i] + a * P[i + 1]


def _cluster_indices(parts: list[tuple[str, tuple, float]]) -> tuple[list[int], list[int]]:
    pos: list[int] = []
    neg: list[int] = []
    for i, (_k, pts, _r) in enumerate(parts):
        P = np.asarray(pts, dtype=float)
        v = P[1] - P[0]
        v = v / (np.linalg.norm(v) + 1e-12)
        if float(v[2]) >= 0.0:
            pos.append(i)
        else:
            neg.append(i)
    if len(pos) != 4 or len(neg) != 4:
        raise RuntimeError(f"expected 4+4 clusters, got {len(pos)}+{len(neg)}")
    return pos, neg


def _azimuth_sort(idxs: list[int], pts: list[np.ndarray]) -> list[int]:
    angs = [(float(np.arctan2(pts[i][1], pts[i][0])), i) for i in idxs]
    angs.sort()
    return [i for _, i in angs]


def _rolling_ball_centers_pair(
    p0: np.ndarray,
    p1: np.ndarray,
    *,
    strut_r: float,
    fillet_r: float,
    penetrate: float,
) -> list[np.ndarray]:
    """
    Classic external rolling-ball centres for two circular sections:
    mid ± h * n_perp, ||c - p0|| = ||c - p1|| = R + Rf - penetrate.
    These sit in the left/right concave exterior crotches (armpits).
    """
    d_vec = p1 - p0
    D = float(np.linalg.norm(d_vec))
    if D < 1e-9:
        return []
    mid = 0.5 * (p0 + p1)
    u = d_vec / D
    # Perp in the plane of u and Z (fallback if u ‖ Z)
    n = np.cross(u, np.array([0.0, 0.0, 1.0], dtype=float))
    pn = float(np.linalg.norm(n))
    if pn < 1e-9:
        n = np.cross(u, np.array([1.0, 0.0, 0.0], dtype=float))
        pn = float(np.linalg.norm(n))
        if pn < 1e-9:
            return []
    n = n / pn
    half = 0.5 * D
    target = float(strut_r) + float(fillet_r) - float(penetrate)
    if target <= half + 1e-6:
        return []
    h = float(np.sqrt(target * target - half * half))
    return [mid + h * n, mid - h * n]


def _clean_path(
    path: list[tuple[float, float, float]], *, min_step: float = 0.08
) -> list[tuple[float, float, float]]:
    if not path:
        return []
    cleaned: list[tuple[float, float, float]] = [path[0]]
    for pt in path[1:]:
        if float(np.linalg.norm(np.asarray(pt) - np.asarray(cleaned[-1]))) > min_step:
            cleaned.append(pt)
    return cleaned


def plan_scheme_b_canals(
    parts: list[tuple[str, tuple, float]],
    params: SchemeBParams,
) -> list[dict[str, Any]]:
    """
    Default ``spine_strut``: canal along Z-spine ↔ each departing strut armpit
    (matches the concave crotch the user highlighted).

    Legacy ``adjacent``: between neighbouring struts in the ±Z ring.
    """
    mode = str(params.mode or "spine_strut").strip().lower()
    if mode == "adjacent":
        return _plan_adjacent_canals(parts, params)
    return _plan_spine_strut_canals(parts, params)


def _plan_spine_strut_canals(
    parts: list[tuple[str, tuple, float]],
    params: SchemeBParams,
) -> list[dict[str, Any]]:
    r = _strut_r(params)
    rf = float(params.r_blend_factor) * r
    pen = float(params.penetrate_factor) * r
    s_vals = np.linspace(
        float(params.s_start_mm),
        float(params.s_end_mm),
        int(params.s_samples),
    )
    pos_i, neg_i = _cluster_indices(parts)
    both = bool(params.both_armpits)

    specs: list[dict[str, Any]] = []
    for label, idxs in (("posZ", pos_i), ("negZ", neg_i)):
        # one path per (strut, armpit_sign)
        signs = (+1, -1) if both else (+1,)
        for i_strut in idxs:
            for sign in signs:
                path: list[tuple[float, float, float]] = []
                for s in s_vals:
                    p = _point_at_arc_s(parts[i_strut][1], float(s))
                    # Idealised Z-spine axis at this height
                    spine = np.array([0.0, 0.0, float(p[2])], dtype=float)
                    centers = _rolling_ball_centers_pair(
                        spine,
                        p,
                        strut_r=r,
                        fillet_r=rf,
                        penetrate=pen,
                    )
                    if not centers:
                        continue
                    # Deterministic pick: + = first, - = second
                    c = centers[0] if sign > 0 else centers[1]
                    path.append((float(c[0]), float(c[1]), float(c[2])))
                cleaned = _clean_path(path)
                if len(cleaned) < 4:
                    continue
                specs.append(
                    {
                        "cluster": label,
                        "strut": int(i_strut),
                        "armpit_sign": int(sign),
                        "mode": "spine_strut",
                        "path_mm": cleaned,
                        "radius_mm": float(rf),
                        "n_pts": len(cleaned),
                        "pair": (int(i_strut), int(sign)),  # for logs / ordering
                    }
                )
    return specs


def _plan_adjacent_canals(
    parts: list[tuple[str, tuple, float]],
    params: SchemeBParams,
) -> list[dict[str, Any]]:
    """Legacy: adjacent struts in ±Z ring (kept for comparison only)."""
    r = _strut_r(params)
    rf = float(params.r_blend_factor) * r
    pen = float(params.penetrate_factor) * r
    s_vals = np.linspace(
        float(params.s_start_mm),
        float(params.s_end_mm),
        int(params.s_samples),
    )
    s_ref = 0.5 * (float(params.s_start_mm) + float(params.s_end_mm))
    samples_ref = [_point_at_arc_s(part[1], s_ref) for part in parts]
    pos_i, neg_i = _cluster_indices(parts)
    side = str(params.side or "outer").strip().lower()

    specs: list[dict[str, Any]] = []
    for label, idxs in (("posZ", pos_i), ("negZ", neg_i)):
        ordered = _azimuth_sort(idxs, samples_ref)
        n = len(ordered)
        for k in range(n):
            i0 = ordered[k]
            i1 = ordered[(k + 1) % n]
            path: list[tuple[float, float, float]] = []
            for s in s_vals:
                samples = [_point_at_arc_s(part[1], float(s)) for part in parts]
                axis = np.mean([samples[i] for i in ordered], axis=0)
                centers = _rolling_ball_centers_pair(
                    samples[i0],
                    samples[i1],
                    strut_r=r,
                    fillet_r=rf,
                    penetrate=pen,
                )
                if not centers:
                    continue
                # Pick the centre further from / closer to axis
                def rho(c: np.ndarray) -> float:
                    return float(np.linalg.norm(c[:2] - axis[:2]))

                c = max(centers, key=rho) if side == "outer" else min(centers, key=rho)
                path.append((float(c[0]), float(c[1]), float(c[2])))
            cleaned = _clean_path(path)
            if len(cleaned) < 4:
                continue
            specs.append(
                {
                    "cluster": label,
                    "pair": (int(i0), int(i1)),
                    "mode": "adjacent",
                    "side": side,
                    "path_mm": cleaned,
                    "radius_mm": float(rf),
                    "n_pts": len(cleaned),
                }
            )
    return specs


def _bbox_span(shape: Any) -> tuple[float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b, True)
    x = b.Get()
    return (float(x[3] - x[0]), float(x[4] - x[1]), float(x[5] - x[2]))


def _count_solids(shape: Any) -> int:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    n = 0
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        n += 1
        exp.Next()
    return n


def _remelt_to_one(shape: Any, *, fuzzy_mm: float, label: str) -> Any:
    n = _count_solids(shape)
    if n <= 1:
        return shape
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    solids: list[Any] = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    print(f"  [schemeB] remelt {n} solids → 1 ({label})...", flush=True)
    acc = solids[0]
    m0 = float(ocp_mass(acc))
    for j, sh in enumerate(solids[1:], start=2):
        merged = None
        for fz in (float(fuzzy_mm), 0.15, 0.25, 0.4):
            try:
                cand = ocp_fuse_pair(
                    acc, sh, glue="off", fuzzy_mm=fz, label=f"{label}-{j}"
                )
                if float(ocp_mass(cand)) < m0 - 0.5:
                    continue
                merged = cand
                break
            except Exception:
                continue
        if merged is None:
            raise RuntimeError(f"{label}: could not remelt solid {j}/{n}")
        acc = merged
        m0 = float(ocp_mass(acc))
    if _count_solids(acc) != 1:
        raise RuntimeError(f"{label}: still {_count_solids(acc)} solids after remelt")
    return acc


def apply_scheme_b_canals(
    seed: Any,
    canal_specs: list[dict[str, Any]],
    params: SchemeBParams,
) -> tuple[Any, dict[str, Any]]:
    """
    Fuse rolling-ball blends into the seed.

    For ``spine_strut`` use sphere beads along the armpit locus (pipe canals
    frequently hang / collapse OCC BOP on this Q=1.5 seed).
    """
    from src.export.exp_node_transition.bcc_explicit_cores import _ocp_sphere

    cur = seed
    mass0 = float(ocp_mass(cur))
    span0 = _bbox_span(cur)
    applied: list[dict[str, Any]] = []
    skipped_final: list[dict[str, Any]] = []

    # Opposite struts first within each cluster
    def _order_key(sp: dict[str, Any]) -> tuple:
        cluster = str(sp.get("cluster") or "")
        strut = sp.get("strut")
        if strut is None:
            pair = sp.get("pair")
            strut = pair[0] if isinstance(pair, (tuple, list)) and pair else 0
        return (
            0 if cluster == "posZ" else 1,
            int(strut) % 2,
            int(strut),
            int(sp.get("armpit_sign") or 1),
        )

    ordered = sorted(canal_specs, key=_order_key)

    mode = str(params.mode or "spine_strut").strip().lower()
    use_spheres = mode == "spine_strut"
    fz = float(params.fuse_fuzzy_mm)
    n_pass = max(1, int(params.fuse_passes))
    pending = list(ordered)

    for pass_id in range(1, n_pass + 1):
        if not pending:
            break
        print(
            f"  [schemeB] fuse pass {pass_id}/{n_pass} pending={len(pending)} "
            f"tool={'spheres' if use_spheres else 'pipe'}",
            flush=True,
        )
        still: list[dict[str, Any]] = []
        for sp in pending:
            label = (
                f"{sp.get('cluster')} strut={sp.get('strut', sp.get('pair'))} "
                f"sign={sp.get('armpit_sign', '')}"
            )
            dmass_total = 0.0
            n_ok = 0
            try:
                if use_spheres:
                    for j, pt in enumerate(sp["path_mm"]):
                        sph = _ocp_sphere(tuple(pt), float(sp["radius_mm"]))
                        cand = ocp_fuse_pair(
                            cur,
                            sph,
                            glue="off",
                            fuzzy_mm=fz,
                            label=f"schemeB-sph-{pass_id}-{n_ok}",
                            simplify=False,
                        )
                        d = float(ocp_mass(cand) - ocp_mass(cur))
                        if d < float(params.min_dmass_mm3):
                            continue
                        if _count_solids(cand) != 1:
                            continue
                        span = _bbox_span(cand)
                        if any(
                            span[k] - span0[k] > params.max_span_grow_mm
                            for k in range(3)
                        ):
                            continue
                        cur = cand
                        dmass_total += d
                        n_ok += 1
                    if n_ok == 0:
                        raise RuntimeError("no sphere gained mass")
                else:
                    canal = ocp_pipe_along_points(
                        tuple(sp["path_mm"]), float(sp["radius_mm"])
                    )
                    cand = ocp_fuse_pair(
                        cur,
                        canal,
                        glue="off",
                        fuzzy_mm=fz,
                        label=f"schemeB-pipe-{pass_id}",
                        simplify=False,
                    )
                    d = float(ocp_mass(cand) - ocp_mass(cur))
                    if d < float(params.min_dmass_mm3):
                        raise RuntimeError(f"tiny_dmass {d:+.4f}")
                    if _count_solids(cand) != 1:
                        raise RuntimeError(f"solids={_count_solids(cand)}")
                    span = _bbox_span(cand)
                    if any(
                        span[k] - span0[k] > params.max_span_grow_mm
                        for k in range(3)
                    ):
                        raise RuntimeError("bbox_explode")
                    cur = cand
                    dmass_total = d
                    n_ok = 1
            except Exception as exc:
                still.append(sp)
                print(f"  [schemeB] defer {label} ({exc})", flush=True)
                continue

            applied.append(
                {
                    "cluster": sp.get("cluster"),
                    "strut": sp.get("strut"),
                    "armpit_sign": sp.get("armpit_sign"),
                    "pair": sp.get("pair"),
                    "mode": sp.get("mode"),
                    "radius_mm": sp["radius_mm"],
                    "n_pts": sp["n_pts"],
                    "n_tools": n_ok,
                    "dmass_step": dmass_total,
                    "pass": pass_id,
                    "tool": "spheres" if use_spheres else "pipe",
                }
            )
            print(
                f"  [schemeB] +blend {label} Rf={sp['radius_mm']:.3f} "
                f"tools={n_ok} mass={float(ocp_mass(cur)):.3f} "
                f"d={dmass_total:+.3f} pass={pass_id}",
                flush=True,
            )
        pending = still

    for sp in pending:
        skipped_final.append({**sp, "reason": "fuse_exhausted"})
        print(
            f"  [schemeB] skip {sp.get('cluster')} "
            f"strut={sp.get('strut', sp.get('pair'))} (exhausted)",
            flush=True,
        )

    return cur, {
        "n_planned": len(canal_specs),
        "n_applied": len(applied),
        "n_skipped": len(skipped_final),
        "applied": applied,
        "skipped": [
            {k: v for k, v in s.items() if k != "path_mm"} for s in skipped_final
        ],
        "mass_pre_mm3": mass0,
        "mass_after_mm3": float(ocp_mass(cur)),
        "span0": span0,
        "span_final": _bbox_span(cur),
        "topology": ocp_shape_topology(cur),
    }



def export_scheme_b_unitcell(
    params: SchemeBParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
    seed_step: str | None = None,
) -> dict[str, Any]:
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer

    params = params or SchemeBParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = str(q).replace(".", "p")
    mode_tag = str(params.mode or "spine_strut").strip().lower().replace("_", "")
    slug = (
        f"exp_schemeB_canal_{mode_tag}"
        f"_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_rf{str(params.r_blend_factor).replace('.', 'p')}"
    )
    out_step = os.path.join(out_dir, f"{slug}_1x1.step")
    out_stl = out_step.replace(".step", ".stl")
    man_path = out_step.replace(".step", "_manifest.json")

    if (not force) and os.path.isfile(out_step):
        print(f"  [skip] exists: {out_step}", flush=True)
        return {"step_path": out_step, "skipped": True}

    print(f"\n=== SCHEME-B canal 1x1 Q={q:g} → {out_step} ===", flush=True)

    if seed_step and os.path.isfile(seed_step):
        seed = ocp_read_step_shape(seed_step)
        seed_meta = {"seed_step": seed_step, "seed_method": "load_step"}
        print(f"  seed STEP: {seed_step}", flush=True)
    else:
        fp = ExpFilletParams(
            cell_size_mm=params.cell_size_mm,
            rod_d_mm=params.rod_d_mm,
            amplitude_mm=params.amplitude_mm,
            period_factor=params.period_factor,
            n_segments=params.n_segments,
        )
        seed, mass, method, attempts = fuse_pipes_unitcell_bare_ladder(fp)
        seed_meta = {
            "seed_method": method,
            "mass_mm3": mass,
            "bare_attempts": attempts,
        }
        print(f"  bare seed OK method={method} mass={mass:.3f}", flush=True)

    parts = load_fillet_pipe_parts(
        ExpFilletParams(
            cell_size_mm=params.cell_size_mm,
            rod_d_mm=params.rod_d_mm,
            amplitude_mm=params.amplitude_mm,
            period_factor=params.period_factor,
            n_segments=params.n_segments,
        )
    )
    canal_specs = plan_scheme_b_canals(parts, params)
    print(f"  planned canals: {len(canal_specs)} mode={params.mode}", flush=True)
    for sp in canal_specs:
        print(
            f"    {sp['cluster']} strut={sp.get('strut', sp.get('pair'))} "
            f"sign={sp.get('armpit_sign', sp.get('side',''))} "
            f"pts={sp['n_pts']} Rf={sp['radius_mm']:.3f}",
            flush=True,
        )

    solid, blend_rep = apply_scheme_b_canals(seed, canal_specs, params)

    if _count_solids(solid) != 1:
        solid = _remelt_to_one(
            solid, fuzzy_mm=float(params.fuse_fuzzy_mm), label="schemeB-export"
        )
    ocp_write_step(solid, out_step)

    final = ocp_read_step_shape(out_step)
    topo = ocp_shape_topology(final)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"schemeB final STEP solids={topo.get('solids')}")

    try:
        BRepMesh_IncrementalMesh(final, 0.25)
        StlAPI_Writer().Write(final, out_stl)
    except Exception as exc:
        print(f"  STL warn: {exc}", flush=True)
        out_stl = None

    report = {
        "experiment": "scheme_b_rolling_ball_canal_spine_strut",
        "slug": slug,
        "main_path_untouched": True,
        "params": asdict(params),
        "seed_meta": seed_meta,
        "blend": blend_rep,
        "step_path": out_step,
        "stl_path": out_stl,
        "topology": topo,
        "mass_mm3": float(ocp_mass(final)),
        "note": (
            "Rolling-ball canals in Z-spine ↔ strut armpits (concave crotches); "
            "not adjacent-ring valleys / hub fill. No OCC MakeFillet."
        ),
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    report["manifest_path"] = man_path
    print(
        f"  done mass={report['mass_mm3']:.3f} "
        f"applied={blend_rep['n_applied']}/{blend_rep['n_planned']}",
        flush=True,
    )
    return report
