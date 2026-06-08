"""Convert STEP BREP to Parasolid X_T (requires SolidWorks on Windows).

COM automation is intentionally conservative: it never starts SolidWorks via
Dispatch, never retries failed opens, and refuses large STL imports (they
crash SW 2025). Use manual File → Open on fused STL for 4×4×4 blocks.
"""

from __future__ import annotations

import os
import re
import sys
import time

# Large mesh STL via COM has crashed SolidWorks 2025 in testing (~80k facets).
SW_STL_COM_MAX_BYTES = 400_000


def _connect_solidworks(*, allow_start: bool = False):
    """Attach to a running SolidWorks instance only (default)."""
    import win32com.client

    try:
        return win32com.client.GetActiveObject("SldWorks.Application")
    except Exception as exc:
        if allow_start:
            return win32com.client.Dispatch("SldWorks.Application")
        raise RuntimeError(
            "SolidWorks is not running. Start SolidWorks manually, then run "
            "scripts/sw_step_to_xt.py — or import the fused STL via File → Open."
        ) from exc


def _doc_title(model) -> str:
    title = getattr(model, "GetTitle", None)
    if title is None:
        return ""
    return title if isinstance(title, str) else title()


def solidworks_running() -> bool:
    """True if a SolidWorks instance is already running (does not start SW)."""
    if sys.platform != "win32":
        return False
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            win32com.client.GetActiveObject("SldWorks.Application")
            return True
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return False


def solidworks_com_available(*, require_running: bool = True) -> bool:
    """
    Return True if pywin32 is available and (by default) SolidWorks is already open.

    Does not start SolidWorks — starting SW from Python caused crashes during
    automated STL import tests.
    """
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    if not require_running:
        return True
    return solidworks_running()


def _import_stl_as_solid(sw_app, stl_path: str, *, visible: bool = False):
    """Import STL via LoadFile4 or LoadFile2 (never OpenDoc6)."""
    import pythoncom
    import win32com.client

    swImportStlBodyType_Solid = 2
    _SW_PREF_STL_IMPORT_AS = 198

    sw_app.Visible = bool(visible)

    import_data = sw_app.GetImportFileData(stl_path)
    if import_data is not None:
        import_data.ImportAs = swImportStlBodyType_Solid
        try:
            import_data.Unit = 8  # mm
        except Exception:
            pass
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        model = sw_app.LoadFile4(stl_path, "r", import_data, errors)
        if model is not None:
            return model

    old_import_as = sw_app.GetUserPreferenceIntegerValue(_SW_PREF_STL_IMPORT_AS)
    sw_app.SetUserPreferenceIntegerValue(_SW_PREF_STL_IMPORT_AS, swImportStlBodyType_Solid)
    try:
        if not sw_app.LoadFile2(stl_path, "r"):
            raise RuntimeError(f"LoadFile2 failed: {stl_path}")
        model = sw_app.ActiveDoc
        if model is None:
            raise RuntimeError(
                f"LoadFile2 succeeded but ActiveDoc is Nothing: {stl_path}"
            )
        return model
    finally:
        sw_app.SetUserPreferenceIntegerValue(_SW_PREF_STL_IMPORT_AS, old_import_as)


