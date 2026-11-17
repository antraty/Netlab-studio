#!/usr/bin/env python3
"""Prototype CLI for Netlab Studio's first technical milestone.

The CLI intentionally delegates container lifecycle operations to the Docker CLI,
keeping the prototype dependency-free while the control-plane API is designed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class TopologyError(ValueError):
    """Raised when a topology is invalid or cannot be operated safely."""


def load_topology(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TopologyError(f"Topology file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TopologyError(f"Invalid JSON in {path}: {exc}") from exc
    validate_topology(data)
    return data


def validate_topology(topology: dict[str, Any]) -> None:
    required = {"version", "lab", "network", "nodes", "connectivity_check"}
    missing = required - topology.keys()
    if missing:
        raise TopologyError(f"Missing top-level fields: {', '.join(sorted(missing))}")
    if topology["version"] != 1:
        raise TopologyError("Only topology format version 1 is supported")
    if not isinstance(topology["lab"], str) or not topology["lab"].strip():
        raise TopologyError("lab must be a non-empty string")

    network = topology["network"]
    if not isinstance(network, dict):
        raise TopologyError("network must be an object")
    for field in ("name", "driver"):
        if not isinstance(network.get(field), str) or not network[field].strip():
            raise TopologyError(f"network.{field} must be a non-empty string")
    if network["driver"] != "bridge":
        raise TopologyError("Prototype only supports the bridge network driver")

    nodes = topology["nodes"]
    if not isinstance(nodes, list) or len(nodes) < 2:
        raise TopologyError("nodes must contain at least two nodes")
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise TopologyError("each node must be an object")
        for field in ("name", "image"):
            if not isinstance(node.get(field), str) or not node[field].strip():
                raise TopologyError(f"node.{field} must be a non-empty string")
        if node["name"] in names:
            raise TopologyError(f"duplicate node name: {node['name']}")
        names.add(node["name"])
        command = node.get("command", ["sleep", "infinity"])
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            raise TopologyError(f"node {node['name']} command must be a non-empty string list")

    check = topology["connectivity_check"]
    if not isinstance(check, dict):
        raise TopologyError("connectivity_check must be an object")
    source, target = check.get("from"), check.get("to")
    if source not in names or target not in names or source == target:
        raise TopologyError("connectivity_check must reference two different nodes")
    command = check.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise TopologyError("connectivity_check.command must be a non-empty string list")


def docker(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=False,
        text=True,
        capture_output=capture,
    )


def resource_name(topology: dict[str, Any], node_name: str | None = None) -> str:
    base = topology["lab"].lower().replace("_", "-").replace(" ", "-")
    return f"netlab-{base}" if node_name is None else f"netlab-{base}-{node_name}"


def deploy(topology: dict[str, Any]) -> int:
    network = topology["network"]
    network_name = resource_name(topology) + "-network"
    existing = docker("network", "inspect", network_name, capture=True)
    if existing.returncode != 0:
        args = ["network", "create", "--driver", network["driver"]]
        if network.get("subnet"):
            args += ["--subnet", network["subnet"]]
        args.append(network_name)
        result = docker(*args, capture=True)
        if result.returncode:
            print(result.stderr.strip(), file=sys.stderr)
            return result.returncode
        print(f"created network {network_name}")
    else:
        print(f"reusing network {network_name}")

    for node in topology["nodes"]:
        container = resource_name(topology, node["name"])
        docker("rm", "-f", container, capture=True)
        result = docker(
            "run", "-d", "--name", container, "--network", network_name,
            "--label", "io.netlab.studio.lab=" + topology["lab"],
            node["image"], *node.get("command", ["sleep", "infinity"]), capture=True,
        )
        if result.returncode:
            print(f"failed to start {node['name']}: {result.stderr.strip()}", file=sys.stderr)
            return result.returncode
        print(f"started {node['name']} ({container})")
    return 0


def verify(topology: dict[str, Any]) -> int:
    check = topology["connectivity_check"]
    container = resource_name(topology, check["from"])
    result = docker("exec", container, *check["command"], capture=True)
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output)
    if result.returncode == 0:
        print(f"connectivity check passed: {check['from']} -> {check['to']}")
    else:
        print(f"connectivity check failed: {check['from']} -> {check['to']}", file=sys.stderr)
    return result.returncode


def destroy(topology: dict[str, Any]) -> int:
    for node in topology["nodes"]:
        container = resource_name(topology, node["name"])
        result = docker("rm", "-f", container, capture=True)
        if result.returncode == 0:
            print(f"removed {container}")
    network_name = resource_name(topology) + "-network"
    result = docker("network", "rm", network_name, capture=True)
    if result.returncode == 0:
        print(f"removed network {network_name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Netlab Studio prototype orchestrator")
    parser.add_argument("topology", type=Path, help="path to a version 1 topology JSON file")
    parser.add_argument("action", choices=("validate", "up", "verify", "down"))
    args = parser.parse_args()
    try:
        topology = load_topology(args.topology)
        if args.action == "validate":
            print(f"valid topology: {topology['lab']} ({len(topology['nodes'])} nodes)")
            return 0
        if args.action == "up":
            return deploy(topology)
        if args.action == "verify":
            return verify(topology)
        return destroy(topology)
    except TopologyError as exc:
        print(f"topology error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print("Docker CLI is required for this action", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
