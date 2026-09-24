# -*- coding: utf-8 -*-
"""Extract whole-model ALLIE / ALLKE / ALLAE history from ODB (Abaqus Python 2.7).

Usage:
  abq python scripts/extract_odb_energy_py2.py ODB CSV [STEP]
"""
from __future__ import print_function

import sys

from odbAccess import openOdb

ENERGY_KEYS = ("ALLIE", "ALLKE", "ALLAE")


def _find_energy_region(step):
    preferred = (
        "Assembly ASSEMBLY",
        "Assembly assembly",
        "Assembly Assembly-1",
        "Whole Model",
        "Assembly Part-1-1",
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


def _series(region, key):
    if key not in region.historyOutputs:
        return None
    return [(float(p[0]), float(p[1])) for p in region.historyOutputs[key].data]


def main():
    if len(sys.argv) < 3:
        print("usage: extract_odb_energy_py2.py ODB CSV [STEP]")
        sys.exit(1)
    odb_path = sys.argv[1]
    csv_path = sys.argv[2]
    step_name = sys.argv[3] if len(sys.argv) > 3 else "Compression"

    odb = openOdb(path=odb_path, readOnly=1)
    try:
        if step_name not in odb.steps:
            step_name = list(odb.steps.keys())[0]
        step = odb.steps[step_name]
        region_name = _find_energy_region(step)
        if region_name is None:
            print("[ERROR] no history region with ALLIE+ALLKE")
            for k in sorted(step.historyRegions.keys()):
                outs = list(step.historyRegions[k].historyOutputs.keys())
                print(" ", k, outs[:12])
            sys.exit(2)
        region = step.historyRegions[region_name]
        ie = _series(region, "ALLIE")
        ke = _series(region, "ALLKE")
        ae = _series(region, "ALLAE")
    finally:
        odb.close()

    ke_map = dict(ke)
    ae_map = dict(ae) if ae else {}
    rows = []
    for t, ie_v in ie:
        ke_v = ke_map.get(t)
        if ke_v is None:
            best = min(ke, key=lambda p: abs(p[0] - t))
            ke_v = best[1]
        if ae is None:
            ae_v = float("nan")
        else:
            ae_v = ae_map.get(t)
            if ae_v is None:
                best = min(ae, key=lambda p: abs(p[0] - t))
                ae_v = best[1]
        rows.append((t, ke_v, ie_v, ae_v))

    with open(csv_path, "w") as f:
        f.write("time_s,ALLKE_J,ALLIE_J,ALLAE_J\n")
        for t, ke_v, ie_v, ae_v in rows:
            if ae is None:
                f.write("%g,%g,%g,\n" % (t, ke_v, ie_v))
            else:
                f.write("%g,%g,%g,%g\n" % (t, ke_v, ie_v, ae_v))

    max_ke_ie = 0.0
    max_ae_ie = 0.0
    for t, ke_v, ie_v, ae_v in rows:
        if ie_v > 1e-9:
            max_ke_ie = max(max_ke_ie, abs(ke_v) / ie_v)
            if ae is not None and ae_v == ae_v:  # not NaN
                max_ae_ie = max(max_ae_ie, abs(ae_v) / ie_v)
    print("Region: %s" % region_name)
    print("Step: %s" % step_name)
    print("Points: %d" % len(rows))
    print("ALLAE present: %s" % ("yes" if ae is not None else "no"))
    print("max |ALLKE|/ALLIE = %.4f%%" % (100.0 * max_ke_ie))
    if ae is not None:
        print("max |ALLAE|/ALLIE = %.4f%%" % (100.0 * max_ae_ie))


if __name__ == "__main__":
    main()
