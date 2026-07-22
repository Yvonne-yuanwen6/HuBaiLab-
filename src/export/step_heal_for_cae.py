"""Gmsh OCC (+ optional OCP ShapeFix) heal for verified STEP before Abaqus CAE tet mesh.

repair_version 3 — structure-preserving (合验一致):
  Prefer verified raw / light sew; reject repairs that change mass, bbox, or face
  count beyond tight gates. Avoid UnifySameDomain unless explicitly allowed.
"""

from __future__ import annotations

import os
import time
from typing import Any

from src.export.sw_parasolid import measure_step_occ_stats
from src.export.timed_attempt import AttemptTimeoutError, run_with_timeout

# Bump when pre-mesh repair pipeline changes so failed old reports do not skip re-heal.
REPAIR_VERSION = 3

# Order: light sew first; destructive fix_small last.
HEAL_PRESETS: tuple[dict[str, Any], ...] = (
    {"label": "tol0.05", "distance_tol": 0.05, "fix_small": False},
    {"label": "tol0.10", "distance_tol": 0.10, "fix_small": False},
    {"label": "tol0.05_fixsmall", "distance_tol": 0.05, "fix_small": True},
    {"label": "tol0.10_fixsmall", "distance_tol": 0.10, "fix_small": True},
    {"label": "tol0.01_fixsmall", "distance_tol": 0.01, "fix_small": True},
)

DEFAULT_HEAL_TIMEOUT_S = float(os.environ.get("BATCH_HEAL_TIMEOUT_S", "2400") or 2400)
DEFAULT_HEAL_PRESET_TIMEOUT_S = float(
    os.environ.get("BATCH_HEAL_PRESET_TIMEOUT_S", "900") or 900
)

# Structure gates vs verified / source STEP (合验外形).
DEFAULT_MASS_RATIO_MIN = float(os.environ.get("BATCH_HEAL_MASS_MIN", "0.98") or 0.98)
DEFAULT_MASS_RATIO_MAX = float(os.environ.get("BATCH_HEAL_MASS_MAX", "1.02") or 1.02)
DEFAULT_FACE_RATIO_MIN = float(os.environ.get("BATCH_HEAL_FACE_MIN", "0.92") or 0.92)
DEFAULT_FACE_RATIO_MAX = float(os.environ.get("BATCH_HEAL_FACE_MAX", "1.08") or 1.08)
DEFAULT_BBOX_RATIO_MIN = float(os.environ.get("BATCH_HEAL_BBOX_MIN", "0.995") or 0.995)
DEFAULT_BBOX_RATIO_MAX = float(os.environ.get("BATCH_HEAL_BBOX_MAX", "1.005") or 1.005)


def structure_gate(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    mass_ratio_min: float = DEFAULT_MASS_RATIO_MIN,
    mass_ratio_max: float = DEFAULT_MASS_RATIO_MAX,
    face_ratio_min: float = DEFAULT_FACE_RATIO_MIN,
    face_ratio_max: float = DEFAULT_FACE_RATIO_MAX,
    bbox_ratio_min: float = DEFAULT_BBOX_RATIO_MIN,
    bbox_ratio_max: float = DEFAULT_BBOX_RATIO_MAX,
) -> tuple[bool, str, dict[str, float]]:
    """Return (ok, reason, metrics). Reject topology/shape drift vs source."""
    ref_mass = float(before.get("mass_mm3") or 0.0)
    out_mass = float(after.get("mass_mm3") or 0.0)
    mass_ratio = (out_mass / ref_mass) if ref_mass > 1e-9 else 1.0

    ref_faces = float(before.get("face_count") or 0.0)
    out_faces = float(after.get("face_count") or 0.0)
    face_ratio = (out_faces / ref_faces) if ref_faces > 0.5 else 1.0

    ref_z = float(before.get("bbox_z_span_mm") or 0.0)
    out_z = float(after.get("bbox_z_span_mm") or 0.0)
    z_ratio = (out_z / ref_z) if ref_z > 1e-9 else 1.0

    metrics = {
        "mass_ratio": mass_ratio,
        "face_ratio": face_ratio,
        "bbox_z_ratio": z_ratio,
    }

    if not (mass_ratio_min <= mass_ratio <= mass_ratio_max):
        return (
            False,
            f"mass_ratio={mass_ratio:.6f} out of [{mass_ratio_min},{mass_ratio_max}]",
            metrics,
        )
    if ref_faces > 0.5 and not (face_ratio_min <= face_ratio <= face_ratio_max):
        return (
            False,
            f"face_ratio={face_ratio:.4f} out of [{face_ratio_min},{face_ratio_max}] "
            f"(faces {int(ref_faces)}→{int(out_faces)}; rejects UnifySameDomain collapse)",
            metrics,
        )
    if ref_z > 1e-6 and not (bbox_ratio_min <= z_ratio <= bbox_ratio_max):
        return (
            False,
            f"bbox_z_ratio={z_ratio:.6f} out of [{bbox_ratio_min},{bbox_ratio_max}]",
            metrics,
        )

    bb0 = before.get("bbox_mm") or {}
    bb1 = after.get("bbox_mm") or {}
    if bb0 and bb1 and ref_z > 1e-6:
        max_shift = 0.0
        for ax in ("x", "y", "z"):
            a0, b0 = bb0.get(ax) or [0.0, 0.0]
            a1, b1 = bb1.get(ax) or [0.0, 0.0]
            max_shift = max(
                max_shift,
                abs(float(a1) - float(a0)),
                abs(float(b1) - float(b0)),
            )
        metrics["bbox_corner_shift_mm"] = max_shift
        if max_shift > 0.05 * ref_z:
            return False, f"bbox_corner_shift={max_shift:.4f} mm too large", metrics

    return True, "ok", metrics


