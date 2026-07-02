# -*- coding: utf-8 -*-
"""Minimal live ODB extract for Abaqus Python 2.7 on Linux server (readOnly)."""
import json
import sys

from odbAccess import openOdb


def resolve_plate_ref_region(assembly, ref_node_id):
    keys = list(assembly.nodeSets.keys())
    upper_map = dict((k.upper(), k) for k in keys)
    for hint in ("PLATE_REF", "PLATE"):
        hu = hint.upper()
        if hu in upper_map:
            k = upper_map[hu]
            return assembly.nodeSets[k], k
    ref_s = str(int(ref_node_id))
    for k in keys:
        ku = k.upper()
        if "REFERENCE_POINT" in ku and ref_s in k:
            return assembly.nodeSets[k], k
    return None, None


def field_series_at_node_label(step, ref_node_id):
    times, u3_list, rf_list = [], [], []
    label = int(ref_node_id)
    for frame in step.frames:
        if "RF" not in frame.fieldOutputs or "U" not in frame.fieldOutputs:
            continue
        rf3 = u3 = None
        for v in frame.fieldOutputs["RF"].values:
            if int(v.nodeLabel) == label:
                rf3 = float(v.data[2])
                break
        for v in frame.fieldOutputs["U"].values:
            if int(v.nodeLabel) == label:
                u3 = float(v.data[2])
                break
        if rf3 is None or u3 is None:
            continue
        times.append(float(frame.frameValue))
        rf_list.append(rf3)
        u3_list.append(u3)
    return times, u3_list, rf_list


def extract_plate_ref_field(step, assembly, ref_node_id):
    plate, plate_label = resolve_plate_ref_region(assembly, ref_node_id)
    times, u3_list, rf_list = [], [], []
    if plate is not None:
        for frame in step.frames:
            if "RF" not in frame.fieldOutputs or "U" not in frame.fieldOutputs:
                continue
            rf_sub = frame.fieldOutputs["RF"].getSubset(region=plate)
            u_sub = frame.fieldOutputs["U"].getSubset(region=plate)
            if not rf_sub.values or not u_sub.values:
                continue
            times.append(float(frame.frameValue))
            rf_list.append(float(rf_sub.values[0].data[2]))
            u3_list.append(float(u_sub.values[0].data[2]))
        region_name = "%s field RF3/U3 (%d frames)" % (plate_label, len(times))
    else:
        times, u3_list, rf_list = field_series_at_node_label(step, ref_node_id)
        region_name = "node %d field RF3/U3 (%d frames)" % (ref_node_id, len(times))
    if len(times) < 2:
        raise ValueError("Too few field frames for PLATE_REF node %d" % ref_node_id)
    return times, u3_list, rf_list, region_name


def main():
    odb_path = sys.argv[1]
    meta_path = sys.argv[2]
    csv_path = sys.argv[3]
    max_time = float(sys.argv[4]) if len(sys.argv) > 4 else None
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
        times, uvals, rfvals, rname = extract_plate_ref_field(
            step, odb.rootAssembly, ref_node
        )
        trimmed_u, trimmed_rf = [], []
        for t, u, r in zip(times, uvals, rfvals):
            if t < hold_end:
                continue
            if max_time is not None and t > max_time:
                continue
            trimmed_u.append(u)
            trimmed_rf.append(r)
        uvals, rfvals = trimmed_u, trimmed_rf
    finally:
        odb.close()

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
    print("Region: %s" % rname)
    print("Points: %d" % len(uvals))
    print("Last: strain=%.6f stress=%.4f MPa" % (last_s, last_st))


if __name__ == "__main__":
    main()
