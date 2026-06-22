"""
Clone an existing CAD solid compression INP with new loading (no re-mesh).

Example:
  py -3 scripts/clone_cad_compression_loading.py ^
    --from-slug hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_fast ^
    --case-suffix fast80 --strain 0.8
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.abaqus_compression import (
    HU_BAI_AMPLITUDE_HOLD_FRACTION,
    HU_BAI_EXPLICIT_DT,
    HU_BAI_LOAD_RATE_MM_MIN,
    hu_bai_compression_displacement,
    hu_bai_quasi_static_step_time,
)
from src.naming import load_case_manifest
from src.paths import ABAQUS_JOBS, ABAQUS_POST, EXPORT_ROOT
from src.postprocess.compression_curve import CompressionMeta, load_compression_meta, save_compression_meta
from src.validation.penetration_risk import update_manifest_penetration_check


def _derive_dst_slug(src_slug: str, case_suffix: str) -> str:
    if re.search(r"_solid_cad_p$", src_slug):
        return re.sub(r"_solid_cad_p$", f"_solid_cad_f_{case_suffix}", src_slug)
    base = re.sub(r"_(fast80|fast70|fast|paper|pilot)$", "", src_slug)
    if base != src_slug:
        return f"{base}_{case_suffix}"
    return f"{src_slug}_{case_suffix}"


def _patch_inp_footer(
    text: str,
    *,
    disp: float,
    step_time: float,
    hold: float,
    explicit_dt: float,
) -> str:
    n_inc = int(round(step_time / explicit_dt))
    hist = step_time / 100.0
    text = re.sub(
        r"(?ms)^(\*Amplitude, name=COMP-DISP, time=TOTAL TIME\r?\n"
        r"0\., 0\.\r?\n)[0-9.eE+-]+, 0\.\r?\n[0-9.eE+-]+, 1\.\r?\n",
        rf"\g<1>{hold:.12g}, 0.\n{step_time:.12g}, 1.\n",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\*Dynamic, Explicit, direct user control\r?\n)[0-9.eE+-]+, [0-9.eE+-]+",
        rf"\g<1>{explicit_dt:.12g}, {step_time:.12g}",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\*Fixed Mass Scaling, elset=ALLSOLID, factor=50, type=BELOW MIN, dt=)[0-9.eE+-]+",
        rf"\g<1>{explicit_dt:.12g}",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\*Boundary, type=DISPLACEMENT, op=MOD, amplitude=COMP-DISP\r?\nPLATE_REF, 3, 3, )-?[0-9.eE+-]+",
        rf"\g<1>{-abs(disp):.12g}",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\*Output, history, time interval=)[0-9.eE+-]+",
        rf"\g<1>{hist:.12g}",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^\*\* Explicit fixed dt=[0-9.eE+-]+s \(~[0-9]+ increments\)",
        rf"** Explicit fixed dt={explicit_dt:.12g}s (~{n_inc} increments)",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\*\* loading=.* disp=)-?[0-9.eE+-]+/[0-9.eE+-]+s",
        rf"\g<1>{-abs(disp):.9g}/{step_time:.9g}s",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\*\* loading=.* dt=)[0-9.eE+-]+s",
        rf"\g<1>{explicit_dt:.12g}s",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\*\* loading=.* n_inc=)[0-9]+",
        rf"\g<1>{n_inc}",
        text,
        count=1,
    )
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-slug", required=True)
    parser.add_argument("--case-suffix", required=True)
    parser.add_argument("--strain", type=float, required=True)
    parser.add_argument("--load-rate-mm-min", type=float, default=0.0)
    parser.add_argument("--explicit-dt", type=float, default=0.0)
    parser.add_argument("--hold-fraction", type=float, default=-1.0)
    args = parser.parse_args()

    src_dir = os.path.join(EXPORT_ROOT, args.from_slug)
    src_manifest_path = os.path.join(src_dir, "case_manifest.json")
    if not os.path.isfile(src_manifest_path):
        print(f"[ERROR] Missing source manifest: {src_manifest_path}", file=sys.stderr)
        return 1

    src = load_case_manifest(src_manifest_path)
    src_slug = str(src["slug"])
    dst_slug = _derive_dst_slug(src_slug, args.case_suffix)

    nz = int(src["paper_params"]["block_cells"][2])
    cell_size = float(src["paper_params"]["cell_size_mm"])
    fast80 = args.case_suffix == "fast80"
    if args.load_rate_mm_min > 0:
        load_rate = float(args.load_rate_mm_min)
    elif fast80:
        load_rate = HU_BAI_LOAD_RATE_MM_MIN
    else:
        load_rate = float(src["loading"]["load_rate_mm_min"])
    if args.explicit_dt > 0:
        explicit_dt = float(args.explicit_dt)
    elif fast80:
        explicit_dt = HU_BAI_EXPLICIT_DT
    else:
        explicit_dt = float(src["loading"]["explicit_dt"])
    if args.hold_fraction >= 0:
        hold_fraction = float(args.hold_fraction)
    elif fast80:
        hold_fraction = HU_BAI_AMPLITUDE_HOLD_FRACTION
    else:
        hold_fraction = float(src["loading"]["amplitude_hold_fraction"])

    disp = hu_bai_compression_displacement(nz, cell_size, target_strain=float(args.strain))
    step_time = hu_bai_quasi_static_step_time(disp, load_rate_mm_min=load_rate)
    hold = hold_fraction * step_time
    n_inc = int(round(step_time / explicit_dt))

    src_inp = str(src["compression_inp"])
    if not os.path.isfile(src_inp):
        print(f"[ERROR] Missing source INP: {src_inp}", file=sys.stderr)
        return 1

    dst_export = os.path.join(EXPORT_ROOT, dst_slug)
    dst_job = os.path.join(ABAQUS_JOBS, dst_slug)
    dst_post = os.path.join(ABAQUS_POST, dst_slug)
    for d in (dst_export, dst_job, dst_post):
        os.makedirs(d, exist_ok=True)

    dst_inp = os.path.join(dst_export, f"{dst_slug}.inp")
    dst_meta_path = os.path.join(dst_export, f"{dst_slug}_meta.json")
    dst_manifest_path = os.path.join(dst_export, "case_manifest.json")

    print(f"Clone mesh from: {src_slug}")
    print(f"  -> {dst_slug}")
    print(f"  strain {src['loading']['target_engineering_strain']:.0%} -> {args.strain:.0%}")
    print(f"  disp {src['loading']['compression_displacement_mm']:.1f} -> {disp:.1f} mm")
    print(f"  step {src['loading']['step_time_s']:.1f} -> {step_time:.1f} s (~{n_inc} inc)")

    with open(src_inp, encoding="utf-8", errors="replace") as f:
        inp_text = f.read()
    patched = _patch_inp_footer(
        inp_text,
        disp=disp,
        step_time=step_time,
        hold=hold,
        explicit_dt=explicit_dt,
    )
    with open(dst_inp, "w", encoding="utf-8", newline="\n") as f:
        f.write(patched)

    src_meta = load_compression_meta(str(src["meta_json"]))
    src_meta.compression_displacement = disp
    src_meta.step_time = step_time
    src_meta.case_slug = dst_slug
    src_meta.amplitude_hold_fraction = hold_fraction
    save_compression_meta(src_meta, dst_meta_path)

    manifest = dict(src)
    manifest.update(
        {
            "slug": dst_slug,
            "export_dir": dst_export,
            "job_dir": dst_job,
            "post_dir": dst_post,
            "compression_inp": dst_inp,
            "case_manifest": dst_manifest_path,
            "meta_json": dst_meta_path,
            "odb": os.path.join(dst_job, f"{dst_slug}.odb"),
            "job_name": dst_slug,
            "job_inp_name": f"{dst_slug}.inp",
            "stress_strain_csv": os.path.join(dst_post, f"{dst_slug}_stress_strain.csv"),
            "stress_strain_raw_csv": os.path.join(dst_post, f"{dst_slug}_stress_strain_raw.csv"),
            "stress_strain_png": os.path.join(dst_post, f"{dst_slug}_stress_strain.png"),
            "yield_json": os.path.join(dst_post, f"{dst_slug}_yield.json"),
        }
    )
    loading = dict(manifest["loading"])
    loading.update(
        {
            "compression_displacement_mm": disp,
            "target_engineering_strain": float(args.strain),
            "step_time_s": step_time,
            "load_rate_mm_min": load_rate,
            "explicit_dt": explicit_dt,
            "amplitude_hold_fraction": hold_fraction,
            "quasi_static_paper_rate": abs(load_rate - 5.0) < 1e-9,
            "explicit_n_increments_est": n_inc,
            "case_suffix": args.case_suffix,
        }
    )
    manifest["loading"] = loading
    if fast80:
        manifest.update({"profile": "fast", "stroke": "full", "stroke_tag": "f"})

    with open(dst_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    active_case = os.path.join(_ROOT, "output", "active_case.json")
    with open(active_case, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    update_manifest_penetration_check(
        dst_manifest_path,
        meta_path=dst_meta_path,
        inp_path=dst_inp,
        active_path=active_case,
    )

    # Copy optional CSV sidecars if present.
    for suffix in ("_nodes.csv", "_beams.csv"):
        src_side = os.path.join(src_dir, f"{src_slug}{suffix}")
        if os.path.isfile(src_side):
            shutil.copy2(src_side, os.path.join(dst_export, f"{dst_slug}{suffix}"))

    print(f"  INP: {dst_inp}")
    print(f"  Manifest: {dst_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
