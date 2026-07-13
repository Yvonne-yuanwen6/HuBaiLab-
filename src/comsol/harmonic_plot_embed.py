"""Default harmonic-resonance plot groups embedded in solved .mph (GUI-ready).

Standard output (Fig. 3.21 / Table 3.3 workflow):
- Top T(f) resonance peaks from transmissibility CSV (default n=3)
- Lattice-only surface selection
- Relative displacement vs pb_base (input-plane probe)
- AuroraBorealis colormap, auto deform scale, no dataset frame edges
- Metadata: {slug}_harmonic_plotgroups.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jpype
import numpy as np

from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.mph_builder import (
    LATTICE_GEOM,
    _ensure_comsol_env,
    _explicit_domain_selection,
    _import_mph,
)
from src.comsol.table33_compare import load_transmissibility_rows, pick_harmonic_top_three
from scripts.comsol_extract_isolation import _resolve_freq_dataset

HARMONIC_PLOT_FORMAT_VERSION = 2
REFERENCE_PROBE = "pb_base"
AVEOP_TABLE_TOP = "aveop_table_top"
SEL_LAT_BND = "_sel_plot_lat_bnd"
_TMP_DOM_LAT = "_sel_plot_d_lat"


@dataclass(frozen=True)
class HarmonicPlotDefaults:
    """Repository default for harmonic cloud plots in *_solved.mph."""

    n_peaks: int = 3
    colortable: str = "AuroraBorealis"
    color_max_mm: float | None = None  # None = auto range
    deform_scale: str = "auto"  # scaleactive=off
    show_dataset_edges: bool = False
    visible_geometry: str = "lattice only"
    peaks_from_csv: bool = True


DEFAULT_HARMONIC_PLOT = HarmonicPlotDefaults()


def harmonic_plotgroups_meta_path(job_dir: Path, slug: str) -> Path:
    return job_dir / f"{slug}_harmonic_plotgroups.json"


def peak_freqs_from_csv(csv_path: Path, *, n: int = DEFAULT_HARMONIC_PLOT.n_peaks) -> list[float]:
    rows = load_transmissibility_rows(csv_path)
    peaks, _ = pick_harmonic_top_three(rows)
    return [float(p["freq_hz"]) for p in peaks[:n] if p.get("freq_hz") is not None]


def load_settings_from_mph(mph_path: Path) -> HuBaiComsolSettings:
    manifest = mph_path.parent / "case_manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        sdict = data.get("settings", {})
        return HuBaiComsolSettings(
            **{k: v for k, v in sdict.items() if k in HuBaiComsolSettings.__dataclass_fields__}
        )
    return HuBaiComsolSettings(slug=mph_path.stem.replace("_solved", ""))


def harmonic_plotgroups_up_to_date(job_dir: Path, slug: str) -> bool:
    meta_path = harmonic_plotgroups_meta_path(job_dir, slug)
    if not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if meta.get("format_version") != HARMONIC_PLOT_FORMAT_VERSION:
        return False
    if meta.get("reference_probe") != REFERENCE_PROBE:
        return False
    return bool(meta.get("plot_groups"))


def _freq_to_solnum(freqs: np.ndarray, target_hz: float) -> tuple[int, float]:
    idx = int(np.argmin(np.abs(freqs - target_hz)))
    return idx + 1, float(freqs[idx])


def _try_set(obj: object, prop: str, val: object) -> bool:
    try:
        obj.set(prop, val)
        return True
    except Exception:
        return False


def _domain_from_material(comp: object, mat_tag: str, fallback: int) -> int:
    if mat_tag not in [str(t) for t in comp.material().tags()]:
        return fallback
    ents = comp.material(mat_tag).selection().entities()
    return int(ents[0]) if ents else fallback


def _remove_stale_aveop(comp: object) -> None:
    if AVEOP_TABLE_TOP in [str(t) for t in comp.cpl().tags()]:
        comp.cpl().remove(AVEOP_TABLE_TOP)
        print(f"  Removed stale {AVEOP_TABLE_TOP}", flush=True)


def _ensure_lattice_boundary_selection(
    comp: object,
    lat_id: int,
    *,
    geom_tag: str = LATTICE_GEOM,
) -> str:
    for tag in (SEL_LAT_BND, _TMP_DOM_LAT):
        if tag in [str(t) for t in comp.selection().tags()]:
            comp.selection().remove(tag)
    _explicit_domain_selection(comp, _TMP_DOM_LAT, lat_id, geom_tag=geom_tag)
    comp.selection().create(SEL_LAT_BND, "Adjacent")
    comp.selection(SEL_LAT_BND).set("input", [_TMP_DOM_LAT])
    n = len(comp.selection(SEL_LAT_BND).entities())
    print(f"  Plot selection: lattice dom {lat_id} only, {n} boundaries", flush=True)
    return SEL_LAT_BND


def _apply_harmonic_surface_plot(
    surf: object,
    *,
    bnd_sel: str,
    actual_f: float,
    disp_expr: str,
    defaults: HarmonicPlotDefaults,
) -> None:
    surf.set("expr", disp_expr)
    surf.set("unit", "mm")
    surf.set("resolution", "normal")
    surf.set("colortable", defaults.colortable)
    _try_set(surf, "coloring", "colortable")
    _try_set(surf, "wireframe", False)

    title = f"fn={actual_f:.1f} Hz  相对位移大小"
    _try_set(surf, "titletype", "custom")
    _try_set(surf, "customtitle", title)

    if defaults.color_max_mm is not None and defaults.color_max_mm > 0:
        surf.set("rangecoloractive", True)
        surf.set("rangecolormin", "0")
        surf.set("rangecolormax", f"{defaults.color_max_mm}[mm]")
    else:
        _try_set(surf, "rangecoloractive", False)

    for old in [str(t) for t in surf.feature().tags()]:
        try:
            surf.feature().remove(old)
        except Exception:
            pass
    sel = surf.create("sel1", "Selection")
    sel.selection().named(bnd_sel)

    deform = surf.create("def1", "Deform")
    deform.set("scaleactive", "off")


def embed_harmonic_plot_groups(
    mph_path: Path,
    settings: HuBaiComsolSettings,
    *,
    freq_hz: list[float],
    comsol_bin: str | None = None,
    defaults: HarmonicPlotDefaults | None = None,
) -> dict:
    """Write Fig. 3.21-style harmonic plot groups into solved .mph."""
    cfg = defaults or DEFAULT_HARMONIC_PLOT
    mph = _import_mph()
    _ensure_comsol_env(comsol_bin)
    path = mph_path.resolve()
    slug = settings.default_slug()
    job_dir = settings.job_dir()

    if not freq_hz:
        raise RuntimeError("no target frequencies for plot groups")

    disp_expr = settings.relative_displacement_magnitude_expr
    print(f"  Relative disp expr: {disp_expr}", flush=True)

    client = mph.start(cores=1)
    model = client.load(str(path))
    java = model.java
    comp = java.component("comp1")
    lat_id = _domain_from_material(comp, "mat_lattice", settings.domain_lattice)
    _remove_stale_aveop(comp)
    bnd_sel = _ensure_lattice_boundary_selection(comp, lat_id)

    freqs = np.array(model.evaluate("freq")).ravel()
    if freqs.size == 0:
        raise RuntimeError("no frequency solutions in mph")

    dataset = _resolve_freq_dataset(java, settings.study_freq_tag)
    result = java.result()
    embedded: list[dict] = []

    for rank, target in enumerate(freq_hz, start=1):
        solnum, actual_f = _freq_to_solnum(freqs, target)
        tag = f"pg_harm_f{int(round(actual_f))}"
        for old in [str(t) for t in result.tags()]:
            if old == tag or old.startswith(("pg_probe", "pg_rel", "pg_test", "pg_ok")):
                try:
                    result.remove(old)
                except Exception:
                    pass

        java.result().create(tag, jpype.JInt(3))
        pg = java.result(tag)
        pg.label(f"fn={actual_f:.1f} Hz  相对位移大小")
        pg.set("data", dataset)
        pg.set("solnum", str(solnum))
        _try_set(pg, "edges", cfg.show_dataset_edges)

        surf = pg.create("surf1", "Surface")
        _apply_harmonic_surface_plot(
            surf,
            bnd_sel=bnd_sel,
            actual_f=actual_f,
            disp_expr=disp_expr,
            defaults=cfg,
        )
        embedded.append(
            {
                "rank": rank,
                "plot_group": tag,
                "label": f"fn={actual_f:.1f} Hz  相对位移大小",
                "target_Hz": target,
                "actual_Hz": actual_f,
                "solnum": solnum,
                "expr": disp_expr,
                "reference": f"{REFERENCE_PROBE} probe on shaker table top",
                "lattice_domain": lat_id,
                "boundary_selection": bnd_sel,
                "deform_scale": cfg.deform_scale,
                "color_max_mm": cfg.color_max_mm,
            }
        )
        print(f"  Plot group: {tag} @ {actual_f:.1f} Hz (sol {solnum})", flush=True)

    model.save(str(path))
    print(f"  Saved plot groups → {path.name}", flush=True)

    meta = {
        "format_version": HARMONIC_PLOT_FORMAT_VERSION,
        "slug": slug,
        "mph": str(path),
        "dataset": dataset,
        "disp_expr": disp_expr,
        "reference_probe": REFERENCE_PROBE,
        "excitation_axis": settings.excitation_axis,
        "visible_geometry": cfg.visible_geometry,
        "colortable": cfg.colortable,
        "deform_scale": cfg.deform_scale,
        "color_max_mm": cfg.color_max_mm,
        "plot_groups": embedded,
        "gui_path": "结果 → 绘图组 → 表面1 → 选择1 + 变形1(自动) → 绘制",
    }
    meta_path = harmonic_plotgroups_meta_path(job_dir, slug)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    client.remove(model)
    return meta


def embed_harmonic_plot_groups_from_csv(
    mph_path: Path,
    settings: HuBaiComsolSettings | None = None,
    *,
    comsol_bin: str | None = None,
    defaults: HarmonicPlotDefaults | None = None,
    skip_if_current: bool = False,
) -> dict | None:
    """Embed default harmonic plots using T(f) peaks from transmissibility CSV."""
    path = mph_path.resolve()
    settings = settings or load_settings_from_mph(path)
    slug = settings.default_slug()
    job_dir = settings.job_dir()
    csv_path = job_dir / f"{slug}_transmissibility.csv"

    cfg = defaults or DEFAULT_HARMONIC_PLOT
    if skip_if_current and harmonic_plotgroups_up_to_date(job_dir, slug):
        print(f"  Harmonic plot groups up to date ({slug})", flush=True)
        return None

    if not csv_path.is_file():
        raise FileNotFoundError(f"missing transmissibility CSV: {csv_path}")

    freq_hz = peak_freqs_from_csv(csv_path, n=cfg.n_peaks)
    if not freq_hz:
        raise RuntimeError(f"no resonance peaks in {csv_path}")

    print(f"  Resonance peaks from CSV: {freq_hz}", flush=True)
    return embed_harmonic_plot_groups(
        path,
        settings,
        freq_hz=freq_hz,
        comsol_bin=comsol_bin,
        defaults=cfg,
    )
