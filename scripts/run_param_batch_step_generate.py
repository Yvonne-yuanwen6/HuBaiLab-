"""
Batch-generate paper_box unitcell + strut1 + 4x4x4 STEP into output/cad/批量构型/{id}/.

Naming:
  {id}_1x1.step
  {id}_strut1_raw.step  # pre-cut extended pipe (same solid about to be box-cut)
  {id}_strut1.step      # one representative paper-box octant-cut strut
  {id}_444.step
  id = af{Af}q{Q}_deq{D}_k{κ}

QC: V_444 / V_1x1 ≈ 64 (±3% default). Strut is independent of that gate.
Accept 444 only when gmsh OCC reports volume_count==1 (not OCP-only).

After a valid 444 write, optionally run structure-preserving Gmsh OCC heal
(``step_heal_for_cae``): only replace ``*_444.step`` when mass_ratio∈[0.95,1.05]
and a single solid remains — design params Af/Q/deq/k are unchanged. Disable with
``--no-post-heal`` / ``BATCH_STEP_POST_HEAL=0``.

Locked 444 scheme (do not regress):
  - Preferred: ocp_seed_scale*_zcopy_* = scale-inflate → fuse iz=0 only → +Z copy
    layers → 444z fuse → gmsh-verify single solid.
  - Thin rod (deq<1.75, k=1): deep_pad first, then seed_scale_zcopy.
  - --jobs>1: gmsh.initialize is never called on worker threads (child process).
  - --force: light pre-scan (qc.json + sizes), no gmsh measure of existing 444.

Each 1x1 / 444 strategy attempt runs in a child process with a hard wall-clock
timeout; hung OCC/gmsh work is killed and the ladder advances.

  py -3 scripts/run_param_batch_step_generate.py
  py -3 scripts/run_param_batch_step_generate.py --only af2q0_deq2_k1
  py -3 scripts/run_param_batch_step_generate.py --force
  py -3 scripts/run_param_batch_step_generate.py --repair
  py -3 scripts/run_param_batch_step_generate.py --repair --only af2q1_deq1p5_k1
  py -3 scripts/run_param_batch_step_generate.py --strut-only
  py -3 scripts/run_param_batch_step_generate.py --force --jobs 2 --only af2q1_deq2_k1 af2q0_deq2_k1p5
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import shutil
import sys
import threading
import time
import traceback
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.sw_parasolid import measure_step_occ_stats
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator, is_q1_period
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

BATCH_DIR_NAME = "批量构型"
DEFAULT_INDEX = os.path.join(str(CAD_ROOT), BATCH_DIR_NAME, "_batch_index.json")
L_MM = 20.0
N_SEG = 24
N_CELLS = 4
VOL_RATIO_TARGET = 64.0
VOL_TOL_REL = 0.03
DEFAULT_UNITCELL_ATTEMPT_TIMEOUT_S = 600.0  # 10 min — kill hang, next strategy
DEFAULT_ARRAY_ATTEMPT_TIMEOUT_S = 5400.0  # 90 min

# Locked seed_scale_zcopy ladder rungs: (scale, glue, fuzzy_mm).
# Proven: scale=1.005, glue=off, fuzzy=0.1 → QC≈64.3 (af2q1p5_deq2_k1p5).
SEED_SCALE_ZCOPY_SPECS_DEFAULT: tuple[tuple[float, str, float], ...] = (
    (1.005, "off", 0.1),
    (1.008, "off", 0.1),
    (1.012, "off", 0.1),
)
SEED_SCALE_ZCOPY_SPECS_THIN_ROD: tuple[tuple[float, str, float], ...] = (
    (1.005, "off", 0.1),
    (1.01, "off", 0.1),
    (1.02, "off", 0.1),
)
DEEP_PAD_SPECS_THIN_ROD: tuple[tuple[float, str, float], ...] = (
    (2.0, "full", 0.05),
    (2.0, "shift", 0.1),
    (1.0, "full", 0.1),
)


def _profile_from_deq_k(deq_mm: float, k: float) -> tuple[str, float, float]:
    """Return (solid_profile, rod_diameter_mm, ellipse_minor_ratio)."""
    deq = float(deq_mm)
    kappa = float(k)
    if abs(kappa - 1.0) < 1e-9:
        return "circle", deq, 1.0
    if kappa < 1.0:
        raise ValueError(f"aspect ratio k must be >= 1, got {kappa}")
    d_major = deq * math.sqrt(kappa)
    minor_ratio = 1.0 / kappa
    return "ellipse", d_major, minor_ratio


def _choose_array_backend(q: float, k: float) -> tuple[str, str]:
    """(backend, ocp_fuse_mode)."""
    if is_q1_period(q) or float(k) > 1.0 + 1e-9:
        mode = (
            "sequential"
            if (is_q1_period(q) or float(q) >= 1.0 - 1e-9)
            else "hierarchical_batch"
        )
        return "ocp", mode
    return "gmsh", "hierarchical_batch"


def _legacy_unitcell_seed(Af: float, Q: float, deq: float, k: float) -> str | None:
    """Reuse previously verified paper_box unitcell seeds for AF2/deq2/k1 baselines."""
    if abs(float(Af) - 2.0) > 1e-9 or abs(float(deq) - 2.0) > 1e-9:
        return None
    if abs(float(k) - 1.0) > 1e-9:
        return None
    gen = HuBaiLatticeGenerator(
        cell_size=L_MM,
        rod_diameter=2.0,
        amplitude=2.0,
        period_factor=float(Q),
        n_segments=N_SEG,
    )
    gen.build_unitcell()
    cand = os.path.join(
        str(CAD_ROOT),
        "_unitcell_paper_box_cut",
        f"unitcell_{gen.variant_name.lower()}_paper_box.step",
    )
    return cand if _seed_ok(cand) else None


def _count_seed_volumes_job(path: str) -> int:
    from src.export.paper_box_array_fuse import _count_seed_volumes

    return int(_count_seed_volumes(path))


def _seed_face_mate_ok(path: str, *, pitch_mm: float = L_MM) -> bool:
    """True if pitch=L neighbour fuse yields one solid with mass≈2×seed (X/Y/Z).

    A 1-volume 1x1 can still fail array fuse when tip faces do not mate at pitch=L
    (seen 2026-07-19 on ``af2q1_deq2p5_k1`` --force rebuild).
    """
    try:
        from src.export.ocp_paper_box_array_fuse import (
            ocp_read_step_shape,
            ocp_translate_shape,
        )
        from src.export.ocp_unitcell_fuse import (
            _ocp_count_solids,
            ocp_fuse_pair,
            ocp_mass,
        )

        seed = ocp_read_step_shape(path)
        m = float(ocp_mass(seed))
        if m <= 0.0 or int(_ocp_count_solids(seed)) != 1:
            return False
        pitch = float(pitch_mm)
        for axis, off in (
            ("X", (pitch, 0.0, 0.0)),
            ("Y", (0.0, pitch, 0.0)),
            ("Z", (0.0, 0.0, pitch)),
        ):
            hit = False
            b = ocp_translate_shape(seed, *off)
            for glue, fz in (("shift", 0.1), ("off", 0.2), ("full", 0.1)):
                try:
                    fused = ocp_fuse_pair(
                        seed,
                        b,
                        glue=glue,  # type: ignore[arg-type]
                        fuzzy_mm=float(fz),
                        simplify=False,
                        label=f"mate-{axis}",
                    )
                    n = int(_ocp_count_solids(fused))
                    r = float(ocp_mass(fused)) / (2.0 * m)
                    if n == 1 and 0.9 <= r <= 1.1:
                        hit = True
                        break
                except Exception:
                    continue
            if not hit:
                return False
        return True
    except Exception:
        return False


def _seed_ok(path: str, *, timeout_s: float = 90.0) -> bool:
    if not os.path.isfile(path) or os.path.getsize(path) < 1024:
        return False
    try:
        from src.export.timed_attempt import run_with_timeout

        return (
            int(
                run_with_timeout(
                    _count_seed_volumes_job,
                    path,
                    timeout_s=float(timeout_s),
                    label="seed_ok",
                )
            )
            == 1
        )
    except Exception:
        return False


def _qc_pair(unit_step: str, array_step: str, *, tol_rel: float) -> dict[str, Any]:
    u = measure_step_occ_stats(unit_step)
    a = measure_step_occ_stats(array_step)
    vu = float(u.get("mass_mm3") or 0.0)
    va = float(a.get("mass_mm3") or 0.0)
    ratio = (va / vu) if vu > 0 else float("nan")
    err = abs(ratio - VOL_RATIO_TARGET) / VOL_RATIO_TARGET if vu > 0 else float("inf")
    ok = (
        int(u.get("volume_count") or 0) == 1
        and int(a.get("volume_count") or 0) == 1
        and err <= float(tol_rel)
    )
    return {
        "ok": bool(ok),
        "unitcell": u,
        "array": a,
        "volume_ratio": ratio,
        "target_ratio": VOL_RATIO_TARGET,
        "rel_error": err,
        "tol_rel": float(tol_rel),
    }


def _case_status(
    case_dir: str,
    case_id: str,
    *,
    tol_rel: float,
    light: bool = False,
) -> dict[str, Any]:
    """Inspect whether a case already has QC-ok STEPs.

    ``light=True`` (check-only): trust qc.json + file sizes only — never gmsh.
    """
    unit_step = os.path.join(case_dir, f"{case_id}_1x1.step")
    array_step = os.path.join(case_dir, f"{case_id}_444.step")
    qc_path = os.path.join(case_dir, f"{case_id}_qc.json")
    unit_exists = os.path.isfile(unit_step) and os.path.getsize(unit_step) > 1024
    array_exists = (
        os.path.isfile(array_step) and os.path.getsize(array_step) > 1_000_000
    )
    out: dict[str, Any] = {
        "case_id": case_id,
        "unit_exists": unit_exists,
        "array_exists": array_exists,
        "unit_ok": False,
        "qc_ok": False,
        "needs_repair": True,
        "unit_step": unit_step,
        "array_step": array_step,
        "qc_path": qc_path,
    }

    if os.path.isfile(qc_path):
        try:
            with open(qc_path, encoding="utf-8") as f:
                qc = json.load(f)
            out["qc_status"] = qc.get("status")
            out["volume_ratio"] = (qc.get("qc") or {}).get("volume_ratio")
            out["error_snippet"] = (str(qc.get("error") or ""))[:240] or None
            qc_block = qc.get("qc") if isinstance(qc.get("qc"), dict) else {}
            status = str(qc.get("status") or "").lower()
            # Older runs stored only nested qc.ok (no top-level status).
            nested_ok = bool(qc_block.get("ok"))
            ratio = qc_block.get("volume_ratio")
            ratio_ok = False
            if ratio is not None:
                try:
                    ratio_ok = (
                        abs(float(ratio) - VOL_RATIO_TARGET) / VOL_RATIO_TARGET
                        <= float(tol_rel)
                    )
                except Exception:
                    ratio_ok = False
            out["qc_ok"] = nested_ok or status == "ok" or (
                ratio_ok
                and int(qc_block.get("unitcell", {}).get("volume_count") or 0) == 1
                and int(qc_block.get("array", {}).get("volume_count") or 0) == 1
            )
            if out["qc_ok"] and unit_exists and array_exists:
                out["unit_ok"] = True
                out["needs_repair"] = False
                return out
        except Exception as exc:
            out["qc_read_error"] = str(exc)

    if light:
        out["unit_ok"] = unit_exists
        out["needs_repair"] = not (unit_exists and array_exists and out["qc_ok"])
        return out

    if unit_exists:
        out["unit_ok"] = _seed_ok(unit_step, timeout_s=90.0)
    out["needs_repair"] = not (out["unit_ok"] and array_exists and out["qc_ok"])
    if out["unit_ok"] and array_exists and not out["qc_ok"]:
        try:
            fresh = _qc_pair(unit_step, array_step, tol_rel=tol_rel)
            out["qc_ok"] = bool(fresh.get("ok"))
            out["volume_ratio"] = fresh.get("volume_ratio")
            out["needs_repair"] = not out["qc_ok"]
        except Exception as exc:
            out["qc_remeasure_error"] = str(exc)
            out["needs_repair"] = True
    return out


def _apply_unitcell_bbox_recenter(out_step: str, report: dict[str, Any]) -> dict[str, Any]:
    """Ensure 1x1 AABB midpoint is at origin (idempotent if already centered)."""
    from src.export.sw_parasolid import recenter_step_bbox_to_origin

    recenter = recenter_step_bbox_to_origin(out_step)
    out = dict(report or {})
    out["bbox_recenter"] = recenter
    if recenter.get("shifted"):
        print(
            f"  recenter 1x1 COM → origin: "
            f"dx={float(recenter['dx']):+.4f} dy={float(recenter['dy']):+.4f} "
            f"dz={float(recenter['dz']):+.4f} mm",
            flush=True,
        )
    return out


def _export_unitcell(
    *,
    out_step: str,
    Af: float,
    Q: float,
    deq_mm: float,
    k: float,
    force: bool,
    attempt_timeout_s: float = DEFAULT_UNITCELL_ATTEMPT_TIMEOUT_S,
) -> dict[str, Any]:
    if (not force) and _seed_ok(out_step):
        print(f"  skip 1x1 (exists vol=1): {out_step}", flush=True)
        return {"skipped": True, "path": out_step}

    # Prefer a previously verified seed only for cold-start (not --force rebuilds).
    if not force:
        legacy = _legacy_unitcell_seed(Af, Q, deq_mm, k)
        if legacy and not _seed_ok(out_step):
            print(f"  try legacy seed copy: {legacy}", flush=True)
            shutil.copy2(legacy, out_step)
            if _seed_ok(out_step):
                return _apply_unitcell_bbox_recenter(
                    out_step,
                    {"skipped": False, "seed_method": "legacy_copy", "path": out_step},
                )

    from src.export.param_batch_jobs import unitcell_gmsh_job, unitcell_ocp_job
    from src.export.timed_attempt import AttemptTimeoutError, run_with_timeout

    profile, rod_d, minor_ratio = _profile_from_deq_k(deq_mm, k)
    base: dict[str, Any] = {
        "out_step": out_step,
        "cell_size_mm": L_MM,
        "rod_diameter_mm": rod_d,
        "amplitude_mm": float(Af),
        "period_factor": float(Q),
        "n_segments": N_SEG,
        "solid_profile": profile,
        "ellipse_minor_ratio": minor_ratio,
        "compression_axis": (0.0, 0.0, 1.0),
        "ellipse_align_to_compression": "minor",
    }

    attempts: list[tuple[str, Any, dict[str, Any], float]] = []
    gmsh_timeout = min(float(attempt_timeout_s), 480.0)

    def _add_gmsh(label: str, *, both_end: bool, q1_mode: str) -> None:
        payload = dict(base)
        payload["both_end_extension"] = both_end
        payload["q1_mode"] = q1_mode
        attempts.append((label, unitcell_gmsh_job, payload, gmsh_timeout))

    def _add_ocp(
        pipe_mode: str,
        strat: str,
        fz: float,
        ov: float | None = None,
        ext: float | None = None,
    ) -> None:
        bits = [f"ocp_{pipe_mode}_{strat}_f{str(fz).replace('.', 'p')}"]
        if ov is not None:
            bits.append(f"ov{str(ov).replace('.', 'p')}")
        if ext is not None:
            bits.append(f"ext{str(ext).replace('.', 'p')}")
        payload = dict(base)
        payload.update(
            {
                "pipe_mode": pipe_mode,
                "strategy": strat,
                "fuzzy_mm": fz,
                "center_overlap_mm": ov,
                "centre_extension_mm": ext,
                "corner_extension_mm": ext,
            }
        )
        attempts.append(
            ("_".join(bits), unitcell_ocp_job, payload, float(attempt_timeout_s))
        )

    # Tip-sliver / strut1 parity:
    # - OCP centre_stub_corner_ext FIRST (2026-07-17): corner path ext → flat tips;
    #   centre stub → sequential GlueShift fuse. both_end_extension often fails to fuse
    #   on hard Q=1 / ellipse cases while this hybrid succeeds (~25s).
    # - gmsh *_both_end and OCP both_end_extension remain as fallbacks.
    # Forbidden ACCEPT: bare centre_stub / gmsh_paper_box / bare gmsh_octant.
    #
    # Face-mate lock (2026-07-19): auto corner≈0.75*deq can yield a 1-solid 1x1 that
    # still fails pitch=L neighbour fuse (empty BOP). Prefer proven ext first so
    # ``_seed_ok`` does not ACCEPT a non-mating seed before noclip_batch64.
    need_ocp = profile == "ellipse" or is_q1_period(Q) or abs(float(Q) - 1.5) < 1e-9
    if need_ocp:
        if profile != "ellipse" and is_q1_period(Q):
            if abs(float(deq_mm) - 2.5) < 1e-6:
                # af2q1_deq2p5_k1: ext=2.5 → X/Y/Z HIT → noclip_batch64
                _add_ocp(
                    "centre_stub_corner_ext",
                    "sequential_glue_shift",
                    0.1,
                    0.02,
                    2.5,
                )
            if abs(float(deq_mm) - 1.5) < 1e-6:
                # af2q1_deq1p5_k1: ext=1.5 → X/Y/Z HIT → noclip_batch64
                _add_ocp(
                    "centre_stub_corner_ext",
                    "sequential_glue_shift",
                    0.1,
                    0.02,
                    1.5,
                )
        if profile == "ellipse" and float(k) >= 2.0 - 1e-9:
            # af2q0p5_deq2_k2: centre_stub fails; both_end+ext=3 → HIT → noclip
            _add_ocp("both_end_extension", "sequential_glue_shift", 0.1, 0.05, 3.0)
            _add_ocp("both_end_extension", "sequential_glue_shift", 0.1, 0.02, 2.5)
        for strat, fz in (
            ("sequential_glue_shift", 0.05),
            ("sequential_glue_shift", 0.1),
            ("x_layer_glue_shift", 0.1),
        ):
            _add_ocp("centre_stub_corner_ext", strat, fz)

    if profile == "ellipse":
        _add_gmsh("gmsh_octant_both_end", both_end=True, q1_mode="fuse")
    elif is_q1_period(Q):
        _add_gmsh("gmsh_octant_both_end", both_end=True, q1_mode="fuse")
        _add_gmsh("gmsh_paper_box_both_end", both_end=True, q1_mode="auto")
    else:
        _add_gmsh("gmsh_paper_box_both_end", both_end=True, q1_mode="auto")
        _add_gmsh("gmsh_octant_both_end", both_end=True, q1_mode="fuse")

    if need_ocp:
        if profile == "ellipse":
            for strat, fz in (
                ("sequential_glue_shift", 0.05),
                ("sequential_glue_shift", 0.1),
                ("sequential_glue_full", 0.05),
                ("x_layer_glue_shift", 0.1),
                ("batch_glue_shift", 0.1),
                ("sequential_glue_shift", 0.2),
            ):
                _add_ocp("both_end_extension", strat, fz)
        else:
            for strat, fz, ov, ext in (
                ("sequential_glue_shift", 0.05, None, None),
                ("sequential", 0.05, None, None),
                ("x_layer_glue_shift", 0.05, None, None),
                ("batch_glue_shift", 0.05, None, None),
                ("sequential_glue_shift", 0.1, None, None),
                ("x_layer_glue_shift", 0.1, None, None),
                ("sequential", 0.1, None, None),
                ("sequential_glue_shift", 0.2, None, None),
                ("x_layer_glue_shift", 0.4, 0.2, 4.0),
            ):
                _add_ocp("both_end_extension", strat, fz, ov, ext)

    def _tip_sliver_payload(label: str, payload: dict[str, Any]) -> bool:
        """True if this attempt would produce strut-end tip wedges (≠ strut1)."""
        if label.startswith("gmsh_") or "gmsh" in label:
            if not bool(payload.get("both_end_extension")):
                return True
            if label == "gmsh_octant" or (
                label.startswith("gmsh_octant") and "both_end" not in label
            ):
                return True
            if label == "gmsh_paper_box" or (
                label.startswith("gmsh_paper_box") and "both_end" not in label
            ):
                return True
            return False
        # OCP: tip-safe modes have corner path extension (flat outer tips).
        mode = str(payload.get("pipe_mode") or "")
        return mode not in ("both_end_extension", "centre_stub_corner_ext")

    # Tip-sliver lock: refuse ACCEPT of tip-wedge methods (strut1 parity).
    errors: list[str] = []
    for label, job_fn, payload, t_budget in attempts:
        print(f"  1x1 try: {label} (timeout={t_budget:.0f}s)", flush=True)
        t0 = time.time()
        try:
            report = run_with_timeout(
                job_fn,
                payload,
                timeout_s=t_budget,
                label=label,
            )
            if _seed_ok(out_step):
                if _tip_sliver_payload(label, payload):
                    errors.append(
                        f"{label}: refused tip-sliver seed "
                        f"(require both_end like strut1; {time.time() - t0:.0f}s)"
                    )
                    print(
                        f"    REJECT {label}: tip-sliver lock "
                        f"(need both_end_extension / OCP both_end_extension)",
                        flush=True,
                    )
                    continue
                report = dict(report or {})
                report["seed_method"] = label
                report["path"] = out_step
                report["attempt_seconds"] = round(time.time() - t0, 1)
                report["both_end_extension"] = bool(
                    payload.get("both_end_extension")
                    or payload.get("pipe_mode") == "both_end_extension"
                )
                # Export paths already recenter; keep idempotent for legacy/edge cases.
                report = _apply_unitcell_bbox_recenter(out_step, report)
                # Hard Q/ellipse arrays need pitch=L face mating (after recenter).
                need_mate = (
                    profile == "ellipse"
                    or is_q1_period(Q)
                    or abs(float(Q) - 1.5) < 1e-9
                )
                if need_mate and not _seed_face_mate_ok(out_step):
                    errors.append(
                        f"{label}: refused non-mating seed "
                        f"(pitch=L X/Y/Z fuse miss; {time.time() - t0:.0f}s)"
                    )
                    print(
                        f"    REJECT {label}: face-mate lock "
                        f"(need X/Y/Z neighbour fuse n=1 r≈1 at pitch=L)",
                        flush=True,
                    )
                    continue
                report["face_mate_ok"] = True
                return report
            errors.append(f"{label}: seed not 1-volume ({time.time() - t0:.0f}s)")
            print(f"    FAIL {label}: seed not 1-volume", flush=True)
        except AttemptTimeoutError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            print(f"    FAIL {label}: {exc}", flush=True)

    raise RuntimeError("unitcell export failed:\n  - " + "\n  - ".join(errors))


def _strut1_raw_path(strut_step: str) -> str:
    """``.../{id}_strut1.step`` → ``.../{id}_strut1_raw.step`` (pre-cut pipe)."""
    root, ext = os.path.splitext(strut_step)
    if root.endswith("_strut1"):
        return root + "_raw" + ext
    return root + "_raw" + ext


def _export_strut1(
    *,
    out_step: str,
    Af: float,
    Q: float,
    deq_mm: float,
    k: float,
    force: bool,
    attempt_timeout_s: float = DEFAULT_UNITCELL_ATTEMPT_TIMEOUT_S,
) -> dict[str, Any]:
    """Export one paper-box octant-cut strut (+ pre-cut raw). Failures non-fatal for QC."""
    raw_step = _strut1_raw_path(out_step)
    if (not force) and _seed_ok(out_step) and _seed_ok(raw_step):
        print(
            f"  skip strut1+raw (exists vol=1): {out_step} ; {raw_step}",
            flush=True,
        )
        return {
            "skipped": True,
            "path": out_step,
            "raw_path": raw_step,
            "ok": True,
        }

    from src.export.param_batch_jobs import strut_job
    from src.export.timed_attempt import AttemptTimeoutError, run_with_timeout

    profile, rod_d, minor_ratio = _profile_from_deq_k(deq_mm, k)
    payload: dict[str, Any] = {
        "out_step": out_step,
        "raw_out_step": raw_step,
        "cell_size_mm": L_MM,
        "rod_diameter_mm": rod_d,
        "amplitude_mm": float(Af),
        "period_factor": float(Q),
        "n_segments": N_SEG,
        "strut_index": 1,
        "solid_profile": profile,
        "ellipse_minor_ratio": minor_ratio,
        "compression_axis": (0.0, 0.0, 1.0),
        "ellipse_align_to_compression": "minor",
        "origin_assembly": True,
        # Both-end path extension past centre + corner → clean planar box-cut faces.
        "both_end_extension": True,
    }
    label = f"strut1_{profile}_both_end"
    t0 = time.time()
    print(
        f"  strut1 try: {label} (+raw) (timeout={float(attempt_timeout_s):.0f}s)",
        flush=True,
    )
    try:
        report = run_with_timeout(
            strut_job,
            payload,
            timeout_s=float(attempt_timeout_s),
            label=label,
        )
        if _seed_ok(out_step):
            out = dict(report or {})
            out["skipped"] = False
            out["ok"] = True
            out["method"] = label
            out["raw_path"] = raw_step
            out["raw_ok"] = bool(_seed_ok(raw_step))
            out["attempt_seconds"] = round(time.time() - t0, 1)
            print(
                f"    OK strut1 mass={out.get('cut_mass_mm3')} "
                f"raw={'ok' if out['raw_ok'] else 'missing'} "
                f"({out['attempt_seconds']:.0f}s)",
                flush=True,
            )
            return out
        return {
            "skipped": False,
            "ok": False,
            "path": out_step,
            "raw_path": raw_step,
            "error": "strut1 not 1-volume after export",
            "attempt_seconds": round(time.time() - t0, 1),
        }
    except AttemptTimeoutError as exc:
        print(f"    TIMEOUT strut1: {exc}", flush=True)
        return {
            "skipped": False,
            "ok": False,
            "path": out_step,
            "raw_path": raw_step,
            "error": str(exc),
            "attempt_seconds": round(time.time() - t0, 1),
        }
    except Exception as exc:
        print(f"    FAIL strut1: {exc}", flush=True)
        return {
            "skipped": False,
            "ok": False,
            "path": out_step,
            "raw_path": raw_step,
            "error": str(exc),
            "attempt_seconds": round(time.time() - t0, 1),
        }


def _export_array(
    *,
    seed_step: str,
    array_step: str,
    work_dir: str,
    Af: float,
    Q: float,
    k: float,
    deq_mm: float = 2.0,
    force: bool,
    attempt_timeout_s: float = DEFAULT_ARRAY_ATTEMPT_TIMEOUT_S,
) -> dict[str, Any]:
    if (
        (not force)
        and os.path.isfile(array_step)
        and os.path.getsize(array_step) > 1_000_000
    ):
        print(f"  skip 444 (exists): {array_step}", flush=True)
        return {"skipped": True, "path": array_step}

    from src.export.param_batch_jobs import (
        array_deep_pad_job,
        array_gmsh_job,
        array_noclip_batch_job,
        array_ocp_job,
        array_scale_batch_job,
        array_seed_scale_job,
    )
    from src.export.timed_attempt import AttemptTimeoutError, run_with_timeout

    os.makedirs(work_dir, exist_ok=True)
    backend, ocp_mode = _choose_array_backend(Q, k)
    work_array = os.path.join(work_dir, "array_work.step")
    if force:
        for name in os.listdir(work_dir):
            p = os.path.join(work_dir, name)
            if os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p) and name == ".work_zslab_cells":
                shutil.rmtree(p, ignore_errors=True)

    base = {
        "seed_step": seed_step,
        "work_array": work_array,
        "nx": N_CELLS,
        "ny": N_CELLS,
        "nz": N_CELLS,
        "cell_size": L_MM,
        "deq_mm": float(deq_mm),
        "Af": float(Af),
        "rod_d": float(deq_mm),
        "amplitude": float(Af),
    }
    attempts: list[tuple[str, Any, dict[str, Any], float]] = []
    thin_rod = float(deq_mm) < 1.75 and float(k) <= 1.0 + 1e-9
    ellipse = float(k) > 1.0 + 1e-9
    hard_q = abs(float(Q) - 1.0) < 1e-9 or abs(float(Q) - 1.5) < 1e-9

    def _append_seed_scale_zcopy(
        specs: tuple[tuple[float, str, float], ...],
    ) -> None:
        for sc, glue, fz in specs:
            payload = dict(base)
            payload.update({"scale": sc, "glue": glue, "fuzzy_mm": fz, "k": float(k)})
            tag = (
                f"ocp_seed_scale{str(sc).replace('.', 'p')}"
                f"_zcopy_g{glue}_f{str(fz).replace('.', 'p')}"
            )
            attempts.append(
                (tag, array_seed_scale_job, payload, float(attempt_timeout_s))
            )

    def _append_noclip_batch(
        specs: tuple[tuple[str, float], ...] = (("shift", 0.1), ("off", 0.1)),
    ) -> None:
        for glue, fz in specs:
            payload = dict(base)
            payload.update({"glue": glue, "fuzzy_mm": fz, "k": float(k)})
            tag = (
                f"ocp_noclip_batch64_g{glue}_f{str(fz).replace('.', 'p')}"
            )
            attempts.append(
                (tag, array_noclip_batch_job, payload, float(attempt_timeout_s))
            )

    def _append_scale_batch(
        specs: tuple[tuple[float, str, float], ...] = (
            (1.005, "shift", 0.1),
            (1.02, "shift", 0.1),
        ),
    ) -> None:
        for sc, glue, fz in specs:
            payload = dict(base)
            payload.update(
                {"scale": sc, "glue": glue, "fuzzy_mm": fz, "k": float(k)}
            )
            tag = (
                f"ocp_scale{str(sc).replace('.', 'p')}"
                f"_batch64_g{glue}_f{str(fz).replace('.', 'p')}"
            )
            attempts.append(
                (tag, array_scale_batch_job, payload, float(attempt_timeout_s))
            )

    # Q=1/1.5 hybrid seeds: one-shot noclip batch64 first (2026-07-18 proven on
    # af2q1_deq2_k1). Layered row/slab/zcopy destroys orthogonal contacts.
    if backend == "ocp" and hard_q and not thin_rod:
        _append_noclip_batch((("shift", 0.1), ("off", 0.1)))
        # When raw place has no volume overlap (e.g. af2q1p5): scale then batch64.
        _append_scale_batch(
            (
                (1.005, "shift", 0.1),
                (1.02, "shift", 0.1),
            )
        )

    # Ellipse (incl. Q=0.5 κ=2): noclip first when seed has face mating
    # (2026-07-19 af2q0p5_deq2_k2 both_end+ext=3 → single-solid 444).
    if backend == "ocp" and ellipse and not hard_q:
        _append_noclip_batch((("shift", 0.1), ("off", 0.1)))
        _append_scale_batch(
            (
                (1.005, "shift", 0.1),
                (1.02, "shift", 0.1),
            )
        )

    # Ellipse / ordinary OCP circle: seed_scale_zcopy (iz0 fuse + Z-copy).
    # Q=1/1.5 hybrid seeds often fail seed_scale (16 vols left); try only 1–2
    # scales then rely on noclip OCP (paper-box overhang overlap) earlier below.
    if ellipse or (backend == "ocp" and not thin_rod):
        if hard_q:
            _append_seed_scale_zcopy(
                (
                    (1.005, "off", 0.1),
                    (1.02, "off", 0.1),
                )
            )
        else:
            _append_seed_scale_zcopy(SEED_SCALE_ZCOPY_SPECS_DEFAULT)

    if backend == "ocp":
        # (mode, row_glue, row_fz, inter_glue, inter_fz, clip, overlap)
        # clip=False keeps paper-box overhangs so neighbours volume-overlap.
        # Prefer noclip early for Q≈1 (2026-07-17: seed_scale often fails on
        # centre_stub_corner_ext seeds; overhang fuse is the paper_box principle).
        ocp_specs: list[tuple[str, str, float, str, float, bool, float]] = [
            (ocp_mode, "shift", 0.20, "shift", 0.20, False, 0.0),
            (ocp_mode, "off", 0.20, "shift", 0.20, False, 0.0),
            (ocp_mode, "full", 0.05, "shift", 0.05, True, 0.02),
            (ocp_mode, "shift", 0.05, "shift", 0.05, True, 0.02),
            (ocp_mode, "shift", 0.10, "shift", 0.10, True, 0.1),
            ("hierarchical_batch", "shift", 0.10, "shift", 0.10, False, 0.1),
            (ocp_mode, "shift", 0.40, "shift", 0.20, True, 0.2),
        ]
        if thin_rod:
            # Face-mate seed (corner_ext=1.5) → noclip first (2026-07-19).
            # deep_pad remains fallback if seed still has no pitch=L contact.
            _append_noclip_batch((("shift", 0.1), ("off", 0.1)))
            _append_scale_batch(
                (
                    (1.005, "shift", 0.1),
                    (1.02, "shift", 0.1),
                )
            )
            for pad, glue, fz in DEEP_PAD_SPECS_THIN_ROD:
                payload = dict(base)
                payload.update(
                    {
                        "pad_mm": pad,
                        "glue": glue,
                        "fuzzy_mm": fz,
                        "cell_fuzzy_mm": 0.1,
                        "k": float(k),
                    }
                )
                tag = (
                    f"ocp_deep_pad{str(pad).replace('.', 'p')}"
                    f"_g{glue}_f{str(fz).replace('.', 'p')}"
                )
                attempts.append(
                    (tag, array_deep_pad_job, payload, float(attempt_timeout_s))
                )
            _append_seed_scale_zcopy(SEED_SCALE_ZCOPY_SPECS_THIN_ROD)
            ocp_specs = [
                # Fallback: no clip (overhang fuse) then expanded clip box.
                (ocp_mode, "shift", 0.05, "shift", 0.05, False, 0.0),
                (ocp_mode, "shift", 0.10, "shift", 0.10, False, 0.0),
                (ocp_mode, "off", 0.20, "shift", 0.20, False, 0.0),
                (ocp_mode, "shift", 0.10, "shift", 0.10, True, 0.2),
                (ocp_mode, "shift", 0.20, "shift", 0.20, True, 0.4),
                (ocp_mode, "off", 0.40, "off", 0.40, True, 0.5),
                ("hierarchical_batch", "shift", 0.20, "shift", 0.20, False, 0.0),
                ("hierarchical_batch", "shift", 0.40, "shift", 0.40, True, 0.4),
                (ocp_mode, "full", 0.20, "shift", 0.20, False, 0.0),
            ]
        for mode, row_g, row_fz, inter_g, inter_fz, do_clip, ov in ocp_specs:
            payload = dict(base)
            payload.update(
                {
                    "inter_cell_fuse_mode": mode,
                    "row_glue": row_g,
                    "row_fuzzy_mm": row_fz,
                    "inter_row_glue": inter_g,
                    "inter_row_fuzzy_mm": inter_fz,
                    "clip_to_periodic_box": do_clip,
                    "periodic_overlap_mm": ov,
                }
            )
            clip_tag = "clip" if do_clip else "noclip"
            ov_tag = f"ov{str(ov).replace('.', 'p')}" if do_clip else "ov0"
            tag = (
                f"ocp_{mode}_row{row_g}{str(row_fz).replace('.', 'p')}"
                f"_inter{inter_g}{str(inter_fz).replace('.', 'p')}"
                f"_{clip_tag}_{ov_tag}"
            )
            attempts.append((tag, array_ocp_job, payload, float(attempt_timeout_s)))
        if float(k) <= 1.0 + 1e-9:
            payload = dict(base)
            payload["force"] = True
            payload["fuse_strategy"] = "row_sequential"
            attempts.append(
                ("gmsh_fallback", array_gmsh_job, payload, float(attempt_timeout_s))
            )
    else:
        payload = dict(base)
        payload["force"] = force
        payload["fuse_strategy"] = "row_sequential"
        attempts.append(("gmsh", array_gmsh_job, payload, float(attempt_timeout_s)))

    errors: list[str] = []
    report: dict[str, Any] | None = None
    used = ""
    for label, job_fn, payload, t_budget in attempts:
        print(f"  444 try: {label} (timeout={t_budget:.0f}s)", flush=True)
        try:
            if os.path.isfile(work_array):
                os.remove(work_array)
            for name in list(os.listdir(work_dir)):
                p = os.path.join(work_dir, name)
                if name.startswith("zslab_") and os.path.isfile(p):
                    os.remove(p)
            cells_dir = os.path.join(work_dir, ".work_zslab_cells")
            if os.path.isdir(cells_dir):
                shutil.rmtree(cells_dir, ignore_errors=True)
            report = run_with_timeout(
                job_fn,
                payload,
                timeout_s=t_budget,
                label=label,
            )
            report = dict(report or {})

            # NFS / spawn: child may return before parent sees the STEP; retry briefly.
            ready = False
            for _ in range(10):
                if os.path.isfile(work_array) and os.path.getsize(work_array) > 1_000_000:
                    ready = True
                    break
                alt = str(report.get("array_step") or "")
                if alt and alt != work_array and os.path.isfile(alt) and os.path.getsize(alt) > 1_000_000:
                    shutil.copy2(alt, work_array)
                    ready = True
                    break
                time.sleep(0.5)
            if not ready:
                msg = (
                    f"{label}: no usable array STEP "
                    f"(work={work_array!r} exists={os.path.isfile(work_array)} "
                    f"size={os.path.getsize(work_array) if os.path.isfile(work_array) else 0} "
                    f"report_step={report.get('array_step')!r})"
                )
                errors.append(msg)
                print(f"    FAIL {msg}", flush=True)
                continue

            # Gate with gmsh volume_count==1 (same as QC). OCP-only solids=1 can
            # disagree with STEP/gmsh (seen: af2q0p5_deq2_k2 OCP=1, gmsh=2).
            # Jobs that already gmsh-verified (seed_scale_zcopy) may skip re-measure.
            rep_n = report.get("array_solids")
            if rep_n is None:
                rep_n = report.get("fused_volume_count")
            rep_mass = report.get("array_mass")
            gmsh_verified = bool(report.get("gmsh_verified"))
            if (
                gmsh_verified
                and rep_n is not None
                and int(rep_n) == 1
                and float(rep_mass or 0.0) > 0.0
            ):
                print(
                    f"    ACCEPT {label}: gmsh-verified solids=1 "
                    f"mass={float(rep_mass):.1f}",
                    flush=True,
                )
                used = label
                break

            try:
                stats = measure_step_occ_stats(work_array)
                nvol = int(stats.get("volume_count") or 0)
                mass = float(stats.get("mass_mm3") or 0.0)
            except Exception as exc:
                errors.append(f"{label}: OCC measure failed: {exc}")
                print(f"    FAIL {label}: OCC measure failed: {exc}", flush=True)
                continue
            if nvol != 1 or mass <= 0.0:
                errors.append(
                    f"{label}: reject array (volume_count={nvol}, mass={mass:.1f})"
                )
                print(
                    f"    FAIL {label}: volume_count={nvol} mass={mass:.1f} (want 1 solid)",
                    flush=True,
                )
                continue
            used = label
            print(f"    ACCEPT {label}: volume_count=1 mass={mass:.1f}", flush=True)
            break
        except AttemptTimeoutError as exc:
            errors.append(str(exc))
            print(f"    TIMEOUT {label}: {exc}", flush=True)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            print(f"    FAIL {label}: {exc}", flush=True)

    if not used or report is None or not os.path.isfile(work_array):
        raise RuntimeError("array fuse failed:\n  - " + "\n  - ".join(errors))
    shutil.copy2(work_array, array_step)
    out = dict(report or {})
    out["path"] = array_step
    out["backend"] = used
    out["Af"] = float(Af)
    return out


def _post_heal_444_structure_preserving(
    *,
    array_step: str,
    case_dir: str,
    case_id: str,
) -> dict[str, Any]:
    """Gmsh OCC heal after 444 write; replace STEP only if mass gate passes.

    Accepted heal cleans CAD topology (sew / tiny edges) without changing lattice
    design (Af/Q/deq/k). Typical accepted mass_ratio ≈ 1.00. Rejected presets keep
    the original ``*_444.step`` unchanged.
    """
    from src.export.step_heal_for_cae import heal_step_for_cae

    heal_dir = os.path.join(case_dir, ".work", "heal_444")
    os.makedirs(heal_dir, exist_ok=True)
    report_path = os.path.join(case_dir, f"{case_id}_444_heal.json")
    print(
        f"  [{case_id}] post-heal 444 (structure-preserving, mass_ratio∈[0.95,1.05])…",
        flush=True,
    )
    try:
        healed, rep = heal_step_for_cae(
            array_step,
            heal_dir,
            basename=f"{case_id}_444",
            mass_ratio_min=0.95,
            mass_ratio_max=1.05,
            stop_on_first_ok=True,
        )
    except Exception as exc:
        print(f"  [{case_id}] post-heal ERROR (keep original): {exc}", flush=True)
        rep = {"used_heal": False, "error": str(exc), "source_step": array_step}
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
        return {
            "used_heal": False,
            "kept_original": True,
            "error": str(exc),
            "report_path": report_path,
        }

    used = bool(rep.get("used_heal")) and bool(healed) and os.path.isfile(healed)
    if used and os.path.abspath(healed) != os.path.abspath(array_step):
        shutil.copy2(healed, array_step)
        print(
            f"  [{case_id}] post-heal ACCEPTED preset={rep.get('preset')} "
            f"mass_ratio={float(rep.get('mass_ratio') or 0):.4f} → replaced _444.step",
            flush=True,
        )
    else:
        print(
            f"  [{case_id}] post-heal KEEP original "
            f"(no preset passed mass/solid gate)",
            flush=True,
        )
        used = False

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    return {
        "used_heal": used,
        "kept_original": not used,
        "preset": rep.get("preset"),
        "mass_ratio": rep.get("mass_ratio"),
        "report_path": report_path,
    }


def _process_case(
    *,
    case_id: str,
    index_i: int,
    n_total: int,
    meta: dict[str, Any],
    batch_root: str,
    force: bool,
    array_only: bool,
    strut_only: bool,
    tol_rel: float,
    unitcell_timeout_s: float,
    array_timeout_s: float,
    post_heal: bool = True,
) -> dict[str, Any]:
    """Run one case end-to-end (safe to call from a worker thread)."""
    Af = float(meta["Af"])
    Q = float(meta["Q"])
    deq = float(meta["deq_mm"])
    k = float(meta["k"])
    case_dir = os.path.join(batch_root, case_id)
    work_dir = os.path.join(case_dir, ".work")
    unit_step = os.path.join(case_dir, f"{case_id}_1x1.step")
    strut_step = os.path.join(case_dir, f"{case_id}_strut1.step")
    array_step = os.path.join(case_dir, f"{case_id}_444.step")
    qc_path = os.path.join(case_dir, f"{case_id}_qc.json")
    os.makedirs(case_dir, exist_ok=True)

    print(f"\n######## [{index_i}/{n_total}] {case_id} ########", flush=True)
    t0 = time.time()
    entry: dict[str, Any] = {
        "case_id": case_id,
        "Af": Af,
        "Q": Q,
        "deq_mm": deq,
        "k": k,
        "unit_step": unit_step,
        "strut_step": strut_step,
        "array_step": array_step,
    }
    try:
        if strut_only:
            s_rep = _export_strut1(
                out_step=strut_step,
                Af=Af,
                Q=Q,
                deq_mm=deq,
                k=k,
                force=bool(force),
                attempt_timeout_s=float(unitcell_timeout_s),
            )
            entry["strut_report"] = {
                "skipped": bool(s_rep.get("skipped")),
                "ok": bool(s_rep.get("ok")),
                "method": s_rep.get("method"),
                "cut_mass_mm3": s_rep.get("cut_mass_mm3"),
                "raw_path": s_rep.get("raw_path"),
                "raw_ok": s_rep.get("raw_ok"),
                "error": s_rep.get("error"),
                "attempt_seconds": s_rep.get("attempt_seconds"),
            }
            entry["status"] = "ok" if s_rep.get("ok") else "strut_fail"
            prev: dict[str, Any] = {}
            if os.path.isfile(qc_path):
                try:
                    with open(qc_path, encoding="utf-8") as f:
                        prev = json.load(f)
                except Exception:
                    prev = {}
            prev.update(
                {
                    "strut_step": strut_step,
                    "strut_raw_step": _strut1_raw_path(strut_step),
                    "strut_report": entry["strut_report"],
                }
            )
            if "case_id" not in prev:
                prev["case_id"] = case_id
            with open(qc_path, "w", encoding="utf-8") as f:
                json.dump(prev, f, indent=2, ensure_ascii=False)
        else:
            u_force = bool(force) and not bool(array_only)
            a_force = bool(force) or bool(array_only)
            u_rep = _export_unitcell(
                out_step=unit_step,
                Af=Af,
                Q=Q,
                deq_mm=deq,
                k=k,
                force=u_force,
                attempt_timeout_s=float(unitcell_timeout_s),
            )
            entry["unitcell_report"] = {
                "skipped": bool(u_rep.get("skipped")),
                "seed_method": u_rep.get("seed_method"),
                "attempt_seconds": u_rep.get("attempt_seconds"),
            }
            s_rep = _export_strut1(
                out_step=strut_step,
                Af=Af,
                Q=Q,
                deq_mm=deq,
                k=k,
                force=u_force,
                attempt_timeout_s=float(unitcell_timeout_s),
            )
            entry["strut_report"] = {
                "skipped": bool(s_rep.get("skipped")),
                "ok": bool(s_rep.get("ok")),
                "method": s_rep.get("method"),
                "cut_mass_mm3": s_rep.get("cut_mass_mm3"),
                "raw_path": s_rep.get("raw_path"),
                "raw_ok": s_rep.get("raw_ok"),
                "error": s_rep.get("error"),
                "attempt_seconds": s_rep.get("attempt_seconds"),
            }
            a_rep = _export_array(
                seed_step=unit_step,
                array_step=array_step,
                work_dir=work_dir,
                Af=Af,
                Q=Q,
                k=k,
                deq_mm=deq,
                force=a_force,
                attempt_timeout_s=float(array_timeout_s),
            )
            entry["array_report"] = {
                "skipped": bool(a_rep.get("skipped")),
                "backend": a_rep.get("backend"),
                "fused_volume_count": (a_rep.get("array_merge") or {}).get(
                    "fused_volume_count"
                )
                if isinstance(a_rep.get("array_merge"), dict)
                else a_rep.get("fused_volume_count"),
            }
            if post_heal and os.path.isfile(array_step):
                entry["array_heal"] = _post_heal_444_structure_preserving(
                    array_step=array_step,
                    case_dir=case_dir,
                    case_id=case_id,
                )
            else:
                entry["array_heal"] = {
                    "used_heal": False,
                    "kept_original": True,
                    "skipped": True,
                    "reason": "post_heal disabled",
                }
            qc = _qc_pair(unit_step, array_step, tol_rel=float(tol_rel))
            entry["qc"] = qc
            if qc["ok"]:
                entry["status"] = "ok"
                print(
                    f"  [{case_id}] QC PASS ratio={qc['volume_ratio']:.3f} "
                    f"(target 64 ±{100 * float(tol_rel):.0f}%)",
                    flush=True,
                )
            else:
                entry["status"] = "qc_fail"
                print(
                    f"  [{case_id}] QC FAIL ratio={qc.get('volume_ratio')} "
                    f"vols=({qc['unitcell'].get('volume_count')},"
                    f"{qc['array'].get('volume_count')})",
                    flush=True,
                )
            with open(qc_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"case_id": case_id, **entry},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)
        entry["traceback"] = traceback.format_exc()
        print(f"  [{case_id}] ERROR: {exc}", flush=True)
        if not strut_only:
            with open(qc_path, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2, ensure_ascii=False)
    entry["elapsed_s"] = round(time.time() - t0, 1)
    return entry


def _load_index(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Batch 1x1 + 444 STEP into 批量构型/ (with per-strategy timeouts)"
    )
    p.add_argument("--index", default=DEFAULT_INDEX)
    p.add_argument("--only", nargs="*", default=[], help="Only these case ids")
    p.add_argument("--force", action="store_true")
    p.add_argument(
        "--repair",
        action="store_true",
        help="Scan QC; only FORCE-regenerate cases that are missing or failed",
    )
    p.add_argument(
        "--array-only",
        action="store_true",
        help="Keep existing 1x1 seed; only (re)build 444 + QC",
    )
    p.add_argument(
        "--strut-only",
        action="store_true",
        help="Only (re)build strut1 STEP; keep existing 1x1 / 444",
    )
    p.add_argument("--tol-rel", type=float, default=VOL_TOL_REL)
    p.add_argument(
        "--unitcell-attempt-timeout",
        type=float,
        default=DEFAULT_UNITCELL_ATTEMPT_TIMEOUT_S,
        help="Wall-clock seconds per 1x1 strategy before kill+next (default 600)",
    )
    p.add_argument(
        "--array-attempt-timeout",
        type=float,
        default=DEFAULT_ARRAY_ATTEMPT_TIMEOUT_S,
        help="Wall-clock seconds per 444 strategy before kill+next (default 5400)",
    )
    p.add_argument(
        "--no-post-heal",
        action="store_true",
        help="Skip structure-preserving Gmsh heal after 444 write "
        "(default: heal and replace only if mass_ratio∈[0.95,1.05])",
    )
    p.add_argument(
        "--check-only",
        action="store_true",
        help="Only print per-case status / needs_repair; do not generate",
    )
    p.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="Abort batch on first case failure (default: continue)",
    )
    p.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Case-level parallelism (default 1). Use 2 while Abaqus is busy; 3+ if CAD-only.",
    )
    args = p.parse_args()

    index_path = os.path.abspath(args.index)
    if not os.path.isfile(index_path):
        raise SystemExit(f"[FAIL] missing index: {index_path}")
    index = _load_index(index_path)
    batch_root = os.path.dirname(index_path)
    order = list(index.get("generation_order") or [])
    cases = dict(index.get("cases") or {})
    only = set(args.only or [])
    if only:
        order = [c for c in order if c in only]

    # Status scan (always useful; required for --repair / --check-only).
    # --force regenerates anyway: use light scan (qc.json + sizes), skip gmsh
    # pre-measure of huge 444 STEPs which can stall minutes before Cases: prints.
    statuses: list[dict[str, Any]] = []
    for case_id in order:
        case_dir = os.path.join(batch_root, case_id)
        os.makedirs(case_dir, exist_ok=True)
        st = _case_status(
            case_dir,
            case_id,
            tol_rel=float(args.tol_rel),
            light=bool(args.check_only or args.repair or args.force),
        )
        statuses.append(st)
        mark = "NEEDS_REPAIR" if st["needs_repair"] else "OK"
        print(
            f"  [{mark}] {case_id}: unit={st.get('unit_ok', st.get('unit_exists'))} "
            f"array={st['array_exists']} qc={st['qc_ok']} ratio={st.get('volume_ratio')}",
            flush=True,
        )

    status_path = os.path.join(batch_root, "_batch_status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "tol_rel": float(args.tol_rel),
                "cases": statuses,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"Status: {status_path}", flush=True)

    if args.check_only:
        n_bad = sum(1 for s in statuses if s["needs_repair"])
        return 0 if n_bad == 0 else 1

    if args.repair and not args.strut_only:
        order = [s["case_id"] for s in statuses if s["needs_repair"]]
        args.force = True
        print(
            f"Repair mode: {len(order)} case(s) to regenerate with --force",
            flush=True,
        )
        if not order:
            print("Nothing to repair.", flush=True)
            return 0

    if args.strut_only:
        print("Strut-only mode: keep existing 1x1 / 444; (re)build strut1", flush=True)

    summary_path = os.path.join(batch_root, "_batch_run_summary.json")
    results: list[dict[str, Any]] = []
    n_jobs = max(1, int(args.jobs))

    print(f"Batch root: {batch_root}", flush=True)
    print(f"Cases: {len(order)}  jobs={n_jobs}", flush=True)
    print(
        f"Timeouts: 1x1={float(args.unitcell_attempt_timeout):.0f}s "
        f"444={float(args.array_attempt_timeout):.0f}s",
        flush=True,
    )

    summary_lock = threading.Lock()

    def _record(entry: dict[str, Any]) -> None:
        with summary_lock:
            results.append(entry)
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "jobs": n_jobs,
                        "results": results,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

    def _submit_kwargs(case_id: str, index_i: int) -> dict[str, Any]:
        # Env BATCH_STEP_POST_HEAL=0 also disables (shell wrapper).
        env_off = os.environ.get("BATCH_STEP_POST_HEAL", "1").strip() in (
            "0",
            "false",
            "False",
            "no",
            "NO",
        )
        return {
            "case_id": case_id,
            "index_i": index_i,
            "n_total": len(order),
            "meta": cases.get(case_id) or {},
            "batch_root": batch_root,
            "force": bool(args.force),
            "array_only": bool(args.array_only),
            "strut_only": bool(args.strut_only),
            "tol_rel": float(args.tol_rel),
            "unitcell_timeout_s": float(args.unitcell_attempt_timeout),
            "array_timeout_s": float(args.array_attempt_timeout),
            "post_heal": (not bool(args.no_post_heal)) and (not env_off),
        }

    if n_jobs <= 1:
        for i, case_id in enumerate(order, start=1):
            entry = _process_case(**_submit_kwargs(case_id, i))
            _record(entry)
            if args.stop_on_fail and entry.get("status") in ("qc_fail", "error", "strut_fail"):
                break
    else:
        # Thread pool: each case already spawns timeout child processes for OCC/gmsh.
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_jobs) as pool:
            futures = {
                pool.submit(_process_case, **_submit_kwargs(cid, i)): cid
                for i, cid in enumerate(order, start=1)
            }
            abort = False
            for fut in concurrent.futures.as_completed(futures):
                cid = futures[fut]
                try:
                    entry = fut.result()
                except Exception as exc:
                    entry = {
                        "case_id": cid,
                        "status": "error",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    print(f"  [{cid}] ERROR (worker): {exc}", flush=True)
                _record(entry)
                if args.stop_on_fail and entry.get("status") in (
                    "qc_fail",
                    "error",
                    "strut_fail",
                ):
                    abort = True
                    for pending in futures:
                        pending.cancel()
                    break
            if abort:
                print("stop-on-fail: cancelling remaining case submissions", flush=True)

    n_ok = sum(1 for r in results if r.get("status") == "ok")
    n_fail = len(results) - n_ok
    print(
        f"\n=== Done: {n_ok} ok / {n_fail} fail-or-error / {len(order)} planned "
        f"(jobs={n_jobs}) ===",
        flush=True,
    )
    print(f"Summary: {summary_path}", flush=True)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    # Required for Windows / spawn multiprocessing of strategy attempts.
    raise SystemExit(main())
