# -*- coding: utf-8 -*-
"""Dump deformed lattice node coordinates at selected compression fractions.

Usage (Abaqus Python 2.7):
  abaqus python scripts/extract_odb_deform_frames_py2.py ODB OUT_DIR \\
      [--step Compression] [--fractions 0,0.3,0.6,1.0] [--instance PART-1-1]
"""
from __future__ import print_function

import csv
import os
import sys


def _parse_args(argv):
    odb = argv[1]
    out_dir = argv[2]
    step = "Compression"
    fractions = [0.0, 0.3, 0.6, 1.0]
    instance = None
    i = 3
    while i < len(argv):
        if argv[i] == "--step" and i + 1 < len(argv):
            step = argv[i + 1]
            i += 2
        elif argv[i] == "--fractions" and i + 1 < len(argv):
            fractions = [float(x) for x in argv[i + 1].split(",") if x.strip()]
            i += 2
        elif argv[i] == "--instance" and i + 1 < len(argv):
            instance = argv[i + 1]
            i += 2
        else:
            i += 1
    return odb, out_dir, step, fractions, instance


def _pick_instance(odb, preferred):
    root = odb.rootAssembly
    names = list(root.instances.keys())
    if preferred and preferred in root.instances:
        return root.instances[preferred]
    # Prefer lattice (usually PART-1-1), skip plates if possible.
    for n in names:
        low = n.lower()
        if "plate" in low:
            continue
        return root.instances[n]
    return root.instances[names[0]]


def _frame_fraction(frames, frac):
    if not frames:
        return None
    # Prefer frameTime / totalTime when available.
    times = []
    for fr in frames:
        t = getattr(fr, "frameValue", None)
        if t is None:
            t = float(fr.frameId)
        times.append(float(t))
    t0, t1 = times[0], times[-1]
    span = t1 - t0 if abs(t1 - t0) > 1e-15 else 1.0
    target = t0 + float(frac) * span
    best_i = 0
    best_d = abs(times[0] - target)
    for i, t in enumerate(times):
        d = abs(t - target)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i, times[best_i], target


def main():
    if len(sys.argv) < 3:
        print("usage: extract_odb_deform_frames_py2.py ODB OUT_DIR [...]")
        sys.exit(1)
    from odbAccess import openOdb

    odb_path, out_dir, step_name, fractions, inst_name = _parse_args(sys.argv)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    odb = openOdb(path=odb_path, readOnly=1)
    try:
        if step_name not in odb.steps:
            step_name = list(odb.steps.keys())[-1]
        step = odb.steps[step_name]
        frames = step.frames
        inst = _pick_instance(odb, inst_name)
        print("step=%s n_frames=%d instance=%s" % (step_name, len(frames), inst.name))

        # Undeformed coords
        node_labels = []
        x0, y0, z0 = [], [], []
        for n in inst.nodes:
            node_labels.append(int(n.label))
            c = n.coordinates
            x0.append(float(c[0]))
            y0.append(float(c[1]))
            z0.append(float(c[2]))

        index_csv = os.path.join(out_dir, "deform_frames_index.csv")
        with open(index_csv, "w") as idx:
            idx.write("fraction,frame_id,frame_time,target_time,csv\n")
            for frac in fractions:
                picked = _frame_fraction(frames, frac)
                if picked is None:
                    continue
                fi, t_act, t_tgt = picked
                fr = frames[fi]
                # Displacement field
                u_field = None
                for key in fr.fieldOutputs.keys():
                    if key == "U":
                        u_field = fr.fieldOutputs[key]
                        break
                if u_field is None:
                    print("[WARN] no U at frame %d" % fi)
                    continue
                # Map label -> (u1,u2,u3)
                u_map = {}
                try:
                    subset = u_field.getSubset(region=inst)
                    values = subset.values
                except Exception:
                    values = u_field.values
                for v in values:
                    try:
                        lab = int(v.nodeLabel)
                    except Exception:
                        continue
                    data = v.data
                    if len(data) >= 3:
                        u_map[lab] = (float(data[0]), float(data[1]), float(data[2]))

                pct = int(round(100.0 * float(frac)))
                csv_name = "deform_%03dpct.csv" % pct
                csv_path = os.path.join(out_dir, csv_name)
                with open(csv_path, "w") as f:
                    f.write("node,x0,y0,z0,u1,u2,u3,x,y,z,u_mag\n")
                    for i, lab in enumerate(node_labels):
                        u = u_map.get(lab, (0.0, 0.0, 0.0))
                        xd = x0[i] + u[0]
                        yd = y0[i] + u[1]
                        zd = z0[i] + u[2]
                        um = (u[0] * u[0] + u[1] * u[1] + u[2] * u[2]) ** 0.5
                        f.write(
                            "%d,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g\n"
                            % (lab, x0[i], y0[i], z0[i], u[0], u[1], u[2], xd, yd, zd, um)
                        )
                idx.write(
                    "%.4f,%d,%.6g,%.6g,%s\n" % (frac, fi, t_act, t_tgt, csv_name)
                )
                print("wrote %s frame=%d t=%.6g (target %.6g)" % (csv_name, fi, t_act, t_tgt))
        print("index:", index_csv)
    finally:
        odb.close()


if __name__ == "__main__":
    main()
