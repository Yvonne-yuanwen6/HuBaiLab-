"""CAD / STEP generation routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.abaqus import CadGenerateRequest, TaskResponse
from api.services.task_manager import start_python_script

router = APIRouter(prefix="/api/abaqus/cad", tags=["abaqus-cad"])


def _effective_q(body: CadGenerateRequest) -> float:
    structure = (body.structure or "").strip().lower()
    if structure == "bcc":
        return 0.0
    q = float(body.Q)
    if structure == "sfbls" and q <= 0.0:
        return 0.5
    return q


@router.post("/generate", response_model=TaskResponse)
def generate_cad(body: CadGenerateRequest) -> TaskResponse:
    if body.backend not in ("ocp", "gmsh"):
        raise HTTPException(status_code=400, detail="backend must be ocp or gmsh")
    if body.mode not in ("auto", "stepwise", "auto_only"):
        raise HTTPException(status_code=400, detail="mode must be auto, stepwise, or auto_only")

    q = _effective_q(body)
    args = [
        "--Q",
        str(q),
        "--cells",
        str(int(body.cells)),
        "--L",
        str(float(body.L)),
        "--backend",
        body.backend,
        "--ocp-fuse-mode",
        body.ocp_fuse_mode,
    ]
    if body.force:
        args.append("--force")
    if body.mode == "auto_only":
        args.append("--auto-only")
    elif body.mode == "stepwise":
        args.append("--stepwise-only")

    variant = "bcc" if q <= 0 else "sfbls"
    slug_hint = f"cad_{variant}_L{int(body.L)}_{int(body.cells)}x{int(body.cells)}x{int(body.cells)}_q{str(q).replace('.', 'p')}"
    task = start_python_script(
        "scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py",
        args,
        slug=slug_hint,
    )
    return TaskResponse(**task)
