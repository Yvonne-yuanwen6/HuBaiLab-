"""Merge manual z-slab STEPs in SolidWorks via COM (Windows + pywin32)."""

from __future__ import annotations

import json
import os
import time
from typing import Iterable

from src.export.sw_parasolid import (
    _connect_solidworks,
    _doc_title,
    discover_part_templates,
    solidworks_com_available,
)

swDocPART = 1
swBodySolid = 0
swCombineAdd = 0
swOpenDocOptions_Silent = 1
swSaveAsCurrentVersion = 0
swSaveAsOptions_Silent = 1
swDefaultTemplatePart = 2


def _layer_steps(manual_dir: str, *, nz: int = 4) -> list[str]:
    paths: list[str] = []
    for iz in range(nz):
        p = os.path.join(manual_dir, f"zslab_iz{iz}.step")
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Missing layer STEP: {p}")
        paths.append(os.path.abspath(p))
    return paths


def _body_count(model) -> int:
    bodies = model.GetBodies2(swBodySolid, True)
    if bodies is None:
        return 0
    try:
        return len(bodies)
    except TypeError:
        return 1


def _combine_all_bodies(model, *, label: str = "combine") -> int:
    bodies = model.GetBodies2(swBodySolid, True)
    if bodies is None:
        raise RuntimeError(f"{label}: no solid bodies found")
    try:
        n = len(bodies)
    except TypeError:
        return 1
    if n <= 1:
        return n

    print(f"  {label}: Combine → Add ({n} bodies)...", flush=True)
    bs = tuple(bodies)
    feat = model.FeatureManager.InsertCombineFeature(swCombineAdd, bs[0], tuple(bs[1:]))
    _rebuild(model)
    n_after = _body_count(model)
    if n_after == 1:
        return 1

    # SW COM Combine often leaves N bodies; fall back to gmsh in-memory fuse.
    print(f"  {label}: SW combine left {n_after} body(ies); gmsh fuse fallback...", flush=True)
    return n_after


def _gmsh_fuse_step_stack(step_paths: list[str], out_path: str, *, label: str = "gmsh-fuse") -> int:
    from src.export.export_sw import _merge_step_solids_in_memory

    report = _merge_step_solids_in_memory(step_paths, out_path, progress_label=label)
    return int(report.get("solid_count") or 0)


def _new_empty_part(sw_app, *, visible: bool = False):
    sw_app.Visible = bool(visible)
    last_err: Exception | None = None
    templates = discover_part_templates(sw_app)

    for template in templates:
        try:
            model = sw_app.NewDocument(template, 0, 0.0, 0.0)
            if model is not None:
                return model
            last_err = RuntimeError(f"NewDocument returned Nothing for template: {template}")
        except Exception as exc:
            last_err = exc

    tried = ", ".join(templates[:4]) if templates else "(none found)"
    raise RuntimeError(
        "SolidWorks NewDocument failed (no usable part template). "
        f"Tried: {tried}. Set a default part template in SW, or open a blank Part first."
    ) from last_err


def _open_document(sw_app, file_path: str, *, visible: bool = False):
    """Open STEP or SLDPRT without dialogs."""
    import pythoncom
    import win32com.client

    file_path = os.path.abspath(file_path)
    sw_app.Visible = bool(visible)
    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".sldprt", ".sldasm"):
        try:
            if sw_app.LoadFile2(file_path, "r"):
                model = sw_app.ActiveDoc
                if model is not None:
                    return model
        except Exception:
            pass
        for opts in (swOpenDocOptions_Silent, 0):
            try:
                model = sw_app.OpenDoc6(file_path, swDocPART, opts, "", errors, warnings)
                if model is not None:
                    return model
            except Exception:
                pass
        raise RuntimeError(f"SolidWorks failed to open: {file_path}")

    import_data = sw_app.GetImportFileData(file_path)
    if import_data is not None:
        try:
            import_data.MapConfigurationData = False
        except Exception:
            pass
        try:
            model = sw_app.LoadFile4(file_path, "r", import_data, errors)
            if model is not None:
                return model
        except Exception:
            pass

    for opts in (swOpenDocOptions_Silent, 0):
        try:
            model = sw_app.OpenDoc6(file_path, swDocPART, opts, "", errors, warnings)
            if model is not None:
                return model
        except Exception:
            pass

    raise RuntimeError(f"SolidWorks failed to open STEP: {file_path}")


