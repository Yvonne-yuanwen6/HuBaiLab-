"""OpenCASCADE MakerVolume helpers for thin-rod array fusion.

BRepAlgoAPI_Fuse often returns empty/tiny mass when neighbouring thin-strut
cells only touch. OCC docs recommend BOPAlgo_MakerVolume (optionally after
Sewing faces) for reconstructing closed solids from connected geometry.
"""

from __future__ import annotations

from typing import Any

from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def _collect_faces(shape: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    faces: list[Any] = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        faces.append(TopoDS.Face_s(exp.Current()))
        exp.Next()
    return faces


def ocp_maker_volume(
    shapes: list[Any],
    *,
    fuzzy_mm: float = 0.05,
    glue: str = "shift",
    intersect: bool = True,
    label: str = "maker-volume",
) -> tuple[Any, dict[str, Any]]:
    """Run BOPAlgo_MakerVolume on solids/faces; return largest solid + report."""
    from OCP.BOPAlgo import BOPAlgo_GlueEnum, BOPAlgo_MakerVolume
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopTools import TopTools_ListOfShape

    if not shapes:
        raise RuntimeError(f"{label}: no shapes")

    args = TopTools_ListOfShape()
    for sh in shapes:
        args.Append(sh)

    mv = BOPAlgo_MakerVolume()
    mv.SetArguments(args)
    mv.SetIntersect(bool(intersect))
    if fuzzy_mm > 0.0:
        mv.SetFuzzyValue(float(fuzzy_mm))
    glue_l = str(glue).strip().lower()
    if glue_l == "shift":
        mv.SetGlue(BOPAlgo_GlueEnum.BOPAlgo_GlueShift)
    elif glue_l == "full":
        mv.SetGlue(BOPAlgo_GlueEnum.BOPAlgo_GlueFull)
    elif glue_l not in ("off", "", "none"):
        raise ValueError(f"unknown glue={glue!r}")

    print(
        f"  {label}: MakerVolume n={len(shapes)} fuzzy={fuzzy_mm:g} "
        f"glue={glue_l} intersect={intersect}",
        flush=True,
    )
    mv.Perform()
    if mv.HasErrors():
        raise RuntimeError(f"{label}: MakerVolume HasErrors")

    result = mv.Shape()
    solids: list[Any] = []
    exp = TopExp_Explorer(result, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    if not solids:
        raise RuntimeError(f"{label}: MakerVolume produced 0 solids")

    masses = [ocp_mass(s) for s in solids]
    best_i = max(range(len(solids)), key=lambda i: masses[i])
    best = solids[best_i]
    report = {
        "method": "BOPAlgo_MakerVolume",
        "n_input": len(shapes),
        "n_solids": len(solids),
        "masses_mm3": masses,
        "best_mass_mm3": float(masses[best_i]),
        "fuzzy_mm": float(fuzzy_mm),
        "glue": glue_l,
        "intersect": bool(intersect),
    }
    print(
        f"  {label}: solids={len(solids)} best_mass={masses[best_i]:.1f} "
        f"sum={sum(masses):.1f}",
        flush=True,
    )
    return best, report


def ocp_sew_faces_then_maker_volume(
    shapes: list[Any],
    *,
    sew_tol_mm: float = 0.05,
    fuzzy_mm: float = 0.05,
    glue: str = "shift",
    label: str = "sew-makervol",
) -> tuple[Any, dict[str, Any]]:
    """Explode to faces → Sewing → MakerVolume (OCC-recommended path)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

    faces: list[Any] = []
    for sh in shapes:
        faces.extend(_collect_faces(sh))
    if not faces:
        raise RuntimeError(f"{label}: no faces")

    print(
        f"  {label}: Sewing {len(faces)} face(s), tol={sew_tol_mm:g} mm...",
        flush=True,
    )
    sewer = BRepBuilderAPI_Sewing(float(sew_tol_mm))
    sewer.SetNonManifoldMode(True)
    for f in faces:
        sewer.Add(f)
    sewer.Perform()
    sewn = sewer.SewedShape()
    sew_rep = {
        "free_edges": int(sewer.NbFreeEdges()),
        "multiple_edges": int(sewer.NbMultipleEdges()),
        "degenerated": int(sewer.NbDegeneratedShapes()),
        "n_faces": len(faces),
        "sew_tol_mm": float(sew_tol_mm),
    }
    print(
        f"  {label}: sew free={sew_rep['free_edges']} "
        f"mult={sew_rep['multiple_edges']} deg={sew_rep['degenerated']}",
        flush=True,
    )

    solid, mv_rep = ocp_maker_volume(
        [sewn],
        fuzzy_mm=fuzzy_mm,
        glue=glue,
        intersect=True,
        label=f"{label}-mv",
    )
    report = {"sew": sew_rep, "maker_volume": mv_rep}
    return solid, report


def gate_mass_ok(got: float, expected: float, *, lo: float = 0.85, hi: float = 1.15) -> bool:
    return expected > 0.0 and lo <= got / expected <= hi
