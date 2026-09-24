# -*- coding: utf-8 -*-
"""
Abaqus/CAE noGUI: export field contour PNGs from one ODB.

Default: S.Mises, one view (Z up / Y right / X toward viewer), three stages
(start / mid / densify ≈ 0% / 45% / 80% of step time).

Env:
  HU_BAI_ODB          path to .odb (required)
  HU_BAI_OUT_DIR      output directory for PNGs + manifest (required)
  HU_BAI_STEP         step name (default: last step)
  HU_BAI_FRACTIONS    comma fractions of step time (default: 0,0.45,0.8)
  HU_BAI_STAGE_TAGS   comma tags aligned with fractions
                      (default: start,mid,densify)
  HU_BAI_FIELDS       comma fields: mises,le  (default: mises)
  HU_BAI_VIEWS        comma views: zup[,iso,front]  (default: zup)
                      zup = Z up, Y right, +X toward viewer (camera looks -X)
  HU_BAI_TITLE        optional title prefix in annotation
  HU_BAI_IMAGE_W      PNG width px (default: 1280)
  HU_BAI_IMAGE_H      PNG height px (default: 960)
  HU_BAI_CONTOUR_MIN  fixed legend min (empty = auto)
  HU_BAI_CONTOUR_MAX  fixed legend max (empty = auto; clip hotspots)

Run (from repo root):
  abaqus cae noGUI=scripts/export_odb_field_contours_cae.py
"""
from __future__ import print_function

import json
import os
import sys

from abaqus import *
from abaqusConstants import *
import visualization

ODB_PATH = os.environ.get("HU_BAI_ODB", "").strip()
OUT_DIR = os.environ.get("HU_BAI_OUT_DIR", "").strip()
STEP_NAME = os.environ.get("HU_BAI_STEP", "").strip()
FRACTIONS_RAW = os.environ.get("HU_BAI_FRACTIONS", "0,0.45,0.8").strip()
STAGE_TAGS_RAW = os.environ.get("HU_BAI_STAGE_TAGS", "start,mid,densify").strip()
FIELDS_RAW = os.environ.get("HU_BAI_FIELDS", "mises").strip()
VIEWS_RAW = os.environ.get("HU_BAI_VIEWS", "zup").strip()
TITLE = os.environ.get("HU_BAI_TITLE", "").strip()
IMAGE_W = int(os.environ.get("HU_BAI_IMAGE_W", "1280") or "1280")
IMAGE_H = int(os.environ.get("HU_BAI_IMAGE_H", "960") or "960")
CONTOUR_MIN_RAW = os.environ.get("HU_BAI_CONTOUR_MIN", "").strip()
CONTOUR_MAX_RAW = os.environ.get("HU_BAI_CONTOUR_MAX", "").strip()


def _die(msg):
    print("[ERROR]", msg)
    sys.exit(1)


def _parse_csv_floats(raw):
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def _parse_csv_names(raw):
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def _frame_times(frames):
    times = []
    for fr in frames:
        t = getattr(fr, "frameValue", None)
        if t is None:
            t = float(fr.frameId)
        times.append(float(t))
    return times


def _pick_frame_index(times, frac):
    if not times:
        return 0
    if abs(frac - 1.0) < 1.0e-12:
        return len(times) - 1
    t0 = times[0]
    t1 = times[-1]
    span = t1 - t0 if abs(t1 - t0) > 1.0e-15 else 1.0
    target = t0 + float(frac) * span
    best_i = 0
    best_d = abs(times[0] - target)
    for i, t in enumerate(times):
        d = abs(t - target)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _frac_tag(frac):
    if abs(frac - 1.0) < 1.0e-12:
        return "f100"
    pct = int(round(100.0 * float(frac)))
    return "f%03d" % pct


def _stage_tags(n_frac):
    tags = [t.strip() for t in STAGE_TAGS_RAW.split(",") if t.strip()]
    if len(tags) == n_frac:
        return tags
    return None


def _set_primary_mises(vp):
    vp.odbDisplay.setPrimaryVariable(
        variableLabel="S",
        outputPosition=INTEGRATION_POINT,
        refinement=(INVARIANT, "Mises"),
    )


