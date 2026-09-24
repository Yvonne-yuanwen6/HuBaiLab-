"""Sweep centre-taper STEP on the four project configs: Af=2, Q in {0,0.5,1,1.5}."""
from __future__ import annotations

import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.centre_taper_pipe import (
    CentreTaperParams,
    export_centre_taper_unitcell,
)

# Milder taper for Q=0; Q=1 uses stub path + moderate scale (probe-proven).
_TAPER_BY_Q: dict[float, tuple[float, float]] = {
    0.0: (3.0, 1.25),
    0.5: (3.2, 1.35),
    1.0: (3.0, 1.30),  # 3.2/1.35 can empty-fuse; 3.0/1.3 hard-STEP OK
    1.5: (3.5, 1.45),
}


def main() -> int:
    rows: list[dict] = []
    for q in (0.0, 0.5, 1.0, 1.5):
        tp, sc = _TAPER_BY_Q[q]
        print(f"\n######## Q={q:g} taper_mm={tp} scale={sc} ########", flush=True)
        params = CentreTaperParams(
            cell_size_mm=20.0,
            rod_d_mm=2.0,
            amplitude_mm=2.0,
            period_factor=float(q),
            n_segments=32,
            taper_mm=float(tp),
            taper_scale=float(sc),
        )
        try:
            man = export_centre_taper_unitcell(params, force=True)
            rb = man.get("step_readback") or {}
            topo = rb.get("topology") or {}
            rows.append(
                {
                    "Q": q,
                    "ok": True,
                    "mass": rb.get("mass_mm3"),
                    "span": rb.get("span"),
                    "solids": topo.get("solids"),
                    "brep_valid": topo.get("brep_valid"),
                    "step": man.get("step_path"),
                    "taper_mm": tp,
                    "taper_scale": sc,
                }
            )
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            rows.append({"Q": q, "ok": False, "error": str(exc), "taper_mm": tp, "taper_scale": sc})

    print("\n======== FOUR-CONFIG CENTRE-TAPER SUMMARY ========", flush=True)
    for r in rows:
        if r.get("ok"):
            span = r.get("span") or ()
            span_s = tuple(round(float(x), 2) for x in span) if span else ()
            print(
                f"  Q={r['Q']:g}  OK  mass={float(r['mass']):.2f}  "
                f"span={span_s}  solids={r['solids']}  valid={r['brep_valid']}  "
                f"tp={r['taper_mm']} sc={r['taper_scale']}",
                flush=True,
            )
            print(f"       {r['step']}", flush=True)
        else:
            print(f"  Q={r['Q']:g}  FAIL  {r.get('error')}", flush=True)
    n_ok = sum(1 for r in rows if r.get("ok"))
    print(f"pass {n_ok}/{len(rows)}", flush=True)
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
