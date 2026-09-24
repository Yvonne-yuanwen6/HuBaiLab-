"""
Centre-taper pipe unitcell (experiment): smooth armpit fill via build-time BRep.

Instead of post-hoc MakeFillet (Q=1.5 → invalid compound / STEP mass loss), each
strut is swept with MakePipeShell using a mildly larger radius near the cell
centre that tapers back to the nominal rod radius. Fusing the eight octants
fills the acute crouches with true BRep surfaces (constant-topology solid).

Isolation: only used from scripts/exp_centre_taper_verify.py.
Does not change batch / paper_box defaults.
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
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.centre_edge_fillet import _bbox_span
from src.export.ocp_unitcell_fuse import (
    OCTANT_CENTER_OVERLAP_MM,
    _as_np_points,
    _box_from_bounds,
    _canonical_corner_from_pipe_path,
    _octant_bounds_from_corner_mm,
    _profile_wire_at_point,
    _require_ocp,
    _spline_wire,
    fuse_octant_shapes,
    ocp_common,
    ocp_fuse_pair,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
    octant_centre_path_extension_mm,
)
from src.mesh.occ_pipe import frames_along_polyline
from src.export.unitcell_box_cut import (
    extend_pipe_path_past_corner,
    pipe_part_with_both_end_path_extension,
    unitcell_octant_corners_mm,
)


@dataclass
class CentreTaperParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.5
    n_segments: int = 32
    # Distance from origin over which radius tapers R*scale → R
    taper_mm: float = 3.5
    # Radius scale at the cell centre (1.0 = no taper)
    taper_scale: float = 1.45
    centre_extension_mm: float | None = None
    corner_extension_mm: float | None = None
    fuse_strategy: str = "sequential_glue_shift"
    fuzzy_mm: float = 0.02
    # both_end_extension | centre_stub_corner_ext | auto
    # auto: Q≈1 → centre_stub_corner_ext (Q=1 both_end fuse historically fragile)
    pipe_mode: str = "auto"


def _radius_at_point(
    pt: np.ndarray,
    *,
    radius: float,
    taper_mm: float,
    taper_scale: float,
) -> float:
    d = float(np.linalg.norm(pt))
    if taper_mm <= 1e-9 or taper_scale <= 1.0 + 1e-9:
        return float(radius)
    if d >= taper_mm:
        return float(radius)
    # Smooth hermite-ish blend: scale at centre → 1 at taper_mm
    t = d / taper_mm
    # smoothstep
    w = t * t * (3.0 - 2.0 * t)
    scale = float(taper_scale) + (1.0 - float(taper_scale)) * w
    return float(radius) * scale


def _scale_law_from_path(
    pts: np.ndarray,
    *,
    taper_mm: float,
    taper_scale: float,
    u0: float,
    u1: float,
):
    """
    Map path arc-length fraction ≈ spine U, scale by distance-to-origin.

    Near the cell centre (small ||p||) radius scale → taper_scale;
    outside taper_mm → 1.0. Uses Law_Interpol so the outer strut stays nominal.
    """
    from OCP.Law import Law_Interpol
    from OCP.TColgp import TColgp_Array1OfPnt2d
    from OCP.gp import gp_Pnt2d

    pts = np.asarray(pts, dtype=float)
    if len(pts) < 2:
        raise ValueError("need >=2 path points for taper law")
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(s[-1])
    if total < 1e-12:
        raise ValueError("degenerate path length")

    # Sample ~8 knots spanning the path (always include ends)
    n_samp = min(8, len(pts))
    idxs = sorted(
        set(
            int(round(i * (len(pts) - 1) / (n_samp - 1)))
            for i in range(n_samp)
        )
    )
    knots: list[tuple[float, float]] = []
    for i in idxs:
        u = float(u0) + (float(s[i]) / total) * (float(u1) - float(u0))
        # scale = r_loc / r_nominal via _radius_at_point with radius=1
        sc = _radius_at_point(
            pts[i],
            radius=1.0,
            taper_mm=taper_mm,
            taper_scale=taper_scale,
        )
        knots.append((u, float(sc)))

    # Ensure strictly increasing U for Law_Interpol
    cleaned: list[tuple[float, float]] = []
    for u, sc in knots:
        if cleaned and u <= cleaned[-1][0] + 1e-9:
            cleaned[-1] = (cleaned[-1][0], sc)
        else:
            cleaned.append((u, sc))
    if len(cleaned) < 2:
        cleaned = [(float(u0), float(taper_scale)), (float(u1), 1.0)]

    arr = TColgp_Array1OfPnt2d(1, len(cleaned))
    for k, (u, sc) in enumerate(cleaned, start=1):
        arr.SetValue(k, gp_Pnt2d(float(u), float(sc)))
    law = Law_Interpol()
    law.Set(arr, False)
    return law


def ocp_pipe_centre_taper(
    path_pts: tuple,
    radius: float,
    *,
    taper_mm: float,
    taper_scale: float,
    open_at_start: bool = False,
) -> Any:
    """
    Spline MakePipeShell with SetLaw radius scale near the cell centre.

    Matches the constant-radius pipe path (same spine) when taper_scale=1;
    Law_Interpol keeps BRep valid and STEP-stable (unlike post-hoc MakeFillet).
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    ocp = _require_ocp()
    pts_all = np.asarray(_as_np_points(path_pts), dtype=float)
    if len(pts_all) < 2:
        raise ValueError("pipe path needs at least two points")
    if open_at_start:
        if len(pts_all) < 3:
            raise ValueError("open_at_start taper needs at least three path points")
        pts = pts_all[1:]
        frames_full = frames_along_polyline(pts_all)
        e_z, e_x, _ = frames_full[1]
    else:
        pts = pts_all
        frames = frames_along_polyline(pts)
        e_z, e_x, _ = frames[0]

    path_tup = tuple(tuple(float(v) for v in p) for p in pts)
    wire = _spline_wire(path_tup)
    profile = _profile_wire_at_point(pts[0], e_z, e_x, float(radius))

    exp = TopExp_Explorer(wire, TopAbs_EDGE)
    edge = TopoDS.Edge_s(exp.Current())
    ad = BRepAdaptor_Curve(edge)
    u0 = float(ad.FirstParameter())
    u1 = float(ad.LastParameter())
    # Law from geometric distance-to-origin on the swept points
    law = _scale_law_from_path(
        pts,
        taper_mm=float(taper_mm),
        taper_scale=float(taper_scale),
        u0=u0,
        u1=u1,
    )

    shell = ocp["BRepOffsetAPI_MakePipeShell"](wire)
    shell.SetMode(False)
    shell.Add(profile)
    shell.SetLaw(profile, law)
    shell.Build()
    if not shell.IsDone():
        raise RuntimeError(f"centre-taper MakePipeShell failed: {shell.GetStatus()}")
    if not shell.MakeSolid():
        raise RuntimeError("centre-taper MakePipeShell MakeSolid failed")
    return shell.Shape()


