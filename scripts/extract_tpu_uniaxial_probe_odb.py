"""
Extract engineering stress-strain from a single-element TPU uniaxial probe ODB.

Run with Abaqus Python on the server:

  abaqus python scripts/extract_tpu_uniaxial_probe_odb.py --slug tpu_mat_marlow
"""
from __future__ import print_function

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from odbAccess import openOdb
except ImportError:
    print(
        "[ERROR] odbAccess not found. Run with Abaqus Python:\n"
        "  abaqus python scripts/extract_tpu_uniaxial_probe_odb.py --slug tpu_mat_marlow"
    )
    sys.exit(1)


def _read_probe_meta(root, slug):
    meta_path = os.path.join(root, "output", "export", slug, "{0}_meta.json".format(slug))
    if os.path.isfile(meta_path):
        with open(meta_path, "r") as f:
            return json.load(f)
    return {}


def _history_xy(history_region, var_name):
    if var_name not in history_region.historyOutputs:
        return []
    out = history_region.historyOutputs[var_name]
    return [(float(d[0]), float(d[1])) for d in out.data]


def extract_probe_curve(odb_path, l0_mm, area_mm2):
    odb = openOdb(path=odb_path, readOnly=True)
    try:
        step = odb.steps[odb.steps.keys()[-1]]
        for region in step.historyRegions.values():
            if "RF3" not in region.historyOutputs or "U3" not in region.historyOutputs:
                continue
            rf = _history_xy(region, "RF3")
            u3 = _history_xy(region, "U3")
            if not rf or not u3:
                continue
            n = min(len(rf), len(u3))
            pts = []
            for i in range(n):
                disp = u3[i][1]
                force = rf[i][1]
                strain = disp / l0_mm if l0_mm > 0 else 0.0
                stress = force / area_mm2 if area_mm2 > 0 else 0.0
                pts.append((strain, stress))
            if pts:
                return pts
        raise RuntimeError("No RF3/U3 nodal history found in {0}".format(odb_path))
    finally:
        odb.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--root", default=_ROOT)
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    slug = args.slug
    job_dir = os.path.join(root, "output", "jobs", slug)
    post_dir = os.path.join(root, "output", "post", slug)
    if not os.path.isdir(post_dir):
        os.makedirs(post_dir)

    meta = _read_probe_meta(root, slug)
    odb = os.path.join(job_dir, "{0}.odb".format(slug))
    if not os.path.isfile(odb):
        print("[ERROR] missing ODB: {0}".format(odb))
        return 1

    l0 = float(meta.get("L0_mm", 10.0))
    area = float(meta.get("area_mm2", 100.0))
    pts = extract_probe_curve(odb, l0, area)

    csv_path = os.path.join(post_dir, "{0}_stress_strain.csv".format(slug))
    with open(csv_path, "wb") as f:
        w = csv.writer(f)
        w.writerow(["engineering_strain", "engineering_stress_MPa"])
        for e, s in pts:
            w.writerow(["{0:.8g}".format(e), "{0:.8g}".format(s)])

    summary = {
        "slug": slug,
        "odb": odb,
        "csv": csv_path,
        "n_points": len(pts),
        "max_strain": max([p[0] for p in pts]) if pts else 0.0,
        "max_stress_MPa": max([p[1] for p in pts]) if pts else 0.0,
    }
    json_path = os.path.join(post_dir, "{0}_extract.json".format(slug))
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print("Wrote {0} ({1} points)".format(csv_path, len(pts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
