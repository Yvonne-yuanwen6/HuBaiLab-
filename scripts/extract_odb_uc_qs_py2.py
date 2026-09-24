# -*- coding: utf-8 -*-
"""Extract RF3/U3 + ALLKE/ALLIE/ALLAE for unit-cell QS study (Abaqus Python 2.7).

Usage:
  abaqus python scripts/extract_odb_uc_qs_py2.py ODB CSV [STEP]
"""
from __future__ import print_function

import sys

from odbAccess import openOdb


def _find_energy_region(step):
    preferred = (
        "Assembly ASSEMBLY",
        "Assembly assembly",
        "Assembly Assembly-1",
        "Whole Model",
    )
    for name in preferred:
        if name in step.historyRegions:
            outs = step.historyRegions[name].historyOutputs
            if "ALLIE" in outs and "ALLKE" in outs:
                return name
    for name in step.historyRegions.keys():
        outs = step.historyRegions[name].historyOutputs
        if "ALLIE" in outs and "ALLKE" in outs:
            return name
    return None


def _find_plate_ref_region(step):
    # Prefer Node ... history with RF3+U3
    for name in step.historyRegions.keys():
        outs = step.historyRegions[name].historyOutputs
        if "RF3" in outs and "U3" in outs:
            return name
    for name in step.historyRegions.keys():
        outs = step.historyRegions[name].historyOutputs
        if "RF3" in outs and ("U3" in outs or "U2" in outs or "U1" in outs):
            return name
    return None


def _series(region, key):
    if key not in region.historyOutputs:
        return None
    return [(float(p[0]), float(p[1])) for p in region.historyOutputs[key].data]


def _interp(series, t):
    if not series:
        return float("nan")
    exact = dict(series)
    if t in exact:
        return exact[t]
    best = min(series, key=lambda p: abs(p[0] - t))
    return best[1]


def main():
    if len(sys.argv) < 3:
        print("usage: extract_odb_uc_qs_py2.py ODB CSV [STEP]")
        sys.exit(1)
    odb_path = sys.argv[1]
    csv_path = sys.argv[2]
    step_name = sys.argv[3] if len(sys.argv) > 3 else "Compression"

    odb = openOdb(path=odb_path, readOnly=1)
    try:
        if step_name not in odb.steps:
            step_name = list(odb.steps.keys())[-1]
        step = odb.steps[step_name]
        e_reg = _find_energy_region(step)
        n_reg = _find_plate_ref_region(step)
        if e_reg is None:
            print("[ERROR] no energy region with ALLIE+ALLKE")
            sys.exit(2)
        if n_reg is None:
            print("[ERROR] no node history with RF3+U3")
            for k in sorted(step.historyRegions.keys()):
                print(" ", k, list(step.historyRegions[k].historyOutputs.keys())[:12])
            sys.exit(3)
        e_region = step.historyRegions[e_reg]
        n_region = step.historyRegions[n_reg]
        ie = _series(e_region, "ALLIE")
        ke = _series(e_region, "ALLKE")
        ae = _series(e_region, "ALLAE")
        rf3 = _series(n_region, "RF3")
        u3 = _series(n_region, "U3")
        if u3 is None:
            u3 = _series(n_region, "U2") or _series(n_region, "U1")
    finally:
        odb.close()

    # Align on ALLIE time base
    rows = []
    for t, ie_v in ie:
        rows.append(
            (
                t,
                _interp(rf3, t),
                _interp(u3, t),
                _interp(ke, t),
                ie_v,
                _interp(ae, t) if ae is not None else float("nan"),
            )
        )

    with open(csv_path, "w") as f:
        f.write("time_s,RF3_N,U3_mm,ALLKE_J,ALLIE_J,ALLAE_J\n")
        for t, rf, u, ke_v, ie_v, ae_v in rows:
            if ae is None:
                f.write("%g,%g,%g,%g,%g,\n" % (t, rf, u, ke_v, ie_v))
            else:
                f.write("%g,%g,%g,%g,%g,%g\n" % (t, rf, u, ke_v, ie_v, ae_v))

    max_ke_ie = 0.0
    max_ae_ie = 0.0
    for t, rf, u, ke_v, ie_v, ae_v in rows:
        if ie_v > 1e-9:
            max_ke_ie = max(max_ke_ie, abs(ke_v) / ie_v)
            if ae is not None and ae_v == ae_v:
                max_ae_ie = max(max_ae_ie, abs(ae_v) / ie_v)
    print("Energy region: %s" % e_reg)
    print("Node region: %s" % n_reg)
    print("Step: %s" % step_name)
    print("Points: %d" % len(rows))
    print("ALLAE present: %s" % ("yes" if ae is not None else "no"))
    print("max |ALLKE|/ALLIE = %.4f%%" % (100.0 * max_ke_ie))
    if ae is not None:
        print("max |ALLAE|/ALLIE = %.4f%%" % (100.0 * max_ae_ie))


if __name__ == "__main__":
    main()
