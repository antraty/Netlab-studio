from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


JobAction = Literal["up", "down", "verify", "status", "terminal"]


class WorkerJob(BaseModel):
    job_id: str
    action: JobAction
    topology: dict[str, Any]
    node_name: str | None = None
    command: list[str] = Field(default_factory=list)


class WorkerResult(BaseModel):
    job_id: str
    ok: bool
    action: str
    exit_code: int = 0
    output: str = ""
    nodes: list[dict[str, str]] = Field(default_factory=list)
