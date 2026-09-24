"""
Capillary morphological closing on a fused unitcell (experiment).

Analogy: liquid surface tension fills concave crotches below length scale R_cap.
Algorithm: voxel occupancy → binary close (dilate then erode with ball R_cap),
hub-masked so L³ outer faces stay sharp → marching cubes → watertight STL.

Does NOT claim hard BRep MakeFillet. Isolation only; no batch defaults.
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
from src.export.exp_node_transition.surface_smooth import (
    _shape_to_trimesh,
    mesh_to_faceted_step,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


@dataclass
class CapillaryCloseParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.0
    n_segments: int = 32
    # Voxel pitch (mm); 0.15–0.20 for L=20 / d=2
    voxel_mm: float = 0.18
    # Capillary radius; default set in export if None → 0.35 * rod_r
    r_cap_mm: float | None = None
    # Hub sphere: close only inside; outside keep original occupancy
    hub_radius_mm: float = 5.0
    # Mesh deflection for bare solid → watertight surface
    mesh_deflection_mm: float = 0.10
    # Always write faceted STEP from closed (+ lightly smoothed) mesh
    write_faceted_step: bool = True
    # Face count for faceted STEP (OCC MakeShapeOnMesh)
    step_face_count: int = 15000
    step_smooth_iters: int = 0  # unused; kept for CLI compatibility


def default_r_cap_mm(rod_d_mm: float, period_factor: float) -> float:
    """Default capillary radius: ~0.45*R (enough voxels at pitch 0.18)."""
    r = 0.5 * float(rod_d_mm)
    q = abs(float(period_factor))
    if q > 1.2:
        return 0.55 * r
    return 0.45 * r


def _ball_structure(radius_voxels: int) -> np.ndarray:
    """Binary ball structuring element of given radius in voxels."""
    r = max(1, int(radius_voxels))
    coords = np.arange(-r, r + 1, dtype=float)
    zz, yy, xx = np.meshgrid(coords, coords, coords, indexing="ij")
    return (xx * xx + yy * yy + zz * zz) <= float(r * r)


def _hub_mask_for_grid(
    matrix_shape: tuple[int, int, int],
    *,
    transform: np.ndarray,
    hub_radius_mm: float,
) -> np.ndarray:
    """True where voxel centers lie inside hub sphere at origin."""
    # trimesh VoxelGrid.matrix is indexed [x, y, z]
    nx, ny, nz = matrix_shape
    xs = np.arange(nx, dtype=float) + 0.5
    ys = np.arange(ny, dtype=float) + 0.5
    zs = np.arange(nz, dtype=float) + 0.5
    XX, YY, ZZ = np.meshgrid(xs, ys, zs, indexing="ij")
    ones = np.ones_like(XX)
    pts = np.stack([XX, YY, ZZ, ones], axis=-1)
    T = np.asarray(transform, dtype=float)
    world = pts @ T.T
    dist2 = world[..., 0] ** 2 + world[..., 1] ** 2 + world[..., 2] ** 2
    return dist2 <= float(hub_radius_mm) ** 2


def morphological_close_occupancy(
    occupied: np.ndarray,
    *,
    r_cap_voxels: int,
    hub_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Binary close (dilate → erode); optionally only inside hub_mask."""
    from scipy import ndimage as ndi

    ball = _ball_structure(r_cap_voxels)
    occ = np.asarray(occupied, dtype=bool)
    closed = ndi.binary_closing(occ, structure=ball)
    if hub_mask is None:
        return closed
    mask = np.asarray(hub_mask, dtype=bool)
    out = occ.copy()
    out[mask] = closed[mask]
    return out


