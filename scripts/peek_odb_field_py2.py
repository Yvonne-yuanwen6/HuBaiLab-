# -*- coding: utf-8 -*-
from odbAccess import openOdb
import sys
odb = openOdb(path=sys.argv[1], readOnly=1)
step = odb.steps["Compression"]
assembly = odb.rootAssembly
ref = int(sys.argv[2])
plate = None
for k in assembly.nodeSets.keys():
    if k == "PLATE_REF" or "PLATE_REF" in k.upper():
        plate = assembly.nodeSets[k]
        print("nset", k, len(plate.nodes))
        break
if plate is None:
    print("no PLATE_REF nset")
frames = step.frames
print("frames", len(frames))
for frame in frames:
    if "RF" not in frame.fieldOutputs or "U" not in frame.fieldOutputs:
        continue
    t = frame.frameValue
    if plate is not None:
        rf_sub = frame.fieldOutputs["RF"].getSubset(region=plate)
        u_sub = frame.fieldOutputs["U"].getSubset(region=plate)
        if rf_sub.values and u_sub.values:
            print(t, u_sub.values[0].data[2], rf_sub.values[0].data[2])
    else:
        for v in frame.fieldOutputs["RF"].values:
            if int(v.nodeLabel) == ref:
                rf3 = v.data[2]
                break
        for v in frame.fieldOutputs["U"].values:
            if int(v.nodeLabel) == ref:
                u3 = v.data[2]
                break
        print(t, u3, rf3)
odb.close()
