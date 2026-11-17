"""Execution-plane adapters for Netlab Studio.

The control plane talks to this small interface instead of calling Docker
commands directly. Docker is the first adapter; a VM or remote worker can be
added without changing the HTTP API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import netlab


@dataclass
class ActionResult:
    ok: bool
    action: str
    exit_code: int
    output: str = ""


class Orchestrator(Protocol):
    def action(self, name: str) -> ActionResult: ...
    def status(self) -> list[dict[str, str]]: ...
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