def ocp_pipe_centre_taper_with_stub(
    path_pts: tuple,
    radius: float,
    *,
    taper_mm: float,
    taper_scale: float,
) -> Any:
    """Centre chord cylinder + open-start tapered spline (Q=1 face-mate path)."""
    pts = np.asarray(_as_np_points(path_pts), dtype=float)
    if len(pts) < 2:
        raise ValueError("pipe path needs at least two points")
    p0, p1 = pts[0], pts[1]
    chord = p1 - p0
    length = float(np.linalg.norm(chord))
    if length < 1e-9:
        return ocp_pipe_centre_taper(
            path_pts, radius, taper_mm=taper_mm, taper_scale=taper_scale
        )

    ocp = _require_ocp()
    direction = chord / length
    # Mildly larger stub matches near-centre taper scale
    r_stub = float(radius) * min(float(taper_scale), 1.35)
    ax = ocp["gp_Ax2"](
        ocp["gp_Pnt"](float(p0[0]), float(p0[1]), float(p0[2])),
        ocp["gp_Dir"](
            float(direction[0]),
            float(direction[1]),
            float(direction[2]),
        ),
    )
    cyl = ocp["BRepPrimAPI_MakeCylinder"](ax, r_stub, length).Shape()
    pipe = ocp_pipe_centre_taper(
        path_pts,
        radius,
        taper_mm=taper_mm,
        taper_scale=taper_scale,
        open_at_start=True,
    )
    return ocp_fuse_pair(
        cyl, pipe, glue="shift", fuzzy_mm=0.02, label="centre-taper-stub"
    )


