from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import netlab
from orchestrator import DockerOrchestrator, Orchestrator, RemoteWorkerOrchestrator

from .education import authenticate_websocket, require_teacher, router as education_router
from .models import CloneRequest, TerminalRequest, Topology, TopologyEnvelope, VersionInfo, VersionsResponse
from .storage import StorageError, TopologyStore
from .terminal import TerminalSession

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOPOLOGY = ROOT / "topology.json"
DEFAULT_DATA = ROOT / ".netlab-data"


def build_orchestrator(topology: dict) -> Orchestrator:
    worker_url = os.getenv("NETLAB_WORKER_URL")
    if worker_url:
        return RemoteWorkerOrchestrator(topology, worker_url, os.getenv("NETLAB_WORKER_TOKEN", ""))
    return DockerOrchestrator(topology)


class ControlPlane:
    def __init__(self, topology_path: Path = DEFAULT_TOPOLOGY, orchestrator_factory: Callable = build_orchestrator):
        self.topology_path = topology_path
        self.orchestrator_factory = orchestrator_factory
        self.store = TopologyStore(Path(os.getenv("NETLAB_DATA_DIR", DEFAULT_DATA)))
        initial = Topology.model_validate(netlab.load_topology(topology_path))
        try:
            initial = Topology.model_validate(self.store.load(initial.lab))
        except StorageError:
            pass
        self.topology = initial
        versions = self.store.list_versions(self.topology.lab)
        self.current_version = versions[0]["version"] if versions else None
        self.orchestrator: Orchestrator = orchestrator_factory(self.topology.to_topology_dict())
        self.events: list[str] = []

    def save(self, topology: Topology) -> None:
        topology_dict = topology.to_topology_dict()
        netlab.validate_topology(topology_dict)
        version = self.store.save(topology_dict)
        self.topology_path.write_text(json.dumps(topology_dict, indent=2) + "\n", encoding="utf-8")
        self.topology = topology
        self.current_version = version["version"]
        self.orchestrator = self.orchestrator_factory(topology_dict)
        self.record(f"topology saved as version {self.current_version}")

    def restore(self, version: int) -> None:
        topology_dict = self.store.restore(self.topology.lab, version)
        topology = Topology.model_validate(topology_dict)
        self.topology = topology
        self.current_version = self.store.list_versions(topology.lab)[0]["version"]
        self.topology_path.write_text(json.dumps(topology_dict, indent=2) + "\n", encoding="utf-8")
        self.orchestrator = self.orchestrator_factory(topology_dict)
        self.record(f"topology restored from version {version}")

    def clone(self, new_lab: str) -> Topology:
        topology = Topology.model_validate(self.store.clone(self.topology.lab, new_lab))
        self.record(f"laboratory cloned as {new_lab}")
        return topology

    def record(self, message: str) -> None:
        self.events.append(message)
        self.events = self.events[-100:]


control = ControlPlane(Path(os.getenv("NETLAB_TOPOLOGY", DEFAULT_TOPOLOGY)))
app = FastAPI(title="Netlab Studio Control API", version="0.5.0")
allowed_origins = [origin.strip() for origin in os.getenv(
    "NETLAB_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "X-Netlab-CSRF"],
)
app.include_router(education_router, prefix="/api")


@app.middleware("http")
async def validate_browser_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in allowed_origins:
        return JSONResponse(status_code=403, content={"detail": "origin is not allowed"})
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "netlab-control-api"}


@app.get("/api/topology", response_model=TopologyEnvelope, dependencies=[Depends(require_teacher)])
def get_topology() -> dict[str, Topology]:
    return {"topology": control.topology}


