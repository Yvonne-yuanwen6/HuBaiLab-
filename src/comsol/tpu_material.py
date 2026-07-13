"""Fig. 2.5 TPU tensile curve → COMSOL Marlow hyperelastic (§2.3.2 / §2.4.3)."""

from __future__ import annotations

from typing import Any

import jpype

from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON, load_tpu_fig25_uniaxial


def initial_tangent_modulus_mpa(
    points: list[tuple[float, float]],
    *,
    fallback_mpa: float,
) -> float:
    """Zero-strain tangent E for eigen linearization; default to paper/settings E."""
    _ = points
    return float(fallback_mpa)


def load_lattice_uniaxial_points(settings: HuBaiComsolSettings) -> list[tuple[float, float]]:
    """Return (engineering_strain, engineering_stress_MPa) from Fig. 2.5 traced data."""
    path = settings.tpu_tensile_curve_json or str(DEFAULT_TPU_FIG25_JSON)
    pts = load_tpu_fig25_uniaxial(path)
    max_eps = float(settings.tpu_tensile_max_strain)
    if max_eps > 0.0:
        pts = [(e, s) for e, s in pts if e <= max_eps + 1e-12]
    if len(pts) < 3:
        raise ValueError("TPU tensile curve needs >=3 points after filtering")
    return pts


def _java_string_matrix(rows: list[list[str]]) -> Any:
    string_array = jpype.JArray(jpype.JString)
    outer = string_array(len(rows))
    for i, row in enumerate(rows):
        inner = string_array(len(row))
        for j, val in enumerate(row):
            inner[j] = val
        outer[i] = inner
    return outer


def _add_uniaxial_interpolation(
    owner: Any,
    tag: str,
    points: list[tuple[float, float]],
    *,
    func_namespace: str = "tpu",
) -> Any:
    """Create Interpolation (stretch λ, nominal stress MPa) under a material property group."""
    funcs = owner.func()
    if tag in [str(t) for t in funcs.tags()]:
        funcs.remove(tag)
    fn = funcs.create(tag, "Interpolation")
    fn.set("funcname", f"{func_namespace}_uni")
    fn.set("source", "table")
    try:
        fn.set("interp", "piecewisecubic")
    except Exception:
        pass
    table = [[f"{1.0 + e:.8g}", f"{s:.8g}"] for e, s in points]
    try:
        fn.set("table", table)
    except Exception:
        fn.set("table", _java_string_matrix(table))
    for key, val in (("argunit", [""]), ("fununit", ["MPa"])):
        try:
            fn.set(key, val)
        except Exception:
            pass
    return fn


def assign_lattice_marlow_material(
    comp: Any,
    settings: HuBaiComsolSettings,
    domain: int,
    *,
    mat_tag: str = "mat_lattice",
) -> list[tuple[float, float]]:
    """Lattice material: density + HyperelasticModel Marlow from Fig. 2.5 uniaxial data."""
    points = load_lattice_uniaxial_points(settings)
    tags = [str(t) for t in comp.material().tags()]
    if mat_tag not in tags:
        comp.material().create(mat_tag, "Common")
    mat = comp.material(mat_tag)
    mat.selection().set(jpype.JArray(jpype.JInt)([int(domain)]))

    def_pg = mat.propertyGroup("def")
    def_pg.set("density", f"{settings.density_kg_m3}[kg/m^3]")

    pg_tags = [str(t) for t in mat.propertyGroup().tags()]
    if "HyperelasticModel" not in pg_tags:
        mat.propertyGroup().create("HyperelasticModel", "HyperelasticModel")
    he = mat.propertyGroup("HyperelasticModel")
    he.set("model", "Marlow")
    _add_uniaxial_interpolation(he, "uni1", points)

    nu = float(settings.poisson)
    e_tangent = initial_tangent_modulus_mpa(
        points, fallback_mpa=float(settings.youngs_modulus_mpa)
    )
    e_expr = "E_mpa"
    for pg in (def_pg, he):
        for key, val in (
            ("youngsmodulus", e_expr),
            ("poissonsratio", str(nu)),
        ):
            try:
                pg.set(key, val)
            except Exception:
                pass
    e_pa = e_tangent * 1e6
    mu = e_pa / (2.0 * (1.0 + nu))
    lam = e_pa * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    for pg in (def_pg, he):
        for key, val in (
            ("muLame", f"{mu}[Pa]"),
            ("lambLame", f"{lam}[Pa]"),
        ):
            try:
                pg.set(key, val)
            except Exception:
                pass

    print(
        f"  Lattice material: Marlow hyperelastic, Fig.2.5 uniaxial "
        f"({len(points)} pts, eps in [{points[0][0]:.4g}, {points[-1][0]:.4g}], "
        f"eigen tangent E≈{e_tangent:.2g} MPa, nu={nu}, rho={settings.density_kg_m3})",
        flush=True,
    )
    return points


