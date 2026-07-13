"""Abaqus post-processing routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.abaqus import TaskResponse
from api.services.task_manager import start_python_script
from src.paths import export_dir_for_slug, job_dir_for_slug, post_dir_for_slug

router = APIRouter(prefix="/api/abaqus", tags=["abaqus-post"])


@router.post("/jobs/{slug}/extract", response_model=TaskResponse)
def extract_curve(slug: str) -> TaskResponse:
    odb = job_dir_for_slug(slug) / f"{slug}.odb"
    if not odb.is_file():
        raise HTTPException(status_code=400, detail="ODB not found; complete job or sync remote first")
    meta = export_dir_for_slug(slug) / f"{slug}_meta.json"
    post_dir = post_dir_for_slug(slug)
    post_dir.mkdir(parents=True, exist_ok=True)
    csv_path = post_dir / f"{slug}_stress_strain.csv"
    args = [
        "--odb",
        str(odb),
        "--csv",
        str(csv_path),
        "--yield-json",
        str(post_dir / f"{slug}_yield.json"),
    ]
    if meta.is_file():
        args.extend(["--meta", str(meta)])
    task = start_python_script("scripts/extract_stress_strain_from_odb.py", args, slug=slug)
    return TaskResponse(**task)


@router.post("/jobs/{slug}/plot", response_model=TaskResponse)
def plot_curve(slug: str) -> TaskResponse:
    post_dir = post_dir_for_slug(slug)
    csv_path = post_dir / f"{slug}_stress_strain.csv"
    if not csv_path.is_file():
        raise HTTPException(status_code=400, detail="Curve CSV not found; run extract first")
    png_path = post_dir / f"{slug}_stress_strain.png"
    task = start_python_script(
        "scripts/plot_stress_strain.py",
        ["--csv", str(csv_path), "--png", str(png_path)],
        slug=slug,
    )
    return TaskResponse(**task)
