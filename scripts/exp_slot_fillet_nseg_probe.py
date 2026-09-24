"""
Q=1 / Q=1.5: does higher n_segments yield brep_valid MakeFillet that survives STEP?

  py -3 scripts/exp_slot_fillet_nseg_probe.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _assign_edge_for_slot,
    _bbox_span,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    build_slots_for_params,
    default_rf_for_q,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


def _probe_q(q: float, n_segments: int, out_dir: str) -> list[dict]:
    print(f"\n======== Q={q} n_seg={n_segments} ========", flush=True)
    params = SlotFilletParams(
        period_factor=q,
        r_blend_factor=default_rf_for_q(q),
        n_segments=n_segments,
    )
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=n_segments,
    )
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    print(f"  fuse={fuse_tag} mass={m0:.3f}", flush=True)
    max_elen = 2.5 if q > 1.2 else None
    used = set()
    pairs = []
    for slot in build_slots_for_params(params):
        if q > 1.2 and _slot_z_group(slot) not in ("bot", "top"):
            continue
        info = _assign_edge_for_slot(
            bare, slot, params, used_mids=used, max_edge_len_mm=max_elen
        )
        if info is None:
            continue
        used.add(_mid_key(info["mid"]))
        pairs.append((slot, info))
    print(f"  unique edges={len(pairs)}", flush=True)

    wins = []
    # single edge sweep
    for slot, info in pairs:
        g = _slot_z_group(slot)
        for r in (0.03, 0.04, 0.05, 0.06, 0.08):
            tag = f"q{q}_n{n_segments}_s{slot.slot_id}_{g}_r{r}".replace(".", "p")
            try:
                sh = _as_single_solid(
                    _try_fillet_per_edge(bare, [(info["edge"], r)])
                )
            except Exception as exc:
                continue
            m1 = float(ocp_mass(sh))
            dm = m1 - m0
            sp = _bbox_span(sh)
            topo = ocp_shape_topology(sh, check_brep=True)
            valid = bool(topo.get("brep_valid"))
            if max(sp) > 27 or abs(dm) > 6:
                continue
            print(
                f"  {tag}: dm={dm:+.3f} valid={valid} "
                f"span={tuple(round(x,2) for x in sp)}",
                flush=True,
            )
            if not valid or dm < -0.15:
                continue
            path = os.path.join(out_dir, f"{tag}.step")
            try:
                ocp_write_step(sh, path)
                rb = ocp_read_step_shape(path)
                rb_m = float(ocp_mass(rb))
                if abs(rb_m - m1) > 0.8:
                    print(
                        f"    STEP mass lost mem={m1:.3f} rb={rb_m:.3f}",
                        flush=True,
                    )
                    continue
                print(f"    WIN dm_rb={rb_m-m0:+.3f} → {path}", flush=True)
                wins.append(
                    {
                        "tag": tag,
                        "q": q,
                        "n_seg": n_segments,
                        "dm": dm,
                        "dm_rb": rb_m - m0,
                        "path": path,
                    }
                )
            except Exception as exc:
                print(f"    STEP fail: {exc}", flush=True)

    # opposite 2-edge if q>1.2
    if q > 1.2 and len(pairs) >= 2:
        bots = [p for p in pairs if _slot_z_group(p[0]) == "bot"]
        tops = [p for p in pairs if _slot_z_group(p[0]) == "top"]
        if bots and tops:
            for r in (0.04, 0.035, 0.03):
                tag = f"q{q}_n{n_segments}_opp_r{r}".replace(".", "p")
                try:
                    sh = _as_single_solid(
                        _try_fillet_per_edge(
                            bare,
                            [
                                (bots[0][1]["edge"], r),
                                (tops[0][1]["edge"], r),
                            ],
                        )
                    )
                    m1 = float(ocp_mass(sh))
                    dm = m1 - m0
                    topo = ocp_shape_topology(sh, check_brep=True)
                    sp = _bbox_span(sh)
                    print(
                        f"  {tag}: dm={dm:+.3f} valid={topo.get('brep_valid')} "
                        f"span={tuple(round(x,2) for x in sp)}",
                        flush=True,
                    )
                    if (
                        topo.get("brep_valid")
                        and max(sp) <= 27
                        and -0.15 <= dm <= 6
                    ):
                        path = os.path.join(out_dir, f"{tag}.step")
                        ocp_write_step(sh, path)
                        rb_m = float(ocp_mass(ocp_read_step_shape(path)))
                        if abs(rb_m - m1) <= 0.8:
                            print(f"    WIN opp → {path}", flush=True)
                            wins.append(
                                {
                                    "tag": tag,
                                    "q": q,
                                    "n_seg": n_segments,
                                    "dm": dm,
                                    "dm_rb": rb_m - m0,
                                    "path": path,
                                }
                            )
                except Exception as exc:
                    print(f"  {tag}: {exc}", flush=True)
    return wins


def main() -> int:
    out_dir = os.path.join(default_exp_out_dir(), "_fillet_nseg_probe")
    os.makedirs(out_dir, exist_ok=True)
    all_wins: list[dict] = []
    for q in (1.5, 1.0):
        for nseg in (32, 48, 64):
            try:
                all_wins.extend(_probe_q(q, nseg, out_dir))
            except Exception as exc:
                print(f"  PROBE FAIL Q={q} n={nseg}: {exc}", flush=True)
    print("\n=== ALL WINS ===", flush=True)
    for w in all_wins:
        print(f"  {w}", flush=True)
    print(f"n_wins={len(all_wins)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
