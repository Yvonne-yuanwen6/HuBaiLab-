"""Pre-submit penetration (穿模) risk assessment for lattice compression cases."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_STRAIN_LARGE = 0.10
_STRAIN_PAIR_EXTRA = 0.05

_UNION_MESH_SOURCES = frozenset(
    {
        "gmsh_occ_boolean_union_tets",
        "gmsh_step_volume",
        "union_voxel",
        "gmsh_occ",
    }
)

_INP_FOOTER_RE = re.compile(
    r"self_contact=(?P<self_contact>True|False).*?"
    r"contact=(?P<contact>\w+).*?"
    r"disp=(?P<disp>[-\d.eE+]+)/(?P<step_time>[-\d.eE+]+)s",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PenetrationIssue:
    level: str  # error | warn | info
    code: str
    message: str


@dataclass
class PenetrationReport:
    level: str = "ok"  # ok | warn | error
    engineering_strain: float | None = None
    compression_displacement_mm: float | None = None
    reference_height_mm: float | None = None
    lattice_self_contact: bool | None = None
    contact_mode: str | None = None
    inp_has_all_exterior: bool = False
    issues: list[PenetrationIssue] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    checked_at: str = "submit"

    def max_level(self) -> str:
        if any(i.level == "error" for i in self.issues):
            return "error"
        if any(i.level == "warn" for i in self.issues):
            return "warn"
        return "ok"


def build_loading_snapshot(
    compression: Any,
    *,
    meta: Any | None = None,
    extra: dict | None = None,
) -> dict:
    """Snapshot loading/contact fields for case_manifest."""
    disp = float(compression.compression_displacement)
    ref_h = None
    if meta is not None:
        ref_h = getattr(meta, "reference_height_mm", None)
    snap: dict = {
        "compression_displacement_mm": disp,
        "step_time_s": float(compression.step_time),
        "contact_mode": str(compression.contact_mode),
        "lattice_self_contact": bool(compression.lattice_self_contact),
        "fixed_bottom_plate": bool(compression.fixed_bottom_plate),
        "contact_friction": float(compression.contact_friction),
        "explicit_dt": float(compression.resolved_explicit_dt()),
        "loading_direction": str(compression.loading_direction),
    }
    if ref_h and ref_h > 0:
        snap["reference_height_mm"] = float(ref_h)
        snap["target_engineering_strain"] = disp / float(ref_h)
    if extra:
        snap.update(extra)
    return snap


def _parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_inp_footer(inp_text: str) -> dict[str, Any]:
    """Parse compression step footer comment from exported INP."""
    out: dict[str, Any] = {}
    if not inp_text:
        return out
    for line in reversed(inp_text.splitlines()):
        if "self_contact=" not in line or "contact=" not in line:
            continue
        m = _INP_FOOTER_RE.search(line)
        if not m:
            continue
        out["inp_self_contact"] = m.group("self_contact").lower() == "true"
        out["inp_contact_mode"] = m.group("contact").lower()
        out["inp_disp"] = float(m.group("disp"))
        out["inp_step_time"] = float(m.group("step_time"))
        break
    out["inp_has_all_exterior"] = "Contact Inclusions, ALL EXTERIOR" in inp_text
    return out


def _resolve_strain_and_disp(
    manifest: dict | None,
    meta: dict | None,
    inp_parsed: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
    disp = None
    ref_h = None
    strain = None

    if meta:
        disp = _coerce_float(meta.get("compression_displacement"))
        ref_h = _coerce_float(meta.get("reference_height_mm"))

    loading = (manifest or {}).get("loading") or {}
    if disp is None:
        disp = _coerce_float(loading.get("compression_displacement_mm"))
    if ref_h is None:
        ref_h = _coerce_float(loading.get("reference_height_mm"))
    strain = _coerce_float(loading.get("target_engineering_strain"))

    if strain is None and disp is not None and ref_h and ref_h > 0:
        strain = disp / ref_h

    if disp is None and "inp_disp" in inp_parsed:
        disp = abs(float(inp_parsed["inp_disp"]))

    if strain is None and disp is not None and ref_h and ref_h > 0:
        strain = disp / ref_h

    footprint = (manifest or {}).get("footprint_mm") or {}
    if strain is None and disp is not None:
        z = _coerce_float(footprint.get("Z"))
        if z and z > 0:
            ref_h = ref_h or z
            strain = disp / z

    return strain, disp, ref_h


def _resolve_self_contact(
    manifest: dict | None,
    loading: dict,
    inp_parsed: dict[str, Any],
) -> bool | None:
    mesh = (manifest or {}).get("mesh") or {}
    for key in ("lattice_self_contact",):
        v = _parse_bool(loading.get(key))
        if v is not None:
            return v
        v = _parse_bool(mesh.get(key))
        if v is not None:
            return v
    if "inp_self_contact" in inp_parsed:
        return bool(inp_parsed["inp_self_contact"])
    return None


def _resolve_contact_mode(
    loading: dict,
    mesh: dict,
    inp_parsed: dict[str, Any],
) -> str | None:
    for src in (loading, mesh):
        mode = src.get("contact_mode")
        if mode:
            return str(mode).lower()
    if "inp_contact_mode" in inp_parsed:
        return str(inp_parsed["inp_contact_mode"]).lower()
    return None


def _is_union_solid_mesh(manifest: dict | None) -> bool:
    mesh = (manifest or {}).get("mesh") or {}
    source = str(mesh.get("source", "")).lower()
    if source in _UNION_MESH_SOURCES:
        return True
    if "union" in source or mesh.get("union_stl_watertight") is not None:
        return True
    element = str(mesh.get("element", "")).upper()
    return element in ("C3D4",) and "step" in source


def assess_penetration_risk(
    manifest: dict | None = None,
    meta: dict | None = None,
    inp_text: str | None = None,
    *,
    checked_at: str = "submit",
) -> PenetrationReport:
    """Evaluate static penetration risk before Abaqus solve."""
    inp_parsed = parse_inp_footer(inp_text or "")
    loading = (manifest or {}).get("loading") or {}
    mesh = (manifest or {}).get("mesh") or {}

    report = PenetrationReport(checked_at=checked_at)
    report.inp_has_all_exterior = bool(inp_parsed.get("inp_has_all_exterior"))

    strain, disp, ref_h = _resolve_strain_and_disp(manifest, meta, inp_parsed)
    report.engineering_strain = strain
    report.compression_displacement_mm = disp
    report.reference_height_mm = ref_h

    self_contact = _resolve_self_contact(manifest, loading, inp_parsed)
    report.lattice_self_contact = self_contact

    contact_mode = _resolve_contact_mode(loading, mesh, inp_parsed)
    report.contact_mode = contact_mode

    is_union = _is_union_solid_mesh(manifest)

    n_comp = mesh.get("mesh_connected_components")
    if n_comp is not None and int(n_comp) != 1:
        report.issues.append(
            PenetrationIssue(
                "error",
                "mesh_disconnected",
                f"Solid mesh has {n_comp} connected components (expected 1).",
            )
        )

    watertight = mesh.get("union_stl_watertight")
    if watertight is False and is_union:
        report.issues.append(
            PenetrationIssue(
                "error",
                "stl_not_watertight",
                "Union STL is not watertight; geometry may be invalid for solid FEA.",
            )
        )

    body_overlaps = mesh.get("cylinder_body_overlaps")
    mesh_source = str(mesh.get("source", ""))
    if body_overlaps and int(body_overlaps) > 0 and not is_union:
        report.issues.append(
            PenetrationIssue(
                "info",
                "cylinder_body_overlaps",
                f"Raw geometry has {body_overlaps} non-joint cylinder overlaps; "
                "use boolean union for a single watertight solid.",
            )
        )

    manifest_sc = _parse_bool(loading.get("lattice_self_contact"))
    if manifest_sc is None:
        manifest_sc = _parse_bool(mesh.get("lattice_self_contact"))
    inp_sc = inp_parsed.get("inp_self_contact")
    if manifest_sc is not None and inp_sc is not None and manifest_sc != inp_sc:
        report.issues.append(
            PenetrationIssue(
                "warn",
                "self_contact_mismatch",
                f"Manifest lattice_self_contact={manifest_sc} but INP footer self_contact={inp_sc}.",
            )
        )

    large_strain = strain is not None and strain >= _STRAIN_LARGE

    if self_contact is False and large_strain:
        pct = strain * 100.0 if strain is not None else 0.0
        disp_s = f"{disp:.2g} mm" if disp is not None else "?"
        ref_s = f"{ref_h:.2g} mm" if ref_h is not None else "?"
        report.issues.append(
            PenetrationIssue(
                "warn",
                "no_self_contact_large_strain",
                f"lattice_self_contact=false with engineering strain ~{pct:.0f}% "
                f"({disp_s} / {ref_s}); folding may penetrate without self-contact.",
            )
        )
        report.advice.append(
            "Enable lattice_self_contact=True in CompressionSettings, or run a small-displacement pilot first."
        )

    if self_contact is False and contact_mode == "pair":
        threshold = _STRAIN_PAIR_EXTRA if strain is None else strain >= _STRAIN_PAIR_EXTRA
        if threshold:
            report.issues.append(
                PenetrationIssue(
                    "warn",
                    "pair_contact_no_self_contact",
                    "contact_mode=pair without lattice self-contact increases plate–lattice penetration risk.",
                )
            )
            if "Enable lattice_self_contact=True" not in " ".join(report.advice):
                report.advice.append(
                    "Consider contact_mode=coupling_nodes for Explicit loading, or enable self-contact."
                )

    if large_strain and not report.inp_has_all_exterior:
        report.issues.append(
            PenetrationIssue(
                "warn",
                "missing_self_contact_inp",
                f"Engineering strain ~{strain * 100:.0f}% but INP lacks 'Contact Inclusions, ALL EXTERIOR'.",
            )
        )

    if self_contact is True and not report.inp_has_all_exterior and large_strain:
        report.issues.append(
            PenetrationIssue(
                "warn",
                "self_contact_flag_without_inp",
                "Manifest expects self-contact but INP has no ALL EXTERIOR general contact.",
            )
        )

    report.level = report.max_level()
    if report.level == "ok" and not report.advice:
        report.advice.append("No high penetration risk flags detected for this configuration.")
    return report


def report_to_dict(report: PenetrationReport) -> dict:
    return {
        "level": report.level,
        "engineering_strain": report.engineering_strain,
        "compression_displacement_mm": report.compression_displacement_mm,
        "reference_height_mm": report.reference_height_mm,
        "lattice_self_contact": report.lattice_self_contact,
        "contact_mode": report.contact_mode,
        "inp_has_all_exterior": report.inp_has_all_exterior,
        "issues": [
            {"level": i.level, "code": i.code, "message": i.message} for i in report.issues
        ],
        "advice": list(report.advice),
        "checked_at": report.checked_at,
    }


def load_json_dict(path: str | None) -> dict | None:
    if not path:
        return None
    import json
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def assess_case_files(
    *,
    manifest_path: str | None = None,
    meta_path: str | None = None,
    inp_path: str | None = None,
    manifest: dict | None = None,
    meta: dict | None = None,
    checked_at: str = "submit",
) -> PenetrationReport:
    """Load manifest/meta/inp from paths and assess."""
    from pathlib import Path

    man = manifest if manifest is not None else load_json_dict(manifest_path)
    met = meta if meta is not None else load_json_dict(meta_path)
    inp_text = None
    if inp_path:
        p = Path(inp_path)
        if p.is_file():
            inp_text = p.read_text(encoding="utf-8", errors="replace")
    return assess_penetration_risk(man, met, inp_text, checked_at=checked_at)


def update_manifest_penetration_check(
    manifest_path: str,
    *,
    meta_path: str | None = None,
    inp_path: str | None = None,
    active_path: str | None = None,
) -> PenetrationReport:
    """Re-read manifest, assess, write penetration_check back to manifest + active_case."""
    import json
    from pathlib import Path

    mpath = Path(manifest_path)
    data = json.loads(mpath.read_text(encoding="utf-8"))
    report = assess_case_files(
        manifest=data,
        meta_path=meta_path or data.get("meta_json"),
        inp_path=inp_path or data.get("compression_inp"),
        checked_at="export",
    )
    data["penetration_check"] = report_to_dict(report)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    mpath.write_text(text, encoding="utf-8")
    if active_path:
        Path(active_path).write_text(text, encoding="utf-8")
    elif data.get("active_manifest"):
        Path(data["active_manifest"]).write_text(text, encoding="utf-8")
    return report


def format_report_lines(report: PenetrationReport) -> list[str]:
    """Human-readable lines for CLI / PowerShell."""
    lines: list[str] = []
    prefix = {"error": "ERROR", "warn": "WARN", "info": "INFO"}
    for issue in report.issues:
        tag = prefix.get(issue.level, issue.level.upper())
        lines.append(f"[穿模风险 {tag}] {issue.message}")
    if report.engineering_strain is not None:
        lines.insert(
            0,
            f"Engineering strain: {report.engineering_strain * 100:.1f}% "
            f"(disp={report.compression_displacement_mm} mm, H={report.reference_height_mm} mm)",
        )
    for tip in report.advice:
        lines.append(f"建议: {tip}")
    return lines
