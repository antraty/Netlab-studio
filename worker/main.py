from __future__ import annotations

import os
import hmac
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException

from orchestrator import DockerOrchestrator
from .contracts import WorkerJob, WorkerResult
from backend.app.security import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    validate_production_topology,
    validate_worker_settings,
)

TOKEN = os.getenv("NETLAB_WORKER_TOKEN", "")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_worker_settings()
    yield


app = FastAPI(title="Netlab Studio Docker Worker", version="0.1.0", lifespan=lifespan)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=2 * 1024 * 1024)
app.add_middleware(SecurityHeadersMiddleware)


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        raise HTTPException(status_code=503, detail="worker authentication is not configured")
    if not hmac.compare_digest(authorization or "", f"Bearer {TOKEN}"):
        raise HTTPException(status_code=401, detail="invalid worker token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "netlab-docker-worker"}


@app.post("/v1/jobs", response_model=WorkerResult, dependencies=[Depends(require_token)])
def execute_job(job: WorkerJob) -> WorkerResult:
    try:
        validate_production_topology(job.topology)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    orchestrator = DockerOrchestrator(job.topology)
    if job.action == "status":
        return WorkerResult(job_id=job.job_id, ok=True, action=job.action, nodes=orchestrator.status())
    if job.action == "observability":
        return WorkerResult(
            job_id=job.job_id,
            ok=True,
            action=job.action,
            observability=orchestrator.observability(),
        )
    if job.action == "terminal":
        if not job.node_name:
            raise HTTPException(status_code=400, detail="node_name is required for terminal jobs")
        result = orchestrator.terminal(job.node_name, job.command)
    else:
        result = orchestrator.action(job.action)
    return WorkerResult(job_id=job.job_id, ok=result.ok, action=result.action, exit_code=result.exit_code, output=result.output)
