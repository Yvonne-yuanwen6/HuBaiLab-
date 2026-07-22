"""
Export Hu & Bai CAD solid → Abaqus compression INP using CAE built-in C3D4 mesh.

§2.4.1 states C3D4 and 0.6 mm mesh; CAE seeding / vtopo / self-contact / ContactSettle
are repo additions (原文未写). See ``run_hu_bai_bcc_solid_cad_export.py`` for thesis vs repo notes.

Example (Windows: CAE mesh runs on server by default):
  py -3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py --cells 4 --Q 0 --profile fast \\
    --case-suffix cae_tet0p6mm80_5mmin_paper --cae-seed 0.6 --strain 0.8 --load-rate-mm-min 5 \\
    --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling --material-model neo_hooke

On Linux server (mesh locally):
  py -3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py ... --mesh-locally
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
    is_neo_hooke_material,
    validate_explicit_restart_inp,
)
from src.export.beam_utils import dedupe_beams
from src.export.cad_solid_paths import resolve_step_and_xt, resolve_verified_solid_step
from src.export.export_csv import export_beams, export_nodes
from src.export.export_inp import export_inp
from src.export.cae_mesh_runner import run_cae_mesh
from src.export.parse_cae_mesh_inp import parse_cae_mesh_inp
from src.export.step_heal_for_cae import HEAL_PRESETS, heal_step_for_cae, heal_step_once
from src.paperbox_slug import build_paperbox_short_slug, paperbox_slug_descriptor
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.material.tpu_fig25 import load_tpu_fig25_uniaxial
from src.paths import (
    ABAQUS_JOBS,
    ABAQUS_POST,
    CAD_VERIFIED_ROOT,
    EXPORT_ROOT,
    HUBAI_REMOTE_ROOT,
    ensure_output_dirs,
)
from src.postprocess.compression_curve import CompressionMeta, save_compression_meta
from src.validation.penetration_risk import update_manifest_penetration_check

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Hu & Bai CAD solid → CAE C3D4 compression INP")
_parser.add_argument("--Q", type=float, default=0.0)
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--cells", type=int, default=4)
_parser.add_argument("--L", type=float, default=20.0, help="Unit cell edge length [mm]")
_parser.add_argument(
    "--rod-diameter",
    type=float,
    default=2.0,
    help="Nominal rod diameter [mm]",
)
_parser.add_argument("--cad", type=str, default="")
_parser.add_argument("--cae-seed", type=float, default=1.2, help="CAE global seed [mm]")
_parser.add_argument(
    "--cae-mesh-quality",
    choices=("fast", "lattice", "lattice_contact", "lattice_curve", "paper"),
    default="lattice_contact",
    help="CAE tet seeding preset (lattice_curve: force d/N seeds on curved struts)",
)
_parser.add_argument(
    "--cae-rods-per-diameter",
    type=float,
    default=3.0,
    help="Target tet count across strut diameter for edge seeding",
)
_parser.add_argument(
    "--cae-virtual-topology",
    action="store_true",
    help="CAE createVirtualTopology: merge small faces/edges before mesh",
)
_parser.add_argument(
    "--cae-mesh-inp",
    type=str,
    default="",
    help="Reuse existing CAE mesh INP (skip abaqus cae mesh step)",
)
_parser.add_argument(
    "--heal-step-before-cae",
    action="store_true",
    help="Gmsh OCC healShapes on STEP before CAE mesh (best mass-preserving preset)",
)
_parser.add_argument(
    "--heal-step-on-mesh-fail",
    action="store_true",
    help="On CAE mesh failure, retry with Gmsh-healed STEP presets",
)
_parser.add_argument("--cae-part-name", type=str, default="LATTICE")
_parser.add_argument(
    "--cae-element-type",
    choices=("C3D4", "C3D10", "C3D10M"),
    default="C3D4",
    help="Solid element type for CAE tet mesh and compression INP",
)
_parser.add_argument(
    "--slug-mode",
    choices=("long", "short"),
    default="long",
    help="long=hu_bai_* legacy slug; short=q05_c10m_s05r4_el_s78 style",
)
_parser.add_argument(
    "--short-slug",
    type=str,
    default="",
    help="Override auto short slug when --slug-mode short",
)
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
_parser.add_argument(
    "--contact-interference-fit",
    action="store_true",
    help="Explicit: gradual INTERFERENCE FIT for initial self-contact overclosures",
)
_parser.add_argument(
    "--contact-init-step-fraction",
    type=float,
    default=0.20,
    help="Step fraction for interference fit (default 0.20)",
)
_parser.add_argument(
    "--contact-soft-clearance",
    type=float,
    default=None,
    metavar="MM",
    help="Explicit general contact: SCALE FACTOR s0 (e.g. 0.08 = 8%% default stiffness)",
)
_parser.add_argument(
    "--contact-store-offsets",
    action="store_true",
    help="Explicit: AUTOMATIC OVERCLOSURE RESOLUTION → STORE OFFSETS (avoid t=0 nodal push)",
)
_parser.add_argument(
    "--contact-settle",
    action="store_true",
    help="Explicit two-step: ContactSettle (soft mu=0) then Compression",
)
_parser.add_argument(
    "--contact-settle-fraction",
    type=float,
    default=0.15,
    help="Extra settle time as fraction of compression step_time (default 0.15)",
)
_parser.add_argument(
    "--contact-settle-soft-s0",
    type=float,
    default=0.02,
    help="SETTLE-CONTACT SCALE FACTOR s0 (default 0.02)",
)
_parser.add_argument(
    "--no-mass-scaling",
    action="store_true",
    help="Omit *Fixed Mass Scaling from INP (mass scaling 原文未给出)",
)
_parser.add_argument(
    "--mass-scaling-factor",
    type=float,
    default=None,
    help=(
        "Fixed mass scaling factor for Explicit (default repo 50 if omitted; "
        "ignored when --no-mass-scaling). Use e.g. 10 for lower inertia lag."
    ),
)
_parser.add_argument(
    "--mass-scaling-mode",
    choices=("none", "uniform", "below_min"),
    default=None,
    help=(
        "none=omit; uniform=all-element factor only (recommended for KE/IE studies); "
        "below_min=scale up to target dt (legacy default with large dt forces huge mass). "
        "Default: below_min when a factor is used, none with --no-mass-scaling."
    ),
)
_parser.add_argument(
    "--mass-scaling-dt",
    type=float,
    default=None,
    help="BELOW MIN target stable dt [s]; default = --explicit-dt",
)
_parser.add_argument("--restart-interval", type=int, default=None)
_parser.add_argument(
    "--material-model",
    choices=(
        "neo_hooke",
        "paper",
        "hyperelastic",
        "elastic_plastic",
        "elastic",
        "marlow",
        "polynomial",
    ),
    default=None,
    help=(
        "neo_hooke (= paper/hyperelastic legacy) = Neo-Hooke; "
        "marlow/polynomial = Fig.2.5 WPD uniaxial; "
        "polynomial = test data input (Mooney-Rivlin fit); "
        "elastic = Fig.3.3 trend trials"
    ),
)
_parser.add_argument(
    "--tpu-fig25-json",
    type=str,
    default="data/hu_bai_tpu_fig25_tensile_traced.json",
    help="Traced Fig.2.5 tensile curve for --material-model marlow or polynomial",
)
_parser.add_argument(
    "--tpu-stress-scale",
    type=float,
    default=1.0,
    help=(
        "Multiply Fig.2.5 uniaxial engineering stress by this factor before Marlow/"
        "polynomial input (1.0 = as traced). Soften e.g. 0.77 to match Fig.3.3 early BCC."
    ),
)
_parser.add_argument(
    "--mesh-on-server",
    action="store_true",
    help="Run Abaqus/CAE mesh on Linux server via SSH (default on Windows)",
)
_parser.add_argument(
    "--mesh-locally",
    action="store_true",
    help="Run Abaqus/CAE mesh on this machine (default on Linux server)",
)
_parser.add_argument(
    "--remote-host",
    type=str,
    default=os.environ.get("HU_BAI_REMOTE_HOST", "art@172.20.200.93"),
    help="SSH host for --mesh-on-server (default art@172.20.200.93)",
)
_parser.add_argument(
    "--remote-root",
    type=str,
    default=os.environ.get("HU_BAI_REMOTE_ROOT", HUBAI_REMOTE_ROOT),
    help="Repo root on remote server",
)
_args = _parser.parse_args()

if _args.mesh_locally:
    MESH_ON_SERVER = False
elif _args.mesh_on_server:
    MESH_ON_SERVER = True
else:
    MESH_ON_SERVER = sys.platform == "win32"

PROFILE = _args.profile
CASE_SUFFIX_RAW = _args.case_suffix.strip().replace(" ", "_")
IS_FAST80 = CASE_SUFFIX_RAW == "fast80"
L = float(_args.L)
ROD_D = float(_args.rod_diameter)
AF = float(_args.Af)
Q = float(_args.Q)
NX = NY = NZ = int(_args.cells)
CAE_SEED = float(_args.cae_seed)
CAE_MESH_QUALITY = str(_args.cae_mesh_quality)
CAE_RODS_PER_DIAMETER = float(_args.cae_rods_per_diameter)
CAE_ELEMENT_TYPE = str(_args.cae_element_type).upper()
SLUG_MODE = str(_args.slug_mode).lower()

E_MODULUS = HU_BAI_E_MODULUS_MPA
POISSON = HU_BAI_POISSON
YIELD_MPA = HU_BAI_YIELD_MPA
DENSITY_KG_M3 = HU_BAI_DENSITY_KG_M3
DENSITY_ABQ = hu_bai_density_abq(DENSITY_KG_M3)
TPU_C10 = hu_bai_neo_hooke_c10(E_MODULUS, POISSON)

MATERIAL_KIND = _args.material_model
if MATERIAL_KIND is None:
    MATERIAL_KIND = "neo_hooke" if PROFILE == "paper" else "elastic_plastic"
# Canonicalize legacy aliases for manifest / slug
if is_neo_hooke_material(MATERIAL_KIND):
    MATERIAL_KIND = "neo_hooke"
USE_HYPERELASTIC = is_neo_hooke_material(MATERIAL_KIND)
TPU_STRESS_SCALE = float(_args.tpu_stress_scale)
if MATERIAL_KIND == "marlow":
    INP_MATERIAL_MODEL = "marlow"
    TPU_UNIAXIAL = load_tpu_fig25_uniaxial(
        _args.tpu_fig25_json, stress_scale=TPU_STRESS_SCALE
    )
elif MATERIAL_KIND == "polynomial":
    INP_MATERIAL_MODEL = "polynomial"
    TPU_UNIAXIAL = load_tpu_fig25_uniaxial(
        _args.tpu_fig25_json, stress_scale=TPU_STRESS_SCALE
    )
elif USE_HYPERELASTIC:
    INP_MATERIAL_MODEL = "neo_hooke"
    TPU_UNIAXIAL = None
else:
    INP_MATERIAL_MODEL = "elastic"
    TPU_UNIAXIAL = None
PLASTIC_YIELD = (
    None
    if USE_HYPERELASTIC or MATERIAL_KIND in ("elastic", "marlow", "polynomial")
    else YIELD_MPA
)

if PROFILE == "paper":
    TARGET_STRAIN = HU_BAI_TARGET_ENGINEERING_STRAIN
    LOAD_RATE_MM_MIN = HU_BAI_LOAD_RATE_MM_MIN
    if CAE_SEED > HU_BAI_MESH_MM + 1e-9:
        print(f"  [WARN] §2.4.1 mesh size is 0.6 mm; consider --cae-seed {HU_BAI_MESH_MM}", flush=True)
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
    print("  [paper profile] forcing explicit_dt_mode=fixed (KE/IE<5% per §2.4.1)", flush=True)
    EXPLICIT_DT_MODE = "fixed"
CASE_SUFFIX = CASE_SUFFIX_RAW or f"cae_tet{CAE_SEED:g}mm{int(round(TARGET_STRAIN * 100))}p_{int(LOAD_RATE_MM_MIN)}mmin"
STROKE_TAG = "f"
N_INC_EST = max(100, int(round(STEP_TIME / EXPLICIT_DT)))
if _args.no_mass_scaling:
    EXPLICIT_MASS_SCALING = None
    MASS_SCALING_MODE = "none"
elif _args.mass_scaling_mode == "below_min" and _args.mass_scaling_factor is None:
    # Uncapped BELOW MIN to --mass-scaling-dt (or explicit-dt): preferred KE/IE sweep.
    EXPLICIT_MASS_SCALING = None
    MASS_SCALING_MODE = "below_min"
elif _args.mass_scaling_factor is not None:
    if float(_args.mass_scaling_factor) <= 0.0:
        raise SystemExit("--mass-scaling-factor must be > 0 (or use --no-mass-scaling)")
    EXPLICIT_MASS_SCALING = float(_args.mass_scaling_factor)
    MASS_SCALING_MODE = _args.mass_scaling_mode or "below_min"
elif _args.mass_scaling_mode == "uniform":
    raise SystemExit("uniform mass scaling requires --mass-scaling-factor > 0")
else:
    EXPLICIT_MASS_SCALING = HU_BAI_EXPLICIT_MASS_SCALING
    MASS_SCALING_MODE = _args.mass_scaling_mode or "below_min"
if _args.mass_scaling_mode is not None and not _args.no_mass_scaling:
    MASS_SCALING_MODE = str(_args.mass_scaling_mode)
MASS_SCALING_DT = (
    float(_args.mass_scaling_dt) if _args.mass_scaling_dt is not None else None
)

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
if SLUG_MODE == "short":
    slug = (_args.short_slug.strip() or build_paperbox_short_slug(
        period_factor=Q,
        element_type=CAE_ELEMENT_TYPE,
        seed_mm=CAE_SEED,
        rods_per_diameter=CAE_RODS_PER_DIAMETER,
        material_model=MATERIAL_KIND or "elastic",
        target_strain=TARGET_STRAIN,
        contact_settle=bool(_args.contact_settle),
    ))
else:
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
    explicit_mass_scaling_factor=EXPLICIT_MASS_SCALING,
    explicit_mass_scaling_mode=MASS_SCALING_MODE,
    explicit_mass_scaling_dt=MASS_SCALING_DT,
    # uniform must not use legacy dt_only path
    explicit_mass_scaling_dt_only=(MASS_SCALING_MODE == "below_min" and EXPLICIT_MASS_SCALING is None),
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
    contact_init_interference_fit=bool(_args.contact_interference_fit),
    contact_init_step_fraction=float(_args.contact_init_step_fraction),
    contact_soft_clearance_mm=(
        float(_args.contact_soft_clearance)
        if _args.contact_soft_clearance is not None
        else None
    ),
    explicit_contact_settle=bool(_args.contact_settle),
    contact_settle_time_fraction=float(_args.contact_settle_fraction),
    contact_settle_soft_s0=float(_args.contact_settle_soft_s0),
    contact_overclosure_store_offsets=bool(_args.contact_store_offsets),
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
MESH_STEP_USED = step_path
STEP_HEAL_REPORT: dict | None = None

if cae_mesh_inp:
    if not os.path.isabs(cae_mesh_inp):
        cae_mesh_inp = os.path.join(_ROOT, cae_mesh_inp)
    if not os.path.isfile(cae_mesh_inp):
        raise FileNotFoundError(cae_mesh_inp)
    print(f"  Reusing CAE mesh INP: {cae_mesh_inp}", flush=True)
    MESH_LOCATION = "reuse"
else:
    cae_mesh_inp = paths["cae_mesh_inp"]

    def _invoke_cae_mesh(mesh_step: str) -> str:
        print(
            f"  CAE TET mesh STEP @ seed={CAE_SEED} mm "
            f"(quality={CAE_MESH_QUALITY}) ...",
            flush=True,
        )
        print(f"  mesh STEP: {mesh_step}", flush=True)
        loc = run_cae_mesh(
            _ROOT,
            mesh_step,
            cae_mesh_inp,
            CAE_SEED,
            _args.cae_part_name,
            mesh_on_server=MESH_ON_SERVER,
            remote_host=_args.remote_host.strip(),
            remote_root=_args.remote_root.strip(),
            mesh_mode="tet",
            mesh_quality=CAE_MESH_QUALITY,
            rod_diameter_mm=ROD_D,
            rods_per_diameter=CAE_RODS_PER_DIAMETER,
            virtual_topology=bool(_args.cae_virtual_topology),
            element_type=CAE_ELEMENT_TYPE,
        )
        if not os.path.isfile(cae_mesh_inp):
            raise FileNotFoundError(f"CAE mesh INP not written: {cae_mesh_inp}")
        return loc

    mesh_step = step_path
    step_heal_report: dict = {"original_step": step_path, "attempts": []}
    if _args.heal_step_before_cae:
        print("  Gmsh heal STEP before CAE mesh ...", flush=True)
        mesh_step, heal_pick = heal_step_for_cae(
            step_path,
            export_dir,
            basename=f"{slug}_cad_heal",
        )
        step_heal_report.update(heal_pick)

    mesh_exc: BaseException | None = None
    try:
        MESH_LOCATION = _invoke_cae_mesh(mesh_step)
        MESH_STEP_USED = mesh_step
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as exc:
        mesh_exc = exc
        if not _args.heal_step_on_mesh_fail:
            raise
        print(f"  CAE mesh failed ({exc!s}), trying Gmsh heal presets ...", flush=True)
        tried = {mesh_step}
        mesh_ok = False
        for preset in HEAL_PRESETS:
            label = str(preset["label"])
            healed = os.path.join(export_dir, f"{slug}_cad_heal_{label}.step")
            if healed in tried:
                continue
            try:
                rep = heal_step_once(
                    step_path,
                    healed,
                    distance_tol=float(preset["distance_tol"]),
                    fix_small=bool(preset.get("fix_small", True)),
                )
                rep["preset"] = label
                step_heal_report["attempts"].append(rep)
            except Exception as heal_exc:
                print(f"  heal FAIL preset={label}: {heal_exc}", flush=True)
                step_heal_report["attempts"].append(
                    {"preset": label, "error": str(heal_exc)},
                )
                continue
            tried.add(healed)
            try:
                print(f"  retry CAE mesh preset={label} -> {healed}", flush=True)
                MESH_LOCATION = _invoke_cae_mesh(healed)
                MESH_STEP_USED = healed
                step_heal_report["preset_used"] = label
                step_heal_report["healed_step"] = healed
                step_heal_report["used_heal"] = True
                mesh_ok = True
                break
            except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as retry_exc:
                print(f"  CAE mesh still failed preset={label}: {retry_exc!s}", flush=True)
        if not mesh_ok:
            raise RuntimeError(
                "CAE mesh failed on original STEP and all Gmsh heal presets"
            ) from mesh_exc

    if step_heal_report.get("attempts") or step_heal_report.get("used_heal"):
        STEP_HEAL_REPORT = step_heal_report
    print(f"  CAE mesh location: {MESH_LOCATION}", flush=True)

mesh_nodes, mesh_elements = parse_cae_mesh_inp(
    cae_mesh_inp,
    part_name=_args.cae_part_name,
    element_type=CAE_ELEMENT_TYPE,
)
elsets = {"solid": [int(e[0]) for e in mesh_elements]}
pre_mesh = (mesh_nodes, mesh_elements, elsets)
print(
    f"  Parsed CAE mesh: {len(mesh_nodes)} nodes, {len(mesh_elements)} {CAE_ELEMENT_TYPE}",
    flush=True,
)

stats = export_inp(
    nodes,
    beams,
    paths["compression_inp"],
    polylines=polylines,
    element_type=CAE_ELEMENT_TYPE,
    material_model=INP_MATERIAL_MODEL,
    material_name="TPU",
    c10=TPU_C10,
    elastic_e=E_MODULUS,
    elastic_nu=POISSON,
    plastic_yield=PLASTIC_YIELD,
    uniaxial_test_data=TPU_UNIAXIAL,
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
# from_export_stats sets reference area/height for top_down compression.
meta.plate_fixed_ref_node_id = int(
    stats.get("fixed_plate_ref_node_id", stats.get("plate_fixed_ref_node_id", 0)) or 0
)
save_compression_meta(meta, paths["meta_json"])

manifest = {
    "slug": slug,
    "slug_mode": SLUG_MODE,
    "legacy_case_suffix": CASE_SUFFIX if SLUG_MODE == "long" else None,
    "slug_descriptor": (
        paperbox_slug_descriptor(
            short_slug=slug,
            period_factor=Q,
            element_type=CAE_ELEMENT_TYPE,
            seed_mm=CAE_SEED,
            rods_per_diameter=CAE_RODS_PER_DIAMETER,
            mesh_quality=CAE_MESH_QUALITY,
            material_model=MATERIAL_KIND or "elastic",
            target_strain=TARGET_STRAIN,
            variant_name=gen.variant_name,
            cad_step=MESH_STEP_USED,
        )
        if SLUG_MODE == "short"
        else None
    ),
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
    "cad_step_meshed": MESH_STEP_USED,
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
        "E_MPa": E_MODULUS,
        "nu": POISSON,
        "yield_MPa": YIELD_MPA,
        "density_kg_m3": DENSITY_KG_M3,
        "neo_hooke_C10_MPa": TPU_C10 if USE_HYPERELASTIC else None,
        "fig25_json": _args.tpu_fig25_json if MATERIAL_KIND in ("marlow", "polynomial") else None,
        "fig25_n_points": len(TPU_UNIAXIAL) if TPU_UNIAXIAL else None,
        "fig25_stress_scale": TPU_STRESS_SCALE if MATERIAL_KIND in ("marlow", "polynomial") else None,
        "hyperelastic_fit": "polynomial_order1_testdata" if MATERIAL_KIND == "polynomial" else None,
    },
    "mesh": {
        "element": CAE_ELEMENT_TYPE,
        "method": "cae_tet",
        "source": "abaqus_cae_tet_free",
        "cae_seed_mm": CAE_SEED,
        "cae_mesh_quality": CAE_MESH_QUALITY,
        "cae_virtual_topology": bool(_args.cae_virtual_topology),
        "cae_rods_per_diameter": CAE_RODS_PER_DIAMETER,
        "cae_part_name": _args.cae_part_name,
        "cae_element_type": CAE_ELEMENT_TYPE,
        "mesh_location": MESH_LOCATION,
        "remote_host": _args.remote_host if MESH_ON_SERVER else None,
        "remote_root": _args.remote_root if MESH_ON_SERVER else None,
        "node_count": stats.get("node_count"),
        "element_count": stats.get("element_count"),
        "step_heal": STEP_HEAL_REPORT,
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
        "explicit_mass_scaling": EXPLICIT_MASS_SCALING,
        "explicit_mass_scaling_mode": MASS_SCALING_MODE,
        "explicit_mass_scaling_dt": MASS_SCALING_DT,
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
        "contact_init_interference_fit": compression.contact_init_interference_fit,
        "contact_init_step_fraction": compression.contact_init_step_fraction,
        "contact_soft_clearance_mm": compression.contact_soft_clearance_mm,
        "explicit_contact_settle": compression.explicit_contact_settle,
        "contact_settle_time_fraction": compression.contact_settle_time_fraction,
        "contact_settle_soft_s0": compression.contact_settle_soft_s0,
        "contact_overclosure_store_offsets": compression.contact_overclosure_store_offsets,
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
print(f"  Target engineering strain: {TARGET_STRAIN:.0%}")
print(
    f"  Loading: {COMPRESSION_DISP:.1f} mm / {STEP_TIME:.1f} s "
    f"({LOAD_RATE_MM_MIN:g} mm/min), mu={HU_BAI_FRICTION}"
)
if MASS_SCALING_MODE == "none":
    _ms_note = "none"
elif EXPLICIT_MASS_SCALING is None:
    _ms_dt = MASS_SCALING_DT if MASS_SCALING_DT is not None else EXPLICIT_DT
    _ms_note = f"{MASS_SCALING_MODE}:BELOW_MIN_dt={_ms_dt:g}"
else:
    _ms_note = f"{MASS_SCALING_MODE}:x{EXPLICIT_MASS_SCALING:g}"
print(
    f"  Explicit: dt_mode={EXPLICIT_DT_MODE}, dt={EXPLICIT_DT:g} s, "
    f"mass scaling {_ms_note}, ~{N_INC_EST} increments"
)
print(f"  Slug: {slug}")
print(f"  Server: scp export + jobs dirs, then bash scripts/linux/submit_job.sh --slug {slug}")
