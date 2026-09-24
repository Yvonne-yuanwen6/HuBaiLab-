"""
Two-strut G1 intersection fillet (no canal, no hub sphere).

Fuse two equal-R rods, then OCC MakeFillet on the pipe–pipe intersection
edge(s). The fillet face is tangent to both circular rod surfaces — it
replaces the sharp valley, it does not glue a third solid into the gap.

Default geometry is analytic cylinders along the pair's centre start-dirs
(the local node of Q=1.5 is an ~11° pair). Curved SFBL stubs are optional
and historically only accept a tiny radius.

  py -3 scripts/exp_two_strut_concave_blend.py
  py -3 scripts/exp_two_strut_concave_blend.py --q 0 --rf 0.30
  py -3 scripts/exp_two_strut_concave_blend.py --mode sfbl --rf 0.08
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.analytic_ix_fillet import (
    apply_tangent_intersection_fillet,
    count_solids as _count_solids,
    cylinder_along as _cylinder_along,
)
from src.export.exp_node_transition.bcc_scheme_b_blend import _point_at_arc_s
from src.export.exp_node_transition.centre_armpit_blend import _angle_deg, _unit
from src.export.ocp_unitcell_fuse import (
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_shape_topology,
    ocp_write_step,
)


def _pick_pair(
    parts: list[tuple[str, tuple, float]],
    *,
    want: str,
) -> tuple[int, int, float]:
    tangents = []
    for _k, pts, _r in parts:
        P = np.asarray(pts, dtype=float)
        tangents.append(_unit(P[1] - P[0]))
    scored: list[tuple[float, int, int]] = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            ang = _angle_deg(tangents[i], tangents[j])
            scored.append((ang, i, j))
    if want == "acute":
        cand = [t for t in scored if 5.0 < t[0] < 90.0]
        if not cand:
            raise RuntimeError("no acute pair")
        best = min(cand, key=lambda t: t[0])
    elif want == "obtuse":
        cand = [t for t in scored if 95.0 < t[0] < 130.0]
        if not cand:
            raise RuntimeError("no obtuse pair")
        best = min(cand, key=lambda t: abs(t[0] - 109.5))
    else:
        raise ValueError(want)
    return best[1], best[2], best[0]


def _slice_near_centre(
    path_pts: tuple,
    s_end_mm: float,
) -> tuple[tuple[float, float, float], ...]:
    P = np.asarray(path_pts, dtype=float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    s1 = min(float(s_end_mm), total)
    pts = [_point_at_arc_s(path_pts, 0.0)]
    for i in range(1, len(P) - 1):
        if 0.0 < float(cum[i]) < s1:
            pts.append(P[i].copy())
    pts.append(_point_at_arc_s(path_pts, s1))
    out: list[tuple[float, float, float]] = []
    for p in pts:
        t = (float(p[0]), float(p[1]), float(p[2]))
        if not out or float(np.linalg.norm(np.asarray(t) - np.asarray(out[-1]))) > 0.05:
            out.append(t)
    if len(out) < 2:
        raise RuntimeError("stub path too short")
    return tuple(out)


def _try_sw_fillet(bare_step: str, out_step: str, radius_mm: float) -> dict[str, Any]:
    import importlib.util

    from src.export.sw_parasolid import _connect_solidworks

    probe_path = os.path.join(_ROOT, "scripts", "exp_sw_fillet_probe.py")
    spec = importlib.util.spec_from_file_location("exp_sw_fillet_probe", probe_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exp_sw_fillet_probe")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    _collect_hub_edges = probe._collect_hub_edges
    _insert_fillet = probe._insert_fillet
    _open_step = probe._open_step
    _save_as = probe._save_as
    _select_edges = probe._select_edges

    sw = _connect_solidworks()
    model = _open_step(sw, bare_step)
    hub = _collect_hub_edges(model, hub_r_mm=6.5, max_len_mm=12.0)
    if not hub:
        raise RuntimeError("SW: no hub edges")
    nsel = _select_edges(model, hub[:4])
    if nsel < 1:
        raise RuntimeError("SW: select failed")
    if not _insert_fillet(model, radius_mm):
        raise RuntimeError("SW: FeatureFillet3 failed")
    _save_as(model, out_step)
    return {"n_selected": nsel, "n_hub": len(hub), "r_mm": radius_mm, "step": out_step}


def main() -> int:
    p = argparse.ArgumentParser(description="Two-strut G1 intersection fillet")
    p.add_argument("--q", type=float, default=1.5)
    p.add_argument(
        "--rf",
        type=float,
        default=0.30,
        help="fillet radius in mm (absolute, not ×R)",
    )
    p.add_argument("--s-end", type=float, default=8.0)
    p.add_argument("--pair", choices=("acute", "obtuse"), default="acute")
    p.add_argument(
        "--mode",
        choices=("analytic", "sfbl"),
        default="analytic",
        help="analytic cylinders along start-dirs, or curved SFBL stubs",
    )
    p.add_argument("--sw-fallback", action="store_true")
    args = p.parse_args()

    out_dir = os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_two_strut_tangent"
    )
    os.makedirs(out_dir, exist_ok=True)

    fp = ExpFilletParams(
        period_factor=float(args.q),
        n_segments=32,
        amplitude_mm=2.0,
        rod_d_mm=2.0,
        cell_size_mm=20.0,
    )
    parts = load_fillet_pipe_parts(fp)
    i, j, theta = _pick_pair(parts, want=str(args.pair))
    r = 0.5 * float(fp.rod_d_mm)
    rf = float(args.rf)
    print(
        f"Q={args.q:g} pair ({i},{j}) θ={theta:.1f}°  R={r:g}  "
        f"fillet r={rf:.3f} mm  mode={args.mode}",
        flush=True,
    )
    print("  G1 MakeFillet on pipe–pipe intersection — no canal, no sphere", flush=True)

    if args.mode == "analytic":
        Pa = np.asarray(parts[i][1], dtype=float)
        Pb = np.asarray(parts[j][1], dtype=float)
        pipe_a = _cylinder_along(Pa[1] - Pa[0], radius=r, length=float(args.s_end))
        pipe_b = _cylinder_along(Pb[1] - Pb[0], radius=r, length=float(args.s_end))
        fuzzy = 0.0
    else:
        path_a = _slice_near_centre(parts[i][1], float(args.s_end))
        path_b = _slice_near_centre(parts[j][1], float(args.s_end))
        pipe_a = ocp_pipe_along_points(path_a, r)
        pipe_b = ocp_pipe_along_points(path_b, r)
        fuzzy = 0.05

    fused = ocp_fuse_pair(
        pipe_a, pipe_b, glue="off", fuzzy_mm=fuzzy, label="twoStrut-fuse", simplify=False
    )
    if _count_solids(fused) != 1:
        raise RuntimeError(f"fuse solids={_count_solids(fused)}")
    fused = ocp_heal_fused_solid(fused)
    mass0 = float(ocp_mass(fused))
    print(f"  fused mass={mass0:.3f}", flush=True)

    qtag = str(args.q).replace(".", "p")
    rtag = str(args.rf).replace(".", "p")
    slug = f"twoStrut_q{qtag}_pair{i}_{j}_{args.mode}_{args.pair}"
    bare_path = os.path.join(out_dir, f"{slug}_bare.step")
    ocp_write_step(fused, bare_path)

    method = None
    result = None
    fil_info: dict[str, Any] = {}
    try:
        result, fil_info = apply_tangent_intersection_fillet(
            fused, radius_mm=rf, mass0=mass0
        )
        method = "occ_makefillet_rational"
        print(
            f"  OCC fillet OK dmass={fil_info['dmass_mm3']:+.4f} "
            f"faces={fil_info['topology'].get('faces')}",
            flush=True,
        )
    except Exception as exc:
        fil_info = {"error": str(exc)}
        print(f"  OCC fillet failed: {exc}", flush=True)
        if args.sw_fallback:
            sw_path = os.path.join(out_dir, f"{slug}_r{rtag}_swFillet.step")
            try:
                sw_info = _try_sw_fillet(bare_path, sw_path, rf)
                fil_info["sw"] = sw_info
                from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

                result = ocp_read_step_shape(sw_path)
                method = "sw_featurefillet3"
                print(f"  SW fillet OK → {sw_path}", flush=True)
            except Exception as sw_exc:
                fil_info["sw_error"] = str(sw_exc)
                print(f"  SW fillet failed: {sw_exc}", flush=True)

    if result is None:
        raise RuntimeError("no tangent fillet produced")

    blend_path = os.path.join(out_dir, f"{slug}_r{rtag}_ixFillet.step")
    ocp_write_step(result, blend_path)
    topo = ocp_shape_topology(result, check_brep=True)
    mass1 = float(ocp_mass(result))

    report = {
        "experiment": "two_strut_tangent_intersection_fillet",
        "note": (
            "Replace the pipe–pipe intersection edge with a Rational MakeFillet "
            "face G1-tangent to both circular rod surfaces. No canal, no sphere."
        ),
        "Q": float(args.q),
        "pair": [i, j],
        "theta_deg": float(theta),
        "mode": args.mode,
        "strut_r_mm": r,
        "fillet_r_mm": rf,
        "method": method,
        "mass_bare_mm3": mass0,
        "mass_blend_mm3": mass1,
        "dmass_mm3": mass1 - mass0,
        "topology": topo,
        "fillet": fil_info,
        "bare_step": os.path.abspath(bare_path),
        "blend_step": os.path.abspath(blend_path),
    }
    man = os.path.join(out_dir, f"{slug}_r{rtag}_summary.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nBare:  {bare_path}", flush=True)
    print(f"Fillet:{blend_path}", flush=True)
    print(f"Wrote {man}", flush=True)
    ok = int(topo.get("solids") or 0) == 1 and bool(topo.get("brep_valid"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
