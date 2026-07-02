# -*- coding: utf-8 -*-
from odbAccess import openOdb
import sys
odb = openOdb(path=sys.argv[1], readOnly=1)
step = odb.steps["Compression"]
r = step.historyRegions["Node PART-1-1.307062"]
rf = r.historyOutputs["RF3"].data
u3 = r.historyOutputs["U3"].data
for i in range(len(rf)):
    pt = rf[i]
    if hasattr(pt, "time"):
        print(pt.time, u3[i].data, pt.data)
    else:
        print(pt[0], u3[i][1], pt[1])
odb.close()
