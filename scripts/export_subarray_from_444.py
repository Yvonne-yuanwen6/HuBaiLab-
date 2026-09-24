# -*- coding: utf-8 -*-
"""Crop NXxNYxNZ sub-arrays from verified 4x4x4 paper-box STEPs.

Source lattice is corner-anchored: cell centres at 0, L, 2L, 3L (L=20).
Crop keeps complete cells (i,j,k) with 0 ≤ i < nx, etc. - same Z rule as
``export_isolator_from_444`` (do not centre-slab through half layers).

Outputs:
  output/cad/test/{nx}{ny}{nz}/{case_id}_{nx}{ny}{nz}.step

  py -3 scripts/export_subarray_from_444.py
  py -3 scripts/export_subarray_from_444.py --only 442 --cases af2q0_deq2_k1
  FORCE=1 py -3 scripts/export_subarray_from_444.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import (
    _box_from_bounds,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)
from src.export.sw_parasolid import (
    count_step_products,
    count_step_solids,
    flatten_step_assembly_to_single_product,
)
from src.paths import CAD_ROOT, CAD_VERIFIED_ROOT, ensure_output_dirs

ensure_output_dirs()

L_MM = 20.0
SRC_NX = SRC_NY = SRC_NZ = 4

CASES = (
    "af2q0_deq2_k1",
    "af2q0p5_deq2_k1",
    "af2q1_deq2_k1",
    "af2q1p5_deq2_k1",
)

SIZES = (
    (3, 3, 2),
    (3, 3, 3),
    (4, 4, 2),
    (4, 4, 3),
)

# Mass ratio vs full 444 within this relative tolerance.
MASS_TOL_REL = 0.05


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _size_tag(nx: int, ny: int, nz: int) -> str:
    return f"{int(nx)}{int(ny)}{int(nz)}"


def _bbox_mm(shape) -> dict[str, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {
        "xmin": float(xmin),
        "xmax": float(xmax),
        "ymin": float(ymin),
        "ymax": float(ymax),
        "zmin": float(zmin),
        "zmax": float(zmax),
        "dx": float(xmax - xmin),
        "dy": float(ymax - ymin),
        "dz": float(zmax - zmin),
        "cx": 0.5 * float(xmin + xmax),
        "cy": 0.5 * float(ymin + ymax),
        "cz": 0.5 * float(zmin + zmax),
    }


def _read_array_shape(path: str):
    try:
        return ocp_read_step_shape(path)
    except RuntimeError as exc:
        print(f"  [WARN] strict 1-solid read failed ({exc}); OneShape fallback", flush=True)
        from OCP.STEPControl import STEPControl_Reader

        reader = STEPControl_Reader()
        if reader.ReadFile(os.path.abspath(path)) != 1:
            raise RuntimeError(f"OCP STEP read failed: {path}") from exc
        reader.TransferRoots()
        return reader.OneShape()


def _common_fuzzy(a, b, *, fuzzy_mm: float, label: str):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    op = BRepAlgoAPI_Common(a, b)
    if fuzzy_mm > 0.0:
        op.SetFuzzyValue(float(fuzzy_mm))
    op.Build()
    if not op.IsDone():
        raise RuntimeError(f"{label}: Common not done (fuzzy={fuzzy_mm:g})")
    shape = op.Shape()
    if ocp_mass(shape) <= 0.0:
        raise RuntimeError(f"{label}: Common empty (fuzzy={fuzzy_mm:g})")
    return shape


def _subarray_prism(nx: int, ny: int, nz: int, *, L_mm: float, pad_mm: float = 0.0):
    """AABB covering complete cells [0..nx)x[0..ny)x[0..nz) (paper-box aligned)."""
    L = float(L_mm)
    pad = float(pad_mm)
    half = 0.5 * L
    return _box_from_bounds(
        (
            -half - pad,
            float(nx) * L - half + pad,
            -half - pad,
            float(ny) * L - half + pad,
            -half - pad,
            float(nz) * L - half + pad,
        )
    )


def _flatten_step_one_sw_window(path: str) -> dict:
    n_p = count_step_products(path)
    n_s = count_step_solids(path)
    if n_p <= 1:
        print(f"  SW one-window OK PRODUCT={n_p} solids={n_s}", flush=True)
        return {
            "step_path": os.path.abspath(path),
            "product_count": n_p,
            "solid_count": n_s,
            "solidworks_safe": True,
            "flattened": False,
        }
    print(f"  flatten for 1 SW window: PRODUCT={n_p} solids={n_s} ...", flush=True)
    report = flatten_step_assembly_to_single_product(path)
    print(
        f"  after flatten PRODUCT={report.get('product_count')} "
        f"solids={report.get('solid_count')} safe={report.get('solidworks_safe')}",
        flush=True,
    )
    if int(report.get("product_count") or 0) != 1:
        raise RuntimeError(
            f"STEP still has {report.get('product_count')} PRODUCTs: {path}"
        )
    return report


def _write_step_one_sw_window(shape, path: str) -> dict:
    ocp_write_step(shape, path)
    return _flatten_step_one_sw_window(path)


def _clip_subarray(array, *, nx: int, ny: int, nz: int, L_mm: float):
    last_exc: Exception | None = None
    for pad in (0.0, 0.05, 0.2):
        prism = _subarray_prism(nx, ny, nz, L_mm=L_mm, pad_mm=pad)
        for fuzzy in (0.0, 0.02, 0.05, 0.1):
            label = f"subarray-{nx}{ny}{nz}-pad{pad:g}-fuzzy{fuzzy:g}"
            try:
                clipped = _common_fuzzy(array, prism, fuzzy_mm=fuzzy, label=label)
                print(
                    f"  Common pad={pad:g} fuzzy={fuzzy:g} "
                    f"mass={ocp_mass(clipped):.1f} mm3",
                    flush=True,
                )
                return clipped, {"pad_mm": pad, "fuzzy_mm": fuzzy}
            except RuntimeError as exc:
                last_exc = exc
                print(f"  [WARN] {label} failed ({exc})", flush=True)
    raise RuntimeError(f"subarray clip failed ({last_exc})") from last_exc


def crop_one(
    case_id: str,
    nx: int,
    ny: int,
    nz: int,
    *,
    L_mm: float = L_MM,
    force: bool = False,
    mass_444: float | None = None,
) -> dict[str, Any]:
    tag = _size_tag(nx, ny, nz)
    out_dir = os.path.join(str(CAD_ROOT), "test", tag)
    os.makedirs(out_dir, exist_ok=True)
    out_step = os.path.join(out_dir, f"{case_id}_{tag}.step")
    out_json = os.path.join(out_dir, f"{case_id}_{tag}_qc.json")

    src = os.path.join(str(CAD_VERIFIED_ROOT), f"batch_{case_id}_paper_box_array.step")
    if not os.path.isfile(src):
        raise FileNotFoundError(src)

    if (
        not force
        and os.path.isfile(out_step)
        and os.path.getsize(out_step) > 10_000
        and os.path.isfile(out_json)
    ):
        print(f"\n=== skip existing {case_id} {tag} ===", flush=True)
        sw = _flatten_step_one_sw_window(out_step)
        with open(out_json, encoding="utf-8") as f:
            prev = json.load(f)
        prev["skipped"] = True
        prev["sw_product_count"] = sw.get("product_count")
        return prev

    t0 = time.perf_counter()
    print(f"\n=== {case_id} -> {tag} ({nx}x{ny}x{nz}) ===", flush=True)
    print(f"  source {src} ({os.path.getsize(src) / 1e6:.2f} MB)", flush=True)

    array = _read_array_shape(src)
    topo0 = ocp_shape_topology(array, count_faces=False, check_brep=False)
    bb0 = _bbox_mm(array)
    m0 = float(mass_444 if mass_444 is not None else (topo0.get("mass_mm3") or ocp_mass(array)))
    print(
        f"  444 solids={topo0.get('solids')} mass={m0:.1f} "
        f"bbox dx={bb0['dx']:.2f} dy={bb0['dy']:.2f} dz={bb0['dz']:.2f} "
        f"c=({bb0['cx']:.1f},{bb0['cy']:.1f},{bb0['cz']:.1f})",
        flush=True,
    )

    n_cells = int(nx) * int(ny) * int(nz)
    n_src = SRC_NX * SRC_NY * SRC_NZ
    expect_mass = m0 * (n_cells / float(n_src))

    clipped, clip_meta = _clip_subarray(array, nx=nx, ny=ny, nz=nz, L_mm=L_mm)
    topo = ocp_shape_topology(clipped, count_faces=True, check_brep=True)
    mass = float(topo.get("mass_mm3") or 0.0)
    bb = _bbox_mm(clipped)
    ratio = (mass / m0) if m0 > 0.0 else 0.0
    expect_ratio = n_cells / float(n_src)
    rel_err = abs(ratio - expect_ratio) / expect_ratio if expect_ratio > 0 else 1.0
    ok = mass > 0.0 and rel_err <= MASS_TOL_REL and int(topo.get("solids") or 0) >= 1

    print(
        f"  clipped solids={topo.get('solids')} mass={mass:.1f} "
        f"(expect≈{expect_mass:.1f}, ratio={ratio:.4f} vs {expect_ratio:.4f}, "
        f"rel_err={rel_err:.3%}) faces={topo.get('faces')} brep={topo.get('brep_valid')}",
        flush=True,
    )
    print(
        f"  bbox dx={bb['dx']:.2f} dy={bb['dy']:.2f} dz={bb['dz']:.2f} "
        f"z=[{bb['zmin']:.2f},{bb['zmax']:.2f}]",
        flush=True,
    )
    if not ok:
        raise RuntimeError(
            f"{case_id}/{tag}: mass check failed "
            f"(mass={mass:.1f} expect≈{expect_mass:.1f} rel_err={rel_err:.3%})"
        )

    sw = _write_step_one_sw_window(clipped, out_step)
    report = {
        "case_id": case_id,
        "tag": tag,
        "nx": int(nx),
        "ny": int(ny),
        "nz": int(nz),
        "L_mm": float(L_mm),
        "n_cells": n_cells,
        "source_444": os.path.abspath(src),
        "source_topo": topo0,
        "source_bbox_mm": bb0,
        "source_mass_mm3": m0,
        "clip": clip_meta,
        "step_path": os.path.abspath(out_step),
        "topo": topo,
        "bbox_mm": bb,
        "mass_mm3": mass,
        "expect_mass_mm3": expect_mass,
        "mass_ratio_vs_444": ratio,
        "expect_ratio": expect_ratio,
        "mass_rel_err": rel_err,
        "sw": sw,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "ok": ok,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  wrote {out_step} ({os.path.getsize(out_step) / 1e6:.2f} MB) in {report['elapsed_s']} s", flush=True)
    return report


def _parse_size(token: str) -> tuple[int, int, int]:
    t = token.strip()
    if len(t) == 3 and t.isdigit():
        return int(t[0]), int(t[1]), int(t[2])
    parts = t.lower().replace("x", " ").split()
    if len(parts) == 3:
        return int(parts[0]), int(parts[1]), int(parts[2])
    raise argparse.ArgumentTypeError(f"bad size {token!r}; use 332 or 3x3x2")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Size tags to run (e.g. 332 442). Default: all four.",
    )
    ap.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Case ids (default: af2 + four Q + deq2 + k1).",
    )
    ap.add_argument("--force", action="store_true", help="Overwrite existing STEPs.")
    ap.add_argument("--L", type=float, default=L_MM, help="Cell size mm (default 20).")
    args = ap.parse_args(argv)

    force = bool(args.force) or _env_flag("FORCE")
    cases = tuple(args.cases) if args.cases else CASES
    if args.only:
        sizes = [_parse_size(t) for t in args.only]
    else:
        sizes = list(SIZES)

    print(
        f"crop subarrays from verified 444 -> {CAD_ROOT / 'test'}\n"
        f"  cases={list(cases)}\n"
        f"  sizes={[ _size_tag(*s) for s in sizes ]}\n"
        f"  force={force}",
        flush=True,
    )

    # Cache 444 mass per case so we do not re-measure after first size.
    mass_cache: dict[str, float] = {}
    reports: list[dict[str, Any]] = []
    failed: list[str] = []

    for case_id in cases:
        for nx, ny, nz in sizes:
            key = f"{case_id}/{_size_tag(nx, ny, nz)}"
            try:
                rep = crop_one(
                    case_id,
                    nx,
                    ny,
                    nz,
                    L_mm=float(args.L),
                    force=force,
                    mass_444=mass_cache.get(case_id),
                )
                if "source_mass_mm3" in rep:
                    mass_cache[case_id] = float(rep["source_mass_mm3"])
                reports.append(rep)
                if not rep.get("ok", True):
                    failed.append(key)
            except Exception as exc:
                print(f"  [FAIL] {key}: {exc}", flush=True)
                failed.append(key)
                reports.append(
                    {
                        "case_id": case_id,
                        "tag": _size_tag(nx, ny, nz),
                        "ok": False,
                        "error": str(exc),
                    }
                )

    summary_path = os.path.join(str(CAD_ROOT), "test", "_subarray_from_444_summary.json")
    summary = {
        "cases": list(cases),
        "sizes": [_size_tag(*s) for s in sizes],
        "n_ok": sum(1 for r in reports if r.get("ok")),
        "n_fail": len(failed),
        "failed": failed,
        "reports": reports,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(
        f"\n=== done ok={summary['n_ok']} fail={summary['n_fail']} "
        f"summary={summary_path} ===",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
