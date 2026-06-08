"""
DEPRECATED — use CAD solid C3D4 path instead (contact loading, full stroke).

  py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3
  powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Cells 3
"""

from __future__ import annotations

import argparse
import sys
import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.abaqus_compression import (
    CompressionSettings,
    HU_BAI_EXPLICIT_DT,
    HU_BAI_EXPLICIT_MASS_SCALING,
    HU_BAI_FRICTION,
    HU_BAI_LOAD_RATE_MM_MIN,
    HU_BAI_TARGET_ENGINEERING_STRAIN,
    hu_bai_compression_displacement,
    hu_bai_quasi_static_step_time,
)
from src.export.beam_utils import dedupe_beams
from src.export.export_csv import export_beams, export_nodes
from src.export.export_inp import export_inp, export_inp_b31
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import ensure_output_dirs
from src.postprocess.compression_curve import CompressionMeta, save_compression_meta
from src.validation.penetration_risk import update_manifest_penetration_check
from src.visualization.plot_lattice import plot_lattice

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Hu & Bai 2024 BCC/SFBLS compression export")
_parser.add_argument("--Q", type=float, default=0.0, help="Period factor Q (0=BCC straight rod)")
_parser.add_argument("--Af", type=float, default=2.0, help="Sinusoidal amplitude A_f [mm]")
_parser.add_argument("--cells", type=int, default=4, help="Cells per axis (paper: 4)")
_parser.add_argument(
    "--skip-wireframe",
    action="store_true",
    help="Skip matplotlib wireframe PNG (avoids memory issues on large blocks)",
)
_parser.add_argument(
    "--strain",
    type=float,
    default=None,
    help=f"Target engineering strain (default {HU_BAI_TARGET_ENGINEERING_STRAIN})",
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
    help=f"Crosshead rate [mm/min] (default {HU_BAI_LOAD_RATE_MM_MIN:g})",
)
_parser.add_argument(
    "--explicit-dt",
    type=float,
    default=None,
    help=f"Explicit fixed dt [s] (default {HU_BAI_EXPLICIT_DT:g})",
)
_parser.add_argument(
    "--case-suffix",
    type=str,
    default="",
    help="Append to slug after stroke tag (e.g. b31p10)",
)
_args = _parser.parse_args()

print(
    "DEPRECATED: run_hu_bai_bcc_export.py (C3D8R beam sweep) is no longer used for Hu & Bai.\n"
    "Use: py -3 scripts/run_hu_bai_bcc_solid_cad_export.py\n"
    "     powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1",
    file=sys.stderr,
)
sys.exit(2)

# --- Paper §2.1 geometry (mm) ---
L = 20.0
ROD_D = 2.0
AF = float(_args.Af)
Q = float(_args.Q)
NX = NY = NZ = int(_args.cells)

# --- Paper §2.4.1 material (TPU tensile test) ---
E_MODULUS = 25.0
POISSON = 0.47
YIELD_MPA = 4.69
DENSITY_KG_M3 = 1135.0
DENSITY_ABQ = DENSITY_KG_M3 * 1.0e-12

# --- Paper §2.4 quasi-static: 5 mm/min, 70 % engineering strain (overridable) ---
TARGET_STRAIN = (
    float(_args.strain) if _args.strain is not None else HU_BAI_TARGET_ENGINEERING_STRAIN
)
BLOCK_HEIGHT = NZ * L
COMPRESSION_DISP = hu_bai_compression_displacement(NZ, L, target_strain=TARGET_STRAIN)
LOAD_RATE_MM_MIN = (
    float(_args.load_rate_mm_min)
    if _args.load_rate_mm_min is not None
    else HU_BAI_LOAD_RATE_MM_MIN
)
if _args.step_time is not None:
    STEP_TIME = float(_args.step_time)
else:
    STEP_TIME = hu_bai_quasi_static_step_time(
        COMPRESSION_DISP, load_rate_mm_min=LOAD_RATE_MM_MIN
    )
