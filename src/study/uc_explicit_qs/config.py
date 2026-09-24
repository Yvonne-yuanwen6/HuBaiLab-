"""Centralized parameters for unit-cell Explicit quasi-static studies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MeshParams:
    """Mesh knobs reserved for later C3D10M convergence studies."""

    element_type: str = "C3D10M"  # C3D4 | C3D10 | C3D10M
    seed_mm: float = 0.6
    rods_per_diameter: float = 3.0
    mesh_quality: str = "lattice_curve"
    virtual_topology: bool = True
    # If set, reuse an existing CAE mesh INP (skip remesh).
    reuse_mesh_inp: str | None = None


@dataclass(frozen=True)
class PhysicsParams:
    """Geometry / material / BC / contact kept identical across rate cases."""

    Q: float = 0.5
    Af: float = 2.0
    cells: int = 1  # 1 = unit cell; later 4 for 4×4×4
    L_mm: float = 20.0
    rod_diameter_mm: float = 2.0
    cad_step: str = (
        "output/cad/verified/hu_bai_sfbls_af2q0p5_L20_1x1x1_paper_box_array.step"
    )
    material_model: str = "neo_hooke"
    strain: float = 0.80
    contact_mode: str = "pair"
    contact_store_offsets: bool = True
    contact_settle: bool = True
    contact_settle_fraction: float = 0.15
    explicit_dt: float = 5.0e-4
    explicit_dt_mode: str = "automatic"  # fixed | automatic
    # Mass-scaling knobs (for later QS tuning if rate alone is insufficient).
    mass_scaling_mode: str | None = None  # none | uniform | below_min | None=export default
    mass_scaling_factor: float | None = None
    mass_scaling_dt: float | None = None
    no_mass_scaling: bool = False


@dataclass(frozen=True)
class RateCase:
    """One load-rate variant."""

    case_id: str
    label: str
    load_rate_mm_min: float
    rate_factor_vs_baseline: float  # 1.0 = baseline, 0.2 = 5× slower, etc.

    def suffix(self, mesh: MeshParams, strain_pct: int) -> str:
        """Unique case-suffix fragment for paperbox slug builder."""
        et = mesh.element_type.lower().replace("c3d", "c3d")
        seed_tag = f"{mesh.seed_mm:g}".replace(".", "p")
        rods_tag = f"{mesh.rods_per_diameter:g}".replace(".", "p")
        rate_tag = f"{self.load_rate_mm_min:g}".replace(".", "p")
        return (
            f"cae_tet{seed_tag}mm{strain_pct}_"
            f"{rate_tag}mmin_uc_{et}_r{rods_tag}_{self.case_id}"
        )


@dataclass(frozen=True)
class MassScaleCase:
    """One mass-scaling variant (geometry / rate fixed)."""

    case_id: str
    label: str
    # none | below_min
    mode: str
    # For below_min: target dt = dt_factor_vs_natural * natural_stable_dt
    dt_factor_vs_natural: float | None = None
    no_mass_scaling: bool = False

    def suffix(
        self,
        mesh: MeshParams,
        *,
        strain_pct: int,
        load_rate_mm_min: float,
    ) -> str:
        et = mesh.element_type.lower()
        seed_tag = f"{mesh.seed_mm:g}".replace(".", "p")
        rods_tag = f"{mesh.rods_per_diameter:g}".replace(".", "p")
        rate_tag = f"{load_rate_mm_min:g}".replace(".", "p")
        return (
            f"cae_tet{seed_tag}mm{strain_pct}_"
            f"{rate_tag}mmin_uc_{et}_r{rods_tag}_{self.case_id}"
        )


@dataclass
class MassScaleStudyConfig:
    """C3D10M mass-scaling sensitivity (fixed rate / mesh / material / BC)."""

    name: str = "q05_uc_c3d10m_qs_mass_scale"
    physics: PhysicsParams = field(default_factory=PhysicsParams)
    mesh: MeshParams = field(default_factory=MeshParams)
    # Fixed loading rate for the MS sweep (prefer slower successful rate).
    load_rate_mm_min: float = 1.0
    # Natural / unscaled stable dt estimate from prior STA (s).
    natural_stable_dt_s: float = 4.767e-4
    # Factors: 0 → no MS; 5 → BELOW MIN dt=5×natural; 10 → 10×natural
    mass_scale_dt_factors: tuple[float, ...] = (0.0, 5.0, 10.0)
    cpus: int = 6
    memory_mb: int = 6144
    abaqus_cmd: str = "abaqus"
    modes: tuple[str, ...] = ("export", "submit", "post", "compare")
    only_case_ids: tuple[str, ...] | None = None
    ke_ie_limit: float = 0.05
    # Peak-force change vs no-MS baseline accepted if |ΔF|/F0 < this.
    peak_force_tol: float = 0.05
    baseline_case_id: str = "MS0"

    def mass_scale_cases(self) -> list[MassScaleCase]:
        cases: list[MassScaleCase] = []
        for fac in self.mass_scale_dt_factors:
            if fac <= 0.0:
                cases.append(
                    MassScaleCase(
                        case_id="MS0",
                        label="no mass scaling",
                        mode="none",
                        dt_factor_vs_natural=None,
                        no_mass_scaling=True,
                    )
                )
            else:
                cid = f"MS{int(round(fac))}"
                cases.append(
                    MassScaleCase(
                        case_id=cid,
                        label=f"BELOW MIN dt={fac:g}× natural",
                        mode="below_min",
                        dt_factor_vs_natural=float(fac),
                        no_mass_scaling=False,
                    )
                )
        if self.only_case_ids:
            # Preserve caller order (e.g. MS10,MS5,MS0 → submit fastest first).
            by_id = {c.case_id: c for c in cases}
            ordered = [by_id[cid.strip()] for cid in self.only_case_ids if cid.strip() in by_id]
            cases = ordered
        return cases

    def target_dt_s(self, case: MassScaleCase) -> float | None:
        if case.no_mass_scaling or case.dt_factor_vs_natural is None:
            return None
        return float(case.dt_factor_vs_natural) * float(self.natural_stable_dt_s)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def default_q05_c3d10m(
        *,
        reuse_mesh_inp: str | None = None,
        load_rate_mm_min: float = 1.0,
        natural_stable_dt_s: float = 4.767e-4,
    ) -> MassScaleStudyConfig:
        return MassScaleStudyConfig(
            name="q05_uc_c3d10m_qs_mass_scale",
            load_rate_mm_min=load_rate_mm_min,
            natural_stable_dt_s=natural_stable_dt_s,
            mass_scale_dt_factors=(0.0, 5.0, 10.0),
            mesh=MeshParams(
                element_type="C3D10M",
                seed_mm=0.6,
                rods_per_diameter=3.0,
                mesh_quality="lattice_curve",
                virtual_topology=True,
                reuse_mesh_inp=reuse_mesh_inp,
            ),
            physics=PhysicsParams(
                Q=0.5,
                cells=1,
                L_mm=20.0,
                rod_diameter_mm=2.0,
                material_model="neo_hooke",
                strain=0.80,
                contact_store_offsets=True,
                contact_settle=True,
                # Per-case mass scaling overrides this in export.
                no_mass_scaling=False,
                mass_scaling_mode=None,
            ),
        )


@dataclass
class StudyConfig:
    """Full study definition: shared physics + mesh + rate matrix."""

    name: str = "q05_uc_c3d10m_qs_rate"
    physics: PhysicsParams = field(default_factory=PhysicsParams)
    mesh: MeshParams = field(default_factory=MeshParams)
    baseline_load_rate_mm_min: float = 5.0
    rate_slowdown_factors: tuple[float, ...] = (1.0, 5.0, 10.0)
    # Compute / IO
    cpus: int = 6
    memory_mb: int = 6144
    abaqus_cmd: str = "abaqus"
    modes: tuple[str, ...] = ("export", "submit", "post", "compare")
    only_case_ids: tuple[str, ...] | None = None
    skip_mesh_if_exists: bool = True
    ke_ie_limit: float = 0.05  # QS pass if max KE/IE after early transient < this

    def rate_cases(self) -> list[RateCase]:
        cases: list[RateCase] = []
        for factor in self.rate_slowdown_factors:
            rate = self.baseline_load_rate_mm_min / float(factor)
            if abs(factor - 1.0) < 1e-12:
                cid, label = "R1", f"baseline {rate:g} mm/min"
            else:
                cid = f"R{int(round(factor))}x"
                label = f"{factor:g}× slower ({rate:g} mm/min)"
            cases.append(
                RateCase(
                    case_id=cid,
                    label=label,
                    load_rate_mm_min=rate,
                    rate_factor_vs_baseline=1.0 / float(factor),
                )
            )
        if self.only_case_ids:
            want = {x.strip() for x in self.only_case_ids}
            cases = [c for c in cases if c.case_id in want]
        return cases

    def with_mesh(self, **kwargs: Any) -> StudyConfig:
        return replace(self, mesh=replace(self.mesh, **kwargs))

    def with_physics(self, **kwargs: Any) -> StudyConfig:
        return replace(self, physics=replace(self.physics, **kwargs))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def default_q05_c3d10m(
        *,
        reuse_mesh_inp: str | None = None,
        baseline_rate_mm_min: float = 5.0,
    ) -> StudyConfig:
        """Factory matching completed Model C setup."""
        return StudyConfig(
            name="q05_uc_c3d10m_qs_rate",
            baseline_load_rate_mm_min=baseline_rate_mm_min,
            rate_slowdown_factors=(1.0, 5.0, 10.0),
            mesh=MeshParams(
                element_type="C3D10M",
                seed_mm=0.6,
                rods_per_diameter=3.0,
                mesh_quality="lattice_curve",
                virtual_topology=True,
                reuse_mesh_inp=reuse_mesh_inp,
            ),
            physics=PhysicsParams(
                Q=0.5,
                cells=1,
                L_mm=20.0,
                rod_diameter_mm=2.0,
                material_model="neo_hooke",
                strain=0.80,
                contact_store_offsets=True,
                contact_settle=True,
            ),
        )


@dataclass
class QsOptStudyConfig:
    """Further QS optimization after MS5 selection: rate × mild mass scaling."""

    name: str = "q05_uc_c3d10m_qs_opt"
    physics: PhysicsParams = field(default_factory=PhysicsParams)
    mesh: MeshParams = field(default_factory=MeshParams)
    natural_stable_dt_s: float = 4.767e-4
    # (case_id, rate_mm_min, ms_dt_factor[, reuse_slug])
    # Default A/B/C matrix requested after MS study.
    case_specs: tuple[tuple[Any, ...], ...] = (
        ("A", 1.0, 5.0, "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_cae_tet0p6mm80_1mmin_uc_c3d10m_r3_MS5"),
        ("B", 0.5, 5.0, None),
        ("C", 0.5, 3.0, None),
    )
    cpus: int = 6
    memory_mb: int = 6144
    abaqus_cmd: str = "abaqus"
    modes: tuple[str, ...] = ("export", "submit", "post", "compare", "paper")
    only_case_ids: tuple[str, ...] | None = None
    ke_ie_limit: float = 0.05
    peak_force_tol: float = 0.05
    baseline_case_id: str = "A"
    failed_elem_id: int = 12488
    snapshot_fractions: tuple[float, ...] = (0.0, 0.30, 0.60, 1.0)

    def qs_opt_cases(self) -> list[QsOptCase]:
        cases: list[QsOptCase] = []
        for spec in self.case_specs:
            cid = str(spec[0])
            rate = float(spec[1])
            fac = float(spec[2])
            reuse = spec[3] if len(spec) > 3 else None
            cases.append(
                QsOptCase(
                    case_id=cid,
                    label=f"{rate:g} mm/min + MS{int(round(fac))}",
                    load_rate_mm_min=rate,
                    ms_dt_factor=fac,
                    reuse_job_slug=str(reuse) if reuse else None,
                )
            )
        if self.only_case_ids:
            by_id = {c.case_id: c for c in cases}
            cases = [by_id[x] for x in self.only_case_ids if x in by_id]
        return cases

    def target_dt_s(self, case: QsOptCase) -> float:
        return float(case.ms_dt_factor) * float(self.natural_stable_dt_s)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QsOptCase:
    """One rate × mass-scaling optimization case."""

    case_id: str
    label: str
    load_rate_mm_min: float
    ms_dt_factor: float
    reuse_job_slug: str | None = None

    def suffix(self, mesh: MeshParams, *, strain_pct: int) -> str:
        et = mesh.element_type.lower()
        seed_tag = f"{mesh.seed_mm:g}".replace(".", "p")
        rods_tag = f"{mesh.rods_per_diameter:g}".replace(".", "p")
        rate_tag = f"{self.load_rate_mm_min:g}".replace(".", "p")
        ms_tag = f"MS{int(round(self.ms_dt_factor))}"
        return (
            f"cae_tet{seed_tag}mm{strain_pct}_"
            f"{rate_tag}mmin_uc_{et}_r{rods_tag}_{self.case_id}{ms_tag}"
        )


@dataclass(frozen=True)
class LatticeStudyParams:
    """Shared parameter interface for UC → 4×4×4 Explicit QS studies.

    Keep these four knobs explicit so later array models reuse the same API:
      - element_type / mesh size (seed + rods_per_diameter)
      - mass_scaling (mode + target dt or factor)
      - loading_rate_mm_min
    """

    element_type: str = "C3D10M"
    mesh_seed_mm: float = 0.6
    rods_per_diameter: float = 3.0
    mass_scaling_mode: str = "none"  # none | below_min | uniform
    mass_scaling_dt_s: float | None = None
    mass_scaling_factor: float | None = None
    loading_rate_mm_min: float = 1.0
    cells: int = 1  # 1=UC, 4=4×4×4

    def to_mesh(self, *, reuse_mesh_inp: str | None = None) -> MeshParams:
        return MeshParams(
            element_type=self.element_type,
            seed_mm=self.mesh_seed_mm,
            rods_per_diameter=self.rods_per_diameter,
            reuse_mesh_inp=reuse_mesh_inp,
        )

    def apply_mass_scaling(self, phy: PhysicsParams) -> PhysicsParams:
        if self.mass_scaling_mode in ("", "none", "off"):
            return replace(phy, no_mass_scaling=True, mass_scaling_mode="none")
        return replace(
            phy,
            no_mass_scaling=False,
            mass_scaling_mode=self.mass_scaling_mode,
            mass_scaling_dt=self.mass_scaling_dt_s,
            mass_scaling_factor=self.mass_scaling_factor,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_path(root: Path, maybe_rel: str | Path) -> Path:
    p = Path(maybe_rel)
    return p if p.is_absolute() else (root / p).resolve()
