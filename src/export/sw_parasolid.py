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


def _sw_com_value(obj, name: str):
    """Call ``name()`` when it is a method; otherwise read a COM property (SW 2025)."""
    attr = getattr(obj, name)
    if not callable(attr):
        return attr
    try:
        return attr()
    except Exception:
        # Late-bound SW API: GetEquationMgr / GetTypeName2 / GetNextFeature are properties.
        prop = getattr(obj, name, None)
        if prop is not None and not callable(prop):
            return prop
        # pywin32 exposes properties as callable dispatch; invoke as propertyget via _oleobj_
        try:
            from win32com.client import dynamic

            disp = dynamic.Dispatch(obj._oleobj_)
            return getattr(disp, name)
        except Exception:
            return attr


def discover_part_templates(sw_app=None) -> list[str]:
    """
    Candidate part templates for NewDocument.

    SW 2025 zh-CN installs often use ``gb_part.prtdot`` instead of ``Part.prtdot``.
    """
    seen: set[str] = set()
    out: list[str] = []

    def _add(path: str | None) -> None:
        if not path:
            return
        path = os.path.abspath(str(path))
        if path.lower().endswith(".prtdot") and os.path.isfile(path) and path not in seen:
            seen.add(path)
            out.append(path)

    if sw_app is not None:
        try:
            _add(sw_app.GetUserPreferenceStringValue(2))  # swDefaultTemplatePart
        except Exception:
            pass
        try:
            _add(sw_app.GetDocumentTemplate("Default", "prtdot", 0, 0, 0))
        except Exception:
            pass
        try:
            rev = str(_sw_com_value(sw_app, "RevisionNumber") or "")
            year_m = re.search(r"(\d{4})", rev)
            if year_m:
                year = year_m.group(1)
                base = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "SOLIDWORKS")
                for name in ("gb_part.prtdot", "Part.prtdot", "part.prtdot"):
                    _add(os.path.join(base, f"SOLIDWORKS {year}", "templates", name))
        except Exception:
            pass

    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    sw_root = os.path.join(program_data, "SOLIDWORKS")
    if os.path.isdir(sw_root):
        for name in ("gb_part.prtdot", "Part.prtdot", "part.prtdot"):
            for year_dir in sorted(os.listdir(sw_root), reverse=True):
                _add(os.path.join(sw_root, year_dir, "templates", name))

    public_root = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Documents", "SOLIDWORKS")
    if os.path.isdir(public_root):
        for name in ("part.prtdot", "Part.prtdot", "gb_part.prtdot"):
            for year_dir in sorted(os.listdir(public_root), reverse=True):
                _add(os.path.join(public_root, year_dir, "samples", "tutorial", "advdrawings", name))

    return out


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


def _parse_step_entities(text: str) -> dict[int, str]:
    """Split STEP DATA section into entity id -> full entity text."""
    entities: dict[int, str] = {}
    if "DATA;" not in text:
        return entities
    data = text.split("DATA;", 1)[1]
    if "ENDSEC;" in data:
        data = data.split("ENDSEC;", 1)[0]

    i = 0
    n = len(data)
    while i < n:
        if data[i] != "#":
            i += 1
            continue
        j = i + 1
        while j < n and data[j].isdigit():
            j += 1
        if j == i + 1:
            i += 1
            continue
        eid = int(data[i + 1 : j])
        k = j
        while k < n and data[k] != "=":
            k += 1
        if k >= n:
            break
        k += 1
        depth = 0
        start = i
        while k < n:
            ch = data[k]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == ";" and depth == 0:
                entities[eid] = data[start : k + 1].strip()
                i = k + 1
                break
            k += 1
        else:
            break
    return entities


def _step_entity_type(entity: str) -> str:
    match = re.match(r"#\d+\s*=\s*(\w+)", entity)
    return match.group(1) if match else ""


def _step_entity_refs(entity: str) -> set[int]:
    rhs = entity.split("=", 1)[1] if "=" in entity else entity
    return {int(x) for x in re.findall(r"#(\d+)", rhs)}


def heal_multibody_step_via_gmsh_roundtrip(step_path: str) -> None:
    """
    Re-import a multi-body STEP and export again so each solid carries baked
    world coordinates (avoids SolidWorks mis-reading stripped assembly transforms).
    """
    step_path = os.path.abspath(step_path)
    tmp_path = f"{step_path}.__heal__.step"
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("step_heal")
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()
        gmsh.write(tmp_path)
    finally:
        gmsh.finalize()
    os.replace(tmp_path, step_path)


