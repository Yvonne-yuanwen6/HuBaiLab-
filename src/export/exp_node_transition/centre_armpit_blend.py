"""
Centre-junction armpit blend (experiment).

Equal-diameter struts (no centre taper). At fuse time, add rolling-ball
*canals* only in pairwise acute crotches near the cell centre.

Pipeline:
  1. Bare equal-R pipe fuse
  2. Pairwise centre angles → per-pair adaptive Rf (same formula for all Q)
  3. Plan rolling-ball canal paths in the acute wedge of each pair
  4. Fuse canals; hard STEP (1 solid, mass preserve) — no STL, no bare fake-success

Does not touch batch / paper_box defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from src.export.exp_node_transition.adaptive_fillet import (
    AdaptiveFilletConfig,
    AdaptiveNodeSpec,
    NodeClass,
    adaptive_r_blend_mm,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.bcc_scheme_b_blend import (
    _clean_path,
    _point_at_arc_s,
    _rolling_ball_centers_pair,
)
from src.export.ocp_unitcell_fuse import (
    ocp_fuse_pair,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_shape_topology,
    ocp_write_step,
)


@dataclass
class CentreArmpitParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.5
    n_segments: int = 32
    # Sample along struts near cell centre (mm from centre)
    s_start_mm: float = 1.20
    s_end_mm: float = 3.20
    s_samples: int = 6
    # Keep pairs whose mutual angle is in (min, max) deg
    pair_angle_min_deg: float = 5.0
    pair_angle_max_deg: float = 95.0
    # Sharpest crotches first; cap BOP count
    max_pairs: int = 8
    penetrate_factor: float = 0.12
    # Adaptive Rf knobs — same law for every Q / every pair
    k_blend: float = 0.45
    k_blend_acute: float = 0.30
    acute_theta_deg: float = 25.0
    k_angle: float = 0.30
    k_clear: float = 0.45
    # Optional global override; None → per-pair adaptive
    r_blend_mm: float | None = None
    fuse_fuzzy_mm: float = 0.03
    min_dmass_mm3: float = 0.03
    max_span_grow_mm: float = 2.0
    max_step_mass_drift_mm3: float = 1.20
    min_applied: int = 1
    # Continuous canal only (no sphere beads, no strut taper)
    tool: str = "canal"


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("zero vector")
    return v / n


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    c = float(np.clip(np.dot(_unit(a), _unit(b)), -1.0, 1.0))
    return float(np.degrees(np.arccos(c)))


def _centre_tangents(
    parts: list[tuple[str, tuple, float]],
) -> list[np.ndarray]:
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


def _adaptive_cfg(params: CentreArmpitParams) -> AdaptiveFilletConfig:
    return AdaptiveFilletConfig(
        k_blend=float(params.k_blend),
        k_blend_acute=float(params.k_blend_acute),
        acute_theta_deg=float(params.acute_theta_deg),
        k_angle=float(params.k_angle),
        k_clear=float(params.k_clear),
    )


def pair_rf_mm(theta_deg: float, params: CentreArmpitParams) -> float:
    """Same adaptive law for every pair / every Q (optional global override)."""
    if params.r_blend_mm is not None:
        return float(params.r_blend_mm)
    r = 0.5 * float(params.rod_d_mm)
    # Local clearance proxy: chord opening at typical sample mid-s
    clear = max(0.25 * float(params.rod_d_mm), 0.5 * r)
    spec = AdaptiveNodeSpec(
        node_id="pair",
        xyz_mm=(0.0, 0.0, 0.0),
        node_class=NodeClass.INTERIOR_CELL,
        valence=2,
        r_min_strut_mm=r,
        clear_mm=clear,
        theta_min_deg=float(theta_deg),
        skip_fillet=False,
    )
    return float(adaptive_r_blend_mm(spec, _adaptive_cfg(params)))


def suggest_centre_rf_mm(
    parts: list[tuple[str, tuple, float]],
    params: CentreArmpitParams,
) -> tuple[float, float, list[dict[str, Any]]]:
    """
    Summary Rf from the sharpest acute pair (for logs / filename).

    Returns (rf_mm, theta_min_deg, pair_rows).
    """
    tangents = _centre_tangents(parts)
    rows: list[dict[str, Any]] = []
    acute: list[float] = []
    for i in range(len(tangents)):
        for j in range(i + 1, len(tangents)):
            ang = _angle_deg(tangents[i], tangents[j])
            rows.append({"i": i, "j": j, "angle_deg": ang})
            if (
                float(params.pair_angle_min_deg)
                < ang
                < float(params.pair_angle_max_deg)
            ):
                acute.append(ang)
    if not rows:
        raise RuntimeError("no strut pairs")
    theta_min = float(min(acute)) if acute else float(min(r["angle_deg"] for r in rows))
    rf = pair_rf_mm(theta_min, params)
    return float(rf), float(theta_min), rows


def _pick_acute_wedge_center(
    centers: list[np.ndarray],
    p0: np.ndarray,
    p1: np.ndarray,
) -> np.ndarray:
    """
    Among the two exterior rolling-ball centres, keep the one in the acute
    wedge of the two strut sample points (bisector from origin through mid).
    """
    bis = _unit(_unit(np.asarray(p0, dtype=float)) + _unit(np.asarray(p1, dtype=float)))
    return max(centers, key=lambda c: float(np.dot(_unit(np.asarray(c)), bis)))


def plan_centre_armpits(
    parts: list[tuple[str, tuple, float]],
    params: CentreArmpitParams,
    *,
    rf_mm: float | None = None,
) -> list[dict[str, Any]]:
    """
    Acute strut pairs near the cell centre → rolling-ball canal paths.

    ``rf_mm`` if set forces one radius; else each pair uses ``pair_rf_mm(θ)``.
    Strut mid-span diameter is unchanged (equal-R bare pipes).
    """
    r = 0.5 * float(params.rod_d_mm)
    pen = float(params.penetrate_factor) * r
    tangents = _centre_tangents(parts)

    cand: list[tuple[float, int, int]] = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            ang = _angle_deg(tangents[i], tangents[j])
            if (
                float(params.pair_angle_min_deg)
                < ang
                < float(params.pair_angle_max_deg)
            ):
                cand.append((ang, i, j))
    cand.sort(key=lambda t: t[0])
    cand = cand[: max(1, int(params.max_pairs))]

    s_vals = np.linspace(
        float(params.s_start_mm),
        float(params.s_end_mm),
        int(params.s_samples),
    )
    specs: list[dict[str, Any]] = []
    for ang, i, j in cand:
        rf = float(rf_mm) if rf_mm is not None else pair_rf_mm(ang, params)
        if rf <= 1e-6:
            continue
        path: list[tuple[float, float, float]] = []
        for s in s_vals:
            p0 = _point_at_arc_s(parts[i][1], float(s))
            p1 = _point_at_arc_s(parts[j][1], float(s))
            centers = _rolling_ball_centers_pair(
                p0, p1, strut_r=r, fillet_r=float(rf), penetrate=pen
            )
            if not centers:
                continue
            c = _pick_acute_wedge_center(centers, p0, p1)
            path.append((float(c[0]), float(c[1]), float(c[2])))
        path = _clean_path(path, min_step=0.05)
        if len(path) < 2:
            continue
        specs.append(
            {
                "pair": (i, j),
                "angle_deg": float(ang),
                "radius_mm": float(rf),
                "path_mm": path,
                "n_pts": len(path),
                "site": "centre_armpit_acute",
            }
        )
    return specs


def apply_centre_armpit_canals(
    seed: Any,
    specs: list[dict[str, Any]],
    params: CentreArmpitParams,
) -> tuple[Any, dict[str, Any]]:
    """
    Continuous rolling-ball *canal* (pipe along locus) — not sphere beads.

    One fuse attempt per canal (small fuzzy); skip on failure; keep single solid.
    """
    cur = seed
    m0 = float(ocp_mass(cur))
    span0 = _bbox_span(cur)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    fz = float(params.fuse_fuzzy_mm)

    # Alternate pairs to reduce BOP clustering in one hemisphere
    ordered = sorted(
        specs,
        key=lambda sp: (int(sp["pair"][0]) % 2, int(sp["pair"][0]), int(sp["pair"][1])),
    )

    for sp in ordered:
        label = f"pair{sp['pair']}"
        path = tuple(sp["path_mm"])
        if len(path) < 2:
            skipped.append(
                {**{k: v for k, v in sp.items() if k != "path_mm"}, "reason": "short_path"}
            )
            continue
        try:
            canal = ocp_pipe_along_points(path, float(sp["radius_mm"]))
        except Exception as exc:
            skipped.append(
                {**{k: v for k, v in sp.items() if k != "path_mm"}, "reason": f"pipe:{exc}"}
            )
            print(f"  [pairCanal] skip {label} pipe: {exc}", flush=True)
            continue

        cand = None
        last_err: Exception | None = None
        # Tight ladder only — avoid long hangs / mass collapse
        for glue, fzz in (("off", fz), ("off", 0.05)):
            try:
                trial = ocp_fuse_pair(
                    cur,
                    canal,
                    glue=glue,  # type: ignore[arg-type]
                    fuzzy_mm=fzz,
                    label=f"centreArmpit-canal-{label}",
                    simplify=False,
                )
                nsol = _count_solids(trial)
                if nsol > 1:
                    # Quick remelt once; else reject
                    from src.export.exp_node_transition.bcc_scheme_b_blend import (
                        _remelt_to_one,
                    )

                    try:
                        trial = _remelt_to_one(
                            trial, fuzzy_mm=0.03, label=f"canal-remelt-{label}"
                        )
                    except Exception as exc:
                        last_err = RuntimeError(f"solids={nsol} remelt:{exc}")
                        continue
                    if _count_solids(trial) != 1:
                        last_err = RuntimeError(f"solids={_count_solids(trial)}")
                        continue
                elif nsol != 1:
                    last_err = RuntimeError(f"solids={nsol}")
                    continue
                m_trial = float(ocp_mass(trial))
                m_cur = float(ocp_mass(cur))
                if m_trial < m_cur - 0.15:
                    last_err = RuntimeError(f"collapse {m_trial:.3f}<{m_cur:.3f}")
                    continue
                d = m_trial - m_cur
                if d < float(params.min_dmass_mm3):
                    last_err = RuntimeError(f"tiny_dmass {d:+.4f}")
                    continue
                span = _bbox_span(trial)
                if any(span[k] - span0[k] > params.max_span_grow_mm for k in range(3)):
                    last_err = RuntimeError("bbox_explode")
                    continue
                cand = trial
                break
            except Exception as exc:
                last_err = exc
                continue

        if cand is None:
            skipped.append(
                {
                    **{k: v for k, v in sp.items() if k != "path_mm"},
                    "reason": str(last_err) if last_err else "fuse_fail",
                }
            )
            print(f"  [pairCanal] skip {label} ({last_err})", flush=True)
            continue

        dmass = float(ocp_mass(cand) - ocp_mass(cur))
        cur = cand
        applied.append(
            {
                "pair": sp["pair"],
                "angle_deg": sp["angle_deg"],
                "radius_mm": sp["radius_mm"],
                "n_pts": sp["n_pts"],
                "tool": "canal",
                "dmass_step": dmass,
            }
        )
        print(
            f"  [pairCanal] +canal {label} θ={sp['angle_deg']:.1f}° "
            f"Rf={sp['radius_mm']:.3f} d={dmass:+.3f}",
            flush=True,
        )

    return cur, {
        "n_planned": len(specs),
        "n_applied": len(applied),
        "n_skipped": len(skipped),
        "applied": applied,
        "skipped": skipped,
        "tool": "canal",
        "mass_pre_mm3": m0,
        "mass_after_mm3": float(ocp_mass(cur)),
        "topology": ocp_shape_topology(cur),
    }


def _hard_step_readback(
    shape: Any,
    path: str,
    *,
    mass_ref: float,
    max_drift: float,
    max_span_mm: float,
) -> tuple[Any, dict[str, Any]]:
    """Write STEP; require 1 solid + mass/span gate on readback."""
    from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

    ocp_write_step(shape, path)
    rb = ocp_read_step_shape(path)
    topo = ocp_shape_topology(rb, check_brep=True)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"STEP rb solids={topo.get('solids')}")
    span = _bbox_span(rb)
    if any(float(span[k]) > float(max_span_mm) for k in range(3)):
        raise RuntimeError(f"STEP rb bbox {span}")
    rb_mass = float(ocp_mass(rb))
    if abs(rb_mass - float(mass_ref)) > float(max_drift):
        raise RuntimeError(f"STEP rb mass drift mem={mass_ref:.3f} rb={rb_mass:.3f}")
    return rb, {
        "mass_mm3": rb_mass,
        "span": list(span),
        "topology": topo,
        "brep_valid": bool(topo.get("brep_valid")),
    }


def export_centre_armpit_unitcell(
    params: CentreArmpitParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
    write_stl: bool = False,
) -> dict[str, Any]:
    params = params or CentreArmpitParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = f"{q:.1f}".replace(".", "p")

    fp = ExpFilletParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=params.period_factor,
        n_segments=params.n_segments,
    )
    parts = load_fillet_pipe_parts(fp)
    rf_summary, theta_min, pair_rows = suggest_centre_rf_mm(parts, params)
    specs = plan_centre_armpits(parts, params, rf_mm=params.r_blend_mm)

    rf_tag = str(round(float(rf_summary), 2)).replace(".", "p")
    slug = (
        f"exp_pairCanal_af{int(round(params.amplitude_mm))}q{q_tag}"
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

    print("  [pairCanal] bare equal-R fuse ...", flush=True)
    bare, mass_bare, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    if _count_solids(bare) != 1:
        raise RuntimeError("bare not single solid")
    ocp_write_step(bare, bare_path)

    if not specs:
        raise RuntimeError(
            f"no acute pair canals planned (θ window "
            f"{params.pair_angle_min_deg}–{params.pair_angle_max_deg}°)"
        )

    print(
        f"  [pairCanal] θ_min={theta_min:.1f}° Rf_summary={rf_summary:.3f} mm "
        f"planned_pairs={len(specs)} (equal-R struts + crotch canals)",
        flush=True,
    )
    for sp in specs:
        print(
            f"    pair={sp['pair']} θ={sp['angle_deg']:.1f}° Rf={sp['radius_mm']:.3f} "
            f"n={sp['n_pts']}",
            flush=True,
        )

    blended, blend_info = apply_centre_armpit_canals(bare, specs, params)
    n_app = int(blend_info["n_applied"])
    if n_app < int(params.min_applied):
        raise RuntimeError(
            f"too few canals applied: {n_app}/{len(specs)} "
            f"(min_applied={params.min_applied})"
        )
    if _count_solids(blended) != 1:
        raise RuntimeError(f"blend not single solid: {ocp_shape_topology(blended)}")

    mem_mass = float(ocp_mass(blended))
    max_span = float(params.cell_size_mm) * 1.35
    rb, rb_info = _hard_step_readback(
        blended,
        step_path,
        mass_ref=mem_mass,
        max_drift=float(params.max_step_mass_drift_mm3),
        max_span_mm=max_span,
    )

    man = {
        "experiment": "pair_canal_equal_r",
        "note": (
            "Equal-diameter struts; adaptive rolling-ball canals only in "
            "pairwise acute centre crotches. Hard STEP gate. No centre taper."
        ),
        "params": asdict(params),
        "theta_min_deg": theta_min,
        "r_blend_summary_mm": rf_summary,
        "pair_angles": pair_rows,
        "planned": [
            {
                "pair": list(sp["pair"]),
                "angle_deg": sp["angle_deg"],
                "radius_mm": sp["radius_mm"],
                "n_pts": sp["n_pts"],
            }
            for sp in specs
        ],
        "n_planned_armpits": len(specs),
        "step_path": os.path.abspath(step_path),
        "bare_step_path": os.path.abspath(bare_path),
        "stl_path": None,
        "used_bare_fallback": False,
        "fuse": {
            "method": fuse_tag,
            "mass_bare_mm3": float(mass_bare),
            "attempts": fuse_attempts,
        },
        "blend": blend_info,
        "mass_mm3": float(rb_info["mass_mm3"]),
        "mass_delta_vs_bare_mm3": float(rb_info["mass_mm3"]) - float(mass_bare),
        "step_readback": rb_info,
        "topology": rb_info["topology"],
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(f"\n=== PAIR CANAL (equal-R) Q={q:g} ===", flush=True)
    print(
        f"  STEP: {step_path}  mass={rb_info['mass_mm3']:.3f}  "
        f"dmass_vs_bare={man['mass_delta_vs_bare_mm3']:+.3f}  "
        f"applied={n_app}/{len(specs)}  brep_valid={rb_info['brep_valid']}",
        flush=True,
    )
    print(f"  bare: {bare_path}", flush=True)
    print(f"  manifest: {man_path}", flush=True)
    return man
