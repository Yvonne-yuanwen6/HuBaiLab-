"""Hu & Bai Abaqus paper_box compression settings for UI export/submit."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paperbox_slug import build_paperbox_short_slug
from src.paths import PROJECT_ROOT


@dataclass
class HuBaiAbaqusSettings:
    Q: float = 0.0
    Af: float = 2.0
    cells: int = 4
    cell_size: float = 20.0
    rod_diameter: float = 2.0
    structure: str = ""  # "bcc" | "sfbls" | "" (infer from Q)
    cad_path: str = ""
    cae_seed_mm: float = 0.6
    cae_mesh_quality: str = "lattice_contact"
    cae_rods_per_diameter: float = 3.0
    cae_virtual_topology: bool = True
    cae_element_type: str = "C3D4"
    slug_mode: str = "long"
    short_slug: str = ""
    profile: str = "fast"
    strain: float = 0.80
    load_rate_mm_min: float = 5.0
    material_model: str = "neo_hooke"
    contact_store_offsets: bool = True
    contact_settle: bool = True
    case_suffix: str = "cae_tet0p6mm80_5mmin_paperbox"
    mesh_on_server: bool = True
    mesh_locally: bool = False
    remote_host: str = ""
    remote_root: str = ""
    submit_target: str = "remote"
    submit_cpus: int = 48
    submit_memory_mb: int = 262144
    submit_recover: bool = False
    submit_restart_from: str = ""

    def _normalized_structure(self) -> str:
        s = (self.structure or "").strip().lower()
        if s in ("bcc", "sfbls"):
            return s
        return "bcc" if float(self.Q) <= 0.0 else "sfbls"

    def _effective_Q(self) -> float:
        s = self._normalized_structure()
        if s == "bcc":
            return 0.0
        q = float(self.Q)
        return q if q > 0.0 else 0.5

    def _generator(self) -> HuBaiLatticeGenerator:
        gen = HuBaiLatticeGenerator(
            cell_size=float(self.cell_size),
            rod_diameter=float(self.rod_diameter),
            amplitude=self.Af,
            period_factor=self._effective_Q(),
            n_segments=12,
        )
        gen.build_lattice(self.cells, self.cells, self.cells)
        return gen

    @property
    def variant_name(self) -> str:
        return self._generator().variant_name.lower()

    def slug_preview(self) -> str:
        gen = self._generator()
        L = float(self.cell_size)
        nx = ny = nz = self.cells
        stroke_tag = "f"
        if self.slug_mode == "short":
            if self.short_slug.strip():
                return self.short_slug.strip()
            return build_paperbox_short_slug(
                period_factor=self._effective_Q(),
                element_type=self.cae_element_type,
                seed_mm=self.cae_seed_mm,
                rods_per_diameter=self.cae_rods_per_diameter,
                material_model=self.material_model,
                target_strain=self.strain,
                contact_settle=self.contact_settle,
            )
        base = f"hu_bai_{gen.variant_name.lower()}_L{int(L)}_{nx}x{ny}x{nz}_solid_cad_{stroke_tag}"
        suffix = self.case_suffix.strip().replace(" ", "_")
        if suffix:
            return f"{base}_{suffix}"
        seed_tag = f"cae_tet{self.cae_seed_mm:g}mm{int(round(self.strain * 100))}p_{int(self.load_rate_mm_min)}mmin"
        return f"{base}_{seed_tag}"

    def to_export_argv(self) -> list[str]:
        script = PROJECT_ROOT / "scripts" / "run_hu_bai_bcc_solid_cad_cae_tet_export.py"
        argv = [
            str(script),
            "--Q",
            str(self._effective_Q()),
            "--Af",
            str(self.Af),
            "--cells",
            str(self.cells),
            "--L",
            str(self.cell_size),
            "--rod-diameter",
            str(self.rod_diameter),
            "--cae-seed",
            str(self.cae_seed_mm),
            "--cae-mesh-quality",
            self.cae_mesh_quality,
            "--cae-rods-per-diameter",
            str(self.cae_rods_per_diameter),
            "--cae-element-type",
            self.cae_element_type,
            "--slug-mode",
            self.slug_mode,
            "--profile",
            self.profile,
            "--strain",
            str(self.strain),
            "--load-rate-mm-min",
            str(self.load_rate_mm_min),
            "--material-model",
            self.material_model,
        ]
        if self.cad_path.strip():
            argv.extend(["--cad", self.cad_path.strip()])
        if self.case_suffix.strip():
            argv.extend(["--case-suffix", self.case_suffix.strip()])
        if self.short_slug.strip():
            argv.extend(["--short-slug", self.short_slug.strip()])
        if self.cae_virtual_topology:
            argv.append("--cae-virtual-topology")
        if self.contact_store_offsets:
            argv.append("--contact-store-offsets")
        if self.contact_settle:
            argv.append("--contact-settle")
        if self.mesh_locally:
            argv.append("--mesh-locally")
        elif self.mesh_on_server:
            argv.append("--mesh-on-server")
        if self.remote_host.strip():
            argv.extend(["--remote-host", self.remote_host.strip()])
        if self.remote_root.strip():
            argv.extend(["--remote-root", self.remote_root.strip()])
        return argv

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["structure"] = self._normalized_structure()
        data["Q"] = self._effective_Q()
        data["variant_name"] = self.variant_name
        data["slug_preview"] = self.slug_preview()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HuBaiAbaqusSettings:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def list_presets() -> dict[str, dict[str, Any]]:
    return {
        "bcc_q0_baseline": HuBaiAbaqusSettings(
            Q=0.0,
            structure="bcc",
            case_suffix="cae_tet0p6mm80_5mmin_paperbox",
            cae_seed_mm=0.6,
            strain=0.80,
            load_rate_mm_min=5.0,
            material_model="neo_hooke",
            contact_store_offsets=True,
            contact_settle=True,
        ).to_dict(),
        "sfbls_q05_baseline": HuBaiAbaqusSettings(
            Q=0.5,
            structure="sfbls",
            case_suffix="cae_tet0p6mm80_5mmin_paperbox",
            cae_seed_mm=0.6,
            strain=0.80,
            load_rate_mm_min=5.0,
            material_model="neo_hooke",
            contact_store_offsets=True,
            contact_settle=True,
        ).to_dict(),
        "fast_test": HuBaiAbaqusSettings(
            Q=0.0,
            structure="bcc",
            profile="fast",
            strain=0.45,
            load_rate_mm_min=15.0,
            case_suffix="fast_test_ui",
            cae_seed_mm=1.2,
            material_model="elastic",
            contact_store_offsets=True,
            contact_settle=True,
            submit_cpus=8,
            submit_memory_mb=8192,
            mesh_on_server=True,
        ).to_dict(),
    }


def load_curve_csv(csv_path: Path) -> list[dict[str, float]]:
    import csv

    if not csv_path.is_file():
        return []
    rows: list[dict[str, float]] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append(
                    {
                        "engineering_strain": float(row["engineering_strain"]),
                        "engineering_stress_MPa": float(row["engineering_stress_MPa"]),
                    }
                )
            except (KeyError, ValueError):
                continue
    return rows
