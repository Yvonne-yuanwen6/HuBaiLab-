# -*- coding: utf-8 -*-
"""Export compression INPs for test subarrays (332/333/442/443) from existing CAE meshes.

Protocol matches L=20 batch (BATCH_SIM_MESH_PROTOCOL=1 export_from_mesh args),
but passes --nx/--ny/--nz so stroke = strain * nz * L.

Requires mesh:
  output/export/test/{size}/{case}/cae_tet0p6mm80_5mmin_paperbox/*_cae_mesh.inp
STEP (cad metadata):
  output/cad/test/{size}/{case}_{size}.step

  py -3 scripts/run_test_subarray_cae_export.py
  py -3 scripts/run_test_subarray_cae_export.py --only-size 332 --only-case af2q0_deq2_k1
  FORCE=1 py -3 scripts/run_test_subarray_cae_export.py
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.paths import ensure_output_dirs

ensure_output_dirs()

RUN_SLUG = "cae_tet0p6mm80_5mmin_paperbox"
L_MM = 20.0
SIZES = ("332", "333", "442", "443")
CASES = (
    "af2q0_deq2_k1",
    "af2q0p5_deq2_k1",
    "af2q1_deq2_k1",
    "af2q1p5_deq2_k1",
)

_CASE_RE = re.compile(
    r"^af(?P<Af>[\dp]+)q(?P<Q>[\dp]+)_deq(?P<deq>[\dp]+)_k(?P<k>[\dp]+)$"
)


def _p_token(s: str) -> float:
    return float(str(s).replace("p", "."))


def parse_case_id(case_id: str) -> dict:
    m = _CASE_RE.match(case_id.strip())
    if not m:
        raise ValueError(f"bad case_id: {case_id!r}")
    return {
        "case_id": case_id,
        "Af": _p_token(m.group("Af")),
        "Q": _p_token(m.group("Q")),
        "deq_mm": _p_token(m.group("deq")),
        "k": _p_token(m.group("k")),
    }


def parse_size_tag(tag: str) -> tuple[int, int, int]:
    t = str(tag).strip()
    if len(t) == 3 and t.isdigit():
        return int(t[0]), int(t[1]), int(t[2])
    raise ValueError(f"bad size tag: {tag!r} (want 332/333/442/443)")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def export_one(
    size: str,
    case_id: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    nx, ny, nz = parse_size_tag(size)
    params = parse_case_id(case_id)
    key = f"{case_id}_{size}"

    step = _ROOT / "output" / "cad" / "test" / size / f"{case_id}_{size}.step"
    out_dir = _ROOT / "output" / "export" / "test" / size / case_id / RUN_SLUG
    mesh_inp = out_dir / f"{RUN_SLUG}_cae_mesh.inp"
    comp_inp = out_dir / f"{RUN_SLUG}.inp"

    if not mesh_inp.is_file() or mesh_inp.stat().st_size < 1_000_000:
        return {"key": key, "ok": False, "error": f"missing mesh: {mesh_inp}"}
    if not step.is_file():
        return {"key": key, "ok": False, "error": f"missing STEP: {step}"}
    if (
        not force
        and comp_inp.is_file()
        and comp_inp.stat().st_size > 1_000_000
    ):
        return {
            "key": key,
            "ok": True,
            "skipped": True,
            "comp_inp": str(comp_inp),
            "nx": nx,
            "ny": ny,
            "nz": nz,
            "stroke_mm": 0.8 * nz * L_MM,
        }

    export_root = _ROOT / "output" / "export" / "test" / size / case_id
    jobs_root = _ROOT / "output" / "jobs" / "test" / size / case_id
    post_root = _ROOT / "output" / "post" / "test" / size / case_id
    for d in (export_root, jobs_root, post_root, out_dir):
        d.mkdir(parents=True, exist_ok=True)

    stroke = 0.8 * nz * L_MM
    args = [
        sys.executable,
        str(_ROOT / "scripts" / "run_hu_bai_bcc_solid_cad_cae_tet_export.py"),
        "--nx",
        str(nx),
        "--ny",
        str(ny),
        "--nz",
        str(nz),
        "--L",
        str(L_MM),
        "--Q",
        str(params["Q"]),
        "--Af",
        str(params["Af"]),
        "--rod-diameter",
        str(params["deq_mm"]),
        "--profile",
        "fast",
        "--cad",
        str(step),
        "--cae-seed",
        "0.6",
        "--cae-element-type",
        "C3D4",
        "--cae-mesh-quality",
        "lattice_contact",
        "--strain",
        "0.80",
        "--load-rate-mm-min",
        "5",
        "--explicit-dt",
        "0.0005",
        "--explicit-dt-mode",
        "automatic",
        "--material-model",
        "paper",
        "--contact-store-offsets",
        "--contact-settle",
        "--contact-settle-fraction",
        "0.15",
        "--contact-settle-soft-s0",
        "0.02",
        "--slug-mode",
        "short",
        "--short-slug",
        RUN_SLUG,
        "--mesh-locally",
        "--cae-mesh-inp",
        str(mesh_inp),
    ]
    print(
        f"\n=== EXPORT {key} {nx}x{ny}x{nz} stroke={stroke:g}mm "
        f"Q={params['Q']} ===",
        flush=True,
    )
    if dry_run:
        print("  DRY", " ".join(args), flush=True)
        return {
            "key": key,
            "ok": True,
            "dry_run": True,
            "nx": nx,
            "ny": ny,
            "nz": nz,
        }

    env = os.environ.copy()
    env["HU_BAI_EXPORT_ROOT"] = str(export_root)
    env["HU_BAI_JOBS_ROOT"] = str(jobs_root)
    env["HU_BAI_POST_ROOT"] = str(post_root)
    env["HU_BAI_PROJECT_ROOT"] = str(_ROOT)
    log_path = out_dir / "cae_export_local.log"
    with open(log_path, "w", encoding="utf-8") as logf:
        proc = subprocess.run(
            args,
            cwd=str(_ROOT),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            check=False,
        )
    ok = (
        proc.returncode == 0
        and comp_inp.is_file()
        and comp_inp.stat().st_size > 1_000_000
    )
    if ok:
        mb = comp_inp.stat().st_size / 1e6
        print(f"  OK -> {comp_inp} ({mb:.1f} MiB)", flush=True)
    else:
        print(f"  FAIL exit={proc.returncode} log={log_path}", flush=True)
    return {
        "key": key,
        "ok": ok,
        "comp_inp": str(comp_inp) if ok else None,
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "stroke_mm": stroke,
        "exit_code": proc.returncode,
        "log": str(log_path),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only-size", nargs="*", default=None)
    ap.add_argument("--only-case", nargs="*", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    sizes = tuple(args.only_size) if args.only_size else SIZES
    cases = tuple(args.only_case) if args.only_case else CASES
    force = bool(args.force) or _env_flag("FORCE")

    print(
        "test-subarray compression export\n"
        f"  sizes={list(sizes)} cases={list(cases)} force={force}",
        flush=True,
    )
    reports = []
    failed = []
    for size in sizes:
        for case_id in cases:
            rep = export_one(
                size, case_id, force=force, dry_run=bool(args.dry_run)
            )
            reports.append(rep)
            if not rep.get("ok"):
                failed.append(rep["key"])
                if rep.get("error"):
                    print(f"  [FAIL] {rep['key']}: {rep['error']}", flush=True)

    n_ok = sum(1 for r in reports if r.get("ok"))
    n_skip = sum(1 for r in reports if r.get("skipped"))
    print(
        f"\n=== DONE ok={n_ok} skip={n_skip} fail={len(failed)} ===",
        flush=True,
    )
    if failed:
        print("  FAIL:", ", ".join(failed), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
