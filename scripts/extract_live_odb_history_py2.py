# -*- coding: utf-8 -*-
"""Live partial stress-strain from ODB history (readOnly, safe while job runs)."""
import json
import sys

from odbAccess import openOdb


def main():
    odb_path = sys.argv[1]
    meta_path = sys.argv[2]
    csv_path = sys.argv[3]
    with open(meta_path, "r") as f:
        meta = json.load(f)
    ref_h = float(meta["reference_height_mm"])
    ref_area = float(meta["reference_area_mm2"])
    hold_end = float(meta.get("amplitude_hold_fraction", 0.05)) * float(meta["step_time"])
    step_name = str(meta.get("step_name", "Compression"))
    ref_node = int(meta["plate_ref_node_id"])

    odb = openOdb(path=odb_path, readOnly=1)
    try:
        step = odb.steps[step_name]
        region_name = "Node PART-1-1.%d" % ref_node
        if region_name not in step.historyRegions:
            for k in step.historyRegions.keys():
                if str(ref_node) in k and "RF3" in step.historyRegions[k].historyOutputs:
                    region_name = k
                    break
        region = step.historyRegions[region_name]
        times = [float(p[0]) for p in region.historyOutputs["U3"].data]
        uvals = [float(p[1]) for p in region.historyOutputs["U3"].data]
        rfvals = [float(p[1]) for p in region.historyOutputs["RF3"].data]
    finally:
        odb.close()

    trimmed_u, trimmed_rf = [], []
    for t, u, r in zip(times, uvals, rfvals):
        if t < hold_end:
            continue
        trimmed_u.append(u)
        trimmed_rf.append(r)
    uvals, rfvals = trimmed_u, trimmed_rf

    if not uvals:
        print("[ERROR] no points after hold trim")
        sys.exit(1)

    u0 = uvals[0]
    with open(csv_path, "w") as f:
        f.write("engineering_strain,engineering_stress_MPa\n")
        for u, r in zip(uvals, rfvals):
            strain = abs(u - u0) / ref_h
            stress = abs(r) / ref_area
            f.write("%g,%g\n" % (strain, stress))

    last_s = abs(uvals[-1] - u0) / ref_h
    last_st = abs(rfvals[-1]) / ref_area
    print("Region: %s" % region_name)
    print("Points: %d" % len(uvals))
    print("Last: strain=%.6f stress=%.4f MPa sim_t=%.1f" % (last_s, last_st, times[-1]))


if __name__ == "__main__":
    main()
