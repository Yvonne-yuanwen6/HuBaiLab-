"""
Retry inter-slab merge for elliptic paper_box 4x4x4 (existing z-slabs).

Phases:
1) OCP ladder 2+2 merge (glue/fuzzy sweep)
2) OCP flat 4-slab merge (remaining combos)
3) Gmsh in-memory merge (direct + ladder)

  py -3 scripts/retry_ellipse_ellmin_ocp_interslab.py --Q 1.5
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import _merge_step_solids_in_memory
from src.export.ocp_paper_box_array_fuse import (
    export_ocp_paper_box_array_from_zslabs,
    export_ocp_paper_box_array_ladder_from_zslabs,
)
from src.export.ocp_unitcell_fuse import GlueMode
from src.export.paper_box_array_fuse import _count_seed_volumes
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def _array_paths(q: float, *, n: int = 4) -> tuple[str, str, list[str]]:
    tag = str(q).replace(".", "p")
    out_dir = os.path.join(str(CAD_ROOT), f"_paper_box_array_ellipse_eqarea_q{tag}")
    gen = HuBaiLatticeGenerator(
        cell_size=20.0,
        rod_diameter=2.582,
        amplitude=2.0,
        period_factor=float(q),
        n_segments=24,
    )
    gen.build_unitcell()
    slug = f"hu_bai_{gen.variant_name.lower()}_L20_{n}x{n}x{n}"
    zslabs = [
        os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_paper_box_fused.step")
        for iz in range(n)
    ]
    array_step = os.path.join(
        out_dir, f"{slug}_paper_box_ellipse_eqarea_ellmin_array.step"
    )
    return out_dir, array_step, zslabs


def _commit_ok(tmp_step: str, array_step: str, label: str, mass: float | None) -> int:
    vols = int(_count_seed_volumes(tmp_step))
    if vols != 1:
        raise RuntimeError(f"expected 1 volume, got {vols}")
    if os.path.isfile(array_step):
        os.remove(array_step)
    os.replace(tmp_step, array_step)
    print(f"  OK [{label}]: {array_step} vol=1 mass={mass}", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Inter-slab retry for ellipse 444")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--zslab-dir", default="")
    p.add_argument("--cells", type=int, default=4)
    args = p.parse_args()

    q = float(args.Q)
    n = int(args.cells)
    if args.zslab_dir.strip():
        out_dir = os.path.abspath(args.zslab_dir.strip())
        _, array_step, _ = _array_paths(q, n=n)
        zslabs = sorted(
            os.path.join(out_dir, f)
            for f in os.listdir(out_dir)
            if f.startswith("zslab_iz") and f.endswith("_paper_box_fused.step")
        )
        array_step = os.path.join(out_dir, os.path.basename(array_step))
    else:
        out_dir, array_step, zslabs = _array_paths(q, n=n)

    missing = [pth for pth in zslabs if not os.path.isfile(pth)]
    if missing:
        raise SystemExit("Missing z-slab STEP(s):\n  " + "\n  ".join(missing))

    print(f"Q={q} z-slabs ({len(zslabs)}):", flush=True)
    for pth in zslabs:
        print(f"  {pth} ({os.path.getsize(pth) // 1024 // 1024} MB)", flush=True)
    print(f"Target array: {array_step}", flush=True)

    glues: tuple[GlueMode, ...] = ("full", "shift")
    fuzzies = (0.05, 0.1, 0.02)
    errors: list[str] = []

    for glue in glues:
        for fuzzy in fuzzies:
            label = f"ladder_{glue}_f{fuzzy:g}"
            tmp_step = array_step + f".try_{label}.step"
            if os.path.isfile(tmp_step):
                os.remove(tmp_step)
            print(f"\n=== OCP ladder try: {label} ===", flush=True)
            try:
                report = export_ocp_paper_box_array_ladder_from_zslabs(
                    zslabs,
                    tmp_step,
                    glue=glue,
                    fuzzy_mm=float(fuzzy),
                    progress_label=f"ocp-ellmin-{label}",
                    skip_gmsh_heal=True,
                )
                return _commit_ok(tmp_step, array_step, label, report.get("merged_mass_mm3"))
            except Exception as exc:
                msg = f"{label}: {exc}"
                print(f"  FAIL {msg}", flush=True)
                errors.append(msg)
                if os.path.isfile(tmp_step):
                    try:
                        os.remove(tmp_step)
                    except OSError:
                        pass

    for fuse_mode in ("sequential",):
        for glue in glues:
            for fuzzy in fuzzies:
                label = f"flat_{fuse_mode}_{glue}_f{fuzzy:g}"
                tmp_step = array_step + f".try_{label}.step"
                if os.path.isfile(tmp_step):
                    os.remove(tmp_step)
                print(f"\n=== OCP flat try: {label} ===", flush=True)
                try:
                    report = export_ocp_paper_box_array_from_zslabs(
                        zslabs,
                        tmp_step,
                        glue=glue,
                        fuzzy_mm=float(fuzzy),
                        fuse_mode=fuse_mode,
                        progress_label=f"ocp-ellmin-{label}",
                        skip_gmsh_heal=True,
                    )
                    return _commit_ok(tmp_step, array_step, label, report.get("merged_mass_mm3"))
                except Exception as exc:
                    msg = f"{label}: {exc}"
                    print(f"  FAIL {msg}", flush=True)
                    errors.append(msg)
                    if os.path.isfile(tmp_step):
                        try:
                            os.remove(tmp_step)
                        except OSError:
                            pass

    gmsh_attempts: list[tuple[str, list[str]]] = [
        ("gmsh_flat_4", list(zslabs)),
    ]
    if len(zslabs) == 4:
        half01 = os.path.join(out_dir, "_tmp_ladder_half01.step")
        half23 = os.path.join(out_dir, "_tmp_ladder_half23.step")
        for path in (half01, half23):
            if os.path.isfile(path):
                os.remove(path)
        try:
            print("\n=== Gmsh ladder: half01 ===", flush=True)
            _merge_step_solids_in_memory(zslabs[0:2], half01, progress_label="gmsh-ladder-01")
            print("=== Gmsh ladder: half23 ===", flush=True)
            _merge_step_solids_in_memory(zslabs[2:4], half23, progress_label="gmsh-ladder-23")
            gmsh_attempts.append(("gmsh_ladder_2x2", [half01, half23]))
        except Exception as exc:
            errors.append(f"gmsh_ladder_halves: {exc}")
            print(f"  FAIL gmsh ladder halves: {exc}", flush=True)

    for label, inputs in gmsh_attempts:
        tmp_step = array_step + f".try_{label}.step"
        if os.path.isfile(tmp_step):
            os.remove(tmp_step)
        print(f"\n=== {label} try ===", flush=True)
        try:
            report = _merge_step_solids_in_memory(
                inputs, tmp_step, progress_label=f"ocp-ellmin-{label}"
            )
            if int(report.get("solid_count") or 0) != 1:
                raise RuntimeError(f"gmsh merge produced {report.get('solid_count')} solids")
            return _commit_ok(tmp_step, array_step, label, None)
        except Exception as exc:
            msg = f"{label}: {exc}"
            print(f"  FAIL {msg}", flush=True)
            errors.append(msg)
            if os.path.isfile(tmp_step):
                try:
                    os.remove(tmp_step)
                except OSError:
                    pass

    raise SystemExit("All inter-slab attempts failed:\n  " + "\n  ".join(errors))


if __name__ == "__main__":
    raise SystemExit(main())