def configure_lattice_eigen_linearized_physics(
    solid: Any,
    *,
    d_lat: int,
    d_tbl: int | None = None,
    d_plt: int | None = None,
    include_fixture: bool = True,
    youngs_mpa: float = 25.0,
    poisson: float = 0.47,
) -> None:
    """Marlow material + eigen: LE tangent at zero strain (COMSOL 5.6 eigen compat)."""
    lat_arr = jpype.JArray(jpype.JInt)([int(d_lat)])

    for tag in list(solid.feature().tags()):
        if str(tag) in ("free1", "init1"):
            continue  # COMSOL NOREMOVE defaults (free1, init1); leave as-is
        try:
            solid.feature().remove(str(tag))
        except Exception:
            continue

    if include_fixture and d_tbl is not None and d_plt is not None:
        fix_arr = jpype.JArray(jpype.JInt)([int(d_tbl), int(d_plt)])
        le = solid.create("lemm_fixture", "LinearElasticModel", jpype.JInt(3))
        le.selection().set(fix_arr)

    le = solid.create("lemm_lattice", "LinearElasticModel", jpype.JInt(3))
    le.selection().set(lat_arr)
    print(
        f"  Solid mechanics: LinearElasticModel on lattice domain {d_lat} "
        f"(Marlow mat; eigen linearization E={youngs_mpa} MPa, nu={poisson})",
        flush=True,
    )


def configure_lattice_hyperelastic_physics(
    solid: Any,
    *,
    d_lat: int,
    d_tbl: int | None = None,
    d_plt: int | None = None,
    include_fixture: bool = True,
    youngs_mpa: float = 25.0,
    poisson: float = 0.47,
) -> None:
    """Scope linear elastic to fixture; add HyperelasticModel on lattice domain."""
    lat_arr = jpype.JArray(jpype.JInt)([int(d_lat)])

    for tag in list(solid.feature().tags()):
        try:
            if "LinearElastic" in str(solid.feature(str(tag)).getType()):
                solid.feature().remove(str(tag))
        except Exception:
            continue

    if include_fixture and d_tbl is not None and d_plt is not None:
        fix_arr = jpype.JArray(jpype.JInt)([int(d_tbl), int(d_plt)])
        le = solid.create("lemm_fixture", "LinearElasticModel", jpype.JInt(3))
        le.selection().set(fix_arr)

    e_pa = float(youngs_mpa) * 1e6
    nu = float(poisson)
    mu = e_pa / (2.0 * (1.0 + nu))
    lam = e_pa * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))

    he_tag = "hemm1"
    if he_tag in [str(t) for t in solid.feature().tags()]:
        solid.feature().remove(he_tag)
    he = solid.create(he_tag, "HyperelasticModel", jpype.JInt(3))
    he.selection().set(lat_arr)
    # Eigen linearization needs infinitesimal Lamé moduli on the physics feature.
    lame_ok = False
    for etype in ("Lame", "Enu"):
        try:
            he.set("Etype", etype)
            if etype == "Lame":
                he.set("lambLame", f"{lam}[Pa]")
                he.set("muLame", f"{mu}[Pa]")
            else:
                he.set("E", f"{youngs_mpa}[MPa]")
                he.set("nu", str(nu))
            lame_ok = True
            break
        except Exception:
            continue
    if not lame_ok:
        for key, val in (
            ("Etype", "Enu"),
            ("E", "E_mpa"),
            ("nu", "nu"),
        ):
            try:
                he.set(key, val)
            except Exception:
                pass
    print(
        f"  Solid mechanics: HyperelasticModel on lattice domain {d_lat} "
        f"(eigen linearization E={youngs_mpa} MPa, nu={nu})",
        flush=True,
    )