def convert_stl_to_xt(
    stl_path: str,
    xt_path: str,
    *,
    visible: bool = False,
    retries: int = 1,
    allow_start_sw: bool = False,
) -> None:
    """Import STL in SolidWorks and save as Parasolid .x_t (small files only)."""
    stl_path = os.path.abspath(stl_path)
    xt_path = os.path.abspath(xt_path)
    if not os.path.isfile(stl_path):
        raise FileNotFoundError(stl_path)

    stl_bytes = os.path.getsize(stl_path)
    if stl_bytes > SW_STL_COM_MAX_BYTES:
        raise RuntimeError(
            f"STL too large for COM import ({stl_bytes} bytes > {SW_STL_COM_MAX_BYTES}). "
            "Open the fused STL manually in SolidWorks (Mesh → Solid body)."
        )

    os.makedirs(os.path.dirname(xt_path) or ".", exist_ok=True)

    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise ImportError(
            "STL → X_T conversion requires pywin32 and SolidWorks."
        ) from exc

    swSaveAsCurrentVersion = 0
    swSaveAsOptions_Silent = 1

    pythoncom.CoInitialize()
    sw_app = None
    model = None
    try:
        sw_app = _connect_solidworks(allow_start=allow_start_sw)

        last_err: Exception | None = None
        for attempt in range(max(1, min(retries, 1))):
            if attempt:
                time.sleep(1.0)
            try:
                model = _import_stl_as_solid(sw_app, stl_path, visible=visible)
                if model is not None:
                    break
                last_err = RuntimeError("STL import returned Nothing")
            except Exception as exc:
                last_err = exc

        if model is None:
            raise RuntimeError(
                f"SolidWorks failed to open STL: {stl_path}"
            ) from last_err

        ok = model.SaveAs3(xt_path, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
        if not os.path.isfile(xt_path):
            raise RuntimeError(
                f"SolidWorks SaveAs3 failed for: {xt_path} (return={ok!r})"
            )
    finally:
        if model is not None and sw_app is not None:
            try:
                title = _doc_title(model)
                if title:
                    sw_app.CloseDoc(title)
            except Exception:
                pass
        pythoncom.CoUninitialize()


def count_step_solids(step_path: str) -> int:
    """Count MANIFOLD_SOLID_BREP entries in a STEP file (text scan)."""
    step_path = os.path.abspath(step_path)
    with open(step_path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read().count("MANIFOLD_SOLID_BREP")


def count_step_products(step_path: str) -> int:
    """
    Count STEP PRODUCT entities (one per SolidWorks part window on import).

    Orphan pipe/cylinder construction geometry is exported as extra PRODUCTs
    even when only one MANIFOLD_SOLID_BREP exists — this count catches that.
    """
    step_path = os.path.abspath(step_path)
    with open(step_path, "r", encoding="utf-8", errors="ignore") as fh:
        return len(re.findall(r"^#\d+ = PRODUCT\(", fh.read(), flags=re.MULTILINE))


def analyze_step_for_solidworks(
    step_path: str,
    *,
    expected_volumes: int | None = None,
    fused_single: bool = True,
    require_advanced_brep: bool = True,
) -> dict[str, int | bool | str]:
    """
    Scan a solid STEP for SolidWorks-safe structure.

    Orphan pipe/cylinder construction geometry appears as ``PRODUCT count >
    volume count`` (e.g. 100 PRODUCTs, 1 solid) and crashes SolidWorks.

    Returns counts; raises ``RuntimeError`` when unsafe.
    """
    step_path = os.path.abspath(step_path)
    with open(step_path, "r", encoding="utf-8", errors="ignore") as fh:
        text = fh.read()

    n_products = len(re.findall(r"^#\d+ = PRODUCT\(", text, flags=re.MULTILINE))
    n_solids = text.count("MANIFOLD_SOLID_BREP")
    has_advanced_brep = "ADVANCED_BREP_SHAPE_REPRESENTATION" in text
    exp_vol = int(expected_volumes) if expected_volumes is not None else n_solids

    report: dict[str, int | bool | str] = {
        "step_path": step_path,
        "product_count": n_products,
        "solid_count": n_solids,
        "expected_volumes": exp_vol,
        "has_advanced_brep": has_advanced_brep,
        "solidworks_safe": True,
    }

    problems: list[str] = []
    if n_products > exp_vol:
        problems.append(
            f"{n_products} STEP PRODUCT entries but only {exp_vol} fused volume(s) — "
            "orphan wire/face construction geometry (SolidWorks multi-window crash)"
        )
    if fused_single:
        if n_solids != 1:
            problems.append(f"{n_solids} MANIFOLD_SOLID_BREP bodies (expected 1 fused solid)")
        if n_products != 1:
            problems.append(f"{n_products} STEP PRODUCT entries (expected 1)")
    if require_advanced_brep and n_solids >= 1 and fused_single and not has_advanced_brep:
        problems.append(
            "missing ADVANCED_BREP_SHAPE_REPRESENTATION (legacy multi-PRODUCT STEP layout)"
        )
    if problems:
        report["solidworks_safe"] = False
        report["problems"] = "; ".join(problems)
        raise RuntimeError(
            "STEP is not safe for SolidWorks import: "
            + report["problems"]
            + ". Regenerate with export_lattice_step_occ(fuse=True); "
            "OCC paths must call prune_occ_for_step_export() before gmsh.write()."
        )
    return report


def convert_step_to_xt(
    step_path: str,
    xt_path: str,
    *,
    visible: bool = False,
    retries: int = 1,
    allow_start_sw: bool = False,
    fused_single: bool = True,
) -> None:
    """Import STEP in a running SolidWorks and save as Parasolid text (.x_t)."""
    step_path = os.path.abspath(step_path)
    xt_path = os.path.abspath(xt_path)
    if not os.path.isfile(step_path):
        raise FileNotFoundError(step_path)

    analyze_step_for_solidworks(step_path, fused_single=fused_single)

    os.makedirs(os.path.dirname(xt_path) or ".", exist_ok=True)

    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise ImportError(
            "STEP → X_T conversion requires pywin32 on Windows "
            "(pip install pywin32) and SolidWorks."
        ) from exc

    swDocPART = 1
    swOpenDocOptions_Silent = 1
    swSaveAsCurrentVersion = 0
    swSaveAsOptions_Silent = 1

    pythoncom.CoInitialize()
    sw_app = None
    model = None
    try:
        sw_app = _connect_solidworks(allow_start=allow_start_sw)
        sw_app.Visible = bool(visible)

        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

        last_err: Exception | None = None
        # SW 2025: OpenDoc6 often fails on OCC STEP (error 2097152); LoadFile2 matches manual Open.
        try:
            if sw_app.LoadFile2(step_path, "r"):
                model = sw_app.ActiveDoc
        except Exception as exc:
            last_err = exc
            model = None

        if model is None:
            for opts in (1, 0):
                try:
                    model = sw_app.OpenDoc6(
                        step_path,
                        swDocPART,
                        opts,
                        "",
                        errors,
                        warnings,
                    )
                    if model is not None:
                        break
                    last_err = RuntimeError(
                        f"OpenDoc6 returned Nothing (errors={int(errors.value)}, "
                        f"warnings={int(warnings.value)})"
                    )
                except Exception as exc:
                    last_err = exc

        if model is None:
            raise RuntimeError(
                f"SolidWorks failed to open STEP: {step_path}"
            ) from last_err

        print(f"  SolidWorks: Save As Parasolid → {xt_path}", flush=True)
        ok = model.SaveAs3(xt_path, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
        if not os.path.isfile(xt_path):
            raise RuntimeError(
                f"SolidWorks SaveAs3 failed for: {xt_path} (return={ok!r})"
            )
    finally:
        if model is not None and sw_app is not None:
            try:
                title = _doc_title(model)
                if title:
                    sw_app.CloseDoc(title)
            except Exception:
                pass
        pythoncom.CoUninitialize()
