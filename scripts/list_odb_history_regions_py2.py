# -*- coding: utf-8 -*-
from odbAccess import openOdb
import sys
odb = openOdb(path=sys.argv[1], readOnly=1)
step = odb.steps["Compression"]
for k in sorted(step.historyRegions.keys()):
    r = step.historyRegions[k]
    outs = list(r.historyOutputs.keys())
    if "RF3" in outs or "U3" in outs:
        print(k, outs)
odb.close()
