from __future__ import annotations

import hmac
import os
import time
import threading
from pathlib import Path
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
from backend.app.education import EducationStore, EducationError

TOKEN = os.getenv("NETLAB_WORKER_TOKEN", "")
WORKER_ID = os.getenv("NETLAB_WORKER_ID", "docker-worker-1").strip() or "docker-worker-1"
WORKER_NAME = os.getenv("NETLAB_WORKER_NAME", WORKER_ID).strip() or WORKER_ID
QUEUE_STORE = EducationStore(
    os.getenv("NETLAB_DATABASE_URL")
    or os.getenv("NETLAB_EDUCATION_DB")
    or str(Path(os.getenv("NETLAB_DATA_DIR", "/tmp/netlab-worker")) / "education.sqlite3")
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_worker_settings()
    stop_event = threading.Event()
    QUEUE_STORE.register_worker(WORKER_ID, WORKER_NAME, ["docker"])

    def queue_poller() -> None:
        while not stop_event.wait(1):
            try:
                QUEUE_STORE.requeue_expired_jobs()
                job = QUEUE_STORE.claim_job(WORKER_ID)
                if not job:
                    continue
                orchestrator = DockerOrchestrator(job["topology"])
                started = time.monotonic()
                try:
                    if job["action"] == "status":
                        result_payload = {
                            "ok": True,
                            "exit_code": 0,
                            "output": "",
                            "nodes": orchestrator.status(),
                            "observability": None,
                        }
                    elif job["action"] == "observability":
                        result_payload = {
                            "ok": True,
                            "exit_code": 0,
                            "output": "",
                            "nodes": [],
                            "observability": orchestrator.observability(),
                        }
                    elif job["action"] == "terminal":
                        result = orchestrator.terminal(job["node_name"], job["command"])
                        result_payload = {
                            "ok": result.ok,
                            "exit_code": result.exit_code,
                            "output": result.output,
                            "nodes": [],
                            "observability": None,
                        }
                    else:
                        result = orchestrator.action(job["action"])
                        result_payload = {
                            "ok": result.ok,
                            "exit_code": result.exit_code,
                            "output": result.output,
                            "nodes": [],
                            "observability": None,
                        }
                    QUEUE_STORE.complete_job(
                        job["id"],
                        WORKER_ID,
                        result_payload["ok"],
                        result_payload["exit_code"],
                        result_payload["output"],
                        result_payload["nodes"],
                        result_payload["observability"],
                        int((time.monotonic() - started) * 1000),
                    )
                except (RuntimeError, ValueError) as exc:
                    QUEUE_STORE.complete_job(
                        job["id"], WORKER_ID, False, 1, str(exc),
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
            except EducationError:
                continue

    poller = threading.Thread(target=queue_poller, name="netlab-worker-queue", daemon=True)
    poller.start()
    try:
        yield
    finally:
        stop_event.set()


app = FastAPI(title="Netlab Studio Docker Worker", version="0.4.0", lifespan=lifespan)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=2 * 1024 * 1024)
app.add_middleware(SecurityHeadersMiddleware)


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        raise HTTPException(status_code=503, detail="worker authentication is not configured")
    bearer = f"Bearer {TOKEN}"
    if not hmac.compare_digest(authorization or "", bearer):
        raise HTTPException(status_code=401, detail="invalid worker token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "netlab-docker-worker", "worker_id": WORKER_ID}


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
    return WorkerResult(
        job_id=job.job_id,
        ok=result.ok,
        action=result.action,
        exit_code=result.exit_code,
        output=result.output,
        worker_id=WORKER_ID,
    )
