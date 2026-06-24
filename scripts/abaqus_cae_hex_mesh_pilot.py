"""
Pilot: mesh a verified STEP in Abaqus/CAE (built-in hex or tet).

Run (from repo root):
  abaqus cae noGUI=scripts/abaqus_cae_hex_mesh_pilot.py

Environment (optional):
  HU_BAI_STEP              path to STEP (default: BCC 4x4x4 verified)
  HU_BAI_SEED              global seed size mm (default: 1.2)
  HU_BAI_OUT               output INP path
  HU_BAI_PART_NAME         Part name in CAE (default: LATTICE)
  HU_BAI_MERGE_SOLIDS      1/true to combine+mergeSolidRegions on import
  HU_BAI_MESH_MODE         hex (default) or tet (C3D4 free mesh)
  HU_BAI_MESH_QUALITY      fast | lattice | lattice_contact | paper
  HU_BAI_ROD_DIAMETER      strut diameter mm (default: 2.0)
  HU_BAI_RODS_PER_DIAMETER target elems across rod diameter (default: 3.0)
  HU_BAI_SURFACE_SEED_FACTOR  face seed = global * factor (lattice_contact)
  HU_BAI_DEVIATION_FACTOR  override seedPart deviationFactor
  HU_BAI_MIN_SIZE_FACTOR   override seedPart minSizeFactor
  HU_BAI_VIRTUAL_TOPOLOGY  1/true: createVirtualTopology before mesh
  HU_BAI_VTOPO_SMALL_FACE  smallFaceAreaThreshold [mm^2] (default 4.0)
  HU_BAI_VTOPO_SHORT_EDGE  shortEdgeThreshold [mm] (default 0.8)
  HU_BAI_VTOPO_SLIVER_AR   faceAspectRatioThreshold (default 15)
  HU_BAI_VTOPO_CORNER_ANGLE smallFaceCornerAngleThreshold [deg] (default 75)
"""

from __future__ import print_function

import math
import os

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
MESH_QUALITY = os.environ.get(
    "HU_BAI_MESH_QUALITY",
    "lattice_contact" if MESH_MODE == "tet" else "fast",
).lower()