def _fuse_to_one_volume() -> int:
    import gmsh

    vols = gmsh.model.getEntities(3)
    if len(vols) <= 1:
        return len(vols)
    tags = [t[1] for t in vols]
    gmsh.model.occ.fuse([(3, tags[0])], [(3, t) for t in tags[1:]])
    gmsh.model.occ.synchronize()
    return len(gmsh.model.getEntities(3))


def heal_step_once(
    in_step: str,
    out_step: str,
    *,
    distance_tol: float = 0.05,
    fix_small: bool = True,
) -> dict[str, Any]:
    import gmsh

    in_step = os.path.abspath(in_step)
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    before = measure_step_occ_stats(in_step)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("heal_cae")
        gmsh.model.occ.importShapes(in_step)
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise RuntimeError(f"no 3D volume in {in_step}")

        n_before_heal = _fuse_to_one_volume()
        if n_before_heal < 1:
            raise RuntimeError(f"no 3D volume after pre-fuse in {in_step}")

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

        n_vol = _fuse_to_one_volume()
        if n_vol != 1:
            raise RuntimeError(f"expected 1 volume after heal, got {n_vol}")

        gmsh.write(out_step)
    finally:
        gmsh.finalize()

    after = measure_step_occ_stats(out_step)
    ref_mass = float(before.get("mass_mm3") or 0.0)
    out_mass = float(after.get("mass_mm3") or 0.0)
    mass_ratio = (out_mass / ref_mass) if ref_mass > 1e-9 else 1.0
    return {
        "before": before,
        "after": after,
        "out_step": out_step,
        "mass_ratio": mass_ratio,
        "distance_tol": float(distance_tol),
        "fix_small": bool(fix_small),
    }


def ocp_pre_repair_step(
    in_step: str,
    out_step: str,
    *,
    heal_mm: float = 0.05,
    unify_same_domain: bool = False,
    skip_gmsh_heal: bool = True,
) -> dict[str, Any]:
    """OCP ShapeFix (+ optional Unify), BREP→gmsh STEP. Default: no Unify, no healShapes."""
    from OCP.STEPControl import STEPControl_Reader
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    from src.export.ocp_unitcell_fuse import ocp_write_step_via_gmsh_brep_heal

    in_step = os.path.abspath(in_step)
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    before = measure_step_occ_stats(in_step)
    reader = STEPControl_Reader()
    if reader.ReadFile(in_step) != 1:
        raise RuntimeError(f"OCP STEP read failed: {in_step}")
    reader.TransferRoots()
    shape = reader.OneShape()

    n_solids = 0
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        n_solids += 1
        exp.Next()
    if n_solids < 1:
        raise RuntimeError(f"OCP pre-repair: no solid in {in_step}")

    work = shape
    if unify_same_domain:
        unified = ShapeUpgrade_UnifySameDomain(work, True, True, True)
        unified.Build()
        work = unified.Shape()
    fixed = ShapeFix_Shape(work)
    fixed.Perform()
    work = fixed.Shape()

    readback = ocp_write_step_via_gmsh_brep_heal(
        work,
        out_step,
        heal_mm=float(heal_mm),
        fast_readback=True,
        skip_gmsh_heal=bool(skip_gmsh_heal),
    )
    after = measure_step_occ_stats(out_step)
    ref_mass = float(before.get("mass_mm3") or 0.0)
    out_mass = float(after.get("mass_mm3") or 0.0)
    mass_ratio = (out_mass / ref_mass) if ref_mass > 1e-9 else 1.0
    label = "ocp_shapefix"
    if unify_same_domain:
        label += "_unify"
    label += "_noglmh" if skip_gmsh_heal else "_gmsh"
    return {
        "preset": label,
        "before": before,
        "after": after,
        "out_step": out_step,
        "mass_ratio": mass_ratio,
        "n_solids_in": n_solids,
        "export_route": readback.get("export_route"),
        "heal_mm": readback.get("heal_mm"),
        "unify_same_domain": bool(unify_same_domain),
        "skip_gmsh_heal": bool(skip_gmsh_heal),
    }