def finalize_compound_step_for_solidworks(
    step_path: str,
    *,
    expected_bodies: int,
    max_flatten_bodies: int = 8,
) -> dict[str, int | bool | str]:
    """
    Gmsh roundtrip + optional flatten so SolidWorks opens positioned solids.

    Heal roundtrip bakes world coordinates into each solid; then text-flatten
    collapses sub-PRODUCTs so SolidWorks opens one part window (not N windows).
    Flatten without heal first can mis-place bodies for large compounds.
    """
    step_path = os.path.abspath(step_path)
    heal_multibody_step_via_gmsh_roundtrip(step_path)
    n_products = count_step_products(step_path)
    n_solids = count_step_solids(step_path)
    if n_solids != expected_bodies:
        raise RuntimeError(
            f"Expected {expected_bodies} MANIFOLD_SOLID_BREP, got {n_solids}: {step_path}"
        )
    if n_products <= 1:
        return {
            "step_path": step_path,
            "product_count": n_products,
            "solid_count": n_solids,
            "solidworks_safe": True,
            "flattened": False,
            "healed": True,
        }
    if int(max_flatten_bodies) > 0 and n_solids > int(max_flatten_bodies):
        return {
            "step_path": step_path,
            "product_count": n_products,
            "solid_count": n_solids,
            "solidworks_safe": n_products <= n_solids,
            "flattened": False,
            "healed": True,
            "flatten_skipped": True,
        }
    flat = flatten_step_assembly_to_single_product(step_path)
    flat["healed"] = True
    return flat


