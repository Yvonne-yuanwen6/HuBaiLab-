"""Pick best Fig.3.3 simulation per structure (BCC / Q0.5 / Q1 / Q1.5)."""

from __future__ import annotations

import csv
import math
from typing import Any

from src.paths import ABAQUS_POST
from src.postprocess.fig33_plot_style import load_fig33_reference, stress_at_strain

KEY_FROM_SLUG = (
    ("sfbls_af2q0p5_", "af2q05"),
    ("sfbls_af2q1p5_", "af2q15"),
    ("sfbls_af2q1_", "af2q1"),
    ("bcc_af2q0_", "bcc"),
)

STRUCTURE_ORDER = ("bcc", "af2q05", "af2q1", "af2q15")

# Hand-picked readable legend suffix
BEST_LABEL: dict[str, str] = {
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el": "fig33_v2_el",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_snap_s78_s0_08": "snap_s78_s0.08",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el": "fig33_v2_el_ocp444",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p": "paperbox_settle5p_ocp444",
    "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_q15_v2_el": "q15_v2_el",
}

# Curated overrides (bypass RMSE auto-pick for known best runs).
PINNED_BEST: dict[str, str] = {
    "af2q1": (
        "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el"
    ),
}


def series_key(slug: str) -> str | None:
    for pat, key in KEY_FROM_SLUG:
        if pat in slug:
            return key
    return None


def variant_label(slug: str) -> str:
    if slug in BEST_LABEL:
        return BEST_LABEL[slug]
    if "_paperbox_" in slug:
        return slug.split("_paperbox_", 1)[1]
    return slug.rsplit("_", 1)[-1]


def load_stress_strain(slug: str) -> list[tuple[float, float]] | None:
    path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
    if not path.is_file():
        return None
    pts: list[tuple[float, float]] = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pts.append((float(row["engineering_strain"]), float(row["engineering_stress_MPa"])))
    return pts if len(pts) >= 5 else None


def _interp(pts: list[tuple[float, float]], target: float) -> float | None:
    for i in range(1, len(pts)):
        e0, s0 = pts[i - 1]
        e1, s1 = pts[i]
        if e1 >= target:
            if e1 == e0:
                return s1
            return s0 + (s1 - s0) * (target - e0) / (e1 - e0)
    return None


def rmse_vs_fig33_ref(slug: str, key: str) -> float | None:
    ref = load_fig33_reference()
    strains = [i / 40 for i in range(1, 33)]
    pts = load_stress_strain(slug)
    if not pts:
        return None
    ref_pts = ref["series"][key]["points"]
    errs: list[float] = []
    for e in strains:
        rs = stress_at_strain(ref_pts, e)
        ss = _interp(pts, e)
        if rs is None or ss is None:
            continue
        errs.append((ss - rs) ** 2)
    if len(errs) < 10:
        return None
    return math.sqrt(sum(errs) / len(errs))


def _pinned_row(key: str, slug: str) -> dict[str, Any] | None:
    rmse = rmse_vs_fig33_ref(slug, key)
    if rmse is None:
        return None
    return {"slug": slug, "rmse": rmse, "label": variant_label(slug), "key": key}


def pick_best_per_structure(*, top_n: int = 1) -> dict[str, list[dict[str, Any]]]:
    ref = load_fig33_reference()
    strains = [i / 40 for i in range(1, 33)]
    candidates: dict[str, list[tuple[float, str]]] = {}

    if not ABAQUS_POST.is_dir():
        return {key: [] for key in STRUCTURE_ORDER}

    for d in sorted(ABAQUS_POST.iterdir()):
        if not d.is_dir():
            continue
        slug = d.name
        if "paperbox" not in slug and "fig33" not in slug:
            continue
        key = series_key(slug)
        if not key:
            continue
        pts = load_stress_strain(slug)
        if not pts:
            continue
        ref_pts = ref["series"][key]["points"]
        errs: list[float] = []
        for e in strains:
            rs = stress_at_strain(ref_pts, e)
            ss = _interp(pts, e)
            if rs is None or ss is None:
                continue
            errs.append((ss - rs) ** 2)
        if len(errs) < 10:
            continue
        rmse = math.sqrt(sum(errs) / len(errs))
        candidates.setdefault(key, []).append((rmse, slug))

    picked: dict[str, list[dict[str, Any]]] = {}
    for key in STRUCTURE_ORDER:
        if key in PINNED_BEST:
            row = _pinned_row(key, PINNED_BEST[key])
            if row:
                picked[key] = [row]
                continue
        rows = sorted(candidates.get(key, []))
        picked[key] = [
            {"slug": slug, "rmse": rmse, "label": variant_label(slug), "key": key}
            for rmse, slug in rows[:top_n]
        ]
    return picked


def load_best_curves() -> list[dict[str, Any]]:
    """Return one best case per structure with stress-strain arrays attached."""
    picked = pick_best_per_structure()
    ref = load_fig33_reference()
    out: list[dict[str, Any]] = []
    for key in STRUCTURE_ORDER:
        rows = picked.get(key) or []
        if not rows:
            continue
        row = rows[0]
        slug = row["slug"]
        pts = load_stress_strain(slug)
        if not pts:
            continue
        eps = [p[0] for p in pts]
        sig = [p[1] for p in pts]
        out.append(
            {
                **row,
                "series_label": ref["series"][key]["label"].replace("-实验", ""),
                "strains": eps,
                "stresses_MPa": sig,
                "csv": str(ABAQUS_POST / slug / f"{slug}_stress_strain.csv"),
            }
        )
    return out
