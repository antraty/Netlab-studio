#!/usr/bin/env python3
"""Netlab Studio topology validator and Docker execution engine.

Version 1 topologies remain supported for compatibility. Version 2 adds real
network segments, node interfaces, IPv4 addresses and static routes.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from backend.app.services import get_service, validate_catalog_node


class TopologyError(ValueError):
    """Raised when a topology is invalid or cannot be operated safely."""


SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
ALLOWED_CONNECTIVITY_COMMANDS = {"getent", "ip", "ping"}
DEFAULT_COMMAND = ["sleep", "infinity"]


def validate_identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or not SAFE_IDENTIFIER.fullmatch(value):
        raise TopologyError(
            f"{field} must contain 1 to 64 characters: letters, numbers, '.', '_' or '-'")


def _network(value: str, field: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise TopologyError(f"{field} must be an IPv4 network in CIDR notation") from exc
    if network.version != 4:
        raise TopologyError(f"{field} must be an IPv4 network")
    return network


def _address(value: str, field: str) -> ipaddress.IPv4Interface:
    try:
        address = ipaddress.ip_interface(value)
    except ValueError as exc:
        raise TopologyError(f"{field} must be an IPv4 address in CIDR notation") from exc
    if address.version != 4:
        raise TopologyError(f"{field} must be an IPv4 address")
    return address


def load_topology(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TopologyError(f"Topology file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TopologyError(f"Invalid JSON in {path}: {exc}") from exc
    validate_topology(data)
    return data


def _validate_node_common(node: dict[str, Any], names: set[str], host_ports: set[int]) -> None:
    if not isinstance(node, dict):
        raise TopologyError("each node must be an object")
    for field in ("name", "image"):
        if not isinstance(node.get(field), str) or not node[field].strip():
            raise TopologyError(f"node.{field} must be a non-empty string")
    validate_identifier(node["name"], f"node {node['name']}.name")
    if node["name"] in names:
        raise TopologyError(f"duplicate node name: {node['name']}")
    names.add(node["name"])
    command = node.get("command", DEFAULT_COMMAND)
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise TopologyError(f"node {node['name']} command must be a non-empty string list")
    service_id = node.get("service_id")
    published_port = node.get("published_port")
    if service_id is not None and (not isinstance(service_id, str) or not service_id.strip()):
        raise TopologyError(f"node {node['name']} service_id must be a non-empty string")
    if published_port is not None and (not isinstance(published_port, int) or isinstance(published_port, bool) or not 1 <= published_port <= 65535):
        raise TopologyError(f"node {node['name']} published_port must be between 1 and 65535")
    try:
        validate_catalog_node(service_id, node["image"], command, published_port)
    except ValueError as exc:
        raise TopologyError(str(exc)) from exc
    if published_port is not None:
        if published_port in host_ports:
            raise TopologyError("published host ports must be unique in a topology")
        host_ports.add(published_port)
    position = node.get("position", {"x": 100, "y": 100})
    if not isinstance(position, dict) or not all(isinstance(position.get(axis), (int, float)) for axis in ("x", "y")):
        raise TopologyError(f"node {node['name']} position must contain numeric x and y")


def _validate_networks(topology: dict[str, Any], version: int) -> list[dict[str, Any]]:
    raw_networks = topology.get("networks") if version == 2 else [topology.get("network")]
    if not isinstance(raw_networks, list) or not raw_networks:
        raise TopologyError("topology must contain at least one network")
    names: set[str] = set()
    result: list[dict[str, Any]] = []
    subnets: list[ipaddress.IPv4Network] = []
    for network in raw_networks:
        if not isinstance(network, dict):
            raise TopologyError("each network must be an object")
        for field in ("name", "driver"):
            if not isinstance(network.get(field), str) or not network[field].strip():
                raise TopologyError(f"network.{field} must be a non-empty string")
        validate_identifier(network["name"], "network.name")
        if network["name"] in names:
            raise TopologyError(f"duplicate network name: {network['name']}")
        names.add(network["name"])
        if network["driver"] != "bridge":
            raise TopologyError("Docker execution currently supports only bridge networks")
        subnet = network.get("subnet")
        if not isinstance(subnet, str):
            raise TopologyError(f"network {network['name']} requires an IPv4 subnet")
        parsed = _network(subnet, f"network {network['name']}.subnet")
        if any(parsed.overlaps(other) for other in subnets):
            raise TopologyError("network subnets must not overlap")
        subnets.append(parsed)
        result.append(network)
    return result


def _validate_v2_node(node: dict[str, Any], network_names: set[str]) -> None:
    interfaces = node.get("interfaces")
    if not isinstance(interfaces, list) or not interfaces:
        raise TopologyError(f"node {node['name']} requires at least one interface in topology v2")
    interface_names: set[str] = set()
    addresses: set[str] = set()
    for interface in interfaces:
        if not isinstance(interface, dict):
            raise TopologyError(f"node {node['name']} interfaces must be objects")
        name = interface.get("name")
        validate_identifier(name, f"node {node['name']}.interface.name")
        if name in interface_names:
            raise TopologyError(f"node {node['name']} has duplicate interface {name}")
        interface_names.add(name)
        network = interface.get("network")
        if network not in network_names:
            raise TopologyError(f"interface {name} references unknown network {network}")
        address = interface.get("ipv4")
        if address is not None:
            parsed = _address(address, f"node {node['name']}.{name}.ipv4")
            if str(parsed.ip) in addresses:
                raise TopologyError("IPv4 addresses must be unique in a topology")
            addresses.add(str(parsed.ip))
        gateway = interface.get("gateway")
        if gateway is not None:
            _address(f"{gateway}/32", f"node {node['name']}.{name}.gateway")
    routes = node.get("routes", [])
    if not isinstance(routes, list):
        raise TopologyError(f"node {node['name']}.routes must be a list")
    for route in routes:
        if not isinstance(route, dict):
            raise TopologyError(f"node {node['name']} routes must be objects")
        _network(route.get("destination", ""), f"node {node['name']}.route.destination")
        _address(f"{route.get('via', '')}/32", f"node {node['name']}.route.via")


def validate_topology(topology: dict[str, Any]) -> None:
    if not isinstance(topology, dict):
        raise TopologyError("topology must be an object")
    required = {"version", "lab", "nodes", "connectivity_check"}
    missing = required - topology.keys()
    if missing:
        raise TopologyError(f"Missing top-level fields: {', '.join(sorted(missing))}")
    version = topology["version"]
    if version not in {1, 2}:
        raise TopologyError("Only topology format versions 1 and 2 are supported")
    validate_identifier(topology["lab"], "lab")
    networks = _validate_networks(topology, version)
    network_names = {network["name"] for network in networks}

    nodes = topology["nodes"]
    if not isinstance(nodes, list) or len(nodes) < 2:
        raise TopologyError("nodes must contain at least two nodes")
    names: set[str] = set()
    host_ports: set[int] = set()
    for node in nodes:
        _validate_node_common(node, names, host_ports)
        if version == 2:
            _validate_v2_node(node, network_names)
        records = node.get("dns_records", [])
        if node.get("service_id") == "coredns":
            if not isinstance(records, list) or not records or len(records) > 100:
                raise TopologyError(f"CoreDNS node {node['name']} requires 1 to 100 DNS A records")
            record_names: set[str] = set()
            for record in records:
                if not isinstance(record, dict):
                    raise TopologyError(f"CoreDNS node {node['name']} DNS records must be objects")
                hostname = record.get("name")
                if not isinstance(hostname, str) or len(hostname) > 253:
                    raise TopologyError(f"CoreDNS node {node['name']} has an invalid DNS name")
                labels = hostname.rstrip(".").lower().split(".")
                if not labels or any(
                    not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in labels
                ):
                    raise TopologyError(f"CoreDNS node {node['name']} has an invalid DNS name: {hostname}")
                normalized_name = ".".join(labels)
                if normalized_name in record_names:
                    raise TopologyError(f"CoreDNS node {node['name']} has duplicate DNS name: {hostname}")
                record_names.add(normalized_name)
                address_value = record.get("ipv4")
                if not isinstance(address_value, str):
                    raise TopologyError(f"CoreDNS record {hostname} must use an IPv4 address")
                try:
                    address = ipaddress.IPv4Address(address_value)
                except ipaddress.AddressValueError as exc:
                    raise TopologyError(f"CoreDNS record {hostname} must use an IPv4 address") from exc
                if not any(address in ipaddress.ip_network(network["subnet"]) for network in networks):
                    raise TopologyError(f"CoreDNS record {hostname} must use an address in a laboratory subnet")
        elif records:
            raise TopologyError(f"DNS records are only supported on CoreDNS nodes")

    links = topology.get("links", [])
    if not isinstance(links, list):
        raise TopologyError("links must be a list")
    for link in links:
        if not isinstance(link, dict) or link.get("from") not in names or link.get("to") not in names:
            raise TopologyError("each link must reference existing nodes with from and to")
        if link["from"] == link["to"]:
            raise TopologyError("a link cannot connect a node to itself")

    check = topology["connectivity_check"]
    if not isinstance(check, dict):
        raise TopologyError("connectivity_check must be an object")
    source, target = check.get("from"), check.get("to")
    if source not in names or target not in names or source == target:
        raise TopologyError("connectivity_check must reference two different nodes")
    command = check.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise TopologyError("connectivity_check.command must be a non-empty string list")
    if command[0] not in ALLOWED_CONNECTIVITY_COMMANDS:
        allowed = ", ".join(sorted(ALLOWED_CONNECTIVITY_COMMANDS))
        raise TopologyError(f"connectivity_check.command must start with one of: {allowed}")


def docker(*args: str, capture: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *args], check=False, text=True, capture_output=capture, timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(["docker", *args], 127, "", "Docker CLI is not installed or is not available in PATH")


def resource_name(topology: dict[str, Any], node_name: str | None = None) -> str:
    base = topology["lab"].lower().replace("_", "-")
    return f"netlab-{base}" if node_name is None else f"netlab-{base}-{node_name}"


def network_specs(topology: dict[str, Any]) -> list[dict[str, Any]]:
    networks = topology.get("networks")
    return networks if networks else [topology["network"]]


def network_gateway(topology: dict[str, Any], network: dict[str, Any]) -> str:
    subnet = ipaddress.ip_network(network["subnet"])
    occupied = {
        ipaddress.ip_interface(interface["ipv4"]).ip
        for node in topology["nodes"]
        for interface in node.get("interfaces", [])
        if interface.get("network") == network["name"] and interface.get("ipv4")
    }
    default_gateway = ipaddress.IPv4Address(int(subnet.network_address) + 1)
    if subnet.prefixlen < 31 and default_gateway not in occupied:
        return str(default_gateway)
    candidate = int(subnet.broadcast_address) - 1
    while candidate > int(subnet.network_address):
        address = ipaddress.IPv4Address(candidate)
        if address not in occupied:
            return str(address)
        candidate -= 1
    raise TopologyError(f"network {network['name']} has no free address for its Docker gateway")


def runtime_network_name(topology: dict[str, Any], network: dict[str, Any]) -> str:
    return f"{resource_name(topology)}-{network['name']}"


def runtime_config_dir(topology: dict[str, Any]) -> Path:
    data_dir = Path(os.getenv("NETLAB_DATA_DIR", Path(__file__).resolve().parent / ".netlab-data"))
    identity = topology.get("laboratory_id", topology["lab"])
    digest = hashlib.sha256(str(identity).encode()).hexdigest()[:32]
    return data_dir / "runtime-config" / digest


def runtime_config_path(topology: dict[str, Any], node: dict[str, Any]) -> Path:
    node_digest = hashlib.sha256(node["name"].encode()).hexdigest()[:16]
    return runtime_config_dir(topology) / f"{node_digest}.Corefile"


def _write_runtime_configs(topology: dict[str, Any]) -> None:
    for node in topology["nodes"]:
        if node.get("service_id") != "coredns":
            continue
        path = runtime_config_path(topology, node)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        records = [
            f"        {record['ipv4']} {record['name'].rstrip('.').lower()}"
            for record in node["dns_records"]
        ]
        corefile = "\n".join([
            ".:53 {",
            "    errors",
            "    health",
            "    ready",
            "    hosts {",
            *records,
            "        fallthrough",
            "    }",
            "    cache 30",
            "    forward . /etc/resolv.conf",
            "}",
            "",
        ])
        path.write_text(corefile, encoding="utf-8")
        path.chmod(0o644)


def _remove_runtime_configs(topology: dict[str, Any]) -> None:
    config_dir = runtime_config_dir(topology)
    if config_dir.is_dir():
        shutil.rmtree(config_dir)


def node_interfaces(topology: dict[str, Any], node: dict[str, Any]) -> list[dict[str, Any]]:
    if topology["version"] == 1:
        return [{"name": "eth0", "network": network_specs(topology)[0]["name"]}]
    return node["interfaces"]


def docker_run_args(topology: dict[str, Any], node: dict[str, Any], network_name: str, interface: dict[str, Any] | None = None) -> list[str]:
    """Build bounded Docker run arguments for the first interface."""
    profile = get_service(node.get("service_id", ""))
    resources = profile.resources if profile else {"memory_mb": 512, "cpu_cores": 1, "pids": 256}
    container = resource_name(topology, node["name"])
    args = [
        "run", "-d", "--name", container,
        "--security-opt", "no-new-privileges:true",
        "--memory", f"{int(resources['memory_mb'])}m",
        "--cpus", f"{float(resources['cpu_cores']):g}",
        "--pids-limit", str(int(resources["pids"])),
        "--label", f"io.netlab.studio.lab={topology['lab']}",
        *(["--label", f"io.netlab.studio.laboratory_id={topology['laboratory_id']}"] if topology.get("laboratory_id") else []),
        "--label", f"io.netlab.studio.memory-mb={int(resources['memory_mb'])}",
        "--label", f"io.netlab.studio.cpu-cores={float(resources['cpu_cores']):g}",
        "--label", f"io.netlab.studio.pids={int(resources['pids'])}",
        "--network", network_name,
    ]
    if interface and interface.get("ipv4"):
        args += ["--ip", str(ipaddress.ip_interface(interface["ipv4"]).ip)]
    if node.get("type") == "router" or node.get("router") is True:
        args += ["--cap-add", "NET_ADMIN", "--sysctl", "net.ipv4.ip_forward=1"]
    elif node.get("routes"):
        args += ["--cap-add", "NET_ADMIN"]
    if node.get("service_id") == "coredns":
        args += [
            "--mount",
            f"type=bind,source={runtime_config_path(topology, node)},target=/etc/coredns/Corefile,readonly",
        ]
    if profile:
        args += ["--label", "io.netlab.studio.service=" + profile.id]
        if node.get("published_port") is not None:
            args += ["--publish", f"127.0.0.1:{node['published_port']}:{profile.primary_port}/tcp"]
    args += [node["image"], *node.get("command", DEFAULT_COMMAND)]
    return args


def _cleanup(topology: dict[str, Any], containers: list[str], networks: list[str]) -> None:
    for container in containers:
        docker("rm", "-f", container, capture=True)
    for network in networks:
        docker("network", "rm", network, capture=True)
    _remove_runtime_configs(topology)


def _exec_retry(container: str, command: list[str], attempts: int = 20) -> subprocess.CompletedProcess[str]:
    result = docker("exec", container, *command, capture=True)
    for _ in range(attempts - 1):
        if result.returncode == 0:
            return result
        time.sleep(0.25)
        result = docker("exec", container, *command, capture=True)
    return result


def deploy(topology: dict[str, Any]) -> int:
    validate_topology(topology)
    specs = network_specs(topology)
    runtime_networks = [runtime_network_name(topology, network) for network in specs]
    created_networks: list[str] = []
    containers: list[str] = []
    try:
        _write_runtime_configs(topology)
        for network, runtime_name in zip(specs, runtime_networks):
            inspected = docker("network", "inspect", runtime_name, capture=True)
            if inspected.returncode != 0:
                args = ["network", "create", "--driver", network["driver"], "--label", f"io.netlab.studio.lab={topology['lab']}"]
                if topology.get("laboratory_id"):
                    args += ["--label", f"io.netlab.studio.laboratory_id={topology['laboratory_id']}"]
                args += ["--subnet", network["subnet"], "--gateway", network_gateway(topology, network), runtime_name]
                result = docker(*args, capture=True)
                if result.returncode:
                    print(result.stderr.strip(), file=sys.stderr)
                    _cleanup(topology, containers, created_networks)
                    return result.returncode
                created_networks.append(runtime_name)
                print(f"created network {runtime_name}")
        for node in topology["nodes"]:
            container = resource_name(topology, node["name"])
            docker("rm", "-f", container, capture=True)
            interfaces = node_interfaces(topology, node)
            first_network = next(network for network in specs if network["name"] == interfaces[0]["network"])
            result = docker(*docker_run_args(topology, node, runtime_network_name(topology, first_network), interfaces[0]), capture=True)
            if result.returncode:
                print(f"failed to start {node['name']}: {result.stderr.strip()}", file=sys.stderr)
                docker("rm", "-f", container, capture=True)
                _cleanup(topology, containers, created_networks)
                return result.returncode
            containers.append(container)
            for interface in interfaces[1:]:
                network = next(network for network in specs if network["name"] == interface["network"])
                args = ["network", "connect"]
                if interface.get("ipv4"):
                    args += ["--ip", str(ipaddress.ip_interface(interface["ipv4"]).ip)]
                args += [runtime_network_name(topology, network), container]
                result = docker(*args, capture=True)
                if result.returncode:
                    print(f"failed to attach {node['name']} to {network['name']}: {result.stderr.strip()}", file=sys.stderr)
                    _cleanup(topology, containers, created_networks)
                    return result.returncode
            for route in node.get("routes", []):
                result = _exec_retry(container, ["ip", "route", "replace", route["destination"], "via", route["via"]])
                if result.returncode:
                    print(f"failed to configure route on {node['name']}: {result.stderr.strip()}", file=sys.stderr)
                    _cleanup(topology, containers, created_networks)
                    return result.returncode
            print(f"started {node['name']} ({container})")
        return 0
    except (StopIteration, KeyError, ValueError) as exc:
        print(f"deployment plan error: {exc}", file=sys.stderr)
        _cleanup(topology, containers, created_networks)
        return 2
    except OSError as exc:
        print(f"could not prepare service configuration: {exc}", file=sys.stderr)
        _cleanup(topology, containers, created_networks)
        return 2


def verify(topology: dict[str, Any]) -> int:
    validate_topology(topology)
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
    validate_topology(topology)
    for node in topology["nodes"]:
        container = resource_name(topology, node["name"])
        result = docker("rm", "-f", container, capture=True)
        if result.returncode == 0:
            print(f"removed {container}")
    for network in network_specs(topology):
        runtime_name = runtime_network_name(topology, network)
        result = docker("network", "rm", runtime_name, capture=True)
        if result.returncode == 0:
            print(f"removed network {runtime_name}")
    _remove_runtime_configs(topology)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Netlab Studio topology orchestrator")
    parser.add_argument("topology", type=Path, help="path to a version 1 or 2 topology JSON file")
    parser.add_argument("action", choices=("validate", "up", "verify", "down"))
    args = parser.parse_args()
    try:
        topology = load_topology(args.topology)
        if args.action == "validate":
            print(f"valid topology: {topology['lab']} (v{topology['version']}, {len(topology['nodes'])} nodes)")
            return 0
        if args.action == "up":
            return deploy(topology)
        if args.action == "verify":
            return verify(topology)
        return destroy(topology)
    except TopologyError as exc:
        print(f"topology error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
