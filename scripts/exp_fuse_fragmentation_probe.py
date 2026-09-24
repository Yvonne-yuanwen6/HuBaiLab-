"""
Fuse-side hub fragmentation probe (experiment isolation).

Sweeps n_segments × fuse_order for Q=1 / Q=1.5 bare glue, reports hub edge
metrics (count, mean length, face-pair singles, plane-chain multi groups).
Does NOT run SW fillet or change delivery defaults.

  py -3 scripts/exp_fuse_fragmentation_probe.py
  py -3 scripts/exp_fuse_fragmentation_probe.py --qs 1.0 --nseg 16 24 32 --orders default vertical_first
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.centre_edge_fillet import _edge_faces
from src.export.exp_node_transition.plane_chain_edge_heal import (
    PlaneChainParams,
    collect_hub_edges,
    diagnose_plane_chains,
)
from src.export.ocp_unitcell_fuse import (
    FUSE_ORDER_PRESETS,
    export_q1_ocp_glue_unitcell,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)


def _face_key(face: Any) -> int:
    try:
        return hash(
            (
                face.TShape().get(),
                str(face.Location().Transformation().TranslationPart()),
            )
        )
    except Exception:
        return id(face)


def hub_edge_metrics(shape: Any, params: PlaneChainParams) -> dict[str, Any]:
    hub = collect_hub_edges(shape, params)
    lengths = [float(h["length_mm"]) for h in hub]
    pair_map: dict[tuple[int, int], int] = defaultdict(int)
    for info in hub:
        faces = info.get("faces") or _edge_faces(shape, info["edge"])
        if len(faces) != 2:
            continue
        a, b = _face_key(faces[0]), _face_key(faces[1])
        key = (min(a, b), max(a, b))
        pair_map[key] += 1
    n_multi = sum(1 for n in pair_map.values() if n >= 2)
    n_single = sum(1 for n in pair_map.values() if n == 1)
    diag = diagnose_plane_chains(shape, params)
    group_summary = {
        g: {
            "n_edges": diag["groups"][g]["n_edges"],
            "n_chains": diag["groups"][g]["n_chains"],
            "n_multi_chains": diag["groups"][g]["n_multi_chains"],
            "mean_edges_per_chain": diag["groups"][g]["mean_edges_per_chain"],
        }
        for g in ("bot", "top", "cross")
        if g in diag["groups"]
    }
    return {
        "n_hub_edges": len(hub),
        "mean_edge_len_mm": float(np.mean(lengths)) if lengths else 0.0,
        "median_edge_len_mm": float(np.median(lengths)) if lengths else 0.0,
        "max_edge_len_mm": float(np.max(lengths)) if lengths else 0.0,
        "min_edge_len_mm": float(np.min(lengths)) if lengths else 0.0,
        "n_face_pairs": len(pair_map),
        "n_face_pairs_multi": n_multi,
        "n_face_pairs_single": n_single,
        "plane_chain": {
            "hypothesis_ok": diag.get("hypothesis_ok"),
            "n_groups_with_multi_chain": diag.get("n_groups_with_multi_chain"),
            "groups": group_summary,
        },
    }


def _fuse_attempts(
    pipe_mode: str,
    strategy: str,
    fuzzy_mm: float,
    *,
    with_fallback: bool,
) -> list[tuple[str, float]]:
    """Primary recipe first; optional GlueFull / higher fuzzy fallbacks."""
    primary = (strategy, float(fuzzy_mm))
    if not with_fallback:
        return [primary]
    fz = float(fuzzy_mm)
    out: list[tuple[str, float]] = [primary]
    for cand in (
        ("sequential_glue_shift", max(fz, 0.05)),
        ("sequential_glue_full", max(fz, 0.08)),
        ("batch_glue_shift", max(fz, 0.05)),
        ("sequential_glue_full", max(fz, 0.12)),
    ):
        if cand not in out:
            out.append(cand)
    return out


def run_one(
    *,
    q: float,
    n_segments: int,
    order_name: str,
    out_dir: str,
    write_step: bool,
    pipe_mode: str,
    strategy: str,
    fuzzy_mm: float,
    with_fallback: bool,
) -> dict[str, Any]:
    order = FUSE_ORDER_PRESETS[order_name]
    params = ExpFilletParams(
        period_factor=float(q),
        n_segments=int(n_segments),
        amplitude_mm=2.0,
        rod_d_mm=2.0,
        cell_size_mm=20.0,
        fuse_fuzzy_mm=float(fuzzy_mm),
    )
    slug = (
        f"fuseFrag_q{str(q).replace('.', 'p')}"
        f"_nseg{n_segments}_{order_name}_{pipe_mode}"
    )
    print(
        f"\n######## {slug} primary={strategy} fuzzy={fuzzy_mm:g} "
        f"fallback={with_fallback} ########",
        flush=True,
    )
    parts = load_fillet_pipe_parts(params)
    step_path = os.path.join(out_dir, f"{slug}.step")
    row: dict[str, Any] = {
        "slug": slug,
        "Q": float(q),
        "n_segments": int(n_segments),
        "order_name": order_name,
        "fuse_order": list(order),
        "pipe_mode": pipe_mode,
        "strategy_requested": strategy,
        "fuzzy_requested_mm": float(fuzzy_mm),
        "ok": False,
        "attempts": [],
    }
    last_exc: Exception | None = None
    for strat, fz in _fuse_attempts(
        pipe_mode, strategy, fuzzy_mm, with_fallback=with_fallback
    ):
        attempt: dict[str, Any] = {
            "strategy": strat,
            "fuzzy_mm": float(fz),
            "ok": False,
        }
        try:
            print(f"  try {pipe_mode} + {strat} fuzzy={fz:g} ...", flush=True)
            rep = export_q1_ocp_glue_unitcell(
                parts,
                step_path,
                cell_size_mm=float(params.cell_size_mm),
                strategy=strat,  # type: ignore[arg-type]
                fuzzy_mm=float(fz),
                pipe_mode=pipe_mode,  # type: ignore[arg-type]
                fuse_order=order,
                write_step=False,
            )
            shape = rep.pop("shape")
            mass = float(rep.get("merged_mass_mm3") or ocp_mass(shape))
            if mass <= 1.0:
                raise RuntimeError(f"empty/near-empty mass={mass}")
            topo = ocp_shape_topology(shape, check_brep=True)
            if int(topo.get("solids") or 0) != 1:
                raise RuntimeError(f"solids={topo.get('solids')}")
            pc = PlaneChainParams(period_factor=float(q), n_segments=int(n_segments))
            metrics = hub_edge_metrics(shape, pc)
            if write_step:
                ocp_write_step(shape, step_path)
                row["step_path"] = os.path.abspath(step_path)
            attempt.update({"ok": True, "mass_mm3": mass})
            row["attempts"].append(attempt)
            row.update(
                {
                    "ok": True,
                    "strategy": strat,
                    "fuzzy_mm": float(fz),
                    "mass_mm3": mass,
                    "topology": {
                        "solids": topo.get("solids"),
                        "faces": topo.get("faces"),
                        "brep_valid": topo.get("brep_valid"),
                    },
                    "hub": metrics,
                    "fuse_desc": rep.get("fuse_strategy"),
                }
            )
            print(
                f"  OK mass={mass:.2f} faces={topo.get('faces')} "
                f"hub_edges={metrics['n_hub_edges']} "
                f"mean_len={metrics['mean_edge_len_mm']:.3f} "
                f"pair_multi={metrics['n_face_pairs_multi']}",
                flush=True,
            )
            return row
        except Exception as exc:
            last_exc = exc
            attempt["error"] = str(exc)[:300]
            row["attempts"].append(attempt)
            print(f"  FAIL ({strat}@{fz:g}): {exc}", flush=True)
    row["error"] = str(last_exc)[:400] if last_exc else "all attempts failed"
    return row


def main() -> int:
    p = argparse.ArgumentParser(description="Fuse fragmentation probe (nseg × order)")
    p.add_argument("--qs", type=float, nargs="+", default=[1.0, 1.5])
    p.add_argument("--nseg", type=int, nargs="+", default=[16, 24, 32])
    p.add_argument(
        "--orders",
        nargs="+",
        default=["default", "vertical_first", "z_pos_first"],
        choices=sorted(FUSE_ORDER_PRESETS.keys()),
    )
    p.add_argument(
        "--pipe-modes",
        nargs="+",
        default=["both_end_extension"],
        help="Q=1 may also try centre_stub; Q=1.5 usually needs both_end_extension",
    )
    p.add_argument("--strategy", default="sequential_glue_shift")
    p.add_argument("--fuzzy", type=float, default=0.02)
    p.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable GlueFull / higher-fuzzy retries (strict primary only)",
    )
    p.add_argument("--write-step", action="store_true")
    args = p.parse_args()

    out_dir = os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_fuse_frag_probe"
    )
    os.makedirs(out_dir, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for q in args.qs:
        modes = list(args.pipe_modes)
        # centre_stub is empty for Q≈1.5; skip unless user forced only that mode
        if abs(float(q) - 1.5) < 1e-9 and "both_end_extension" in modes:
            modes = [m for m in modes if m != "centre_stub"] or modes
        for nseg in args.nseg:
            for order_name in args.orders:
                for pipe_mode in modes:
                    row = run_one(
                        q=float(q),
                        n_segments=int(nseg),
                        order_name=str(order_name),
                        out_dir=out_dir,
                        write_step=bool(args.write_step),
                        pipe_mode=str(pipe_mode),
                        strategy=str(args.strategy),
                        fuzzy_mm=float(args.fuzzy),
                        with_fallback=not bool(args.no_fallback),
                    )
                    rows.append(row)

    # Ranking: prefer fewer hub edges, longer mean length
    scored = []
    for r in rows:
        if not r.get("ok"):
            continue
        hub = r["hub"]
        score = float(hub["mean_edge_len_mm"]) / max(int(hub["n_hub_edges"]), 1)
        scored.append(
            {
                **{
                    k: r[k]
                    for k in (
                        "slug",
                        "Q",
                        "n_segments",
                        "order_name",
                        "pipe_mode",
                        "strategy",
                        "fuzzy_mm",
                        "mass_mm3",
                    )
                },
                "hub": hub,
                "score_meanLen_over_nHub": score,
            }
        )
    scored.sort(key=lambda x: (-float(x["Q"]), -float(x["score_meanLen_over_nHub"])))

    # Compact matrix for quick reading
    matrix: list[dict[str, Any]] = []
    for r in rows:
        entry: dict[str, Any] = {
            "Q": r.get("Q"),
            "n_segments": r.get("n_segments"),
            "order": r.get("order_name"),
            "pipe_mode": r.get("pipe_mode"),
            "ok": bool(r.get("ok")),
        }
        if r.get("ok"):
            h = r["hub"]
            entry.update(
                {
                    "strategy": r.get("strategy"),
                    "fuzzy_mm": r.get("fuzzy_mm"),
                    "mass_mm3": round(float(r["mass_mm3"]), 2),
                    "faces": r["topology"].get("faces"),
                    "n_hub": h["n_hub_edges"],
                    "mean_len": round(float(h["mean_edge_len_mm"]), 3),
                    "pair_single": h["n_face_pairs_single"],
                    "pair_multi": h["n_face_pairs_multi"],
                    "plane_multi_groups": h["plane_chain"].get(
                        "n_groups_with_multi_chain"
                    ),
                }
            )
        else:
            entry["error"] = r.get("error", "")[:160]
        matrix.append(entry)

    summary = {
        "experiment": "fuse_fragmentation_probe",
        "out_dir": os.path.abspath(out_dir),
        "n_ok": sum(1 for r in rows if r.get("ok")),
        "n_total": len(rows),
        "matrix": matrix,
        "rows": rows,
        "ranked_by_meanLen_over_nHub": scored,
    }
    summary_path = os.path.join(out_dir, "fuse_frag_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {summary_path}", flush=True)
    print(f"n_ok={summary['n_ok']}/{summary['n_total']}", flush=True)
    print("\nMatrix (ok rows):", flush=True)
    for m in matrix:
        if not m.get("ok"):
            print(
                f"  FAIL Q={m['Q']} nseg={m['n_segments']} order={m['order']} "
                f"mode={m['pipe_mode']}",
                flush=True,
            )
            continue
        print(
            f"  Q={m['Q']} nseg={m['n_segments']} order={m['order']} "
            f"mode={m['pipe_mode']} hub={m['n_hub']} meanLen={m['mean_len']} "
            f"faces={m['faces']} via={m['strategy']}@{m['fuzzy_mm']}",
            flush=True,
        )
    print("\nTop scores (mean_len / n_hub):", flush=True)
    for s in scored[:10]:
        h = s["hub"]
        print(
            f"  Q={s['Q']} nseg={s['n_segments']} order={s['order_name']} "
            f"mode={s['pipe_mode']} hub={h['n_hub_edges']} "
            f"meanLen={h['mean_edge_len_mm']:.3f} "
            f"score={s['score_meanLen_over_nHub']:.4f}",
            flush=True,
        )
    return 0 if summary["n_ok"] == summary["n_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
