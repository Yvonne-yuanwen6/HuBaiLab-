"""Short slugs for Hu & Bai paper_box CAE tet compression cases."""

from __future__ import annotations


def _fmt_num(value: float) -> str:
    v = float(value)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    scaled = round(v * 10)
    if abs(v * 10 - scaled) < 1e-9:
        if v < 1:
            return f"{int(scaled):02d}"
        return str(int(scaled))
    return f"{v:g}".replace(".", "p")


def q_token(period_factor: float) -> str:
    """Q0 -> q0, Q0.5 -> q05, Q1 -> q1, Q1.5 -> q15."""
    return f"q{_fmt_num(float(period_factor))}"


def mesh_token(
    *,
    element_type: str = "C3D4",
    seed_mm: float = 0.6,
    rods_per_diameter: float = 3.0,
) -> str:
    """
    Mesh descriptor for short slugs.

    Examples:
      C3D10M seed 0.5 r4 -> c10m_s05r4
      C3D4 seed 0.6 r3   -> c04_s06r3
    """
    et = element_type.upper()
    if et == "C3D10M":
        elem = "c10m"
    elif et == "C3D10":
        elem = "c10"
    elif et in ("C3D4", "C3D4R"):
        elem = "c04"
    elif et in ("C3D8R", "C3D8"):
        elem = "c8r"
    else:
        elem = et.lower()

    seed = f"s{_fmt_num(seed_mm)}"
    rods = f"r{_fmt_num(rods_per_diameter)}"
    return f"{elem}_{seed}{rods}"


def mat_token(material_model: str) -> str:
    kind = material_model.lower()
    if kind in ("elastic", "elastic_plastic"):
        return "el"
    if kind == "marlow":
        return "marlow"
    if kind == "polynomial":
        return "poly"
    if kind in ("paper", "hyperelastic"):
        return "nh"
    return kind[:8]


def strain_token(target_strain: float) -> str:
    pct = int(round(float(target_strain) * 100.0))
    return f"s{pct}"


def build_paperbox_short_slug(
    *,
    period_factor: float,
    element_type: str = "C3D4",
    seed_mm: float = 0.6,
    rods_per_diameter: float = 3.0,
    material_model: str = "elastic",
    target_strain: float = 0.80,
    contact_settle: bool = False,
    extra: str = "",
) -> str:
    """
    Build a compact case slug (also used as Abaqus job name).

    Example: q05_c10m_s05r4_el_s78
    """
    parts = [
        q_token(period_factor),
        mesh_token(
            element_type=element_type,
            seed_mm=seed_mm,
            rods_per_diameter=rods_per_diameter,
        ),
        mat_token(material_model),
        strain_token(target_strain),
    ]
    if contact_settle:
        parts.insert(-1, "settle5p")
    if extra:
        parts.append(extra.strip("_"))
    return "_".join(p for p in parts if p)


def paperbox_slug_descriptor(
    *,
    short_slug: str,
    period_factor: float,
    element_type: str,
    seed_mm: float,
    rods_per_diameter: float,
    mesh_quality: str,
    material_model: str,
    target_strain: float,
    variant_name: str,
    cad_step: str,
) -> dict:
    """Full traceability fields stored alongside a short slug."""
    return {
        "short_slug": short_slug,
        "period_factor": float(period_factor),
        "variant_name": variant_name,
        "element_type": element_type,
        "cae_seed_mm": float(seed_mm),
        "cae_rods_per_diameter": float(rods_per_diameter),
        "cae_mesh_quality": mesh_quality,
        "material_model": material_model,
        "target_engineering_strain": float(target_strain),
        "cad_step": cad_step,
    }