def _set_primary_le(vp, odb, step_name, frame_idx):
    """Prefer Max. Principal LE; fall back to LE33 then other comps."""
    inv_candidates = (
        "Max. Principal",
        "Max Principal",
        "Absolute Max Principal",
        "Mid. Principal",
        "Min. Principal",
    )
    last_err = None
    for inv in inv_candidates:
        try:
            vp.odbDisplay.setPrimaryVariable(
                variableLabel="LE",
                outputPosition=INTEGRATION_POINT,
                refinement=(INVARIANT, inv),
            )
            return inv
        except Exception as ex:
            last_err = ex
            continue

    comp_candidates = ("LE33", "LE11", "LE22", "LE12", "LE13", "LE23")
    try:
        fr = odb.steps[step_name].frames[frame_idx]
        if "LE" in fr.fieldOutputs:
            fo = fr.fieldOutputs["LE"]
            try:
                comps = [str(c) for c in fo.componentLabels]
            except Exception:
                comps = []
            ordered = [c for c in comp_candidates if (not comps) or (c in comps)]
            for c in comps:
                if c not in ordered:
                    ordered.append(c)
            if ordered:
                comp_candidates = tuple(ordered)
    except Exception as ex:
        print("[WARN] LE component probe failed:", ex)

    for comp in comp_candidates:
        try:
            vp.odbDisplay.setPrimaryVariable(
                variableLabel="LE",
                outputPosition=INTEGRATION_POINT,
                refinement=(COMPONENT, comp),
            )
            return comp
        except Exception as ex:
            last_err = ex
            continue
    raise RuntimeError("Could not set LE primary variable: %s" % last_err)


def _apply_contour_clip(vp):
    cmin = float(CONTOUR_MIN_RAW) if CONTOUR_MIN_RAW else None
    cmax = float(CONTOUR_MAX_RAW) if CONTOUR_MAX_RAW else None
    if cmax is None:
        vp.odbDisplay.contourOptions.setValues(
            numIntervals=12,
            maxAutoCompute=ON,
            minAutoCompute=ON,
        )
        return
    vp.odbDisplay.contourOptions.setValues(
        numIntervals=12,
        maxAutoCompute=OFF,
        maxValue=float(cmax),
        minAutoCompute=OFF,
        minValue=float(cmin) if cmin is not None else 0.0,
    )


def _force_z_up(vp):
    try:
        vp.view.setValues(cameraUpVector=(0.0, 0.0, 1.0))
    except Exception:
        pass


def _apply_view(vp, view_name):
    """
    zup (default): Z up, Y right, +X toward viewer (camera looks along -X).
    iso: isometric with Z up.
    front: look along -Y (XZ plane, Z up) — legacy.
    """
    if view_name in ("zup", "xy", "default"):
        # Camera on +X looking at origin → viewVector (-1,0,0).
        # Up +Z ⇒ screen-right +Y; +X points at viewer.
        vp.view.setViewpoint(
            viewVector=(-1.0, 0.0, 0.0),
            cameraUpVector=(0.0, 0.0, 1.0),
        )
    elif view_name == "iso":
        vp.view.setViewpoint(
            viewVector=(1.0, 1.0, 1.0),
            cameraUpVector=(0.0, 0.0, 1.0),
        )
    elif view_name == "front":
        vp.view.setViewpoint(
            viewVector=(0.0, -1.0, 0.0),
            cameraUpVector=(0.0, 0.0, 1.0),
        )
    else:
        raise ValueError("unknown view: %s" % view_name)
    _force_z_up(vp)
    try:
        vp.view.fitView()
    except Exception:
        pass
    _force_z_up(vp)


def _safe_print(vp, file_stem):
    if file_stem.lower().endswith(".png"):
        file_stem = file_stem[:-4]
    session.printToFile(
        fileName=file_stem,
        format=PNG,
        canvasObjects=(vp,),
    )
    png = file_stem + ".png"
    if not os.path.isfile(png):
        raise RuntimeError("printToFile did not create %s" % png)
    return png


