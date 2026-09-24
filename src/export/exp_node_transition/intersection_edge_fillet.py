"""
Intersection-edge fillet (experiment): smooth strut–strut meeting curves.

Idea (user): where two rod surfaces meet after fuse, the BRep stores an
intersection *edge* (face–face curve). Apply OCC MakeFillet on those edges
to round the concave crotch — true BRep fillet surface, not taper / canal / mesh.

Pipeline:
  1) Bare pipe fuse (stable 1-solid seed)
  2) Classify 2-face concave junction edges near cell centre
  3) Sequential gated MakeFillet (bbox / mass / timeout / STEP readback)

Isolation: scripts/exp_intersection_fillet_*.py only; no batch defaults.
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
    _edge_midpoint_mm,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.exp_node_transition.centre_edge_fillet import (
    _bbox_span,
    _edge_faces,
    _edge_length_mm,
    _face_normal_at_edge_mid,
    _try_fillet_timeout,
    _unit,
)
from src.export.ocp_unitcell_fuse import (
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)


@dataclass
class IntersectionFilletParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.5
    n_segments: int = 32
    # Search ball around cell centre for junction intersection edges
    select_radius_mm: float = 5.0
    # Skip tiny fragments / long outer generators
    min_edge_len_mm: float = 0.40
    max_edge_len_mm: float = 8.0
    # Dihedral: n0·n1 in [dot_min, dot_max] → acute-to-moderate crotch
    normal_dot_min: float = -0.95
    normal_dot_max: float = 0.85
    # Fillet radius as fraction of strut R
    r_blend_factor: float = 0.20
    radius_scales: tuple[float, ...] = (1.0, 0.75, 0.55)
    max_dmass_step_mm3: float = 0.80
    max_edges_apply: int = 8
    max_candidates_per_pass: int = 10
    fillet_timeout_s: float = 20.0
    # Reject STEP that loses most of the in-memory fillet mass gain
    max_step_mass_drift_mm3: float = 0.50


def _dihedral_normals(
    shape: Any, edge: Any
) -> tuple[np.ndarray, np.ndarray, float] | None:
    faces = _edge_faces(shape, edge)
    if len(faces) != 2:
        return None
    n0 = _face_normal_at_edge_mid(faces[0], edge)
    n1 = _face_normal_at_edge_mid(faces[1], edge)
    if n0 is None or n1 is None:
        return None
    return n0, n1, float(np.dot(n0, n1))


def _is_concave_junction(
    shape: Any,
    edge: Any,
    *,
    center: np.ndarray,
    params: IntersectionFilletParams,
) -> bool:
    """
    Concave strut–strut crotch: two faces, outward normals diverge somewhat,
    and the edge mid sits outside the material relative to the cell centre
    (armpit facing outward from origin).
    """
    dih = _dihedral_normals(shape, edge)
    if dih is None:
        return False
    n0, n1, ndot = dih
    if ndot < float(params.normal_dot_min) or ndot > float(params.normal_dot_max):
        return False
    mid = _edge_midpoint_mm(edge)
    if mid is None:
        return False
    radial = mid - center
    rn = float(np.linalg.norm(radial))
    if rn < 1e-9:
        # At exact origin: allow if normals are not nearly parallel
        return ndot < 0.5
    radial = radial / rn
    n_avg = _unit(n0 + n1)
    # Valley armpit: average outward normal points away from centre
    return float(np.dot(n_avg, radial)) > 0.02


def _edge_is_nearly_straight(edge: Any, *, tol_mm: float = 0.08) -> bool:
    """Reject long straight cylinder generators (not true intersection loops)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    try:
        ad = BRepAdaptor_Curve(edge)
        u0 = float(ad.FirstParameter())
        u1 = float(ad.LastParameter())
        p0 = ad.Value(u0)
        p1 = ad.Value(u1)
        pm = ad.Value(0.5 * (u0 + u1))
        a = np.array([p0.X(), p0.Y(), p0.Z()], dtype=float)
        b = np.array([p1.X(), p1.Y(), p1.Z()], dtype=float)
        m = np.array([pm.X(), pm.Y(), pm.Z()], dtype=float)
        ab = b - a
        lab = float(np.linalg.norm(ab))
        if lab < 1e-9:
            return True
        t = float(np.dot(m - a, ab) / (lab * lab))
        proj = a + t * ab
        return float(np.linalg.norm(m - proj)) < tol_mm
    except Exception:
        return False


