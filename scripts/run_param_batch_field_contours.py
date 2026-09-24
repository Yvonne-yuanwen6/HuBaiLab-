#!/usr/bin/env python3
"""Batch-export Abaqus CAE field contour PNGs for param_batch.

Discovers ODBs under output/jobs/param_batch/{case_id}/{run_slug}/, optionally
upgrades them, runs scripts/export_odb_field_contours_cae.py via
`abaqus cae noGUI=...`, writes PNGs to
output/post/param_batch/{case}/{slug}/contours/, and builds a collage under
output/reports/param_batch/.

Usage:
  py -3 scripts/run_param_batch_field_contours.py
  py -3 scripts/run_param_batch_field_contours.py --only af2q1_deq2_k1,af2q0_deq2_k1
  py -3 scripts/run_param_batch_field_contours.py --upgrade --skip-existing
  py -3 scripts/run_param_batch_field_contours.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.paths import PROJECT_ROOT, REPORTS_ROOT

RUN_SLUG = "cae_tet0p6mm80_5mmin_paperbox"
BATCH_NAME = "param_batch"
CAE_SCRIPT = PROJECT_ROOT / "scripts" / "export_odb_field_contours_cae.py"
DEFAULT_CASES = [
    "af2q0_deq2_k1",
    "af2q0_deq2_k1p5",
    "af2q0_deq2_k2",
    "af2q0p5_deq2_k1",
    "af2q0p5_deq2_k1p5",
    "af2q0p5_deq2_k2",
    "af2q1_deq1p5_k1",
    "af2q1_deq2_k1",
    "af2q1_deq2_k1p5",
    "af2q1_deq2_k2",
    "af2q1_deq2p5_k1",
    "af2q1p5_deq2_k1",
    "af2q1p5_deq2_k1p5",
    "af2q1p5_deq2_k2",
    "af1q1_deq2_k1",
    "af3q1_deq2_k1",
    "af0p5q1_deq2_k1",
    "af1p5q1_deq2_k1",
    "af2p5q1_deq2_k1",
    "af0p5q1p5_deq2_k1",
    "af1q1p5_deq2_k1",
    "af1p5q1p5_deq2_k1",
]

_DEFAULT_ABAQUS = Path(r"D:\Apps\SIMULIA\Commands\abaqus.bat")


def _abaqus_cmd() -> str:
    env = os.environ.get("ABAQUS_CMD", "").strip()
    if env:
        return env
    if _DEFAULT_ABAQUS.is_file():
        return str(_DEFAULT_ABAQUS)
    return "abaqus"


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> int:
    run_cmd: list[str] = [str(c) for c in cmd]
    if run_cmd and run_cmd[0].lower().endswith(".bat"):
        run_cmd = [os.environ.get("ComSpec", "cmd.exe"), "/c", *run_cmd]
    print("CMD:", " ".join(run_cmd), flush=True)
    p = subprocess.run(run_cmd, cwd=str(cwd) if cwd else None, env=env)
    return int(p.returncode)


def _job_dir_for_case(case_id: str) -> Path | None:
    jd = PROJECT_ROOT / "output" / "jobs" / BATCH_NAME / case_id / RUN_SLUG
    return jd if jd.is_dir() else None


def resolve_odb(case_id: str) -> tuple[Path | None, Path | None]:
    """Prefer up.odb then {slug}.odb under param_batch."""
    jd = _job_dir_for_case(case_id)
    if jd is None:
        return None, None
    up = jd / "up.odb"
    main = jd / f"{RUN_SLUG}.odb"
    if up.is_file():
        return up, jd
    if main.is_file():
        return main, jd
    return None, None


def post_contours_dir(case_id: str) -> Path:
    return (
        PROJECT_ROOT
        / "output"
        / "post"
        / BATCH_NAME
        / case_id
        / RUN_SLUG
        / "contours"
    )


DELIVER_NAMES = (
    "S_Mises_start_zup.png",
    "S_Mises_mid_zup.png",
    "S_Mises_densify_zup.png",
    "case_collage.png",
)


def deliver_case_dir(case_id: str) -> Path:
    """Clean per-structure folder: only 3 stage PNGs + 1 collage."""
    return REPORTS_ROOT / BATCH_NAME / "field_contours" / case_id


def publish_case_package(case_id: str, contours_dir: Path) -> Path | None:
    """Copy the 3+1 deliverables into reports/.../field_contours/{case_id}/."""
    dst = deliver_case_dir(case_id)
    dst.mkdir(parents=True, exist_ok=True)
    # Remove stale extras so folder stays exactly 3+1
    for p in list(dst.iterdir()):
        if p.is_file() and p.name not in DELIVER_NAMES:
            try:
                p.unlink()
            except OSError:
                pass
    missing: list[str] = []
    for name in DELIVER_NAMES:
        src = contours_dir / name
        if not src.is_file():
            missing.append(name)
            continue
        shutil.copy2(src, dst / name)
    if missing:
        print(f"[{case_id}] WARN deliver missing: {missing}", flush=True)
        return None
    return dst



def ensure_upgraded(odb: Path, job_dir: Path, *, force: bool) -> Path:
    """Return usable ODB path; create up.odb when forced or when odb is the raw file and force."""
    up = job_dir / "up.odb"
    if odb.name.lower() == "up.odb" and odb.is_file() and not force:
        return odb
    if up.is_file() and not force:
        return up
    if not force and odb.is_file():
        # Use as-is; caller may retry with --upgrade on failure
        return odb
    # Upgrade raw slug.odb → up.odb in job_dir
    raw = job_dir / f"{RUN_SLUG}.odb"
    if not raw.is_file():
        raw = odb
    if up.is_file() and force:
        try:
            up.unlink()
        except OSError:
            pass
    print(f"[upgrade] {raw} -> {up}", flush=True)
    rc = _run(
        [_abaqus_cmd(), "upgrade", "job=up", f"odb={raw.name}"],
        cwd=job_dir,
    )
    if rc != 0 or not up.is_file():
        raise RuntimeError(f"abaqus upgrade failed rc={rc} for {case_id_from_job(job_dir)}")
    return up


def case_id_from_job(job_dir: Path) -> str:
    # .../{case_id}/{run_slug}
    return job_dir.parent.name


def discover_cases(only: list[str] | None) -> list[str]:
    if only:
        return list(only)
    found: list[str] = []
    seen: set[str] = set()
    root = PROJECT_ROOT / "output" / "jobs" / BATCH_NAME
    if root.is_dir():
        for case_dir in sorted(root.iterdir()):
            if not case_dir.is_dir():
                continue
            cid = case_dir.name
            if cid in seen:
                continue
            odb, _ = resolve_odb(cid)
            if odb is None:
                continue
            seen.add(cid)
            found.append(cid)
    # Prefer documented default order, then any extras
    ordered = [c for c in DEFAULT_CASES if c in seen]
    extras = [c for c in found if c not in set(DEFAULT_CASES)]
    return ordered + extras


def run_cae_export(
    odb: Path,
    out_dir: Path,
    *,
    title: str,
    fractions: str,
    fields: str,
    views: str,
    stage_tags: str = "start,mid,densify",
    tool: str = "viewer",
    image_w: int = 1280,
    image_h: int = 960,
    contour_min: str = "",
    contour_max: str = "",
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Ensure SIMULIA Commands on PATH for nested tools
    sim = r"D:\Apps\SIMULIA\Commands"
    if Path(sim).is_dir() and sim not in env.get("Path", ""):
        env["Path"] = sim + os.pathsep + env.get("Path", "")
    env["HU_BAI_ODB"] = str(odb.resolve())
    env["HU_BAI_OUT_DIR"] = str(out_dir.resolve())
    env["HU_BAI_FRACTIONS"] = fractions
    env["HU_BAI_STAGE_TAGS"] = stage_tags
    env["HU_BAI_FIELDS"] = fields
    env["HU_BAI_VIEWS"] = views
    env["HU_BAI_TITLE"] = title
    env["HU_BAI_ROOT"] = str(PROJECT_ROOT)
    env["HU_BAI_IMAGE_W"] = str(int(image_w))
    env["HU_BAI_IMAGE_H"] = str(int(image_h))
    if contour_min:
        env["HU_BAI_CONTOUR_MIN"] = str(contour_min)
    if contour_max:
        env["HU_BAI_CONTOUR_MAX"] = str(contour_max)
    tool = (tool or "viewer").strip().lower()
    if tool not in ("viewer", "cae"):
        tool = "viewer"
    # Keep Abaqus cwd ASCII-safe
    return _run(
        [_abaqus_cmd(), tool, f"noGUI={CAE_SCRIPT.as_posix()}"],
        cwd=PROJECT_ROOT,
        env=env,
    )


def has_zup_set(contours_dir: Path) -> bool:
    return all(
        (contours_dir / n).is_file()
        for n in (
            "S_Mises_start_zup.png",
            "S_Mises_mid_zup.png",
            "S_Mises_densify_zup.png",
        )
    )


def _setup_font() -> None:
    try:
        from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

        configure_matplotlib_chinese()
    except Exception:
        pass


def build_collage(
    case_pngs: list[tuple[str, Path]],
    out_png: Path,
    *,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg

    _setup_font()
    n = len(case_pngs)
    if n == 0:
        return
    ncols = min(4, n)
    nrows = int(math.ceil(n / float(ncols)))
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(4.2 * ncols, 3.4 * nrows),
        dpi=140,
    )
    if nrows == 1 and ncols == 1:
        axes_flat = [axes]
    else:
        axes_flat = list(axes.flat) if hasattr(axes, "flat") else [axes]
    for i, (cid, png) in enumerate(case_pngs):
        ax = axes_flat[i]
        if png.is_file():
            img = mpimg.imread(str(png))
            ax.imshow(img)
        ax.set_title(cid, fontsize=9)
        ax.axis("off")
    for j in range(n, len(axes_flat)):
        axes_flat[j].axis("off")
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print("Wrote", out_png, "n_panels=%d" % n)


def build_case_collage(contours_dir: Path, case_id: str) -> Path | None:
    """Grid contour PNGs for one case; prefer start→mid→densify order."""
    stage_order = ("start", "mid", "densify")
    all_pngs = [
        p
        for p in contours_dir.glob("*.png")
        if p.is_file() and not p.name.startswith("case_collage")
    ]
    if not all_pngs:
        return None

    def sort_key(p: Path) -> tuple:
        name = p.stem.lower()
        stage_i = 99
        for i, s in enumerate(stage_order):
            if f"_{s}_" in f"_{name}_" or name.endswith(f"_{s}_zup") or f"_{s}_zup" in name:
                stage_i = i
                break
        return (stage_i, name)

    # Prefer the new default set: S_Mises_{start,mid,densify}_zup
    preferred = [
        contours_dir / f"S_Mises_{s}_zup.png" for s in stage_order
    ]
    if all(p.is_file() for p in preferred):
        pngs = preferred
    else:
        pngs = sorted(all_pngs, key=sort_key)

    out = contours_dir / "case_collage.png"
    panels = [(p.stem, p) for p in pngs]
    build_collage(
        panels,
        out,
        title=f"{case_id} · start / mid / densify · {RUN_SLUG}",
    )
    return out if out.is_file() else None


def pick_collage_png(contours_dir: Path) -> Path | None:
    """Prefer densify (or mid) Mises zup for batch collage thumb."""
    preferred = [
        "S_Mises_densify_zup.png",
        "S_Mises_mid_zup.png",
        "S_Mises_start_zup.png",
        "S_Mises_f080_zup.png",
        "S_Mises_f100_iso.png",
        "S_Mises_f080_iso.png",
    ]
    for name in preferred:
        p = contours_dir / name
        if p.is_file():
            return p
    pngs = sorted(contours_dir.glob("S_Mises_*_zup.png"))
    if pngs:
        return pngs[-1]
    pngs = sorted(
        p
        for p in contours_dir.glob("*.png")
        if p.is_file() and not p.name.startswith("case_collage")
    )
    return pngs[0] if pngs else None



def collect_existing_batch_panels(only: list[str] | None = None) -> list[tuple[str, Path]]:
    """Scan post trees for existing last-frame Mises panels (multi-case collage)."""
    cases = only if only else discover_cases(None)
    # Also include cases that only have post contours (ODB may be gone)
    if not only:
        extra: list[str] = []
        root = PROJECT_ROOT / "output" / "post" / BATCH_NAME
        if root.is_dir():
            for case_dir in sorted(root.iterdir()):
                if not case_dir.is_dir():
                    continue
                cdir = case_dir / RUN_SLUG / "contours"
                if cdir.is_dir() and case_dir.name not in cases:
                    extra.append(case_dir.name)
        cases = list(cases) + extra
    panels: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for cid in cases:
        if cid in seen:
            continue
        cdir = post_contours_dir(cid)
        png = pick_collage_png(cdir) if cdir.is_dir() else None
        if png is not None:
            seen.add(cid)
            panels.append((cid, png))
    return panels


def write_batch_collage(panels: list[tuple[str, Path]], log) -> Path | None:
    if len(panels) < 1:
        log("collage skip: no panels")
        return None
    report_dir = REPORTS_ROOT / BATCH_NAME
    report_dir.mkdir(parents=True, exist_ok=True)
    collage_png = report_dir / "batch_cae_field_contours_collage.png"
    build_collage(
        panels,
        collage_png,
        title=f"{BATCH_NAME} · S.Mises last-frame iso · {RUN_SLUG} · n={len(panels)}",
    )
    log(f"collage panels={len(panels)} -> {collage_png}")
    return collage_png


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch CAE field contour export")
    ap.add_argument(
        "--only",
        default="",
        help="Comma-separated case_id filter",
    )
    ap.add_argument(
        "--fractions",
        default="0,0.45,0.8",
        help="Step-time fractions: start/mid/densify (default 0,0.45,0.8)",
    )
    ap.add_argument(
        "--stage-tags",
        default="start,mid,densify",
        help="Tags aligned with --fractions (filenames)",
    )
    ap.add_argument("--fields", default="mises", help="mises and/or le (default: mises)")
    ap.add_argument(
        "--views",
        default="zup",
        help="zup=Z-up Y-right X-toward-viewer (default); also iso,front",
    )
    ap.add_argument(
        "--upgrade",
        action="store_true",
        help="Force abaqus upgrade → up.odb before export",
    )
    ap.add_argument(
        "--upgrade-on-fail",
        action="store_true",
        help="If export fails, try upgrade once then retry (off by default; uses a lot of disk/RAM)",
    )
    ap.add_argument(
        "--no-upgrade-on-fail",
        action="store_true",
        help="Disable automatic upgrade retry (default)",
    )
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip case if start/mid/densify zup PNGs already exist (default)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-export even if zup PNGs already exist",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Max number of new CAE/Viewer exports this run (default 1, resume-safe)",
    )
    ap.add_argument(
        "--pause-sec",
        type=float,
        default=30.0,
        help="Seconds to wait after each export so RAM can be released (default 30)",
    )
    ap.add_argument(
        "--tool",
        default="viewer",
        choices=("viewer", "cae"),
        help="Abaqus frontend: viewer is lighter than cae (default viewer)",
    )
    ap.add_argument("--image-w", type=int, default=1280)
    ap.add_argument("--image-h", type=int, default=960)
    ap.add_argument(
        "--contour-min",
        default="",
        help="Fixed legend min (MPa). Empty = auto.",
    )
    ap.add_argument(
        "--contour-max",
        default="",
        help="Fixed legend max (MPa). Empty = auto. Use e.g. 8 to clip hotspots.",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--collage-only",
        action="store_true",
        help="Only rebuild per-case + batch collages from existing PNGs (no CAE)",
    )
    ap.add_argument(
        "--no-collage",
        action="store_true",
        help="Skip reports collage",
    )
    args = ap.parse_args()

    only = [c.strip() for c in args.only.split(",") if c.strip()] or None
    cases = discover_cases(only)
    upgrade_on_fail = bool(args.upgrade_on_fail) and not bool(args.no_upgrade_on_fail)
    skip_existing = bool(args.skip_existing) and not bool(args.force)
    export_limit = max(0, int(args.limit))
    n_exported = 0

    log_dir = PROJECT_ROOT / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "param_batch_field_contours.log"

    def log(msg: str) -> None:
        print(msg, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")

    # ---- collage-only path ----
    if args.collage_only:
        log("==== collage-only ====")
        targets = only if only else [c for c, _ in collect_existing_batch_panels(None)]
        if only:
            targets = only
        else:
            # all cases that have any contour png
            targets = []
            seen: set[str] = set()
            root = PROJECT_ROOT / "output" / "post" / BATCH_NAME
            if root.is_dir():
                for case_dir in sorted(root.iterdir()):
                    cdir = case_dir / RUN_SLUG / "contours"
                    if cdir.is_dir() and any(cdir.glob("*.png")) and case_dir.name not in seen:
                        seen.add(case_dir.name)
                        targets.append(case_dir.name)
        for cid in targets:
            cdir = post_contours_dir(cid)
            if cdir.is_dir():
                out = build_case_collage(cdir, cid)
                pub = publish_case_package(cid, cdir)
                log(f"[{cid}] case_collage={out} deliver={pub}")
        panels = collect_existing_batch_panels(only)
        collage_png = None
        if not args.no_collage:
            collage_png = write_batch_collage(panels, log)
        summary = {
            "mode": "collage-only",
            "cases": targets,
            "n_panels": len(panels),
            "collage": str(collage_png) if collage_png else None,
        }
        report_dir = REPORTS_ROOT / BATCH_NAME
        report_dir.mkdir(parents=True, exist_ok=True)
        summary_path = report_dir / "batch_cae_field_contours_manifest.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log(f"DONE collage-only panels={len(panels)}")
        return 0 if panels else 1

    log(f"==== batch field contours start n={len(cases)} ====")
    if not cases:
        log("No cases with ODBs found under jobs/param_batch")
        return 1

    ok: list[str] = []
    fail: list[tuple[str, str]] = []
    skipped: list[str] = []
    collage_inputs: list[tuple[str, Path]] = []

    for cid in cases:
        log(f"==== {cid} ====")
        odb, jd = resolve_odb(cid)
        if odb is None or jd is None:
            fail.append((cid, "no odb"))
            log(f"[{cid}] FAIL: no odb")
            continue
        out_dir = post_contours_dir(cid)
        if skip_existing and has_zup_set(out_dir):
            skipped.append(cid)
            build_case_collage(out_dir, cid)
            pub = publish_case_package(cid, out_dir)
            log(f"[{cid}] SKIP existing deliver={pub}")
            png = pick_collage_png(out_dir)
            if png:
                collage_inputs.append((cid, png))
            continue

        if export_limit and n_exported >= export_limit:
            log(f"[{cid}] STOP remaining (limit={export_limit}); re-run to continue")
            break

        if args.dry_run:
            log(f"[{cid}] DRY odb={odb} out={out_dir}")
            ok.append(cid)
            continue

        try:
            use_odb = ensure_upgraded(odb, jd, force=bool(args.upgrade))
        except Exception as ex:
            fail.append((cid, f"upgrade: {ex}"))
            log(f"[{cid}] FAIL upgrade: {ex}")
            continue

        rc = run_cae_export(
            use_odb,
            out_dir,
            title=cid,
            fractions=args.fractions,
            fields=args.fields,
            views=args.views,
            stage_tags=args.stage_tags,
            tool=args.tool,
            image_w=args.image_w,
            image_h=args.image_h,
            contour_min=args.contour_min,
            contour_max=args.contour_max,
        )
        n_exported += 1
        # Server ODBs are often older than local Viewer — upgrade once if needed.
        if not has_zup_set(out_dir) and use_odb.name.lower() != "up.odb":
            log(f"[{cid}] export incomplete; try abaqus upgrade → up.odb then retry once")
            try:
                use_odb = ensure_upgraded(odb, jd, force=True)
                rc = run_cae_export(
                    use_odb,
                    out_dir,
                    title=cid,
                    fractions=args.fractions,
                    fields=args.fields,
                    views=args.views,
                    stage_tags=args.stage_tags,
                    tool=args.tool,
                    image_w=args.image_w,
                    image_h=args.image_h,
                    contour_min=args.contour_min,
                    contour_max=args.contour_max,
                )
            except Exception as ex:
                fail.append((cid, f"retry: {ex}"))
                log(f"[{cid}] FAIL retry: {ex}")
                if args.pause_sec > 0:
                    time.sleep(float(args.pause_sec))
                continue

        # Abaqus noGUI often returns 0 even when script sys.exit(2); trust files.
        man = out_dir / "contours_manifest.json"
        man_ok = False
        n_written = 0
        if man.is_file():
            try:
                data = json.loads(man.read_text(encoding="utf-8"))
                n_written = len(data.get("written") or [])
                man_ok = n_written > 0
            except Exception:
                man_ok = False
        if has_zup_set(out_dir):
            man_ok = True
            n_written = max(n_written, 3)
        if man_ok:
            case_col = build_case_collage(out_dir, cid)
            pub = publish_case_package(cid, out_dir)
            log(f"[{cid}] case_collage={case_col} deliver={pub} n_png={n_written}")
            png = pick_collage_png(out_dir)
            if png:
                collage_inputs.append((cid, png))
            ok.append(cid)
            log(f"[{cid}] OK rc={rc} odb={use_odb.name}")
        else:
            fail.append((cid, f"cae rc={rc} no pngs"))
            log(f"[{cid}] FAIL cae rc={rc} no pngs")

        if args.pause_sec > 0:
            log(f"pause {args.pause_sec:.0f}s to release RAM")
            time.sleep(float(args.pause_sec))

    # Merge any other existing cases into batch collage so one-case runs still
    # show multi-case grid when prior exports exist.
    existing = collect_existing_batch_panels(None)
    by_id = {cid: p for cid, p in existing}
    for cid, p in collage_inputs:
        by_id[cid] = p
    # Keep DEFAULT_CASES order then extras
    ordered_ids = [c for c in DEFAULT_CASES if c in by_id]
    ordered_ids += [c for c in by_id if c not in set(DEFAULT_CASES)]
    panels = [(c, by_id[c]) for c in ordered_ids]

    collage_png = None
    if not args.no_collage and not args.dry_run:
        try:
            collage_png = write_batch_collage(panels, log)
        except Exception as ex:
            log(f"collage FAIL: {ex}")

    summary: dict[str, Any] = {
        "run_slug": RUN_SLUG,
        "ok": ok,
        "fail": [{"case": c, "error": e} for c, e in fail],
        "skipped": skipped,
        "collage": str(collage_png) if collage_png and collage_png.is_file() else None,
        "n_ok": len(ok),
        "n_fail": len(fail),
        "n_skipped": len(skipped),
        "n_collage_panels": len(panels),
    }
    report_dir = REPORTS_ROOT / BATCH_NAME
    report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = report_dir / "batch_cae_field_contours_manifest.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"DONE ok={len(ok)} fail={len(fail)} skipped={len(skipped)} collage_panels={len(panels)}")
    log(f"summary: {summary_path}")
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
