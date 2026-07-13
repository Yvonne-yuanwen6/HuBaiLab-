"""HuBaiLab web API entry point.

User-facing Web UI docs (keep in sync when changing routes/UI):
  docs/Abaqus_WebUI使用说明.md
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import abaqus_cases, abaqus_export, abaqus_jobs, abaqus_post, abaqus_trash, tasks

app = FastAPI(title="HuBaiLab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "api_version": "0.1.0",
        "features": ["sync-output", "case-list-wrapper", "discover-remote"],
    }


app.include_router(abaqus_cases.router)
app.include_router(abaqus_jobs.router)
app.include_router(abaqus_export.router)
app.include_router(abaqus_post.router)
app.include_router(abaqus_trash.router)
app.include_router(tasks.router)

# 开发模式请用 Vite :5173；单进程静态页见 docs §2.2（npm run build 后另行挂载）
