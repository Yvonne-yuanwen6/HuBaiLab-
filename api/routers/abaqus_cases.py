"""Abaqus case listing and detail routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from api.schemas.abaqus import (
    ArtifactInfo,
    CaseDetail,
    CaseListResponse,
    CaseSummary,
    CurveResponse,
    TaskResponse,
)
from api.services.remote import list_remote_job_slugs, run_remote_trash
from api.services.task_manager import _write_task, start_sync_result, start_task
from src.abaqus.case_info import (
    build_settings_groups,
    build_filter_facets,
    case_display_tags,
    extract_case_tags,
    format_timestamp,
    get_case_timing,
    settings_groups_to_dict,
    timing_to_dict,
)
from src.abaqus.trash import make_trash_id, trash_local_case
from src.abaqus.job_status import inspect_job
from src.abaqus.settings import HuBaiAbaqusSettings, list_presets, load_curve_csv
from src.paths import (
    ABAQUS_JOBS,
    ABAQUS_POST,
    CAD_VERIFIED_ROOT,
    EXPORT_ROOT,
    export_dir_for_slug,
    job_dir_for_slug,
    post_dir_for_slug,
)

router = APIRouter(prefix="/api/abaqus", tags=["abaqus-cases"])


def _discover_export_slugs() -> list[str]:
    if not EXPORT_ROOT.is_dir():
        return []
    slugs: set[str] = set()
    for manifest in EXPORT_ROOT.rglob("case_manifest.json"):
        slugs.add(manifest.parent.name)
    for inp in EXPORT_ROOT.rglob("*.inp"):
        if not inp.name.endswith("_cae_mesh.inp") and not inp.name.endswith("_topology_b31.inp"):
            slugs.add(inp.stem)
    return sorted(slugs)


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


_DATA_SOURCE_HINT = (
    "列表与状态均读取本机 output/export、output/jobs、output/post。"
    "若作业仅在 Linux 服务器运行，状态可能滞后；请在「作业监控」开启「远程同步」后再查看。"
)

_DASHBOARD_STATUS_ORDER = ("RUNNING", "COMPLETED", "FAILED", "STOPPED", "WAITING")
_DASHBOARD_CASE_LIMIT = 50


def _has_local_artifacts(slug: str) -> bool:
    export_dir = export_dir_for_slug(slug)
    job_dir = job_dir_for_slug(slug)
    if (export_dir / f"{slug}.inp").is_file():
        return True
    if job_dir.is_dir():
        for name in (f"{slug}.sta", f"{slug}.odb", f"{slug}.lck"):
            if (job_dir / name).is_file():
                return True
    if export_dir.is_dir():
        try:
            return any(export_dir.iterdir())
        except OSError:
            return False
    return False


def _resolve_location(has_local: bool, has_remote: bool) -> tuple[str, str]:
    if has_local and has_remote:
        return "both", "本机+服务器"
    if has_remote:
        return "remote", "服务器"
    return "local", "本机"


def select_dashboard_cases(cases: list[CaseSummary], limit: int = _DASHBOARD_CASE_LIMIT) -> list[CaseSummary]:
    """Prioritize RUNNING/COMPLETED so dashboard table matches summary counts."""
    buckets: dict[str, list[CaseSummary]] = {s: [] for s in _DASHBOARD_STATUS_ORDER}
    other: list[CaseSummary] = []
    for case in cases:
        if case.status in buckets:
            buckets[case.status].append(case)
        else:
            other.append(case)
    for status in _DASHBOARD_STATUS_ORDER:
        buckets[status].sort(key=case_activity_ts, reverse=True)
    other.sort(key=case_activity_ts, reverse=True)

    result: list[CaseSummary] = []
    seen: set[str] = set()
    for status in _DASHBOARD_STATUS_ORDER:
        for case in buckets[status]:
            if case.slug in seen:
                continue
            seen.add(case.slug)
            result.append(case)
    for case in other:
        if case.slug in seen:
            continue
        seen.add(case.slug)
        result.append(case)
    return result[:limit]


def case_activity_ts(case: CaseSummary) -> float:
    """Best-effort recency for sorting dashboard recent list."""
    ts = case.last_activity_at or case.completed_at or case.exported_at or case.modified_at or 0.0
    job_dir = job_dir_for_slug(case.slug)
    for name in (f"{case.slug}.sta", f"{case.slug}.lck"):
        path = job_dir / name
        if path.is_file():
            try:
                ts = max(ts, path.stat().st_mtime)
            except OSError:
                pass
    return ts


def _case_summary(
    slug: str,
    *,
    remote_slugs: set[str] | None = None,
    remote_watch: bool = False,
) -> CaseSummary:
    export_dir = export_dir_for_slug(slug)
    manifest = _load_json(export_dir / "case_manifest.json")
    meta = _load_json(export_dir / f"{slug}_meta.json")
    progress = inspect_job(slug, remote_watch=remote_watch)
    mtime = None
    if export_dir.is_dir():
        try:
            mtime = export_dir.stat().st_mtime
        except OSError:
            pass
    tag_fields = extract_case_tags(manifest, meta)
    Q_raw = tag_fields.get("Q")
    variant = tag_fields.get("variant")
    post_csv = post_dir_for_slug(slug) / f"{slug}_stress_strain.csv"
    timing = get_case_timing(slug)
    last_activity = timing.completed_at or timing.exported_at or mtime
    job_dir = job_dir_for_slug(slug)
    sta = job_dir / f"{slug}.sta"
    if sta.is_file():
        try:
            last_activity = max(last_activity or 0, sta.stat().st_mtime)
        except OSError:
            pass
    has_local = _has_local_artifacts(slug)
    has_remote = bool(remote_slugs and slug in remote_slugs)
    location, location_label = _resolve_location(has_local, has_remote)
    return CaseSummary(
        slug=slug,
        variant=variant,
        Q=float(Q_raw) if Q_raw is not None else None,
        status=progress.state.value,
        has_inp=(export_dir / f"{slug}.inp").is_file(),
        has_odb=progress.odb_path.is_file(),
        has_curve=post_csv.is_file(),
        export_dir=str(export_dir),
        modified_at=mtime,
        exported_at=timing.exported_at,
        exported_at_label=format_timestamp(timing.exported_at),
        completed_at=timing.completed_at,
        completed_at_label=format_timestamp(timing.completed_at),
        wallclock_seconds=timing.wallclock_seconds,
        last_activity_at=last_activity,
        data_source="local+remote" if has_remote else "local",
        location=location,
        location_label=location_label,
        has_local=has_local,
        has_remote=has_remote,
        material=tag_fields.get("material"),
        element_type=tag_fields.get("element_type"),
        cae_seed_mm=tag_fields.get("cae_seed_mm"),
        target_strain=tag_fields.get("target_strain"),
        load_rate_mm_min=tag_fields.get("load_rate_mm_min"),
        explicit_dt=tag_fields.get("explicit_dt"),
        step_time_s=tag_fields.get("step_time_s"),
        cells=tag_fields.get("cells"),
        profile=tag_fields.get("profile"),
        mesh_quality=tag_fields.get("mesh_quality"),
        tags={k: v for k, v in tag_fields.items() if v is not None},
        display_tags=case_display_tags(tag_fields),
    )


def _build_case_list(summaries: list[CaseSummary]) -> CaseListResponse:
    case_dicts = [c.model_dump() for c in summaries]
    return CaseListResponse(
        data_source="local",
        data_source_label="本机 output/",
        hint=_DATA_SOURCE_HINT,
        cases=summaries,
        filter_facets=build_filter_facets(case_dicts),
    )


@router.get("/cases", response_model=CaseListResponse)
def list_cases(
    status: str | None = Query(None, description="Filter by RUNNING|COMPLETED|FAILED|STOPPED|WAITING"),
    discover_remote: bool = Query(False, description="Merge remote output/jobs slugs"),
) -> CaseListResponse:
    return list_cases_impl(status, discover_remote=discover_remote)


def list_cases_impl(
    status: str | None = None,
    *,
    discover_remote: bool = False,
    remote_slugs: list[str] | None = None,
) -> CaseListResponse:
    slugs = set(_discover_export_slugs())
    if ABAQUS_JOBS.is_dir():
        for d in ABAQUS_JOBS.iterdir():
            if d.is_dir():
                slugs.add(d.name)
    if remote_slugs:
        slugs.update(remote_slugs)
    elif discover_remote:
        slugs.update(list_remote_job_slugs())
    if remote_slugs:
        remote_set = set(remote_slugs)
    elif discover_remote:
        remote_set = set(list_remote_job_slugs())
    else:
        remote_set = set()
    summaries = [
        _case_summary(s, remote_slugs=remote_set, remote_watch=discover_remote)
        for s in sorted(slugs)
    ]
    if status:
        status_upper = status.upper()
        summaries = [c for c in summaries if c.status == status_upper]
    hint = _DATA_SOURCE_HINT
    label = "本机 output/"
    if discover_remote or remote_slugs:
        hint = (
            "列表包含本机 output/ 与服务器 output/jobs 中的算例。"
            "状态文件需先执行「同步服务器 output」。"
        )
        label = "本机 + 已纳入远程算例"
    case_dicts = [c.model_dump() for c in summaries]
    return CaseListResponse(
        data_source="local+remote" if (discover_remote or remote_slugs) else "local",
        data_source_label=label,
        hint=hint,
        cases=summaries,
        filter_facets=build_filter_facets(case_dicts),
    )


@router.get("/cases/{slug}", response_model=CaseDetail)
def get_case(slug: str) -> CaseDetail:
    export_dir = export_dir_for_slug(slug)
    if not export_dir.is_dir() and not job_dir_for_slug(slug).is_dir():
        raise HTTPException(status_code=404, detail=f"Case not found: {slug}")
    manifest = _load_json(export_dir / "case_manifest.json")
    meta = _load_json(export_dir / f"{slug}_meta.json")
    progress = inspect_job(slug)
    paths = {
        "export_dir": export_dir.is_dir(),
        "job_dir": job_dir_for_slug(slug).is_dir(),
        "post_dir": post_dir_for_slug(slug).is_dir(),
        "inp": (export_dir / f"{slug}.inp").is_file(),
        "odb": progress.odb_path.is_file(),
        "sta": progress.sta_path.is_file(),
        "curve_csv": (post_dir_for_slug(slug) / f"{slug}_stress_strain.csv").is_file(),
        "curve_png": (post_dir_for_slug(slug) / f"{slug}_stress_strain.png").is_file(),
    }
    return CaseDetail(
        slug=slug,
        manifest=manifest,
        meta=meta,
        status=progress.state.value,
        paths=paths,
        settings_groups=settings_groups_to_dict(build_settings_groups(manifest, meta)),
        timing=timing_to_dict(get_case_timing(slug)),
    )


@router.get("/cases/{slug}/curve", response_model=CurveResponse)
def get_curve(slug: str) -> CurveResponse:
    post_dir = post_dir_for_slug(slug)
    csv_path = post_dir / f"{slug}_stress_strain.csv"
    if not csv_path.is_file():
        raise HTTPException(status_code=404, detail="Curve CSV not found")
    yield_path = post_dir / f"{slug}_yield.json"
    yield_data = _load_json(yield_path) if yield_path.is_file() else None
    return CurveResponse(slug=slug, points=load_curve_csv(csv_path), yield_data=yield_data)


@router.get("/cases/{slug}/artifacts", response_model=list[ArtifactInfo])
def list_artifacts(slug: str) -> list[ArtifactInfo]:
    artifacts: list[ArtifactInfo] = []
    for label, base in (
        ("export", export_dir_for_slug(slug)),
        ("job", job_dir_for_slug(slug)),
        ("post", post_dir_for_slug(slug)),
    ):
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir()):
            if not path.is_file():
                continue
            kind = path.suffix.lstrip(".") or "file"
            artifacts.append(
                ArtifactInfo(
                    name=path.name,
                    path=str(path),
                    size_bytes=path.stat().st_size,
                    kind=f"{label}/{kind}",
                )
            )
    return artifacts


@router.get("/cad/verified")
def list_verified_cad() -> list[dict]:
    if not CAD_VERIFIED_ROOT.is_dir():
        return []
    steps = sorted(CAD_VERIFIED_ROOT.glob("*.step")) + sorted(CAD_VERIFIED_ROOT.glob("*.STEP"))
    return [
        {
            "name": p.name,
            "path": str(p),
            "size_bytes": p.stat().st_size,
        }
        for p in steps
    ]


@router.get("/presets")
def get_presets() -> dict:
    return list_presets()


@router.post("/settings/preview")
def preview_settings(settings: dict) -> dict:
    cfg = HuBaiAbaqusSettings.from_dict(settings)
    return cfg.to_dict()


@router.delete("/cases/{slug}", response_model=TaskResponse)
def delete_case(
    slug: str,
    scope: str = Query("local", description="local | remote | both"),
    remote_host: str = "",
    remote_root: str = "",
    clear_active: bool = True,
) -> TaskResponse:
    """Move case directories to recycle bin. Local trash returns immediately; remote is async."""
    scope = scope.lower()
    if scope not in ("local", "remote", "both"):
        raise HTTPException(status_code=400, detail="scope must be local, remote, or both")

    local_result = None
    trash_id: str | None = None
    if scope in ("local", "both"):
        local_result = trash_local_case(slug, clear_active=clear_active)
        trash_id = local_result.get("trash_id")  # type: ignore[assignment]

    if scope == "remote":
        trash_id = make_trash_id(slug)
        task = start_task(
            run_remote_trash(slug, trash_id, remote_host=remote_host, remote_root=remote_root),
            slug=slug,
        )
        return TaskResponse(**task)

    # local or both — respond synchronously for local trash
    result: dict[str, object] = {"local": local_result, "scope": scope}
    remote_task_id = None
    if scope == "both":
        tid = trash_id or make_trash_id(slug)
        remote_task = start_task(
            run_remote_trash(slug, tid, remote_host=remote_host, remote_root=remote_root),
            slug=slug,
        )
        remote_task_id = remote_task["task_id"]
        result["remote_task_id"] = remote_task_id
        result["remote_note"] = "远程移入回收站已在后台执行；失败不影响本机结果。"

    sync = start_sync_result(slug=slug, result=result)
    return TaskResponse(**sync)
