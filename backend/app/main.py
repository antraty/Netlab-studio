from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
import time
from typing import Any, AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import netlab
from orchestrator import DockerOrchestrator, Orchestrator, RemoteWorkerOrchestrator

from . import education as education_module
from .education import EducationError, authenticate_websocket, require_teacher, require_user, router as education_router
from .models import (
    CloneRequest,
    CreateLaboratoryRequest,
    LaboratoryMemberRequest,
    TerminalRequest,
    Topology,
    TopologyEnvelope,
    VersionInfo,
    VersionsResponse,
)
from .services import list_services
from .storage import StorageError, TopologyStore
from .terminal import TerminalSession

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOPOLOGY = ROOT / "topology.json"
DEFAULT_DATA = ROOT / ".netlab-data"
logger = logging.getLogger(__name__)


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


def expire_laboratories() -> None:
    for laboratory in education_module.store.expired_laboratories():
        try:
            result = build_orchestrator(laboratory["topology"]).action("down")
        except (RuntimeError, ValueError) as exc:
            education_module.store.set_laboratory_status(laboratory["id"], "failed")
            education_module.store.record_laboratory_event(laboratory["id"], None, f"expired cleanup failed: {exc}")
            logger.error("Could not expire laboratory %s: %s", laboratory["id"], exc)
            continue
        if result.ok:
            education_module.store.set_laboratory_status(laboratory["id"], "expired")
            education_module.store.record_laboratory_event(laboratory["id"], None, "expired: resources cleaned")
        else:
            education_module.store.set_laboratory_status(laboratory["id"], "failed")
            education_module.store.record_laboratory_event(laboratory["id"], None, f"expired cleanup failed (exit {result.exit_code})")
            logger.error("Could not clean up expired laboratory %s (exit %s)", laboratory["id"], result.exit_code)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(expire_laboratories)

    async def expiry_worker() -> None:
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(expire_laboratories)

    task = asyncio.create_task(expiry_worker())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Netlab Studio Control API", version="0.6.0", lifespan=lifespan)
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


@app.get("/api/services", dependencies=[Depends(require_teacher)])
def get_services() -> dict[str, object]:
    return {"services": list_services()}


def _laboratory_for_user(laboratory_id: str, user: dict[str, str], write: bool = False) -> dict[str, Any]:
    expire_laboratories()
    laboratory = education_module.store.laboratory(laboratory_id, user["id"])
    if not laboratory:
        raise HTTPException(status_code=404, detail="laboratory not found")
    if laboratory["expires_at"] <= time.time() or laboratory["status"] == "expired":
        raise HTTPException(status_code=410, detail="laboratory has expired")
    if write and user["role"] == "student":
        raise HTTPException(status_code=403, detail="student execution requires an isolated student laboratory")
    if write and laboratory["role"] == "viewer":
        raise HTTPException(status_code=403, detail="laboratory is read-only")
    return laboratory


def _primary_laboratory_for_user(user: dict[str, str]) -> dict[str, Any]:
    try:
        labs = education_module.store.list_laboratories(user["id"])
        owned = next((lab for lab in labs if lab["role"] == "owner"), None)
        if owned is None:
            created = education_module.store.create_laboratory(user["id"], control.topology.to_topology_dict())
            control.store.save(created["topology"], reason="initial")
            education_module.store.record_laboratory_event(created["id"], user["id"], "laboratory created from initial topology")
            laboratory = education_module.store.laboratory(created["id"], user["id"])
        else:
            laboratory = education_module.store.laboratory(owned["id"], user["id"])
    except EducationError as exc:
        raise HTTPException(status_code=503, detail=f"could not load the primary laboratory: {exc}") from exc
    if laboratory is None:
        raise RuntimeError("primary laboratory disappeared while it was being loaded")
    return laboratory


@app.get("/api/laboratories")
def list_laboratories(user: dict[str, str] = Depends(require_user)) -> dict[str, list[dict[str, Any]]]:
    expire_laboratories()
    if user["role"] == "teacher":
        _primary_laboratory_for_user(user)
    return {"laboratories": education_module.store.list_laboratories(user["id"])}


