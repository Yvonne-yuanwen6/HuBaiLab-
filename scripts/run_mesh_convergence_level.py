"""Run one Q0.5 mesh-convergence level (export and/or submit via paperbox variant)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.mesh.mesh_convergence import Q05_MESH_CONVERGENCE_LEVELS, slug_for_q05_level


def _level_by_id(level_id: str) -> dict:
    for lv in Q05_MESH_CONVERGENCE_LEVELS:
        if lv["id"] == level_id:
            return lv
    raise SystemExit(f"unknown level id: {level_id!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", required=True, help="Level id from mesh_convergence.py")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--submit-only", action="store_true")
    parser.add_argument("--cpus", type=int, default=48)
    parser.add_argument("--memory-mb", type=int, default=262144)
    args = parser.parse_args()

    lv = _level_by_id(args.level)
    variant_sh = os.path.join(_ROOT, "scripts", "linux", "run_paperbox_variant.sh")
    if not os.path.isfile(variant_sh):
        print(f"[ERROR] missing {variant_sh} (run on Linux server)")
        return 1

    common = [
        "--contact-store-offsets",
        "--material-model",
        "elastic",
        "--strain",
        "0.80",
        "--load-rate-mm-min",
        "5",
        "--explicit-dt",
        "0.0005",
        "--explicit-dt-mode",
        "automatic",
        "--cae-seed",
        str(lv["cae_seed_mm"]),
    ]

    def run_variant(extra: list[str]) -> int:
        cmd = [
            "bash",
            variant_sh,
            "--Q",
            "0.5",
            "--variant-suffix",
            lv["variant_suffix"],
            "--force-remesh",
            "--cae-mesh-quality",
            lv["cae_mesh_quality"],
            "--cae-rods-per-diameter",
            str(lv["cae_rods_per_diameter"]),
            "--cpus",
            str(args.cpus),
            "--memory-mb",
            str(args.memory_mb),
            *extra,
            *common,
        ]
        print("RUN:", " ".join(cmd))
        return subprocess.call(cmd, cwd=_ROOT)

    rc = 0
    if args.submit_only:
        rc = run_variant(["--submit-only"])
    elif args.export_only:
        rc = run_variant(["--export-only"])
    else:
        rc = run_variant(["--export-only"])
        if rc == 0:
            rc = run_variant(["--submit-only"])

    slug = slug_for_q05_level(lv)
    print(f"slug={slug} rc={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
