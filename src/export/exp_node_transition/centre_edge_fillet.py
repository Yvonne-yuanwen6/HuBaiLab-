"""
Centre-junction smooth STEP via OCC edge MakeFillet (experiment).

Returns to STEP-first delivery with *true* BRep fillet surfaces (not mesh facets,
not Boolean canal/sphere add-ons).

Pipeline:
  1) Bare pipe fuse (stable solid)
  2) Select concave edges near cell centre
  3) BRepFilletAPI_MakeFillet with radius ladder
  4) Write smooth STEP (single solid)

Does not touch batch / paper_box defaults.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from multiprocessing import Process, Queue
from typing import Any

import numpy as np

from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    _collect_edges_near_nodes,
    _edge_midpoint_mm,
    _try_fillet,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_unitcell_fuse import (
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)


@dataclass
class CentreFilletParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.5
    n_segments: int = 32
    # Search ball; actual candidates further restricted to annular band
    select_radius_mm: float = 4.0
    # Prefer armpit band away from exact origin (acute 11° seams explode)
    band_rmin_mm: float = 1.8
    band_rmax_mm: float = 3.8
    min_edge_len_mm: float = 0.35
    # Small fillet — Q=1.5 rejects large radii
    r_blend_factor: float = 0.12
    # Only top radius: smaller scales burn CPU / hang MakeFillet on Q=1.5
    radius_scales: tuple[float, ...] = (1.0, 0.75)
    concave_only: bool = False
    prefer_gmsh_step: bool = False
    max_dmass_step_mm3: float = 0.60
    max_edges_apply: int = 6
    max_candidates_per_pass: int = 8
    fillet_timeout_s: float = 25.0


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return v
    return v / n


def _edge_faces(shape: Any, edge: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopoDS import TopoDS

    mmap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, mmap)
    if not mmap.Contains(edge):
        return []
    faces: list[Any] = []
    lst = mmap.FindFromKey(edge)
    # OCP 7.x / pythonocc: ListOfShape is iterable (no ListIterator binding)
    for item in lst:
        faces.append(TopoDS.Face_s(item))
    return faces


def _face_normal_at_edge_mid(face: Any, edge: Any) -> np.ndarray | None:
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TopAbs import TopAbs_REVERSED

    try:
        ad = BRepAdaptor_Curve(edge)
        u0 = float(ad.FirstParameter())
        u1 = float(ad.LastParameter())
        p = ad.Value(0.5 * (u0 + u1))
        surf = BRepAdaptor_Surface(face)
        hsurf = BRep_Tool.Surface_s(face)
        proj = GeomAPI_ProjectPointOnSurf(p, hsurf)
        if proj.NbPoints() < 1:
            return None
        u, v = proj.LowerDistanceParameters()
        d1u = gp_Vec()
        d1v = gp_Vec()
        pnt = gp_Pnt()
        surf.D1(u, v, pnt, d1u, d1v)
        n = d1u.Crossed(d1v)
        if face.Orientation() == TopAbs_REVERSED:
            n.Reverse()
        vec = np.array([float(n.X()), float(n.Y()), float(n.Z())], dtype=float)
        return _unit(vec)
    except Exception:
        return None


def _is_concave_edge(shape: Any, edge: Any, *, center: np.ndarray) -> bool:
    """
    Concave (re-entrant) if both face normals point somewhat *away* from the
    material side toward the outside of the crotch — equivalently: the edge
    mid is a valley relative to the cell centre for junction blends.

    Practical test: average of face normals dotted with (mid - center) is
    negative enough → normals point outward while mid is near centre → valley
    facing center (armpit).
    """
    faces = _edge_faces(shape, edge)
    if len(faces) != 2:
        return False
    mid = _edge_midpoint_mm(edge)
    if mid is None:
        return False
    n0 = _face_normal_at_edge_mid(faces[0], edge)
    n1 = _face_normal_at_edge_mid(faces[1], edge)
    if n0 is None or n1 is None:
        return False
    # Dihedral: concave if normals diverge (n0·n1 small) AND mid is outside
    # relative to face material. For pipe junctions near origin, valleys have
    # outward normals whose average points away from centre.
    radial = mid - center
    rn = float(np.linalg.norm(radial))
    if rn < 1e-9:
        return True
    radial = radial / rn
    n_avg = _unit(n0 + n1)
    # Outward-ish average vs radial from centre: valley armpits → n_avg · radial > 0
    # (normals point out of solid, mid sits on outer crotch relative to centre).
    return float(np.dot(n_avg, radial)) > 0.05 and float(np.dot(n0, n1)) < 0.85


def _edge_length_mm(edge: Any) -> float:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint

    try:
        ad = BRepAdaptor_Curve(edge)
        return float(
            GCPnts_AbscissaPoint.Length_s(ad, ad.FirstParameter(), ad.LastParameter())
        )
    except Exception:
        return 0.0


def collect_centre_fillet_edges(
    shape: Any,
    params: CentreFilletParams,
) -> list[Any]:
    """
    Edges in an annular band around the cell centre (armpit zone).

    Avoid the exact origin cluster of nearly-parallel Q=1.5 seams — those
    MakeFillet attempts historically exploded the bbox (~25→246 mm).
    """
    center = np.zeros(3, dtype=float)
    raw = _collect_edges_near_nodes(
        shape,
        node_pts=[center],
        select_radius_mm=float(params.select_radius_mm),
    )
    scored: list[tuple[float, Any]] = []
    for e in raw:
        mid = _edge_midpoint_mm(e)
        if mid is None:
            continue
        rr = float(np.linalg.norm(mid - center))
        if rr < float(params.band_rmin_mm) or rr > float(params.band_rmax_mm):
            continue
        elen = _edge_length_mm(e)
        if elen < float(params.min_edge_len_mm):
            continue
        if params.concave_only:
            try:
                if not _is_concave_edge(shape, e, center=center):
                    continue
            except Exception:
                continue
        # Prefer longer edges slightly farther out (more stable)
        scored.append((elen + 0.1 * rr, e))
    scored.sort(key=lambda t: -t[0])
    edges = [e for _, e in scored]
    print(
        f"  [centreFillet] band=[{params.band_rmin_mm:g},{params.band_rmax_mm:g}] "
        f"candidates={len(edges)} (from {len(raw)} near-centre)",
        flush=True,
    )
    return edges


def _bbox_span(shape: Any) -> tuple[float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return (xmax - xmin, ymax - ymin, zmax - zmin)


def _write_brep(shape: Any, path: str) -> None:
    from OCP.BRepTools import BRepTools

    if not BRepTools.Write_s(shape, path):
        raise RuntimeError(f"BREP write failed: {path}")


def _read_brep(path: str) -> Any:
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    builder = BRep_Builder()
    if not BRepTools.Read_s(shape, path, builder):
        raise RuntimeError(f"BREP read failed: {path}")
    return shape


def _find_edge_near_mid(shape: Any, mid: np.ndarray, *, tol_mm: float = 0.35) -> Any:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    best = None
    best_d = 1e9
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        e = TopoDS.Edge_s(exp.Current())
        em = _edge_midpoint_mm(e)
        if em is not None:
            d = float(np.linalg.norm(em - mid))
            if d < best_d:
                best_d = d
                best = e
        exp.Next()
    if best is None or best_d > tol_mm:
        raise RuntimeError(f"edge mid not found (best_d={best_d:.3f})")
    return best


def _fillet_subprocess_worker(
    in_brep: str,
    out_brep: str,
    mid_xyz: tuple[float, float, float],
    radius_mm: float,
    q: Any,
) -> None:
    """Child process: MakeFillet one edge identified by midpoint (killable)."""
    try:
        shape = _read_brep(in_brep)
        edge = _find_edge_near_mid(shape, np.asarray(mid_xyz, dtype=float))
        out = _try_fillet(shape, [edge], float(radius_mm))
        _write_brep(out, out_brep)
        q.put({"ok": True})
    except Exception as exc:  # noqa: BLE001 — surface to parent
        q.put({"ok": False, "err": str(exc)})


def _try_fillet_timeout(
    shape: Any,
    edge: Any,
    radius_mm: float,
    *,
    timeout_s: float,
) -> Any:
    """
    MakeFillet in a child process so hung OCC Build() can be terminated.
    Falls back to in-process only if mid cannot be measured.
    """
    mid = _edge_midpoint_mm(edge)
    if mid is None:
        return _try_fillet(shape, [edge], radius_mm)

    td = tempfile.mkdtemp(prefix="exp_fillet_to_")
    in_brep = os.path.join(td, "in.brep")
    out_brep = os.path.join(td, "out.brep")
    try:
        _write_brep(shape, in_brep)
        q: Queue = Queue()
        proc = Process(
            target=_fillet_subprocess_worker,
            args=(
                in_brep,
                out_brep,
                (float(mid[0]), float(mid[1]), float(mid[2])),
                float(radius_mm),
                q,
            ),
        )
        proc.start()
        proc.join(float(timeout_s))
        if proc.is_alive():
            proc.terminate()
            proc.join(5.0)
            raise TimeoutError(f"MakeFillet timeout >{timeout_s:.0f}s")
        if q.empty():
            raise RuntimeError("fillet worker exited with no result")
        res = q.get()
        if not res.get("ok"):
            raise RuntimeError(str(res.get("err") or "fillet worker failed"))
        return _read_brep(out_brep)
    finally:
        for p in (in_brep, out_brep):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(td)
        except OSError:
            pass


def apply_centre_fillet(
    shape: Any,
    params: CentreFilletParams,
) -> tuple[Any, dict[str, Any]]:
    """
    Apply MakeFillet one edge at a time with hard integrity gates.

    Reject any step that explodes the bbox or dumps mass (Q=1.5 MakeFillet
    often 'succeeds' while shredding the solid — that was the SW 破碎).
    """
    r_strut = 0.5 * float(params.rod_d_mm)
    r0 = float(params.r_blend_factor) * r_strut
    m0 = float(ocp_mass(shape))
    span0 = _bbox_span(shape)
    # Unitcell must stay near L; allow small grow for fillet beads
    max_span = float(params.cell_size_mm) * 1.35
    max_dmass_step = float(params.max_dmass_step_mm3)
    max_apply = max(1, int(params.max_edges_apply))
    max_cand = max(1, int(params.max_candidates_per_pass))
    timeout_s = float(params.fillet_timeout_s)
    cur = shape
    applied: list[dict[str, Any]] = []
    errors: list[str] = []
    rejected_explode = 0
    timed_out = 0

    for s in params.radius_scales:
        if len(applied) >= max_apply:
            break
        rad = float(s) * r0
        if rad < 1e-4:
            continue
        for pass_i in range(8):
            if len(applied) >= max_apply:
                break
            edges = collect_centre_fillet_edges(cur, params)[:max_cand]
            if pass_i == 0:
                print(
                    f"  [centreFillet] pass r={rad:.3f} candidate_edges={len(edges)} "
                    f"span0={tuple(round(x,2) for x in span0)} "
                    f"timeout={timeout_s:.0f}s",
                    flush=True,
                )
            if not edges:
                break
            got = False
            for ei, edge in enumerate(edges):
                try:
                    trial = _try_fillet_timeout(
                        cur, edge, rad, timeout_s=timeout_s
                    )
                    topo = ocp_shape_topology(trial)
                    if int(topo.get("solids") or 0) != 1:
                        raise RuntimeError(f"solids={topo.get('solids')}")
                    # Q=1.5 often marks BRepCheck invalid while span/mass stay sane;
                    # reject only geometric explosion (the SW 破碎 cause).
                    m1 = float(ocp_mass(trial))
                    if m1 < 0.95 * m0:
                        raise RuntimeError(f"mass collapse {m1:.2f}")
                    d = m1 - float(ocp_mass(cur))
                    # True concave fillet should not remove significant mass
                    if d < -0.05:
                        rejected_explode += 1
                        raise RuntimeError(f"dmass_negative {d:+.3f}")
                    if d > max_dmass_step:
                        rejected_explode += 1
                        raise RuntimeError(f"dmass_explode {d:+.3f}")
                    span = _bbox_span(trial)
                    if any(span[k] > max_span for k in range(3)):
                        rejected_explode += 1
                        raise RuntimeError(
                            f"bbox_explode span={tuple(round(x,2) for x in span)}"
                        )
                    if any(span[k] > span0[k] + 2.5 for k in range(3)):
                        rejected_explode += 1
                        raise RuntimeError(
                            f"bbox_grow span={tuple(round(x,2) for x in span)}"
                        )
                    # Optional soft heal when checker is unhappy
                    if topo.get("brep_valid") is False:
                        try:
                            from OCP.ShapeFix import ShapeFix_Shape

                            fixer = ShapeFix_Shape(trial)
                            fixer.Perform()
                            healed = fixer.Shape()
                            ht = ocp_shape_topology(healed)
                            hs = _bbox_span(healed)
                            hm = float(ocp_mass(healed))
                            hd = hm - float(ocp_mass(cur))
                            if (
                                int(ht.get("solids") or 0) == 1
                                and all(hs[k] <= max_span for k in range(3))
                                and hm > 0.95 * m0
                                and hd >= -0.05
                                and hd <= max_dmass_step
                            ):
                                trial = healed
                                topo = ht
                                m1 = hm
                                d = hd
                                span = hs
                                print(
                                    f"  [centreFillet] ShapeFix after invalid "
                                    f"brep (valid={topo.get('brep_valid')})",
                                    flush=True,
                                )
                        except Exception as hexc:
                            print(f"  [centreFillet] ShapeFix warn: {hexc}", flush=True)
                    cur = trial
                    applied.append(
                        {
                            "r_mm": rad,
                            "edge_index": ei,
                            "pass": pass_i,
                            "dmass_step": d,
                            "mass_mm3": m1,
                            "span": span,
                        }
                    )
                    print(
                        f"  [centreFillet] +edge#{ei} r={rad:.3f} "
                        f"d={d:+.3f} mass={m1:.3f} (n_ok={len(applied)})",
                        flush=True,
                    )
                    got = True
                    break
                except TimeoutError as exc:
                    timed_out += 1
                    errors.append(f"r={rad:g} e={ei}: {exc}")
                    print(f"  [centreFillet] skip timeout edge#{ei} r={rad:.3f}", flush=True)
                    continue
                except Exception as exc:
                    errors.append(f"r={rad:g} e={ei}: {exc}")
                    continue
            if not got:
                break

    if not applied:
        raise RuntimeError(
            "centre fillet produced no safe edge "
            f"(rejected_explode={rejected_explode}, timed_out={timed_out}, "
            f"last_errors={errors[-6:] if errors else []})"
        )

    # Final integrity (span/mass/solid — not BRepCheck flag alone)
    span_f = _bbox_span(cur)
    if any(span_f[k] > max_span for k in range(3)):
        raise RuntimeError(f"final bbox explode {span_f}")
    topo = ocp_shape_topology(cur)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"final topology bad {topo}")
    m1 = float(ocp_mass(cur))
    if m1 < 0.95 * m0 or m1 > m0 + 8.0:
        raise RuntimeError(f"final mass out of band {m1} vs {m0}")
    return cur, {
        "mode": "sequential_single_edge_gated",
        "r0_mm": r0,
        "n_applied": len(applied),
        "applied": applied,
        "mass_pre_mm3": m0,
        "mass_mm3": m1,
        "mass_delta_mm3": m1 - m0,
        "span0": span0,
        "span_final": span_f,
        "topology": topo,
        "rejected_explode": rejected_explode,
        "timed_out": timed_out,
        "n_errors_logged": len(errors),
    }


def export_centre_fillet_unitcell(
    params: CentreFilletParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    params = params or CentreFilletParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = str(q).replace(".", "p")
    rf_tag = str(params.r_blend_factor).replace(".", "p")
    slug = (
        f"exp_centreFillet_af{int(round(params.amplitude_mm))}q{q_tag}"
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
    print("  [centreFillet] bare fuse ...", flush=True)
    bare, mass_bare, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    if int(ocp_shape_topology(bare).get("solids") or 0) != 1:
        raise RuntimeError("bare not single solid")
    ocp_write_step(bare, bare_path)

    used_bare = False
    try:
        final, fillet_info = apply_centre_fillet(bare, params)
    except Exception as exc:
        print(f"  [centreFillet] fillet failed → bare STEP ({exc})", flush=True)
        final = bare
        fillet_info = {"error": str(exc), "applied": False}
        used_bare = True

    # Smooth BRep STEP write — skip gmsh heal (destroys fragile fillets → 0 solid)
    write_note = "ocp_direct"
    try:
        ocp_write_step(final, step_path)
        # Hard readback: must remain 1 solid with sane span
        from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

        rb = ocp_read_step_shape(step_path)
        rb_topo = ocp_shape_topology(rb)
        rb_span = _bbox_span(rb)
        if int(rb_topo.get("solids") or 0) != 1:
            raise RuntimeError(f"STEP readback solids={rb_topo.get('solids')}")
        if any(rb_span[k] > float(params.cell_size_mm) * 1.35 for k in range(3)):
            raise RuntimeError(f"STEP readback bbox explode {rb_span}")
        write_note = "ocp_direct_readback_ok"
    except Exception as exc:
        print(f"  [centreFillet] STEP write/readback fail → bare ({exc})", flush=True)
        final = bare
        used_bare = True
        fillet_info = {
            **(fillet_info if isinstance(fillet_info, dict) else {}),
            "step_readback_error": str(exc),
            "reverted_to_bare": True,
        }
        ocp_write_step(final, step_path)
        write_note = "bare_after_bad_step"

    topo = ocp_shape_topology(final)
    mass = float(ocp_mass(final))
    man = {
        "experiment": "centre_edge_fillet",
        "note": (
            "Smooth STEP via OCC MakeFillet on centre junction edges "
            "(true BRep fillet surfaces). Not mesh/OBJ facets, not Boolean add-ons."
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
        "step_write": write_note,
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(f"\n=== CENTRE FILLET STEP Q={q:g} ===", flush=True)
    print(
        f"  STEP: {step_path}  mass={mass:.3f}  "
        f"fallback_bare={used_bare}  solids={topo.get('solids')}",
        flush=True,
    )
    print(f"  manifest: {man_path}", flush=True)
    return man
