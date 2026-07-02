"""
Export single-element uniaxial tension probes for TPU material-model screening.

Each model gets a tiny C3D8H cube INP (Abaqus fits hyperelastic forms from Fig.2.5
test data where applicable). Run on the server via scripts/linux/run_tpu_material_sweep.sh.

  py -3 scripts/export_tpu_uniaxial_material_probe.py
  py -3 scripts/export_tpu_uniaxial_material_probe.py --max-strain 0.8
"""
from __future__ import annotations

import argparse
import json
import sys
from io import StringIO
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.export.abaqus_compression import (
    HU_BAI_DENSITY_KG_M3,
    HU_BAI_E_MODULUS_MPA,
    HU_BAI_POISSON,
    hu_bai_density_abq,
    hu_bai_neo_hooke_c10,
)
from src.export.export_inp import _write_tpu_material
from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON, load_tpu_fig25_uniaxial
from src.paths import EXPORT_ROOT, PROJECT_ROOT

PROBE_PREFIX = "tpu_mat"
CUBE_MM = 10.0
DEFAULT_TPU_D1 = 8.0e-4

# (slug suffix, export_inp material_model, needs Fig.2.5 test data)
PROBE_MODELS: tuple[tuple[str, str, bool], ...] = (
    ("elastic", "elastic", False),
    ("neo_hooke", "hyperelastic", False),
    ("marlow", "marlow", True),
    ("polynomial", "polynomial", True),
    ("ogden_n2", "ogden_n2", True),
    ("reduced_poly_n2", "reduced_poly_n2", True),
)


def _probe_slug(model_suffix: str) -> str:
    return f"{PROBE_PREFIX}_{model_suffix}"


def _write_probe_inp(
    *,
    slug: str,
    material_model: str,
    max_strain: float,
    test_data: list[tuple[float, float]] | None,
    elastic_e: float,
    elastic_nu: float,
    c10: float,
    tpu_d1: float,
    density: float,
) -> str:
    h0 = CUBE_MM
    area = CUBE_MM * CUBE_MM
    u_max = float(max_strain) * h0
    buf = StringIO()
    buf.write(
        "*Heading\n"
        f"TPU uniaxial material probe ({material_model}) - single C3D8H cube\n"
        f"HuBaiLab slug={slug}; L0={h0} mm; target engineering strain={max_strain}\n"
        "*Node\n"
    )
    coords = [
        (0.0, 0.0, 0.0),
        (h0, 0.0, 0.0),
        (h0, h0, 0.0),
        (0.0, h0, 0.0),
        (0.0, 0.0, h0),
        (h0, 0.0, h0),
        (h0, h0, h0),
        (0.0, h0, h0),
    ]
    for i, (x, y, z) in enumerate(coords, start=1):
        buf.write(f"{i}, {x}, {y}, {z}\n")

    buf.write("*Element, type=C3D8H\n1, 1, 2, 3, 4, 5, 6, 7, 8\n")
    buf.write("*Elset, elset=SOLID\n1\n")
    buf.write("*Nset, nset=BOTTOM\n1, 2, 3, 4\n")
    buf.write("*Nset, nset=TOP\n5, 6, 7, 8\n")
    buf.write("*Nset, nset=TOP_REF\n5\n")

    mat_buf = StringIO()
    _write_tpu_material(
        mat_buf,
        material_name="TPU",
        density=density,
        material_model=material_model,
        elastic_e=elastic_e,
        elastic_nu=elastic_nu,
        plastic_yield=None,
        c10=c10,
        tpu_d1=tpu_d1,
        uniaxial_test_data=test_data,
    )
    buf.write("\n" + mat_buf.getvalue())
    buf.write("*Solid Section, elset=SOLID, material=TPU\n")
    buf.write("*Step, name=Tension, nlgeom=YES\n")
    buf.write("*Static\n0.05, 1.0, 1e-08, 0.2\n")
    buf.write("*Boundary\nBOTTOM, 1, 3\n")
    buf.write("*Boundary\nTOP, 1, 2\n")
    buf.write(f"*Boundary\nTOP, 3, 3, {u_max}\n")
    buf.write("*Output, field, frequency=20\n")
    buf.write("*Node Output\nU\n")
    buf.write("*Element Output, directions=YES\nS, E\n")
    buf.write("*Output, history, frequency=1\n")
    buf.write("*Node Output, nset=TOP_REF\nRF3, U3\n")
    buf.write("*End Step\n")
    return buf.getvalue()


