"""Sequential chamfer to maximize Q=1.5 edge coverage with hard STEP."""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _assign_edge_for_slot,
    _ensure_written_solid,
    _mid_key,
    _slot_z_group,
    _try_slot_chamfer,
    _write_step_hard_solid,
    build_slots_for_params,
    default_rf_for_q,
)
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_unitcell_fuse import ocp_mass


def main() -> int:
    out = r"D:\HuBaiLab\output\cad\_exp_node_transition\_fillet_hardstep_probe"
    os.makedirs(out, exist_ok=True)
    q = 1.5
    params = SlotFilletParams(period_factor=q, r_blend_factor=default_rf_for_q(q))
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=32,
    )
    bare, m0, tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    print(f"bare={m0:.3f} {tag}", flush=True)
    used: set = set()
    pairs = []
    for slot in build_slots_for_params(params):
        if _slot_z_group(slot) not in ("bot", "top"):
            continue
        info = _assign_edge_for_slot(
            bare, slot, params, used_mids=used, max_edge_len_mm=2.5
        )
        if info is None:
            continue
        used.add(_mid_key(info["mid"]))
        pairs.append((slot, info))
    print(f"n_pairs={len(pairs)}", flush=True)

    for d in (0.05, 0.04, 0.03):
        try:
            sh = _try_slot_chamfer(
                bare, pairs, d_mm=d, m0=m0, max_span=27.0
            )
            sh = _ensure_written_solid(sh)
            path = os.path.join(out, f"_chamfer4_d{d}.step".replace(".", "p"))
            rb = _write_step_hard_solid(
                sh,
                path,
                mass_ref=float(ocp_mass(sh)),
                max_drift=1.2,
                max_span_mm=27.0,
            )
            print(f"BATCH4 OK d={d} mass={ocp_mass(rb):.3f} → {path}", flush=True)
            return 0
        except Exception as exc:
            print(f"BATCH4 fail d={d}: {exc}", flush=True)

    cur = bare
    filled = 0
    for slot, info in pairs:
        ok = False
        for d in (0.05, 0.04, 0.03, 0.06):
            try:
                # re-find edge on current shape
                info2 = _assign_edge_for_slot(
                    cur,
                    slot,
                    params,
                    used_mids=set(),
                    max_edge_len_mm=2.5,
                )
                pair = (slot, info2 if info2 is not None else info)
                sh = _try_slot_chamfer(
                    cur, [pair], d_mm=d, m0=float(ocp_mass(cur)), max_span=27.0
                )
                sh = _ensure_written_solid(sh)
                path = os.path.join(out, f"_chseq{filled}_d{d}.step".replace(".", "p"))
                rb = _write_step_hard_solid(
                    sh,
                    path,
                    mass_ref=float(ocp_mass(sh)),
                    max_drift=1.2,
                    max_span_mm=27.0,
                )
                cur = rb
                filled += 1
                ok = True
                print(
                    f"SEQ {filled} slot={slot.slot_id} d={d} mass={ocp_mass(cur):.3f}",
                    flush=True,
                )
                break
            except Exception as exc:
                print(f"  seq fail s{slot.slot_id} d={d}: {exc}", flush=True)
        if not ok:
            print(f"skip slot {slot.slot_id}", flush=True)

    final = os.path.join(out, "_chamfer_seq_final.step")
    rb = _write_step_hard_solid(
        cur,
        final,
        mass_ref=float(ocp_mass(cur)),
        max_drift=1.2,
        max_span_mm=27.0,
    )
    print(f"SEQ FINAL filled={filled} mass={ocp_mass(rb):.3f} → {final}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
