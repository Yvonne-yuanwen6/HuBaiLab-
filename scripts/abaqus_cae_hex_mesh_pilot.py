"""
Pilot: mesh a verified STEP in Abaqus/CAE (built-in hex or tet).

Run (from repo root):
  abaqus cae noGUI=scripts/abaqus_cae_hex_mesh_pilot.py

Environment (optional):
  HU_BAI_STEP          path to STEP (default: BCC 4x4x4 verified)
  HU_BAI_SEED          global seed size mm (default: 1.2)
  HU_BAI_OUT           output INP path
  HU_BAI_PART_NAME     Part name in CAE (default: LATTICE)
  HU_BAI_MERGE_SOLIDS  1/true to combine+mergeSolidRegions on import
  HU_BAI_MESH_MODE     hex (default) or tet (C3D4 free mesh)
"""

from __future__ import print_function

import os
import sys

from abaqus import *
from abaqusConstants import *
import mesh
import part

ROOT = os.environ.get("HU_BAI_ROOT", os.getcwd())
DEFAULT_STEP = os.path.join(
    ROOT,
    "output",
    "cad",
    "verified",
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_merged.step",
)
STEP_PATH = os.environ.get("HU_BAI_STEP", DEFAULT_STEP)
SEED_MM = float(os.environ.get("HU_BAI_SEED", "1.2"))
PART_NAME = os.environ.get("HU_BAI_PART_NAME", "LATTICE")
MERGE_SOLIDS = os.environ.get("HU_BAI_MERGE_SOLIDS", "").lower() in (
    "1",
    "true",
    "yes",
)
MESH_MODE = os.environ.get("HU_BAI_MESH_MODE", "hex").lower()
OUT_INP = os.environ.get(
    "HU_BAI_OUT",
    os.path.join(
        ROOT,
        "output",
        "export",
        "cae_hex_pilot",
        "bcc_cae_tet_mesh.inp" if MESH_MODE == "tet" else "bcc_cae_hex_mesh.inp",
    ),
)

if not os.path.isfile(STEP_PATH):
    raise IOError("STEP not found: %s" % STEP_PATH)

out_dir = os.path.dirname(OUT_INP)
if out_dir and not os.path.isdir(out_dir):
    os.makedirs(out_dir)

LOG_PATH = os.path.join(out_dir or ROOT, "cae_hex_pilot.log")


def log(msg):
    line = str(msg)
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


if os.path.isfile(LOG_PATH):
    os.remove(LOG_PATH)

model_name = "Model-1"
part_name = PART_NAME

print("Import STEP:", STEP_PATH)
log("Import STEP: %s" % STEP_PATH)
step_path = STEP_PATH.replace("\\", "/")

for name in list(mdb.models.keys()):
    if len(mdb.models) <= 1:
        break
    del mdb.models[name]
log("Models after clear: %s" % list(mdb.models.keys()))

if model_name not in mdb.models.keys():
    mdb.Model(name=model_name)
model = mdb.models[model_name]
if part_name in model.parts.keys():
    del model.parts[part_name]

# Match manual CAE replay: openStep returns a geometry handle; pass it to
# PartFromGeometryFile (not a STEP path string).
step_geom = mdb.openStep(step_path, scaleFromFile=OFF)
log("openStep OK; creating Part %s (merge=%s)" % (part_name, MERGE_SOLIDS))
part_kwargs = dict(
    name=part_name,
    geometryFile=step_geom,
    combine=MERGE_SOLIDS,
    dimensionality=THREE_D,
    type=DEFORMABLE_BODY,
)
if MERGE_SOLIDS:
    part_kwargs["mergeSolidRegions"] = True
model.PartFromGeometryFile(**part_kwargs)
p = model.parts[part_name]
log(
    "Part %s: cells=%d faces=%d edges=%d"
    % (part_name, len(p.cells), len(p.faces), len(p.edges))
)
if len(p.cells) == 0:
    raise RuntimeError("Part has no cells after import: %s" % STEP_PATH)

