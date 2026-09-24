"""
Hard CAD delivery for HuBai unitcells (experiment isolation).

CAD gate (non-negotiable for delivery):
  - True B-Rep STEP and/or Parasolid .x_t only
  - No STL, no faceted/triangle STEP, no capillary/Taubin mesh products
  - No chamfer pretending to be fillet

Policy:
  Q=0, 0.5 → slot MakeFillet hard STEP (proven)
  Q=1, 1.5 → prefer SolidWorks sequential hub fillet (sw_fillet);
             else bare hard STEP with fillet=unsupported
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from typing import Any

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _bbox_span,
    _q_slug,
    _write_step_hard_solid,
    default_rf_for_q,
    export_slot_fillet,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology

CAD_GATE = {
    "allowed_formats": ["hard_step", "x_t"],
    "forbidden": [
        "stl",
        "faceted_step",
        "make_shape_on_mesh",
        "capillary_mesh",
        "taubin_mesh",
        "chamfer_as_fillet",
    ],
    "note": (
        "Delivery must be true B-Rep STEP or Parasolid x_t. "
        "Mesh / triangular faceted STEP is not acceptable CAD."
    ),
}


def delivery_out_dir(base: str | None = None) -> str:
    root = base or default_exp_out_dir()
    # Idempotent: if caller already passed the delivery dir, do not nest.
    if os.path.basename(os.path.normpath(root)) == "_hard_cad_delivery":
        path = root
    else:
        path = os.path.join(root, "_hard_cad_delivery")
    os.makedirs(path, exist_ok=True)
    return path


def _copy_into_delivery(
    src: str,
    out_dir: str,
    dest_name: str,
) -> str:
    dest = os.path.join(out_dir, dest_name)
    if os.path.abspath(src) != os.path.abspath(dest):
        shutil.copy2(src, dest)
    return os.path.abspath(dest)


def export_bare_hard_step(
    *,
    period_factor: float,
    out_dir: str,
    cell_size_mm: float = 20.0,
    rod_d_mm: float = 2.0,
    amplitude_mm: float = 2.0,
    n_segments: int = 32,
    force: bool = False,
) -> dict[str, Any]:
    """Bare octant-fuse unitcell → hard STEP; fillet marked unsupported."""
    q = float(period_factor)
    slug = (
        f"exp_hardBare_af{int(round(amplitude_mm))}q{_q_slug(q)}"
        f"_L{int(round(cell_size_mm))}"
        f"_d{str(rod_d_mm).replace('.', 'p')}_1x1"
    )
    step_path = os.path.join(out_dir, f"{slug}.step")
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")

    if (
        not force
        and os.path.isfile(step_path)
        and os.path.getsize(step_path) > 1000
        and os.path.isfile(man_path)
    ):
        with open(man_path, encoding="utf-8") as f:
            return json.load(f)

    fp = ExpFilletParams(
        cell_size_mm=cell_size_mm,
        rod_d_mm=rod_d_mm,
        amplitude_mm=amplitude_mm,
        period_factor=q,
        n_segments=n_segments,
    )
    print(f"  [hardCAD] bare fuse Q={q:g} ...", flush=True)
    bare, mass_bare, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    span = _bbox_span(bare)
    rb = _write_step_hard_solid(
        bare,
        step_path,
        mass_ref=float(mass_bare),
        max_drift=1.2,
        max_span_mm=float(cell_size_mm) * 1.35,
    )
    topo = ocp_shape_topology(rb, check_brep=True)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"bare hard STEP solids={topo.get('solids')}")
    if not bool(topo.get("brep_valid")):
        raise RuntimeError("bare hard STEP brep_valid=False")

    man: dict[str, Any] = {
        "experiment": "hard_cad_delivery",
        "cad_gate": CAD_GATE,
        "cad_format": "hard_step",
        "fillet": "unsupported",
        "period_factor": q,
        "slug": slug,
        "step_path": os.path.abspath(step_path),
        "xt_path": None,
        "fuse": {
            "method": fuse_tag,
            "mass_bare_mm3": float(mass_bare),
            "attempts": fuse_attempts,
        },
        "mass_mm3": float(ocp_mass(rb)),
        "topology": topo,
        "span": list(span),
        "params": {
            "cell_size_mm": cell_size_mm,
            "rod_d_mm": rod_d_mm,
            "amplitude_mm": amplitude_mm,
            "n_segments": n_segments,
        },
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)
    print(
        f"  [hardCAD] bare Q={q:g} mass={man['mass_mm3']:.2f} "
        f"valid={topo.get('brep_valid')} → {step_path}",
        flush=True,
    )
    return man


def export_filleted_hard_step(
    *,
    period_factor: float,
    out_dir: str,
    force: bool = False,
) -> dict[str, Any]:
    """Q=0/0.5 slot MakeFillet → copy into delivery dir; reject chamfer."""
    q = float(period_factor)
    rf = default_rf_for_q(q)
    params = SlotFilletParams(period_factor=q, r_blend_factor=float(rf))
    # Export into parent exp dir first (existing API), then promote to delivery
    print(f"  [hardCAD] slot MakeFillet Q={q:g} rf={rf:g} ...", flush=True)
    man0 = export_slot_fillet(params, out_dir=default_exp_out_dir(), force=force)
    if man0.get("used_chamfer_fallback"):
        raise RuntimeError(
            f"Q={q:g}: chamfer fallback is forbidden under hard CAD gate"
        )
    fil = man0.get("fillet") or {}
    mode = str(fil.get("mode") or "")
    if "chamfer" in mode.lower():
        raise RuntimeError(f"Q={q:g}: fillet mode is chamfer ({mode})")

    src_step = man0.get("step_path")
    if not src_step or not os.path.isfile(src_step):
        raise RuntimeError(f"Q={q:g}: missing fillet STEP")

    slug = (
        f"exp_hardFillet_af{int(round(params.amplitude_mm))}q{_q_slug(q)}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_rf{str(rf).replace('.', 'p')}_1x1"
    )
    step_path = _copy_into_delivery(src_step, out_dir, f"{slug}.step")
    bare_src = man0.get("bare_step_path")
    bare_dest = None
    if bare_src and os.path.isfile(bare_src):
        bare_dest = _copy_into_delivery(bare_src, out_dir, f"{slug}_bare.step")

    topo = man0.get("topology") or {}
    man: dict[str, Any] = {
        "experiment": "hard_cad_delivery",
        "cad_gate": CAD_GATE,
        "cad_format": "hard_step",
        "fillet": "slot_makefillet",
        "period_factor": q,
        "slug": slug,
        "step_path": step_path,
        "bare_step_path": bare_dest,
        "xt_path": None,
        "source_slot_fillet_manifest": man0,
        "mass_mm3": man0.get("mass_mm3"),
        "topology": topo,
        "fillet_detail": fil,
        "params": asdict(params),
    }
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)
    print(
        f"  [hardCAD] fillet Q={q:g} mass={man.get('mass_mm3')} → {step_path}",
        flush=True,
    )
    return man


def try_convert_xt(step_path: str, out_dir: str) -> dict[str, Any]:
    """Best-effort STEP → x_t via SolidWorks; never fails the delivery."""
    try:
        from src.export.sw_parasolid import convert_step_to_xt
    except Exception as exc:
        return {"ok": False, "error": f"import convert_step_to_xt: {exc}"}

    base = os.path.splitext(os.path.basename(step_path))[0]
    xt_path = os.path.join(out_dir, f"{base}.x_t")
    try:
        print(f"  [hardCAD] STEP→x_t {step_path} ...", flush=True)
        convert_step_to_xt(step_path, xt_path)
        if os.path.isfile(xt_path) and os.path.getsize(xt_path) > 500:
            return {"ok": True, "xt_path": os.path.abspath(xt_path)}
        return {"ok": False, "error": "x_t missing or tiny after convert"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:400]}


def promote_sw_fillet_win(
    *,
    probe_row: dict[str, Any],
    out_dir: str | None = None,
    cell_size_mm: float = 20.0,
    rod_d_mm: float = 2.0,
    amplitude_mm: float = 2.0,
) -> dict[str, Any]:
    """
    Promote a successful SW sequential fillet probe into delivery root.

    Expects probe_row keys: Q, step_path, xt_path, radius_mm,
    n_edges_filleted, n_edges_attempted (optional).
    """
    from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

    out_dir = delivery_out_dir(out_dir)
    q = float(probe_row["Q"])
    src_step = str(probe_row.get("step_path") or "")
    src_xt = str(probe_row.get("xt_path") or "")
    if not src_step or not os.path.isfile(src_step):
        raise RuntimeError(f"Q={q:g}: missing SW fillet STEP")
    if os.path.getsize(src_step) < 1000:
        raise RuntimeError(f"Q={q:g}: SW fillet STEP too small")

    r = probe_row.get("radius_mm")
    n_ok = int(probe_row.get("n_edges_filleted") or 0)
    n_try = int(probe_row.get("n_edges_attempted") or 0)
    r_slug = str(r).replace(".", "p") if r is not None else "na"
    slug = (
        f"exp_hardSwFillet_af{int(round(amplitude_mm))}q{_q_slug(q)}"
        f"_L{int(round(cell_size_mm))}"
        f"_d{str(rod_d_mm).replace('.', 'p')}"
        f"_r{r_slug}_n{n_ok}_1x1"
    )
    step_path = _copy_into_delivery(src_step, out_dir, f"{slug}.step")
    xt_path = None
    if src_xt and os.path.isfile(src_xt) and os.path.getsize(src_xt) > 500:
        xt_path = _copy_into_delivery(src_xt, out_dir, f"{slug}.x_t")

    shape = ocp_read_step_shape(step_path)
    topo = ocp_shape_topology(shape, check_brep=True)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"Q={q:g} SW fillet solids={topo.get('solids')}")
    if not bool(topo.get("brep_valid")):
        raise RuntimeError(f"Q={q:g} SW fillet brep_valid=False")

    mass = float(ocp_mass(shape))
    span = _bbox_span(shape)
    man: dict[str, Any] = {
        "experiment": "hard_cad_delivery",
        "cad_gate": CAD_GATE,
        "cad_format": "hard_step+x_t" if xt_path else "hard_step",
        "fillet": "sw_fillet",
        "period_factor": q,
        "slug": slug,
        "step_path": step_path,
        "xt_path": xt_path,
        "mass_mm3": mass,
        "topology": topo,
        "span": list(span),
        "fillet_detail": {
            "mode": "sw_sequential_hub_edge",
            "radius_mm": r,
            "n_edges_filleted": n_ok,
            "n_edges_attempted": n_try,
            "n_hub_candidates": probe_row.get("n_hub_candidates"),
            "note": (
                "Partial hub fillet via SolidWorks FeatureFillet3 "
                "(one edge at a time); not full OCC MakeFillet."
            ),
        },
        "source_probe": {
            "step_in": probe_row.get("step_in"),
            "probe_step": os.path.abspath(src_step),
            "probe_xt": os.path.abspath(src_xt) if src_xt else None,
        },
        "params": {
            "cell_size_mm": cell_size_mm,
            "rod_d_mm": rod_d_mm,
            "amplitude_mm": amplitude_mm,
        },
    }
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)
    print(
        f"  [hardCAD] promote sw_fillet Q={q:g} n={n_ok}/{n_try} "
        f"mass={mass:.2f} valid={topo.get('brep_valid')} → {step_path}",
        flush=True,
    )
    return man


def promote_sw_fillet_probe_summary(
    *,
    probe_summary_path: str | None = None,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Promote all ok rows from sw_fillet_probe_summary.json into delivery."""
    out_dir = delivery_out_dir(out_dir)
    if probe_summary_path is None:
        probe_summary_path = os.path.join(
            out_dir, "_sw_fillet_probe", "sw_fillet_probe_summary.json"
        )
    with open(probe_summary_path, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        raise RuntimeError("probe summary must be a list")

    promoted: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("ok"):
            continue
        man = promote_sw_fillet_win(probe_row=row, out_dir=out_dir)
        promoted.append(man)

    # Refresh delivery_summary: keep Q=0/0.5 rows; replace Q>=1 with sw wins
    summary_path = os.path.join(out_dir, "delivery_summary.json")
    existing_rows: list[dict[str, Any]] = []
    if os.path.isfile(summary_path):
        with open(summary_path, encoding="utf-8") as f:
            prev = json.load(f)
        existing_rows = list(prev.get("rows") or [])

    by_q: dict[float, dict[str, Any]] = {}
    for r in existing_rows:
        by_q[float(r["Q"])] = r
    for man in promoted:
        q = float(man["period_factor"])
        by_q[q] = {
            "Q": q,
            "fillet": man.get("fillet"),
            "cad_format": man.get("cad_format"),
            "step_path": man.get("step_path"),
            "xt_path": man.get("xt_path"),
            "mass_mm3": man.get("mass_mm3"),
            "brep_valid": (man.get("topology") or {}).get("brep_valid"),
            "fillet_detail": man.get("fillet_detail"),
            "ok": True,
            "error": None,
        }

    ordered = [by_q[q] for q in sorted(by_q.keys())]
    summary = {
        "experiment": "hard_cad_delivery",
        "cad_gate": CAD_GATE,
        "out_dir": os.path.abspath(out_dir),
        "rows": ordered,
        "n_ok": sum(1 for r in ordered if r.get("ok")),
        "n_total": len(ordered),
        "sw_fillet_promoted": len(promoted),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote {summary_path} (promoted {len(promoted)})", flush=True)
    return summary


def export_four_hard_cad(
    *,
    qs: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5),
    force: bool = False,
    try_xt: bool = True,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Unified four-config hard CAD delivery."""
    out_dir = delivery_out_dir(out_dir)
    gate_path = os.path.join(out_dir, "CAD_GATE.json")
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump(CAD_GATE, f, indent=2)

    rows: list[dict[str, Any]] = []
    for q in qs:
        print(f"\n######## hard CAD Q={q:g} ########", flush=True)
        try:
            if abs(float(q)) < 0.75:
                man = export_filleted_hard_step(
                    period_factor=float(q), out_dir=out_dir, force=force
                )
            else:
                man = export_bare_hard_step(
                    period_factor=float(q), out_dir=out_dir, force=force
                )
            xt_info: dict[str, Any] | None = None
            if try_xt and man.get("step_path"):
                xt_info = try_convert_xt(str(man["step_path"]), out_dir)
                if xt_info.get("ok"):
                    man["xt_path"] = xt_info["xt_path"]
                    man["cad_format"] = "hard_step+x_t"
                    man_path = os.path.join(
                        out_dir, f"{man['slug']}_manifest.json"
                    )
                    with open(man_path, "w", encoding="utf-8") as f:
                        json.dump(man, f, indent=2)
            row = {
                "Q": float(q),
                "fillet": man.get("fillet"),
                "cad_format": man.get("cad_format"),
                "step_path": man.get("step_path"),
                "xt_path": man.get("xt_path"),
                "mass_mm3": man.get("mass_mm3"),
                "brep_valid": (man.get("topology") or {}).get("brep_valid"),
                "xt": xt_info,
                "ok": True,
                "error": None,
            }
        except Exception as exc:
            row = {
                "Q": float(q),
                "ok": False,
                "error": str(exc)[:500],
            }
            print(f"  FAIL Q={q:g}: {exc}", flush=True)
        rows.append(row)
        print(f"  row={row}", flush=True)

    summary = {
        "experiment": "hard_cad_delivery",
        "cad_gate": CAD_GATE,
        "out_dir": os.path.abspath(out_dir),
        "rows": rows,
        "n_ok": sum(1 for r in rows if r.get("ok")),
        "n_total": len(rows),
    }
    summary_path = os.path.join(out_dir, "delivery_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {summary_path}", flush=True)
    print(f"n_ok={summary['n_ok']}/{summary['n_total']}", flush=True)
    return summary