def collect_intersection_edges(
    shape: Any,
    params: IntersectionFilletParams,
) -> list[dict[str, Any]]:
    """
    Rank candidate face–face intersection edges at the cell-centre junction.
    Returns list of {edge, mid, length, r, ndot}.
    """
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    center = np.zeros(3, dtype=float)
    scored: list[tuple[float, dict[str, Any]]] = []
    seen: set[tuple[float, float, float]] = set()
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        exp.Next()
        mid = _edge_midpoint_mm(edge)
        if mid is None:
            continue
        key = (round(float(mid[0]), 4), round(float(mid[1]), 4), round(float(mid[2]), 4))
        if key in seen:
            continue
        rr = float(np.linalg.norm(mid - center))
        if rr > float(params.select_radius_mm):
            continue
        elen = _edge_length_mm(edge)
        if elen < float(params.min_edge_len_mm) or elen > float(params.max_edge_len_mm):
            continue
        if not _is_concave_junction(shape, edge, center=center, params=params):
            continue
        # Prefer curved intersection loops over straight generators
        straight = _edge_is_nearly_straight(edge)
        dih = _dihedral_normals(shape, edge)
        ndot = float(dih[2]) if dih else 1.0
        # Score: longer curved edges closer to a mid-radius armpit band
        band = abs(rr - 2.5)
        score = elen - 0.15 * band - (1.5 if straight else 0.0)
        seen.add(key)
        scored.append(
            (
                score,
                {
                    "edge": edge,
                    "mid": mid,
                    "length_mm": elen,
                    "r_mm": rr,
                    "ndot": ndot,
                    "straight": straight,
                },
            )
        )
    scored.sort(key=lambda t: -t[0])
    out = [d for _, d in scored]
    print(
        f"  [ixFillet] intersection candidates={len(out)} "
        f"(select_r={params.select_radius_mm:g})",
        flush=True,
    )
    for i, d in enumerate(out[:8]):
        print(
            f"    cand#{i} L={d['length_mm']:.2f} r={d['r_mm']:.2f} "
            f"ndot={d['ndot']:.2f} straight={d['straight']}",
            flush=True,
        )
    return out


