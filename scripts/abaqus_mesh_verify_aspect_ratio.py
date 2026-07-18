# -*- coding: utf-8 -*-
"""Mesh Verify ASPECT_RATIO (shape metrics) — literature Table 2.1 style warn count.

In CAE Shape Metrics, failing elements are reported as highlighted/warning in UI;
API returns them in failedElements for ASPECT_RATIO criterion.

Env: HU_BAI_MESH_INP, HU_BAI_OUT_JSON, HU_BAI_ASPECT_THR (default 3.0)
"""
from __future__ import print_function
import json, os
from abaqus import *
from abaqusConstants import *

MESH_INP = os.environ["HU_BAI_MESH_INP"]
OUT_JSON = os.environ["HU_BAI_OUT_JSON"]
THR = float(os.environ.get("HU_BAI_ASPECT_THR", "3.0"))

if "VERIFY_AR" in mdb.models.keys():
    del mdb.models["VERIFY_AR"]
mdb.ModelFromInputFile(name="VERIFY_AR", inputFileName=MESH_INP)
model = mdb.models["VERIFY_AR"]
part = None
best = -1
pname_best = None
for pname in model.parts.keys():
    p = model.parts[pname]
    n = len(p.elements)
    if n > best:
        best, part, pname_best = n, p, pname

stats = part.verifyMeshQuality(criterion=ASPECT_RATIO, threshold=THR)

def L(k):
    v = stats.get(k, None)
    if v is None:
        return 0
    try:
        return len(v)
    except TypeError:
        return int(v) if v else 0

num = int(stats.get("numElements", best) or best)
# Shape-metric failures are what CAE highlights; literature "Warning meshes"
n_fail = L("failedElements")
n_warn_api = L("warningElements")
# Use failedElements as literature warning count for ASPECT_RATIO
n_lit = n_fail if n_fail else n_warn_api
pct = (100.0 * n_lit / num) if num else 0.0

result = {
    "criterion": "ASPECT_RATIO",
    "threshold": THR,
    "part_name": pname_best,
    "mesh_inp": MESH_INP,
    "numElements": num,
    "warningElements_api": n_warn_api,
    "failedElements": n_fail,
    "warning_meshes_literature": n_lit,
    "warning_pct": pct,
    "average": stats.get("average", None),
    "worst": stats.get("worst", None),
}
d = os.path.dirname(OUT_JSON)
if d and not os.path.isdir(d):
    os.makedirs(d)
with open(OUT_JSON, "w") as f:
    json.dump(result, f, indent=2)
print(
    "ASPECT_RATIO thr=%g num=%d warning=%d (%.4f%%) avg=%s worst=%s"
    % (THR, num, n_lit, pct, stats.get("average"), stats.get("worst"))
)
