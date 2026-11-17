#!/usr/bin/env python3
"""Small local control-plane server for the Netlab Studio prototype."""

from __future__ import annotations

import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import netlab


ROOT = Path(__file__).parent
WEB_ROOT = ROOT / "web"


class ControlPlane:
    def __init__(self, topology_path: Path) -> None:
        self.topology_path = topology_path
        self.topology = netlab.load_topology(topology_path)
        self.events: list[str] = []

    def record(self, message: str) -> None:
        self.events.append(message)
        self.events = self.events[-100:]

    def save(self, topology: dict[str, Any]) -> None:
        netlab.validate_topology(topology)
        self.topology_path.write_text(json.dumps(topology, indent=2) + "\n", encoding="utf-8")
        self.topology = topology
        self.record("topology saved")

    def action(self, name: str) -> dict[str, Any]:
        actions = {"up": netlab.deploy, "down": netlab.destroy, "verify": netlab.verify}
        if name not in actions:
            raise ValueError(f"unsupported action: {name}")
        result = actions[name](self.topology)
        self.record(f"{name}: exit code {result}")
        return {"ok": result == 0, "action": name, "exit_code": result, "logs": self.events}

    def status(self) -> list[dict[str, Any]]:
        result = netlab.docker("ps", "-a", "--format", "{{.Names}}\\t{{.Status}}", capture=True)
        if result.returncode:
            return [{"name": node["name"], "state": "docker-unavailable"} for node in self.topology["nodes"]]
        rows = dict(line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line)
        return [{"name": node["name"], "state": rows.get(netlab.resource_name(self.topology, node["name"]), "stopped")} for node in self.topology["nodes"]]

    def terminal(self, node_name: str, command: list[str]) -> dict[str, Any]:
        allowed = {"hostname", "uname", "ip", "ping"}
        if not command or command[0] not in allowed:
            raise ValueError("allowed terminal commands: hostname, uname, ip, ping")
        names = {node["name"] for node in self.topology["nodes"]}
        if node_name not in names:
            raise ValueError(f"unknown node: {node_name}")
        result = netlab.docker("exec", netlab.resource_name(self.topology, node_name), *command, capture=True)
        output = (result.stdout + result.stderr).strip()
        self.record(f"terminal {node_name}: {' '.join(command)} -> {result.returncode}")
        return {"ok": result.returncode == 0, "exit_code": result.returncode, "output": output}


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
