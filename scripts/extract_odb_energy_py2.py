# -*- coding: utf-8 -*-
"""Extract whole-model ALLIE / ALLKE history from ODB (Abaqus Python 2.7).

Usage:
  abq python scripts/extract_odb_energy_py2.py ODB CSV
"""
from __future__ import print_function

import sys

from odbAccess import openOdb


def _find_energy_region(step):
    preferred = (
        "Assembly ASSEMBLY",
        "Assembly assembly",
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


def main():
    if len(sys.argv) < 3:
        print("usage: extract_odb_energy_py2.py ODB CSV")
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
        ie = [(float(p[0]), float(p[1])) for p in region.historyOutputs["ALLIE"].data]
        ke = [(float(p[0]), float(p[1])) for p in region.historyOutputs["ALLKE"].data]
    finally:
        odb.close()

    # Align by time (usually identical).
    ke_map = dict(ke)
    rows = []
    for t, ie_v in ie:
        ke_v = ke_map.get(t)
        if ke_v is None:
            # nearest
            best = min(ke, key=lambda p: abs(p[0] - t))
            ke_v = best[1]
        rows.append((t, ke_v, ie_v))

    with open(csv_path, "w") as f:
        f.write("time_s,ALLKE_J,ALLIE_J\n")
        for t, ke_v, ie_v in rows:
            f.write("%g,%g,%g\n" % (t, ke_v, ie_v))

    max_ratio = 0.0
    for t, ke_v, ie_v in rows:
        if ie_v > 1e-9:
            max_ratio = max(max_ratio, abs(ke_v) / ie_v)
    print("Region: %s" % region_name)
    print("Points: %d" % len(rows))
    print("max |ALLKE|/ALLIE = %.4f%%" % (100.0 * max_ratio))


if __name__ == "__main__":
    main()
