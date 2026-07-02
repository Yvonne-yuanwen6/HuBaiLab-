# -*- coding: utf-8 -*-
from odbAccess import openOdb
import sys
odb = openOdb(path=sys.argv[1], readOnly=1)
step = odb.steps["Compression"]
assembly = odb.rootAssembly
ref = str(int(sys.argv[2]))
plate = None
for k in assembly.nodeSets.keys():
    if "REFERENCE_POINT" in k.upper() and ref in k:
        plate = assembly.nodeSets[k]
        print("using", k)
        break
for frame in step.frames:
    if "RF" not in frame.fieldOutputs or "U" not in frame.fieldOutputs:
        continue
    t = frame.frameValue
    rf_sub = frame.fieldOutputs["RF"].getSubset(region=plate)
    u_sub = frame.fieldOutputs["U"].getSubset(region=plate)
    if rf_sub.values and u_sub.values:
        print(t, u_sub.values[0].data[2], rf_sub.values[0].data[2])
odb.close()