def flatten_step_assembly_to_single_product(
    step_path: str,
    *,
    out_path: str | None = None,
) -> dict[str, int | bool | str]:
    """
    Collapse OCCT assembly-style STEP (N sub-PRODUCTs) into one PRODUCT with
    N MANIFOLD_SOLID_BREP bodies so SolidWorks opens a single part window.
    """
    step_path = os.path.abspath(step_path)
    out_path = os.path.abspath(out_path or step_path)
    with open(step_path, "r", encoding="utf-8", errors="ignore") as fh:
        text = fh.read()

    n_products_before = len(re.findall(r"^#\d+ = PRODUCT\(", text, flags=re.MULTILINE))
    solid_ids = [
        int(x)
        for x in re.findall(r"^#(\d+) = MANIFOLD_SOLID_BREP\(", text, flags=re.MULTILINE)
    ]
    if len(solid_ids) <= 1 and n_products_before <= 1:
        return {
            "step_path": out_path,
            "product_count": n_products_before,
            "solid_count": len(solid_ids),
            "solidworks_safe": n_products_before <= len(solid_ids),
            "flattened": False,
        }

    entities = _parse_step_entities(text)
    if not entities:
        raise RuntimeError(f"Could not parse STEP entities: {step_path}")

    sdr_ids = sorted(
        eid for eid, ent in entities.items() if _step_entity_type(ent) == "SHAPE_DEFINITION_REPRESENTATION"
    )
    if not sdr_ids:
        raise RuntimeError(f"No SHAPE_DEFINITION_REPRESENTATION in {step_path}")
    root_sdr = sdr_ids[0]
    root_sdr_ent = entities[root_sdr]
    root_shape_refs = list(_step_entity_refs(root_sdr_ent))
    if len(root_shape_refs) != 2:
        raise RuntimeError(f"Unexpected root SDR refs in {step_path}: {root_shape_refs}")
    root_shape_id = max(root_shape_refs)

    remove: set[int] = set()
    assembly_types = {
        "NEXT_ASSEMBLY_USAGE_OCCURRENCE",
        "SHAPE_REPRESENTATION_RELATIONSHIP",
        "SHAPE_REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION",
        "REPRESENTATION_RELATIONSHIP",
        "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION",
        "ITEM_DEFINED_TRANSFORMATION",
    }

    for eid, ent in entities.items():
        etype = _step_entity_type(ent)
        if etype in assembly_types:
            remove.add(eid)
        elif etype == "PRODUCT_DEFINITION_SHAPE" and "Placement" in ent:
            remove.add(eid)

    for sdr in sdr_ids[1:]:
        remove.add(sdr)
        queue = [sdr]
        seen: set[int] = set()
        while queue:
            cur = queue.pop()
            if cur in seen:
                continue
            seen.add(cur)
            ent = entities.get(cur)
            if not ent:
                continue
            etype = _step_entity_type(ent)
            if etype in {
                "SHAPE_DEFINITION_REPRESENTATION",
                "PRODUCT_DEFINITION_SHAPE",
                "PRODUCT_DEFINITION",
                "PRODUCT_DEFINITION_FORMATION",
                "PRODUCT_DEFINITION_CONTEXT",
                "PRODUCT",
                "ADVANCED_BREP_SHAPE_REPRESENTATION",
            }:
                remove.add(cur)
            for ref in _step_entity_refs(ent):
                ref_ent = entities.get(ref)
                if not ref_ent:
                    continue
                ref_type = _step_entity_type(ref_ent)
                if ref_type in {
                    "PRODUCT_DEFINITION_SHAPE",
                    "PRODUCT_DEFINITION",
                    "PRODUCT_DEFINITION_FORMATION",
                    "PRODUCT_DEFINITION_CONTEXT",
                    "PRODUCT",
                    "ADVANCED_BREP_SHAPE_REPRESENTATION",
                }:
                    queue.append(ref)

    root_product_id: int | None = None
    for ref in _step_entity_refs(entities[root_sdr]):
        ent = entities.get(ref)
        if ent and _step_entity_type(ent) == "PRODUCT_DEFINITION":
            for ref2 in _step_entity_refs(ent):
                ent2 = entities.get(ref2)
                if ent2 and _step_entity_type(ent2) == "PRODUCT_DEFINITION_FORMATION":
                    prods = _step_entity_refs(ent2)
                    if prods:
                        root_product_id = min(prods)
                        break

    for eid, ent in entities.items():
        if _step_entity_type(ent) != "PRODUCT_RELATED_PRODUCT_CATEGORY":
            continue
        refs = _step_entity_refs(ent)
        if root_product_id is not None and root_product_id not in refs:
            remove.add(eid)

    root_shape_ent = entities[root_shape_id]
    shape_match = re.search(r"\(\s*'[^']*'\s*,\s*\(([^)]*)\)\s*,\s*#(\d+)", root_shape_ent)
    if not shape_match:
        raise RuntimeError(f"Could not parse root shape representation in {step_path}")
    inner_refs = [int(x) for x in re.findall(r"#(\d+)", shape_match.group(1))]
    context_id = int(shape_match.group(2))
    axis_id = inner_refs[0] if inner_refs else 11

    solid_ref = ",".join(f"#{sid}" for sid in solid_ids)
    entities[root_shape_id] = (
        f"#{root_shape_id} = ADVANCED_BREP_SHAPE_REPRESENTATION('',(#{axis_id},{solid_ref}),#{context_id});"
    )
    remove.discard(root_shape_id)

    header, data_tail = text.split("DATA;", 1)
    _, footer = data_tail.split("ENDSEC;", 1)
    kept = [entities[eid] for eid in sorted(entities) if eid not in remove]
    new_text = f"{header}DATA;\n" + "\n".join(kept) + "\nENDSEC;" + footer

    if out_path != step_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_text)

    n_products = count_step_products(out_path)
    n_solids = count_step_solids(out_path)
    sw_safe = n_products == 1 and n_solids == len(solid_ids)
    return {
        "step_path": out_path,
        "product_count": n_products,
        "solid_count": n_solids,
        "solidworks_safe": sw_safe,
        "flattened": True,
        "products_before": n_products_before,
    }


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


def measure_step_occ_stats(step_path: str) -> dict[str, float | int]:
    """Import STEP in gmsh OCC and return volume / face / bbox stats."""
    import gmsh

    step_path = os.path.abspath(step_path)
    if not os.path.isfile(step_path):
        raise FileNotFoundError(step_path)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("step_stats")
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        faces = gmsh.model.getEntities(2)
        mass = 0.0
        for dim, tag in vols:
            mass += float(gmsh.model.occ.getMass(int(dim), int(tag)))
        bb = gmsh.model.getBoundingBox(-1, -1)
        return {
            "volume_count": len(vols),
            "face_count": len(faces),
            "mass_mm3": mass,
            "bbox_z_span_mm": float(bb[5] - bb[2]),
            "bbox_mm": {
                "x": [float(bb[0]), float(bb[3])],
                "y": [float(bb[1]), float(bb[4])],
                "z": [float(bb[2]), float(bb[5])],
            },
        }
    finally:
        gmsh.finalize()


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
