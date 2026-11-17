from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import netlab
from orchestrator import DockerOrchestrator, Orchestrator

from .models import TerminalRequest, Topology, TopologyEnvelope

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOPOLOGY = ROOT / "topology.json"


class ControlPlane:
    def __init__(self, topology_path: Path = DEFAULT_TOPOLOGY, orchestrator_factory: Callable = DockerOrchestrator):
        self.topology_path = topology_path
        self.orchestrator_factory = orchestrator_factory
        self.topology = Topology.model_validate(netlab.load_topology(topology_path))
        self.orchestrator: Orchestrator = orchestrator_factory(self.topology.to_topology_dict())
        self.events: list[str] = []

    def save(self, topology: Topology) -> None:
        topology_dict = topology.to_topology_dict()
        netlab.validate_topology(topology_dict)
        self.topology_path.write_text(json.dumps(topology_dict, indent=2) + "\n", encoding="utf-8")
        self.topology = topology
        self.orchestrator = self.orchestrator_factory(topology_dict)
        self.record("topology saved")

    def record(self, message: str) -> None:
        self.events.append(message)
        self.events = self.events[-100:]


control = ControlPlane(Path(os.getenv("NETLAB_TOPOLOGY", DEFAULT_TOPOLOGY)))
app = FastAPI(title="Netlab Studio Control API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "netlab-control-api"}


@app.get("/api/topology", response_model=TopologyEnvelope)
def get_topology() -> dict[str, Topology]:
    return {"topology": control.topology}


@app.post("/api/topology", response_model=TopologyEnvelope)
def save_topology(envelope: TopologyEnvelope) -> dict[str, Topology]:
    try:
        control.save(envelope.topology)
    except (ValueError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topology": control.topology}


@app.get("/api/status")
def get_status() -> dict[str, list[dict[str, str]]]:
    return {"nodes": control.orchestrator.status()}


@app.get("/api/logs")
def get_logs() -> dict[str, list[str]]:
    return {"logs": control.events}


@app.post("/api/{action}")
def run_action(action: str) -> dict[str, object]:
    if action not in {"up", "down", "verify"}:
        raise HTTPException(status_code=404, detail="unknown action")
    result = control.orchestrator.action(action)
    control.record(f"{action}: exit code {result.exit_code}")
    return {"ok": result.ok, "action": action, "exit_code": result.exit_code, "logs": control.events}


@app.post("/api/nodes/{node_name}/terminal")
def run_terminal(node_name: str, request: TerminalRequest) -> dict[str, object]:
    try:
        result = control.orchestrator.terminal(node_name, request.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    control.record(f"terminal {node_name}: {' '.join(request.command)} -> {result.exit_code}")
    return {"ok": result.ok, "exit_code": result.exit_code, "output": result.output}