def export_probe(
    model_suffix: str,
    material_model: str,
    *,
    needs_test_data: bool,
    test_data: list[tuple[float, float]],
    max_strain: float,
    elastic_e: float,
    elastic_nu: float,
    c10: float,
    tpu_d1: float,
    density: float,
) -> Path:
    slug = _probe_slug(model_suffix)
    out_dir = EXPORT_ROOT / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    td = test_data if needs_test_data else None
    text = _write_probe_inp(
        slug=slug,
        material_model=material_model,
        max_strain=max_strain,
        test_data=td,
        elastic_e=elastic_e,
        elastic_nu=elastic_nu,
        c10=c10,
        tpu_d1=tpu_d1,
        density=density,
    )
    inp = out_dir / f"{slug}.inp"
    inp.write_text(text, encoding="utf-8")
    meta = {
        "slug": slug,
        "material_model": material_model,
        "model_suffix": model_suffix,
        "probe_kind": "uniaxial_single_element",
        "L0_mm": CUBE_MM,
        "area_mm2": CUBE_MM * CUBE_MM,
        "max_engineering_strain": max_strain,
        "max_displacement_mm": max_strain * CUBE_MM,
        "fig25_json": str(DEFAULT_TPU_FIG25_JSON.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "n_test_points": len(test_data) if needs_test_data else 0,
    }
    (out_dir / f"{slug}_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return inp


def main() -> int:
    ap = argparse.ArgumentParser(description="Export TPU uniaxial material probe INPs.")
    ap.add_argument("--fig25-json", type=Path, default=DEFAULT_TPU_FIG25_JSON)
    ap.add_argument(
        "--max-strain",
        type=float,
        default=0.0,
        help="Target engineering strain (0 = use Fig.2.5 peak strain)",
    )
    ap.add_argument(
        "--models",
        nargs="*",
        default=[m[0] for m in PROBE_MODELS],
        help=f"Model suffixes to export (default: all). Choices: {[m[0] for m in PROBE_MODELS]}",
    )
    args = ap.parse_args()

    test_data = load_tpu_fig25_uniaxial(args.fig25_json)
    peak_strain = max(e for e, _ in test_data)
    max_strain = float(args.max_strain) if args.max_strain > 0 else peak_strain

    c10 = hu_bai_neo_hooke_c10(HU_BAI_E_MODULUS_MPA, HU_BAI_POISSON)
    density = hu_bai_density_abq(HU_BAI_DENSITY_KG_M3)
    by_suffix = {m[0]: (m[1], m[2]) for m in PROBE_MODELS}

    exported: list[str] = []
    for suffix in args.models:
        if suffix not in by_suffix:
            print(f"[WARN] unknown model suffix: {suffix}", file=sys.stderr)
            continue
        mat_model, needs_td = by_suffix[suffix]
        inp = export_probe(
            suffix,
            mat_model,
            needs_test_data=needs_td,
            test_data=test_data,
            max_strain=max_strain,
            elastic_e=HU_BAI_E_MODULUS_MPA,
            elastic_nu=HU_BAI_POISSON,
            c10=c10,
            tpu_d1=DEFAULT_TPU_D1,
            density=density,
        )
        exported.append(str(inp))
        print(f"Wrote {inp}")

    summary = {
        "max_engineering_strain": max_strain,
        "fig25_peak_strain": peak_strain,
        "models": args.models,
        "exported_inps": exported,
    }
    out_json = EXPORT_ROOT / PROBE_PREFIX / "probe_manifest.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest: {out_json}")
    return 0 if exported else 1


if __name__ == "__main__":
    raise SystemExit(main())