FRICTION = HU_BAI_FRICTION

# Mesh: paper C3D4 @ 0.6 mm; beam sweep n_axial=6 → ~0.5 mm along strut
N_THETA = 8
STRUT_LEN = 0.5 * math.sqrt(3.0) * L
N_POLYLINE_SEG = max(12, int(math.ceil(STRUT_LEN / 0.6)))
N_AXIAL = 6
POLYLINE_AXIAL = 4

EXPLICIT_DT = float(_args.explicit_dt) if _args.explicit_dt is not None else HU_BAI_EXPLICIT_DT
EXPLICIT_MASS_SCALING = HU_BAI_EXPLICIT_MASS_SCALING
N_INC_EST = max(100, int(round(STEP_TIME / EXPLICIT_DT)))
STROKE = "full"
CASE_SUFFIX = _args.case_suffix.strip().replace(" ", "_")

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=ROD_D,
    amplitude=AF,
    period_factor=Q,
    n_segments=N_POLYLINE_SEG,
)
gen.build_lattice(NX, NY, NZ)

nodes, beams, polylines = gen.get_data()
beams, beam_dups = dedupe_beams(beams)
if beam_dups:
    print(f"  Deduped beams: {len(beams)} unique ({beam_dups} duplicates removed)")

variant = gen.variant_name.lower()
cells_tag = f"{NX}x{NY}x{NZ}"
_slug_base = f"hu_bai_{variant}_L{int(L)}_{cells_tag}_{STROKE[0]}"
slug = f"{_slug_base}_{CASE_SUFFIX}" if CASE_SUFFIX else _slug_base
export_dir = os.path.join(_ROOT, "output", "export", "hu_bai", slug)
job_dir = os.path.join(_ROOT, "output", "abaqus", "jobs", "hu_bai", slug)
post_dir = os.path.join(_ROOT, "output", "abaqus", "post", "hu_bai", slug)
for d in (export_dir, job_dir, post_dir):
    os.makedirs(d, exist_ok=True)

geom_tag = f"hu_bai_{variant}_L{int(L)}_d{int(ROD_D)}_{cells_tag}"

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
    contact_mode="pair",
    fixed_bottom_plate=True,
    plate_divisions=(12, 12),
    plate_thickness=0.5,
    analysis="explicit",
    explicit_dt=EXPLICIT_DT,
    explicit_mass_scaling_factor=EXPLICIT_MASS_SCALING,
    explicit_mass_scaling_dt_only=False,
    amplitude_hold_fraction=0.05,
    lattice_self_contact=False,
    rod_radius=ROD_D / 2.0,
    plate_margin=10.0,
    plate_standoff=0.05,
    top_surface_z_band=1.5,
    top_node_z_band=2.5,
    bottom_surface_z_band=1.5,
)

paths = {
    "nodes_csv": os.path.join(export_dir, f"{slug}_nodes.csv"),
    "beams_csv": os.path.join(export_dir, f"{slug}_beams.csv"),
    "compression_inp": os.path.join(export_dir, f"{slug}.inp"),
    "topology_b31_inp": os.path.join(export_dir, f"{slug}_topology_b31.inp"),
    "meta_json": os.path.join(export_dir, f"{slug}_meta.json"),
    "wireframe_png": os.path.join(export_dir, f"{slug}_wireframe.png"),
    "case_manifest": os.path.join(export_dir, "case_manifest.json"),
}

export_nodes(nodes, paths["nodes_csv"])
export_beams(beams, paths["beams_csv"])

stats = export_inp(
    nodes,
    beams,
    paths["compression_inp"],
    polylines=polylines,
    element_type="C3D8R",
    n_axial=N_AXIAL,
    n_theta=N_THETA,
    polyline_axial_per_span=POLYLINE_AXIAL,
    material_model="elastic",
    material_name="TPU",
    elastic_e=E_MODULUS,
    elastic_nu=POISSON,
    plastic_yield=YIELD_MPA,
    density=DENSITY_ABQ,
    compression=compression,
    geom_tag=geom_tag,
    include_wireframe=False,
)