@app.post("/api/laboratories", status_code=201)
def create_laboratory(
    request: CreateLaboratoryRequest,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        created = education_module.store.create_laboratory(teacher["id"], request.topology)
        control.store.save(created["topology"], reason="create")
        education_module.store.record_laboratory_event(created["id"], teacher["id"], "laboratory created")
    except (EducationError, StorageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"laboratory": {key: value for key, value in created.items() if key != "topology"}, "topology": created["topology"]}


@app.get("/api/laboratories/{laboratory_id}")
def get_laboratory(
    laboratory_id: str,
    user: dict[str, str] = Depends(require_user),
) -> dict[str, Any]:
    laboratory = _laboratory_for_user(laboratory_id, user)
    return {"laboratory": {key: value for key, value in laboratory.items() if key != "topology"}, "topology": laboratory["topology"]}


@app.put("/api/laboratories/{laboratory_id}/topology")
def save_laboratory_topology(
    laboratory_id: str,
    envelope: TopologyEnvelope,
    user: dict[str, str] = Depends(require_user),
) -> dict[str, Any]:
    _laboratory_for_user(laboratory_id, user, write=True)
    topology = envelope.topology.to_topology_dict()
    try:
        control.store.save(topology, reason="save")
        education_module.store.save_laboratory_topology(laboratory_id, user["id"], topology)
        education_module.store.record_laboratory_event(laboratory_id, user["id"], "topology saved")
    except (EducationError, StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": topology}


@app.get("/api/laboratories/{laboratory_id}/status")
def get_laboratory_status(
    laboratory_id: str,
    user: dict[str, str] = Depends(require_user),
) -> dict[str, Any]:
    laboratory = _laboratory_for_user(laboratory_id, user)
    try:
        return {"nodes": build_orchestrator(laboratory["topology"]).status()}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/laboratories/{laboratory_id}/logs")
def get_laboratory_logs(
    laboratory_id: str,
    user: dict[str, str] = Depends(require_user),
) -> dict[str, list[dict[str, Any]]]:
    _laboratory_for_user(laboratory_id, user)
    return {"logs": education_module.store.laboratory_events(laboratory_id)}


@app.post("/api/laboratories/{laboratory_id}/versions/{version}/restore")
def restore_laboratory_version(
    laboratory_id: str,
    version: int,
    user: dict[str, str] = Depends(require_user),
) -> dict[str, Any]:
    laboratory = _laboratory_for_user(laboratory_id, user, write=True)
    try:
        topology = control.store.restore(laboratory["name"], version)
        education_module.store.save_laboratory_topology(laboratory_id, user["id"], topology)
        education_module.store.record_laboratory_event(laboratory_id, user["id"], f"topology restored from version {version}")
    except (StorageError, EducationError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": topology}


@app.post("/api/laboratories/{laboratory_id}/members", status_code=201)
def add_laboratory_member(
    laboratory_id: str,
    request: LaboratoryMemberRequest,
    user: dict[str, str] = Depends(require_user),
) -> dict[str, bool]:
    laboratory = _laboratory_for_user(laboratory_id, user)
    if laboratory["role"] != "owner":
        raise HTTPException(status_code=403, detail="laboratory owner role required")
    try:
        education_module.store.add_laboratory_member(laboratory_id, user["id"], request.email, request.role)
        education_module.store.record_laboratory_event(laboratory_id, user["id"], f"member added with role {request.role}")
    except EducationError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/laboratories/{laboratory_id}/actions/{action}")
def run_laboratory_action(
    laboratory_id: str,
    action: str,
    user: dict[str, str] = Depends(require_user),
) -> dict[str, Any]:
    if action not in {"up", "down", "verify"}:
        raise HTTPException(status_code=404, detail="unknown action")
    laboratory = _laboratory_for_user(laboratory_id, user, write=True)
    try:
        if action == "up":
            topology = education_module.store.claim_laboratory_run(laboratory_id, user["id"])
        else:
            topology = laboratory["topology"]
    except EducationError as exc:
        raise HTTPException(status_code=403 if "read-only" in str(exc) else 409, detail=str(exc)) from exc
    try:
        result = build_orchestrator(topology).action(action)
    except (RuntimeError, ValueError) as exc:
        if action != "verify":
            education_module.store.set_laboratory_status(laboratory_id, "failed")
        education_module.store.record_laboratory_event(laboratory_id, user["id"], f"{action} failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if action == "up":
        education_module.store.set_laboratory_status(laboratory_id, "running" if result.ok else "failed")
    elif action == "down":
        education_module.store.set_laboratory_status(laboratory_id, "stopped" if result.ok else "failed")
    education_module.store.record_laboratory_event(
        laboratory_id,
        user["id"],
        f"{action}: {'succeeded' if result.ok else f'failed (exit {result.exit_code})'}",
    )
    return {"ok": result.ok, "action": action, "exit_code": result.exit_code, "output": result.output}


@app.get("/api/topology", response_model=TopologyEnvelope, dependencies=[Depends(require_teacher)])
def get_topology(user: dict[str, str] = Depends(require_teacher)) -> dict[str, Topology]:
    return {"topology": Topology.model_validate(_primary_laboratory_for_user(user)["topology"])}


@app.post("/api/topology", response_model=TopologyEnvelope, dependencies=[Depends(require_teacher)])
def save_topology(envelope: TopologyEnvelope, user: dict[str, str] = Depends(require_teacher)) -> dict[str, Topology]:
    laboratory = _primary_laboratory_for_user(user)
    topology_dict = envelope.topology.to_topology_dict()
    topology_dict["laboratory_id"] = laboratory["id"]
    topology_dict["lab"] = laboratory["name"]
    try:
        topology = Topology.model_validate(topology_dict)
        netlab.validate_topology(topology_dict)
        control.store.save(topology_dict)
        education_module.store.save_laboratory_topology(laboratory["id"], user["id"], topology_dict)
        education_module.store.record_laboratory_event(laboratory["id"], user["id"], "topology saved")
    except (EducationError, StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": topology}


@app.get("/api/laboratories/{lab}/versions", response_model=VersionsResponse)
def list_versions(lab: str, user: dict[str, str] = Depends(require_user)) -> VersionsResponse:
    record = education_module.store.laboratory(lab, user["id"]) or education_module.store.laboratory_by_name(lab, user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="laboratory not found")
    _laboratory_for_user(record["id"], user)
    try:
        return VersionsResponse(lab=record["name"], versions=control.store.list_versions(record["name"]))
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/laboratories/{lab}/restore/{version}", response_model=TopologyEnvelope)
def restore_version(lab: str, version: int, user: dict[str, str] = Depends(require_user)) -> dict[str, Topology]:
    record = education_module.store.laboratory(lab, user["id"]) or education_module.store.laboratory_by_name(lab, user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="laboratory not found")
    _laboratory_for_user(record["id"], user, write=True)
    try:
        topology_dict = control.store.restore(record["name"], version)
        education_module.store.save_laboratory_topology(record["id"], user["id"], topology_dict)
        education_module.store.record_laboratory_event(record["id"], user["id"], f"topology restored from version {version}")
        topology = Topology.model_validate(topology_dict)
    except (EducationError, StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": topology}


@app.post("/api/laboratories/{lab}/clone", response_model=TopologyEnvelope)
def clone_laboratory(lab: str, request: CloneRequest, user: dict[str, str] = Depends(require_teacher)) -> dict[str, Topology]:
    record = education_module.store.laboratory(lab, user["id"]) or education_module.store.laboratory_by_name(lab, user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="laboratory is not active")
    if record["role"] == "viewer":
        raise HTTPException(status_code=403, detail="laboratory is read-only")
    try:
        source = dict(record["topology"])
        source["lab"] = request.new_lab
        source.pop("laboratory_id", None)
        created = education_module.store.create_laboratory(user["id"], source)
        control.store.save(created["topology"], reason=f"clone:{record['name']}")
        education_module.store.record_laboratory_event(created["id"], user["id"], f"cloned from {record['name']}")
        topology = Topology.model_validate(created["topology"])
    except (EducationError, StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": topology}


@app.get("/api/laboratories/{lab}/export")
def export_laboratory(lab: str, user: dict[str, str] = Depends(require_user)) -> dict[str, object]:
    record = education_module.store.laboratory(lab, user["id"]) or education_module.store.laboratory_by_name(lab, user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="laboratory not found")
    _laboratory_for_user(record["id"], user)
    try:
        return control.store.export(record["name"])
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/laboratories/import", response_model=TopologyEnvelope)
def import_laboratory(envelope: TopologyEnvelope, user: dict[str, str] = Depends(require_teacher)) -> dict[str, Topology]:
    try:
        imported = envelope.topology.to_topology_dict()
        imported.pop("laboratory_id", None)
        created = education_module.store.create_laboratory(user["id"], imported)
        control.store.save(created["topology"], reason="import")
        education_module.store.record_laboratory_event(created["id"], user["id"], "laboratory imported")
        topology = Topology.model_validate(created["topology"])
    except (EducationError, StorageError, ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": topology}


@app.get("/api/status", dependencies=[Depends(require_teacher)])
def get_status(user: dict[str, str] = Depends(require_teacher)) -> dict[str, list[dict[str, str]]]:
    topology = _primary_laboratory_for_user(user)["topology"]
    try:
        return {"nodes": build_orchestrator(topology).status()}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/observability", dependencies=[Depends(require_teacher)])
def get_observability(user: dict[str, str] = Depends(require_teacher)) -> dict[str, object]:
    _primary_laboratory_for_user(user)
    snapshot = control.orchestrator.observability()
    allowed_labs = education_module.store.list_laboratories(user["id"])
    allowed_ids = {laboratory["id"] for laboratory in allowed_labs}
    allowed_names = {laboratory["name"] for laboratory in allowed_labs}
    snapshot["labs"] = [
        laboratory for laboratory in snapshot.get("labs", [])
        if laboratory.get("laboratory_id") in allowed_ids
        or laboratory.get("name") in allowed_names
    ]
    snapshot["nodes"] = [
        node for node in snapshot.get("nodes", [])
        if node.get("laboratory_id") in allowed_ids or node.get("lab") in allowed_names
    ]
    snapshot["networks"] = [
        network for network in snapshot.get("networks", [])
        if network.get("laboratory_id") in allowed_ids or network.get("lab") in allowed_names
    ]
    snapshot["active_lab_count"] = sum(1 for laboratory in snapshot["labs"] if laboratory.get("running_count", 0) > 0)
    snapshot["running_node_count"] = sum(1 for node in snapshot["nodes"] if node.get("state") == "running")
    snapshot["storage"] = []
    snapshot["events"] = [
        f"{event['message']}"
        for laboratory in allowed_labs
        for event in education_module.store.laboratory_events(laboratory["id"])
    ][-100:]
    snapshot["errors"] = []
    snapshot["alerts"] = snapshot.get("alerts", [])
    snapshot["alerts"] = [alert for alert in snapshot["alerts"] if alert.get("lab") in allowed_names]
    return snapshot


@app.get("/api/logs", dependencies=[Depends(require_teacher)])
def get_logs(user: dict[str, str] = Depends(require_teacher)) -> dict[str, list[str]]:
    laboratory = _primary_laboratory_for_user(user)
    return {"logs": [event["message"] for event in education_module.store.laboratory_events(laboratory["id"])]}


@app.post("/api/{action}", dependencies=[Depends(require_teacher)])
def run_action(action: str, user: dict[str, str] = Depends(require_teacher)) -> dict[str, object]:
    if action not in {"up", "down", "verify"}:
        raise HTTPException(status_code=404, detail="unknown action")
    laboratory = _primary_laboratory_for_user(user)
    return run_laboratory_action(laboratory["id"], action, user)


@app.post("/api/nodes/{node_name}/terminal", dependencies=[Depends(require_teacher)])
def run_terminal(node_name: str, request: TerminalRequest, user: dict[str, str] = Depends(require_teacher)) -> dict[str, object]:
    laboratory = _primary_laboratory_for_user(user)
    selected_orchestrator = build_orchestrator(laboratory["topology"])
    try:
        result = selected_orchestrator.terminal(node_name, request.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    education_module.store.record_laboratory_event(
        laboratory["id"],
        user["id"],
        f"terminal {node_name}: {' '.join(request.command)} -> {result.exit_code}",
    )
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
    laboratory_id = websocket.query_params.get("laboratory_id")
    if laboratory_id:
        try:
            laboratory = _laboratory_for_user(laboratory_id, user, write=True)
        except HTTPException as exc:
            await websocket.close(code=1008, reason=exc.detail)
            return
        selected_orchestrator = build_orchestrator(laboratory["topology"])
    else:
        if user["role"] != "teacher":
            await websocket.close(code=1008, reason="teacher role required")
            return
        laboratory = _primary_laboratory_for_user(user)
        laboratory_id = laboratory["id"]
        selected_orchestrator = build_orchestrator(laboratory["topology"])
    await websocket.accept()
    session: TerminalSession | None = None
    try:
        if not isinstance(selected_orchestrator, DockerOrchestrator):
            await websocket.send_text("remote worker terminal streaming is not implemented yet; use the local worker mode\n")
            return
        session = TerminalSession(selected_orchestrator.container_name(node_name))
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
                await asyncio.to_thread(
                    education_module.store.record_laboratory_event,
                    laboratory_id,
                    user["id"],
                    f"terminal websocket {node_name}: command received",
                )
                receive_task = asyncio.create_task(websocket.receive_text())
            await asyncio.sleep(0.05)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        await websocket.send_text(f"terminal error: {exc}\n")
    finally:
        if "receive_task" in locals() and not receive_task.done():
            receive_task.cancel()
        if session:
            session.close()
