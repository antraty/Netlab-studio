"""Execution-plane adapters for Netlab Studio."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import ssl
import subprocess
import time
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
        result = netlab.docker("ps", "-a", "--format", "{{.Names}}\t{{.Status}}", capture=True)
        if result.returncode:
            state = "docker-unavailable" if result.returncode == 127 else "docker-error"
            return [{"name": node["name"], "state": state} for node in self.topology["nodes"]]
        rows = dict(line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line)
        return [{
            "name": node["name"],
            "state": rows.get(netlab.resource_name(self.topology, node["name"]), "stopped"),
        } for node in self.topology["nodes"]]

    def terminal(self, node_name: str, command: list[str]) -> ActionResult:
        self._validate_terminal_command(command)
        names = {node["name"] for node in self.topology["nodes"]}
        if node_name not in names:
            raise ValueError(f"unknown node: {node_name}")
        safe_command = list(command)
        if command[0] == "ping":
            if "-4" not in safe_command[1:]:
                safe_command.insert(1, "-4")
            if "-c" not in safe_command[1:]:
                safe_command.extend(["-c", "1"])
            if "-W" not in safe_command[1:]:
                safe_command.extend(["-W", "2"])
        try:
            result = netlab.docker(
                "exec", netlab.resource_name(self.topology, node_name), *safe_command,
                capture=True, timeout=15,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or b""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            return ActionResult(False, f"terminal:{node_name}", 124, (output + "\ncommand timed out").strip()[-65536:])
        return ActionResult(
            result.returncode == 0,
            f"terminal:{node_name}",
            result.returncode,
            (result.stdout + result.stderr).strip()[-65536:],
        )

    @classmethod
    def _validate_terminal_command(cls, command: list[str]) -> None:
        if (
            not command
            or len(command) > 8
            or any(not isinstance(item, str) or len(item) > 256 for item in command)
            or sum(len(item) for item in command) > 4096
        ):
            raise ValueError("terminal command must contain at most 8 bounded arguments")
        if command[0] == "hostname" and len(command) == 1:
            return
        if command[0] == "uname" and command[1:] in ([], ["-a"], ["-s"], ["-r"], ["-m"]):
            return
        if command[0] == "ip" and len(command) <= 4 and all(
            item in {"-4", "-brief", "addr", "address", "route", "link", "show"}
            for item in command[1:]
        ):
            return
        if command[0] == "ping":
            cls._validate_ping(command[1:])
            return
        allowed = ", ".join(sorted(cls.ALLOWED_TERMINAL_COMMANDS))
        raise ValueError(f"allowed terminal commands and safe arguments: {allowed}")

    @staticmethod
    def _validate_ping(arguments: list[str]) -> None:
        destination: str | None = None
        index = 0
        while index < len(arguments):
            item = arguments[index]
            if item in {"-4", "-n"}:
                index += 1
                continue
            if item in {"-c", "-W"} and index + 1 < len(arguments):
                try:
                    value = int(arguments[index + 1])
                except ValueError as exc:
                    raise ValueError("ping count and timeout must be integers") from exc
                if item == "-c" and not 1 <= value <= 3:
                    raise ValueError("ping count must be between 1 and 3")
                if item == "-W" and not 1 <= value <= 3:
                    raise ValueError("ping timeout must be between 1 and 3 seconds")
                index += 2
                continue
            if destination is not None or item.startswith("-"):
                raise ValueError("ping accepts only a bounded count, timeout, and one destination")
            destination = item
            index += 1
        if destination is None:
            raise ValueError("ping requires a destination")
        try:
            address = ipaddress.ip_address(destination)
        except ValueError:
            if len(destination) > 253 or not re.fullmatch(
                r"(?i)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*",
                destination,
            ):
                raise ValueError("ping destination must be an IP address or hostname")
        else:
            if address.version != 4:
                raise ValueError("ping destination must be IPv4")

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
        started = time.monotonic()
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
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "X-Netlab-Worker-ID": os.getenv("NETLAB_WORKER_ID", "control-plane"),
            },
            method="POST",
        )
        ca_file = os.getenv("NETLAB_MTLS_CA_FILE", "")
        cert_file = os.getenv("NETLAB_MTLS_CERT_FILE", "")
        key_file = os.getenv("NETLAB_MTLS_KEY_FILE", "")
        if self.base_url.startswith("https://") and any((ca_file, cert_file, key_file)):
            if not all((ca_file, cert_file, key_file)):
                raise RuntimeError("mTLS requires NETLAB_MTLS_CA_FILE, NETLAB_MTLS_CERT_FILE and NETLAB_MTLS_KEY_FILE")
            ssl_context = ssl.create_default_context(cafile=ca_file)
            ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
        else:
            opener = urllib.request.build_opener()

        max_attempts = max(1, min(10, int(os.getenv("NETLAB_WORKER_MAX_ATTEMPTS", "3"))))
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode())
                    result.setdefault("duration_ms", int((time.monotonic() - started) * 1000))
                    return result
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")
                raise RuntimeError(f"worker returned HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < max_attempts:
                    time.sleep(min(5, 2 ** (attempt - 1)))
        raise RuntimeError(f"worker unavailable after {max_attempts} attempts: {getattr(last_error, 'reason', last_error)}")

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
