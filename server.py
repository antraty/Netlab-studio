#!/usr/bin/env python3
"""Small local control-plane server for the Netlab Studio prototype."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import netlab
from orchestrator import DockerOrchestrator, Orchestrator


ROOT = Path(__file__).parent
WEB_ROOT = ROOT / "web"


class ControlPlane:
    def __init__(self, topology_path: Path, orchestrator_factory=DockerOrchestrator) -> None:
        self.topology_path = topology_path
        self.orchestrator_factory = orchestrator_factory
        self.topology = netlab.load_topology(topology_path)
        self.orchestrator: Orchestrator = orchestrator_factory(self.topology)
        self.events: list[str] = []

    def record(self, message: str) -> None:
        self.events.append(message)
        self.events = self.events[-100:]

    def save(self, topology: dict[str, Any]) -> None:
        netlab.validate_topology(topology)
        self.topology_path.write_text(json.dumps(topology, indent=2) + "\n", encoding="utf-8")
        self.topology = topology
        self.orchestrator = self.orchestrator_factory(topology)
        self.record("topology saved")

    def action(self, name: str) -> dict[str, Any]:
        result = self.orchestrator.action(name)
        self.record(f"{name}: exit code {result.exit_code}")
        return {"ok": result.ok, "action": name, "exit_code": result.exit_code, "logs": self.events}

    def status(self) -> list[dict[str, Any]]:
        return self.orchestrator.status()

    def terminal(self, node_name: str, command: list[str]) -> dict[str, Any]:
        result = self.orchestrator.terminal(node_name, command)
        self.record(f"terminal {node_name}: {' '.join(command)} -> {result.exit_code}")
        return {"ok": result.ok, "exit_code": result.exit_code, "output": result.output}


class Handler(BaseHTTPRequestHandler):
    server_version = "NetlabStudio/0.2"

    @property
    def control(self) -> ControlPlane:
        return self.server.control  # type: ignore[attr-defined]

    def json_response(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/topology":
            self.json_response({"topology": self.control.topology})
        elif parsed.path == "/api/status":
            self.json_response({"nodes": self.control.status()})
        elif parsed.path == "/api/logs":
            self.json_response({"logs": self.control.events})
        elif parsed.path == "/" or parsed.path == "/index.html":
            self.serve_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
        elif parsed.path.startswith("/web/"):
            name = Path(unquote(parsed.path.removeprefix("/web/"))).name
            types = {"app.js": "text/javascript; charset=utf-8", "styles.css": "text/css; charset=utf-8"}
            self.serve_file(WEB_ROOT / name, types.get(name, "application/octet-stream"))
        else:
            self.json_response({"error": "not found"}, 404)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            parsed = urlparse(self.path)
            if parsed.path == "/api/topology":
                self.control.save(payload["topology"])
                response = {"ok": True, "topology": self.control.topology}
            elif parsed.path in {"/api/up", "/api/down", "/api/verify"}:
                response = self.control.action(parsed.path.rsplit("/", 1)[1])
            elif parsed.path.startswith("/api/nodes/") and parsed.path.endswith("/terminal"):
                name = unquote(parsed.path.split("/")[3])
                response = self.control.terminal(name, payload.get("command", []))
            else:
                self.json_response({"error": "not found"}, 404)
                return
            self.json_response(response)
        except (ValueError, KeyError, json.JSONDecodeError, netlab.TopologyError) as exc:
            self.json_response({"error": str(exc)}, 400)

    def serve_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self.json_response({"error": "file not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[web] {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Netlab Studio local control plane")
    parser.add_argument("--topology", type=Path, default=ROOT / "topology.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    control = ControlPlane(args.topology)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.control = control  # type: ignore[attr-defined]
    print(f"Netlab Studio: http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nserver stopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
