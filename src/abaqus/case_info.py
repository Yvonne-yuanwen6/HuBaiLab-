"""Structured case parameters and timing for UI display."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.abaqus.job_status import is_job_completed
from src.paths import export_dir_for_slug, job_dir_for_slug, post_dir_for_slug

_WALLCLOCK_RE = re.compile(r"WALLCLOCK TIME \(SEC\)\s*=\s*(\d+)")


@dataclass(frozen=True)
class SettingItem:
    key: str
    label: str
    value: str


@dataclass(frozen=True)
class SettingGroup:
    title: str
    items: list[SettingItem]


@dataclass(frozen=True)
class CaseTiming:
    exported_at: float | None = None
    completed_at: float | None = None
    wallclock_seconds: int | None = None
    odb_size_bytes: int | None = None


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return " × ".join(str(x) for x in value)
    return str(value)


def _item(key: str, label: str, value: Any) -> SettingItem:
    return SettingItem(key=key, label=label, value=_fmt(value))


def parse_sta_wallclock_seconds(sta_path: Path) -> int | None:
    if not sta_path.is_file():
        return None
    text = sta_path.read_text(encoding="utf-8", errors="replace")
    matches = _WALLCLOCK_RE.findall(text)
    if not matches:
        return None
    return int(matches[-1])


def get_case_timing(slug: str) -> CaseTiming:
    export_dir = export_dir_for_slug(slug)
    job_dir = job_dir_for_slug(slug)
    sta = job_dir / f"{slug}.sta"
    odb = job_dir / f"{slug}.odb"
    manifest_path = export_dir / "case_manifest.json"
    meta_path = export_dir / f"{slug}_meta.json"

    exported_at = None
    for candidate in (manifest_path, meta_path, export_dir / f"{slug}.inp"):
        if candidate.is_file():
            try:
                exported_at = candidate.stat().st_mtime
                break
            except OSError:
                pass
    if exported_at is None and export_dir.is_dir():
        try:
            exported_at = export_dir.stat().st_mtime
        except OSError:
            pass

    completed_at = None
    wallclock = parse_sta_wallclock_seconds(sta)
    if is_job_completed(sta, odb):
        try:
            completed_at = odb.stat().st_mtime
        except OSError:
            if sta.is_file():
                completed_at = sta.stat().st_mtime

    odb_size = None
    if odb.is_file():
        try:
            odb_size = odb.stat().st_size
        except OSError:
            pass

    return CaseTiming(
        exported_at=exported_at,
        completed_at=completed_at,
        wallclock_seconds=wallclock,
        odb_size_bytes=odb_size,
    )


def format_timestamp(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def build_settings_groups(
    manifest: dict[str, Any] | None,
    meta: dict[str, Any] | None,
) -> list[SettingGroup]:
    manifest = manifest or {}
    meta = meta or {}
    groups: list[SettingGroup] = []

    paper = manifest.get("paper_params") or {}
    slug_desc = manifest.get("slug_descriptor") or {}
    geom_items = [
        _item("slug", "算例 slug", manifest.get("slug") or meta.get("case_slug")),
        _item("structure", "结构", manifest.get("structure") or slug_desc.get("variant_name")),
        _item("period_factor", "周期因子 Q", slug_desc.get("period_factor")),
        _item("cells", "阵列", paper.get("block_cells") or [meta.get("nx"), meta.get("ny"), meta.get("nz")]),
        _item("cell_size_mm", "单胞边长 (mm)", paper.get("cell_size_mm") or meta.get("cell_size")),
        _item("rod_diameter_mm", "杆径 (mm)", paper.get("rod_diameter_mm")),
        _item("cad_step", "CAD STEP", manifest.get("cad_step")),
        _item("geometry_tag", "几何标识", meta.get("geometry_tag")),
    ]
    groups.append(SettingGroup(title="几何", items=geom_items))

    mesh = manifest.get("mesh") or {}
    mesh_items = [
        _item("method", "网格方法", mesh.get("method")),
        _item("element", "单元类型", mesh.get("cae_element_type") or mesh.get("element") or slug_desc.get("element_type")),
        _item("cae_seed_mm", "CAE seed (mm)", mesh.get("cae_seed_mm") or slug_desc.get("cae_seed_mm")),
        _item("cae_mesh_quality", "网格 preset", mesh.get("cae_mesh_quality") or slug_desc.get("cae_mesh_quality")),
        _item("cae_rods_per_diameter", "杆径方向单元数", mesh.get("cae_rods_per_diameter") or slug_desc.get("cae_rods_per_diameter")),
        _item("cae_virtual_topology", "Virtual Topology", mesh.get("cae_virtual_topology")),
        _item("node_count", "节点数", mesh.get("node_count")),
        _item("element_count", "单元数", mesh.get("element_count")),
        _item("mesh_location", "剖分位置", mesh.get("mesh_location")),
    ]
    groups.append(SettingGroup(title="网格", items=mesh_items))

    material = manifest.get("material") or {}
    mat_items = [
        _item("model", "材料模型", material.get("model") or slug_desc.get("material_model")),
        _item("E_MPa", "弹性模量 E (MPa)", material.get("E_MPa")),
        _item("nu", "泊松比 ν", material.get("nu")),
        _item("yield_MPa", "屈服强度 (MPa)", material.get("yield_MPa")),
        _item("density_kg_m3", "密度 (kg/m³)", material.get("density_kg_m3")),
        _item("fig25_json", "Fig.2.5 曲线", material.get("fig25_json")),
    ]
    groups.append(SettingGroup(title="材料", items=mat_items))

    loading = manifest.get("loading") or meta.get("loading") or {}
    load_items = [
        _item("target_strain", "目标工程应变", loading.get("target_engineering_strain") or slug_desc.get("target_engineering_strain")),
        _item("compression_disp_mm", "压缩位移 (mm)", loading.get("compression_displacement_mm") or meta.get("compression_displacement")),
        _item("step_time_s", "步长 (s)", loading.get("step_time_s") or meta.get("step_time")),
        _item("load_rate_mm_min", "加载速率 (mm/min)", loading.get("load_rate_mm_min")),
        _item("explicit_dt", "显式 dt", loading.get("explicit_dt")),
        _item("explicit_dt_mode", "dt 模式", loading.get("explicit_dt_mode")),
        _item("friction", "摩擦系数", loading.get("friction")),
        _item("contact_store_offsets", "STORE OFFSETS", loading.get("contact_overclosure_store_offsets")),
        _item("contact_settle", "ContactSettle", loading.get("explicit_contact_settle")),
        _item("lattice_self_contact", "自接触", loading.get("lattice_self_contact")),
        _item("profile", "profile", manifest.get("profile")),
        _item("case_suffix", "case suffix", loading.get("case_suffix") or manifest.get("legacy_case_suffix")),
    ]
    groups.append(SettingGroup(title="载荷与接触", items=load_items))

    restart = meta.get("restart_continue")
    if restart:
        restart_items = [
            _item("source_slug", "续算来源", restart.get("source_slug")),
            _item("source_strain", "来源应变", restart.get("source_strain")),
            _item("target_strain", "目标应变", restart.get("target_strain")),
            _item("delta_strain", "增量应变", restart.get("delta_strain")),
            _item("mode", "续算模式", restart.get("mode")),
        ]
        groups.append(SettingGroup(title="显式续算", items=restart_items))

    return groups


def settings_groups_to_dict(groups: list[SettingGroup]) -> list[dict[str, Any]]:
    return [
        {
            "title": g.title,
            "items": [{"key": i.key, "label": i.label, "value": i.value} for i in g.items],
        }
        for g in groups
    ]


CASE_FILTER_FIELD_LABELS: dict[str, str] = {
    "Q": "Q",
    "variant": "结构",
    "material": "材料",
    "element_type": "单元",
    "cae_seed_mm": "seed (mm)",
    "target_strain": "应变",
    "load_rate_mm_min": "加载速率",
    "explicit_dt": "dt",
    "step_time_s": "步长 (s)",
    "cells": "阵列",
    "profile": "profile",
    "mesh_quality": "网格 preset",
}


def _norm_tag_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:g}"
    text = str(value).strip()
    return text or None


def extract_case_tags(
    manifest: dict[str, Any] | None,
    meta: dict[str, Any] | None,
) -> dict[str, str | None]:
    """Normalized string tags for list filtering (from manifest / meta)."""
    manifest = manifest or {}
    meta = meta or {}
    paper = manifest.get("paper_params") or {}
    slug_desc = manifest.get("slug_descriptor") or {}
    mesh = manifest.get("mesh") or {}
    material = manifest.get("material") or {}
    loading = manifest.get("loading") or meta.get("loading") or {}

    cells_raw = paper.get("block_cells") or [meta.get("nx"), meta.get("ny"), meta.get("nz")]
    cells: str | None = None
    if isinstance(cells_raw, (list, tuple)) and cells_raw and all(c is not None for c in cells_raw):
        cells = "×".join(str(c) for c in cells_raw)

    return {
        "Q": _norm_tag_value(
            slug_desc.get("period_factor") or meta.get("period_factor") or meta.get("Q"),
        ),
        "variant": _norm_tag_value(
            manifest.get("structure")
            or slug_desc.get("variant_name")
            or meta.get("variant_name")
            or meta.get("variant"),
        ),
        "material": _norm_tag_value(material.get("model") or slug_desc.get("material_model")),
        "element_type": _norm_tag_value(
            mesh.get("cae_element_type") or mesh.get("element") or slug_desc.get("element_type"),
        ),
        "cae_seed_mm": _norm_tag_value(mesh.get("cae_seed_mm") or slug_desc.get("cae_seed_mm")),
        "target_strain": _norm_tag_value(
            loading.get("target_engineering_strain") or slug_desc.get("target_engineering_strain"),
        ),
        "load_rate_mm_min": _norm_tag_value(loading.get("load_rate_mm_min")),
        "explicit_dt": _norm_tag_value(loading.get("explicit_dt")),
        "step_time_s": _norm_tag_value(loading.get("step_time_s") or meta.get("step_time")),
        "cells": cells,
        "profile": _norm_tag_value(manifest.get("profile")),
        "mesh_quality": _norm_tag_value(
            mesh.get("cae_mesh_quality") or slug_desc.get("cae_mesh_quality"),
        ),
    }


def case_display_tags(tags: dict[str, str | None]) -> list[str]:
    """Compact labels for table chips."""
    out: list[str] = []
    if tags.get("Q") is not None:
        out.append(f"Q={tags['Q']}")
    if tags.get("variant"):
        out.append(tags["variant"])
    if tags.get("material"):
        out.append(tags["material"])
    if tags.get("element_type"):
        out.append(tags["element_type"])
    if tags.get("cae_seed_mm") is not None:
        out.append(f"seed={tags['cae_seed_mm']}")
    if tags.get("target_strain") is not None:
        out.append(f"ε={tags['target_strain']}")
    if tags.get("load_rate_mm_min") is not None:
        out.append(f"{tags['load_rate_mm_min']} mm/min")
    if tags.get("explicit_dt") is not None:
        out.append(f"dt={tags['explicit_dt']}")
    if tags.get("step_time_s") is not None:
        out.append(f"Δt={tags['step_time_s']}s")
    if tags.get("cells"):
        out.append(tags["cells"])
    if tags.get("profile"):
        out.append(tags["profile"])
    if tags.get("mesh_quality"):
        out.append(tags["mesh_quality"])
    return out


def build_filter_facets(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate distinct tag values with counts for UI facets."""
    counts: dict[str, dict[str, int]] = {k: {} for k in CASE_FILTER_FIELD_LABELS}
    for case in cases:
        tags = case.get("tags") or {}
        for key in CASE_FILTER_FIELD_LABELS:
            val = tags.get(key)
            if not val:
                continue
            bucket = counts[key]
            bucket[val] = bucket.get(val, 0) + 1

    facets: list[dict[str, Any]] = []
    for key, label in CASE_FILTER_FIELD_LABELS.items():
        values = counts[key]
        if not values:
            continue
        sorted_vals = sorted(values.items(), key=lambda x: (-x[1], x[0]))
        facets.append(
            {
                "key": key,
                "label": label,
                "values": [{"value": v, "count": n} for v, n in sorted_vals],
            }
        )
    return facets


def timing_to_dict(timing: CaseTiming) -> dict[str, Any]:
    return {
        "exported_at": timing.exported_at,
        "exported_at_label": format_timestamp(timing.exported_at),
        "completed_at": timing.completed_at,
        "completed_at_label": format_timestamp(timing.completed_at),
        "wallclock_seconds": timing.wallclock_seconds,
        "odb_size_bytes": timing.odb_size_bytes,
    }