def main():
    if not ODB_PATH or not os.path.isfile(ODB_PATH):
        _die("HU_BAI_ODB missing or not a file: %r" % ODB_PATH)
    if not OUT_DIR:
        _die("HU_BAI_OUT_DIR not set")
    _ensure_dir(OUT_DIR)

    fractions = _parse_csv_floats(FRACTIONS_RAW)
    if not fractions:
        fractions = [0.0, 0.45, 0.8]
    stage_tags = _stage_tags(len(fractions))
    fields = _parse_csv_names(FIELDS_RAW) or ["mises"]
    views = _parse_csv_names(VIEWS_RAW) or ["zup"]

    print("Opening ODB:", ODB_PATH)
    odb = visualization.openOdb(path=ODB_PATH, readOnly=True)

    step_keys = list(odb.steps.keys())
    if not step_keys:
        odb.close()
        _die("ODB has no steps")
    step_name = STEP_NAME if STEP_NAME and STEP_NAME in odb.steps else step_keys[-1]
    step = odb.steps[step_name]
    frames = step.frames
    if not frames:
        odb.close()
        _die("step %s has no frames" % step_name)
    times = _frame_times(frames)
    print(
        "step=%s n_frames=%d t=[%g, %g]"
        % (step_name, len(frames), times[0], times[-1])
    )
    print(
        "stages=%s fractions=%s views=%s fields=%s"
        % (stage_tags, fractions, views, fields)
    )

    vp_name = "Viewport: 1"
    if vp_name in session.viewports.keys():
        vp = session.viewports[vp_name]
    else:
        vp = session.Viewport(name=vp_name, origin=(0, 0), width=220, height=165)
    vp.makeCurrent()
    vp.setValues(displayedObject=odb)

    try:
        session.pngOptions.setValues(imageSize=(IMAGE_W, IMAGE_H))
    except Exception as ex:
        print("[WARN] pngOptions.imageSize:", ex)

    session.printOptions.setValues(
        rendition=COLOR,
        vpDecorations=ON,
        vpBackground=OFF,
    )
    try:
        vp.viewportAnnotationOptions.setValues(
            triad=ON,
            title=ON,
            state=ON,
            legend=ON,
            compass=OFF,
        )
    except Exception:
        pass

    vp.odbDisplay.display.setValues(plotState=(CONTOURS_ON_DEF,))
    try:
        vp.odbDisplay.commonOptions.setValues(
            visibleEdges=FEATURE,
            deformationScaling=UNIFORM,
            uniformScaleFactor=1.0,
        )
    except Exception:
        pass
    try:
        _apply_contour_clip(vp)
    except Exception as ex:
        print("[WARN] contourOptions:", ex)

    written = []
    errors = []

    for si, frac in enumerate(fractions):
        fi = _pick_frame_index(times, frac)
        if stage_tags is not None:
            ftag = stage_tags[si]
        else:
            ftag = _frac_tag(frac)
        try:
            vp.odbDisplay.setFrame(step=step_name, frame=fi)
        except Exception:
            step_i = step_keys.index(step_name)
            vp.odbDisplay.setFrame(step=step_i, frame=fi)
        print(
            "frame stage=%s frac=%s -> idx=%d time=%g"
            % (ftag, frac, fi, times[fi])
        )

        for field in fields:
            le_inv = None
            try:
                if field in ("mises", "s_mises", "s.mises"):
                    field_tag = "S_Mises"
                    _set_primary_mises(vp)
                elif field in ("le", "le_maxp", "strain"):
                    field_tag = "LE"
                    le_inv = _set_primary_le(vp, odb, step_name, fi)
                    field_tag = "LE_%s" % le_inv.replace(" ", "_").replace(".", "")
                else:
                    raise ValueError("unknown field %r" % field)
            except Exception as ex:
                msg = "field %s @ %s: %s" % (field, ftag, ex)
                print("[ERROR]", msg)
                errors.append(msg)
                continue

            for view in views:
                stem = os.path.join(
                    OUT_DIR,
                    "%s_%s_%s" % (field_tag, ftag, view),
                )
                try:
                    _apply_view(vp, view)
                    try:
                        _apply_contour_clip(vp)
                    except Exception as ex:
                        print("[WARN] contour clip:", ex)
                    if TITLE:
                        try:
                            vp.viewportAnnotationOptions.setValues(
                                titleString="%s | %s | %s | %s"
                                % (TITLE, field_tag, ftag, view)
                            )
                        except Exception:
                            pass
                    png = _safe_print(vp, stem)
                    print("Wrote", png)
                    written.append(
                        {
                            "path": png,
                            "field": field_tag,
                            "le_invariant": le_inv,
                            "stage": ftag,
                            "fraction": float(frac),
                            "frame_index": int(fi),
                            "frame_time": float(times[fi]),
                            "view": view,
                        }
                    )
                except Exception as ex:
                    msg = "print %s %s %s: %s" % (field_tag, ftag, view, ex)
                    print("[ERROR]", msg)
                    errors.append(msg)

    manifest = {
        "odb": os.path.abspath(ODB_PATH),
        "out_dir": os.path.abspath(OUT_DIR),
        "step": step_name,
        "n_frames": len(frames),
        "fractions": [float(x) for x in fractions],
        "stage_tags": stage_tags,
        "fields": fields,
        "views": views,
        "image_size": [IMAGE_W, IMAGE_H],
        "view_convention": "zup: Z-up, Y-right, +X toward viewer",
        "written": written,
        "errors": errors,
        "ok": len(errors) == 0 and len(written) > 0,
    }
    man_path = os.path.join(OUT_DIR, "contours_manifest.json")
    with open(man_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print("Wrote", man_path, "n_png=%d n_err=%d" % (len(written), len(errors)))

    try:
        odb.close()
    except Exception:
        pass
    try:
        for _name in list(session.odbs.keys()):
            try:
                session.odbs[_name].close()
            except Exception:
                pass
    except Exception:
        pass

    if not written:
        _die("no PNGs written")
    if errors:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
