# -*- coding: utf-8 -*-
"""Cut isolators from existing 4x4x4 paper-box arrays.

Omega = outer square S x two-layer height minus inner cylinder.
Source: output/cad/verified/batch_*_paper_box_array.step

  py -3 scripts/export_isolator_from_444.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.design_domain import (
    make_cylinder_z_extent,
    make_inner_cylinder_liner,
    make_square_minus_cylinder_domain,
    make_square_prism,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape, ocp_translate_shape
from src.export.ocp_unitcell_fuse import (
    ocp_common,
    ocp_cut,
    ocp_fuse_batch,
    ocp_fuse_pair,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)
from src.export.sw_parasolid import (
    count_step_products,
    count_step_solids,
    flatten_step_assembly_to_single_product,
)
from src.paths import CAD_ROOT, CAD_VERIFIED_ROOT, ensure_output_dirs

ensure_output_dirs()


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip() in ("1", "true", "TRUE")


S_MM = 80.0
HOLE_DIAMETER_MM = 25.0
INNER_WALL_MM = 2.0
OUTER_WALL_MM = 0.0

CASES = (
    "af2q0p5_deq2_k2",
    "af2q0p5_deq2_k1",
    "af2q0_deq2_k1",
    "af2q0_deq2_k1p5",
)

# Eight isolators: 4 cases x (L20 single layer | L10 double layer from scaled 444)
JOBS = (
    {"L_mm": 20.0, "nz": 1, "scale_from_l20": False, "tag_suffix": "L20_1layer"},
    {"L_mm": 10.0, "nz": 2, "scale_from_l20": True, "tag_suffix": "L10_2layer"},
)


def _flatten_step_one_sw_window(path: str) -> dict:
    """Collapse extra STEP PRODUCTs so SolidWorks opens one part window."""
    n_p = count_step_products(path)
    n_s = count_step_solids(path)
    if n_p <= 1:
        print(f"  SW one-window OK PRODUCT={n_p} solids={n_s} {path}", flush=True)
        return {
            "step_path": os.path.abspath(path),
            "product_count": n_p,
            "solid_count": n_s,
            "solidworks_safe": True,
            "flattened": False,
        }
    print(
        f"  flatten for 1 SW window: PRODUCT={n_p} solids={n_s} ...",
        flush=True,
    )
    report = flatten_step_assembly_to_single_product(path)
    print(
        f"  after flatten PRODUCT={report.get('product_count')} "
        f"solids={report.get('solid_count')} safe={report.get('solidworks_safe')}",
        flush=True,
    )
    if int(report.get("product_count") or 0) != 1:
        raise RuntimeError(
            f"STEP still has {report.get('product_count')} PRODUCTs "
            f"(SolidWorks would open multiple windows): {path}"
        )
    return report


def _write_step_one_sw_window(shape, path: str) -> dict:
    ocp_write_step(shape, path)
    return _flatten_step_one_sw_window(path)


def flatten_existing_isolator_steps(out_dir: str) -> int:
    """Rewrite already-exported isolator STEPs to a single PRODUCT."""
    needle = os.environ.get("ISOLATOR_FLATTEN_FILTER", "_H20_").strip() or "_H20_"
    names = sorted(
        n
        for n in os.listdir(out_dir)
        if n.startswith("isolator_") and n.endswith(".step") and needle in n
    )
    failed = []
    for name in names:
        path = os.path.join(out_dir, name)
        print(f"\n=== flatten {name} ===", flush=True)
        try:
            _flatten_step_one_sw_window(path)
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc}", flush=True)
            failed.append(name)
    print(f"\nflatten OK {len(names) - len(failed)}/{len(names)}", flush=True)
    return 0 if not failed else 1


def _bbox_mm(shape) -> dict[str, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {
        "xmin": float(xmin),
        "xmax": float(xmax),
        "ymin": float(ymin),
        "ymax": float(ymax),
        "zmin": float(zmin),
        "zmax": float(zmax),
        "dx": float(xmax - xmin),
        "dy": float(ymax - ymin),
        "dz": float(zmax - zmin),
        "cx": 0.5 * float(xmin + xmax),
        "cy": 0.5 * float(ymin + ymax),
        "cz": 0.5 * float(zmin + zmax),
    }


def _read_array_shape(path: str):
    try:
        return ocp_read_step_shape(path)
    except RuntimeError as exc:
        print(f"  [WARN] strict 1-solid read failed ({exc}); OneShape fallback", flush=True)
        from OCP.STEPControl import STEPControl_Reader

        reader = STEPControl_Reader()
        if reader.ReadFile(os.path.abspath(path)) != 1:
            raise RuntimeError(f"OCP STEP read failed: {path}") from exc
        reader.TransferRoots()
        return reader.OneShape()


def _common_fuzzy(a, b, *, fuzzy_mm: float, label: str):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    op = BRepAlgoAPI_Common(a, b)
    if fuzzy_mm > 0.0:
        op.SetFuzzyValue(float(fuzzy_mm))
    op.Build()
    if not op.IsDone():
        raise RuntimeError(f"{label}: Common not done (fuzzy={fuzzy_mm:g})")
    shape = op.Shape()
    if ocp_mass(shape) <= 0.0:
        raise RuntimeError(f"{label}: Common empty (fuzzy={fuzzy_mm:g})")
    return shape


def _cut_fuzzy(a, b, *, fuzzy_mm: float, label: str):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    op = BRepAlgoAPI_Cut(a, b)
    if fuzzy_mm > 0.0:
        op.SetFuzzyValue(float(fuzzy_mm))
    op.Build()
    if not op.IsDone():
        raise RuntimeError(f"{label}: Cut not done (fuzzy={fuzzy_mm:g})")
    shape = op.Shape()
    if ocp_mass(shape) <= 0.0:
        raise RuntimeError(f"{label}: Cut empty (fuzzy={fuzzy_mm:g})")
    return shape


def _clip_array_to_frame(array, *, side_mm: float, height_mm: float, hole_radius_mm: float):
    """Clip to S x H square, then cut inner hole.

    Order is tried both ways: slab-then-hole (usual) and hole-then-slab
    (needed when OCC empties Cut on the already-clipped slab).
    """
    prism = make_square_prism(side_mm, height_mm, z_center=0.0)
    hole_short = make_cylinder_z_extent(hole_radius_mm, height_mm, z_center=0.0)
    hole_tall = make_cylinder_z_extent(
        hole_radius_mm, max(height_mm, 100.0), z_center=0.0, overshoot_mm=2.0
    )
    last_exc: Exception | None = None

    slab = None
    for fuzzy in (0.0, 0.02, 0.05, 0.1):
        try:
            slab = _common_fuzzy(array, prism, fuzzy_mm=fuzzy, label=f"slab-fuzzy{fuzzy:g}")
            print(f"  slab Common fuzzy={fuzzy:g} mass={ocp_mass(slab):.1f} mm3", flush=True)
            break
        except RuntimeError as exc:
            last_exc = exc
            print(f"  [WARN] slab Common fuzzy={fuzzy:g} failed ({exc})", flush=True)
    if slab is None:
        raise RuntimeError(f"square-slab clip failed ({last_exc})") from last_exc

    for fuzzy in (0.0, 0.02, 0.05, 0.1):
        try:
            lattice = _cut_fuzzy(slab, hole_short, fuzzy_mm=fuzzy, label=f"hole-fuzzy{fuzzy:g}")
            print(f"  hole Cut fuzzy={fuzzy:g} mass={ocp_mass(lattice):.1f} mm3", flush=True)
            return lattice
        except RuntimeError as exc:
            last_exc = exc
            print(f"  [WARN] hole Cut on slab fuzzy={fuzzy:g} failed ({exc})", flush=True)

    print("  retry: cut tall hole on full 444, then slab Common...", flush=True)
    pierced = None
    for fuzzy in (0.0, 0.02, 0.05, 0.1, 0.2):
        try:
            pierced = _cut_fuzzy(
                array, hole_tall, fuzzy_mm=fuzzy, label=f"tallhole-fuzzy{fuzzy:g}"
            )
            print(
                f"  tall-hole Cut fuzzy={fuzzy:g} mass={ocp_mass(pierced):.1f} mm3",
                flush=True,
            )
            break
        except RuntimeError as exc:
            last_exc = exc
            print(f"  [WARN] tall-hole Cut fuzzy={fuzzy:g} failed ({exc})", flush=True)
    if pierced is not None:
        for fuzzy in (0.0, 0.02, 0.05, 0.1):
            try:
                lattice = _common_fuzzy(
                    pierced, prism, fuzzy_mm=fuzzy, label=f"pierced-slab-fuzzy{fuzzy:g}"
                )
                print(
                    f"  pierced-slab Common fuzzy={fuzzy:g} mass={ocp_mass(lattice):.1f} mm3",
                    flush=True,
                )
                return lattice
            except RuntimeError as exc:
                last_exc = exc
                print(f"  [WARN] pierced-slab Common fuzzy={fuzzy:g} failed ({exc})", flush=True)

    print("  retry: grow inner hole radius in steps...", flush=True)
    try:
        return _cut_hole_growing(slab, hole_radius_mm=hole_radius_mm, height_mm=height_mm)
    except RuntimeError as exc:
        last_exc = exc
        print(f"  [WARN] grow hole failed ({exc})", flush=True)

    gmsh_lat = _clip_hole_via_gmsh(slab, hole_radius_mm, height_mm)
    if gmsh_lat is not None:
        return gmsh_lat
    raise RuntimeError(f"hole cut failed ({last_exc})") from last_exc


def _cut_hole_growing(slab, *, hole_radius_mm: float, height_mm: float):
    """OCC refuses a large cylinder Cut on some elliptic slabs; grow radius."""
    target = float(hole_radius_mm)
    acc = slab
    # Coarse steps; fall back to 1 mm if a jump empties.
    steps = []
    r = 1.0
    while r < target - 1e-9:
        steps.append(round(r, 6))
        r += 3.0
    if not steps or abs(steps[-1] - target) > 1e-9:
        steps.append(target)
    print(f"  grow hole radii={steps} ...", flush=True)
    i = 0
    while i < len(steps):
        r = steps[i]
        hole = make_cylinder_z_extent(r, height_mm, overshoot_mm=1.0)
        ok = False
        for fuzzy in (0.0, 0.02):
            try:
                nxt = _cut_fuzzy(acc, hole, fuzzy_mm=fuzzy, label=f"grow-r{r:g}")
                print(
                    f"  grow r={r:g} fuzzy={fuzzy:g} mass={ocp_mass(nxt):.1f} "
                    f"(removed {ocp_mass(acc) - ocp_mass(nxt):.1f})",
                    flush=True,
                )
                acc = nxt
                ok = True
                break
            except RuntimeError as exc:
                print(f"  [WARN] grow r={r:g} fuzzy={fuzzy:g} failed ({exc})", flush=True)
        if ok:
            i += 1
            continue
        prev = 0.0 if i == 0 else float(steps[i - 1])
        mid = round(0.5 * (prev + r), 3)
        if mid <= prev + 0.24:
            print(
                f"  grow stuck near r={prev:g}; gmsh finish to r={target:g} ...",
                flush=True,
            )
            gm = _clip_hole_via_gmsh(acc, target, height_mm)
            if gm is not None:
                return gm
            print(
                f"  [WARN] grow stopping at r={prev:g} (target {target:g}); keep partial",
                flush=True,
            )
            return acc
        print(f"  split step: insert r={mid:g} before {r:g}", flush=True)
        steps.insert(i, mid)
    return acc


def _clip_hole_via_gmsh(slab, hole_radius_mm: float, height_mm: float):
    """Last-resort OCC cut in a fresh gmsh session via BREP round-trip."""
    import tempfile

    import gmsh

    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    print("  retry: gmsh OCC cut of inner hole...", flush=True)
    tmp = tempfile.mkdtemp(prefix="isolator_hole_")
    slab_brep = os.path.join(tmp, "slab.brep")
    out_brep = os.path.join(tmp, "cut.brep")
    try:
        BRepTools.Write_s(slab, slab_brep)
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("isolator_hole")
        gmsh.model.occ.importShapes(slab_brep)
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        if not vols:
            print("  [WARN] gmsh imported 0 volumes from slab BREP", flush=True)
            return None
        r = float(hole_radius_mm)
        h = float(height_mm) + 4.0
        z0 = -0.5 * float(height_mm) - 2.0
        cyl = gmsh.model.occ.addCylinder(0, 0, z0, 0, 0, h, r)
        gmsh.model.occ.synchronize()
        gmsh.model.occ.cut(vols, [(3, cyl)])
        gmsh.model.occ.synchronize()
        out_vols = gmsh.model.getEntities(3)
        if not out_vols:
            print("  [WARN] gmsh cut left 0 volumes", flush=True)
            return None
        gmsh.write(out_brep)
        gmsh.finalize()
        shape = TopoDS_Shape()
        builder = BRep_Builder()
        if not BRepTools.Read_s(shape, out_brep, builder):
            print("  [WARN] gmsh cut BREP read failed", flush=True)
            return None
        mass = ocp_mass(shape)
        print(f"  gmsh hole cut mass={mass:.1f} mm3", flush=True)
        if mass <= 0.0:
            return None
        return shape
    except Exception as exc:
        print(f"  [WARN] gmsh hole cut failed ({exc})", flush=True)
        try:
            gmsh.finalize()
        except Exception:
            pass
        return None
    finally:
        for name in ("slab.brep", "cut.brep"):
            try:
                os.remove(os.path.join(tmp, name))
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass


def _make_compound(shapes: list) -> Any:
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for sh in shapes:
        if sh is not None and ocp_mass(sh) > 0.0:
            builder.Add(comp, sh)
    return comp


def _attach_inner_liner(
    lattice,
    *,
    hole_radius_mm: float,
    inner_wall_mm: float,
    height_mm: float,
    side_mm: float,
):
    """
    Clear lattice through radius R+t, then compound a hollow liner (R..R+t).

    Prevents struts from piercing the liner wall (seen in SW when only R was cut).
    """
    r_clear = float(hole_radius_mm) + float(inner_wall_mm)
    solids = _list_solids(lattice)
    if len(solids) > 1:
        print(f"  clear R+t per-solid ({len(solids)} bodies) ...", flush=True)
        cleared = []
        for i, sol in enumerate(solids):
            cleared.append(
                _clear_one_to_r_plus_t(
                    sol,
                    r_clear=r_clear,
                    height_mm=height_mm,
                    label=f"clear-solid{i}",
                )
            )
        core = _make_compound(cleared)
    else:
        core = _clear_one_to_r_plus_t(
            lattice, r_clear=r_clear, height_mm=height_mm, label="clear-R+t"
        )
    core = _fuse_solids_if_many(core, label="clear-fuse")

    liner = make_inner_cylinder_liner(
        hole_radius_mm=hole_radius_mm,
        skin_mm=inner_wall_mm,
        height_mm=height_mm,
        side_mm=side_mm,
    )
    print(
        f"  inner liner t={inner_wall_mm:g} mm vol={ocp_mass(liner):.1f} mm3 "
        "(no outer frame); compound lattice+liner",
        flush=True,
    )
    return _make_compound([core, liner]), liner


def attach_inner_on_existing_lattices(out_dir: str) -> int:
    """Add inner circle liner to already-cut *_lattice.step files (no outer wall)."""
    r_hole = 0.5 * float(HOLE_DIAMETER_MM)
    n_ok = 0
    n_try = 0
    for job in JOBS:
        h = float(job["nz"]) * float(job["L_mm"])
        suffix = str(job["tag_suffix"])
        for case_id in CASES:
            tag = f"{case_id}_S{S_MM:g}_D{HOLE_DIAMETER_MM:g}_H{h:g}_{suffix}"
            src = os.path.join(out_dir, f"isolator_{tag}_lattice.step")
            n_try += 1
            if not os.path.isfile(src):
                print(f"  [SKIP] missing {src}", flush=True)
                continue
            print(f"\n=== inner liner {case_id} {suffix} ===", flush=True)
            lattice = _read_array_shape(src)
            print(f"  lattice mass={ocp_mass(lattice):.1f} mm3", flush=True)
            packed, liner = _attach_inner_liner(
                lattice,
                hole_radius_mm=r_hole,
                inner_wall_mm=INNER_WALL_MM,
                height_mm=h,
                side_mm=S_MM,
            )
            out = os.path.join(out_dir, f"isolator_{tag}_inner.step")
            _write_step_one_sw_window(packed, out)
            topo = ocp_shape_topology(packed, count_faces=False, check_brep=True)
            print(
                f"  solids={topo.get('solids')} mass={topo.get('mass_mm3'):.1f} -> {out}",
                flush=True,
            )
            n_ok += 1
    return 0 if n_ok == n_try and n_try > 0 else 1


def _scale_shape(shape, scale: float, *, center=(0.0, 0.0, 0.0)):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Pnt, gp_Trsf

    cx, cy, cz = map(float, center)
    trsf = gp_Trsf()
    trsf.SetScale(gp_Pnt(cx, cy, cz), float(scale))
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def _xy_aabb_hits_disk(bb: dict[str, float], radius_mm: float) -> bool:
    r = float(radius_mm)
    qx = max(bb["xmin"], min(0.0, bb["xmax"]))
    qy = max(bb["ymin"], min(0.0, bb["ymax"]))
    return (qx * qx + qy * qy) <= (r * r + 1e-6)


def _fuse_solids_if_many(shape, *, label: str):
    solids = _list_solids(shape)
    if len(solids) <= 1:
        return shape
    m0 = ocp_mass(shape)
    try:
        fused = ocp_fuse_batch(solids, fuzzy_mm=0.02, label=label)
        m1 = ocp_mass(fused)
        if m1 < 0.8 * m0:
            print(
                f"  [WARN] {label}: fuse collapsed mass {m0:.1f} -> {m1:.1f}; keep compound",
                flush=True,
            )
            return shape
        print(
            f"  {label}: {len(solids)} bodies -> "
            f"{len(_list_solids(fused))} solid(s) mass={m1:.1f}",
            flush=True,
        )
        return fused
    except Exception as exc:
        print(f"  [WARN] {label} fuse skipped ({exc})", flush=True)
        return shape


def _fuse_mass_ok(m0_a: float, m0_b: float, m1: float) -> bool:
    if m1 <= 0.0:
        return False
    if m1 < 0.85 * max(m0_a, m0_b):
        return False
    if m1 > m0_a + m0_b + 1.0:
        return False
    return True


def _fuse_plug_keep_tiles(lattice, plug, *, label: str):
    """Fuse lattice solids onto the plug. Do not pre-fuse unfused tiles with each other."""
    solids = _list_solids(lattice) or [lattice]
    m_lat = ocp_mass(lattice)
    m_plug = ocp_mass(plug)
    print(
        f"  {label}: lattice solids={len(solids)} mass={m_lat:.1f} "
        f"+ plug mass={m_plug:.1f}",
        flush=True,
    )
    try:
        fused = ocp_fuse_batch(
            [plug] + list(solids), fuzzy_mm=0.02, label=f"{label}-batch"
        )
        m1 = ocp_mass(fused)
        if _fuse_mass_ok(m_lat, m_plug, m1) and m1 >= 0.9 * m_lat:
            nsol = len(_list_solids(fused))
            print(
                f"  {label} batch -> {nsol} solid(s) mass={m1:.1f}",
                flush=True,
            )
            return fused
        print(
            f"  [WARN] {label} batch mass {m1:.1f} rejected; sequential from plug",
            flush=True,
        )
    except Exception as exc:
        print(f"  [WARN] {label} batch ({exc}); sequential from plug", flush=True)

    acc = plug
    for i, sol in enumerate(solids):
        m_acc = ocp_mass(acc)
        m_sol = ocp_mass(sol)
        done = False
        last = ""
        for fuzzy in (0.02, 0.0, 0.05, 0.1):
            try:
                cand = ocp_fuse_pair(
                    acc, sol, fuzzy_mm=fuzzy, label=f"{label}-s{i}"
                )
                m1 = ocp_mass(cand)
                if not _fuse_mass_ok(m_acc, m_sol, m1):
                    last = f"fuzzy={fuzzy:g} mass {m_acc:.1f}+{m_sol:.1f}->{m1:.1f}"
                    continue
                print(
                    f"  {label} solid{i} fuzzy={fuzzy:g} "
                    f"{m_acc:.1f}+{m_sol:.1f}->{m1:.1f}",
                    flush=True,
                )
                acc = cand
                done = True
                break
            except Exception as exc:
                last = str(exc)
        if not done:
            print(
                f"  [WARN] {label} solid{i} keep compound ({last})",
                flush=True,
            )
            acc = _make_compound([acc, sol])
    m1 = ocp_mass(acc)
    if m1 < 0.8 * m_lat:
        raise RuntimeError(
            f"{label}: fused mass {m1:.1f} collapsed vs lattice {m_lat:.1f}"
        )
    print(
        f"  {label} sequential solids={len(_list_solids(acc))} mass={m1:.1f}",
        flush=True,
    )
    return acc


def _cut_center_hole_simple(shape, *, radius_mm: float, height_mm: float, label: str):
    """Cut a filled body with a cylinder. Do not Common-Ω the lattice."""
    import math

    r = float(radius_mm)
    h = float(height_mm)
    m0 = ocp_mass(shape)
    cyl_vol = math.pi * r * r * h
    min_drop = max(50.0, 0.25 * cyl_vol)

    def _accept(out, how: str):
        m1 = ocp_mass(out)
        dropped = m0 - m1
        if m1 <= 0.0:
            raise RuntimeError(f"{how}: empty")
        if dropped < min_drop:
            raise RuntimeError(
                f"{how}: mass drop {dropped:.1f} < {min_drop:.1f} "
                f"({m0:.1f}->{m1:.1f})"
            )
        print(
            f"  {label} {how} mass={m1:.1f} (removed {dropped:.1f})",
            flush=True,
        )
        return out

    hole = make_cylinder_z_extent(r, h, overshoot_mm=2.0, z_center=0.0)
    last: Exception | None = None
    for fuzzy in (0.0, 0.02, 0.05, 0.1):
        try:
            return _accept(
                _cut_fuzzy(
                    shape, hole, fuzzy_mm=fuzzy, label=f"{label}-cut{fuzzy:g}"
                ),
                f"Cut fuzzy={fuzzy:g}",
            )
        except RuntimeError as exc:
            last = exc
            print(f"  [WARN] {label} Cut fuzzy={fuzzy:g} ({exc})", flush=True)
    solids = _list_solids(shape)
    if len(solids) > 1:
        print(f"  {label}: per-solid Cut ({len(solids)} bodies)", flush=True)
        parts = []
        for i, sol in enumerate(solids):
            try:
                parts.append(
                    _cut_fuzzy(sol, hole, fuzzy_mm=0.02, label=f"{label}-ps{i}")
                )
            except RuntimeError:
                parts.append(sol)
        out = _make_compound(parts)
        try:
            return _accept(out, "per-solid Cut")
        except RuntimeError as exc:
            last = exc
            print(f"  [WARN] {label} per-solid ({exc})", flush=True)
    for ns in (24, 16):
        try:
            facet = _make_faceted_z_cylinder(r, h, n_sides=ns, overshoot_mm=2.0)
            return _accept(
                _cut_fuzzy(shape, facet, fuzzy_mm=0.0, label=f"{label}-facet{ns}"),
                f"faceted n={ns}",
            )
        except RuntimeError as exc:
            last = exc
            print(f"  [WARN] {label} facet n={ns} ({exc})", flush=True)
    raise RuntimeError(f"{label}: cannot drill R={r:g} ({last})")


def _plug_then_drill(
    lattice,
    *,
    hole_radius_mm: float,
    inner_wall_mm: float,
    height_mm: float,
):
    """Lattice + solid OD plug, fuse, then drill ID hole."""
    r_hole = float(hole_radius_mm)
    r_plug = r_hole + float(inner_wall_mm)
    h = float(height_mm)
    plug = make_cylinder_z_extent(r_plug, h, overshoot_mm=0.0, z_center=0.0)
    print(
        f"  plug-then-drill: OD={2.0 * r_plug:g} ID={2.0 * r_hole:g} H={h:g} "
        f"plug_mass={ocp_mass(plug):.1f}",
        flush=True,
    )
    fused = _fuse_plug_keep_tiles(lattice, plug, label="plug-fuse")
    drilled = _cut_center_hole_simple(
        fused, radius_mm=r_hole, height_mm=h, label="plug-drill"
    )
    return drilled, plug


def _quadrant_cylinder(radius_mm: float, height_mm: float, dx: float, dy: float):
    """Cylinder clipped to the tile quadrant so OCC does not empty elliptic cuts."""
    cyl = make_cylinder_z_extent(
        float(radius_mm), float(height_mm), overshoot_mm=1.0, z_center=0.0
    )
    cx = 40.0 if float(dx) >= 0.0 else -40.0
    cy = 40.0 if float(dy) >= 0.0 else -40.0
    box = make_square_prism(
        82.0, float(height_mm) + 4.0, center_xy=(cx, cy), z_center=0.0
    )
    return _common_fuzzy(cyl, box, fuzzy_mm=0.0, label=f"quad-cyl-{dx:g}-{dy:g}")


def _make_faceted_z_cylinder(
    radius_mm: float,
    height_mm: float,
    *,
    n_sides: int = 24,
    z_center: float = 0.0,
    overshoot_mm: float = 1.0,
):
    import math

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakePolygon,
    )
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec

    r = float(radius_mm)
    h = float(height_mm) + 2.0 * max(0.0, float(overshoot_mm))
    z0 = float(z_center) - 0.5 * float(height_mm) - max(0.0, float(overshoot_mm))
    poly = BRepBuilderAPI_MakePolygon()
    ns = max(8, int(n_sides))
    for i in range(ns):
        ang = 2.0 * math.pi * i / ns
        poly.Add(gp_Pnt(r * math.cos(ang), r * math.sin(ang), z0))
    poly.Close()
    face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, 0.0, h)).Shape()


def _punch_radius(shape, *, radius_mm: float, height_mm: float, label: str):
    """Cut a cylinder at the origin. Never keep struts inside the hole."""
    r = float(radius_mm)
    h = float(height_mm)
    if not _xy_aabb_hits_disk(_bbox_mm(shape), r):
        print(f"  {label}: no overlap with R={r:g}; keep", flush=True)
        return shape
    m0 = ocp_mass(shape)
    min_drop = max(5.0, 0.002 * m0)

    def _accept(out, how: str):
        m1 = ocp_mass(out)
        dropped = m0 - m1
        if m1 <= 0.0:
            raise RuntimeError(f"{how}: empty")
        if dropped < min_drop:
            raise RuntimeError(
                f"{how}: mass unchanged ({m0:.1f}->{m1:.1f}, drop={dropped:.2f})"
            )
        print(f"  {label} {how} mass={m1:.1f} (removed {dropped:.1f})", flush=True)
        return out

    # Common with Ω = square − cylinder. Cut often returns the original (0 drop).
    try:
        domain, _ = make_square_minus_cylinder_domain(
            side_mm=160.0,
            height_mm=h + 4.0,
            hole_radius_mm=r,
            z_center=0.0,
            overshoot_mm=1.0,
        )
        for fuzzy in (0.0, 0.02, 0.05, 0.1):
            try:
                return _accept(
                    _common_fuzzy(
                        shape, domain, fuzzy_mm=fuzzy, label=f"{label}-omega{fuzzy:g}"
                    ),
                    f"Common-Ω fuzzy={fuzzy:g}",
                )
            except RuntimeError as exc:
                print(f"  [WARN] {label} Ω fuzzy={fuzzy:g} ({exc})", flush=True)
    except Exception as exc:
        print(f"  [WARN] {label} Ω domain failed ({exc})", flush=True)

    def _omega_square(radius: float):
        outer = make_square_prism(160.0, h + 4.0, z_center=0.0)
        inner = make_square_prism(2.0 * float(radius), h + 4.0, z_center=0.0)
        return _cut_fuzzy(outer, inner, fuzzy_mm=0.0, label=f"{label}-sq-omega-tool")

    def _try_square_omega(src, how: str):
        tool = _omega_square(r)
        for fuzzy in (0.0, 0.02, 0.05, 0.1):
            try:
                return _accept(
                    _common_fuzzy(
                        src, tool, fuzzy_mm=fuzzy, label=f"{label}-sqomega{fuzzy:g}"
                    ),
                    f"{how} square-Ω fuzzy={fuzzy:g}",
                )
            except RuntimeError as exc:
                print(f"  [WARN] {label} {how} sq-Ω fuzzy={fuzzy:g} ({exc})", flush=True)
        return None

    sq = _try_square_omega(shape, "pre")
    if sq is not None:
        return sq

    hole = make_cylinder_z_extent(r, h, overshoot_mm=1.0, z_center=0.0)
    for fuzzy in (0.0, 0.02, 0.05, 0.1):
        try:
            return _accept(
                _cut_fuzzy(
                    shape, hole, fuzzy_mm=fuzzy, label=f"{label}-fuzzy{fuzzy:g}"
                ),
                f"R={r:g} fuzzy={fuzzy:g}",
            )
        except RuntimeError as exc:
            print(f"  [WARN] {label} fuzzy={fuzzy:g} ({exc})", flush=True)
    for ns in (24, 16, 8):
        try:
            facet = _make_faceted_z_cylinder(r, h, n_sides=ns)
            return _accept(
                _cut_fuzzy(shape, facet, fuzzy_mm=0.0, label=f"{label}-facet{ns}"),
                f"faceted n={ns}",
            )
        except RuntimeError as exc:
            print(f"  [WARN] {label} facet n={ns} ({exc})", flush=True)
    print(f"  {label}: gmsh cylinder cut R={r:g} ...", flush=True)
    gm = _clip_hole_via_gmsh(shape, r, h)
    if gm is not None:
        try:
            return _accept(gm, "gmsh")
        except RuntimeError as exc:
            print(f"  [WARN] {label} gmsh ({exc})", flush=True)
    try:
        grown = _cut_hole_growing(shape, hole_radius_mm=r, height_mm=h)
        print(
            f"  {label} grow result mass={ocp_mass(grown):.1f}; enlarge to R={r:g}",
            flush=True,
        )
        sq2 = _try_square_omega(grown, "post-grow")
        if sq2 is not None:
            return sq2
        square = make_square_prism(2.0 * r, h + 2.0, z_center=0.0)
        try:
            return _accept(
                _cut_fuzzy(grown, square, fuzzy_mm=0.0, label=f"{label}-square-grown"),
                f"square-on-grown half={r:g}",
            )
        except RuntimeError as exc:
            print(f"  [WARN] {label} square-on-grown ({exc})", flush=True)
    except RuntimeError as exc:
        print(f"  [WARN] {label} grow failed ({exc}); square clearance", flush=True)
    square = make_square_prism(2.0 * r, h + 2.0, z_center=0.0)
    try:
        return _accept(
            _cut_fuzzy(shape, square, fuzzy_mm=0.0, label=f"{label}-square"),
            f"square half={r:g}",
        )
    except RuntimeError as exc:
        raise RuntimeError(f"{label}: cannot punch R={r:g}") from exc


def _cut_hole_keep_if_miss(shape, *, hole_radius_mm: float, height_mm: float, label: str):
    return _punch_radius(
        shape, radius_mm=float(hole_radius_mm), height_mm=height_mm, label=label
    )


def _clear_one_to_r_plus_t(shape, *, r_clear: float, height_mm: float, label: str):
    return _punch_radius(
        shape, radius_mm=float(r_clear), height_mm=height_mm, label=label
    )


def _prepare_array_l20(array, *, L_src: float = 20.0):
    """
    4x4x4 seed is anchored at cell (0,0,0): centres 0,20,40,60 mm.

    Shift only XY by -30 so the 80 mm square is centred. Do not shift Z:
    iz=0 is already a complete L=20 layer at z=0. Shifting Z by -30 put the
    H=20 slab across two half-layers and left only a few intact cells.
    """
    grid_c = 0.5 * (4 - 1) * float(L_src)
    shifted = ocp_translate_shape(array, -grid_c, -grid_c, 0.0)
    return shifted, grid_c


def _list_solids(shape) -> list:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    solids = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids.append(TopoDS.Solid_s(exp.Current()))
        exp.Next()
    return solids


def _prepare_array_l10_from_l20(array, *, height_mm: float, hole_radius_mm: float):
    """
    Scale L=20 4x4x4 by 1/2, keep two complete L=10 layers, tile 2x2 in XY.

    After XY-centre and 0.5 scale, layer iz=0 is at z=0 and iz=1 at z=10.
    Shift Z by -5 mm so those two complete cells span H=20 at z=0.
    """
    centered, grid_c = _prepare_array_l20(array, L_src=20.0)
    scaled = _scale_shape(centered, 0.5, center=(0.0, 0.0, 0.0))
    two_layer = ocp_translate_shape(scaled, 0.0, 0.0, -5.0)
    z_prism = make_square_prism(120.0, float(height_mm), z_center=0.0)
    slab = None
    for fuzzy in (0.0, 0.02, 0.05):
        try:
            slab = _common_fuzzy(
                two_layer, z_prism, fuzzy_mm=fuzzy, label=f"l10-zclip-fuzzy{fuzzy:g}"
            )
            print(
                f"  L10 two complete layers H={height_mm:g} fuzzy={fuzzy:g} "
                f"mass={ocp_mass(slab):.1f} mm3",
                flush=True,
            )
            break
        except RuntimeError as exc:
            print(f"  [WARN] L10 z-clip fuzzy={fuzzy:g} failed ({exc})", flush=True)
    if slab is None:
        raise RuntimeError("L10 z-clip failed")
    bb_s = _bbox_mm(slab)
    print(
        f"  L10 slab bbox dx={bb_s['dx']:.1f} dy={bb_s['dy']:.1f} "
        f"dz={bb_s['dz']:.1f} z=[{bb_s['zmin']:.2f},{bb_s['zmax']:.2f}]",
        flush=True,
    )

    parts = []
    for dx, dy in ((20.0, 20.0), (20.0, -20.0), (-20.0, 20.0), (-20.0, -20.0)):
        tile = ocp_translate_shape(slab, dx, dy, 0.0)
        m = ocp_mass(tile)
        print(f"  tile dx={dx:g} dy={dy:g} mass={m:.1f} mm3", flush=True)
        if m > 0.0:
            parts.append(tile)

    if not parts:
        raise RuntimeError("L10 tiling produced no lattice")
    packed = parts[0] if len(parts) == 1 else _make_compound(parts)
    no_hole = _env_flag("ISOLATOR_NO_HOLE")
    plug_drill = _env_flag("ISOLATOR_PLUG_THEN_DRILL")
    if no_hole or plug_drill:
        print(
            "  skip hole punch in tiling "
            f"(no_hole={no_hole} plug_then_drill={plug_drill}); keep complete array",
            flush=True,
        )
    else:
        print(
            f"  punch packed {len(parts)}-tile compound ...",
            flush=True,
        )
        try:
            packed = _punch_radius(
                packed,
                radius_mm=float(hole_radius_mm),
                height_mm=float(height_mm),
                label="l10-packed-hole",
            )
        except RuntimeError as exc:
            print(f"  [WARN] packed punch failed ({exc}); clip-to-frame hole ...", flush=True)
            packed = _clip_array_to_frame(
                packed,
                side_mm=S_MM,
                height_mm=float(height_mm),
                hole_radius_mm=float(hole_radius_mm),
            )
    if not plug_drill:
        packed = _fuse_solids_if_many(packed, label="l10-tile-fuse")
    bb = _bbox_mm(packed)
    print(
        f"  L10 tiled {len(parts)} complete-cell part(s); bbox "
        f"dx={bb['dx']:.1f} dy={bb['dy']:.1f} dz={bb['dz']:.1f} "
        f"mass={ocp_mass(packed):.1f}",
        flush=True,
    )
    if ocp_mass(packed) < 500.0:
        raise RuntimeError(
            f"L10 lattice mass {ocp_mass(packed):.1f} mm3 too small (geometry collapsed)"
        )
    return packed, grid_c


def cut_one(
    case_id: str,
    out_dir: str,
    *,
    L_mm: float,
    nz: int,
    scale_from_l20: bool,
    tag_suffix: str,
) -> dict:
    src = os.path.join(str(CAD_VERIFIED_ROOT), f"batch_{case_id}_paper_box_array.step")
    if not os.path.isfile(src):
        raise FileNotFoundError(src)

    r_hole = 0.5 * float(HOLE_DIAMETER_MM)
    h = float(nz) * float(L_mm)
    t0 = time.perf_counter()
    tag = f"{case_id}_S{S_MM:g}_D{HOLE_DIAMETER_MM:g}_H{h:g}_{tag_suffix}"
    no_hole = _env_flag("ISOLATOR_NO_HOLE")
    plug_drill = _env_flag("ISOLATOR_PLUG_THEN_DRILL")
    inner_step = os.path.join(out_dir, f"isolator_{tag}_inner.step")
    force = _env_flag("ISOLATOR_FORCE")
    if (
        not force
        and not no_hole
        and not plug_drill
        and INNER_WALL_MM > 0.0
        and os.path.isfile(inner_step)
        and os.path.getsize(inner_step) > 10000
    ):
        print(f"\n=== skip existing {tag} (flatten SW window) ===", flush=True)
        sw = _flatten_step_one_sw_window(inner_step)
        lattice_step = os.path.join(out_dir, f"isolator_{tag}_lattice.step")
        if os.path.isfile(lattice_step):
            _flatten_step_one_sw_window(lattice_step)
        return {
            "case_id": case_id,
            "tag_suffix": tag_suffix,
            "ok": True,
            "skipped": True,
            "inner_step": os.path.abspath(inner_step),
            "sw_product_count": sw.get("product_count"),
            "H_mm": h,
            "L_mm": float(L_mm),
        }

    print(f"\n=== {case_id} {tag_suffix} L={L_mm:g} nz={nz} H={h:g} ===", flush=True)
    print(f"  source {src} ({os.path.getsize(src) / 1e6:.2f} MB)", flush=True)

    array = _read_array_shape(src)
    topo0 = ocp_shape_topology(array, count_faces=False, check_brep=False)
    bb0 = _bbox_mm(array)
    print(
        f"  444 solids={topo0.get('solids')} mass={topo0.get('mass_mm3'):.1f} "
        f"bbox dx={bb0['dx']:.2f} dy={bb0['dy']:.2f} dz={bb0['dz']:.2f}",
        flush=True,
    )
    if scale_from_l20:
        lattice, grid_c = _prepare_array_l10_from_l20(
            array, height_mm=h, hole_radius_mm=r_hole
        )
    else:
        array, grid_c = _prepare_array_l20(array, L_src=float(L_mm))
        bb = _bbox_mm(array)
        print(
            f"  XY-centre -{grid_c:g} mm (Z unchanged for complete iz=0 layer); "
            f"bbox x=[{bb['xmin']:.2f},{bb['xmax']:.2f}] "
            f"z=[{bb['zmin']:.2f},{bb['zmax']:.2f}]",
            flush=True,
        )
        print(
            f"  clip S={S_MM:g} H={h:g} D_hole={HOLE_DIAMETER_MM:g} ...",
            flush=True,
        )
        lattice = _clip_array_to_frame(
            array, side_mm=S_MM, height_mm=h, hole_radius_mm=r_hole
        )
    topo_l = ocp_shape_topology(lattice, count_faces=True, check_brep=True)
    mass_l = float(topo_l.get("mass_mm3") or 0.0)
    if mass_l <= 0.0:
        raise RuntimeError(f"{case_id}/{tag_suffix}: clipped lattice empty")
    print(
        f"  lattice solids={topo_l.get('solids')} mass={mass_l:.1f} "
        f"faces={topo_l.get('faces')} brep={topo_l.get('brep_valid')} "
        f"bbox dx={_bbox_mm(lattice)['dx']:.1f} dy={_bbox_mm(lattice)['dy']:.1f} "
        f"dz={_bbox_mm(lattice)['dz']:.1f}",
        flush=True,
    )

    out_name = (
        f"isolator_{tag}_array.step"
        if (no_hole or plug_drill)
        else f"isolator_{tag}_lattice.step"
    )
    lattice_step = os.path.join(out_dir, out_name)
    if (
        plug_drill
        and os.path.isfile(lattice_step)
        and os.path.getsize(lattice_step) > 10_000_000
    ):
        print(f"  reuse uncut array {lattice_step}", flush=True)
    else:
        _write_step_one_sw_window(lattice, lattice_step)

    domain, domain_meta = make_square_minus_cylinder_domain(
        side_mm=S_MM,
        height_mm=h,
        hole_radius_mm=r_hole,
        z_center=0.0,
    )
    domain_step = os.path.join(
        out_dir, f"isolator_domain_S{S_MM:g}_D{HOLE_DIAMETER_MM:g}_H{h:g}.step"
    )
    if not os.path.isfile(domain_step):
        _write_step_one_sw_window(domain, domain_step)

    report = {
        "case_id": case_id,
        "tag_suffix": tag_suffix,
        "source_444": os.path.abspath(src),
        "S_mm": S_MM,
        "hole_diameter_mm": HOLE_DIAMETER_MM,
        "H_mm": h,
        "L_mm": float(L_mm),
        "nz_layers": int(nz),
        "scale_from_l20": bool(scale_from_l20),
        "inner_wall_mm": INNER_WALL_MM,
        "outer_wall_mm": OUTER_WALL_MM,
        "source_topo": topo0,
        "source_bbox_mm": bb0,
        "domain_meta": domain_meta,
        "lattice_step": os.path.abspath(lattice_step),
        "lattice_topo": topo_l,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "ok": mass_l > 0.0 and int(topo_l.get("solids") or 0) >= 1,
    }
    if plug_drill and not no_hole:
        packed, plug = _plug_then_drill(
            lattice,
            hole_radius_mm=r_hole,
            inner_wall_mm=INNER_WALL_MM,
            height_mm=h,
        )
        _write_step_one_sw_window(packed, inner_step)
        topo_i = ocp_shape_topology(packed, count_faces=False, check_brep=True)
        print(
            f"  inner solids={topo_i.get('solids')} mass={topo_i.get('mass_mm3'):.1f} "
            f"-> {inner_step}",
            flush=True,
        )
        report["inner_step"] = os.path.abspath(inner_step)
        report["inner_topo"] = topo_i
        report["pipeline"] = "plug_then_drill"
        report["plug_mass_mm3"] = ocp_mass(plug)
    elif INNER_WALL_MM > 0.0 and not no_hole:
        packed, liner = _attach_inner_liner(
            lattice,
            hole_radius_mm=r_hole,
            inner_wall_mm=INNER_WALL_MM,
            height_mm=h,
            side_mm=S_MM,
        )
        _write_step_one_sw_window(packed, inner_step)
        topo_i = ocp_shape_topology(packed, count_faces=False, check_brep=True)
        print(
            f"  inner solids={topo_i.get('solids')} mass={topo_i.get('mass_mm3'):.1f} "
            f"-> {inner_step}",
            flush=True,
        )
        report["inner_step"] = os.path.abspath(inner_step)
        report["inner_topo"] = topo_i
        report["inner_liner_mass_mm3"] = ocp_mass(liner)
    print(f"  done in {report['elapsed_s']} s", flush=True)
    return report


def main() -> int:
    out_dir = os.path.join(str(CAD_ROOT), "_isolator_from_444")
    os.makedirs(out_dir, exist_ok=True)
    if os.environ.get("ISOLATOR_FLATTEN_ONLY", "").strip() in ("1", "true", "TRUE"):
        print(f"flatten isolator STEPs to 1 SolidWorks window -> {out_dir}", flush=True)
        return flatten_existing_isolator_steps(out_dir)
    if os.environ.get("ISOLATOR_INNER_ONLY", "").strip() in ("1", "true", "TRUE"):
        print(
            f"attach inner liner only (no outer wall) t={INNER_WALL_MM:g} mm -> {out_dir}",
            flush=True,
        )
        return attach_inner_on_existing_lattices(out_dir)
    only = os.environ.get("ISOLATOR_ONLY_JOB", "").strip()
    jobs = [j for j in JOBS if not only or str(j["tag_suffix"]) == only]
    if only and not jobs:
        print(f"[FAIL] unknown ISOLATOR_ONLY_JOB={only!r}", flush=True)
        return 2
    only_cases_raw = os.environ.get("ISOLATOR_ONLY_CASES", "").strip()
    if only_cases_raw:
        wanted = [c.strip() for c in only_cases_raw.split(",") if c.strip()]
        cases = [c for c in CASES if c in wanted]
        unknown = [c for c in wanted if c not in CASES]
        if unknown:
            print(f"[FAIL] unknown ISOLATOR_ONLY_CASES={unknown!r}", flush=True)
            return 2
        if not cases:
            print(f"[FAIL] empty ISOLATOR_ONLY_CASES={only_cases_raw!r}", flush=True)
            return 2
    else:
        cases = list(CASES)
    print(
        f"isolator-from-444: S={S_MM:g} D_hole={HOLE_DIAMETER_MM:g} "
        f"jobs={len(jobs)} x cases={len(cases)} -> {out_dir}",
        flush=True,
    )
    reports = []
    failed = []
    for job in jobs:
        for case_id in cases:
            try:
                reports.append(
                    cut_one(
                        case_id,
                        out_dir,
                        L_mm=float(job["L_mm"]),
                        nz=int(job["nz"]),
                        scale_from_l20=bool(job["scale_from_l20"]),
                        tag_suffix=str(job["tag_suffix"]),
                    )
                )
            except Exception as exc:
                print(f"  [FAIL] {case_id}/{job['tag_suffix']}: {exc}", flush=True)
                failed.append(
                    {
                        "case_id": case_id,
                        "tag_suffix": job["tag_suffix"],
                        "error": str(exc),
                    }
                )
                reports.append(
                    {
                        "case_id": case_id,
                        "tag_suffix": job["tag_suffix"],
                        "ok": False,
                        "error": str(exc),
                    }
                )
    if only_cases_raw:
        man_name = "manifest_H20_L10_k2_k1p5.json"
    elif only == "L10_2layer":
        man_name = "manifest_H20_L10.json"
    else:
        man_name = "manifest_H20.json"
    man = os.path.join(out_dir, man_name)
    with open(man, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "out_dir": os.path.abspath(out_dir),
                "S_mm": S_MM,
                "hole_diameter_mm": HOLE_DIAMETER_MM,
                "H_mm": 20.0,
                "jobs": list(jobs),
                "cases": cases,
                "reports": reports,
                "failed": failed,
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )
        fh.write("\n")
    print(f"\nManifest: {man}", flush=True)
    n_ok = sum(1 for r in reports if r.get("ok"))
    n_tot = len(cases) * len(jobs)
    print(f"OK {n_ok}/{n_tot}", flush=True)
    return 0 if n_ok == n_tot else 1


if __name__ == "__main__":
    raise SystemExit(main())
