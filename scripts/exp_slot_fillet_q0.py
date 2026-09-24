"""
Q=0 BCC: fillet all 12 acute strut-pair intersection slots.

  py -3 scripts/exp_slot_fillet_q0.py --force
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    export_slot_fillet_q0,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Q=0 acute 12-slot MakeFillet")
    p.add_argument("--rf", type=float, default=0.35)
    p.add_argument("--force", action="store_true")
    p.add_argument("--max-per-slot", type=int, default=2)
    args = p.parse_args()

    params = SlotFilletParams(
        r_blend_factor=float(args.rf),
    )
    man = export_slot_fillet_q0(params, force=bool(args.force))
    fil = man.get("fillet") or {}
    print(
        "ok coverage=",
        fil.get("n_slots_filled"),
        "/",
        fil.get("n_slots"),
        "r_used=",
        fil.get("r_used_mm"),
        "fallback=",
        man.get("used_bare_fallback"),
        "valid=",
        (man.get("topology") or {}).get("brep_valid"),
        "step=",
        man.get("step_path"),
    )
    for s in fil.get("slot_edges") or []:
        flag = "Y" if s.get("assigned") else "N"
        print(f"  slot#{s['slot_id']:02d} pair={tuple(s['pair'])} assigned={flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
