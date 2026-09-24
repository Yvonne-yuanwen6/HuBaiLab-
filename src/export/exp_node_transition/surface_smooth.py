"""
Direct surface smoothing of a fused unitcell (experiment).

Does NOT add canals/spheres/hubs. Operates on the existing solid surface:

  1) Mesh the bare fused solid
  2) Local Taubin smooth near the cell centre (junction region only)
  3) Write STL (primary visual) + optional faceted STEP via gmsh

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
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


@dataclass
class SurfaceSmoothParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.5
    n_segments: int = 32
    # Finer mesh → less tear at strut seams
    mesh_deflection_mm: float = 0.08
    # Local smooth ball around cell centre
    smooth_radius_mm: float = 3.5
    # Wide soft falloff (avoids hard cut → cracks)
    falloff_mm: float = 4.0
    iterations: int = 8
    # Milder Taubin (less folding / shatter)
    taubin_lambda: float = 0.20
    taubin_mu: float = -0.21
    # Cap |disp| per iteration (mm)
    max_step_mm: float = 0.08
    # Write faceted STEP from smoothed STL via gmsh (approximate CAD)
    write_faceted_step: bool = False


def _shape_to_trimesh(shape: Any, *, deflection_mm: float, tmp_stl: str):
    """
    Closed surface mesh via gmsh (BREP heal → 2D mesh).

    OCC StlAPI triangles are usually non-watertight (open seams) and tear under
    local smooth — that was the '破碎' the user saw.
    ``deflection_mm`` maps to gmsh characteristic length.
    """
    import gmsh
    import trimesh
    from OCP.BRepTools import BRepTools

    brep_path = os.path.abspath(tmp_stl) + ".brep"
    out_stl = os.path.abspath(tmp_stl)
    os.makedirs(os.path.dirname(out_stl) or ".", exist_ok=True)
    if not BRepTools.Write_s(shape, brep_path):
        raise RuntimeError(f"BREP write failed: {brep_path}")

    lc = max(0.12, float(deflection_mm) * 2.0)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("surf_smooth_mesh")
        gmsh.model.occ.importShapes(brep_path)
        gmsh.model.occ.synchronize()
        try:
            gmsh.model.occ.healShapes(tolerance=0.05)
            gmsh.model.occ.synchronize()
        except Exception as exc:
            print(f"  [surfSmooth] gmsh heal warn: {exc}", flush=True)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 0.45 * lc)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.model.mesh.generate(2)
        gmsh.write(out_stl)
    finally:
        gmsh.finalize()

    if not os.path.isfile(out_stl) or os.path.getsize(out_stl) < 100:
        raise RuntimeError(f"gmsh surface STL failed: {out_stl}")

    mesh = trimesh.load(out_stl, force="mesh", process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    trimesh.grouping.merge_vertices(mesh, digits_vertex=5)
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    try:
        trimesh.repair.fix_normals(mesh)
    except Exception:
        pass

    print(
        f"  [surfSmooth] gmsh mesh verts={len(mesh.vertices)} faces={len(mesh.faces)} "
        f"watertight={mesh.is_watertight} euler={mesh.euler_number}",
        flush=True,
    )
    if not mesh.is_watertight:
        raise RuntimeError(
            "surface mesh not watertight after gmsh — refusing smooth (would shatter)"
        )
    return mesh


def _vertex_weights(
    vertices: np.ndarray,
    *,
    center: np.ndarray,
    radius_mm: float,
    falloff_mm: float,
) -> np.ndarray:
    d = np.linalg.norm(vertices - center.reshape(1, 3), axis=1)
    r0 = float(radius_mm)
    r1 = r0 + max(float(falloff_mm), 1e-6)
    w = np.ones_like(d)
    mid = (d > r0) & (d < r1)
    w[d >= r1] = 0.0
    # Smooth hermite falloff
    t = (d[mid] - r0) / (r1 - r0)
    w[mid] = 1.0 - (3.0 * t * t - 2.0 * t * t * t)
    return w.astype(float)


def _cotangent_laplacian_displacement(mesh) -> np.ndarray:
    """Uniform Laplacian displacement (vectorized)."""
    v = np.asarray(mesh.vertices, dtype=float)
    n = len(v)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    edges = np.unique(edges, axis=0)
    a = edges[:, 0]
    b = edges[:, 1]
    acc = np.zeros_like(v)
    cnt = np.zeros(n, dtype=float)
    np.add.at(acc, a, v[b])
    np.add.at(acc, b, v[a])
    np.add.at(cnt, a, 1.0)
    np.add.at(cnt, b, 1.0)
    cnt = np.maximum(cnt, 1.0)
    mean = acc / cnt[:, None]
    return mean - v


def local_taubin_smooth(
    mesh,
    *,
    center_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
    radius_mm: float = 3.5,
    falloff_mm: float = 4.0,
    iterations: int = 8,
    lamb: float = 0.20,
    mu: float = -0.21,
    max_step_mm: float = 0.08,
):
    """
    Mild local Taubin smooth near cell centre.

    Weights are frozen on the *original* positions so the blend region does not
    crawl outward and tear against frozen far-field vertices.
    """
    import trimesh

    m = mesh.copy()
    center = np.asarray(center_mm, dtype=float)
    v0 = np.asarray(m.vertices, dtype=float).copy()
    w = _vertex_weights(
        v0,
        center=center,
        radius_mm=radius_mm,
        falloff_mm=falloff_mm,
    )
    n_active = int(np.count_nonzero(w > 1e-6))
    print(
        f"  [surfSmooth] active verts={n_active}/{len(m.vertices)} "
        f"R={radius_mm:g}+{falloff_mm:g} mm iters={iterations} "
        f"λ={lamb:g} μ={mu:g} cap={max_step_mm:g}",
        flush=True,
    )
    cap = float(max_step_mm)
    for it in range(int(iterations)):
        disp = _cotangent_laplacian_displacement(m)
        step = float(lamb if (it % 2 == 0) else mu)
        delta = (w[:, None] * step) * disp
        # Cap step length to avoid fold / shatter
        nrm = np.linalg.norm(delta, axis=1, keepdims=True)
        scale = np.ones_like(nrm)
        big = nrm > cap
        scale[big] = cap / nrm[big]
        delta = delta * scale
        m.vertices = np.asarray(m.vertices, dtype=float) + delta

    # Far-field verts stay exactly original (numerical drift guard)
    frozen = w < 1e-8
    m.vertices[frozen] = v0[frozen]

    try:
        trimesh.repair.fix_normals(m)
    except Exception:
        pass
    # Critical for SW: export must be welded (gmsh/trimesh STL often duplicates verts)
    trimesh.grouping.merge_vertices(m, digits_vertex=5)
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    if not m.is_watertight:
        raise RuntimeError("smoothed mesh not watertight after weld")

    return m, {
        "n_vertices": int(len(m.vertices)),
        "n_faces": int(len(m.faces)),
        "n_active_vertices": n_active,
        "watertight": bool(m.is_watertight),
        "volume": float(m.volume) if m.is_watertight else None,
    }


def mesh_to_faceted_step(mesh, step_path: str, *, sew_tol: float = 1e-3) -> dict[str, Any]:
    """
    Watertight triangle mesh → single-solid faceted STEP (OCC MakeShapeOnMesh).

    This is approximate CAD (planar facets), not NURBS fillets — but opens as one
    solid in SolidWorks.
    """
    import tempfile

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeShapeOnMesh,
        BRepBuilderAPI_MakeSolid,
        BRepBuilderAPI_Sewing,
    )
    from OCP.RWStl import RWStl
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    os.makedirs(os.path.dirname(step_path) or ".", exist_ok=True)
    tmp_stl = os.path.join(
        tempfile.mkdtemp(prefix="surf_step_"), "mesh.stl"
    )
    mesh.export(tmp_stl)
    tri = RWStl.ReadFile_s(os.path.abspath(tmp_stl))
    if tri is None or int(tri.NbTriangles()) < 4:
        raise RuntimeError("RWStl failed to read mesh")
    mk = BRepBuilderAPI_MakeShapeOnMesh(tri)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("MakeShapeOnMesh failed")
    sew = BRepBuilderAPI_Sewing(float(sew_tol))
    sew.Add(mk.Shape())
    sew.Perform()
    sewn = sew.SewedShape()
    shells: list[Any] = []
    exp = TopExp_Explorer(sewn, TopAbs_SHELL)
    while exp.More():
        shells.append(TopoDS.Shell_s(exp.Current()))
        exp.Next()
    if len(shells) == 1:
        ms = BRepBuilderAPI_MakeSolid(shells[0])
        if ms.IsDone():
            final = ms.Solid()
        else:
            final = sewn
    else:
        final = sewn
    ocp_write_step(final, step_path)
    topo = ocp_shape_topology(final)
    return {
        "ok": int(topo.get("solids") or 0) == 1,
        "topology": topo,
        "mass_mm3": float(ocp_mass(final)),
        "step_bytes": os.path.getsize(step_path) if os.path.isfile(step_path) else 0,
        "n_faces_mesh": int(len(mesh.faces)),
    }


def export_surface_smooth_unitcell(
    params: SurfaceSmoothParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    params = params or SurfaceSmoothParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = str(q).replace(".", "p")
    slug = (
        f"exp_surfSmoothV3_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_R{str(params.smooth_radius_mm).replace('.', 'p')}"
        f"_i{int(params.iterations)}"
        f"_1x1"
    )
    stl_path = os.path.join(out_dir, f"{slug}.stl")
    bare_step = os.path.join(out_dir, f"{slug}_bare.step")
    bare_stl = os.path.join(out_dir, f"{slug}_bare.stl")
    step_path = os.path.join(out_dir, f"{slug}.step")
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")

    if (
        not force
        and os.path.isfile(stl_path)
        and os.path.getsize(stl_path) > 1000
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
    print("  [surfSmooth] bare fuse ...", flush=True)
    bare, mass_bare, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    topo0 = ocp_shape_topology(bare)
    if int(topo0.get("solids") or 0) != 1:
        raise RuntimeError(f"bare not solid: {topo0}")
    ocp_write_step(bare, bare_step)

    print("  [surfSmooth] mesh solid (gmsh heal → watertight) ...", flush=True)
    mesh0 = _shape_to_trimesh(
        bare,
        deflection_mm=float(params.mesh_deflection_mm),
        tmp_stl=bare_stl,
    )
    mesh1, mesh_info = local_taubin_smooth(
        mesh0,
        center_mm=(0.0, 0.0, 0.0),
        radius_mm=float(params.smooth_radius_mm),
        falloff_mm=float(params.falloff_mm),
        iterations=int(params.iterations),
        lamb=float(params.taubin_lambda),
        mu=float(params.taubin_mu),
        max_step_mm=float(params.max_step_mm),
    )
    if not mesh1.is_watertight:
        raise RuntimeError("smoothed mesh lost watertightness — abort export")
    mesh1.export(stl_path)
    obj_path = stl_path.replace(".stl", ".obj")
    try:
        # Indexed mesh (shared verts) — often opens cleaner in SW than raw STL
        mesh1.export(obj_path)
        print(f"  [surfSmooth] OBJ: {obj_path}", flush=True)
    except Exception as exc:
        print(f"  [surfSmooth] OBJ warn: {exc}", flush=True)
        obj_path = ""
    print(f"  [surfSmooth] STL: {stl_path} watertight=True", flush=True)

    step_info: dict[str, Any] | None = None
    if params.write_faceted_step:
        try:
            print("  [surfSmooth] faceted STEP via OCC MakeShapeOnMesh ...", flush=True)
            mesh_for_step = mesh1
            try:
                # Prefer SW-friendly size (~10k faces)
                mesh_for_step = mesh1.simplify_quadric_decimation(face_count=10000)
                import trimesh as _tm

                _tm.grouping.merge_vertices(mesh_for_step, digits_vertex=4)
                mesh_for_step.remove_unreferenced_vertices()
            except Exception as exc:
                print(f"  [surfSmooth] simplify warn (full mesh): {exc}", flush=True)
                mesh_for_step = mesh1
            lite_step = step_path.replace(".step", "_lite.step")
            step_info = mesh_to_faceted_step(mesh_for_step, lite_step)
            if step_info.get("ok"):
                step_path_out = os.path.abspath(lite_step)
                print(
                    f"  [surfSmooth] STEP: {lite_step} "
                    f"mass={step_info.get('mass_mm3'):.3f} "
                    f"MB={step_info.get('step_bytes', 0)/1e6:.2f}",
                    flush=True,
                )
            else:
                step_path_out = None
        except Exception as exc:
            print(f"  [surfSmooth] STEP warn: {exc}", flush=True)
            step_info = {"ok": False, "error": str(exc)}
            step_path_out = None
    else:
        step_path_out = None

    man = {
        "experiment": "surface_smooth_taubin",
        "note": (
            "V3: gmsh-healed watertight surface mesh + mild local Taubin. "
            "V1/V2 used cracked OCC STL and shattered in SW. No Boolean add-ons."
        ),
        "params": asdict(params),
        "bare_step": os.path.abspath(bare_step),
        "stl_path": os.path.abspath(stl_path),
        "obj_path": os.path.abspath(obj_path) if obj_path else None,
        "step_path": step_path_out,
        "fuse": {
            "method": fuse_tag,
            "mass_bare_mm3": float(mass_bare),
            "topology": topo0,
            "attempts": fuse_attempts,
        },
        "mesh": mesh_info,
        "step_export": step_info,
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(f"\n=== SURFACE SMOOTH Q={q:g} ===", flush=True)
    print(f"  STL: {stl_path}", flush=True)
    if step_path_out:
        print(f"  STEP(faceted): {step_path_out}", flush=True)
    print(f"  manifest: {man_path}", flush=True)
    return man
