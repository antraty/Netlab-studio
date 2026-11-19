from __future__ import annotations

import os
from typing import Any, Protocol


class ExecutionBackend(Protocol):
    def action(self, name: str) -> Any: ...
    def status(self) -> list[dict[str, str]]: ...
    def observability(self) -> dict[str, Any]: ...
    def terminal(self, node_name: str, command: list[str]) -> Any: ...


class DockerExecutionBackend:
    def __init__(self, topology: dict[str, Any], local_orchestrator: Any) -> None:
        self.local_orchestrator = local_orchestrator

    def action(self, name: str) -> Any:
        return self.local_orchestrator.action(name)

    def status(self) -> list[dict[str, str]]:
        return self.local_orchestrator.status()

    def observability(self) -> dict[str, Any]:
        return self.local_orchestrator.observability()

    def terminal(self, node_name: str, command: list[str]) -> Any:
        return self.local_orchestrator.terminal(node_name, command)


class LibvirtExecutionBackend:
    def __init__(self, topology: dict[str, Any]) -> None:
        self.topology = topology

    def action(self, name: str) -> Any:
        raise RuntimeError(
            "KVM/libvirt execution is reserved for Tranche 5; "
            "set NETLAB_EXECUTION_BACKEND=docker",
        )

    def status(self) -> list[dict[str, str]]:
        raise RuntimeError("KVM/libvirt execution is not implemented yet")

    def observability(self) -> dict[str, Any]:
        raise RuntimeError("KVM/libvirt observability is not implemented yet")

    def terminal(self, node_name: str, command: list[str]) -> Any:
        raise RuntimeError("KVM/libvirt consoles are not implemented yet")


def selected_execution_backend() -> str:
    backend = os.getenv("NETLAB_EXECUTION_BACKEND", "docker").strip().lower()
    if backend not in {"docker", "libvirt"}:
        raise RuntimeError("NETLAB_EXECUTION_BACKEND must be docker or libvirt")
    return backend
