"""Pydantic schemas for Abaqus API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CaseSummary(BaseModel):
    slug: str
    variant: str | None = None
    Q: float | None = None
    status: str
    has_inp: bool = False
    has_odb: bool = False
    has_curve: bool = False
    export_dir: str
    modified_at: float | None = None
    exported_at: float | None = None
    exported_at_label: str | None = None
    completed_at: float | None = None
    completed_at_label: str | None = None
    wallclock_seconds: int | None = None
    last_activity_at: float | None = None
    data_source: str = "local"
    material: str | None = None
    element_type: str | None = None
    cae_seed_mm: str | None = None
    target_strain: str | None = None
    load_rate_mm_min: str | None = None
    explicit_dt: str | None = None
    step_time_s: str | None = None
    cells: str | None = None
    profile: str | None = None
    mesh_quality: str | None = None
    tags: dict[str, str | None] = Field(default_factory=dict)
    display_tags: list[str] = Field(default_factory=list)
    location: str = "local"
    location_label: str = "本机"
    has_local: bool = False
    has_remote: bool = False


class FilterFacetValue(BaseModel):
    value: str
    count: int


class FilterFacet(BaseModel):
    key: str
    label: str
    values: list[FilterFacetValue] = Field(default_factory=list)


class CaseListResponse(BaseModel):
    """Case list with data-source hint for the UI."""

    data_source: str = "local"
    data_source_label: str = "本机 output/"
    hint: str = (
        "列表与状态均读取本机 output/export、output/jobs、output/post。"
        "若作业仅在 Linux 服务器运行，状态可能滞后；请在「作业监控」开启「远程同步」后再查看。"
    )
    cases: list[CaseSummary] = Field(default_factory=list)
    filter_facets: list[FilterFacet] = Field(default_factory=list)


class SettingItemModel(BaseModel):
    key: str
    label: str
    value: str


class SettingGroupModel(BaseModel):
    title: str
    items: list[SettingItemModel] = Field(default_factory=list)


class CaseTimingModel(BaseModel):
    exported_at: float | None = None
    exported_at_label: str | None = None
    completed_at: float | None = None
    completed_at_label: str | None = None
    wallclock_seconds: int | None = None
    odb_size_bytes: int | None = None


class CaseDetail(BaseModel):
    slug: str
    manifest: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    status: str
    paths: dict[str, bool] = Field(default_factory=dict)
    settings_groups: list[SettingGroupModel] = Field(default_factory=list)
    timing: CaseTimingModel | None = None


class JobStatusResponse(BaseModel):
    slug: str
    state: str
    failure_reason: str | None = None
    lck_exists: bool = False
    frame: int | None = None
    frames_total: int | None = None
    sim_time_s: float = 0.0
    total_time_s: float = 0.0
    ke: float | None = None
    ie: float | None = None
    progress_pct: float = 0.0
    step_time_s: float | None = None
    target_strain: float | None = None
    eta: str | None = None


class CurveResponse(BaseModel):
    slug: str
    points: list[dict[str, float]]
    yield_data: dict[str, Any] | None = None


class ArtifactInfo(BaseModel):
    name: str
    path: str
    size_bytes: int
    kind: str


class ExportRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class SubmitRequest(BaseModel):
    target: str = "remote"
    cpus: int = 48
    memory_mb: int = 262144
    recover: bool = False
    restart_from: str = ""
    background: bool = True


class SyncRemoteRequest(BaseModel):
    remote_host: str = ""
    remote_root: str = ""


class StopRequest(BaseModel):
    target: str = "remote"
    remote_host: str = ""
    remote_root: str = ""


class TaskResponse(BaseModel):
    task_id: str
    status: str
    command: list[str] = Field(default_factory=list)
    slug: str | None = None
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    created_at: str = ""
    finished_at: str | None = None
    error: str | None = None


class SyncOutputResponse(BaseModel):
    slug_count: int = 0
    synced_slugs: int = 0
    remote_job_count: int = 0
    remote_jobs: list[str] = Field(default_factory=list)
    results: dict[str, Any] = Field(default_factory=dict)


class DashboardSummary(BaseModel):
    active_case: dict[str, Any] | None = None
    running_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    trash_count: int = 0
    recent_cases: list[CaseSummary] = Field(default_factory=list)
    data_source: str = "local"
    data_source_label: str = "本机 output/"
    hint: str = (
        "仪表盘统计来自本机 output/。服务器上的运行中作业需 scp 同步后才会反映在本机状态。"
    )


class TrashItem(BaseModel):
    trash_id: str
    slug: str
    deleted_at: str | None = None
    deleted_at_label: str | None = None
    deleted_at_ts: float | None = None
    had_export: bool = False
    had_jobs: bool = False
    had_post: bool = False
    cleared_active_case: bool | None = None
