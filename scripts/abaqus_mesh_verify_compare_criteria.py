# -*- coding: utf-8 -*-
"""Compare Mesh Verify criteria on one INP (ANALYSIS_CHECKS vs ASPECT_RATIO etc)."""
from __future__ import print_function
import json, os, sys
from abaqus import *
from abaqusConstants import *

MESH_INP = os.environ["HU_BAI_MESH_INP"]
OUT_JSON = os.environ["HU_BAI_OUT_JSON"]

if "VERIFY2" in mdb.models.keys():
    del mdb.models["VERIFY2"]
mdb.ModelFromInputFile(name="VERIFY2", inputFileName=MESH_INP)
model = mdb.models["VERIFY2"]
part = None
best = -1
for pname in model.parts.keys():
    p = model.parts[pname]
    n = len(p.elements)
    if n > best:
        best = n
        part = p
        part_name = pname

def count_stats(stats):
    def L(k):
        v = stats.get(k, None)
        if v is None:
            return 0
        try:
            return len(v)
        except TypeError:
            return int(v) if v else 0
    n = int(stats.get("numElements", best) or best)
    return {
        "numElements": n,
        "warningElements": L("warningElements"),
        "failedElements": L("failedElements"),
        "naElements": L("naElements"),
        "keys": sorted([str(k) for k in stats.keys()]),
    }

out = {"part": part_name, "nelem": best, "checks": {}}

# Analysis checks (literature often means this OR shape metrics)
out["checks"]["ANALYSIS_CHECKS"] = count_stats(part.verifyMeshQuality(criterion=ANALYSIS_CHECKS))

# Shape metrics: aspect ratio default threshold 10
for thr in (10.0, 5.0, 3.0):
    key = "ASPECT_RATIO_thr_%g" % thr
    out["checks"][key] = count_stats(
        part.verifyMeshQuality(criterion=ASPECT_RATIO, threshold=thr)
    )

# Shape factor for tets (default threshold often 0.0001)
for thr in (0.01, 0.001, 0.0001):
    key = "SHAPE_FACTOR_thr_%g" % thr
    try:
        out["checks"][key] = count_stats(
            part.verifyMeshQuality(criterion=SHAPE_FACTOR, threshold=thr)
        )
    except Exception as exc:
        out["checks"][key] = {"error": str(exc)}

# Angular deviation
try:
    out["checks"]["ANGULAR_DEVIATION_thr_30"] = count_stats(
        part.verifyMeshQuality(criterion=ANGULAR_DEVIATION, threshold=30.0)
    )
except Exception as exc:
    out["checks"]["ANGULAR_DEVIATION_thr_30"] = {"error": str(exc)}

with open(OUT_JSON, "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
