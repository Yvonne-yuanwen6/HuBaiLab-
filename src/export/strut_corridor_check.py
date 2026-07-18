"""Validate that fused unit-cell STEP still contains all 8 HuBai centre→corner struts."""

from __future__ import annotations

from typing import Any

from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_IN, TopAbs_ON
from OCP.gp import gp_Pnt

from src.generator.hu_bai_bcc import HuBaiLatticeGenerator


def _load_shape(path: str):
    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise RuntimeError(f"STEP read failed ({status}): {path}")
    reader.TransferRoots()
    return reader.OneShape()


def _unitcell_paths(
    *,
    cell_size_mm: float,
    rod_diameter_mm: float,
    amplitude_mm: float,
    period_factor: float,
    n_segments: int,
) -> list[list[tuple[float, float, float]]]:
    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size_mm),
        rod_diameter=float(rod_diameter_mm),
        amplitude=float(amplitude_mm),
        period_factor=float(period_factor),
        n_segments=max(3, int(n_segments)),
    )
    gen.build_unitcell()
    nodes, _beams, polylines = gen.get_data(copy=True)
    by_id = {int(n[0]): (float(n[1]), float(n[2]), float(n[3])) for n in nodes}
    paths: list[list[tuple[float, float, float]]] = []
    for poly in polylines:
        paths.append([by_id[int(nid)] for nid in poly["nodes"]])
    if len(paths) != 8:
        raise RuntimeError(f"expected 8 unit-cell polylines, got {len(paths)}")
    return paths


def _sample_path(
    pts: list[tuple[float, float, float]],
    *,
    n_per_seg: int = 3,
) -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    for a, b in zip(pts[:-1], pts[1:]):
        for k in range(n_per_seg):
            t = (k + 0.5) / n_per_seg
            out.append(
                (
                    a[0] + t * (b[0] - a[0]),
                    a[1] + t * (b[1] - a[1]),
                    a[2] + t * (b[2] - a[2]),
                )
            )
    return out


def _point_near_solid(clf: Any, x: float, y: float, z: float, tol: float) -> bool:
    clf.Perform(gp_Pnt(float(x), float(y), float(z)), 1e-4)
    if clf.State() in (TopAbs_IN, TopAbs_ON):
        return True
    for dx, dy, dz in (
        (tol, 0.0, 0.0),
        (-tol, 0.0, 0.0),
        (0.0, tol, 0.0),
        (0.0, -tol, 0.0),
        (0.0, 0.0, tol),
        (0.0, 0.0, -tol),
    ):
        clf.Perform(gp_Pnt(float(x + dx), float(y + dy), float(z + dz)), 1e-4)
        if clf.State() in (TopAbs_IN, TopAbs_ON):
            return True
    return False


def check_unitcell_strut_corridors(
    step_path: str,
    *,
    cell_size_mm: float = 20.0,
    rod_diameter_mm: float = 2.0,
    amplitude_mm: float = 2.0,
    period_factor: float = 1.0,
    n_segments: int = 24,
    tol_mm: float = 0.55,
    min_hit_fraction: float = 0.85,
) -> dict[str, Any]:
    """
    Sample each of the 8 design centreline polylines against the fused STEP.

    A strut is missing/broken when hit fraction < ``min_hit_fraction``.
    ``tol_mm`` allows the solid surface to sit slightly off the geometric centreline
    (ellipse sweep / Frenet offset).
    """
    shape = _load_shape(step_path)
    clf = BRepClass3d_SolidClassifier(shape)
    paths = _unitcell_paths(
        cell_size_mm=cell_size_mm,
        rod_diameter_mm=rod_diameter_mm,
        amplitude_mm=amplitude_mm,
        period_factor=period_factor,
        n_segments=n_segments,
    )
    strut_reports: list[dict[str, Any]] = []
    missing: list[int] = []
    for idx, pts in enumerate(paths):
        samples = _sample_path(pts, n_per_seg=3)
        hits = sum(
            1 for x, y, z in samples if _point_near_solid(clf, x, y, z, tol_mm)
        )
        frac = hits / len(samples) if samples else 0.0
        ok = frac >= float(min_hit_fraction)
        if not ok:
            missing.append(idx)
        strut_reports.append(
            {
                "strut_index": idx,
                "hits": hits,
                "samples": len(samples),
                "hit_fraction": frac,
                "ok": ok,
            }
        )
    return {
        "ok": not missing,
        "missing_strut_indices": missing,
        "struts": strut_reports,
        "step_path": step_path,
    }


def assert_unitcell_struts_present(
    step_path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    report = check_unitcell_strut_corridors(step_path, **kwargs)
    if not report["ok"]:
        miss = report["missing_strut_indices"]
        detail = ", ".join(
            f"#{s['strut_index']}={s['hit_fraction']:.2f}"
            for s in report["struts"]
            if not s["ok"]
        )
        raise RuntimeError(
            f"unit-cell STEP missing strut corridor(s) {miss} "
            f"({detail}): {step_path}"
        )
    return report