def _resolve_pipe_mode(params: CentreTaperParams) -> str:
    mode = str(params.pipe_mode or "auto").strip().lower()
    if mode == "auto":
        # Q=1 (−Af·sin) both_end+taper empties at fuse step 3; use stub+corner.
        if abs(float(params.period_factor) - 1.0) < 1e-9:
            return "centre_stub_corner_ext"
        return "both_end_extension"
    return mode


def build_centre_taper_octants(
    params: CentreTaperParams,
) -> tuple[list[Any], float, dict[str, Any]]:
    fp = ExpFilletParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=params.period_factor,
        n_segments=params.n_segments,
    )
    parts = load_fillet_pipe_parts(fp)
    if len(parts) != 8:
        raise RuntimeError(f"expected 8 pipes, got {len(parts)}")

    sample_r = 0.5 * float(params.rod_d_mm)
    auto_ext = octant_centre_path_extension_mm(sample_r)
    centre_ext = (
        float(params.centre_extension_mm)
        if params.centre_extension_mm is not None
        else auto_ext
    )
    corner_ext = (
        float(params.corner_extension_mm)
        if params.corner_extension_mm is not None
        else centre_ext
    )

    corners = unitcell_octant_corners_mm(params.cell_size_mm)
    corner_tol = max(1e-3, 1e-6 * float(params.cell_size_mm))
    cut_shapes: list[Any] = []
    pipe_ref_mass = 0.0
    pipe_mode = _resolve_pipe_mode(params)

    print(
        f"  [centreTaper] mode={pipe_mode} taper_mm={params.taper_mm:g} "
        f"scale={params.taper_scale:g} ext=({centre_ext:g},{corner_ext:g})",
        flush=True,
    )

    for idx, part in enumerate(parts, start=1):
        corner = corners[idx - 1]
        path_corner = _canonical_corner_from_pipe_path(part[1], params.cell_size_mm)
        if any(abs(path_corner[i] - corner[i]) > corner_tol for i in range(3)):
            raise RuntimeError(
                f"strut {idx}: endpoint {path_corner} != octant corner {corner}"
            )
        radius = float(part[2])
        if pipe_mode == "centre_stub_corner_ext":
            path_for_stub = part[1]
            if corner_ext > 0.0:
                path_for_stub = extend_pipe_path_past_corner(path_for_stub, corner_ext)
            pipe_solid = ocp_pipe_centre_taper_with_stub(
                path_for_stub,
                radius,
                taper_mm=float(params.taper_mm),
                taper_scale=float(params.taper_scale),
            )
        else:
            _, extended_path, _ = pipe_part_with_both_end_path_extension(
                part,
                centre_ext,
                corner_extension_mm=corner_ext,
            )
            pipe_solid = ocp_pipe_centre_taper(
                extended_path,
                radius,
                taper_mm=float(params.taper_mm),
                taper_scale=float(params.taper_scale),
            )
        pipe_ref_mass += float(ocp_mass(pipe_solid))
        bounds = _octant_bounds_from_corner_mm(
            corner,
            params.cell_size_mm,
            center_overlap_mm=float(OCTANT_CENTER_OVERLAP_MM),
        )
        box = _box_from_bounds(bounds)
        cut = ocp_common(pipe_solid, box)
        cut_mass = float(ocp_mass(cut))
        if cut_mass <= 0.0:
            raise RuntimeError(f"strut {idx}: octant cut empty")
        cut_shapes.append(cut)
        print(
            f"  [centreTaper] octant {idx}/8 mass={cut_mass:.1f} corner={corner}",
            flush=True,
        )

    meta = {
        "pipe_mode": pipe_mode,
        "centre_ext_mm": centre_ext,
        "corner_ext_mm": corner_ext,
        "pipe_ref_mass_mm3": pipe_ref_mass,
        "cut_sum_mm3": sum(float(ocp_mass(s)) for s in cut_shapes),
    }
    return cut_shapes, pipe_ref_mass, meta