p.seedPart(size=SEED_MM, deviationFactor=0.1, minSizeFactor=0.25)

mesh_ok = False
mesh_errors = []
mesh_label = ""

if MESH_MODE == "tet":
    elem_type_tet = mesh.ElemType(elemCode=C3D4, elemLibrary=STANDARD)
    p.setElementType(regions=(p.cells,), elemTypes=(elem_type_tet,))
    for label, controls in (
        ("TET_FREE", dict(elemShape=TET, technique=FREE)),
        ("TET_DEFAULT", dict(elemShape=TET)),
    ):
        try:
            p.setMeshControls(regions=p.cells, **controls)
            p.generateMesh()
            if len(p.elements) == 0:
                raise RuntimeError("generateMesh produced 0 elements")
            mesh_ok = True
            mesh_label = label
            log("Mesh OK with %s (C3D4 tet)" % label)
            print("Mesh OK with", label, "(C3D4 tet)")
            break
        except Exception as exc:
            mesh_errors.append("%s: %s" % (label, exc))
            try:
                p.deleteMesh()
            except Exception:
                pass
else:
    elem_type_hex = mesh.ElemType(
        elemCode=C3D8R,
        elemLibrary=STANDARD,
        hourglassControl=DEFAULT,
        distortionControl=DEFAULT,
    )
    elem_type_wedge = mesh.ElemType(elemCode=C3D6, elemLibrary=STANDARD)
    elem_type_tet = mesh.ElemType(elemCode=C3D4, elemLibrary=STANDARD)
    p.setElementType(
        regions=(p.cells,),
        elemTypes=(elem_type_hex, elem_type_wedge, elem_type_tet),
    )
    for label, controls in (
        (
            "HEX_DOMINATED_AF",
            dict(elemShape=HEX_DOMINATED, technique=FREE, algorithm=ADVANCING_FRONT),
        ),
        ("HEX_DOMINATED", dict(elemShape=HEX_DOMINATED, technique=FREE)),
        ("HEX_SWEEP", dict(elemShape=HEX, technique=SWEEP)),
    ):
        try:
            p.setMeshControls(regions=p.cells, **controls)
            p.generateMesh()
            if len(p.elements) == 0:
                raise RuntimeError("generateMesh produced 0 elements")
            mesh_ok = True
            mesh_label = label
            log("Mesh OK with %s" % label)
            print("Mesh OK with", label)
            break
        except Exception as exc:
            mesh_errors.append("%s: %s" % (label, exc))
            try:
                p.deleteMesh()
            except Exception:
                pass

if not mesh_ok:
    raise RuntimeError(
        "CAE %s mesh failed:\n" % MESH_MODE + "\n".join(mesh_errors)
    )

log("Nodes: %d Elements: %d" % (len(p.nodes), len(p.elements)))
print("Nodes:", len(p.nodes), "Elements:", len(p.elements))

model.rootAssembly.DatumCsysByDefault(CARTESIAN)
model.rootAssembly.Instance(name=part_name + "_INST", part=p, dependent=ON)

job_name = "cae_hex_export"
if job_name in mdb.jobs.keys():
    del mdb.jobs[job_name]
mdb.Job(name=job_name, model=model_name, type=ANALYSIS, memory=90, memoryUnits=PERCENTAGE)
mdb.jobs[job_name].writeInput(consistencyChecking=OFF)

# Abaqus writes <job_name>.inp in cwd; copy/rename to HU_BAI_OUT.
src_inp = os.path.join(os.getcwd(), job_name + ".inp")
if not os.path.isfile(src_inp):
    raise IOError("Expected INP not written: %s" % src_inp)

with open(src_inp, "rb") as f_in:
    data = f_in.read()
with open(OUT_INP, "wb") as f_out:
    f_out.write(data)

print("Wrote:", OUT_INP)
