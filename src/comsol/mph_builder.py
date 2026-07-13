"""Build Hu & Bai COMSOL vibration-isolation models from STEP (MPh + API)."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jpype

from src.comsol.eigen_extract import extract_eigen_rows, rank_modes_by_meff, resolve_eigen_dataset
from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.tpu_material import (
    assign_lattice_marlow_material,
    configure_lattice_eigen_linearized_physics,
    configure_lattice_hyperelastic_physics,
)
from src.comsol.runner import resolve_comsol_bin
from src.paths import COMSOL_BATCH_PREFS_DIR

if TYPE_CHECKING:
    import mph


def _ensure_comsol_env(comsol_bin: str | None = None) -> str:
    bin_path = resolve_comsol_bin(comsol_bin)
    comsol_root = Path(bin_path).resolve().parent.parent
    bin_dir = str(comsol_root / "bin")
    os.environ["COMSOL_BIN"] = bin_path
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    if COMSOL_BATCH_PREFS_DIR.is_dir():
        os.environ["COMSOLPREFS"] = str(COMSOL_BATCH_PREFS_DIR.resolve())
    return bin_path


def _import_mph() -> Any:
    try:
        import mph  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "MPh is required for COMSOL Python build. Install: pip install mph"
        ) from exc
    return mph


LATTICE_GEOM = "geom_lat"
LATTICE_MESH = "mesh_lat"

# COMSOL GUI display labels (tags stay ASCII for API stability)
LABEL_COMP_MAIN = "Fig2.8隔振组件"
LABEL_COMP_FIXTURE = "临时工装组件"
LABEL_GEOM = "几何"
LABEL_MESH = "网格"
LABEL_GEOM_LATTICE_STEP = "点阵CAD导入"
LABEL_GEOM_TABLE = "振动台（AISI4340钢）"
LABEL_GEOM_PLATE = "上铝合金板"
LABEL_GEOM_ASSEMBLY = "形成装配体"
LABEL_MAT_LATTICE = "TPU点阵（Marlow超弹性）"
LABEL_MAT_TABLE = "振动台钢（AISI4340）"
LABEL_MAT_PLATE = "铝合金上板"
LABEL_PHYSICS_SOLID = "固体力学"
LABEL_STUDY_FREQ = "频域谐响应"
LABEL_STUDY_EIGEN = "本征频率"
LABEL_MESH_COPY_TABLE = "振动台网格（常规 hauto=5）"
LABEL_MESH_COPY_PLATE = "上板网格（常规 hauto=5）"
LABEL_MESH_SIZE_LAT = "点阵单元大小（细化 hauto=4）"
LABEL_MESH_FTET_LAT = "点阵自由四面体网格"
LABEL_MESH_SIZE_TABLE = "大小 振动台（常规 hauto=5）"
LABEL_MESH_SIZE_PLATE = "大小 上板（薄板适配）"
LABEL_MESH_FTET_TABLE = "自由四面体 振动台"
LABEL_MESH_FTET_PLATE = "自由四面体 上板"


def _set_label(obj: Any, label: str) -> None:
    try:
        obj.label(label)
    except Exception:
        pass


def _label_mesh_feature(mesh: Any, tag: str, label: str) -> None:
    try:
        _set_label(mesh.feature(tag), label)
    except Exception:
        pass


def _ensure_geom1(comp: Any, *, dimension: int = 3) -> Any:
    """Return the primary 3D geometry sequence for a component."""
    tags = [str(t) for t in comp.geom().tags()]
    if "geom1" in tags:
        geom = comp.geom("geom1")
    elif tags:
        geom = comp.geom(tags[0])
    else:
        try:
            comp.geom().create("geom1", dimension)
            geom = comp.geom("geom1")
        except Exception as exc:
            msg = str(exc)
            if "already exists" not in msg and "已存在" not in msg:
                raise
            try:
                comp.geom().remove("geom1")
            except Exception:
                pass
            comp.geom().create("geom1", dimension)
            geom = comp.geom("geom1")
    geom.lengthUnit("mm")
    return geom


def _ensure_lattice_geom(comp: Any, *, dimension: int = 3) -> str:
    """Dedicated geometry tag for comp1 (avoids phantom default geom1 on new components)."""
    comp.geom().create(LATTICE_GEOM, dimension)
    geom = comp.geom(LATTICE_GEOM)
    geom.lengthUnit("mm")
    return LATTICE_GEOM


def _reset_comp1(java: Any) -> Any:
    """Fresh comp1 for lattice STEP import (avoid stale geom from partial builds)."""
    tags = [str(t) for t in java.component().tags()]
    if "comp1" in tags:
        java.component().remove("comp1")
    java.component().create("comp1", True)
    return java.component("comp1")


def _step_bbox_mm(
    step_path: str | Path,
) -> tuple[float, float, float, float, float, float] | None:
    """Axis-aligned STEP bbox (xmin, ymin, zmin, xmax, ymax, zmax) in mm."""
    path = Path(step_path).resolve()
    if not path.is_file():
        return None
    try:
        import gmsh

        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("bbox_probe")
        gmsh.model.occ.importShapes(str(path))
        gmsh.model.occ.synchronize()
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        gmsh.finalize()
        return (xmin, ymin, zmin, xmax, ymax, zmax)
    except Exception as exc:
        print(f"  WARN: STEP bbox probe failed ({exc})", flush=True)
        return None


def _step_bbox_center_mm(step_path: str | Path) -> tuple[float, float, float] | None:
    """Axis-aligned bbox center of a STEP file [mm] (gmsh OCC probe)."""
    bbox = _step_bbox_mm(step_path)
    if bbox is None:
        return None
    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    return (
        0.5 * (xmin + xmax),
        0.5 * (ymin + ymax),
        0.5 * (zmin + zmax),
    )


def _plate_z_bottom_mm(settings: HuBaiComsolSettings) -> float:
    """Resolved lattice-top / plate-bottom Z [mm] (set during build)."""
    raw = settings.extra.get("plate_z_bottom_mm")
    if raw is not None:
        return float(raw)
    return settings.z_max_mm


def _resolve_plate_z_bottom_mm(
    settings: HuBaiComsolSettings,
    *,
    comp: Any | None = None,
    geom_tag: str = "geom1",
) -> float:
    """Snap plate bottom to lattice top for imprint bonding.

    Use the nominal §2.4.3 plane (``z_max_mm``) when the lattice meets or exceeds
    design height.  Curved SFBLS struts can protrude slightly above nominal in
    bbox probes; raising the plate to that peak leaves a gap and ``fin`` omits
    identity pair ``ap2``.  Only lower the plate when the lattice is shorter
    than nominal.
    """
    nominal = settings.z_max_mm
    z_geom: float | None = None
    if comp is not None:
        z_geom = _geom_lattice_z_top_mm(comp, geom_tag)

    z_step: float | None = None
    if settings.step_path:
        bbox = _step_bbox_mm(settings.step_path)
        center = _step_bbox_center_mm(settings.step_path)
        if bbox is not None and center is not None:
            z_step = bbox[5] - center[2]

    if z_geom is not None:
        z_measured = z_geom
        source = "geom_bbox"
    elif z_step is not None:
        z_measured = z_step
        source = "step_bbox"
    else:
        return nominal

    if z_measured < nominal - 0.05:
        print(
            f"  Plate z snap ({source}): nominal {nominal:g} → lattice top {z_measured:g} mm",
            flush=True,
        )
        return z_measured

    if z_measured > nominal + 0.05:
        print(
            f"  Plate z clamp ({source}): measured top {z_measured:g} mm "
            f"> nominal {nominal:g} mm — keep plate on design plane for imprint bond",
            flush=True,
        )
    elif z_geom is not None and z_step is not None and abs(z_geom - z_step) > 0.1:
        print(
            f"  WARN: lattice z_top geom={z_geom:g} mm vs STEP={z_step:g} mm",
            flush=True,
        )
    return nominal


def _geom_lattice_z_top_mm(comp: Any, geom_tag: str) -> float | None:
    """Top Z of current geometry sequence (lattice only, before table/plate blocks)."""
    try:
        g = comp.geom(geom_tag)
        bb = g.getBoundingBox()
        if hasattr(bb, "tolist"):
            vals = [float(v) for v in bb.tolist()]
        else:
            vals = [float(bb[i]) for i in range(len(bb))]
        if len(vals) >= 6:
            return vals[5]
        if len(vals) >= 2:
            return vals[1]
    except Exception as exc:
        print(f"  WARN: geom bbox z_top probe failed ({exc})", flush=True)
    return None


def _center_paper_box_import(
    comp: Any,
    geom_tag: str,
    settings: HuBaiComsolSettings,
) -> None:
    """Translate imported lattice so its STEP bbox center sits at the global origin."""
    cx, cy, cz = settings.paper_box_import_center_mm
    if settings.step_path:
        measured = _step_bbox_center_mm(settings.step_path)
        if measured is not None:
            mx, my, mz = measured
            if (
                abs(mx - cx) > 0.5
                or abs(my - cy) > 0.5
                or abs(mz - cz) > 0.5
            ):
                print(
                    f"  STEP bbox center ({mx:g}, {my:g}, {mz:g}) mm "
                    f"≠ grid assumption ({cx:g}, {cy:g}, {cz:g}) mm — using measured",
                    flush=True,
                )
            cx, cy, cz = mx, my, mz
    if abs(cx) < 1e-6 and abs(cy) < 1e-6 and abs(cz) < 1e-6:
        return
    geom = comp.geom(geom_tag)
    mov = geom.feature().create("mov1", "Move")
    try:
        mov.selection("input").all()
    except Exception:
        mov.selection("input").set(jpype.JArray(jpype.JInt)([1]))
    mov.set("displ", [f"{-cx}[mm]", f"{-cy}[mm]", f"{-cz}[mm]"])
    geom.run()
    print(
        f"  Recentered lattice import by ({-cx:g}, {-cy:g}, {-cz:g}) mm "
        f"(paper_box STEP → Fig. 2.8 origin-centred stack)",
        flush=True,
    )


def _clip_lattice_top_to_nominal(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    geom: str = "geom1",
    import_tag: str = "imp1",
) -> bool:
    """Trim lattice protrusion above §2.4.3 z_max so plate imprint can bond (ap2).

    Curved SFBLS struts can extend ~1–2 mm above nominal height.  If the plate
    sits on the design plane while lattice tips poke through, ``fin`` overlap
    prevents identity pairs and ``pb_top`` reads zero after solve.
    """
    z_max = settings.z_max_mm
    z_top = _geom_lattice_z_top_mm(comp, geom)
    if z_top is None or z_top <= z_max + 0.05:
        return False

    print(
        f"  Lattice top clip: z_top={z_top:g} > nominal {z_max:g} mm — "
        f"compose trim to design height",
        flush=True,
    )
    g = comp.geom(geom)
    feat_tags = [str(t) for t in g.feature().tags()]
    lattice_feat = "mov1" if "mov1" in feat_tags else import_tag
    top_tag = "blk_lat_top"
    compose_tag = "co_lat_clip"
    print(f"  Lattice clip compose: {lattice_feat}-{top_tag}", flush=True)
    for tag in (compose_tag, top_tag):
        if tag in feat_tags:
            g.feature().remove(tag)

    half = settings.half_xy_mm + 5.0
    _add_block(
        comp,
        top_tag,
        x0=-half,
        y0=-half,
        z0=z_max,
        lx=2.0 * half,
        ly=2.0 * half,
        lz=max(20.0, z_top - z_max + 5.0),
        geom=geom,
    )
    g.run()
    obj_names = [str(o) for o in g.objectNames()]
    if lattice_feat not in obj_names or top_tag not in obj_names:
        raise RuntimeError(
            f"Lattice clip objects missing (have {obj_names}, "
            f"need {lattice_feat} and {top_tag})"
        )
    if compose_tag in [str(t) for t in g.feature().tags()]:
        g.feature().remove(compose_tag)
    co_f = g.feature().create(compose_tag, "Compose")
    co_f.set("formula", f"{lattice_feat} - {top_tag}")
    co_f.selection("input").set([lattice_feat, top_tag])
    g.run()
    for tag in (lattice_feat, top_tag):
        try:
            g.feature(tag).active(False)
        except Exception as exc:
            print(f"  WARN: could not deactivate {tag} after clip ({exc})", flush=True)
    g.run()

    z_after = _geom_lattice_z_top_mm(comp, geom)
    if z_after is None or z_after > z_max + 0.15:
        raise RuntimeError(
            f"Lattice clip failed: z_top still {z_after} mm (nominal {z_max:g})"
        )
    print(f"  Lattice top after clip: {z_after:g} mm", flush=True)
    return True


def _log_fixture_stack(settings: HuBaiComsolSettings) -> None:
    z0 = settings.shaker_table_z_bottom_mm
    z_tbl_top = settings.z_min_mm
    z_plt_bot = _plate_z_bottom_mm(settings)
    z_plt_top = z_plt_bot + settings.top_plate_thickness_mm
    print(
        f"  Fig.2.8 stack (Z): table [{z0:g}, {z_tbl_top:g}] → "
        f"lattice [{z_tbl_top:g}, {z_plt_bot:g}] → "
        f"plate [{z_plt_bot:g}, {z_plt_top:g}] mm",
        flush=True,
    )


def _box_domain_selection(
    comp: Any,
    tag: str,
    *,
    half_xy: float,
    z_min: float,
    z_max: float,
) -> None:
    """Axis-aligned box selecting 3D domains (for localized mesh size)."""
    tags = [str(t) for t in comp.selection().tags()]
    if tag in tags:
        comp.selection().remove(tag)
    comp.selection().create(tag, "Box")
    sel = comp.selection(tag)
    sel.set("entitydim", jpype.JInt(3))
    sel.set("xmin", f"{-half_xy}[mm]")
    sel.set("xmax", f"{half_xy}[mm]")
    sel.set("ymin", f"{-half_xy}[mm]")
    sel.set("ymax", f"{half_xy}[mm]")
    sel.set("zmin", f"{z_min}[mm]")
    sel.set("zmax", f"{z_max}[mm]")


def _ensure_table_contact_mesh_selection(
    comp: Any, settings: HuBaiComsolSettings
) -> str:
    """Top shaker layer under lattice/plate footprint (Fig. 2.8 contact patch)."""
    tag = "sel_mesh_tbl_contact"
    z_top = settings.z_min_mm
    z_bot = z_top - settings.table_contact_refine_depth_mm
    _box_domain_selection(
        comp,
        tag,
        half_xy=settings.top_plate_half_xy_mm,
        z_min=z_bot,
        z_max=z_top,
    )
    return tag


def _set_named_mesh_size(
    mesh: Any,
    tag: str,
    sel_name: str,
    *,
    hmax_mm: float | None = None,
    hauto: int | None = None,
    hgrad: float | None = None,
    hmin_mm: float | None = None,
) -> Any:
    """Size on a component named selection (boundary or domain box)."""
    size = mesh.create(tag, "Size")
    size.selection().named(sel_name)
    if hmax_mm is not None:
        # Explicit hmax — do not combine with hauto (COMSOL keeps hmin from hauto > hmax).
        _apply_explicit_mesh_bounds(size, hmax_mm, hmin_mm)
    elif hauto is not None:
        try:
            size.set("hauto", int(hauto))
        except Exception:
            pass
    if hgrad is not None:
        try:
            size.set("hgradactive", True)
            size.set("hgrad", str(hgrad))
        except Exception:
            pass
    return size


def _add_table_contact_mesh_sizes(
    mesh: Any,
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    tbl_size: Any,
) -> list[Any]:
    """Refine shaker table top under lattice — Fig. 2.8 contact-zone gradient."""
    if not settings.table_contact_refine:
        return []
    hmax = settings.table_contact_refine_hmax_mm
    try:
        tbl_size.set("hgradactive", True)
        tbl_size.set("hgrad", str(settings.table_bulk_hgrad))
    except Exception:
        pass
    contact_sel = _ensure_table_contact_mesh_selection(comp, settings)
    sizes = [
        _set_named_mesh_size(
            mesh,
            "size_tbl_contact",
            contact_sel,
            hmax_mm=hmax,
            hgrad=settings.table_contact_refine_hgrad,
        ),
    ]
    print(
        f"  Table contact refine: hmax={hmax} mm, depth={settings.table_contact_refine_depth_mm} mm, "
        f"footprint ±{settings.top_plate_half_xy_mm} mm",
        flush=True,
    )
    return sizes


def _box_selection(
    comp: Any,
    tag: str,
    *,
    half_xy: float,
    z0: float,
    z1: float,
    band: float,
    condition: str = "allvertices",
) -> None:
    """Box boundary selection; default allvertices avoids picking vertical side faces."""
    tags = [str(t) for t in comp.selection().tags()]
    if tag in tags:
        comp.selection().remove(tag)
    comp.selection().create(tag, "Box")
    sel = comp.selection(tag)
    sel.set("entitydim", jpype.JInt(2))
    sel.set("xmin", f"{-half_xy}[mm]")
    sel.set("xmax", f"{half_xy}[mm]")
    sel.set("ymin", f"{-half_xy}[mm]")
    sel.set("ymax", f"{half_xy}[mm]")
    sel.set("zmin", f"{z0 - band}[mm]")
    sel.set("zmax", f"{z1 + band}[mm]")
    try:
        sel.set("condition", condition)
    except Exception:
        pass


def _horizontal_face_box_selection(
    comp: Any,
    tag: str,
    *,
    half_xy: float,
    z_mm: float,
    band_mm: float = 0.05,
) -> None:
    """Select a horizontal boundary at z=z_mm (all vertices in thin z-slab).

    COMSOL Box + condition=allvertices: side faces span z=[z_bot,z_top] so they
    are excluded; only the target horizontal face qualifies.
    """
    _box_selection(
        comp,
        tag,
        half_xy=half_xy,
        z0=z_mm,
        z1=z_mm,
        band=band_mm,
        condition="allvertices",
    )


def _explicit_domain_selection(
    comp: Any,
    tag: str,
    domain: int,
    *,
    geom_tag: str,
) -> None:
    tags = [str(t) for t in comp.selection().tags()]
    if tag in tags:
        comp.selection().remove(tag)
    comp.selection().create(tag, "Explicit")
    sel = comp.selection(tag)
    sel.geom(geom_tag, jpype.JInt(3))
    sel.set(jpype.JArray(jpype.JInt)([int(domain)]))


def _table_top_excitation_selection(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    d_tbl: int,
    geom_tag: str,
) -> None:
    """Shaker table top face only — exclude lattice strut faces at the same z plane."""
    tag = "sel_table_top"
    z = settings.z_min_mm
    band = min(settings.selection_band_mm, 0.05)
    half_xy = settings.shaker_half_xy_mm
    dom_tag = "_sel_tbl_dom"
    adj_tag = "_sel_tbl_adj"
    box_tag = "_sel_tbl_top_box"
    for old in (tag, dom_tag, adj_tag, box_tag):
        if old in [str(t) for t in comp.selection().tags()]:
            comp.selection().remove(old)
    try:
        _explicit_domain_selection(comp, dom_tag, d_tbl, geom_tag=geom_tag)
        comp.selection().create(adj_tag, "Adjacent")
        adj = comp.selection(adj_tag)
        adj.set("input", [dom_tag])
        _box_selection(
            comp,
            box_tag,
            half_xy=half_xy,
            z0=z,
            z1=z,
            band=band,
            condition="allvertices",
        )
        comp.selection().create(tag, "Intersection")
        inter = comp.selection(tag)
        inter.set("input", [adj_tag, box_tag])
        n = len(comp.selection(tag).entities())
        if n < 1:
            raise RuntimeError(f"empty intersection ({n} boundaries)")
        print(f"  Table-top selection: Intersection (domain {d_tbl} ∩ z={z} mm), n={n}", flush=True)
    except Exception as exc:
        print(f"  WARN: table-top Intersection failed ({exc}); using z-slab Box", flush=True)
        _horizontal_face_box_selection(
            comp,
            tag,
            half_xy=half_xy,
            z_mm=z,
            band_mm=band,
        )


def _log_boundary_selection(comp: Any, tag: str, label: str) -> None:
    try:
        ents = comp.selection(tag).entities()
        n = len(ents) if hasattr(ents, "__len__") else int(ents.length)
        ids = [int(ents[i]) for i in range(min(n, 8))]
        print(f"  Selection {label} ({tag}): {n} boundary(ies) {ids}", flush=True)
    except Exception as exc:
        print(f"  Selection {label} ({tag}): count unavailable ({exc})", flush=True)


def _ball_point_selection(
    comp: Any,
    tag: str,
    *,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    r_mm: float = 0.5,
) -> None:
    """Ball selection for a geometric point (entitydim=0)."""
    tags = [str(t) for t in comp.selection().tags()]
    if tag in tags:
        comp.selection().remove(tag)
    comp.selection().create(tag, "Ball")
    sel = comp.selection(tag)
    sel.set("entitydim", jpype.JInt(0))
    sel.set("posx", f"{x_mm}[mm]")
    sel.set("posy", f"{y_mm}[mm]")
    sel.set("posz", f"{z_mm}[mm]")
    sel.set("r", f"{r_mm}[mm]")


def _add_block(
    comp: Any,
    tag: str,
    *,
    x0: float,
    y0: float,
    z0: float,
    lx: float,
    ly: float,
    lz: float,
    geom: str = "geom1",
) -> None:
    blk = comp.geom(geom).feature().create(tag, "Block")
    blk.set("size", [f"{lx}[mm]", f"{ly}[mm]", f"{lz}[mm]"])
    blk.set("pos", [f"{x0}[mm]", f"{y0}[mm]", f"{z0}[mm]"])
    blk.set("base", "corner")
    if tag == "blk_table":
        _set_label(blk, LABEL_GEOM_TABLE)
    elif tag == "blk_plate":
        _set_label(blk, LABEL_GEOM_PLATE)


def _add_table_plate_blocks(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    geom: str = "geom1",
    plate_z0: float | None = None,
) -> None:
    """Table + plate blocks at §2.4.3 positions (no FormAssembly)."""
    half_tbl = settings.shaker_half_xy_mm
    half_plt = settings.top_plate_half_xy_mm
    z_plt_bot = plate_z0 if plate_z0 is not None else _plate_z_bottom_mm(settings)
    _add_block(
        comp,
        "blk_table",
        x0=-half_tbl,
        y0=-half_tbl,
        z0=settings.shaker_table_z_bottom_mm,
        lx=settings.shaker_table_size_xy_mm,
        ly=settings.shaker_table_size_xy_mm,
        lz=settings.shaker_table_height_mm,
        geom=geom,
    )
    _add_block(
        comp,
        "blk_plate",
        x0=-half_plt,
        y0=-half_plt,
        z0=z_plt_bot,
        lx=settings.top_plate_xy_mm,
        ly=settings.top_plate_xy_mm,
        lz=settings.top_plate_thickness_mm,
        geom=geom,
    )


def _add_shaker_fixture_geometry(
    comp: Any, settings: HuBaiComsolSettings, *, geom: str = "geom1"
) -> None:
    """Fig. 2.8: shaker table below lattice + thin aluminum plate on top."""
    tbl_xy = settings.shaker_table_size_xy_mm
    tbl_h = settings.shaker_table_height_mm
    plt_xy = settings.top_plate_xy_mm
    plt_t = settings.top_plate_thickness_mm

    _add_table_plate_blocks(comp, settings, geom=geom)
    fin_pairtype = (
        "contact"
        if settings.interface_coupling.lower() == "p3_contact_auto"
        else "identity"
    )
    _finalize_fixture_geometry(comp, geom=geom, pairtype=fin_pairtype)
    print(
        f"  Fig.2.8 fixture: table {tbl_xy}×{tbl_xy}×{tbl_h} mm, "
        f"plate {plt_xy}×{plt_xy}×{plt_t} mm",
        flush=True,
    )


def _finalize_fixture_geometry(
    comp: Any,
    *,
    geom: str = "geom1",
    pairtype: str = "identity",
) -> None:
    """Form Assembly + auto pairs at touching lattice/table/plate faces."""
    g = comp.geom(geom)
    tags = [str(t) for t in g.feature().tags()]
    if "fin" in tags:
        fin = g.feature("fin")
    else:
        fin = g.feature().create("fin", "FormUnion")
    fin.set("action", "assembly")
    try:
        fin.set("imprint", "on")
        print("  Form assembly: imprint=on (bond lattice–plate interfaces)", flush=True)
    except Exception as exc:
        print(f"  WARN: imprint not set ({exc})", flush=True)
    try:
        fin.set("createpairs", "on")
    except Exception:
        fin.set("createpairs", True)
    pt = "contact" if pairtype.lower() == "contact" else "identity"
    try:
        fin.set("pairtype", pt)
    except Exception:
        pass
    print(f"  Form assembly: pairtype={pt}", flush=True)
    _set_label(fin, LABEL_GEOM_ASSEMBLY)
    g.run()


def _set_material(
    comp: Any,
    tag: str,
    domain: int,
    *,
    youngs: str,
    poisson: str,
    density: str,
) -> None:
    tags = [str(t) for t in comp.material().tags()]
    if tag not in tags:
        comp.material().create(tag, "Common")
    mat = comp.material(tag)
    mat.selection().set(jpype.JArray(jpype.JInt)([int(domain)]))
    mat.propertyGroup("def").set("youngsmodulus", youngs)
    mat.propertyGroup("def").set("poissonsratio", poisson)
    mat.propertyGroup("def").set("density", density)
    _MAT_LABELS = {
        "mat_table": LABEL_MAT_TABLE,
        "mat_tbl_stack": LABEL_MAT_TABLE,
        "mat_plate": LABEL_MAT_PLATE,
        "mat_plt_stack": LABEL_MAT_PLATE,
        "mat_lattice": LABEL_MAT_LATTICE,
        "mat1": LABEL_MAT_LATTICE,
    }
    if tag in _MAT_LABELS:
        _set_label(mat, _MAT_LABELS[tag])


def _probe_domain_at_point(
    comp: Any,
    *,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    r_mm: float = 0.5,
    sel_tag: str = "_tmp_dom_probe",
) -> int:
    tags = [str(t) for t in comp.selection().tags()]
    if sel_tag in tags:
        comp.selection().remove(sel_tag)
    comp.selection().create(sel_tag, "Ball")
    sel = comp.selection(sel_tag)
    sel.set("entitydim", jpype.JInt(3))
    sel.set("posx", f"{x_mm}[mm]")
    sel.set("posy", f"{y_mm}[mm]")
    sel.set("posz", f"{z_mm}[mm]")
    sel.set("r", f"{r_mm}[mm]")
    ents = sel.entities()
    if len(ents) != 1:
        raise ValueError(f"domain probe ({x_mm},{y_mm},{z_mm}) hit {list(ents)}")
    return int(ents[0])


def _log_geometry_domains(
    comp: Any, settings: HuBaiComsolSettings, *, geom: str = "geom1"
) -> None:
    """Warn if hard-coded domain indices do not match geometry after assembly."""
    try:
        g = comp.geom(geom)
        ndom = int(g.getNDomains())
        expected = 3 if settings.include_shaker_fixture else 1
        print(f"  Geometry domains (3D): {ndom}", flush=True)
        if settings.include_shaker_fixture and ndom != expected:
            print(
                f"  WARNING: expected {expected} domains "
                f"(lattice/table/plate) but geometry has {ndom}; "
                "check domain_lattice/domain_shaker_table/domain_top_plate",
                flush=True,
            )
        for dom in range(1, ndom + 1):
            print(f"  Domain {dom} present in geometry", flush=True)
    except Exception as exc:
        print(f"  Domain check skipped: {exc}", flush=True)


def _resolve_fixture_domains(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    geom: str = "geom1",
) -> tuple[int, int, int]:
    """Detect lattice/table/plate domain IDs after Form Assembly (order != feature order)."""
    g = comp.geom(geom)
    ndom = int(g.getNDomains())
    if ndom != 3:
        print(
            f"  Domain map: using settings defaults (ndom={ndom})",
            flush=True,
        )
        return (
            settings.domain_lattice,
            settings.domain_shaker_table,
            settings.domain_top_plate,
        )

    try:
        z_tbl = settings.shaker_table_z_bottom_mm + 0.5 * settings.shaker_table_height_mm
        z_plt = _plate_z_bottom_mm(settings) + 0.5 * settings.top_plate_thickness_mm
        d_tbl = _probe_domain_at_point(comp, x_mm=0.0, y_mm=0.0, z_mm=z_tbl)
        d_lat = _probe_domain_at_point(comp, x_mm=0.0, y_mm=0.0, z_mm=0.0)
        d_plt = _probe_domain_at_point(comp, x_mm=0.0, y_mm=0.0, z_mm=z_plt, r_mm=0.2)
    except Exception as exc:
        print(f"  Domain map: ball probe failed ({exc}); using settings defaults", flush=True)
        return (
            settings.domain_lattice,
            settings.domain_shaker_table,
            settings.domain_top_plate,
        )
    finally:
        try:
            if "_tmp_dom_probe" in [str(t) for t in comp.selection().tags()]:
                comp.selection().remove("_tmp_dom_probe")
        except Exception:
            pass

    if (
        d_lat != settings.domain_lattice
        or d_tbl != settings.domain_shaker_table
        or d_plt != settings.domain_top_plate
    ):
        print(
            f"  Domain map (resolved): lattice={d_lat}, table={d_tbl}, plate={d_plt} "
            f"(settings assumed {settings.domain_lattice}/"
            f"{settings.domain_shaker_table}/{settings.domain_top_plate})",
            flush=True,
        )
    else:
        print(
            f"  Domain map: lattice={d_lat}, table={d_tbl}, plate={d_plt}",
            flush=True,
        )
    return d_lat, d_tbl, d_plt


def _assign_materials(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    d_lat: int | None = None,
    d_tbl: int | None = None,
    d_plt: int | None = None,
) -> None:
    if not settings.include_shaker_fixture:
        d_lat_only = settings.domain_lattice if d_lat is None else d_lat
        use_marlow = settings.lattice_material_model.lower() in (
            "marlow_uniaxial",
            "marlow",
            "hyperelastic_marlow",
            "fig25",
        )
        if use_marlow:
            assign_lattice_marlow_material(comp, settings, d_lat_only, mat_tag="mat1")
        else:
            comp.material().create("mat1", "Common")
            comp.material("mat1").selection().all()
            mat_def = comp.material("mat1").propertyGroup("def")
            mat_def.set("youngsmodulus", "E_mpa")
            mat_def.set("poissonsratio", str(settings.poisson))
            mat_def.set("density", f"{settings.density_kg_m3}[kg/m^3]")
        return

    d_lat = settings.domain_lattice if d_lat is None else d_lat
    d_tbl = settings.domain_shaker_table if d_tbl is None else d_tbl
    d_plt = settings.domain_top_plate if d_plt is None else d_plt

    use_marlow = settings.lattice_material_model.lower() in (
        "marlow_uniaxial",
        "marlow",
        "hyperelastic_marlow",
        "fig25",
    )
    if use_marlow:
        assign_lattice_marlow_material(comp, settings, d_lat)
        if "mat_lattice" in [str(t) for t in comp.material().tags()]:
            _set_label(comp.material("mat_lattice"), LABEL_MAT_LATTICE)
    else:
        _set_material(
            comp,
            "mat_lattice",
            d_lat,
            youngs="E_mpa",
            poisson=str(settings.poisson),
            density=f"{settings.density_kg_m3}[kg/m^3]",
        )

    _set_material(
        comp,
        "mat_tbl_stack",
        d_tbl,
        youngs="E_table",
        poisson=str(settings.shaker_table_poisson),
        density=f"{settings.shaker_table_density_kg_m3}[kg/m^3]",
    )
    _set_material(
        comp,
        "mat_plt_stack",
        d_plt,
        youngs="E_plate",
        poisson=str(settings.top_plate_poisson),
        density=f"{settings.top_plate_density_kg_m3}[kg/m^3]",
    )


def _plate_bottom_selection(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    geom_tag: str = LATTICE_GEOM,
) -> None:
    """Aluminum plate bottom face (bonded contact source)."""
    z = _plate_z_bottom_mm(settings)
    band = min(settings.selection_band_mm, 0.05)
    _horizontal_face_box_selection(
        comp,
        "sel_plate_bottom",
        half_xy=settings.top_plate_half_xy_mm,
        z_mm=z,
        band_mm=band,
    )


def _lattice_top_contact_selection(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    d_lat: int,
    geom_tag: str = LATTICE_GEOM,
) -> None:
    """Lattice strut tops at plate interface (bonded contact destination)."""
    tag = "sel_lattice_top"
    z = _plate_z_bottom_mm(settings)
    band = min(settings.selection_band_mm, 0.05)
    dom_tag = "_sel_lat_dom"
    adj_tag = "_sel_lat_adj"
    box_tag = "_sel_lat_top_box"
    for old in (tag, dom_tag, adj_tag, box_tag):
        if old in [str(t) for t in comp.selection().tags()]:
            comp.selection().remove(old)
    try:
        _explicit_domain_selection(comp, dom_tag, d_lat, geom_tag=geom_tag)
        comp.selection().create(adj_tag, "Adjacent")
        comp.selection(adj_tag).set("input", [dom_tag])
        _box_selection(
            comp,
            box_tag,
            half_xy=settings.top_plate_half_xy_mm,
            z0=z,
            z1=z,
            band=band,
            condition="allvertices",
        )
        comp.selection().create(tag, "Intersection")
        comp.selection(tag).set("input", [adj_tag, box_tag])
        n = len(comp.selection(tag).entities())
        if n < 1:
            raise RuntimeError(f"empty lattice-top intersection ({n} boundaries)")
        print(
            f"  Lattice-top contact selection: domain {d_lat} ∩ z={z:g} mm, n={n}",
            flush=True,
        )
    except Exception as exc:
        print(f"  WARN: lattice-top Intersection failed ({exc}); using z-slab Box", flush=True)
        _horizontal_face_box_selection(
            comp,
            tag,
            half_xy=settings.half_xy_mm,
            z_mm=z,
            band_mm=band,
        )


def _remove_identity_pair(comp: Any, tag: str) -> bool:
    try:
        tags = [str(t) for t in comp.pair().tags()]
        if tag not in tags:
            return False
        if str(comp.pair(tag).type()).lower() != "identity":
            return False
        comp.pair().remove(tag)
        print(f"  Removed identity pair {tag}", flush=True)
        return True
    except Exception as exc:
        print(f"  WARN: could not remove pair {tag} ({exc})", flush=True)
        return False


def _set_feature_prop(feat: Any, props: dict[str, object]) -> list[str]:
    """Try several property keys; return those successfully set."""
    set_keys: list[str] = []
    for key, val in props.items():
        try:
            feat.set(key, val)
            set_keys.append(key)
        except Exception:
            continue
    return set_keys


def _remove_pair(comp: Any, tag: str) -> bool:
    try:
        tags = [str(t) for t in comp.pair().tags()]
        if tag not in tags:
            return False
        comp.pair().remove(tag)
        print(f"  Removed pair {tag}", flush=True)
        return True
    except Exception as exc:
        print(f"  WARN: could not remove pair {tag} ({exc})", flush=True)
        return False


def _remove_solid_feature(solid: Any, tag: str) -> None:
    try:
        if tag in [str(t) for t in solid.feature().tags()]:
            solid.feature().remove(tag)
    except Exception:
        pass


def _lattice_bottom_contact_selection(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    d_lat: int,
    geom_tag: str = LATTICE_GEOM,
) -> None:
    """Lattice strut bottoms at table interface (contact destination)."""
    tag = "sel_lattice_bottom"
    z = settings.z_min_mm
    band = min(settings.selection_band_mm, 0.05)
    dom_tag = "_sel_lat_bot_dom"
    adj_tag = "_sel_lat_bot_adj"
    box_tag = "_sel_lat_bot_box"
    for old in (tag, dom_tag, adj_tag, box_tag):
        if old in [str(t) for t in comp.selection().tags()]:
            comp.selection().remove(old)
    try:
        _explicit_domain_selection(comp, dom_tag, d_lat, geom_tag=geom_tag)
        comp.selection().create(adj_tag, "Adjacent")
        comp.selection(adj_tag).set("input", [dom_tag])
        _box_selection(
            comp,
            box_tag,
            half_xy=settings.half_xy_mm,
            z0=z,
            z1=z,
            band=band,
            condition="allvertices",
        )
        comp.selection().create(tag, "Intersection")
        comp.selection(tag).set("input", [adj_tag, box_tag])
        n = len(comp.selection(tag).entities())
        if n < 1:
            raise RuntimeError(f"empty lattice-bottom intersection ({n} boundaries)")
        print(
            f"  Lattice-bottom contact selection: domain {d_lat} ∩ z={z:g} mm, n={n}",
            flush=True,
        )
    except Exception as exc:
        print(f"  WARN: lattice-bottom Intersection failed ({exc}); using z-slab Box", flush=True)
        _horizontal_face_box_selection(
            comp,
            tag,
            half_xy=settings.half_xy_mm,
            z_mm=z,
            band_mm=band,
        )


def _create_contact_pair(
    comp: Any,
    cp_tag: str,
    *,
    src_sel: str,
    dst_sel: str,
    geom_tag: str,
    label: str,
) -> None:
    pair_tags = [str(t) for t in comp.pair().tags()]
    if cp_tag in pair_tags:
        comp.pair().remove(cp_tag)
    comp.pair().create(cp_tag, "Contact", geom_tag)
    cp = comp.pair(cp_tag)
    cp.source().named(src_sel)
    cp.destination().named(dst_sel)
    _set_label(cp, label)
    print(f"  Contact pair {cp_tag}: {src_sel} → {dst_sel}", flush=True)


def _create_penalty_contact_bc(
    solid: Any,
    cnt_tag: str,
    cp_tag: str,
    *,
    label: str,
    use_adhesion: bool = False,
) -> None:
    _remove_solid_feature(solid, cnt_tag)
    cnt = solid.create(cnt_tag, "Contact", jpype.JInt(2))
    _set_label(cnt, label)
    set_keys = _set_feature_prop(
        cnt,
        {
            "pairs": cp_tag,
            "ContactMethodCtrl": "Penalty",
            "penaltyCtrl": "Preset",
            "tunedFor": "Speed",
            "zeroInitGap": "1",
        },
    )
    print(f"  Contact BC {cnt_tag}: set {set_keys}", flush=True)
    if not use_adhesion:
        return
    adh_tag = f"adh_{cnt_tag.replace('cnt_', '')}"
    try:
        if adh_tag in [str(t) for t in cnt.feature().tags()]:
            cnt.feature().remove(adh_tag)
        adh = cnt.create(adh_tag, "Adhesion", jpype.JInt(2))
        _set_label(adh, f"{label} 胶接")
        adh_keys = _set_feature_prop(
            adh,
            {
                "ActivationCriterion": "Pressure",
                "p_n0": "1e5[Pa]",
                "NormalStiffness": "FromContactPressurePenaltyFactor",
                "ShearStiffness": "FromContactPressurePenaltyFactor",
                "n_tau": "0.17",
            },
        )
        print(f"  Adhesion {adh_tag}: set {adh_keys}", flush=True)
    except Exception as exc:
        print(f"  WARN: Adhesion subnode not created ({exc})", flush=True)


def _create_continuity_bc(solid: Any, cont_tag: str, pair_tag: str, *, label: str) -> None:
    _remove_solid_feature(solid, cont_tag)
    cont = solid.create(cont_tag, "Continuity", jpype.JInt(2))
    _set_label(cont, label)
    set_keys = _set_feature_prop(
        cont,
        {
            "pairs": pair_tag,
            "pair": pair_tag,
            "identityPair": pair_tag,
            "IdentityPair": pair_tag,
        },
    )
    print(f"  Continuity {cont_tag} @ {pair_tag}: set {set_keys}", flush=True)


def _log_auto_pairs(comp: Any) -> None:
    for tag in comp.pair().tags():
        pt = comp.pair(str(tag))
        try:
            ptype = str(pt.type())
        except Exception:
            ptype = "?"
        print(f"  Auto pair {tag}: type={ptype}", flush=True)


def _assert_fixture_identity_pairs(comp: Any, settings: HuBaiComsolSettings) -> None:
    """Fail fast when fin imprint did not bond table/lattice/plate (no ap1/ap2)."""
    if not settings.include_shaker_fixture:
        return
    if settings.interface_coupling.lower() != "p1_continuity":
        return
    pairs = [str(t) for t in comp.pair().tags()]
    missing = [t for t in ("ap1", "ap2") if t not in pairs]
    if missing:
        raise RuntimeError(
            f"Form assembly missing identity pairs {missing} — "
            "check plate/lattice Z snap (lattice top protrusion vs plate_z_bottom_mm)"
        )


def _setup_p1_identity_continuity(
    comp: Any,
    solid: Any,
    settings: HuBaiComsolSettings,
) -> None:
    """Phase 1: keep fin identity ap1/ap2; add Solid Mechanics Continuity on both."""
    _ = settings
    _log_auto_pairs(comp)
    _assert_fixture_identity_pairs(comp, settings)
    for pair_tag, cont_tag, label in (
        ("ap1", "cont_ap1", "台–点阵连续"),
        ("ap2", "cont_ap2", "板–点阵连续"),
    ):
        if pair_tag not in [str(t) for t in comp.pair().tags()]:
            print(f"  WARN: expected identity pair {pair_tag} missing after fin", flush=True)
            continue
        _create_continuity_bc(solid, cont_tag, pair_tag, label=label)


def _setup_p2_all_contact_pairs(
    comp: Any,
    solid: Any,
    settings: HuBaiComsolSettings,
    *,
    geom_tag: str,
    d_lat: int,
    d_tbl: int,
    d_plt: int,
) -> None:
    """Phase 2: replace ap1/ap2 with manual Contact pairs + Penalty (no Adhesion)."""
    _ = d_plt
    for old in ("ap1", "ap2", "cp_tbl_lat", "cp_plt_lat"):
        _remove_pair(comp, old)
    _table_top_excitation_selection(comp, settings, d_tbl=d_tbl, geom_tag=geom_tag)
    _lattice_bottom_contact_selection(comp, settings, d_lat=d_lat, geom_tag=geom_tag)
    _plate_bottom_selection(comp, settings, geom_tag=geom_tag)
    _lattice_top_contact_selection(comp, settings, d_lat=d_lat, geom_tag=geom_tag)
    _log_boundary_selection(comp, "sel_table_top", "table top (contact src tbl–lat)")
    _log_boundary_selection(comp, "sel_lattice_bottom", "lattice bottom (contact dst tbl–lat)")
    _log_boundary_selection(comp, "sel_plate_bottom", "plate bottom (contact src plt–lat)")
    _log_boundary_selection(comp, "sel_lattice_top", "lattice top (contact dst plt–lat)")
    _create_contact_pair(
        comp,
        "cp_tbl_lat",
        src_sel="sel_table_top",
        dst_sel="sel_lattice_bottom",
        geom_tag=geom_tag,
        label="台顶–点阵底 接触对",
    )
    _create_contact_pair(
        comp,
        "cp_plt_lat",
        src_sel="sel_plate_bottom",
        dst_sel="sel_lattice_top",
        geom_tag=geom_tag,
        label="板底–点阵顶 接触对",
    )
    _create_penalty_contact_bc(
        solid, "cnt_tbl", "cp_tbl_lat", label="台–点阵粘结接触", use_adhesion=False
    )
    _create_penalty_contact_bc(
        solid, "cnt_plt", "cp_plt_lat", label="板–点阵粘结接触", use_adhesion=False
    )


def _setup_p3_auto_contact_pairs(comp: Any, solid: Any, settings: HuBaiComsolSettings) -> None:
    """Phase 3: fin auto Contact pairs ap1/ap2 + Penalty BCs (imprint-native boundaries)."""
    _ = settings
    _log_auto_pairs(comp)
    for pair_tag, cnt_tag, label in (
        ("ap1", "cnt_ap1", "台–点阵自动接触"),
        ("ap2", "cnt_ap2", "板–点阵自动接触"),
    ):
        if pair_tag not in [str(t) for t in comp.pair().tags()]:
            print(f"  WARN: expected auto contact pair {pair_tag} missing after fin", flush=True)
            continue
        _create_penalty_contact_bc(
            solid, cnt_tag, pair_tag, label=label, use_adhesion=False
        )


def _setup_plate_lattice_bonded_contact(
    comp: Any,
    solid: Any,
    settings: HuBaiComsolSettings,
    *,
    geom_tag: str,
    d_lat: int,
    d_plt: int,
) -> None:
    """Plan B: plate bottom ↔ lattice top as Contact pair + penalty Adhesion (bonded)."""
    _ = d_plt
    _plate_bottom_selection(comp, settings, geom_tag=geom_tag)
    _lattice_top_contact_selection(comp, settings, d_lat=d_lat, geom_tag=geom_tag)
    _log_boundary_selection(comp, "sel_plate_bottom", "plate bottom (contact src)")
    _log_boundary_selection(comp, "sel_lattice_top", "lattice top (contact dst)")

    # ap2 is the auto identity pair for plate–lattice; replace with explicit contact pair.
    _remove_identity_pair(comp, "ap2")

    cp_tag = "cp_plt_lat"
    pair_tags = [str(t) for t in comp.pair().tags()]
    if cp_tag in pair_tags:
        comp.pair().remove(cp_tag)
    comp.pair().create(cp_tag, "Contact", geom_tag)
    cp = comp.pair(cp_tag)
    cp.source().named("sel_plate_bottom")
    cp.destination().named("sel_lattice_top")
    _set_label(cp, "板底–点阵顶 接触对")
    # COMSOL: destination mesh finer than source — plate=src, lattice tips=dst.
    print(f"  Contact pair {cp_tag}: sel_plate_bottom → sel_lattice_top", flush=True)

    cnt_tag = "cnt_plt"
    feat_tags = [str(t) for t in solid.feature().tags()]
    if cnt_tag in feat_tags:
        solid.feature().remove(cnt_tag)
    cnt = solid.create(cnt_tag, "Contact", jpype.JInt(2))
    _set_label(cnt, "板–点阵粘结接触")

    set_keys = _set_feature_prop(
        cnt,
        {
            "pairs": cp_tag,
            "ContactMethodCtrl": "Penalty",
            "penaltyCtrl": "Preset",
            "tunedFor": "Speed",
            "zeroInitGap": "1",
        },
    )
    print(f"  Contact BC {cnt_tag}: set {set_keys}", flush=True)

    adh_tag = "adh_plt"
    try:
        if adh_tag in [str(t) for t in cnt.feature().tags()]:
            cnt.feature().remove(adh_tag)
        adh = cnt.create(adh_tag, "Adhesion", jpype.JInt(2))
        _set_label(adh, "板–点阵胶接")
        adh_keys = _set_feature_prop(
            adh,
            {
                "ActivationCriterion": "Pressure",
                "p_n0": "1e5[Pa]",
                "NormalStiffness": "FromContactPressurePenaltyFactor",
                "ShearStiffness": "FromContactPressurePenaltyFactor",
                "n_tau": "0.17",
            },
        )
        print(f"  Adhesion {adh_tag}: set {adh_keys}", flush=True)
    except Exception as exc:
        print(f"  WARN: Adhesion subnode not created ({exc})", flush=True)


def _add_fixture_contacts(
    comp: Any,
    settings: HuBaiComsolSettings,
    solid: Any,
    *,
    geom_tag: str = LATTICE_GEOM,
    d_lat: int | None = None,
    d_plt: int | None = None,
    d_tbl: int | None = None,
) -> None:
    """Apply Fig.2.8 interface coupling per settings.interface_coupling."""
    for key in ("usepairs", "usePairs"):
        try:
            solid.set(key, True)
            print(f"  Solid mechanics: {key}=True", flush=True)
            break
        except Exception:
            continue
    if d_lat is None or d_plt is None:
        return
    mode = settings.interface_coupling.lower()
    print(f"  Interface coupling: {mode}", flush=True)
    if mode == "p1_continuity":
        _setup_p1_identity_continuity(comp, solid, settings)
    elif mode == "p2_contact_all":
        if d_tbl is None:
            d_tbl = settings.domain_shaker_table
        _setup_p2_all_contact_pairs(
            comp, solid, settings, geom_tag=geom_tag, d_lat=d_lat, d_tbl=d_tbl, d_plt=d_plt
        )
    elif mode == "p3_contact_auto":
        _setup_p3_auto_contact_pairs(comp, solid, settings)
    else:
        print(f"  WARN: unknown interface_coupling={mode!r}; using p1_continuity", flush=True)
        _setup_p1_identity_continuity(comp, solid, settings)


def _add_boundary_probes(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    base_sel: str,
    top_sel: str,
    java: Any | None = None,
) -> None:
    """Input/output probes for Eq. 3.20 / 3.6 (disp + acceleration)."""
    disp = settings.excitation_displacement_expr
    acc = settings.excitation_acceleration_expr
    for tag, sel_name, expr, unit in (
        ("pb_base", base_sel, disp, "mm"),
        ("pb_top", top_sel, disp, "mm"),
        ("pb_base_acc", base_sel, acc, "m/s^2"),
        ("pb_top_acc", top_sel, acc, "m/s^2"),
    ):
        comp.probe().create(tag, "Boundary")
        pb = comp.probe(tag)
        pb.selection().named(sel_name)
        # average (not integral): table 400×400 mm vs plate 100×100 mm — integral
        # scales with area and falsely lowers T by ~(100/400)² at all frequencies.
        pb.set("type", "average")
        pb.set("expr", expr)
        pb.set("unit", unit)
        if java is not None:
            tbl_tag = f"tbl_{tag}"
            try:
                if tbl_tag not in [str(t) for t in java.result().table().tags()]:
                    java.result().table().create(tbl_tag, "Table")
                pb.set("table", tbl_tag)
            except Exception:
                pass


def _activate_study_features(study_step: Any, activations: list[tuple[str, bool]]) -> None:
    """Activate/deactivate physics features for a study step (COMSOL 5.6 .activate API)."""
    for path, state in activations:
        try:
            study_step.activate(path, bool(state))
        except Exception as exc:
            print(f"  WARN: study activate {path}={state} ({exc})", flush=True)


def _apply_freq_study_activate(freq_step: Any, settings: HuBaiComsolSettings) -> None:
    """Bind physics features to Frequency study (per-feature activate only).

    COMSOL 5.6 rejects bulk freq_step.set('activate', [...]) — it overwrites
    partial state and leaves fixbase/base_exc off.
    """
    _activate_study_features(freq_step, _freq_study_physics_activations(settings))
    print(
        "  freq study activate: fixbase/base_exc/lemm on; init1/free1/lemm1 off",
        flush=True,
    )


def _study_step_path(study_tag: str, step_tag: str) -> str:
    return f"{study_tag}/{step_tag}"


def _bind_bc_to_study_steps(
    solid: Any,
    *,
    fixbase_steps: list[str],
    base_exc_steps: list[str],
) -> None:
    """Bind boundary conditions to study steps via physics-feature activate strings."""
    for feat, steps in (("fixbase", fixbase_steps), ("base_exc", base_exc_steps)):
        if not steps:
            continue
        value = ", ".join(steps)
        try:
            solid.feature(feat).set("activate", value)
            print(f"  BC {feat} → studies [{value}]", flush=True)
        except Exception as exc:
            print(f"  WARN: BC {feat} study binding ({exc})", flush=True)


def _remove_default_solid_features(solid: Any) -> None:
    for tag in ("lemm1",):
        try:
            if tag in [str(t) for t in solid.feature().tags()]:
                solid.feature().remove(tag)
        except Exception:
            pass


def _coupling_study_activations(settings: HuBaiComsolSettings) -> list[tuple[str, bool]]:
    mode = settings.interface_coupling.lower()
    if mode == "p1_continuity":
        return [("solid.cont_ap1", True), ("solid.cont_ap2", True)]
    if mode == "p2_contact_all":
        return [("solid.cnt_tbl", True), ("solid.cnt_plt", True)]
    if mode == "p3_contact_auto":
        return [("solid.cnt_ap1", True), ("solid.cnt_ap2", True)]
    return [("solid.cont_ap1", True), ("solid.cont_ap2", True)]


def _freq_study_physics_activations(settings: HuBaiComsolSettings) -> list[tuple[str, bool]]:
    return [
        ("solid.fixbase", True),
        ("solid.base_exc", True),
        *_coupling_study_activations(settings),
        ("solid.init1", False),
        ("solid.free1", False),
        ("solid.lemm1", False),
        ("solid.lemm_fixture", True),
        ("solid.lemm_lattice", True),
    ]


def _eigen_study_physics_activations(settings: HuBaiComsolSettings) -> list[tuple[str, bool]]:
    return [
        ("solid.fixbase", True),
        ("solid.base_exc", False),
        *_coupling_study_activations(settings),
        ("solid.lemm1", False),
        ("solid.lemm_fixture", True),
        ("solid.lemm_lattice", True),
    ]


def _bodyload_force_vector(settings: HuBaiComsolSettings) -> list[str]:
    """Volume force density F = rho * A_base along excitation axis (N/m^3)."""
    vec = ["0", "0", "0"]
    idx = {"x": 0, "y": 1, "z": 2}.get(settings.excitation_axis.lower(), 2)
    vec[idx] = "A_base*solid.rho"
    return vec


def _add_bodyload_acceleration_excitation(
    solid: Any,
    settings: HuBaiComsolSettings,
    domains: list[int],
) -> bool:
    """BodyLoad Ftot=rho*A_base — standard Frequency study (no Harmonic Perturbation tag)."""
    if not domains:
        return False
    try:
        bl = solid.create("base_exc", "BodyLoad", jpype.JInt(3))
        bl.selection().set(jpype.JArray(jpype.JInt)([int(d) for d in domains]))
        bl.set("Ftot", _bodyload_force_vector(settings))
        doms = ",".join(str(d) for d in domains)
        print(
            f"  Freq excitation: BodyLoad Ftot=rho*A_base on domain(s) {doms} "
            f"({settings.excitation_axis.upper()}, A_base={settings.base_acceleration_m_s2} m/s²)",
            flush=True,
        )
        return True
    except Exception as exc:
        print(f"  WARN: BodyLoad excitation failed ({exc})", flush=True)
        try:
            solid.feature().remove("base_exc")
        except Exception:
            pass
        return False


def _create_solid_feature(solid: Any, tag: str, feature_types: tuple[str, ...]) -> Any | None:
    for feat_type in feature_types:
        try:
            return solid.create(tag, feat_type, jpype.JInt(2))
        except Exception:
            continue
    return None


def _configure_prescribed_acceleration(
    acc: Any,
    settings: HuBaiComsolSettings,
) -> bool:
    """Prescribed acceleration for standard Frequency Domain study (not perturbation type)."""
    axis = settings.excitation_axis.lower()
    axis_props = {
        "x": [("Ax", "ax"), ("Prescribedx", "ax")],
        "y": [("Ay", "ay"), ("Prescribedy", "ay")],
        "z": [("Az", "az"), ("Prescribedz", "az")],
    }
    for flag, comp_name in axis_props.get(axis, axis_props["z"]):
        try:
            acc.set(flag, True)
            acc.set(comp_name, "A_base")
            return True
        except Exception:
            continue
    try:
        acc.set("a0", settings.excitation_vector(acceleration=True))
        return True
    except Exception:
        return False


def _configure_prescribed_displacement_harmonic(
    pd: Any,
    settings: HuBaiComsolSettings,
) -> None:
    """COMSOL 5.6 Displacement2: Direction is a length-3 on/off vector (not U0 alone)."""
    axis = settings.excitation_axis.lower()
    idx = {"x": 0, "y": 1, "z": 2}.get(axis, 2)
    if settings.excitation_type == "acceleration":
        comp_expr = "A_base/(2*pi*freq)^2*1000"
    else:
        comp_expr = "A_disp"
    direction = ["0", "0", "0"]
    u0 = ["0", "0", "0"]
    direction[idx] = "1"
    u0[idx] = comp_expr
    pd.set("Direction", direction)
    pd.set("U0", u0)


def _add_harmonic_displacement_excitation(
    solid: Any,
    settings: HuBaiComsolSettings,
    exc_sel: str,
) -> None:
    """Prescribed displacement u = A/ω² on shaker table top (§2.4.3 振动台顶面指定加速度)."""
    pd = _create_solid_feature(
        solid,
        "base_exc",
        ("Displacement2", "PrescribedDisplacement"),
    )
    if pd is None:
        raise RuntimeError("No supported harmonic excitation feature in Solid Mechanics")
    pd.selection().named(exc_sel)
    _configure_prescribed_displacement_harmonic(pd, settings)
    _set_label(
        pd,
        f"指定位移（振动台顶面{settings.excitation_axis.upper()}向）",
    )
    print(
        "  Freq excitation: Displacement2 on shaker table top "
        f"({exc_sel}, {settings.excitation_axis.upper()}, "
        f"A_base={settings.base_acceleration_m_s2} m/s², u=A/(2πf)²)",
        flush=True,
    )


def _add_frequency_excitation(
    solid: Any,
    settings: HuBaiComsolSettings,
    exc_sel: str,
    *,
    exc_table_domain: int | None = None,
    exc_domains: list[int] | None = None,
) -> None:
    """§2.4.3 harmonic excitation on shaker table top (Frequency study).

    Paper: prescribed acceleration on the upper surface of the shaker table.
    COMSOL 5.6: Displacement2 u=A/ω² on sel_table_top (GUI-visible boundary BC).
    BodyLoad Ftot=rho*A_base on solid domains is the numerical fallback.
    """
    if settings.excitation_type == "acceleration":
        try:
            _add_harmonic_displacement_excitation(solid, settings, exc_sel)
            return
        except Exception as exc:
            print(f"  WARN: table-top Displacement2 failed ({exc})", flush=True)
        body_domains: list[int] = []
        if exc_domains:
            body_domains = [int(d) for d in exc_domains]
        elif exc_table_domain is not None:
            body_domains = [int(exc_table_domain)]
        if body_domains and _add_bodyload_acceleration_excitation(
            solid, settings, body_domains
        ):
            print(
                "  WARN: using BodyLoad fallback on solid domain(s) "
                f"{body_domains} (boundary excitation preferred per §2.4.3)",
                flush=True,
            )
            return
        raise RuntimeError("No supported harmonic excitation on shaker table top")
    else:
        pd = _create_solid_feature(solid, "base_exc", ("Displacement2", "PrescribedDisplacement"))
        if pd is None:
            raise RuntimeError("Displacement2 not available in Solid Mechanics")
        pd.selection().named(exc_sel)
        _configure_prescribed_displacement_harmonic(pd, settings)
        _set_label(pd, f"指定位移（{settings.excitation_axis.upper()}向）")


def _add_boundary_conditions(
    comp: Any,
    solid: Any,
    settings: HuBaiComsolSettings,
    *,
    java: Any | None = None,
    exc_table_domain: int | None = None,
    exc_domains: list[int] | None = None,
    d_tbl: int | None = None,
    geom_tag: str = LATTICE_GEOM,
) -> None:
    band = settings.selection_band_mm
    z_min = settings.z_min_mm
    z_max = settings.z_max_mm
    z_plt_bot = _plate_z_bottom_mm(settings)
    half_lat = settings.half_xy_mm
    plt_t = settings.top_plate_thickness_mm

    if settings.include_shaker_fixture:
        z_tbl_bot = settings.shaker_table_z_bottom_mm
        face_band = min(settings.selection_band_mm, 0.05)
        _horizontal_face_box_selection(
            comp,
            "sel_table_bottom",
            half_xy=settings.shaker_half_xy_mm,
            z_mm=z_tbl_bot,
            band_mm=face_band,
        )
        _table_top_excitation_selection(
            comp,
            settings,
            d_tbl=d_tbl if d_tbl is not None else settings.domain_shaker_table,
            geom_tag=geom_tag,
        )
        _horizontal_face_box_selection(
            comp,
            "sel_plate_top",
            half_xy=settings.top_plate_half_xy_mm,
            z_mm=z_plt_bot + plt_t,
            band_mm=face_band,
        )
        _log_boundary_selection(comp, "sel_table_bottom", "table bottom (fixed)")
        _log_boundary_selection(comp, "sel_table_top", "table top (excitation)")
        _log_boundary_selection(comp, "sel_plate_top", "plate top")
        fix_sel = "sel_table_bottom"
        exc_sel = "sel_table_top"  # §2.4.3: 振动台顶面（输入端）指定加速度
        probe_base = "sel_table_top"
        probe_top = "sel_plate_top"
    else:
        _box_selection(comp, "sel_base", half_xy=half_lat, z0=z_min, z1=z_min, band=band)
        _box_selection(comp, "sel_top", half_xy=half_lat, z0=z_max, z1=z_max, band=band)
        fix_sel = "sel_base"
        exc_sel = "sel_base"
        probe_base = "sel_base"
        probe_top = "sel_top"

    if settings.run_eigen or settings.run_frequency:
        # Table bottom only — do not fix side faces (matches thesis test fixture).
        fix = solid.create("fixbase", "Fixed", jpype.JInt(2))
        fix.selection().named(fix_sel)
        _set_label(fix, "固定约束（振动台底面）")

    if settings.run_frequency:
        _add_frequency_excitation(
            solid,
            settings,
            exc_sel,
            exc_table_domain=exc_table_domain,
            exc_domains=exc_domains,
        )
        _add_boundary_probes(
            comp, settings, base_sel=probe_base, top_sel=probe_top, java=java
        )


def _add_participation_factors(comp: Any, settings: HuBaiComsolSettings) -> str:
    """Participation Factors for effective modal mass along excitation axis (COMSOL SME)."""
    tag = settings.eigen_mpf_tag
    try:
        common = comp.common()
        existing = [str(t) for t in common.tags()]
        if tag in existing:
            return tag
        common.create(tag, "ParticipationFactors")
        print(f"  ParticipationFactors: {tag} (common)", flush=True)
        return tag
    except Exception as exc:
        print(f"  WARN: ParticipationFactors not created ({exc})", flush=True)
    return tag


def _add_top_payload_mass(
    solid: Any,
    comp: Any,
    settings: HuBaiComsolSettings,
) -> None:
    """300 g experimental payload on output plate top (Table 3.3).

    COMSOL 5.6 Solid Mechanics: try AddedMass / MassLoad on sel_plate_top.
    """
    if not settings.include_top_payload or settings.top_payload_mass_kg <= 0.0:
        return
    z_top = _plate_z_bottom_mm(settings) + settings.top_plate_thickness_mm
    mass = settings.top_payload_mass_kg
    created = False
    feat_used = ""

    attempts: list[tuple[str, int]] = [
        ("AddedMass", 2),
        ("BoundaryMass", 2),
        ("MassLoad", 2),
    ]
    for feat_name, dim in attempts:
        try:
            am = solid.create("pm_payload", feat_name, jpype.JInt(dim))
            am.selection().named("sel_plate_top")
            for key in ("M", "m", "mass", "Mass", "Mtot"):
                try:
                    am.set(key, f"{mass}[kg]")
                    created = True
                    feat_used = feat_name
                    break
                except Exception:
                    continue
            if created:
                break
            solid.remove("pm_payload")
        except Exception:
            try:
                solid.remove("pm_payload")
            except Exception:
                pass
            continue

    if not created:
        # Fallback: lump 300 g into plate domain density (COMSOL 5.6 API limit).
        vol_m3 = (
            settings.top_plate_xy_mm * settings.top_plate_xy_mm * settings.top_plate_thickness_mm
        ) * 1e-9
        eff_rho = settings.top_plate_density_kg_m3 + mass / vol_m3
        d_plt = settings.domain_top_plate
        _set_material(
            comp,
            "mat_plt_stack",
            d_plt,
            youngs="E_plate",
            poisson=str(settings.top_plate_poisson),
            density=f"{eff_rho}[kg/m^3]",
        )
        print(
            f"  Top payload fallback: {mass} kg merged into plate density "
            f"(rho={eff_rho:.1f} kg/m^3, was {settings.top_plate_density_kg_m3})",
            flush=True,
        )
        return
    print(
        f"  Top payload: {mass} kg on plate top (z={z_top} mm, feature={feat_used})",
        flush=True,
    )


def _set_domain_hauto(
    mesh: Any,
    tag: str,
    domain: int,
    hauto: int,
    *,
    geom_tag: str,
    label: str = "",
) -> Any:
    """COMSOL physics-controlled Size on one 3D domain (hauto level, no manual hmax)."""
    size = mesh.create(tag, "Size")
    size.set("hauto", str(int(hauto)))
    try:
        size.set("customsizeactive", False)
    except Exception:
        pass
    domains = jpype.JArray(jpype.JInt)([int(domain)])
    sel = size.selection()
    try:
        sel.geom(geom_tag, jpype.JInt(3)).set(domains)
    except Exception:
        sel.geom(jpype.JInt(3)).set(domains)
    if label:
        _set_label(size, label)
    return size


def _mesh_hmin_mm(hmax_mm: float) -> float:
    """Keep hmin < hmax for COMSOL Size (avoids hauto default hmin > thin hmax)."""
    return max(min(0.2 * hmax_mm, hmax_mm * 0.45), 0.01)


def _apply_explicit_mesh_bounds(
    size: Any,
    hmax_mm: float,
    hmin_mm: float | None = None,
) -> None:
    hmin = hmin_mm if hmin_mm is not None else _mesh_hmin_mm(hmax_mm)
    try:
        size.set("customsizeactive", True)
        size.set("hauto", 9)  # COMSOL: Custom (explicit hmax/hmin)
    except Exception:
        pass
    try:
        size.set("hmaxactive", True)
        size.set("hmax", f"{hmax_mm}[mm]")
        size.set("hminactive", True)
        size.set("hmin", f"{hmin}[mm]")
    except Exception:
        size.set("hmax", f"{hmax_mm}[mm]")


def _set_domain_mesh_size(
    mesh: Any,
    tag: str,
    domain: int,
    hmax_mm: float,
    *,
    geom_tag: str = "geom1",
    hmin_mm: float | None = None,
) -> Any:
    """Assign explicit hmax/hmin to one 3D domain."""
    size = mesh.create(tag, "Size")
    _apply_explicit_mesh_bounds(size, hmax_mm, hmin_mm)
    domains = jpype.JArray(jpype.JInt)([int(domain)])
    sel = size.selection()
    try:
        sel.geom(geom_tag, jpype.JInt(3)).set(domains)
    except Exception:
        sel.geom(jpype.JInt(3)).set(domains)
    return size


def _set_domain_mesh_hauto(
    mesh: Any,
    tag: str,
    domain: int,
    hauto: int,
    *,
    geom_tag: str = "geom1",
    hmax_mm: float | None = None,
    hmin_mm: float | None = None,
    label: str = "",
) -> Any:
    """Physics-controlled element size preset on one 3D domain."""
    if hmax_mm is not None:
        return _set_domain_mesh_size(
            mesh,
            tag,
            domain,
            hmax_mm,
            geom_tag=geom_tag,
            hmin_mm=hmin_mm,
        )
    return _set_domain_hauto(
        mesh, tag, domain, hauto, geom_tag=geom_tag, label=label
    )


def _deactivate_mesh_features(features: list[Any]) -> None:
    for feat in features:
        try:
            feat.active(False)
        except Exception:
            pass


def _ftet_domains(
    mesh: Any, tag: str, domains: list[int], geom_tag: str, *, label: str = ""
) -> Any:
    """FreeTet on explicit 3D domains (required to avoid meshing other unmeshed domains)."""
    ftet = mesh.create(tag, "FreeTet")
    arr = jpype.JArray(jpype.JInt)([int(d) for d in domains])
    sel = ftet.selection()
    try:
        sel.geom(geom_tag, jpype.JInt(3)).set(arr)
    except Exception:
        sel.geom(jpype.JInt(3)).set(arr)
    if label:
        _set_label(ftet, label)
    return ftet


def _mesh_domain_step(
    mesh: Any,
    settings: HuBaiComsolSettings,
    *,
    size_tag: str,
    ftet_tag: str,
    domain: int,
    hmax_mm: float,
    geom_tag: str,
    label: str,
    prior_sizes: list[Any],
    prior_ftets: list[Any],
) -> tuple[Any, Any]:
    """Mesh one domain; deactivate prior Size nodes only (keep FreeTet mesh)."""
    _deactivate_mesh_features(prior_sizes)
    if label == "lattice":
        size = _set_lattice_mesh_size(
            mesh, size_tag, domain, settings, geom_tag=geom_tag
        )
        print(
            f"  FreeTet domain {domain} ({label}), hmax={settings.mesh_mm} mm...",
            flush=True,
        )
    else:
        size = _set_domain_mesh_size(mesh, size_tag, domain, hmax_mm, geom_tag=geom_tag)
        print(f"  FreeTet domain {domain} ({label}), hmax={hmax_mm} mm...", flush=True)
    ftet = _ftet_domains(mesh, ftet_tag, [domain], geom_tag)
    mesh.run()
    return size, ftet


def _mesh_fixture_stack_step(
    mesh: Any,
    settings: HuBaiComsolSettings,
    *,
    comp: Any,
    geom_tag: str,
    d_tbl: int,
    d_plt: int,
    prior_sizes: list[Any],
    prior_ftets: list[Any],
) -> tuple[list[Any], list[Any]]:
    """Mesh shaker table then top plate (separate FreeTet passes; lattice stays unmeshed)."""
    all_sizes: list[Any] = []
    all_ftets: list[Any] = []

    _deactivate_mesh_features(prior_sizes)
    tbl_size = _set_domain_mesh_size(
        mesh, "size_tbl", d_tbl, settings.shaker_mesh_mm, geom_tag=geom_tag
    )
    tbl_sizes = [tbl_size]
    if settings.table_contact_refine:
        try:
            tbl_size.set("hauto", 9)
            tbl_size.set("customsizeactive", True)
        except Exception:
            pass
        tbl_sizes.extend(
            _add_table_contact_mesh_sizes(mesh, comp, settings, tbl_size=tbl_size)
        )
    print(
        f"  FreeTet domain {d_tbl} (table), hmax={settings.shaker_mesh_mm} mm...",
        flush=True,
    )
    ftet_tbl = _ftet_domains(mesh, "ftet_tbl", [d_tbl], geom_tag)
    mesh.run()
    all_sizes.extend(tbl_sizes)
    all_ftets.append(ftet_tbl)
    _log_mesh_stats(comp, str(mesh.tag()), enforce_limit=False)

    _deactivate_mesh_features(all_sizes)
    plt_size, plate_hmax, plate_hmin = _set_plate_mesh_size(
        mesh, "size_plt", d_plt, settings, geom_tag=geom_tag
    )
    print(
        f"  FreeTet domain {d_plt} (plate), hmax={plate_hmax} mm, hmin={plate_hmin} mm...",
        flush=True,
    )
    ftet_plt = _ftet_domains(mesh, "ftet_plt", [d_plt], geom_tag)
    mesh.run()
    all_sizes.append(plt_size)
    all_ftets.append(ftet_plt)

    return all_sizes, all_ftets


def _keep_default_discretization(comp: Any, solid: Any) -> None:
    """Keep COMSOL default quadratic solid-mechanics discretization (§2.4.3)."""
    _ = (comp, solid)
    print("  Discretization: COMSOL default (quadratic)", flush=True)


def _log_mesh_stats(comp: Any, mesh_tag: str = "mesh1", *, enforce_limit: bool = True) -> None:
    mesh = comp.mesh(mesh_tag)
    try:
        n_elem = int(mesh.getNumElem())
        n_vert = int(mesh.getNumVertex())
        second_order = bool(mesh.hasSecondOrderElements())
        print(
            f"  Mesh stats: {n_elem} elements, {n_vert} vertices, "
            f"second_order={second_order}",
            flush=True,
        )
        if enforce_limit and n_elem > 2_500_000:
            raise RuntimeError(
                f"Mesh too large ({n_elem} elements > 2.5M): "
                "check domain-scoped Size/FreeTet — do not mesh full assembly in one pass"
            )
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"  Mesh stats unavailable: {exc}", flush=True)


def _plate_mesh_hmax_mm(settings: HuBaiComsolSettings) -> float:
    """Thin plate: hmax ≈ sheet thickness (≥1 layer), not lattice-scale refinement."""
    t = settings.top_plate_thickness_mm
    return min(settings.top_plate_mesh_mm, max(t, 0.25))


def _plate_mesh_hmin_mm(settings: HuBaiComsolSettings, hmax_mm: float) -> float:
    """Allow short imprint edges on 0.5 mm plate without min-size warnings."""
    t = settings.top_plate_thickness_mm
    return max(min(t / 20.0, 0.1 * hmax_mm), 0.001)


def _set_lattice_mesh_size(
    mesh: Any,
    tag: str,
    domain: int,
    settings: HuBaiComsolSettings,
    *,
    geom_tag: str = "geom1",
) -> Any:
    """Fig. 2.8 fine lattice mesh (0.6 mm) + narrow-region resolve for 2 mm struts."""
    hmax = settings.mesh_mm
    hmin = max(0.06, 0.1 * hmax)
    size = _set_domain_mesh_size(
        mesh, tag, domain, hmax, geom_tag=geom_tag, hmin_mm=hmin
    )
    for prop, val in (("hnarrowactive", True), ("hnarrow", "1")):
        try:
            size.set(prop, val)
        except Exception:
            pass
    return size


def _set_plate_mesh_size(
    mesh: Any,
    tag: str,
    domain: int,
    settings: HuBaiComsolSettings,
    *,
    geom_tag: str = "geom1",
) -> tuple[Any, float, float]:
    hmax = _plate_mesh_hmax_mm(settings)
    hmin = _plate_mesh_hmin_mm(settings, hmax)
    size = _set_domain_mesh_size(
        mesh, tag, domain, hmax, geom_tag=geom_tag, hmin_mm=hmin
    )
    for prop, val in (("hnarrowactive", True), ("hnarrow", "0.5")):
        try:
            size.set(prop, val)
        except Exception:
            pass
    return size, hmax, hmin


def _build_physics_controlled_mesh(
    comp: Any,
    mesh_tag: str,
    settings: HuBaiComsolSettings,
) -> None:
    """COMSOL physics-controlled mesh (automatic sequence, no manual Size/FreeTet)."""
    mesh = comp.mesh(mesh_tag)
    mesh.automatic(True)
    mesh.autoMeshSize(int(settings.lattice_hauto))
    mesh.run()
    print(
        f"  Physics-controlled mesh: automatic=True, autoMeshSize={settings.lattice_hauto}",
        flush=True,
    )
    _log_mesh_stats(comp, mesh_tag)


def _build_physics_controlled_mesh_split(
    comp: Any,
    mesh_tag: str,
    settings: HuBaiComsolSettings,
    *,
    geom_tag: str,
    d_lat: int,
    d_tbl: int,
    d_plt: int,
) -> None:
    """Domain-scoped Size + FreeTet per part; one mesh.run() — all nodes stay enabled (no gray).

    Each FreeTet targets one domain only, so lattice hauto=4 does not bleed into the
    400 mm shaker block (unlike a single global FreeTet on the full assembly).
    """
    mesh = comp.mesh(mesh_tag)

    _set_domain_mesh_hauto(
        mesh,
        "size_tbl",
        d_tbl,
        settings.fixture_hauto,
        geom_tag=geom_tag,
        label=LABEL_MESH_SIZE_TABLE,
    )
    _ftet_domains(
        mesh, "ftet_tbl", [d_tbl], geom_tag, label=LABEL_MESH_FTET_TABLE
    )

    plt_size, plate_hmax, plate_hmin = _set_plate_mesh_size(
        mesh, "size_plt", d_plt, settings, geom_tag=geom_tag
    )
    _set_label(plt_size, LABEL_MESH_SIZE_PLATE)
    _ftet_domains(
        mesh, "ftet_plt", [d_plt], geom_tag, label=LABEL_MESH_FTET_PLATE
    )

    _set_domain_mesh_hauto(
        mesh,
        "size_lat",
        d_lat,
        settings.lattice_hauto,
        geom_tag=geom_tag,
        label=LABEL_MESH_SIZE_LAT,
    )
    _ftet_domains(
        mesh, "ftet_lat", [d_lat], geom_tag, label=LABEL_MESH_FTET_LAT
    )

    print(
        f"  Split mesh (single run): table hauto={settings.fixture_hauto}, "
        f"plate hmax={plate_hmax} mm, lattice hauto={settings.lattice_hauto}",
        flush=True,
    )
    mesh.run()
    _log_mesh_stats(comp, mesh_tag)


def _mesh_fixture_component(comp: Any, settings: HuBaiComsolSettings) -> None:
    """Mesh table (domain 1) + plate (domain 2) in comp_fixture template."""
    comp.mesh().create("mesh1", "geom1")
    _set_label(comp.mesh("mesh1"), LABEL_MESH)
    if settings.physics_controlled_mesh:
        mesh = comp.mesh("mesh1")
        tbl_size = _set_domain_mesh_hauto(
            mesh,
            "size_tbl",
            1,
            settings.fixture_hauto,
            geom_tag="geom1",
            label=LABEL_MESH_SIZE_TABLE,
        )
        if settings.table_contact_refine:
            _add_table_contact_mesh_sizes(mesh, comp, settings, tbl_size=tbl_size)
        _ftet_domains(
            mesh, "ftet_tbl", [1], "geom1", label=LABEL_MESH_FTET_TABLE
        )
        mesh.run()
        _deactivate_mesh_features([tbl_size])
        _set_domain_mesh_hauto(
            mesh,
            "size_plt",
            2,
            settings.fixture_hauto,
            geom_tag="geom1",
            label=LABEL_MESH_SIZE_PLATE,
        )
        _ftet_domains(
            mesh, "ftet_plt", [2], "geom1", label=LABEL_MESH_FTET_PLATE
        )
        mesh.run()
        print(
            f"  Fixture template mesh: table/plate hauto={settings.fixture_hauto}",
            flush=True,
        )
        _log_mesh_stats(comp, "mesh1")
        return
    mesh = comp.mesh("mesh1")
    tbl_size = _set_domain_mesh_hauto(
        mesh, "size_tbl", 1, settings.fixture_hauto, geom_tag="geom1"
    )
    print(
        f"  FreeTet domain 1 (table), hauto={settings.fixture_hauto}...",
        flush=True,
    )
    _ftet_domains(mesh, "ftet_tbl", [1], "geom1")
    mesh.run()
    plt_size, plate_hmax, plate_hmin = _set_plate_mesh_size(
        mesh, "size_plt", 2, settings, geom_tag="geom1"
    )
    print(
        f"  FreeTet domain 2 (plate), hmax={plate_hmax} mm, hmin={plate_hmin} mm...",
        flush=True,
    )
    _ftet_domains(mesh, "ftet_plt", [2], "geom1")
    mesh.run()
    print(
        f"  Fixture template mesh: table hauto={settings.fixture_hauto}, "
        f"plate hmax={plate_hmax} mm, hmin={plate_hmin} mm",
        flush=True,
    )
    _log_mesh_stats(comp, "mesh1", enforce_limit=False)


def _copy_fixture_mesh_to_main(
    main_comp: Any,
    fixture_comp: Any,
    settings: HuBaiComsolSettings,
    *,
    dest_geom: str = LATTICE_GEOM,
    main_mesh_tag: str = LATTICE_MESH,
    d_tbl: int | None = None,
    d_plt: int | None = None,
) -> None:
    """Copy pre-meshed table/plate from comp_fixture → main component domains."""
    main_mesh = main_comp.mesh(main_mesh_tag)
    dst_tbl = settings.domain_shaker_table if d_tbl is None else d_tbl
    dst_plt = settings.domain_top_plate if d_plt is None else d_plt
    mappings = (
        (1, dst_tbl, LABEL_MESH_COPY_TABLE),
        (2, dst_plt, LABEL_MESH_COPY_PLATE),
    )
    for src_dom, dst_dom, copy_label in mappings:
        tag = f"copy_d{dst_dom}"
        cpy = main_mesh.create(tag, "Copy")
        _set_label(cpy, copy_label)
        cpy.set("mesh", "mesh1")
        try:
            cpy.set("component", "comp_fixture")
        except Exception:
            pass
        cpy.set("dimension", jpype.JInt(3))
        cpy.selection("source").geom("geom1", jpype.JInt(3))
        cpy.selection("source").set(jpype.JArray(jpype.JInt)([int(src_dom)]))
        cpy.selection("destination").geom(dest_geom, jpype.JInt(3))
        cpy.selection("destination").set(jpype.JArray(jpype.JInt)([int(dst_dom)]))
        print(f"  Mesh copy comp_fixture d{src_dom} → comp1 d{dst_dom}", flush=True)
    _ = fixture_comp


def _ftet_domain(mesh: Any, tag: str, domain: int, geom_tag: str) -> None:
    """FreeTet on one 3D domain."""
    _ftet_domains(mesh, tag, [domain], geom_tag)


def _ensure_lattice_mesh(comp: Any, geom_tag: str) -> str:
    """Dedicated mesh sequence bound to geom_lat."""
    comp.mesh().create(LATTICE_MESH, geom_tag)
    _set_label(comp.mesh(LATTICE_MESH), LABEL_MESH)
    return LATTICE_MESH


def _flatten_fixture_after_mesh(java: Any, main_comp: Any, mesh_tag: str) -> None:
    """Remove temporary comp_fixture; keep labeled Copy nodes on comp1."""
    try:
        if "comp_fixture" in [str(t) for t in java.component().tags()]:
            java.component().remove("comp_fixture")
            print("  Removed comp_fixture (mesh retained on comp1)", flush=True)
    except Exception as exc:
        print(f"  WARN: could not remove comp_fixture: {exc}", flush=True)


def _build_mesh(
    comp: Any,
    settings: HuBaiComsolSettings,
    *,
    fixture_comp: Any | None = None,
    geom_tag: str = "geom1",
    d_lat: int | None = None,
    d_tbl: int | None = None,
    d_plt: int | None = None,
) -> None:
    d_lat = settings.domain_lattice if d_lat is None else d_lat
    d_tbl = settings.domain_shaker_table if d_tbl is None else d_tbl
    d_plt = settings.domain_top_plate if d_plt is None else d_plt
    mesh_tag = _ensure_lattice_mesh(comp, geom_tag)
    try:
        _set_label(comp.mesh(mesh_tag).feature("size"), "全局默认大小")
    except Exception:
        pass
    _ = fixture_comp

    if settings.physics_controlled_mesh:
        if settings.include_shaker_fixture:
            _build_physics_controlled_mesh_split(
                comp,
                mesh_tag,
                settings,
                geom_tag=geom_tag,
                d_lat=d_lat,
                d_tbl=d_tbl,
                d_plt=d_plt,
            )
        else:
            _build_physics_controlled_mesh(comp, mesh_tag, settings)
        return

    mesh = comp.mesh(mesh_tag)

    if settings.include_shaker_fixture and fixture_comp is not None:
        _copy_fixture_mesh_to_main(
            comp,
            fixture_comp,
            settings,
            dest_geom=geom_tag,
            main_mesh_tag=mesh_tag,
            d_tbl=d_tbl,
            d_plt=d_plt,
        )
        prior_sizes: list[Any] = []
        prior_ftets: list[Any] = []
        size_lat, ftet_lat = _mesh_domain_step(
            mesh,
            settings,
            size_tag="size_lat",
            ftet_tag="ftet_lat",
            domain=d_lat,
            hmax_mm=settings.mesh_mm,
            geom_tag=geom_tag,
            label="lattice",
            prior_sizes=prior_sizes,
            prior_ftets=prior_ftets,
        )
        prior_sizes.append(size_lat)
        prior_ftets.append(ftet_lat)
        _log_mesh_stats(comp, mesh_tag)
        return

    if settings.include_shaker_fixture:
        prior_sizes = []
        prior_ftets: list[Any] = []
        fixture_sizes, ftet_fixture = _mesh_fixture_stack_step(
            mesh,
            settings,
            comp=comp,
            geom_tag=geom_tag,
            d_tbl=d_tbl,
            d_plt=d_plt,
            prior_sizes=prior_sizes,
            prior_ftets=prior_ftets,
        )
        prior_sizes.extend(fixture_sizes)
        prior_ftets.extend(ftet_fixture)
        _log_mesh_stats(comp, mesh_tag, enforce_limit=False)
        size_lat, ftet_lat = _mesh_domain_step(
            mesh,
            settings,
            size_tag="size_lat",
            ftet_tag="ftet_lat",
            domain=d_lat,
            hmax_mm=settings.mesh_mm,
            geom_tag=geom_tag,
            label="lattice",
            prior_sizes=prior_sizes,
            prior_ftets=prior_ftets,
        )
        prior_sizes.append(size_lat)
        prior_ftets.append(ftet_lat)
        _log_mesh_stats(comp, mesh_tag)
    else:
        size = mesh.create("size1", "Size")
        size.set("hmax", f"{settings.mesh_mm}[mm]")
        size.selection().geom(jpype.JInt(3)).all()
        mesh.create("ftet1", "FreeTet")
        mesh.run()
        _log_mesh_stats(comp, mesh_tag)


def build_fixture_template_mph(
    settings: HuBaiComsolSettings,
    *,
    out_mph: Path | str | None = None,
    comsol_bin: str | None = None,
    cores: int = 4,
) -> Path:
    """Build reusable meshed fixture (table + plate only) for 4×4×4 array."""
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)

    out = Path(out_mph) if out_mph else settings.fixture_template_mph
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"  Building fixture template: {out}", flush=True)
    client = mph.start(cores=cores)
    model = client.create("comsol_fixture_444")
    java = model.java

    java.param().set("E_table", f"{settings.shaker_table_youngs_gpa}[GPa]")
    java.param().set("E_plate", f"{settings.top_plate_youngs_gpa}[GPa]")

    java.component().create("comp_fixture", True)
    comp = java.component("comp_fixture")
    _ensure_geom1(comp)
    _add_table_plate_blocks(comp, settings)
    geom = comp.geom("geom1")
    if "fin" not in [str(t) for t in geom.feature().tags()]:
        geom.feature().create("fin", "FormUnion")
    geom.run()

    _set_material(comp, "mat_table", 1, youngs="E_table", poisson=str(settings.shaker_table_poisson),
                  density=f"{settings.shaker_table_density_kg_m3}[kg/m^3]")
    _set_material(comp, "mat_plate", 2, youngs="E_plate", poisson=str(settings.top_plate_poisson),
                  density=f"{settings.top_plate_density_kg_m3}[kg/m^3]")

    _mesh_fixture_component(comp, settings)
    model.save(out)
    print(f"  Saved fixture template: {out}", flush=True)
    client.remove(model)
    return out


def _prepare_inline_fixture_component(
    java: Any,
    settings: HuBaiComsolSettings,
) -> Any:
    """Mesh table+plate in isolated comp_fixture (prevents lattice mesh bleed)."""
    if "comp_fixture" not in [str(t) for t in java.component().tags()]:
        java.component().create("comp_fixture", True)
    comp = java.component("comp_fixture")
    _set_label(comp, LABEL_COMP_FIXTURE)
    _ensure_geom1(comp)
    _set_label(comp.geom("geom1"), LABEL_GEOM)
    geom = comp.geom("geom1")
    if "blk_table" not in [str(t) for t in geom.feature().tags()]:
        _add_table_plate_blocks(comp, settings)
    if "fin" not in [str(t) for t in geom.feature().tags()]:
        geom.feature().create("fin", "FormUnion")
    geom.run()
    _set_material(
        comp,
        "mat_table",
        1,
        youngs="E_table",
        poisson=str(settings.shaker_table_poisson),
        density=f"{settings.shaker_table_density_kg_m3}[kg/m^3]",
    )
    _set_material(
        comp,
        "mat_plate",
        2,
        youngs="E_plate",
        poisson=str(settings.top_plate_poisson),
        density=f"{settings.top_plate_density_kg_m3}[kg/m^3]",
    )
    _mesh_fixture_component(
        comp,
        replace(settings, table_contact_refine=False),
    )
    print("  Inline fixture: comp_fixture meshed (table+plate isolated)", flush=True)
    return comp


def build_mph_from_step(
    settings: HuBaiComsolSettings,
    step_path: Path | str,
    *,
    out_mph: Path | str | None = None,
    comsol_bin: str | None = None,
    cores: int = 4,
) -> Path:
    """Import STEP lattice, optional Fig.2.8 fixture, mesh, studies, save .mph."""
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)

    step = Path(step_path).resolve()
    if not step.is_file():
        raise FileNotFoundError(f"STEP not found: {step}")

    slug = settings.default_slug()
    job_dir = settings.job_dir()
    job_dir.mkdir(parents=True, exist_ok=True)
    out = Path(out_mph) if out_mph else job_dir / f"{slug}.mph"

    template_path = settings.fixture_template_mph
    # Full Fig. 2.8 build: fresh model + inline fixture on comp1 (template load wastes RAM).

    print(f"  MPh: starting COMSOL (cores={cores})...", flush=True)
    client = mph.start(cores=cores)
    model = client.create(slug)
    java = model.java
    fixture_comp = None

    if "comp1" not in [str(t) for t in java.component().tags()]:
        java.component().create("comp1", True)
    comp = java.component("comp1")
    _set_label(comp, LABEL_COMP_MAIN)
    lat_geom = _ensure_lattice_geom(comp)
    _set_label(comp.geom(lat_geom), LABEL_GEOM)

    java.param().set("E_mpa", f"{settings.youngs_modulus_mpa}[MPa]")
    java.param().set("nu", str(settings.poisson))
    java.param().set("rho", f"{settings.density_kg_m3}[kg/m^3]")
    java.param().set("A_base", f"{settings.base_acceleration_m_s2}[m/s^2]")
    java.param().set("A_disp", f"{settings.base_displacement_mm}[mm]")
    java.param().set("freq", "10[Hz]")
    if settings.include_shaker_fixture:
        java.param().set("E_table", f"{settings.shaker_table_youngs_gpa}[GPa]")
        java.param().set("E_plate", f"{settings.top_plate_youngs_gpa}[GPa]")

    imp = comp.geom(lat_geom).feature().create("imp1", "Import")
    _set_label(imp, LABEL_GEOM_LATTICE_STEP)
    imp.set("type", "cad")
    imp.set("filename", str(step))
    imp.set("unit", "source")
    comp.geom(lat_geom).run()
    _center_paper_box_import(comp, lat_geom, settings)

    if settings.include_shaker_fixture:
        _clip_lattice_top_to_nominal(comp, settings, geom=lat_geom)
        plate_z = _resolve_plate_z_bottom_mm(settings, comp=comp, geom_tag=lat_geom)
        settings.extra["plate_z_bottom_mm"] = plate_z
        if not settings.skip_mesh and not settings.physics_controlled_mesh:
            fixture_comp = _prepare_inline_fixture_component(java, settings)
        _log_fixture_stack(settings)
        _add_shaker_fixture_geometry(comp, settings, geom=lat_geom)

    _log_geometry_domains(comp, settings, geom=lat_geom)
    if settings.include_shaker_fixture:
        d_lat, d_tbl, d_plt = _resolve_fixture_domains(comp, settings, geom=lat_geom)
    else:
        d_lat = settings.domain_lattice
        d_tbl = settings.domain_shaker_table
        d_plt = settings.domain_top_plate
    _assign_materials(comp, settings, d_lat=d_lat, d_tbl=d_tbl, d_plt=d_plt)

    comp.physics().create("solid", "SolidMechanics", lat_geom)
    solid = comp.physics("solid")
    _set_label(solid, LABEL_PHYSICS_SOLID)
    _keep_default_discretization(comp, solid)

    if settings.lattice_material_model.lower() in (
        "marlow_uniaxial",
        "marlow",
        "hyperelastic_marlow",
        "fig25",
    ):
        # COMSOL 5.6: Marlow hyperelastic harmonic/eigen need LE tangent (no lambLame in batch).
        _configure_lattice = (
            configure_lattice_eigen_linearized_physics
            if settings.run_frequency or (settings.run_eigen and not settings.run_frequency)
            else configure_lattice_hyperelastic_physics
        )
        _configure_lattice(
            solid,
            d_lat=d_lat,
            d_tbl=d_tbl if settings.include_shaker_fixture else None,
            d_plt=d_plt if settings.include_shaker_fixture else None,
            include_fixture=settings.include_shaker_fixture,
            youngs_mpa=float(settings.youngs_modulus_mpa),
            poisson=float(settings.poisson),
        )
    _remove_default_solid_features(solid)

    if settings.include_shaker_fixture:
        _add_fixture_contacts(
            comp,
            settings,
            solid,
            geom_tag=lat_geom,
            d_lat=d_lat,
            d_plt=d_plt,
            d_tbl=d_tbl,
        )

    if settings.include_shaker_fixture:
        exc_table_domain = d_tbl
        exc_domains = [d_tbl, d_lat, d_plt]
    else:
        exc_table_domain = d_lat
        exc_domains = [d_lat]
    _add_boundary_conditions(
        comp,
        solid,
        settings,
        java=java,
        exc_table_domain=exc_table_domain,
        exc_domains=exc_domains,
        d_tbl=d_tbl if settings.include_shaker_fixture else None,
        geom_tag=lat_geom,
    )
    if settings.include_shaker_fixture:
        _add_top_payload_mass(solid, comp, settings)
    if settings.skip_mesh:
        print("  Mesh: skipped (geometry + physics only)", flush=True)
    else:
        _build_mesh(
            comp,
            settings,
            fixture_comp=fixture_comp,
            geom_tag=lat_geom,
            d_lat=d_lat,
            d_tbl=d_tbl,
            d_plt=d_plt,
        )

    if settings.run_eigen:
        _add_participation_factors(comp, settings)
        java.study().create(settings.study_eigen_tag)
        _set_label(java.study(settings.study_eigen_tag), LABEL_STUDY_EIGEN)
        eigen = java.study(settings.study_eigen_tag).create(
            settings.eigen_feature_tag, "Eigenfrequency"
        )
        _set_label(eigen, "本征频率求解")
        eigen.set("neigs", str(settings.n_eigenmodes))
        eigen.set("eigwhich", settings.eigen_search)
        try:
            eigen.set("eigmethod", "manual")
        except Exception:
            pass
        eigen.set("shiftactive", "off")
        if settings.eigen_shift_hz is not None:
            eigen.set("shiftactive", "on")
            eigen.set("shift", f"{settings.eigen_shift_hz}[Hz]")
        else:
            try:
                eigen.set("shift", "0")
            except Exception:
                pass
        print(
            f"  Eigen study: neigs={settings.n_eigenmodes}, "
            f"eigwhich={settings.eigen_search}, shift={settings.eigen_shift_hz} Hz",
            flush=True,
        )
        if settings.run_frequency:
            _activate_study_features(
                eigen,
                _eigen_study_physics_activations(settings),
            )

    if settings.run_frequency:
        java.study().create(settings.study_freq_tag)
        _set_label(java.study(settings.study_freq_tag), LABEL_STUDY_FREQ)
        freq = java.study(settings.study_freq_tag).create(
            settings.freq_feature_tag, "Frequency"
        )
        _set_label(freq, "频率扫频求解")
        freq.set("plist", settings.freq_list_expression())
        try:
            freq.set("probes", True)
        except Exception:
            pass
        try:
            freq.set("probetable", True)
        except Exception:
            pass
        _apply_freq_study_activate(freq, settings)

    model.save(out)
    print(f"  Saved model: {out}", flush=True)
    client.remove(model)
    return out


def solve_mph(
    mph_path: Path | str,
    settings: HuBaiComsolSettings,
    *,
    comsol_bin: str | None = None,
    cores: int = 4,
    studies: list[str] | None = None,
) -> Path:
    """Solve eigen and/or frequency studies via MPh."""
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)
    path = Path(mph_path).resolve()
    solved = settings.job_dir() / f"{settings.default_slug()}_solved.mph"

    tags = studies or []
    if not tags:
        if settings.run_eigen:
            tags.append(settings.study_eigen_tag)
        if settings.run_frequency:
            tags.append(settings.study_freq_tag)

    client = mph.start(cores=cores)
    model = client.load(str(path))
    for tag in tags:
        print(f"  Solving study {tag}...", flush=True)
        model.solve(tag)
    model.save(solved)
    client.remove(model)
    print(f"  Saved solution: {solved}", flush=True)
    return solved


def _disp_expr_for_axis(axis: str) -> str:
    return {"x": "u", "y": "v", "z": "w"}.get(axis.lower(), "w")


def export_eigenmode_plots(
    mph_path: Path | str,
    settings: HuBaiComsolSettings,
    *,
    n_modes: int = 3,
    min_hz: float | None = None,
    rank_by_meff: bool = True,
    comsol_bin: str | None = None,
    save_mph: bool = True,
) -> dict:
    """Create eigenmode plot groups in .mph and export PNG displacement maps."""
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)

    if min_hz is None:
        min_hz = settings.eigen_min_hz

    path = Path(mph_path).resolve()
    slug = settings.default_slug()
    job_dir = settings.job_dir()
    disp_expr = _disp_expr_for_axis(settings.excitation_axis)

    client = mph.start(cores=1)
    model = client.load(str(path))
    java = model.java

    eigen_rows = extract_eigen_rows(model, java, settings, mpf_tag=settings.eigen_mpf_tag)
    freqs = [r["frequency_Hz"] for r in eigen_rows]

    if rank_by_meff:
        ranked = rank_modes_by_meff(eigen_rows, min_hz=min_hz, n=n_modes)
        physical = [int(r["mode"]) for r in ranked]
    else:
        physical = [r["mode"] for r in eigen_rows if abs(r["frequency_Hz"]) >= min_hz]
        if not physical:
            physical = list(range(1, min(n_modes, len(freqs)) + 1))
        physical = physical[:n_modes]

    result = java.result()
    dataset = resolve_eigen_dataset(java)
    if not dataset:
        dtags = [str(t) for t in result.dataset().tags()]
        dataset = dtags[0] if dtags else ""
    if not dataset:
        raise RuntimeError("No eigen dataset in solved .mph")

    exported: list[dict] = []
    for rank, solnum in enumerate(physical[:n_modes], start=1):
        freq = freqs[solnum - 1]
        pg_tag = f"pg_mode{rank:02d}"
        for old in [str(t) for t in result.tags()]:
            if old == pg_tag or old.startswith(f"pg_export_{solnum}"):
                try:
                    result.remove(old)
                except Exception:
                    pass

        java.result().create(pg_tag, jpype.JInt(3))
        pg = java.result(pg_tag)
        pg.label(f"Mode {rank}: {freq:.2g} Hz")
        pg.set("data", dataset)
        pg.set("solnum", str(solnum))

        surf = pg.create("surf1", "Surface")
        surf.set("expr", disp_expr)
        surf.set("colortable", "AuroraBorealis")
        surf.set("resolution", "normal")
        for prop, val in (
            ("deform", "on"),
            ("scaletype", "manual"),
            ("scale", "50"),
            ("titletype", "custom"),
            ("customtitle", f"Mode {rank}: {freq:.3g} Hz ({disp_expr})"),
        ):
            for target in (pg, surf):
                try:
                    target.set(prop, val)
                    break
                except Exception:
                    continue

        pg.run()

        png = job_dir / f"{slug}_mode{rank:02d}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        exp_tag = f"exp_mode{rank:02d}"
        exp_tags = [str(t) for t in result.export().tags()]
        if exp_tag in exp_tags:
            result.export().remove(exp_tag)
        exp = result.export().create(exp_tag, "Image")
        exp.set("plotgroup", pg_tag)
        for key, val in (
            ("pngfilename", str(png.resolve())),
            ("filename", str(png.resolve())),
            ("width", "1200"),
            ("height", "900"),
            ("unit", "px"),
            ("quality", "high"),
            ("transparent", "off"),
        ):
            try:
                exp.set(key, val)
            except Exception:
                pass
        exp.run()
        exported.append(
            {
                "rank": rank,
                "solnum": solnum,
                "frequency_Hz": freq,
                "png": str(png.resolve()),
                "plot_group": pg_tag,
            }
        )
        print(f"  Mode {rank}: solnum={solnum}, f={freq:.4g} Hz → {png.name}", flush=True)

    if save_mph:
        model.save(str(path))

    meta = {
        "slug": slug,
        "mph": str(path.resolve()),
        "dataset": dataset,
        "min_hz": min_hz,
        "rank_by_meff": rank_by_meff,
        "disp_expr": disp_expr,
        "modes": exported,
    }
    meta_path = job_dir / f"{slug}_mode_shapes.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    client.remove(model)
    return meta