def fuse_centre_taper_unitcell(
    params: CentreTaperParams,
) -> tuple[Any, dict[str, Any]]:
    """
    Build taper octants then fuse with a small strategy ladder.

    Q≈1 often fails on the first GlueShift recipe (same as bare Q=1 history);
    fall back to GlueFull / higher fuzzy before giving up.
    """
    cuts, pipe_ref, meta = build_centre_taper_octants(params)
    cut_sum = float(meta["cut_sum_mm3"])
    fuzzy0 = float(params.fuzzy_mm)
    recipes: list[tuple[str, float]] = [
        (str(params.fuse_strategy), fuzzy0),
        ("sequential_glue_full", max(fuzzy0, 0.08)),
        ("batch_glue_shift", max(fuzzy0, 0.05)),
        ("sequential_glue_shift", max(fuzzy0, 0.08)),
    ]
    # de-dupe while preserving order
    seen: set[tuple[str, float]] = set()
    uniq: list[tuple[str, float]] = []
    for strat, fz in recipes:
        key = (strat, round(fz, 6))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((strat, fz))

    last_exc: Exception | None = None
    for strat, fz in uniq:
        try:
            print(
                f"  [centreTaper] fuse try {strat} fuzzy={fz:g} ...",
                flush=True,
            )
            fused, fuse_desc = fuse_octant_shapes(
                cuts,
                cut_mass=cut_sum,
                strategy=strat,  # type: ignore[arg-type]
                fuzzy_mm=float(fz),
                cell_size_mm=float(params.cell_size_mm),
            )
            topo = ocp_shape_topology(fused, check_brep=True)
            span = _bbox_span(fused)
            mass = float(ocp_mass(fused))
            if int(topo.get("solids") or 0) != 1:
                raise RuntimeError(f"taper fuse not single solid: {topo}")
            max_span = float(params.cell_size_mm) * 1.35
            if any(span[k] > max_span for k in range(3)):
                raise RuntimeError(f"taper fuse bbox explode {span}")
            info = {
                **meta,
                "pipe_ref_mass_mm3": pipe_ref,
                "fuse": fuse_desc,
                "fuse_strategy_used": strat,
                "fuse_fuzzy_mm": fz,
                "mass_mm3": mass,
                "span": span,
                "topology": topo,
            }
            return fused, info
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"  [centreTaper] fuse fail {strat}: {exc}", flush=True)
            continue
    raise RuntimeError(
        f"centre taper fuse exhausted recipes; last={last_exc}"
    )


def export_centre_taper_unitcell(
    params: CentreTaperParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    params = params or CentreTaperParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = str(q).replace(".", "p")
    sc_tag = str(params.taper_scale).replace(".", "p")
    tp_tag = str(params.taper_mm).replace(".", "p")
    slug = (
        f"exp_centreTaper_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_tp{tp_tag}sc{sc_tag}"
        f"_1x1"
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

    print("  [centreTaper] build + fuse ...", flush=True)
    solid, info = fuse_centre_taper_unitcell(params)
    ocp_write_step(solid, step_path)

    from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

    rb = ocp_read_step_shape(step_path)
    rb_topo = ocp_shape_topology(rb, check_brep=True)
    rb_span = _bbox_span(rb)
    rb_mass = float(ocp_mass(rb))
    if int(rb_topo.get("solids") or 0) != 1:
        raise RuntimeError(f"STEP readback solids={rb_topo.get('solids')}")
    if any(rb_span[k] > float(params.cell_size_mm) * 1.35 for k in range(3)):
        raise RuntimeError(f"STEP readback bbox explode {rb_span}")
    # Mass must survive STEP (unlike MakeFillet compounds)
    mem_mass = float(info["mass_mm3"])
    if abs(rb_mass - mem_mass) > max(1.0, 0.02 * mem_mass):
        raise RuntimeError(
            f"STEP mass drift mem={mem_mass:.3f} rb={rb_mass:.3f}"
        )

    man = {
        "experiment": "centre_taper_pipe",
        "note": (
            "Build-time centre radius taper via MakePipeShell + Law_Interpol; "
            "true BRep solid (not MakeFillet, not mesh, not Boolean canal)."
        ),
        "params": asdict(params),
        "step_path": os.path.abspath(step_path),
        "build": info,
        "step_readback": {
            "mass_mm3": rb_mass,
            "span": rb_span,
            "topology": rb_topo,
        },
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(f"\n=== CENTRE TAPER STEP Q={q:g} ===", flush=True)
    print(
        f"  STEP: {step_path}  mass={rb_mass:.3f}  "
        f"span={tuple(round(x, 2) for x in rb_span)}  "
        f"solids={rb_topo.get('solids')} valid={rb_topo.get('brep_valid')}",
        flush=True,
    )
    print(f"  manifest: {man_path}", flush=True)
    return man
