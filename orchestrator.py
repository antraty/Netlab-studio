"""Execution-plane adapters for Netlab Studio.

The control plane talks to this small interface instead of calling Docker
commands directly. Docker is the first adapter; a VM or remote worker can be
added without changing the HTTP API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import netlab
from backend.app.observability import collect_docker_observability


@dataclass
class ActionResult:
    ok: bool
    action: str
    exit_code: int
    output: str = ""


class Orchestrator(Protocol):
    def action(self, name: str) -> ActionResult: ...
    def status(self) -> list[dict[str, str]]: ...
    def observability(self) -> dict[str, Any]: ...
    def terminal(self, node_name: str, command: list[str]) -> ActionResult: ...


class DockerOrchestrator:
    """Execute one validated topology through the local Docker CLI."""

    ALLOWED_TERMINAL_COMMANDS = {"hostname", "uname", "ip", "ping"}

    def __init__(self, topology: dict[str, Any]) -> None:
        netlab.validate_topology(topology)
        self.topology = topology

    def action(self, name: str) -> ActionResult:
        actions = {"up": netlab.deploy, "down": netlab.destroy, "verify": netlab.verify}
        if name not in actions:
            raise ValueError(f"unsupported action: {name}")
        exit_code = actions[name](self.topology)
        return ActionResult(exit_code == 0, name, exit_code)

    def status(self) -> list[dict[str, str]]:
        result = netlab.docker("ps", "-a", "--format", "{{.Names}}\\t{{.Status}}", capture=True)
        if result.returncode:
            state = "docker-unavailable" if result.returncode == 127 else "docker-error"
            return [{"name": node["name"], "state": state} for node in self.topology["nodes"]]
        rows = dict(line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line)
        return [
            {
                "name": node["name"],
                "state": rows.get(netlab.resource_name(self.topology, node["name"]), "stopped"),
            }
            for node in self.topology["nodes"]
        ]

    def terminal(self, node_name: str, command: list[str]) -> ActionResult:
        if not command or command[0] not in self.ALLOWED_TERMINAL_COMMANDS:
            allowed = ", ".join(sorted(self.ALLOWED_TERMINAL_COMMANDS))
            raise ValueError(f"allowed terminal commands: {allowed}")
        names = {node["name"] for node in self.topology["nodes"]}
        if node_name not in names:
            raise ValueError(f"unknown node: {node_name}")
        result = netlab.docker("exec", netlab.resource_name(self.topology, node_name), *command, capture=True)
        return ActionResult(
            result.returncode == 0,
            f"terminal:{node_name}",
            result.returncode,
            (result.stdout + result.stderr).strip(),
        )

    def container_name(self, node_name: str) -> str:
        names = {node["name"] for node in self.topology["nodes"]}
        if node_name not in names:
            raise ValueError(f"unknown node: {node_name}")
        return netlab.resource_name(self.topology, node_name)

    def observability(self) -> dict[str, Any]:
        return collect_docker_observability()


class RemoteWorkerOrchestrator:
    """Control-plane adapter that never accesses the Docker socket directly."""

    def __init__(self, topology: dict[str, Any], base_url: str, token: str, timeout: float = 30) -> None:
        netlab.validate_topology(topology)
        self.topology = topology
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, action: str, node_name: str | None = None, command: list[str] | None = None) -> dict[str, Any]:
        payload = {
            "job_id": str(uuid.uuid4()),
            "action": action,
            "topology": self.topology,
            "node_name": node_name,
            "command": command or [],
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/jobs",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"worker returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"worker unavailable: {exc.reason}") from exc

    def action(self, name: str) -> ActionResult:
        result = self._request(name)
        return ActionResult(bool(result["ok"]), name, int(result.get("exit_code", 0)), result.get("output", ""))

    def status(self) -> list[dict[str, str]]:
        return self._request("status").get("nodes", [])

    def observability(self) -> dict[str, Any]:
        return self._request("observability").get("observability") or {
            "available": False,
            "collected_at": None,
            "active_lab_count": 0,
            "running_node_count": 0,
            "labs": [],
            "nodes": [],
            "networks": [],
            "storage": [],
            "alerts": [],
            "errors": ["la supervision du worker distant n’est pas disponible"],
            "events": [],
            "truncated": False,
            "thresholds": {"cpu_percent": 80, "memory_percent": 80, "writable_storage_mb": 1024},
        }

    def terminal(self, node_name: str, command: list[str]) -> ActionResult:
        result = self._request("terminal", node_name, command)
        return ActionResult(bool(result["ok"]), "terminal", int(result.get("exit_code", 0)), result.get("output", ""))