def _load_step_silent(sw_app, step_path: str, *, visible: bool = False):
    return _open_document(sw_app, step_path, visible=visible)


def _rebuild(model) -> None:
    try:
        model.ForceRebuild3(False)
    except Exception:
        try:
            model.EditRebuild3()
        except Exception:
            pass


def _step_to_sldprt(sw_app, step_path: str, prt_path: str, *, visible: bool = False) -> str:
    """Cache STEP as native SLDPRT (InsertPart requires SLDPRT, not STEP)."""
    prt_path = os.path.abspath(prt_path)
    if os.path.isfile(prt_path) and os.path.getsize(prt_path) > 100_000:
        return prt_path

    os.makedirs(os.path.dirname(prt_path) or ".", exist_ok=True)
    model = _load_step_silent(sw_app, step_path, visible=visible)
    try:
        ok = model.SaveAs3(prt_path, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
        if not os.path.isfile(prt_path):
            raise RuntimeError(f"SaveAs3 SLDPRT failed (return={ok!r}): {prt_path}")
    finally:
        title = _doc_title(model)
        if title:
            sw_app.CloseDoc(title)
    return prt_path


def _insert_sldprt(model, prt_path: str, *, label: str) -> None:
    """Insert a positioned SLDPRT into the active part (Insert → Part)."""
    ok = model.InsertPart(prt_path, 0.0, 0.0, 0.0)
    if ok is None or ok is False:
        raise RuntimeError(f"{label}: InsertPart failed for {prt_path}")
    _rebuild(model)
    time.sleep(0.3)
    print(f"  {label}: inserted {os.path.basename(prt_path)}", flush=True)


def merge_manual_zslabs(
    manual_dir: str,
    out_step: str,
    *,
    out_xt: str | None = None,
    per_layer_combine: bool = False,
    visible: bool = False,
    allow_start_sw: bool = False,
) -> dict[str, str | int | bool]:
    """
    Merge zslab_iz0..iz3.step in SolidWorks into one solid.

    Requires SolidWorks running (or allow_start_sw=True).
    """
    if not solidworks_com_available(require_running=not allow_start_sw):
        raise RuntimeError(
            "SolidWorks is not running. Start SolidWorks manually, then re-run."
        )

    manual_dir = os.path.abspath(manual_dir)
    layer_paths = _layer_steps(manual_dir)
    work_dir = os.path.join(manual_dir, ".sw_work")
    os.makedirs(work_dir, exist_ok=True)
    out_step = os.path.abspath(out_step)
    if out_xt:
        out_xt = os.path.abspath(out_xt)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)
    if out_xt:
        os.makedirs(os.path.dirname(out_xt) or ".", exist_ok=True)

    import pythoncom

    pythoncom.CoInitialize()
    sw_app = None
    model = None
    try:
        sw_app = _connect_solidworks(allow_start=allow_start_sw)
        try:
            sw_app.CloseAllDocuments(True)
        except Exception:
            pass

        prt_paths: list[str] = []
        for iz, step_path in enumerate(layer_paths):
            prt_path = os.path.join(work_dir, f"zslab_iz{iz}.sldprt")
            print(f"Cache iz={iz} STEP→SLDPRT ...", flush=True)
            prt_paths.append(_step_to_sldprt(sw_app, step_path, prt_path, visible=visible))

        print(f"Open base layer: {prt_paths[0]}", flush=True)
        model = _open_document(sw_app, prt_paths[0], visible=visible)
        n = _body_count(model)
        print(f"  base bodies: {n}", flush=True)
        if per_layer_combine and n > 1:
            n = _combine_all_bodies(model, label="base-layer")
            print(f"  base after layer combine: {n}", flush=True)

        for iz, prt_path in enumerate(prt_paths[1:], start=1):
            print(f"Insert layer iz={iz}: {os.path.basename(prt_path)}", flush=True)
            _insert_sldprt(model, prt_path, label=f"iz={iz}")
            n = _body_count(model)
            print(f"  bodies after iz={iz}: {n}", flush=True)
            if per_layer_combine and n > 1:
                n = _combine_all_bodies(model, label=f"layer-iz{iz}")
                print(f"  after layer combine: {n}", flush=True)

        stacked_step = os.path.join(work_dir, "_stacked_multibody.step")
        final_n = _combine_all_bodies(model, label="final-block")
        print(f"Save stacked part → {stacked_step}", flush=True)
        ok = model.SaveAs3(stacked_step, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
        if not os.path.isfile(stacked_step):
            raise RuntimeError(f"SaveAs3 stacked STEP failed (return={ok!r})")

        if final_n != 1:
            print(f"Gmsh fuse {len(layer_paths)} layer STEP(s) → {out_step}", flush=True)
            final_n = _gmsh_fuse_step_stack(layer_paths, out_step, label="sw-manual-gmsh")
            if final_n != 1:
                raise RuntimeError(f"Gmsh fuse expected 1 body, got {final_n}")
            if xt_path:
                print(f"Open fused STEP in SW for X_T → {xt_path}", flush=True)
                fused_model = _load_step_silent(sw_app, out_step, visible=visible)
                try:
                    ok = fused_model.SaveAs3(xt_path, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
                    if not os.path.isfile(xt_path):
                        raise RuntimeError(f"SaveAs3 X_T failed (return={ok!r}): {xt_path}")
                finally:
                    title = _doc_title(fused_model)
                    if title:
                        sw_app.CloseDoc(title)
        else:
            print(f"Save STEP → {out_step}", flush=True)
            ok = model.SaveAs3(out_step, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
            if not os.path.isfile(out_step):
                raise RuntimeError(f"SaveAs3 STEP failed (return={ok!r}): {out_step}")
            if xt_path:
                print(f"Save X_T → {xt_path}", flush=True)
                ok = model.SaveAs3(xt_path, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
                if not os.path.isfile(xt_path):
                    raise RuntimeError(f"SaveAs3 X_T failed (return={ok!r}): {xt_path}")

        return {
            "manual_dir": manual_dir,
            "merged_step": out_step,
            "merged_xt": xt_path or "",
            "stacked_step": stacked_step,
            "final_body_count": final_n,
            "layers_merged": len(layer_paths),
            "method": "sw_insert_gmsh_fuse" if final_n == 1 else "sw_stack",
        }
    finally:
        if model is not None and sw_app is not None:
            try:
                title = _doc_title(model)
                if title:
                    sw_app.CloseDoc(title)
            except Exception:
                pass
        pythoncom.CoUninitialize()


def merge_from_manifest(
    manifest_path: str,
    *,
    out_step: str | None = None,
    out_xt: str | None = None,
    per_layer_combine: bool | None = None,
    visible: bool = False,
    allow_start_sw: bool = False,
) -> dict[str, str | int | bool]:
    manifest_path = os.path.abspath(manifest_path)
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    manual_dir = manifest.get("manual_dir") or os.path.dirname(manifest_path)
    if out_step is None:
        out_step = manifest.get("expected_merged_step") or os.path.join(
            manual_dir, f"{manifest.get('slug', 'merged')}_solid_merged.step"
        )
    if out_xt is None:
        root, _ = os.path.splitext(out_step)
        out_xt = root + ".x_t"

    if per_layer_combine is None:
        per_layer_combine = manifest.get("method") == "manual_sw_multibody_zslab"

    stats = merge_manual_zslabs(
        manual_dir,
        out_step,
        out_xt=out_xt,
        per_layer_combine=per_layer_combine,
        visible=visible,
        allow_start_sw=allow_start_sw,
    )
    manifest["merged_step"] = stats["merged_step"]
    manifest["merged_xt"] = stats.get("merged_xt") or ""
    manifest["sw_auto_merge"] = stats
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return stats


def variant_dir_for_q(q: float, *, nx: int = 4, ny: int = 4, nz: int = 4) -> str:
    from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
    from src.paths import CAD_ROOT

    gen = HuBaiLatticeGenerator(
        cell_size=20.0,
        rod_diameter=2.0,
        amplitude=2.0,
        period_factor=float(q),
        n_segments=24,
    )
    gen.build_unitcell()
    slug = f"hu_bai_{gen.variant_name.lower()}_L20"
    return os.path.join(str(CAD_ROOT), "manual", f"{slug}_{nx}x{ny}x{nz}")
