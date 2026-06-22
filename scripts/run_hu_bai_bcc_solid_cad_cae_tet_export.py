"""
Export Hu & Bai CAD solid → Abaqus compression INP using CAE built-in C3D4 mesh.

1) Abaqus/CAE noGUI meshes verified STEP (TET_FREE).
2) Parse mesh INP → merge with rigid plates, contact, explicit step (export_inp).

Example:
  py -3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py --cells 4 --Q 0 --profile fast \\
    --case-suffix cae_tet1p2mm80_5mmin --cae-seed 1.2 --strain 0.8 --load-rate-mm-min 5 \\
    --no-lattice-self-contact
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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
from src.export.parse_cae_mesh_inp import parse_cae_mesh_inp
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import ABAQUS_JOBS, ABAQUS_POST, CAD_VERIFIED_ROOT, EXPORT_ROOT, ensure_output_dirs
from src.postprocess.compression_curve import CompressionMeta, save_compression_meta
from src.validation.penetration_risk import update_manifest_penetration_check

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Hu & Bai CAD solid → CAE C3D4 compression INP")
_parser.add_argument("--Q", type=float, default=0.0)
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--cells", type=int, default=4)
_parser.add_argument("--cad", type=str, default="")
_parser.add_argument("--cae-seed", type=float, default=1.2, help="CAE global seed [mm]")
_parser.add_argument(
    "--cae-mesh-inp",
    type=str,
    default="",
    help="Reuse existing CAE mesh INP (skip abaqus cae mesh step)",
)
_parser.add_argument("--cae-part-name", type=str, default="LATTICE")
_parser.add_argument("--strain", type=float, default=None)
_parser.add_argument(
    "--profile",
    choices=("fast", "paper", "pilot"),
    default="fast",
)
_parser.add_argument("--case-suffix", type=str, default="")
_parser.add_argument("--load-rate-mm-min", type=float, default=None)
_parser.add_argument("--step-time", type=float, default=None)
_parser.add_argument("--explicit-dt", type=float, default=None)
_parser.add_argument(
    "--explicit-dt-mode",
    choices=("fixed", "automatic"),
    default="fixed",
)
_parser.add_argument("--hold-fraction", type=float, default=None)
_parser.add_argument(
    "--contact-mode",
    choices=("pair", "coupling_nodes"),
    default="pair",
)
_parser.add_argument("--no-lattice-self-contact", action="store_true")
_parser.add_argument("--restart-interval", type=int, default=None)
_parser.add_argument(
    "--material-model",
    choices=("paper", "hyperelastic", "elastic_plastic"),
    default=None,
)
_args = _parser.parse_args()

PROFILE = _args.profile
CASE_SUFFIX_RAW = _args.case_suffix.strip().replace(" ", "_")
IS_FAST80 = CASE_SUFFIX_RAW == "fast80"
L = 20.0
ROD_D = 2.0
AF = float(_args.Af)
Q = float(_args.Q)
NX = NY = NZ = int(_args.cells)
CAE_SEED = float(_args.cae_seed)

E_MODULUS = HU_BAI_E_MODULUS_MPA
POISSON = HU_BAI_POISSON
YIELD_MPA = HU_BAI_YIELD_MPA
DENSITY_KG_M3 = HU_BAI_DENSITY_KG_M3
DENSITY_ABQ = hu_bai_density_abq(DENSITY_KG_M3)
TPU_C10 = hu_bai_neo_hooke_c10(E_MODULUS, POISSON)

MATERIAL_KIND = _args.material_model
if MATERIAL_KIND is None:
    MATERIAL_KIND = "paper" if PROFILE == "paper" else "elastic_plastic"
USE_HYPERELASTIC = MATERIAL_KIND in ("paper", "hyperelastic")
INP_MATERIAL_MODEL = "hyperelastic" if USE_HYPERELASTIC else "elastic"

if PROFILE == "paper":
    TARGET_STRAIN = HU_BAI_TARGET_ENGINEERING_STRAIN
    LOAD_RATE_MM_MIN = HU_BAI_LOAD_RATE_MM_MIN
    if CAE_SEED > HU_BAI_MESH_MM + 1e-9:
        print(f"  [WARN] paper mesh is 0.6 mm; consider --cae-seed {HU_BAI_MESH_MM}", flush=True)
elif _args.strain is not None:
    TARGET_STRAIN = float(_args.strain)
elif IS_FAST80:
    TARGET_STRAIN = HU_BAI_FAST80_TARGET_STRAIN
elif PROFILE == "fast":
    TARGET_STRAIN = 0.45
elif PROFILE == "pilot":
    TARGET_STRAIN = 0.15
else:
    TARGET_STRAIN = HU_BAI_TARGET_ENGINEERING_STRAIN

COMPRESSION_DISP = hu_bai_compression_displacement(NZ, L, target_strain=TARGET_STRAIN)
if PROFILE != "paper":
    LOAD_RATE_MM_MIN = (
        float(_args.load_rate_mm_min)
        if _args.load_rate_mm_min is not None
        else HU_BAI_LOAD_RATE_MM_MIN
    )
if _args.step_time is not None:
    STEP_TIME = float(_args.step_time)
    QUASI_STATIC_PAPER_RATE = False
else:
    STEP_TIME = hu_bai_quasi_static_step_time(
        COMPRESSION_DISP, load_rate_mm_min=LOAD_RATE_MM_MIN
    )
    QUASI_STATIC_PAPER_RATE = abs(LOAD_RATE_MM_MIN - HU_BAI_LOAD_RATE_MM_MIN) < 1e-9

EXPLICIT_DT = (
    float(_args.explicit_dt)
    if _args.explicit_dt is not None
    else (HU_BAI_FAST80_EXPLICIT_DT if IS_FAST80 else HU_BAI_EXPLICIT_DT)
)
HOLD_FRACTION = (
    float(_args.hold_fraction)
    if _args.hold_fraction is not None
    else HU_BAI_AMPLITUDE_HOLD_FRACTION
)
EXPLICIT_DT_MODE = str(_args.explicit_dt_mode)
if PROFILE == "paper" and EXPLICIT_DT_MODE in ("automatic", "auto", "adaptive"):
    print("  [paper] forcing explicit_dt_mode=fixed (quasi-static KE/IE < 5%)", flush=True)
    EXPLICIT_DT_MODE = "fixed"
CASE_SUFFIX = CASE_SUFFIX_RAW or f"cae_tet{CAE_SEED:g}mm{int(round(TARGET_STRAIN * 100))}p_{int(LOAD_RATE_MM_MIN)}mmin"
STROKE_TAG = "f"
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
    cad_arg = cad_arg_raw if os.path.isabs(cad_arg_raw) else os.path.join(_ROOT, cad_arg_raw)
else:
    cad_arg = None

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
slug = f"{_slug_base}_{CASE_SUFFIX}"
export_dir = os.path.join(EXPORT_ROOT, slug)
job_dir = os.path.join(ABAQUS_JOBS, slug)
post_dir = os.path.join(ABAQUS_POST, slug)
for d in (export_dir, job_dir, post_dir):
    os.makedirs(d, exist_ok=True)

geom_tag = f"hu_bai_{variant}_L{int(L)}_{NX}x{NY}x{NZ}_cad"
CONTACT_MODE = _args.contact_mode
PLATE_EMBED_MM = max(0.3, 0.5 * CAE_SEED)
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
    contact_friction=HU_BAI_FRICTION,
    tpu_d1=8e-4,
    contact_mode=CONTACT_MODE,
    fixed_bottom_plate=True,
    plate_divisions=(14, 14),
    plate_thickness=0.5,
    analysis="explicit",
    explicit_dt=EXPLICIT_DT,
    explicit_dt_mode=EXPLICIT_DT_MODE,
    explicit_mass_scaling_factor=HU_BAI_EXPLICIT_MASS_SCALING,
    explicit_mass_scaling_dt_only=False,
    amplitude_hold_fraction=HOLD_FRACTION,
    lattice_self_contact=not _args.no_lattice_self_contact,
    rod_radius=0.0,
    plate_margin=10.0,
    plate_standoff=0.0,
    plate_embed=PLATE_EMBED_MM,
    top_surface_z_band=TOP_SURFACE_Z_BAND,
    top_node_z_band=TOP_NODE_Z_BAND,
    top_face_normal_z_min=TOP_FACE_NORMAL_Z_MIN,
    bottom_surface_z_band=BOTTOM_SURFACE_Z_BAND,
    bottom_face_normal_z_max=BOTTOM_FACE_NORMAL_Z_MAX,
    explicit_restart_number_interval=_args.restart_interval,
)

paths = {
    "nodes_csv": os.path.join(export_dir, f"{slug}_nodes.csv"),
    "beams_csv": os.path.join(export_dir, f"{slug}_beams.csv"),
    "cae_mesh_inp": os.path.join(export_dir, f"{slug}_cae_mesh.inp"),
    "compression_inp": os.path.join(export_dir, f"{slug}.inp"),
    "meta_json": os.path.join(export_dir, f"{slug}_meta.json"),
    "case_manifest": os.path.join(export_dir, "case_manifest.json"),
}

export_nodes(nodes, paths["nodes_csv"])
export_beams(beams, paths["beams_csv"])

cae_mesh_inp = _args.cae_mesh_inp.strip()
if cae_mesh_inp:
    if not os.path.isabs(cae_mesh_inp):
        cae_mesh_inp = os.path.join(_ROOT, cae_mesh_inp)
    if not os.path.isfile(cae_mesh_inp):
        raise FileNotFoundError(cae_mesh_inp)
    print(f"  Reusing CAE mesh INP: {cae_mesh_inp}", flush=True)
else:
    cae_mesh_inp = paths["cae_mesh_inp"]
    print(f"  CAE TET mesh STEP @ seed={CAE_SEED} mm ...", flush=True)
    pilot_ps1 = os.path.join(_ROOT, "scripts", "run_abaqus_cae_hex_mesh_pilot.ps1")
    cmd = [
        "powershell",
        "-NoProfile",
        "-File",
        pilot_ps1,
        "-MeshMode",
        "tet",
        "-SeedMm",
        str(CAE_SEED),
        "-StepPath",
        step_path,
        "-OutInp",
        cae_mesh_inp,
        "-PartName",
        _args.cae_part_name,
    ]
    print(f"  Running: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=_ROOT, check=True)
    if not os.path.isfile(cae_mesh_inp):
        raise FileNotFoundError(f"CAE mesh INP not written: {cae_mesh_inp}")

mesh_nodes, mesh_elements = parse_cae_mesh_inp(
    cae_mesh_inp,
    part_name=_args.cae_part_name,
    element_type="C3D4",
)
elsets = {"solid": [int(e[0]) for e in mesh_elements]}
pre_mesh = (mesh_nodes, mesh_elements, elsets)
print(
    f"  Parsed CAE mesh: {len(mesh_nodes)} nodes, {len(mesh_elements)} C3D4",
    flush=True,
)

stats = export_inp(
    nodes,
    beams,
    paths["compression_inp"],
    polylines=polylines,
    element_type="C3D4",
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
    "stroke": "full",
    "stroke_tag": STROKE_TAG,
    "structure": gen.variant_name,
    "reference": "Hu & Bai 2024 — CAE C3D4 tet + explicit compression",
    "figure_target": "CAE built-in C3D4 tet mesh compression",
    "export_dir": export_dir,
    "job_dir": job_dir,
    "post_dir": post_dir,
    "compression_inp": paths["compression_inp"],
    "cae_mesh_inp": cae_mesh_inp,
    "case_manifest": paths["case_manifest"],
    "meta_json": paths["meta_json"],
    "cad_step": step_path,
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
        "E_MPa": E_MODULUS,
        "nu": POISSON,
        "yield_MPa": YIELD_MPA,
        "density_kg_m3": DENSITY_KG_M3,
    },
    "mesh": {
        "element": "C3D4",
        "method": "cae_tet",
        "source": "abaqus_cae_tet_free",
        "cae_seed_mm": CAE_SEED,
        "cae_part_name": _args.cae_part_name,
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
        "friction": HU_BAI_FRICTION,
        "explicit_dt": EXPLICIT_DT,
        "explicit_dt_mode": EXPLICIT_DT_MODE,
        "amplitude_hold_fraction": HOLD_FRACTION,
        "explicit_mass_scaling": HU_BAI_EXPLICIT_MASS_SCALING,
        "explicit_n_increments_est": N_INC_EST,
        "case_suffix": CASE_SUFFIX,
        "contact_mode": CONTACT_MODE,
        "fixed_bottom_plate": True,
        "plate_margin_mm": compression.plate_margin,
        "plate_embed_mm": PLATE_EMBED_MM,
        "top_surface_z_band_mm": TOP_SURFACE_Z_BAND,
        "top_face_normal_z_min": TOP_FACE_NORMAL_Z_MIN,
        "lattice_load_faces": stats.get("lattice_load_faces"),
        "lattice_load_nodes": stats.get("lattice_load_nodes"),
        "lattice_self_contact": compression.lattice_self_contact,
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
print(f"Hu & Bai CAE tet compression INP (profile={PROFILE}):", paths["compression_inp"])
print(f"  Mesh: {stats['node_count']} nodes, {stats['element_count']} C3D4 @ CAE seed {CAE_SEED} mm")
print(f"  Slug: {slug}")
print(f"  Server: scp export + jobs dirs, then bash scripts/linux/submit_job.sh --slug {slug}")