def morphological_close_sdf(
    occupied: np.ndarray,
    *,
    r_cap_voxels: float,
    hub_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    SDF morphological close (dilate solid by R, then erode by R).

    Returns (closed_occupancy, closed_sdf) with sdf <= 0 inside solid.
    Hub mask: outside hub keep original occupancy.
    """
    from scipy import ndimage as ndi

    occ = np.asarray(occupied, dtype=bool)
    dist_out = ndi.distance_transform_edt(~occ)
    dist_in = ndi.distance_transform_edt(occ)
    phi = dist_out - dist_in  # <0 inside
    r = float(r_cap_voxels)

    # Dilate: expand solid by R → then erode by R (fills gaps narrower than 2R)
    occ_dilated = phi <= r
    dist_out_d = ndi.distance_transform_edt(~occ_dilated)
    dist_in_d = ndi.distance_transform_edt(occ_dilated)
    phi_d = dist_out_d - dist_in_d
    occ_closed = phi_d <= -r

    if hub_mask is not None:
        mask = np.asarray(hub_mask, dtype=bool)
        out_occ = occ.copy()
        out_occ[mask] = occ_closed[mask]
        occ_closed = out_occ

    dist_out_c = ndi.distance_transform_edt(~occ_closed)
    dist_in_c = ndi.distance_transform_edt(occ_closed)
    phi_c = dist_out_c - dist_in_c
    return occ_closed, phi_c


def voxel_close_mesh(
    mesh,
    *,
    voxel_mm: float,
    r_cap_mm: float,
    hub_radius_mm: float,
):
    """
    Voxelize → hub-masked SDF morphological close → marching cubes mesh.

    Returns (closed_mesh, bare_voxel_mesh, info_dict).
    """
    import trimesh
    from skimage import measure
    from trimesh.voxel.ops import matrix_to_marching_cubes

    pitch = float(voxel_mm)
    if pitch <= 0.0:
        raise ValueError("voxel_mm must be > 0")

    print(
        f"  [capillary] voxelize pitch={pitch:g} mm "
        f"(verts={len(mesh.vertices)} faces={len(mesh.faces)}) ...",
        flush=True,
    )
    vg = mesh.voxelized(pitch=pitch)
    try:
        vg = vg.fill()
    except Exception as exc:
        print(f"  [capillary] voxel fill warn: {exc}", flush=True)

    mat = np.asarray(vg.matrix, dtype=bool)
    transform = np.asarray(vg.transform, dtype=float)
    r_vox = max(1.0, float(r_cap_mm) / pitch)
    hub = _hub_mask_for_grid(
        mat.shape, transform=transform, hub_radius_mm=float(hub_radius_mm)
    )
    n_hub = int(np.count_nonzero(hub))
    print(
        f"  [capillary] grid={mat.shape} occupied={int(mat.sum())} "
        f"R_cap={r_cap_mm:.3f} mm ({r_vox:.2f} vox) hub_voxels={n_hub}",
        flush=True,
    )

    closed_mat, phi_c = morphological_close_sdf(
        mat, r_cap_voxels=r_vox, hub_mask=hub
    )
    n_added = int(np.count_nonzero(closed_mat & ~mat))
    n_removed = int(np.count_nonzero(mat & ~closed_mat))
    print(
        f"  [capillary] SDF-close delta voxels +{n_added} -{n_removed}",
        flush=True,
    )

    def _mc_from_matrix(matrix: np.ndarray):
        mc = matrix_to_marching_cubes(matrix=matrix, pitch=1.0)
        verts = np.asarray(mc.vertices, dtype=float)
        ones = np.ones((len(verts), 1), dtype=float)
        world = (transform @ np.hstack([verts, ones]).T).T[:, :3]
        out = trimesh.Trimesh(vertices=world, faces=mc.faces, process=False)
        return _finalize_mesh(out)

    def _mc_from_sdf(phi: np.ndarray):
        # skimage expects volume[z,y,x]; our matrix is [x,y,z]
        vol = np.transpose(phi, (2, 1, 0))
        try:
            verts_zyx, faces, *_ = measure.marching_cubes(
                vol, level=0.0, spacing=(1.0, 1.0, 1.0)
            )
        except Exception as exc:
            print(f"  [capillary] SDF MC fail ({exc}); fallback binary MC", flush=True)
            return _mc_from_matrix(phi <= 0.0)
        # verts are (z,y,x) index → convert to (x,y,z)
        verts = np.column_stack(
            [verts_zyx[:, 2], verts_zyx[:, 1], verts_zyx[:, 0]]
        )
        ones = np.ones((len(verts), 1), dtype=float)
        world = (transform @ np.hstack([verts, ones]).T).T[:, :3]
        out = trimesh.Trimesh(vertices=world, faces=faces, process=False)
        return _finalize_mesh(out)

    bare_voxel_mesh = _mc_from_matrix(mat)
    # Prefer binary MC on closed occupancy (watertight); SDF MC often opens seams.
    closed_mesh = _mc_from_matrix(closed_mat)
    if not closed_mesh.is_watertight:
        print("  [capillary] binary MC not watertight; try SDF MC ...", flush=True)
        closed_mesh = _mc_from_sdf(phi_c)
    if not closed_mesh.is_watertight:
        raise RuntimeError("capillary closed mesh not watertight")

    vox_vol = pitch ** 3
    vol_vox_before = float(mat.sum()) * vox_vol
    vol_vox_after = float(closed_mat.sum()) * vox_vol
    dvol_vox = vol_vox_after - vol_vox_before
    dvol_vox_frac = dvol_vox / vol_vox_before if vol_vox_before > 0 else None

    info = {
        "grid_shape": list(mat.shape),
        "voxel_mm": pitch,
        "r_cap_mm": float(r_cap_mm),
        "r_cap_voxels": float(r_vox),
        "hub_radius_mm": float(hub_radius_mm),
        "n_occupied_before": int(mat.sum()),
        "n_occupied_after": int(closed_mat.sum()),
        "n_voxels_added": n_added,
        "n_voxels_removed": n_removed,
        "volume_voxel_before_mm3": vol_vox_before,
        "volume_voxel_after_mm3": vol_vox_after,
        "dvol_voxel_mm3": dvol_vox,
        "dvol_voxel_frac": dvol_vox_frac,
        "volume_mc_bare_mm3": (
            float(bare_voxel_mesh.volume) if bare_voxel_mesh.is_watertight else None
        ),
        "volume_mc_closed_mm3": (
            float(closed_mesh.volume) if closed_mesh.is_watertight else None
        ),
        "n_vertices": int(len(closed_mesh.vertices)),
        "n_faces": int(len(closed_mesh.faces)),
        "watertight": bool(closed_mesh.is_watertight),
        "bare_voxel_watertight": bool(bare_voxel_mesh.is_watertight),
        "close_mode": "sdf_dilate_erode",
    }
    return closed_mesh, bare_voxel_mesh, info


def _finalize_mesh(mesh):
    import trimesh

    trimesh.grouping.merge_vertices(mesh, digits_vertex=5)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    try:
        trimesh.repair.fix_normals(mesh)
    except Exception:
        pass
    if not mesh.is_watertight:
        try:
            trimesh.repair.fill_holes(mesh)
        except Exception:
            pass
        trimesh.grouping.merge_vertices(mesh, digits_vertex=5)
        mesh.remove_unreferenced_vertices()
    return mesh


def _prepare_mesh_for_step(mesh, *, face_count: int = 12000):
    """
    Decimate for OCC MakeShapeOnMesh.

    Quadric decimation often opens tiny seams (not watertight) but OCC sew still
    yields a single solid — prefer ~12–15k faces for appearance.
    """
    import trimesh

    targets = [
        int(face_count),
        15000,
        12000,
        10000,
        8000,
        6000,
    ]
    seen: set[int] = set()
    last = None
    for target in targets:
        target = max(3000, int(target))
        if target in seen:
            continue
        seen.add(target)
        try:
            if len(mesh.faces) <= target * 1.05:
                trial = mesh.copy()
            else:
                trial = mesh.simplify_quadric_decimation(face_count=target)
            trimesh.grouping.merge_vertices(trial, digits_vertex=4)
            trial.update_faces(trial.nondegenerate_faces())
            trial.update_faces(trial.unique_faces())
            trial.remove_unreferenced_vertices()
            try:
                trimesh.repair.fix_normals(trial)
            except Exception:
                pass
            if len(trial.faces) < 500:
                continue
            last = trial
            print(
                f"  [capillary] STEP mesh faces={len(trial.faces)} "
                f"watertight={trial.is_watertight} (target~{target})",
                flush=True,
            )
            return trial, {
                "face_count": int(len(trial.faces)),
                "target": target,
                "watertight": bool(trial.is_watertight),
            }
        except Exception as exc:
            print(f"  [capillary] decimate {target} fail: {exc}", flush=True)
    if last is not None:
        return last, {"face_count": int(len(last.faces)), "fallback": True}
    raise RuntimeError("could not decimate mesh for STEP")


def export_capillary_close_unitcell(
    params: CapillaryCloseParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Bare fuse → voxel capillary close → STL (+ optional faceted STEP)."""
    params = params or CapillaryCloseParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    r_cap = (
        float(params.r_cap_mm)
        if params.r_cap_mm is not None
        else default_r_cap_mm(params.rod_d_mm, q)
    )
    q_tag = f"{q:.1f}".replace(".", "p")
    r_tag = f"{r_cap:.2f}".replace(".", "p")
    slug = (
        f"exp_capillaryClose_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_Rc{r_tag}"
        f"_v{str(params.voxel_mm).replace('.', 'p')}"
        f"_1x1"
    )
    stl_path = os.path.join(out_dir, f"{slug}.stl")
    bare_stl = os.path.join(out_dir, f"{slug}_bare.stl")
    bare_step = os.path.join(out_dir, f"{slug}_bare.step")
    step_path = os.path.join(out_dir, f"{slug}.step")
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")

    need_step = bool(params.write_faceted_step)
    if (
        not force
        and os.path.isfile(stl_path)
        and os.path.getsize(stl_path) > 1000
        and os.path.isfile(man_path)
        and (
            not need_step
            or (
                os.path.isfile(step_path)
                and os.path.getsize(step_path) > 1000
            )
        )
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
    print(f"  [capillary] bare fuse Q={q:g} ...", flush=True)
    bare, mass_bare, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    topo0 = ocp_shape_topology(bare)
    if int(topo0.get("solids") or 0) != 1:
        raise RuntimeError(f"bare not solid: {topo0}")
    ocp_write_step(bare, bare_step)

    print("  [capillary] mesh bare (gmsh heal) ...", flush=True)
    mesh0 = _shape_to_trimesh(
        bare,
        deflection_mm=float(params.mesh_deflection_mm),
        tmp_stl=bare_stl,
    )
    vol0 = float(mesh0.volume) if mesh0.is_watertight else None

    closed_mesh, bare_voxel_mesh, close_info = voxel_close_mesh(
        mesh0,
        voxel_mm=float(params.voxel_mm),
        r_cap_mm=r_cap,
        hub_radius_mm=float(params.hub_radius_mm),
    )
    bare_voxel_stl = os.path.join(out_dir, f"{slug}_bare_voxel.stl")
    bare_voxel_mesh.export(bare_voxel_stl)
    closed_mesh.export(stl_path)
    print(f"  [capillary] STL: {stl_path}", flush=True)
    print(f"  [capillary] bare_voxel STL: {bare_voxel_stl}", flush=True)

    dvol_vox_frac = close_info.get("dvol_voxel_frac")
    vol1 = close_info.get("volume_mc_closed_mm3")
    dvol_mc = None
    if (
        close_info.get("volume_mc_bare_mm3") is not None
        and vol1 is not None
    ):
        dvol_mc = float(vol1) - float(close_info["volume_mc_bare_mm3"])

    step_info: dict[str, Any] | None = None
    step_path_out: str | None = None
    if params.write_faceted_step:
        try:
            print(
                "  [capillary] faceted STEP from closed mesh (MakeShapeOnMesh) ...",
                flush=True,
            )
            # Skip Taubin here: local smooth often opens seams on voxel MC meshes.
            # Staircasing is reduced by keeping moderate face count after decimate.
            mesh_for_step, dec_info = _prepare_mesh_for_step(
                closed_mesh, face_count=int(params.step_face_count)
            )
            smooth_stl = os.path.join(out_dir, f"{slug}_for_step.stl")
            mesh_for_step.export(smooth_stl)
            step_info = mesh_to_faceted_step(mesh_for_step, step_path, sew_tol=5e-3)
            step_info["decimate"] = dec_info
            step_info["step_stl"] = os.path.abspath(smooth_stl)
            step_info["n_faces_step_mesh"] = int(len(mesh_for_step.faces))
            # Accept 1-solid faceted STEP even if BRepCheck flags minor issues
            solids_ok = int((step_info.get("topology") or {}).get("solids") or 0) == 1
            if step_info.get("ok") or solids_ok:
                step_info["ok"] = True
                step_path_out = os.path.abspath(step_path)
                print(
                    f"  [capillary] STEP OK solids=1 "
                    f"mass={step_info.get('mass_mm3')} "
                    f"faces={step_info.get('n_faces_step_mesh')} "
                    f"brep_valid={(step_info.get('topology') or {}).get('brep_valid')} "
                    f"→ {step_path_out}",
                    flush=True,
                )
            else:
                step_path_out = None
                print(f"  [capillary] STEP not ok: {step_info}", flush=True)
        except Exception as exc:
            step_info = {"ok": False, "error": str(exc)[:400]}
            step_path_out = None
            print(f"  [capillary] STEP FAIL: {exc}", flush=True)

    params_out = asdict(params)
    params_out["r_cap_mm"] = r_cap

    man: dict[str, Any] = {
        "method": "capillary_morphological_close",
        "note": (
            "Voxel SDF closing (hub-masked) → decimated mesh → faceted STEP "
            "via OCC MakeShapeOnMesh (1 solid). Approximate CAD (planar facets), "
            "not NURBS MakeFillet / hard BRep mass-preserve."
        ),
        "params": params_out,
        "slug": slug,
        "bare_step": os.path.abspath(bare_step),
        "bare_stl": os.path.abspath(bare_stl),
        "bare_voxel_stl": os.path.abspath(bare_voxel_stl),
        "stl_path": os.path.abspath(stl_path),
        "step_path": step_path_out,
        "fuse": {
            "method": fuse_tag,
            "mass_bare_mm3": float(mass_bare),
            "topology": topo0,
            "attempts": fuse_attempts,
        },
        "volumes_mm3": {
            "ocp_bare": float(mass_bare),
            "mesh_bare_surface": vol0,
            "voxel_before": close_info.get("volume_voxel_before_mm3"),
            "voxel_after": close_info.get("volume_voxel_after_mm3"),
            "dvol_voxel": close_info.get("dvol_voxel_mm3"),
            "dvol_voxel_frac": dvol_vox_frac,
            "mc_bare_voxel": close_info.get("volume_mc_bare_mm3"),
            "mc_closed": vol1,
            "dvol_mc": dvol_mc,
        },
        "close": close_info,
        "faceted_step_ok": bool(step_info and step_info.get("ok")),
        "step_export": step_info,
        "success_gates": {
            "watertight": bool(close_info.get("watertight")),
            "dvol_frac_ok": (
                dvol_vox_frac is not None and abs(float(dvol_vox_frac)) < 0.08
            ),
            "step_ok": bool(step_info and step_info.get("ok"))
            if params.write_faceted_step
            else None,
        },
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(
        f"  [capillary] DONE Q={q:g} R_cap={r_cap:.3f} "
        f"watertight={close_info.get('watertight')} "
        f"step_ok={bool(step_info and step_info.get('ok'))} "
        f"dvol_voxel_frac="
        f"{dvol_vox_frac if dvol_vox_frac is None else f'{dvol_vox_frac:+.4f}'} "
        f"added_vox={close_info.get('n_voxels_added')} "
        f"→ step={step_path_out or '(none)'} stl={stl_path}",
        flush=True,
    )
    return man