export_inp_b31(
    nodes,
    beams,
    paths["topology_b31_inp"],
    polylines=polylines,
    geom_tag=geom_tag,
)

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
    support_type="bcc",
    r_frame=gen.r_strut,
    r_support=gen.r_strut,
    r_vertical=gen.r_strut,
)
meta.reference_area_mm2 = NX * L * NY * L
meta.reference_height_mm = NZ * L
save_compression_meta(meta, paths["meta_json"])

manifest = {
    "slug": slug,
    "stroke": STROKE,
    "structure": gen.variant_name,
    "reference": "Hu & Bai 2024, lattice vibration isolation for underwater vehicle",
    "figure_target": "Fig. 3.3 compressive stress-strain (BCC baseline)",
    "export_dir": export_dir,
    "job_dir": job_dir,
    "post_dir": post_dir,
    "compression_inp": paths["compression_inp"],
    "case_manifest": paths["case_manifest"],
    "topology_b31_inp": paths["topology_b31_inp"],
    "meta_json": paths["meta_json"],
    "wireframe_png": paths["wireframe_png"],
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
        "amplitude_mm": AF,
        "period_factor_Q": Q,
        "block_cells": [NX, NY, NZ],
    },
    "material": {
        "name": "TPU (SLS)",
        "E_MPa": E_MODULUS,
        "nu": POISSON,
        "yield_MPa": YIELD_MPA,
        "density_kg_m3": DENSITY_KG_M3,
    },
    "mesh": {
        "element": "C3D8R",
        "source": "beam_sweep",
        "n_axial": N_AXIAL,
        "n_theta": N_THETA,
        "paper_target_mm": 0.6,
    },
    "loading": {
        "compression_displacement_mm": COMPRESSION_DISP,
        "target_engineering_strain": TARGET_STRAIN,
        "step_time_s": STEP_TIME,
        "load_rate_mm_min": LOAD_RATE_MM_MIN,
        "quasi_static": True,
        "friction": FRICTION,
        "explicit_dt": EXPLICIT_DT,
        "explicit_mass_scaling": EXPLICIT_MASS_SCALING,
        "explicit_n_increments_est": N_INC_EST,
        "case_suffix": CASE_SUFFIX or None,
        "contact_mode": "pair",
        "fixed_bottom_plate": True,
        "lattice_self_contact": False,
    },
    "footprint_mm": {
        "X": NX * L,
        "Y": NY * L,
        "Z": NZ * L,
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

if not _args.skip_wireframe:
    plot_lattice(nodes, beams, save_path=paths["wireframe_png"], polylines=polylines)

print("Hu & Bai BCC compression model exported:", paths["compression_inp"])
print(f"  Variant: {gen.variant_name} (Q={Q}, A_f={AF} mm, d={ROD_D} mm)")
print(f"  Mesh: C3D8R beam sweep, n_axial={N_AXIAL}, n_theta={N_THETA} (paper ref 0.6 mm)")
print(f"  Material: TPU E={E_MODULUS} MPa, nu={POISSON}, yield={YIELD_MPA} MPa")
print(f"  Nodes: {stats['node_count']}, Elements: {stats['element_count']}")
print(
    f"  Loading: {COMPRESSION_DISP:.1f} mm / {STEP_TIME:.1f} s "
    f"({LOAD_RATE_MM_MIN:g} mm/min quasi-static, strain {TARGET_STRAIN:.0%})"
)
print(
    f"  Explicit: dt={EXPLICIT_DT:g} s, mass scaling ×{EXPLICIT_MASS_SCALING:g}, ~{N_INC_EST} increments"
)
print(f"  Reference area: {meta.reference_area_mm2:.0f} mm2, height: {meta.reference_height_mm:.0f} mm")
print(f"  Job slug: {slug}")
print("  >>> Submit: powershell -File scripts\\submit_hu_bai_bcc_compression.ps1")
