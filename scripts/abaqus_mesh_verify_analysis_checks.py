# -*- coding: utf-8 -*-
"""
Abaqus/CAE noGUI: Mesh Verify = ANALYSIS_CHECKS (literature Table 2.1 style).

Env:
  HU_BAI_MESH_INP   path to CAE mesh or compression INP with *Element
  HU_BAI_OUT_JSON   output JSON path

Run:
  abaqus cae noGUI=scripts/abaqus_mesh_verify_analysis_checks.py
"""
from __future__ import print_function

import json
import os
import sys

from abaqus import *
from abaqusConstants import *

MESH_INP = os.environ.get("HU_BAI_MESH_INP", "").strip()
OUT_JSON = os.environ.get("HU_BAI_OUT_JSON", "").strip()
if not MESH_INP or not os.path.isfile(MESH_INP):
    raise RuntimeError("HU_BAI_MESH_INP missing or not a file: %r" % MESH_INP)
if not OUT_JSON:
    raise RuntimeError("HU_BAI_OUT_JSON not set")

print("Mesh Verify ANALYSIS_CHECKS on:", MESH_INP)

model_name = "VERIFY"
# ModelFromInputFile creates a new model from INP
if model_name in mdb.models.keys():
    del mdb.models[model_name]

try:
    mdb.ModelFromInputFile(name=model_name, inputFileName=MESH_INP)
except Exception as exc:
    # Older CAE fallback
    print("ModelFromInputFile failed:", exc)
    raise

model = mdb.models[model_name]
# Prefer a solid continuum part with elements
part = None
part_name = None
best_n = -1
for pname in model.parts.keys():
    p = model.parts[pname]
    try:
        n = len(p.elements)
    except Exception:
        n = 0
    if n > best_n:
        best_n = n
        part = p
        part_name = pname

if part is None or best_n <= 0:
    raise RuntimeError("No meshed part found in INP model")

print("Part:", part_name, "elements=", best_n)

stats = part.verifyMeshQuality(criterion=ANALYSIS_CHECKS)

def _len_or_zero(key):
    val = stats.get(key, None)
    if val is None:
        return 0
    try:
        return len(val)
    except TypeError:
        return int(val) if val else 0

num_elements = int(stats.get("numElements", best_n) or best_n)
n_warn = _len_or_zero("warningElements")
n_fail = _len_or_zero("failedElements")
n_na = _len_or_zero("naElements")

warn_pct = (100.0 * n_warn / num_elements) if num_elements else 0.0
fail_pct = (100.0 * n_fail / num_elements) if num_elements else 0.0

result = {
    "mesh_inp": MESH_INP,
    "part_name": part_name,
    "criterion": "ANALYSIS_CHECKS",
    "numElements": num_elements,
    "warningElements": n_warn,
    "failedElements": n_fail,
    "naElements": n_na,
    "warning_pct": warn_pct,
    "failed_pct": fail_pct,
    "stats_keys": sorted([str(k) for k in stats.keys()]),
}

out_dir = os.path.dirname(OUT_JSON)
if out_dir and not os.path.isdir(out_dir):
    os.makedirs(out_dir)

with open(OUT_JSON, "w") as f:
    json.dump(result, f, indent=2)

print("Wrote", OUT_JSON)
print(
    "numElements=%d warning=%d (%.4f%%) failed=%d (%.4f%%)"
    % (num_elements, n_warn, warn_pct, n_fail, fail_pct)
)