def apply_intersection_fillet(
    shape: Any,
    params: IntersectionFilletParams,
) -> tuple[Any, dict[str, Any]]:
    """Sequential single-edge MakeFillet with integrity gates."""
    r_strut = 0.5 * float(params.rod_d_mm)
    r0 = float(params.r_blend_factor) * r_strut
    m0 = float(ocp_mass(shape))
    span0 = _bbox_span(shape)
    max_span = float(params.cell_size_mm) * 1.35
    max_dmass = float(params.max_dmass_step_mm3)
    max_apply = max(1, int(params.max_edges_apply))
    max_cand = max(1, int(params.max_candidates_per_pass))
    timeout_s = float(params.fillet_timeout_s)

    cur = shape
    applied: list[dict[str, Any]] = []
    errors: list[str] = []
    rejected = 0
    timed_out = 0

    for s in params.radius_scales:
        if len(applied) >= max_apply:
            break
        rad = float(s) * r0
        if rad < 1e-4:
            continue
        for pass_i in range(6):
            if len(applied) >= max_apply:
                break
            cands = collect_intersection_edges(cur, params)[:max_cand]
            if pass_i == 0:
                print(
                    f"  [ixFillet] pass r={rad:.3f} n_cand={len(cands)} "
                    f"span0={tuple(round(x, 2) for x in span0)}",
                    flush=True,
                )
            if not cands:
                break
            got = False
            for ei, info in enumerate(cands):
                edge = info["edge"]
                try:
                    trial = _try_fillet_timeout(
                        cur, edge, rad, timeout_s=timeout_s
                    )
                    # Prefer real solid (extract if compound)
                    from OCP.TopAbs import TopAbs_SOLID
                    from OCP.TopExp import TopExp_Explorer
                    from OCP.TopoDS import TopoDS

                    exp = TopExp_Explorer(trial, TopAbs_SOLID)
                    solids = []
                    while exp.More():
                        solids.append(TopoDS.Solid_s(exp.Current()))
                        exp.Next()
                    if len(solids) != 1:
                        raise RuntimeError(f"solids={len(solids)}")
                    trial = solids[0]
                    topo = ocp_shape_topology(trial, check_brep=True)
                    m1 = float(ocp_mass(trial))
                    if m1 < 0.95 * m0:
                        raise RuntimeError(f"mass collapse {m1:.2f}")
                    d = m1 - float(ocp_mass(cur))
                    if d < -0.05:
                        rejected += 1
                        raise RuntimeError(f"dmass_negative {d:+.3f}")
                    if d > max_dmass:
                        rejected += 1
                        raise RuntimeError(f"dmass_explode {d:+.3f}")
                    span = _bbox_span(trial)
                    if any(span[k] > max_span for k in range(3)):
                        rejected += 1
                        raise RuntimeError(f"bbox_explode {span}")
                    if any(span[k] > span0[k] + 2.0 for k in range(3)):
                        rejected += 1
                        raise RuntimeError(f"bbox_grow {span}")
                    # Do NOT ShapeFix — historically inflates invalid fillets
                    cur = trial
                    applied.append(
                        {
                            "r_mm": rad,
                            "edge_index": ei,
                            "pass": pass_i,
                            "dmass_step": d,
                            "mass_mm3": m1,
                            "span": span,
                            "mid": [float(x) for x in info["mid"]],
                            "edge_len_mm": info["length_mm"],
                            "brep_valid": topo.get("brep_valid"),
                        }
                    )
                    print(
                        f"  [ixFillet] +edge#{ei} r={rad:.3f} d={d:+.3f} "
                        f"mass={m1:.3f} valid={topo.get('brep_valid')} "
                        f"(n_ok={len(applied)})",
                        flush=True,
                    )
                    got = True
                    break
                except TimeoutError as exc:
                    timed_out += 1
                    errors.append(f"r={rad:g} e={ei}: {exc}")
                    print(
                        f"  [ixFillet] timeout edge#{ei} r={rad:.3f}",
                        flush=True,
                    )
                except Exception as exc:
                    errors.append(f"r={rad:g} e={ei}: {exc}")
            if not got:
                break

    if not applied:
        raise RuntimeError(
            "no safe intersection fillet "
            f"(rejected={rejected}, timed_out={timed_out}, "
            f"last={errors[-4:] if errors else []})"
        )

    span_f = _bbox_span(cur)
    topo = ocp_shape_topology(cur, check_brep=True)
    m1 = float(ocp_mass(cur))
    return cur, {
        "mode": "intersection_edge_sequential_gated",
        "r0_mm": r0,
        "n_applied": len(applied),
        "applied": applied,
        "mass_pre_mm3": m0,
        "mass_mm3": m1,
        "mass_delta_mm3": m1 - m0,
        "span0": span0,
        "span_final": span_f,
        "topology": topo,
        "rejected": rejected,
        "timed_out": timed_out,
        "n_errors_logged": len(errors),
    }


def _default_rf_for_q(q: float) -> float:
    """Q=0 star tolerates larger fillet; acute Q>0 needs small R."""
    if abs(q) < 1e-12:
        return 0.35
    if abs(q - 0.5) < 1e-9:
        return 0.25
    if abs(q - 1.0) < 1e-9:
        return 0.18
    return 0.12


