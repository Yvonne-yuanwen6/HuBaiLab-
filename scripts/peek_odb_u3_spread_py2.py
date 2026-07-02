# -*- coding: utf-8 -*-
"""Report U3 spread (min/max/mean) on lattice nodes at selected Compression frames."""
from odbAccess import openOdb
import sys

odb_path = sys.argv[1]
step_name = sys.argv[2] if len(sys.argv) > 2 else "Compression"
frame_targets = [float(x) for x in sys.argv[3:]] if len(sys.argv) > 3 else [0.3, 0.5, 0.65, 0.72, 0.76]

odb = openOdb(path=odb_path, readOnly=1)
step = odb.steps[step_name]
inst = odb.rootAssembly.instances[odb.rootAssembly.instances.keys()[0]]
print("step", step_name, "frames", len(step.frames), "instance", inst.name, "nodes", len(inst.nodes))

for target_t in frame_targets:
    best = None
    best_dt = 1e30
    for fr in step.frames:
        t = fr.frameValue
        dt = abs(t - target_t)
        if dt < best_dt:
            best_dt = dt
            best = fr
    if best is None:
        continue
    u = best.fieldOutputs["U"].getSubset(region=inst)
    zs = [v.data[2] for v in u.values]
    if not zs:
        continue
    zmin = min(zs)
    zmax = max(zs)
    zmean = sum(zs) / float(len(zs))
    print(
        "t=%.4f target=%.2f spread=%.4f zmin=%.4f zmax=%.4f zmean=%.4f"
        % (best.frameValue, target_t, zmax - zmin, zmin, zmax, zmean)
    )

odb.close()