def _env_float(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


ROD_DIAMETER_MM = float(os.environ.get("HU_BAI_ROD_DIAMETER", "2.0"))
RODS_PER_DIAMETER = float(os.environ.get("HU_BAI_RODS_PER_DIAMETER", "3.0"))
VIRTUAL_TOPOLOGY = os.environ.get("HU_BAI_VIRTUAL_TOPOLOGY", "").lower() in (
    "1",
    "true",
    "yes",
)
VTOPO_SMALL_FACE = _env_float("HU_BAI_VTOPO_SMALL_FACE", 4.0)
VTOPO_SHORT_EDGE = _env_float("HU_BAI_VTOPO_SHORT_EDGE", 0.8)
VTOPO_SLIVER_AR = _env_float("HU_BAI_VTOPO_SLIVER_AR", 15.0)
VTOPO_CORNER_ANGLE = _env_float("HU_BAI_VTOPO_CORNER_ANGLE", 75.0)
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

QUALITY_PRESETS = {
    "fast": dict(
        deviation=0.10,
        min_size=0.25,
        surface_faces=False,
        short_edge_seeds=False,
        all_edge_seeds=False,
        min_transition=False,
    ),
    "lattice": dict(
        deviation=0.10,
        min_size=0.45,
        surface_faces=False,
        short_edge_seeds=False,
        all_edge_seeds=True,
        min_transition=False,
    ),
    # Self-contact oriented: finer exterior + junction short edges, coarser interior.
    "lattice_contact": dict(
        deviation=0.10,
        min_size=0.55,
        surface_faces=False,
        surface_factor=0.72,
        short_edge_seeds=True,
        fine_edge_ratio=0.40,
        short_edge_ratio=6.0,
        all_edge_seeds=False,
        min_transition=False,
        size_growth=1.12,
    ),
    "paper": dict(
        deviation=0.06,
        min_size=0.40,
        surface_faces=True,
        surface_factor=0.65,
        short_edge_seeds=True,
        short_edge_ratio=1.25,
        all_edge_seeds=False,
        min_transition=True,
        size_growth=1.10,
    ),
}


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
log(
    "Mesh config: mode=%s quality=%s seed=%.4g mm rod=%.4g mm vtopo=%s"
    % (MESH_MODE, MESH_QUALITY, SEED_MM, ROD_DIAMETER_MM, VIRTUAL_TOPOLOGY)
)
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

try:
    p.removeRedundantEntities(vertexAndEdgeAccuracy=0.001, faceAngleTolerance=0.15)
    log("removeRedundantEntities OK")
except Exception as exc:
    log("removeRedundantEntities skipped: %s" % exc)


def apply_virtual_topology(part_obj):
    if not VIRTUAL_TOPOLOGY:
        return
    n_faces = len(part_obj.faces)
    n_edges = len(part_obj.edges)
    log(
        "virtual topology BEFORE: faces=%d edges=%d (smallFace<=%.3g mm2 shortEdge<=%.3g mm sliverAR<=%.3g corner<=%.3g deg)"
        % (
            n_faces,
            n_edges,
            VTOPO_SMALL_FACE,
            VTOPO_SHORT_EDGE,
            VTOPO_SLIVER_AR,
            VTOPO_CORNER_ANGLE,
        )
    )
    kwargs = dict(
        regions=part_obj.faces,
        mergeShortEdges=True,
        shortEdgeThreshold=VTOPO_SHORT_EDGE,
        mergeSmallFaces=True,
        smallFaceAreaThreshold=VTOPO_SMALL_FACE,
        mergeSliverFaces=True,
        faceAspectRatioThreshold=VTOPO_SLIVER_AR,
        mergeSmallAngleFaces=True,
        smallFaceCornerAngleThreshold=VTOPO_CORNER_ANGLE,
        ignoreRedundantEntities=True,
    )
    try:
        part_obj.createVirtualTopology(**kwargs)
        log("createVirtualTopology OK (full)")
    except TypeError as exc:
        log("createVirtualTopology full failed (%s); retry minimal" % exc)
        try:
            part_obj.createVirtualTopology(
                regions=part_obj.faces,
                mergeSmallFaces=True,
                smallFaceAreaThreshold=VTOPO_SMALL_FACE,
                mergeShortEdges=True,
                shortEdgeThreshold=VTOPO_SHORT_EDGE,
            )
            log("createVirtualTopology OK (minimal)")
        except Exception as exc2:
            log("createVirtualTopology FAILED: %s" % exc2)
            raise
    except Exception as exc:
        log("createVirtualTopology FAILED: %s" % exc)
        raise
    log(
        "virtual topology AFTER: faces=%d edges=%d"
        % (len(part_obj.faces), len(part_obj.edges))
    )


def _quality_params():
    preset = QUALITY_PRESETS.get(MESH_QUALITY, QUALITY_PRESETS["lattice_contact"])
    deviation = _env_float("HU_BAI_DEVIATION_FACTOR", preset["deviation"])
    min_size = _env_float("HU_BAI_MIN_SIZE_FACTOR", preset["min_size"])
    return preset, deviation, min_size


def _edge_lengths(part_obj):
    """Edge lengths [mm] from geometry."""
    try:
        return list(part_obj.getEdgeLength(edges=part_obj.edges))
    except Exception:
        pass
    lengths = []
    for edge in part_obj.edges:
        try:
            lengths.append(edge.getSize(printResults=OFF))
        except TypeError:
            try:
                lengths.append(edge.getSize())
            except Exception:
                lengths.append(1.0e9)
        except Exception:
            lengths.append(1.0e9)
    return lengths


def _is_c3d4_element(el):
    try:
        code = el.type
        if code == C3D4:
            return True
    except Exception:
        pass
    return "C3D4" in str(getattr(el, "type", ""))


def _seed_face_by_size(part_obj, face_size, deviation, min_size):
    """Refine boundary edges (Abaqus 2022 has no seedFaceBySize on Part)."""
    boundary_edges = part_obj.edges
    if not boundary_edges:
        return 0
    _seed_edges_by_size(
        part_obj, boundary_edges, face_size, deviation, min_size
    )
    return len(boundary_edges)


def seed_junction_edges(part_obj, preset, deviation, min_size):
    if not preset.get("short_edge_seeds") and not preset.get("surface_faces"):
        return
    lengths = _edge_lengths(part_obj)
    if not lengths:
        log("junction edge seeds skipped: no edge lengths")
        return

    fine_factor = preset.get("surface_factor", 0.70)
    fine_size = SEED_MM * fine_factor
    mid_size = min(SEED_MM, ROD_DIAMETER_MM / max(RODS_PER_DIAMETER, 1.0))
    fine_thresh = ROD_DIAMETER_MM * preset.get("fine_edge_ratio", 0.65)
    mid_thresh = ROD_DIAMETER_MM * preset.get("short_edge_ratio", 1.35)

    fine_edges = []
    mid_edges = []
    for edge, length in zip(part_obj.edges, lengths):
        if length <= fine_thresh:
            fine_edges.append(edge)
        elif length <= mid_thresh:
            mid_edges.append(edge)

    if fine_edges and fine_size < SEED_MM * 0.98:
        _seed_edges_by_size(part_obj, tuple(fine_edges), fine_size, deviation, min_size)
        log(
            "junction fine edges=%d/%d size=%.4g mm (L<=%.3g)"
            % (len(fine_edges), len(part_obj.edges), fine_size, fine_thresh)
        )
    if mid_edges and mid_size < SEED_MM * 0.98:
        _seed_edges_by_size(part_obj, tuple(mid_edges), mid_size, deviation, min_size)
        log(
            "junction mid edges=%d/%d size=%.4g mm (L<=%.3g)"
            % (len(mid_edges), len(part_obj.edges), mid_size, mid_thresh)
        )


def _seed_edges_by_size(part_obj, edges, edge_size, deviation, min_size):
    if not edges:
        return
    try:
        part_obj.seedEdgeBySize(
            edges=edges,
            size=edge_size,
            deviationFactor=deviation,
            minSizeFactor=min_size,
            constraint=FINER,
        )
    except TypeError:
        part_obj.seedEdgeBySize(
            edges=edges,
            size=edge_size,
            constraint=FINER,
        )


def apply_seeds(part_obj):
    preset, deviation, min_size = _quality_params()
    part_obj.seedPart(
        size=SEED_MM,
        deviationFactor=deviation,
        minSizeFactor=min_size,
    )
    log(
        "seedPart size=%.4g deviation=%.4g minSizeFactor=%.4g"
        % (SEED_MM, deviation, min_size)
    )

    lengths = _edge_lengths(part_obj)
    if lengths:
        ls = sorted(lengths)
        log(
            "edge lengths mm: min=%.4g p50=%.4g p95=%.4g max=%.4g (n=%d)"
            % (ls[0], ls[len(ls) // 2], ls[int(0.95 * (len(ls) - 1))], ls[-1], len(ls))
        )

    if preset.get("surface_faces") and len(part_obj.faces):
        face_factor = _env_float(
            "HU_BAI_SURFACE_SEED_FACTOR",
            preset.get("surface_factor", 0.70),
        )
        face_size = SEED_MM * face_factor
        if face_size < SEED_MM * 0.98:
            n_edges = _seed_face_by_size(part_obj, face_size, deviation, min_size)
            log(
                "surface edge refine (no seedFaceBySize): edges=%d size=%.4g mm factor=%.3g"
                % (n_edges, face_size, face_factor)
            )

    seed_junction_edges(part_obj, preset, deviation, min_size)

    if preset.get("all_edge_seeds") and ROD_DIAMETER_MM > 0 and RODS_PER_DIAMETER > 0:
        rod_edge_size = min(SEED_MM, ROD_DIAMETER_MM / max(RODS_PER_DIAMETER, 1.0))
        elems_across_rod = ROD_DIAMETER_MM / SEED_MM if SEED_MM > 0 else 0.0
        if rod_edge_size < SEED_MM * 0.95 and elems_across_rod < RODS_PER_DIAMETER - 0.25:
            _seed_edges_by_size(
                part_obj, part_obj.edges, rod_edge_size, deviation, min_size
            )
            log(
                "seedEdgeBySize all edges=%d size=%.4g mm"
                % (len(part_obj.edges), rod_edge_size)
            )
        else:
            log(
                "skip all-edge seeds: ~%.2f elems/rod (target %.2f)"
                % (elems_across_rod, RODS_PER_DIAMETER)
            )


def set_tet_mesh_controls(part_obj, algorithm=None):
    preset, _, _ = _quality_params()
    base = dict(regions=part_obj.cells, elemShape=TET, technique=FREE)
    if algorithm == ADVANCING_FRONT:
        base["algorithm"] = ADVANCING_FRONT
    extras = ()
    if preset.get("min_transition"):
        growth = preset.get("size_growth", 1.12)
        extras = (
            dict(minTransition=ON, sizeGrowth=growth),
            dict(minTransition=ON),
            {},
        )
    else:
        extras = ({},)
    for extra in extras:
        try:
            part_obj.setMeshControls(**dict(base, **extra))
            if extra:
                log("setMeshControls extras: %s" % extra)
            return
        except TypeError:
            continue
    part_obj.setMeshControls(**base)


def node_coord_map(part_obj):
    by_label = {}
    by_index = {}
    for idx, node in enumerate(part_obj.nodes):
        by_index[idx] = node.coordinates
        by_label[node.label] = node.coordinates
    return by_label, by_index


def node_coords(by_label, by_index, node_id):
    if node_id in by_label:
        return by_label[node_id]
    if node_id in by_index:
        return by_index[node_id]
    raise KeyError(node_id)


def tet_aspect_ratio(by_label, by_index, n1, n2, n3, n4):
    pts = [
        node_coords(by_label, by_index, n1),
        node_coords(by_label, by_index, n2),
        node_coords(by_label, by_index, n3),
        node_coords(by_label, by_index, n4),
    ]
    edges = []
    for i in range(4):
        for j in range(i + 1, 4):
            dx = pts[i][0] - pts[j][0]
            dy = pts[i][1] - pts[j][1]
            dz = pts[i][2] - pts[j][2]
            edges.append(math.sqrt(dx * dx + dy * dy + dz * dz))
    emax = max(edges)
    emin = min(edges)
    return emax / max(emin, 1.0e-9)


def log_mesh_quality(part_obj, sample_limit=120000):
    by_label, by_index = node_coord_map(part_obj)
    aspects = []
    n_bad = 0
    n_sampled = 0
    for el in part_obj.elements:
        if not _is_c3d4_element(el):
            continue
        conn = el.connectivity
        if len(conn) < 4:
            continue
        try:
            ar = tet_aspect_ratio(by_label, by_index, conn[0], conn[1], conn[2], conn[3])
        except KeyError:
            continue
        aspects.append(ar)
        if ar > 10.0:
            n_bad += 1
        n_sampled += 1
        if n_sampled >= sample_limit:
            break
    if not aspects:
        log("mesh quality: no C3D4 elements sampled")
        return
    aspects.sort()
    p50 = aspects[len(aspects) // 2]
    p95 = aspects[int(0.95 * (len(aspects) - 1))]
    log(
        "mesh quality (sample n=%d): aspect p50=%.2f p95=%.2f max=%.2f bad(>10)=%d"
        % (len(aspects), p50, p95, aspects[-1], n_bad)
    )


def log_mesh_summary(part_obj):
    type_counts = {}
    for el in part_obj.elements:
        t = el.type
        type_counts[t] = type_counts.get(t, 0) + 1
    log("Nodes: %d Elements: %d" % (len(part_obj.nodes), len(part_obj.elements)))
    log("Element types: %s" % type_counts)
    print("Nodes:", len(part_obj.nodes), "Elements:", len(part_obj.elements))
    print("Element types:", type_counts)
    log_mesh_quality(part_obj)


def try_mesh(part_obj, label, setup_fn):
    try:
        setup_fn()
        part_obj.generateMesh()
        if len(part_obj.elements) == 0:
            raise RuntimeError("generateMesh produced 0 elements")
        log("Mesh OK with %s" % label)
        print("Mesh OK with", label)
        return True, label
    except Exception as exc:
        log("Mesh failed %s: %s" % (label, exc))
        try:
            part_obj.deleteMesh()
        except Exception:
            pass
        return False, "%s: %s" % (label, exc)


def score_mesh(part_obj):
    by_label, by_index = node_coord_map(part_obj)
    aspects = []
    step = max(1, len(part_obj.elements) // 80000)
    for idx, el in enumerate(part_obj.elements):
        if idx % step:
            continue
        if not _is_c3d4_element(el):
            continue
        conn = el.connectivity
        if len(conn) < 4:
            continue
        try:
            aspects.append(
                tet_aspect_ratio(by_label, by_index, conn[0], conn[1], conn[2], conn[3])
            )
        except KeyError:
            continue
    if not aspects:
        return 1.0e9, 0
    aspects.sort()
    p95 = aspects[int(0.95 * (len(aspects) - 1))]
    n_elem = len(part_obj.elements)
    return p95 + 0.15 * (n_elem / 1000000.0), p95


apply_virtual_topology(p)
apply_seeds(p)

mesh_ok = False
mesh_errors = []
mesh_label = ""
best_part = None
best_score = 1.0e18
best_label = ""

if MESH_MODE == "tet":
    elem_type_tet = mesh.ElemType(elemCode=C3D4, elemLibrary=STANDARD)
    p.setElementType(regions=(p.cells,), elemTypes=(elem_type_tet,))

    tet_attempts = (
        ("TET_FREE", lambda: set_tet_mesh_controls(p, algorithm=None)),
        (
            "TET_FREE_AF",
            lambda: set_tet_mesh_controls(p, algorithm=ADVANCING_FRONT),
        ),
    )
    compare_algorithms = MESH_QUALITY in ("lattice_contact", "paper")
    for label, setup in tet_attempts:
        ok, info = try_mesh(p, label, setup)
        if not ok:
            mesh_errors.append(info)
            continue
        score, p95 = score_mesh(p)
        log("mesh score %s: p95_aspect=%.2f penalty=%.4f" % (label, p95, score))
        if score < best_score:
            best_score = score
            best_label = label
            mesh_ok = True
            mesh_label = label
        if not compare_algorithms:
            break
        try:
            p.deleteMesh()
        except Exception:
            pass

    if mesh_ok and best_label != tet_attempts[-1][0]:
        for label, setup in tet_attempts:
            if label == best_label:
                ok, info = try_mesh(p, label, setup)
                if not ok:
                    mesh_errors.append(info)
                    mesh_ok = False
                break
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
    hex_attempts = (
        (
            "HEX_DOMINATED_AF",
            lambda: p.setMeshControls(
                regions=p.cells,
                elemShape=HEX_DOMINATED,
                technique=FREE,
                algorithm=ADVANCING_FRONT,
            ),
        ),
        (
            "HEX_DOMINATED",
            lambda: p.setMeshControls(
                regions=p.cells, elemShape=HEX_DOMINATED, technique=FREE
            ),
        ),
        (
            "HEX_SWEEP",
            lambda: p.setMeshControls(
                regions=p.cells, elemShape=HEX, technique=SWEEP
            ),
        ),
    )
    for label, setup in hex_attempts:
        ok, info = try_mesh(p, label, setup)
        if ok:
            mesh_ok = True
            mesh_label = label
            break
        mesh_errors.append(info)

if not mesh_ok:
    raise RuntimeError(
        "CAE %s mesh failed:\n" % MESH_MODE + "\n".join(mesh_errors)
    )

log("Selected technique: %s (score=%.4f)" % (mesh_label, best_score))
log_mesh_summary(p)

model.rootAssembly.DatumCsysByDefault(CARTESIAN)
model.rootAssembly.Instance(name=part_name + "_INST", part=p, dependent=ON)

job_name = "cae_hex_export"
if job_name in mdb.jobs.keys():
    del mdb.jobs[job_name]
mdb.Job(name=job_name, model=model_name, type=ANALYSIS, memory=90, memoryUnits=PERCENTAGE)
mdb.jobs[job_name].writeInput(consistencyChecking=OFF)

src_inp = os.path.join(os.getcwd(), job_name + ".inp")
if not os.path.isfile(src_inp):
    raise IOError("Expected INP not written: %s" % src_inp)

with open(src_inp, "rb") as f_in:
    data = f_in.read()
with open(OUT_INP, "wb") as f_out:
    f_out.write(data)

print("Wrote:", OUT_INP)
