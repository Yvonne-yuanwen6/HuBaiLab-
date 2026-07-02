#!/usr/bin/env python3
"""Heal a verified paper_box STEP for CAE mesh (merge sliver edges/faces)."""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.sw_parasolid import measure_step_occ_stats


def heal_step(
    in_step: str,
    out_step: str,
    *,
    distance_tol: float = 1e-5,
    fix_small: bool = False,
) -> dict:
    import gmsh

    in_step = os.path.abspath(in_step)
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step), exist_ok=True)

    before = measure_step_occ_stats(in_step)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add("heal")
        gmsh.model.occ.importShapes(in_step)
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise RuntimeError(f"no 3D volume in {in_step}")

        gmsh.model.occ.healShapes(
            tolerance=float(distance_tol),
            fixDegenerated=True,
            fixSmallEdges=bool(fix_small),
            fixSmallFaces=bool(fix_small),
            sewFaces=True,
            makeSolids=True,
        )
        gmsh.model.occ.synchronize()
        gmsh.model.occ.removeAllDuplicates()
        gmsh.model.occ.synchronize()

        n_vol = len(gmsh.model.getEntities(3))
        if n_vol != 1:
            raise RuntimeError(f"expected 1 volume after heal, got {n_vol}")

        gmsh.write(out_step)
    finally:
        gmsh.finalize()

    after = measure_step_occ_stats(out_step)
    return {"before": before, "after": after, "out_step": out_step}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("in_step")
    p.add_argument("out_step")
    p.add_argument("--distance-tol", type=float, default=1e-5)
    p.add_argument("--fix-small", action="store_true")
    args = p.parse_args()
    rep = heal_step(
        args.in_step,
        args.out_step,
        distance_tol=args.distance_tol,
        fix_small=args.fix_small,
    )
    print("before:", rep["before"])
    print("after:", rep["after"])
    print("OK:", rep["out_step"])


if __name__ == "__main__":
    main()