def export_intersection_fillet_unitcell(
    params: IntersectionFilletParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    params = params or IntersectionFilletParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = str(q).replace(".", "p")
    rf_tag = str(params.r_blend_factor).replace(".", "p")
    slug = (
        f"exp_ixFillet_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_rf{rf_tag}"
        f"_1x1"
    )
    step_path = os.path.join(out_dir, f"{slug}.step")
    bare_path = os.path.join(out_dir, f"{slug}_bare.step")
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
        period_factor=params.period_factor,
        n_segments=params.n_segments,
    )
    print("  [ixFillet] bare fuse ...", flush=True)
    bare, mass_bare, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    if int(ocp_shape_topology(bare).get("solids") or 0) != 1:
        raise RuntimeError("bare not single solid")
    ocp_write_step(bare, bare_path)

    used_bare = False
    try:
        final, fillet_info = apply_intersection_fillet(bare, params)
    except Exception as exc:
        print(f"  [ixFillet] fillet failed → bare ({exc})", flush=True)
        final = bare
        fillet_info = {"error": str(exc), "applied": False}
        used_bare = True

    write_note = "ocp_direct"
    from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

    try:
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS

        exp = TopExp_Explorer(final, TopAbs_SOLID)
        if exp.More():
            final = TopoDS.Solid_s(exp.Current())
        mem_mass = float(ocp_mass(final))
        ocp_write_step(final, step_path)
        rb = ocp_read_step_shape(step_path)
        rb_topo = ocp_shape_topology(rb, check_brep=True)
        rb_span = _bbox_span(rb)
        rb_mass = float(ocp_mass(rb))
        if int(rb_topo.get("solids") or 0) != 1:
            raise RuntimeError(f"readback solids={rb_topo.get('solids')}")
        if any(rb_span[k] > float(params.cell_size_mm) * 1.35 for k in range(3)):
            raise RuntimeError(f"readback bbox explode {rb_span}")
        if abs(rb_mass - mem_mass) > float(params.max_step_mass_drift_mm3):
            raise RuntimeError(
                f"STEP mass drift mem={mem_mass:.3f} rb={rb_mass:.3f}"
            )
        write_note = "ocp_direct_readback_ok"
        final = rb
    except Exception as exc:
        print(f"  [ixFillet] STEP fail → bare ({exc})", flush=True)
        final = bare
        used_bare = True
        fillet_info = {
            **(fillet_info if isinstance(fillet_info, dict) else {}),
            "step_error": str(exc),
            "reverted_to_bare": True,
        }
        ocp_write_step(final, step_path)
        write_note = "bare_after_bad_step"

    topo = ocp_shape_topology(final, check_brep=True)
    mass = float(ocp_mass(final))
    man = {
        "experiment": "intersection_edge_fillet",
        "note": (
            "MakeFillet on strut–strut face intersection edges at cell centre "
            "(true BRep round). Not centre-taper, not canal, not mesh."
        ),
        "params": asdict(params),
        "step_path": os.path.abspath(step_path),
        "bare_step_path": os.path.abspath(bare_path),
        "used_bare_fallback": used_bare,
        "fuse": {
            "method": fuse_tag,
            "mass_bare_mm3": float(mass_bare),
            "attempts": fuse_attempts,
        },
        "fillet": fillet_info,
        "mass_mm3": mass,
        "topology": topo,
        "span": _bbox_span(final),
        "step_write": write_note,
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(f"\n=== INTERSECTION FILLET Q={q:g} ===", flush=True)
    print(
        f"  STEP: {step_path}  mass={mass:.3f}  fallback_bare={used_bare}  "
        f"solids={topo.get('solids')} valid={topo.get('brep_valid')}",
        flush=True,
    )
    print(f"  manifest: {man_path}", flush=True)
    return man