def _spawn_failed_without_result(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "child exited with code" in msg
        or "without returning a result" in msg
        or "no result" in msg
    )


def _run_heal_preset(
    *,
    in_step: str,
    out_step: str,
    distance_tol: float,
    fix_small: bool,
    this_budget: float,
    preset_timeout_s: float,
    label: str,
) -> dict[str, Any]:
    if this_budget > 0 and preset_timeout_s > 0:
        try:
            return run_with_timeout(
                heal_step_once,
                in_step,
                out_step,
                timeout_s=this_budget,
                label=f"heal:{label}",
                distance_tol=float(distance_tol),
                fix_small=bool(fix_small),
            )
        except AttemptTimeoutError:
            raise
        except Exception as exc:
            if not _spawn_failed_without_result(exc):
                raise
            print(
                f"  heal spawn-fail preset={label}: {exc} — retry in-process",
                flush=True,
            )
    return heal_step_once(
        in_step,
        out_step,
        distance_tol=float(distance_tol),
        fix_small=bool(fix_small),
    )


def heal_step_for_cae(
    in_step: str,
    out_dir: str,
    *,
    basename: str = "healed",
    presets: tuple[dict[str, Any], ...] | None = None,
    mass_ratio_min: float | None = None,
    mass_ratio_max: float | None = None,
    timeout_s: float | None = None,
    preset_timeout_s: float | None = None,
    stop_on_first_ok: bool = True,
    run_ocp_prerepair: bool | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Pre-mesh geometry repair; return (best_out_step, report).

    repair_version=3: keep 合验 raw unless a gated light repair passes
    mass/face/bbox gates. UnifySameDomain that collapses faces is rejected.
    """
    presets = presets or HEAL_PRESETS
    in_step = os.path.abspath(in_step)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    if timeout_s is None:
        timeout_s = DEFAULT_HEAL_TIMEOUT_S
    if preset_timeout_s is None:
        preset_timeout_s = DEFAULT_HEAL_PRESET_TIMEOUT_S
    if mass_ratio_min is None:
        mass_ratio_min = DEFAULT_MASS_RATIO_MIN
    if mass_ratio_max is None:
        mass_ratio_max = DEFAULT_MASS_RATIO_MAX
    timeout_s = float(timeout_s)
    preset_timeout_s = float(preset_timeout_s)

    if run_ocp_prerepair is None:
        env = os.environ.get("BATCH_HEAL_OCP_PREREPAIR", "1").strip().lower()
        run_ocp_prerepair = env not in ("0", "false", "no", "off")

    before = measure_step_occ_stats(in_step)
    best_path = in_step
    best_report: dict[str, Any] = {
        "source_step": in_step,
        "preset": "none",
        "before": before,
        "after": before,
        "attempts": [],
        "stop_on_first_ok": bool(stop_on_first_ok),
        "timeout_s": timeout_s,
        "preset_timeout_s": preset_timeout_s,
        "repair_version": REPAIR_VERSION,
        "ocp_prerepair": bool(run_ocp_prerepair),
        "structure_preserving": True,
        "gates": {
            "mass": [mass_ratio_min, mass_ratio_max],
            "face": [DEFAULT_FACE_RATIO_MIN, DEFAULT_FACE_RATIO_MAX],
            "bbox_z": [DEFAULT_BBOX_RATIO_MIN, DEFAULT_BBOX_RATIO_MAX],
        },
    }

    t0 = time.monotonic()
    timed_out = False

    def _budget_left() -> float:
        if timeout_s <= 0:
            return preset_timeout_s if preset_timeout_s > 0 else 1e9
        return max(0.0, timeout_s - (time.monotonic() - t0))

    def _accept(rep: dict[str, Any], out_step: str, label: str) -> bool:
        nonlocal best_path
        ok, reason, metrics = structure_gate(
            before,
            rep.get("after") or {},
            mass_ratio_min=float(mass_ratio_min),
            mass_ratio_max=float(mass_ratio_max),
        )
        rep["structure_ok"] = ok
        rep["structure_reason"] = reason
        rep["structure_metrics"] = metrics
        if ok:
            best_path = out_step
            best_report["preset"] = label
            best_report["after"] = rep["after"]
            best_report["mass_ratio"] = metrics["mass_ratio"]
            best_report["structure_metrics"] = metrics
            print(
                f"  heal OK preset={label} mass_ratio={metrics['mass_ratio']:.4f} "
                f"face_ratio={metrics['face_ratio']:.4f} "
                f"faces={rep['after'].get('face_count')} -> {out_step}",
                flush=True,
            )
            return True
        print(f"  heal reject preset={label}: {reason}", flush=True)
        return False

    def _try_ocp(*, label: str, unify: bool, skip_gmsh: bool) -> bool:
        if not run_ocp_prerepair or _budget_left() <= 1.0:
            return False
        out_step = os.path.join(out_dir, f"{basename}_{label}.step")
        this_budget = (
            min(preset_timeout_s, _budget_left())
            if timeout_s > 0
            else preset_timeout_s
        )
        try:
            print(
                f"  heal OCP ({label}: unify={unify} skip_gmsh_heal={skip_gmsh})…",
                flush=True,
            )
            kwargs = dict(
                heal_mm=0.05,
                unify_same_domain=unify,
                skip_gmsh_heal=skip_gmsh,
            )
            if this_budget > 0 and preset_timeout_s > 0:
                try:
                    rep = run_with_timeout(
                        ocp_pre_repair_step,
                        in_step,
                        out_step,
                        timeout_s=this_budget,
                        label=f"heal:{label}",
                        **kwargs,
                    )
                except AttemptTimeoutError:
                    raise
                except Exception as exc:
                    if _spawn_failed_without_result(exc):
                        print(
                            f"  heal spawn-fail preset={label}: {exc} — retry in-process",
                            flush=True,
                        )
                        rep = ocp_pre_repair_step(in_step, out_step, **kwargs)
                    else:
                        raise
            else:
                rep = ocp_pre_repair_step(in_step, out_step, **kwargs)
            rep["preset"] = label
            best_report["attempts"].append(rep)
            return _accept(rep, out_step, label)
        except AttemptTimeoutError as exc:
            print(f"  heal TIMEOUT preset={label}: {exc}", flush=True)
            best_report["attempts"].append(
                {"preset": label, "error": str(exc), "timeout": True}
            )
        except Exception as exc:
            print(f"  heal FAIL preset={label}: {exc}", flush=True)
            best_report["attempts"].append({"preset": label, "error": str(exc)})
        return False

    light_presets = [p for p in presets if not p.get("fix_small")]
    heavy_presets = [p for p in presets if p.get("fix_small")]

    for preset in light_presets:
        if _budget_left() <= 1.0 and timeout_s > 0:
            timed_out = True
            break
        this_budget = (
            min(preset_timeout_s, _budget_left()) if timeout_s > 0 else preset_timeout_s
        )
        if this_budget <= 1.0 and timeout_s > 0:
            timed_out = True
            break
        label = str(preset["label"])
        out_step = os.path.join(out_dir, f"{basename}_{label}.step")
        try:
            rep = _run_heal_preset(
                in_step=in_step,
                out_step=out_step,
                distance_tol=float(preset["distance_tol"]),
                fix_small=False,
                this_budget=this_budget,
                preset_timeout_s=preset_timeout_s,
                label=label,
            )
            rep["preset"] = label
            best_report["attempts"].append(rep)
            if _accept(rep, out_step, label) and stop_on_first_ok:
                best_report["healed_step"] = best_path
                best_report["used_heal"] = best_path != in_step
                best_report["timed_out"] = False
                best_report["elapsed_s"] = round(time.monotonic() - t0, 1)
                return best_path, best_report
        except AttemptTimeoutError as exc:
            print(f"  heal TIMEOUT preset={label}: {exc}", flush=True)
            best_report["attempts"].append(
                {"preset": label, "error": str(exc), "timeout": True}
            )
        except Exception as exc:
            print(f"  heal FAIL preset={label}: {exc}", flush=True)
            best_report["attempts"].append({"preset": label, "error": str(exc)})

    if _try_ocp(label="ocp_shapefix_noglmh", unify=False, skip_gmsh=True):
        if stop_on_first_ok:
            best_report["healed_step"] = best_path
            best_report["used_heal"] = best_path != in_step
            best_report["timed_out"] = False
            best_report["elapsed_s"] = round(time.monotonic() - t0, 1)
            return best_path, best_report

    for preset in heavy_presets:
        if _budget_left() <= 1.0 and timeout_s > 0:
            print(
                f"  heal TIMEOUT total budget={timeout_s:.0f}s "
                f"(elapsed≈{time.monotonic() - t0:.0f}s) — keep best so far",
                flush=True,
            )
            timed_out = True
            break
        this_budget = (
            min(preset_timeout_s, _budget_left()) if timeout_s > 0 else preset_timeout_s
        )
        if this_budget <= 1.0 and timeout_s > 0:
            timed_out = True
            break
        label = str(preset["label"])
        out_step = os.path.join(out_dir, f"{basename}_{label}.step")
        try:
            rep = _run_heal_preset(
                in_step=in_step,
                out_step=out_step,
                distance_tol=float(preset["distance_tol"]),
                fix_small=True,
                this_budget=this_budget,
                preset_timeout_s=preset_timeout_s,
                label=label,
            )
            rep["preset"] = label
            best_report["attempts"].append(rep)
            if _accept(rep, out_step, label) and stop_on_first_ok:
                break
        except AttemptTimeoutError as exc:
            print(f"  heal TIMEOUT preset={label}: {exc}", flush=True)
            best_report["attempts"].append(
                {"preset": label, "error": str(exc), "timeout": True}
            )
        except Exception as exc:
            print(f"  heal FAIL preset={label}: {exc}", flush=True)
            best_report["attempts"].append({"preset": label, "error": str(exc)})

    if best_path == in_step:
        _try_ocp(label="ocp_shapefix_unify_noglmh", unify=True, skip_gmsh=True)

    if best_path == in_step:
        print(
            "  heal KEEP verified raw STEP (no gated repair accepted — 合验原样)",
            flush=True,
        )
        best_report["preset"] = "verified_raw"
        best_report["kept_verified_raw"] = True

    best_report["healed_step"] = best_path
    best_report["used_heal"] = best_path != in_step
    best_report["timed_out"] = timed_out
    best_report["elapsed_s"] = round(time.monotonic() - t0, 1)
    return best_path, best_report


def cad_heal_report_path(case_id: str, batch_root: str | None = None) -> str:
    root = batch_root or os.path.join("output", "cad", "批量构型")
    return os.path.join(root, case_id, f"{case_id}_444_heal.json")


def should_skip_cae_heal(
    case_id: str,
    *,
    batch_root: str | None = None,
    verified_heal_dir: str | None = None,
) -> tuple[bool, str]:
    """Skip only when a current-version successful / decided heal report exists."""
    import json

    candidates: list[tuple[str, str]] = [
        (cad_heal_report_path(case_id, batch_root=batch_root), "CAD"),
    ]
    vdir = verified_heal_dir or os.path.join(
        "output", "cad", "verified", f"heal_{case_id}"
    )
    candidates.append((os.path.join(vdir, "heal_report.json"), "CAE"))

    for path, tag in candidates:
        if not os.path.isfile(path):
            continue
        try:
            rep = json.loads(open(path, encoding="utf-8").read())
        except Exception as exc:
            return False, f"unreadable {tag} heal report: {exc}"
        if bool(rep.get("skipped_cae_heal")) and tag == "CAE":
            continue
        ver = int(rep.get("repair_version") or 0)
        if ver > 0 and ver < REPAIR_VERSION:
            return (
                False,
                f"{tag} repair_version={ver}<{REPAIR_VERSION} — re-run structure heal",
            )
        if bool(rep.get("kept_verified_raw")) and ver >= REPAIR_VERSION:
            return True, f"{tag} kept_verified_raw (structure-preserving)"
        if bool(rep.get("used_heal")):
            mr = rep.get("mass_ratio")
            preset = rep.get("preset")
            return True, f"{tag} used_heal preset={preset} mass_ratio={mr}"
    return False, "no successful prior heal"
