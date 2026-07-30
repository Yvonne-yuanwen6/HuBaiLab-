"""Hu & Bai (2024) thesis parameters for COMSOL vibration-isolation models.

COMSOL Multiphysics 5.6 — §2.4.3 vibration FE model (Fig. 2.8):
  - Shaker table: AISI 4340 steel (COMSOL UNS G43400)
  - Top plate: aluminum alloy (COMSOL built-in)
  - Lattice: TPU Fig.2.5 tensile curve → Marlow hyperelastic (§2.3.2); ρ=1135 kg/m³
  - Excitation: prescribed sinusoidal acceleration, Y-axis, 0.98 m/s²
  - Mesh (Fig. 2.8 layered): lattice 0.6 mm fine; table ~40 mm + top footprint ~8 mm
    gradient; plate ~8 mm; split domain FreeTet (optional physics-controlled hauto)

Not quasi-static compression (that remains Abaqus §2.4.1 / Fig.3.3).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.export.abaqus_compression import (
    HU_BAI_DENSITY_KG_M3,
    HU_BAI_E_MODULUS_MPA,
    HU_BAI_MESH_MM,
    HU_BAI_POISSON,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import COMSOL_JOBS_ROOT, PROJECT_ROOT
from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON

# §2.4.3 — COMSOL built-in AISI 4340 steel (UNS G43400)
AISI_4340_E_GPA = 205.0
AISI_4340_POISSON = 0.29
AISI_4340_DENSITY_KG_M3 = 7850.0

# §2.4.3 — COMSOL built-in aluminum alloy (representative 6061)
ALUMINUM_ALLOY_E_GPA = 69.0
ALUMINUM_ALLOY_POISSON = 0.33
ALUMINUM_ALLOY_DENSITY_KG_M3 = 2700.0

# §2.4.3 prescribed sinusoidal base acceleration
THESIS_BASE_ACCELERATION_M_S2 = 0.98

# COMSOL Size hauto levels (physics-controlled element size)
# COMSOL preset index: 4=Fine(细化), 5=Normal(常规)
HAUTO_NORMAL = 5  # 常规
HAUTO_FINE = 4  # 细化

# Fig. 2.8 explicit hmax [mm] (default layered mesh)
MESH_FINE_LATTICE_MM = HU_BAI_MESH_MM
MESH_NORMAL_TABLE_MM = 40.0
MESH_NORMAL_PLATE_MM = 8.0
MESH_TABLE_CONTACT_HMAX_MM = 8.0
MESH_TABLE_CONTACT_DEPTH_MM = 40.0
MESH_TABLE_BULK_HGRAD = 1.7
MESH_TABLE_CONTACT_HGRAD = 1.5


@dataclass(frozen=True)
class HuBaiComsolSettings:
    """COMSOL isolation setup: geometry §2.1 + linear elastic TPU §2.3.2."""

    # Geometry §2.1
    Q: float = 0.0
    amplitude_mm: float = 2.0
    cell_size_mm: float = 20.0
    rod_diameter_mm: float = 2.0
    nx: int = 4
    ny: int = 4
    nz: int = 4

    # Material §2.3.2 Fig.2.5 tensile curve (Marlow) or linear fallback
    lattice_material_model: str = "marlow_uniaxial"  # marlow_uniaxial | linear_elastic
    tpu_tensile_curve_json: str = str(DEFAULT_TPU_FIG25_JSON)
    tpu_tensile_max_strain: float = 0.0  # 0 = full traced curve
    youngs_modulus_mpa: float = HU_BAI_E_MODULUS_MPA  # linear fallback / manifest reference
    poisson: float = HU_BAI_POISSON
    density_kg_m3: float = HU_BAI_DENSITY_KG_M3

    # Mesh §2.4.3 / Fig. 2.8 — layered split FreeTet (see mph_builder._build_fig28_layered_mesh)
    physics_controlled_mesh: bool = False  # True → hauto presets instead of explicit hmax
    skip_mesh: bool = False  # geometry + physics only (GUI inspection before meshing)
    lattice_hauto: int = HAUTO_FINE
    fixture_hauto: int = HAUTO_NORMAL
    mesh_mm: float = MESH_FINE_LATTICE_MM  # lattice hmax [mm]
    # Shaker top footprint under lattice/plate — local refine + hgrad into bulk table
    table_contact_refine: bool = True
    table_contact_refine_hmax_mm: float = MESH_TABLE_CONTACT_HMAX_MM
    table_contact_refine_depth_mm: float = MESH_TABLE_CONTACT_DEPTH_MM
    table_bulk_hgrad: float = MESH_TABLE_BULK_HGRAD
    table_contact_refine_hgrad: float = MESH_TABLE_CONTACT_HGRAD

    # Base mounting band for Box selections [mm]
    selection_band_mm: float = 1.0

    # §2.4.3 / Fig. 2.8 — shaker table + thin aluminum output plate
    include_shaker_fixture: bool = True
    shaker_table_size_xy_mm: float = 400.0  # Fig. 2.8 ±200 mm axes
    shaker_table_height_mm: float = 400.0  # cubic shaker block in Fig. 2.8
    shaker_table_youngs_gpa: float = AISI_4340_E_GPA
    shaker_table_poisson: float = AISI_4340_POISSON
    shaker_table_density_kg_m3: float = AISI_4340_DENSITY_KG_M3
    shaker_mesh_mm: float = MESH_NORMAL_TABLE_MM
    top_plate_size_xy_mm: float = 0.0  # 0 => footprint + 1×cell_size (one-cell ring)
    top_plate_thickness_mm: float = 0.5  # thin sheet (Fig. 2.8 / Table 3.3 setup)
    top_plate_margin_mm: float = 0.0  # >0 overrides ring → footprint + 2×margin
    top_plate_youngs_gpa: float = ALUMINUM_ALLOY_E_GPA
    top_plate_poisson: float = ALUMINUM_ALLOY_POISSON
    top_plate_density_kg_m3: float = ALUMINUM_ALLOY_DENSITY_KG_M3
    top_plate_mesh_mm: float = MESH_NORMAL_PLATE_MM
    # §2.4.3 experiment: 300 g payload above output plate (Table 3.3 modal test)
    include_top_payload: bool = True
    top_payload_mass_kg: float = 0.3
    # Form Assembly domain order (resolved at build time via ball probe in mph_builder)
    domain_lattice: int = 3
    domain_shaker_table: int = 1
    domain_top_plate: int = 2

    # Eigenfrequency study (COMSOL Ref.: shift-invert + LM = closest |f−shift|; SME §2.4)
    run_eigen: bool = True
    n_eigenmodes: int = 30
    eigen_search: str = "lm"  # closest in absolute value to shift (COMSOL default)
    eigen_shift_hz: float | None = 15.0  # Hz; ~Table 3.3 BCC mode 1 (14.8)
    eigen_min_hz: float = 1.0  # exclude near-zero / constraint modes when ranking
    eigen_mpf_tag: str = "mpf1"
    study_eigen_tag: str = "std_eigen"
    eigen_feature_tag: str = "eig"

    # §2.4.3 harmonic excitation (frequency study)
    # 论文：指定加速度加在振动台顶面（输入端）；COMSOL 5.6 用 Displacement2 u=A/ω² 等效
    excitation_type: str = "acceleration"  # 指定加速度
    excitation_axis: str = "z"  # repo STEP 为 Z 向堆叠；论文文字为 Y 轴
    base_acceleration_m_s2: float = THESIS_BASE_ACCELERATION_M_S2
    base_displacement_mm: float = 1.0  # only if excitation_type == "displacement"

    # Frequency-domain harmonic study (sweep range: repo default, not in §2.4.3 excerpt)
    run_frequency: bool = True
    study_freq_tag: str = "std_freq"
    freq_feature_tag: str = "freq"
    freq_min_hz: float = 10.0
    freq_max_hz: float = 2000.0
    freq_step_hz: float = 10.0
    # Solid Mechanics displacement shape order: 2=quadratic (default), 1=linear (low-RAM)
    solid_displacement_order: int = 2
    # Frequency study linear solver: direct (default) | iterative (GMRES, low-RAM)
    freq_linear_solver: str = "direct"

    step_path: str = ""
    slug: str = ""
    fixture_template_path: str = ""
    save_fixture_template: bool = False

    # Interface coupling strategy (Fig.2.8 assembly interfaces):
    #   p1_continuity   — fin identity ap1/ap2 + Solid Mechanics Continuity (paper-like, fast)
    #   p2_contact_all  — manual Contact pairs tbl–lat + plt–lat, Penalty bonded (slow)
    #   p3_contact_auto — fin auto Contact pairs ap1/ap2 + Penalty (imprint-native)
    interface_coupling: str = "p1_continuity"

    extra: dict[str, str | float | int | bool] = field(default_factory=dict)

    @property
    def fixture_template_mph(self) -> Path:
        if self.fixture_template_path:
            return Path(self.fixture_template_path)
        # Always use global fixture under output/comsol_jobs/ — do NOT follow
        # HU_BAI_COMSOL_JOBS_ROOT (batch per-case redirect would miss the template).
        return PROJECT_ROOT / "output" / "comsol_jobs" / "comsol_fixture_444" / "comsol_fixture_444.mph"

    @property
    def variant_name(self) -> str:
        gen = HuBaiLatticeGenerator(
            cell_size=self.cell_size_mm,
            rod_diameter=self.rod_diameter_mm,
            amplitude=self.amplitude_mm,
            period_factor=self.Q,
        )
        return gen.variant_name.lower()

    @property
    def lattice_height_mm(self) -> float:
        return float(self.nz) * float(self.cell_size_mm)

    @property
    def paper_box_import_center_mm(self) -> tuple[float, float, float]:
        """Paper_box array envelope centre in STEP coords (``origin_centered=False``).

        Single-cell seed is paper_box-cut at the origin (±L/2).  An n×n×n array
        spans [-L/2, (n−1)·L + L/2] per axis → centre = (n−1)·L/2.  Solid bbox
        is asymmetric (~±1 mm pipe overhang); align the **design envelope** to
        Fig. 2.8 ±(nL/2), not the axis-aligned bbox centre.
        """
        cx = 0.5 * (float(self.nx) - 1.0) * float(self.cell_size_mm)
        cy = 0.5 * (float(self.ny) - 1.0) * float(self.cell_size_mm)
        cz = 0.5 * (float(self.nz) - 1.0) * float(self.cell_size_mm)
        return (cx, cy, cz)

    @property
    def footprint_mm(self) -> float:
        return max(self.nx, self.ny) * self.cell_size_mm

    @property
    def half_xy_mm(self) -> float:
        return 0.5 * self.footprint_mm + 10.0

    @property
    def z_min_mm(self) -> float:
        return -0.5 * self.lattice_height_mm

    @property
    def z_max_mm(self) -> float:
        return 0.5 * self.lattice_height_mm

    @property
    def shaker_table_z_bottom_mm(self) -> float:
        return self.z_min_mm - self.shaker_table_height_mm

    @property
    def top_plate_xy_mm(self) -> float:
        if self.top_plate_size_xy_mm > 0.0:
            return self.top_plate_size_xy_mm
        if self.top_plate_margin_mm > 0.0:
            return self.footprint_mm + 2.0 * self.top_plate_margin_mm
        # 比点阵平面大一圈：4×4×L20 → 80+20=100 mm，每侧外扩 L/2
        return self.footprint_mm + self.cell_size_mm

    @property
    def shaker_half_xy_mm(self) -> float:
        return 0.5 * self.shaker_table_size_xy_mm

    @property
    def top_plate_half_xy_mm(self) -> float:
        return 0.5 * self.top_plate_xy_mm

    @property
    def excitation_acceleration_expr(self) -> str:
        """Harmonic acceleration amplitude a = ω²|u| along excitation axis (COMSOL 5.6)."""
        return {
            "x": "abs((2*pi*freq)^2*u)",
            "y": "abs((2*pi*freq)^2*v)",
            "z": "abs((2*pi*freq)^2*w)",
        }.get(self.excitation_axis.lower(), "abs((2*pi*freq)^2*w)")

    @property
    def excitation_displacement_expr(self) -> str:
        """Solid-mechanics displacement component for probes / transmissibility."""
        return {"x": "u", "y": "v", "z": "w"}.get(self.excitation_axis.lower(), "v")

    def excitation_vector(self, *, acceleration: bool) -> list[str]:
        """3-vector for PrescribedAcceleration (m/s²) or Displacement2 (mm)."""
        param = "A_base" if acceleration else "A_disp"
        vec = ["0", "0", "0"]
        idx = {"x": 0, "y": 1, "z": 2}.get(self.excitation_axis.lower(), 1)
        vec[idx] = param
        return vec

    def excitation_displacement_harmonic_vector(self) -> list[str]:
        """Harmonic displacement amplitude u = A/ω² (mm) for COMSOL 5.6 fallback."""
        expr = "A_base/(2*pi*freq)^2*1000"
        vec = ["0", "0", "0"]
        idx = {"x": 0, "y": 1, "z": 2}.get(self.excitation_axis.lower(), 2)
        vec[idx] = expr
        return vec

    @property
    def harmonic_rigid_drive_displacement_mm_expr(self) -> str:
        """Rigid-body drive on shaker table top (COMSOL 5.6 Displacement2 u=A/ω²)."""
        if self.excitation_type == "acceleration":
            return "A_base/(2*pi*freq)^2*1000[mm/m]"
        return "A_disp"

    @property
    def relative_displacement_magnitude_expr(self) -> str:
        """|u_rel| w.r.t. measured input-plane motion (pb_base boundary probe).

        COMSOL 5.6: probe tags are valid in Results expressions (unlike Average
        coupling operators on solved .mph).  Prescribed A/(2πf)² drive is only
        ~0.1 mm at 15 Hz while |w|~10³ mm on the lattice, so subtracting the
        analytical drive does nothing; pb_base tracks the actual input plane.
        """
        comp = self.excitation_displacement_expr
        terms: list[str] = []
        for _ax, field in (("x", "u"), ("y", "v"), ("z", "w")):
            if field == comp:
                terms.append(f"({field}-pb_base)^2")
            else:
                terms.append(f"{field}^2")
        return f"sqrt({' + '.join(terms)})"

    def freq_list_expression(self) -> str:
        return f"range({self.freq_min_hz},{self.freq_step_hz},{self.freq_max_hz})"

    def default_slug(self) -> str:
        if self.slug:
            return self.slug
        studies = []
        if self.run_eigen:
            studies.append("eigen")
        if self.run_frequency:
            studies.append("freq")
        tag = "+".join(studies) if studies else "iso"
        fixture = "_fig28" if self.include_shaker_fixture else ""
        return (
            f"hu_bai_{self.variant_name}_L{int(self.cell_size_mm)}_"
            f"{self.nx}x{self.ny}x{self.nz}_comsol_iso{fixture}_{tag}"
        )

    def job_dir(self) -> Path:
        return COMSOL_JOBS_ROOT / self.default_slug()

    def manifest_path(self) -> Path:
        return self.job_dir() / "case_manifest.json"

    def primary_study_tag(self) -> str:
        if self.run_eigen:
            return self.study_eigen_tag
        if self.run_frequency:
            return self.study_freq_tag
        return self.study_eigen_tag

    def write_manifest(
        self,
        path: Path | None = None,
        *,
        mode: str = "isolation",
    ) -> Path:
        out = path or self.manifest_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "slug": self.default_slug(),
            "solver": "comsol",
            "mode": mode,
            "thesis": "Hu & Bai 2024 — COMSOL vibration isolation (not §2.4 compression)",
            "abaqus_compression": "Use Abaqus for Fig.3.3 stress–strain / energy plots",
            "geometry": {
                "variant": self.variant_name,
                "Q": self.Q,
                "amplitude_mm": self.amplitude_mm,
                "cells": [self.nx, self.ny, self.nz],
                "cell_size_mm": self.cell_size_mm,
                "rod_diameter_mm": self.rod_diameter_mm,
                "height_mm": self.lattice_height_mm,
                "paper_box_import_center_mm": list(self.paper_box_import_center_mm),
                "z_envelope_mm": [self.z_min_mm, self.z_max_mm],
            },
            "material": {
                "lattice_model": self.lattice_material_model,
                "tpu_tensile_curve": self.tpu_tensile_curve_json,
                "E_MPa_linear_ref": self.youngs_modulus_mpa,
                "nu": self.poisson,
                "rho_kg_m3": self.density_kg_m3,
            },
            "mesh_mm": self.mesh_mm,
            "interface_coupling": self.interface_coupling,
            "fig28_fixture": {
                "enabled": self.include_shaker_fixture,
                "thesis": "§2.4.3 / Fig. 2.8",
                "shaker_table_mm": [
                    self.shaker_table_size_xy_mm,
                    self.shaker_table_size_xy_mm,
                    self.shaker_table_height_mm,
                ],
                "shaker_material": {
                    "name": "AISI 4340 steel (UNS G43400)",
                    "E_GPa": self.shaker_table_youngs_gpa,
                    "nu": self.shaker_table_poisson,
                    "rho_kg_m3": self.shaker_table_density_kg_m3,
                },
                "top_plate_mm": [self.top_plate_xy_mm, self.top_plate_xy_mm, self.top_plate_thickness_mm],
                "top_plate_material": {
                    "name": "Aluminum alloy (COMSOL built-in)",
                    "E_GPa": self.top_plate_youngs_gpa,
                    "nu": self.top_plate_poisson,
                    "rho_kg_m3": self.top_plate_density_kg_m3,
                },
                "mesh": {
                    "skipped": self.skip_mesh,
                    "strategy": (
                        "skipped"
                        if self.skip_mesh
                        else (
                            "physics_controlled_hauto"
                            if self.physics_controlled_mesh
                            else "fig28_layered_hmax"
                        )
                    ),
                    "split_freetet": True,
                    "lattice_hmax_mm": self.mesh_mm,
                    "table_hmax_mm": self.shaker_mesh_mm,
                    "plate_hmax_mm": self.top_plate_mesh_mm,
                    "table_contact_refine": self.table_contact_refine,
                    "table_contact_hmax_mm": self.table_contact_refine_hmax_mm,
                    "table_contact_depth_mm": self.table_contact_refine_depth_mm,
                    "table_bulk_hgrad": self.table_bulk_hgrad,
                    "table_contact_hgrad": self.table_contact_refine_hgrad,
                    "lattice_hauto": self.lattice_hauto,
                    "fixture_hauto": self.fixture_hauto,
                },
                "domains": {
                    "lattice": self.domain_lattice,
                    "shaker_table": self.domain_shaker_table,
                    "top_plate": self.domain_top_plate,
                },
                "top_payload_kg": self.top_payload_mass_kg if self.include_top_payload else 0.0,
            },
            "isolation": {
                "run_eigen": self.run_eigen,
                "n_eigenmodes": self.n_eigenmodes,
                "eigen_search": self.eigen_search,
                "eigen_shift_hz": self.eigen_shift_hz,
                "eigen_min_hz": self.eigen_min_hz,
                "study_eigen": self.study_eigen_tag,
                "run_frequency": self.run_frequency,
                "study_freq": self.study_freq_tag,
                "freq_hz": [self.freq_min_hz, self.freq_max_hz, self.freq_step_hz],
                "excitation": {
                    "type": self.excitation_type,
                    "axis": self.excitation_axis,
                    "acceleration_m_s2": self.base_acceleration_m_s2,
                    "displacement_mm": self.base_displacement_mm,
                },
                "outputs": [
                    "eigenfrequencies_Hz",
                    "transmissibility_top_over_base",
                ],
            },
            "paths": {
                "step": str(Path(self.step_path).resolve()) if self.step_path else "",
                "job_dir": str(self.job_dir().resolve()),
                "project_root": str(PROJECT_ROOT.resolve()),
                "docs": str((PROJECT_ROOT / "docs" / "COMSOL隔振工作流.md").resolve()),
            },
            "settings": asdict(self),
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return out
