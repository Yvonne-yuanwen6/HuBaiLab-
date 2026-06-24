"""
Export Hu & Bai BCC solid CAD (STEP/X_T) → meshed Abaqus compression INP.

Paper §2.4: TPU elastic-plastic, explicit quasi-static, μ=0.1, top loading plate +
fixed bottom plate (footprint larger than lattice), engineering stress–strain curve.

The Parasolid X_T from SolidWorks is the reference CAD; gmsh volume-meshes the sibling
STEP (same BREP) and writes an INP with rigid plates + general contact (Hu & Bai Fig.2.6).

  py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3 --stroke pilot
  py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --stroke full --mesh-size 0.6
  powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Stroke pilot
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.abaqus_compression import (
    CompressionSettings,
    HU_BAI_AMPLITUDE_HOLD_FRACTION,
    HU_BAI_DENSITY_KG_M3,
    HU_BAI_E_MODULUS_MPA,
    HU_BAI_EXPLICIT_DT,
    HU_BAI_EXPLICIT_MASS_SCALING,
    HU_BAI_FAST80_EXPLICIT_DT,
    HU_BAI_FAST80_MESH_MM,
    HU_BAI_FAST80_TARGET_STRAIN,
    HU_BAI_FRICTION,
    HU_BAI_LOAD_RATE_MM_MIN,
    HU_BAI_MESH_MM,
    HU_BAI_POISSON,
    HU_BAI_TARGET_ENGINEERING_STRAIN,
    HU_BAI_YIELD_MPA,
    hu_bai_compression_displacement,
    hu_bai_density_abq,
    hu_bai_neo_hooke_c10,
    hu_bai_quasi_static_step_time,
    validate_explicit_restart_inp,
)
from src.export.beam_utils import dedupe_beams
from src.export.cad_solid_paths import resolve_step_and_xt, resolve_verified_solid_step
from src.export.export_csv import export_beams, export_nodes
from src.export.export_inp import export_inp
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.mesh.solid_union import mesh_step_gmsh_tets, mesh_step_voxel_c3d8r
from src.paths import ABAQUS_JOBS, ABAQUS_POST, CAD_VERIFIED_ROOT, EXPORT_ROOT, ensure_output_dirs
from src.postprocess.compression_curve import CompressionMeta, save_compression_meta
from src.validation.penetration_risk import update_manifest_penetration_check

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Hu & Bai CAD solid → Abaqus compression INP")
_parser.add_argument("--Q", type=float, default=0.0, help="Period factor Q (0=BCC)")
_parser.add_argument("--Af", type=float, default=2.0, help="Sinusoidal amplitude A_f [mm]")
_parser.add_argument("--cells", type=int, default=3, help="Cells per axis (paper 4; use 3 for test STEP)")
_parser.add_argument(
    "--nz",
    type=int,
    default=None,
    help="Override nz (e.g. 1 for single z-slab pilot mesh); default = --cells",
)
_parser.add_argument(
    "--cad",
    type=str,
    default="",
    help="Verified STEP or X_T under output/cad/verified/ (default: auto-resolve by slug)",
)
_parser.add_argument(
    "--mesh-size",
    type=float,
    default=None,
    help="Gmsh tet size [mm] (pilot default 1.0; full/paper 0.6)",
)
_parser.add_argument(
    "--mesh-heal",
    action="store_true",
    help="Run gmsh occ.healShapes() on STEP before volume mesh",
)
_parser.add_argument(
    "--mesh-algorithm",
    type=int,
    default=None,
    help="Gmsh Mesh.Algorithm3D (1=Delaunay, 10=HXT; default 1)",
)
_parser.add_argument(
    "--mesh-method",
    choices=("tet", "voxel"),
    default="tet",
    help="tet = gmsh C3D4 volume mesh (paper); voxel = axis-aligned C3D8R brick fill",
)
_parser.add_argument(
    "--voxel-pitch",
    type=float,
    default=0.5,
    help="Voxel edge length [mm] when --mesh-method voxel (default 0.5)",
)
_parser.add_argument(
    "--strain",
    type=float,
    default=None,
    help="Target engineering strain (pilot default 0.15; full 0.70)",
)
_parser.add_argument(
    "--profile",
    choices=("fast", "paper", "pilot"),
    default=None,
    help="fast = 45%% strain, 1.2 mm, 10 mm/min, dt=5e-4; fast80 = --case-suffix fast80 (1.2 mm, 80%%, 5 mm/min, dt=5e-4); paper/pilot = full QA",
)
_parser.add_argument(
    "--stroke",
    choices=("pilot", "full"),
    default="full",
    help="full = paper 70%% strain @ 0.6 mm (default); pilot = coarse QA",
)
_parser.add_argument(
    "--contact-mode",
    choices=("pair", "coupling_nodes"),
    default="pair",
    help="pair = plate–lattice hard contact (Fig.2.6); coupling_nodes = kinematic top nodes",
)
_parser.add_argument(
    "--step-time",
    type=float,
    default=None,
    help="Override step time [s]; default = stroke / load-rate",
)
_parser.add_argument(
    "--load-rate-mm-min",
    type=float,
    default=None,
    help=f"Crosshead rate [mm/min] (default {HU_BAI_LOAD_RATE_MM_MIN:g}, paper §2.4)",
)
_parser.add_argument(
    "--explicit-dt",
    type=float,
    default=None,
    help=f"Explicit dt [s]: fixed mode = constant; automatic mode = max cap (default {HU_BAI_EXPLICIT_DT:g})",
)
_parser.add_argument(
    "--explicit-dt-mode",
    choices=("fixed", "automatic"),
    default="fixed",
    help="fixed = direct user control; automatic = stable increment with optional --explicit-dt cap",
)
_parser.add_argument(
    "--hold-fraction",
    type=float,
    default=None,
    help="Amplitude hold at zero before load (fraction of step_time; default 0.05)",
)
_parser.add_argument(
    "--case-suffix",
    type=str,
    default="",
    help="Append to slug after stroke tag, e.g. dt2e4 or qa25 (keeps separate ODB/post)",
)
_parser.add_argument(
    "--no-lattice-self-contact",
    action="store_true",
    help="Plate contact only (skip ALL EXTERIOR); lowers INP preprocessor memory for large SFBLS meshes",
)
_parser.add_argument(
    "--restart-interval",
    type=int,
    default=None,
    help="Explicit *Restart number interval (time slices in step; default 8)",
)
_parser.add_argument(
    "--bulk-viscosity-linear",
    type=float,
    default=None,
    help="*Bulk Viscosity linear coefficient (default 0.12)",
)
_parser.add_argument(
    "--bulk-viscosity-quadratic",
    type=float,
    default=None,
    help="*Bulk Viscosity quadratic coefficient (default 1.6)",
)
_parser.add_argument(
    "--material-model",
    choices=("paper", "hyperelastic", "elastic_plastic"),
    default=None,
    help="paper = Neo-Hooke TPU (§3.1); elastic_plastic = E+Plastic (§2.4.1); default: paper profile→hyperelastic, else elastic_plastic",
)
_parser.add_argument(
    "--contact-interference-fit",
    action="store_true",
    help="Explicit: treat initial overclosures as interference fit (gradual, not strain-free)",
)
_parser.add_argument(
    "--contact-init-step-fraction",
    type=float,
    default=0.15,
    help="Fraction of step to resolve interference fit (default 0.15)",
)
_args = _parser.parse_args()

PROFILE = _args.profile
if PROFILE is None:
    PROFILE = "pilot" if _args.stroke == "pilot" else "paper"

STROKE = _args.stroke
if PROFILE == "fast":
    STROKE = "full"
PILOT_STRAIN = 0.15
PILOT_MESH_MM = 1.0
FULL_MESH_MM = HU_BAI_MESH_MM
FAST_STRAIN = 0.45
FAST_MESH_MM = 1.2
FAST_LOAD_RATE_MM_MIN = 10.0
FAST_EXPLICIT_DT = 5.0e-4
FAST_HOLD_FRACTION = 0.02
# fast80 defaults: HU_BAI_FAST80_* in abaqus_compression

CASE_SUFFIX_RAW = _args.case_suffix.strip().replace(" ", "_")
IS_FAST80 = CASE_SUFFIX_RAW == "fast80"

L = 20.0
ROD_D = 2.0
AF = float(_args.Af)
Q = float(_args.Q)
NX = NY = int(_args.cells)
NZ = int(_args.nz) if _args.nz is not None else int(_args.cells)
if _args.mesh_size is not None:
    MESH_SIZE = float(_args.mesh_size)
elif IS_FAST80:
    MESH_SIZE = HU_BAI_FAST80_MESH_MM
elif PROFILE == "fast":
    MESH_SIZE = FAST_MESH_MM
elif STROKE == "pilot":
    MESH_SIZE = PILOT_MESH_MM
else:
    MESH_SIZE = FULL_MESH_MM

MESH_METHOD = str(_args.mesh_method).lower()

E_MODULUS = HU_BAI_E_MODULUS_MPA
POISSON = HU_BAI_POISSON
YIELD_MPA = HU_BAI_YIELD_MPA
DENSITY_KG_M3 = HU_BAI_DENSITY_KG_M3
DENSITY_ABQ = hu_bai_density_abq(DENSITY_KG_M3)
TPU_C10 = hu_bai_neo_hooke_c10(E_MODULUS, POISSON)

if PROFILE == "paper":
    if _args.load_rate_mm_min is not None and abs(float(_args.load_rate_mm_min) - HU_BAI_LOAD_RATE_MM_MIN) > 1e-9:
        print(
            f"  [paper] ignoring --load-rate-mm-min {_args.load_rate_mm_min}; "
            f"using {HU_BAI_LOAD_RATE_MM_MIN:g} mm/min (§2.4)",
            flush=True,
        )
    if _args.strain is not None and abs(float(_args.strain) - HU_BAI_TARGET_ENGINEERING_STRAIN) > 1e-9:
        print(
            f"  [paper] ignoring --strain {_args.strain}; "
            f"using {HU_BAI_TARGET_ENGINEERING_STRAIN:.0%} (§2.4)",
            flush=True,
        )
    if _args.explicit_dt_mode in ("automatic", "auto", "adaptive"):
        print("  [paper] forcing explicit_dt_mode=fixed (quasi-static KE/IE < 5%)", flush=True)
    if MESH_METHOD == "voxel":
        print("  [WARN] paper profile expects C3D4 tet mesh 0.6 mm; use --mesh-method tet", flush=True)

MATERIAL_KIND = _args.material_model
if MATERIAL_KIND is None:
    MATERIAL_KIND = "paper" if PROFILE == "paper" else "elastic_plastic"
USE_HYPERELASTIC = MATERIAL_KIND in ("paper", "hyperelastic")
INP_MATERIAL_MODEL = "hyperelastic" if USE_HYPERELASTIC else "elastic"

if PROFILE == "paper":
    TARGET_STRAIN = HU_BAI_TARGET_ENGINEERING_STRAIN
elif _args.strain is not None:
    TARGET_STRAIN = float(_args.strain)
elif IS_FAST80:
    TARGET_STRAIN = HU_BAI_FAST80_TARGET_STRAIN
elif PROFILE == "fast":
    TARGET_STRAIN = FAST_STRAIN
elif STROKE == "pilot":
    TARGET_STRAIN = PILOT_STRAIN
else:
    TARGET_STRAIN = HU_BAI_TARGET_ENGINEERING_STRAIN

BLOCK_HEIGHT = NZ * L
COMPRESSION_DISP = hu_bai_compression_displacement(NZ, L, target_strain=TARGET_STRAIN)
if PROFILE == "paper":
    LOAD_RATE_MM_MIN = HU_BAI_LOAD_RATE_MM_MIN
elif _args.load_rate_mm_min is not None:
    LOAD_RATE_MM_MIN = float(_args.load_rate_mm_min)
elif IS_FAST80:
    LOAD_RATE_MM_MIN = HU_BAI_LOAD_RATE_MM_MIN
elif PROFILE == "fast":
    LOAD_RATE_MM_MIN = FAST_LOAD_RATE_MM_MIN
else:
    LOAD_RATE_MM_MIN = HU_BAI_LOAD_RATE_MM_MIN
if _args.step_time is not None:
    STEP_TIME = float(_args.step_time)
    QUASI_STATIC_PAPER_RATE = False
else:
    STEP_TIME = hu_bai_quasi_static_step_time(
        COMPRESSION_DISP, load_rate_mm_min=LOAD_RATE_MM_MIN
    )
    QUASI_STATIC_PAPER_RATE = abs(LOAD_RATE_MM_MIN - HU_BAI_LOAD_RATE_MM_MIN) < 1e-9
FRICTION = HU_BAI_FRICTION
if _args.explicit_dt is not None:
    EXPLICIT_DT = float(_args.explicit_dt)
elif IS_FAST80:
    EXPLICIT_DT = HU_BAI_FAST80_EXPLICIT_DT
elif PROFILE == "fast":
    EXPLICIT_DT = FAST_EXPLICIT_DT
else:
    EXPLICIT_DT = HU_BAI_EXPLICIT_DT
if _args.hold_fraction is not None:
    HOLD_FRACTION = float(_args.hold_fraction)
elif _args.contact_interference_fit:
    HOLD_FRACTION = max(
        HU_BAI_AMPLITUDE_HOLD_FRACTION,
        float(_args.contact_init_step_fraction),
    )
elif IS_FAST80:
    HOLD_FRACTION = HU_BAI_AMPLITUDE_HOLD_FRACTION
elif PROFILE == "fast":
    HOLD_FRACTION = FAST_HOLD_FRACTION
else:
    HOLD_FRACTION = HU_BAI_AMPLITUDE_HOLD_FRACTION
EXPLICIT_MASS_SCALING = HU_BAI_EXPLICIT_MASS_SCALING
RESTART_INTERVAL = _args.restart_interval
BULK_VISCOSITY_LINEAR = (
    float(_args.bulk_viscosity_linear) if _args.bulk_viscosity_linear is not None else 0.12
)
BULK_VISCOSITY_QUADRATIC = (
    float(_args.bulk_viscosity_quadratic) if _args.bulk_viscosity_quadratic is not None else 1.6
)
EXPLICIT_DT_MODE = str(_args.explicit_dt_mode)
if PROFILE == "paper" and EXPLICIT_DT_MODE in ("automatic", "auto", "adaptive"):
    EXPLICIT_DT_MODE = "fixed"
STROKE_TAG = "p" if STROKE == "pilot" else "f"
VOXEL_PITCH = float(_args.voxel_pitch)
CASE_SUFFIX = CASE_SUFFIX_RAW
if not CASE_SUFFIX:
    if MESH_METHOD == "voxel":
        CASE_SUFFIX = "voxel"
    elif PROFILE == "fast":
        CASE_SUFFIX = "fast"
SOLID_ELEMENT = "C3D8R" if MESH_METHOD == "voxel" else "C3D4"
N_INC_EST = max(100, int(round(STEP_TIME / EXPLICIT_DT)))

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=ROD_D,
    amplitude=AF,
    period_factor=Q,
    n_segments=12,
)
gen.build_lattice(NX, NY, NZ)
nodes, beams, polylines = gen.get_data()
beams, beam_dups = dedupe_beams(beams)
if beam_dups:
    print(f"  Deduped beams: {len(beams)} unique ({beam_dups} removed)")

cad_arg_raw = _args.cad.strip()
if cad_arg_raw:
    cad_arg = cad_arg_raw
    if not os.path.isabs(cad_arg):
        cad_arg = os.path.join(_ROOT, cad_arg)
else:
    cad_arg = None

cad_ext = os.path.splitext(cad_arg or "")[1].lower()
cad_is_stl = cad_ext == ".stl"
if cad_is_stl:
    if not cad_arg or not os.path.isfile(cad_arg):
        raise FileNotFoundError(f"CAD STL not found: {cad_arg}")
    step_path = cad_arg
    xt_path = None
    print(f"CAD STL (fused): {step_path}")
else:
    resolved_cad = resolve_verified_solid_step(
        variant_name=gen.variant_name,
        cell_size_mm=L,
        nx=NX,
        ny=NY,
        nz=NZ,
        cad_path=cad_arg,
    )
    step_path, xt_path = resolve_step_and_xt(resolved_cad)
    print(f"CAD verified dir: {CAD_VERIFIED_ROOT}")
    print(f"CAD STEP: {step_path}")
    if xt_path:
        print(f"CAD X_T:  {xt_path}")

variant = gen.variant_name.lower()
_slug_base = f"hu_bai_{variant}_L{int(L)}_{NX}x{NY}x{NZ}_solid_cad_{STROKE_TAG}"
slug = f"{_slug_base}_{CASE_SUFFIX}" if CASE_SUFFIX else _slug_base
export_dir = os.path.join(EXPORT_ROOT, slug)
job_dir = os.path.join(ABAQUS_JOBS, slug)
post_dir = os.path.join(ABAQUS_POST, slug)
for d in (export_dir, job_dir, post_dir):
    os.makedirs(d, exist_ok=True)

geom_tag = f"hu_bai_{variant}_L{int(L)}_{NX}x{NY}x{NZ}_cad"

CONTACT_MODE = _args.contact_mode
# CAD 融合顶面起伏（Af≈2 mm）：放宽顶面带宽与法向阈值，增大初始 embed 保证板–顶面闭合传力
PLATE_EMBED_MM = max(0.3, 0.5 * MESH_SIZE)
TOP_SURFACE_Z_BAND = 10.0
TOP_NODE_Z_BAND = 12.0
TOP_FACE_NORMAL_Z_MIN = 0.35
BOTTOM_SURFACE_Z_BAND = 10.0
BOTTOM_FACE_NORMAL_Z_MAX = -0.35

compression = CompressionSettings(
    nx=NX,
    ny=NY,
    nz=NZ,
    cell_size=L,
    height_ratio=0.0,
    compression_displacement=COMPRESSION_DISP,
    step_time=STEP_TIME,
    contact_friction=FRICTION,
    tpu_d1=8e-4,
    # pair：顶板刚体通过 LATTICE_TOP↔PLATE_BOT 接触传力（论文 Fig.2.6）
    contact_mode=CONTACT_MODE,
    fixed_bottom_plate=True,
    plate_divisions=(14, 14),
    plate_thickness=0.5,
    analysis="explicit",
    explicit_dt=EXPLICIT_DT,
    explicit_dt_mode=EXPLICIT_DT_MODE,
    explicit_mass_scaling_factor=EXPLICIT_MASS_SCALING,
    explicit_mass_scaling_dt_only=False,
    amplitude_hold_fraction=HOLD_FRACTION,
    lattice_self_contact=not _args.no_lattice_self_contact,
    # 实体网格顶面已在 z_max；勿再加杆半径/standoff 留缝
    rod_radius=0.0,
    plate_margin=10.0,
    plate_standoff=0.0,
    plate_embed=PLATE_EMBED_MM,
    top_surface_z_band=TOP_SURFACE_Z_BAND,
    top_node_z_band=TOP_NODE_Z_BAND,
    top_face_normal_z_min=TOP_FACE_NORMAL_Z_MIN,
    bottom_surface_z_band=BOTTOM_SURFACE_Z_BAND,
    bottom_face_normal_z_max=BOTTOM_FACE_NORMAL_Z_MAX,
    explicit_restart_number_interval=RESTART_INTERVAL,
    bulk_viscosity_linear=BULK_VISCOSITY_LINEAR,
    bulk_viscosity_quadratic=BULK_VISCOSITY_QUADRATIC,
    contact_init_interference_fit=bool(_args.contact_interference_fit),
    contact_init_step_fraction=float(_args.contact_init_step_fraction),
)

paths = {
    "nodes_csv": os.path.join(export_dir, f"{slug}_nodes.csv"),
    "beams_csv": os.path.join(export_dir, f"{slug}_beams.csv"),
    "compression_inp": os.path.join(export_dir, f"{slug}.inp"),
    "meta_json": os.path.join(export_dir, f"{slug}_meta.json"),
    "case_manifest": os.path.join(export_dir, "case_manifest.json"),
}

export_nodes(nodes, paths["nodes_csv"])
export_beams(beams, paths["beams_csv"])

if MESH_METHOD == "voxel":
    if cad_is_stl:
        import trimesh

        from src.mesh.solid_union import mesh_union_voxel_c3d8r

        print(f"  Voxel mesh fused STL @ pitch={VOXEL_PITCH} mm (C3D8R)...", flush=True)
        union_mesh = trimesh.load(step_path)
        mesh_nodes, mesh_elements = mesh_union_voxel_c3d8r(union_mesh, pitch=VOXEL_PITCH)
        elsets = {"solid": [int(e[0]) for e in mesh_elements]}
    else:
        print(f"  Voxel mesh STEP @ pitch={VOXEL_PITCH} mm (C3D8R)...", flush=True)
        mesh_nodes, mesh_elements, elsets = mesh_step_voxel_c3d8r(
            step_path,
            pitch=VOXEL_PITCH,
        )
elif cad_is_stl:
    import trimesh

    from src.mesh.solid_union import mesh_union_gmsh_tets

    print(f"  Meshing fused STL @ {MESH_SIZE} mm (C3D4)...", flush=True)
    union_mesh = trimesh.load(step_path)
    mesh_nodes, mesh_elements = mesh_union_gmsh_tets(union_mesh, mesh_size=MESH_SIZE)
    elsets = {"solid": [int(e[0]) for e in mesh_elements]}
else:
    print(f"  Meshing STEP @ {MESH_SIZE} mm (paper C3D4)...", flush=True)
    mesh_algo = int(_args.mesh_algorithm) if _args.mesh_algorithm is not None else 1
    mesh_nodes, mesh_elements, elsets = mesh_step_gmsh_tets(
        step_path,
        mesh_size=MESH_SIZE,
        algorithm=mesh_algo,
        heal_shapes=bool(_args.mesh_heal),
    )
pre_mesh = (mesh_nodes, mesh_elements, elsets)

stats = export_inp(
    nodes,
    beams,
    paths["compression_inp"],
    polylines=polylines,
    element_type=SOLID_ELEMENT,
    material_model=INP_MATERIAL_MODEL,
    material_name="TPU",
    c10=TPU_C10,
    elastic_e=E_MODULUS,
    elastic_nu=POISSON,
    plastic_yield=None if USE_HYPERELASTIC else YIELD_MPA,
    density=DENSITY_ABQ,
    compression=compression,
    geom_tag=geom_tag,
    include_wireframe=False,
    pre_mesh=pre_mesh,
)

with open(paths["compression_inp"], encoding="utf-8", errors="replace") as _inp_f:
    validate_explicit_restart_inp(_inp_f.read())

meta = CompressionMeta.from_export_stats(
    nx=NX,
    ny=NY,
    nz=NZ,
    cell_size=L,
    height_ratio=0.0,
    compression_displacement=COMPRESSION_DISP,
    step_time=STEP_TIME,
    step_name=compression.step_name,
    stats=stats,
    amplitude_hold_fraction=compression.amplitude_hold_fraction,
    case_slug=slug,
    geometry_tag=geom_tag,
    support_type="bcc_cad_solid",
    r_frame=gen.r_strut,
    r_support=gen.r_strut,
    r_vertical=gen.r_strut,
)
meta.reference_area_mm2 = NX * L * NY * L
meta.reference_height_mm = NZ * L
meta.plate_fixed_ref_node_id = int(
    stats.get("fixed_plate_ref_node_id", stats.get("plate_fixed_ref_node_id", 0)) or 0
)
save_compression_meta(meta, paths["meta_json"])

manifest = {
    "slug": slug,
    "profile": PROFILE,
    "stroke": STROKE,
    "stroke_tag": STROKE_TAG,
    "structure": gen.variant_name,
    "reference": "Hu & Bai 2024 — CAD solid (STEP/X_T) explicit compression",
    "figure_target": (
        "Fig. 3.3 compressive stress-strain (solid C3D4 mesh)"
        if MESH_METHOD == "tet"
        else "Voxel C3D8R solid mesh (print-oriented)"
    ),
    "export_dir": export_dir,
    "job_dir": job_dir,
    "post_dir": post_dir,
    "compression_inp": paths["compression_inp"],
    "case_manifest": paths["case_manifest"],
    "meta_json": paths["meta_json"],
    "cad_step": step_path if not cad_is_stl else None,
    "cad_stl": step_path if cad_is_stl else None,
    "cad_xt": xt_path,
    "cad_verified_root": str(CAD_VERIFIED_ROOT),
    "cad_source": "verified",
    "odb": os.path.join(job_dir, f"{slug}.odb"),
    "job_name": slug,
    "job_inp_name": f"{slug}.inp",
    "stress_strain_csv": os.path.join(post_dir, f"{slug}_stress_strain.csv"),
    "stress_strain_raw_csv": os.path.join(post_dir, f"{slug}_stress_strain_raw.csv"),
    "stress_strain_png": os.path.join(post_dir, f"{slug}_stress_strain.png"),
    "yield_json": os.path.join(post_dir, f"{slug}_yield.json"),
    "paper_params": {
        "cell_size_mm": L,
        "rod_diameter_mm": ROD_D,
        "block_cells": [NX, NY, NZ],
    },
    "material": {
        "model": MATERIAL_KIND,
        "inp_model": INP_MATERIAL_MODEL,
        "E_MPa": E_MODULUS,
        "nu": POISSON,
        "yield_MPa": YIELD_MPA,
        "neo_hooke_C10_MPa": TPU_C10 if USE_HYPERELASTIC else None,
        "density_kg_m3": DENSITY_KG_M3,
    },
    "mesh": {
        "element": SOLID_ELEMENT,
        "method": MESH_METHOD,
        "source": (
            "union_voxel"
            if MESH_METHOD == "voxel"
            else ("gmsh_stl_volume" if cad_is_stl else "gmsh_step_volume")
        ),
        "mesh_size_mm": VOXEL_PITCH if MESH_METHOD == "voxel" else MESH_SIZE,
        "voxel_pitch_mm": VOXEL_PITCH if MESH_METHOD == "voxel" else None,
        "node_count": stats.get("node_count"),
        "element_count": stats.get("element_count"),
    },
    "loading": {
        "compression_displacement_mm": COMPRESSION_DISP,
        "target_engineering_strain": TARGET_STRAIN,
        "step_time_s": STEP_TIME,
        "load_rate_mm_min": LOAD_RATE_MM_MIN,
        "quasi_static_paper_rate": QUASI_STATIC_PAPER_RATE,
        "step_time_overridden": _args.step_time is not None,
        "friction": FRICTION,
        "explicit_dt": EXPLICIT_DT,
        "explicit_dt_mode": EXPLICIT_DT_MODE,
        "amplitude_hold_fraction": HOLD_FRACTION,
        "explicit_mass_scaling": EXPLICIT_MASS_SCALING,
        "explicit_n_increments_est": N_INC_EST,
        "case_suffix": CASE_SUFFIX or None,
        "contact_mode": CONTACT_MODE,
        "fixed_bottom_plate": True,
        "plate_margin_mm": compression.plate_margin,
        "plate_embed_mm": PLATE_EMBED_MM,
        "top_surface_z_band_mm": TOP_SURFACE_Z_BAND,
        "top_face_normal_z_min": TOP_FACE_NORMAL_Z_MIN,
        "lattice_load_faces": stats.get("lattice_load_faces"),
        "lattice_load_nodes": stats.get("lattice_load_nodes"),
        "lattice_self_contact": compression.lattice_self_contact,
        "contact_init_interference_fit": compression.contact_init_interference_fit,
        "contact_init_step_fraction": compression.contact_init_step_fraction,
        "explicit_restart_write": compression.explicit_restart_write,
        "explicit_restart_number_interval": compression.resolved_restart_number_interval(),
    },
}
with open(paths["case_manifest"], "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")
active_case = os.path.join(_ROOT, "output", "active_case.json")
with open(active_case, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")
update_manifest_penetration_check(
    paths["case_manifest"],
    meta_path=paths["meta_json"],
    inp_path=paths["compression_inp"],
    active_path=active_case,
)

print()
print(f"Hu & Bai CAD solid compression INP (profile={PROFILE}, stroke={STROKE}):", paths["compression_inp"])
_mesh_label = f"{SOLID_ELEMENT} @ {VOXEL_PITCH} mm pitch" if MESH_METHOD == "voxel" else f"C3D4 @ {MESH_SIZE} mm"
print(f"  Mesh: {stats['node_count']} nodes, {stats['element_count']} {_mesh_label}")
n_load_faces = int(stats.get("lattice_load_faces") or stats.get("lattice_top_faces") or 0)
print(f"  LATTICE_TOP contact faces: {n_load_faces} (z_band={TOP_SURFACE_Z_BAND} mm, normal_z>={TOP_FACE_NORMAL_Z_MIN})")
if n_load_faces < 3000:
    print(
        f"  [WARN] Few top contact faces ({n_load_faces}); check plate_embed={PLATE_EMBED_MM} mm or z_band.",
        flush=True,
    )
print(f"  Target engineering strain: {TARGET_STRAIN:.0%}")
print(f"  Plates: margin {compression.plate_margin} mm beyond lattice (rod R={ROD_D/2} mm)")
_rate_note = "paper quasi-static" if QUASI_STATIC_PAPER_RATE else "custom rate"
print(
    f"  Loading: {COMPRESSION_DISP:.1f} mm / {STEP_TIME:.1f} s "
    f"({LOAD_RATE_MM_MIN:g} mm/min, {_rate_note}), μ={FRICTION}"
)
_mat_note = (
    f"Neo-Hooke C10={TPU_C10:.4g} MPa (E~{E_MODULUS:g} MPa)"
    if USE_HYPERELASTIC
    else f"elastic E={E_MODULUS:g} MPa + plastic yield={YIELD_MPA:g} MPa"
)
print(f"  Material ({MATERIAL_KIND}): {_mat_note}, rho={DENSITY_KG_M3:g} kg/m^3, nu={POISSON}")
print(
    f"  Explicit: dt_mode={EXPLICIT_DT_MODE}, dt={EXPLICIT_DT:g} s, "
    f"mass scaling ×{EXPLICIT_MASS_SCALING:g}, ~{N_INC_EST} increments"
)
print(
    f"  Bulk viscosity: {BULK_VISCOSITY_LINEAR:g}, {BULK_VISCOSITY_QUADRATIC:g}; "
    f"restart slices: {compression.resolved_restart_number_interval()}"
)
_elem_n = max(int(stats.get("element_count", 0) or 0), 1)
# Empirical SFBLS Q=1 4×4×4 ~1.2 mm mesh, 8 cpus, dt=5e-4: ~0.01 s/increment (2026-06 runs).
_wall_sec_per_inc_ref = 0.01
_elem_ref = 144_000
_wall_h_8cpu = N_INC_EST * _wall_sec_per_inc_ref * (_elem_n / _elem_ref) / 3600.0
print(
    f"  Wall-clock estimate: ~{_wall_h_8cpu:.0f} h @ 8 cpus full step "
    f"(scales with increments x elements; SFBLS self-contact)"
)
if compression.explicit_restart_write:
    n_rst = compression.resolved_restart_number_interval()
    print(
        f"  Restart: overlay, number interval={n_rst} "
        f"(~{n_rst + 1} time checkpoints; disk-safe, not increment stride)"
    )
print(f"  Job slug: {slug}")
print("  >>> Submit: powershell -File scripts\\submit_hu_bai_bcc_solid_cad_compression.ps1")
