from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException

from orchestrator import DockerOrchestrator
from .contracts import WorkerJob, WorkerResult

TOKEN = os.getenv("NETLAB_WORKER_TOKEN", "")
app = FastAPI(title="Netlab Studio Docker Worker", version="0.1.0")


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        raise HTTPException(status_code=503, detail="worker authentication is not configured")
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="invalid worker token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "netlab-docker-worker"}


@app.post("/v1/jobs", response_model=WorkerResult, dependencies=[Depends(require_token)])
def execute_job(job: WorkerJob) -> WorkerResult:
    orchestrator = DockerOrchestrator(job.topology)
    if job.action == "status":
        return WorkerResult(job_id=job.job_id, ok=True, action=job.action, nodes=orchestrator.status())
    if job.action == "terminal":
        if not job.node_name:
            raise HTTPException(status_code=400, detail="node_name is required for terminal jobs")
        result = orchestrator.terminal(job.node_name, job.command)
    else:
        result = orchestrator.action(job.action)
    return WorkerResult(job_id=job.job_id, ok=result.ok, action=result.action, exit_code=result.exit_code, output=result.output)
