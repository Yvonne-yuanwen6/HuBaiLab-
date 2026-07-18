"""
Unified attempt: generate 4×4×4 paper_box arrays for Q=0/0.5/1/1.5 via one method.

Pipeline per Q:
  1. Ensure 1-volume paper_box unit-cell seed
     (Q=1 prefers OCP glue pilot if present, else gmsh paper_box)
  2. OCP Glue layered array fuse (same backend for all Q)
  3. Validate STEP (vol=1, SolidWorks-safe)

  py -3 scripts/batch_paper_box_444_ocp_unified.py
  py -3 scripts/batch_paper_box_444_ocp_unified.py --Q 0 0.5 --force
  py -3 scripts/batch_paper_box_444_ocp_unified.py --skip-validate
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

from src.export.ocp_paper_box_array_fuse import (
    export_ocp_paper_box_layered_array_fuse,
    ocp_default_q1_seed_step,
    resolve_paper_box_seed,
)
from src.export.paper_box_array_fuse import _count_seed_volumes, paper_box_seed_step
from src.export.unitcell_box_cut import export_unitcell_step_paper_box_cut
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator, is_q1_period
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

DEFAULT_Q = (0.0, 0.5, 1.0, 1.5)


def _variant(q: float, *, l_mm: float = 20.0, rod_d: float = 2.0, af: float = 2.0) -> str:
    gen = HuBaiLatticeGenerator(
        cell_size=float(l_mm),
        rod_diameter=float(rod_d),
        amplitude=float(af),
        period_factor=float(q),
        n_segments=24,
    )
    gen.build_unitcell()
    return gen.variant_name.lower()


def ensure_unitcell_seed(q: float, *, force: bool = False) -> str:
    """Return absolute path to a 1-volume paper_box (or Q1 OCP) seed."""
    if is_q1_period(q):
        ocp = ocp_default_q1_seed_step()
        if force or not os.path.isfile(ocp):
            print(f"  Building Q=1 OCP glue seed -> {ocp}", flush=True)
            from src.export.export_sw import _collect_solid_primitives
            from src.export.ocp_unitcell_fuse import export_q1_ocp_glue_unitcell

            gen = HuBaiLatticeGenerator(
                cell_size=20.0,
                rod_diameter=2.0,
                amplitude=2.0,
                period_factor=1.0,
                n_segments=24,
            )
            gen.build_unitcell()
            nodes, beams, polylines = gen.get_data(copy=True)
            _, pipes_only = _collect_solid_primitives(
                nodes,
                beams,
                polylines=polylines,
                junction_spheres=False,
                trim_for_junctions=False,
                polyline_sweep="pipe",
            )
            pipe_parts = [p for p in pipes_only if p[0] == "pipe"]
            os.makedirs(os.path.dirname(ocp) or ".", exist_ok=True)
            export_q1_ocp_glue_unitcell(
                pipe_parts,
                ocp,
                cell_size_mm=20.0,
                strategy="sequential_glue_shift",
                fuzzy_mm=0.02,
            )
        vols = int(_count_seed_volumes(ocp))
        if vols == 1:
            return os.path.abspath(ocp)
        print(f"  [WARN] Q=1 OCP seed vols={vols}; falling back to gmsh paper_box", flush=True)

    seed = paper_box_seed_step(q)
    need = force or (not os.path.isfile(seed))
    if not need and os.path.isfile(seed):
        vols = int(_count_seed_volumes(seed))
        if vols != 1:
            need = True
            print(f"  [WARN] Q={q} seed vols={vols} (need 1); regenerating...", flush=True)

    if need and not is_q1_period(q):
        print(f"  Exporting paper_box unit cell Q={q} -> {seed}", flush=True)
        gen = HuBaiLatticeGenerator(
            cell_size=20.0,
            rod_diameter=2.0,
            amplitude=2.0,
            period_factor=float(q),
            n_segments=24,
        )
        gen.build_unitcell()
        nodes, beams, polylines = gen.get_data(copy=True)
        export_unitcell_step_paper_box_cut(
            nodes,
            beams,
            seed,
            polylines=polylines,
            cell_size_mm=20.0,
            period_factor=float(q),
        )
    elif need and is_q1_period(q) and not os.path.isfile(seed):
        print(f"  Exporting gmsh paper_box fallback Q={q} -> {seed}", flush=True)
        gen = HuBaiLatticeGenerator(
            cell_size=20.0,
            rod_diameter=2.0,
            amplitude=2.0,
            period_factor=float(q),
            n_segments=24,
        )
        gen.build_unitcell()
        nodes, beams, polylines = gen.get_data(copy=True)
        export_unitcell_step_paper_box_cut(
            nodes,
            beams,
            seed,
            polylines=polylines,
            cell_size_mm=20.0,
            period_factor=float(q),
        )

    if is_q1_period(q) and os.path.isfile(ocp_default_q1_seed_step()):
        return os.path.abspath(ocp_default_q1_seed_step())

    vols = int(_count_seed_volumes(seed))
    if vols != 1:
        raise RuntimeError(f"Q={q} seed is not 1-volume (vols={vols}): {seed}")
    return os.path.abspath(seed)


def run_one_q(
    q: float,
    *,
    force: bool = False,
    skip_validate: bool = False,
    ocp_fuse_mode: str = "auto",
) -> dict[str, Any]:
    t0 = time.time()
    variant = _variant(q)
    q_tag = str(q).replace(".", "p")
    out_dir = os.path.join(str(CAD_ROOT), f"_paper_box_array_q{q_tag}_ocp_unified")
    os.makedirs(out_dir, exist_ok=True)
    array_step = os.path.join(
        out_dir, f"hu_bai_{variant}_L20_4x4x4_paper_box_array.step"
    )

    mode = str(ocp_fuse_mode)
    if mode == "auto":
        # Q>=1: sequential is more robust for dense centre contacts (batch can empty).
        mode = "sequential" if float(q) >= 0.999 else "hierarchical_batch"

    print(f"\n======== Q={q} ({variant}) unified OCP 4x4x4 ========", flush=True)
    resolved = ensure_unitcell_seed(q, force=False)
    print(f"  seed: {resolved}", flush=True)
    print(f"  out:  {array_step}", flush=True)
    print(f"  ocp_fuse_mode: {mode}", flush=True)

    manifest = export_ocp_paper_box_layered_array_fuse(
        resolved,
        array_step,
        nx=4,
        ny=4,
        nz=4,
        cell_size=20.0,
        force=force,
        inter_cell_fuse_mode=mode,
    )

    entry: dict[str, Any] = {
        "Q": float(q),
        "variant": variant,
        "seed": resolved,
        "array_step": os.path.abspath(array_step),
        "out_dir": os.path.abspath(out_dir),
        "ocp_fuse_mode": mode,
        "elapsed_s": round(time.time() - t0, 1),
        "fuse_manifest": {
            k: manifest.get(k)
            for k in ("method", "glue", "fuzzy_mm", "array_merge")
            if k in manifest
        },
        "ok": os.path.isfile(array_step),
    }

    if not skip_validate and entry["ok"]:
        from src.export.sw_parasolid import analyze_step_for_solidworks

        report = analyze_step_for_solidworks(array_step, fused_single=True)
        vols = int(report.get("solid_count") or 0)
        safe = bool(report.get("solidworks_safe"))
        entry["validate"] = {
            "fused_volume_count": vols,
            "step_solidworks_safe": safe,
            "product_count": report.get("product_count"),
        }
        entry["ok"] = vols == 1 and safe
        print(
            f"  validate: vol={vols} sw_safe={safe} elapsed={entry['elapsed_s']}s",
            flush=True,
        )
    else:
        print(f"  done elapsed={entry['elapsed_s']}s ok={entry['ok']}", flush=True)

    return entry


def main() -> int:
    p = argparse.ArgumentParser(
        description="Unified OCP layered 4×4×4 for multiple Q (paper_box seeds)"
    )
    p.add_argument("--Q", type=float, nargs="*", default=list(DEFAULT_Q))
    p.add_argument("--force", action="store_true", help="Re-fuse even if outputs exist")
    p.add_argument("--skip-validate", action="store_true")
    p.add_argument(
        "--ocp-fuse-mode",
        default="auto",
        choices=("auto", "hierarchical_batch", "sequential"),
        help="auto: hierarchical_batch for Q<1, sequential for Q>=1",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Do not abort batch when one Q fails",
    )
    args = p.parse_args()

    results: list[dict[str, Any]] = []
    failed = 0
    for q in args.Q:
        try:
            entry = run_one_q(
                float(q),
                force=bool(args.force),
                skip_validate=bool(args.skip_validate),
                ocp_fuse_mode=str(args.ocp_fuse_mode),
            )
            results.append(entry)
            if not entry.get("ok"):
                failed += 1
                if not args.continue_on_error:
                    break
        except Exception as exc:
            failed += 1
            results.append({"Q": float(q), "ok": False, "error": str(exc)})
            print(f"  [FAIL] Q={q}: {exc}", flush=True)
            if not args.continue_on_error:
                break

    summary = {
        "method": "ocp_layered_unified",
        "Q_list": [float(q) for q in args.Q],
        "force": bool(args.force),
        "failed": failed,
        "results": results,
    }
    out_json = os.path.join(str(CAD_ROOT), "_paper_box_array_ocp_unified_batch.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nBatch summary: {out_json}", flush=True)
    print(f"failed={failed}/{len(results)}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