@app.post("/api/topology", response_model=TopologyEnvelope, dependencies=[Depends(require_teacher)])
def save_topology(envelope: TopologyEnvelope) -> dict[str, Topology]:
    try:
        control.save(envelope.topology)
    except (ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": control.topology}


@app.get("/api/laboratories/{lab}/versions", response_model=VersionsResponse, dependencies=[Depends(require_teacher)])
def list_versions(lab: str) -> VersionsResponse:
    try:
        return VersionsResponse(lab=lab, versions=control.store.list_versions(lab))
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/laboratories/{lab}/restore/{version}", response_model=TopologyEnvelope, dependencies=[Depends(require_teacher)])
def restore_version(lab: str, version: int) -> dict[str, Topology]:
    if lab != control.topology.lab:
        raise HTTPException(status_code=404, detail="laboratory is not active")
    try:
        control.restore(version)
    except (StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": control.topology}


@app.post("/api/laboratories/{lab}/clone", response_model=TopologyEnvelope, dependencies=[Depends(require_teacher)])
def clone_laboratory(lab: str, request: CloneRequest) -> dict[str, Topology]:
    if lab != control.topology.lab:
        raise HTTPException(status_code=404, detail="laboratory is not active")
    try:
        topology = control.clone(request.new_lab)
    except (StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": topology}


@app.get("/api/laboratories/{lab}/export", dependencies=[Depends(require_teacher)])
def export_laboratory(lab: str) -> dict[str, object]:
    try:
        return control.store.export(lab)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/laboratories/import", response_model=TopologyEnvelope, dependencies=[Depends(require_teacher)])
def import_laboratory(envelope: TopologyEnvelope) -> dict[str, Topology]:
    try:
        control.save(envelope.topology)
    except (StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": control.topology}


@app.get("/api/status", dependencies=[Depends(require_teacher)])
def get_status() -> dict[str, list[dict[str, str]]]:
    return {"nodes": control.orchestrator.status()}


@app.get("/api/logs", dependencies=[Depends(require_teacher)])
def get_logs() -> dict[str, list[str]]:
    return {"logs": control.events}


@app.post("/api/{action}", dependencies=[Depends(require_teacher)])
def run_action(action: str) -> dict[str, object]:
    if action not in {"up", "down", "verify"}:
        raise HTTPException(status_code=404, detail="unknown action")
    result = control.orchestrator.action(action)
    control.record(f"{action}: exit code {result.exit_code}")
    return {"ok": result.ok, "action": action, "exit_code": result.exit_code, "logs": control.events}


@app.post("/api/nodes/{node_name}/terminal", dependencies=[Depends(require_teacher)])
def run_terminal(node_name: str, request: TerminalRequest) -> dict[str, object]:
    try:
        result = control.orchestrator.terminal(node_name, request.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    control.record(f"terminal {node_name}: {' '.join(request.command)} -> {result.exit_code}")
    return {"ok": result.ok, "exit_code": result.exit_code, "output": result.output}


@app.websocket("/ws/nodes/{node_name}/terminal")
async def terminal_socket(websocket: WebSocket, node_name: str) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in allowed_origins:
        await websocket.close(code=1008, reason="origin is not allowed")
        return
    user = authenticate_websocket(websocket.cookies.get("netlab_session"))
    if not user:
        await websocket.close(code=1008, reason="authentication required")
        return
    if user["role"] != "teacher":
        await websocket.close(code=1008, reason="teacher role required")
        return
    await websocket.accept()
    session: TerminalSession | None = None
    try:
        if not isinstance(control.orchestrator, DockerOrchestrator):
            await websocket.send_text("remote worker terminal streaming is not implemented yet; use the local worker mode\n")
            return
        session = TerminalSession(control.orchestrator.container_name(node_name))
        await websocket.send_text(f"connected to {node_name}\n")
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            for chunk in session.drain():
                await websocket.send_text(chunk.decode(errors="replace"))
            if receive_task.done():
                try:
                    command = receive_task.result()
                except WebSocketDisconnect:
                    break
                session.write(command)
                control.record(f"terminal websocket {node_name}: command received")
                receive_task = asyncio.create_task(websocket.receive_text())
            await asyncio.sleep(0.05)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        await websocket.send_text(f"terminal error: {exc}\n")
    finally:
        if "receive_task" in locals() and not receive_task.done():
            receive_task.cancel()
        if session:
            session.close()
