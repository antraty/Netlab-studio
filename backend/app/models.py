from __future__ import annotations

import ipaddress
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import netlab
from .services import validate_catalog_node


class Position(BaseModel):
    x: float = 100
    y: float = 100


class Network(BaseModel):
    name: str
    driver: str = "bridge"
    subnet: str

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        netlab.validate_identifier(value, "network.name")
        return value


class Interface(BaseModel):
    name: str
    network: str
    ipv4: str | None = None
    gateway: str | None = None

    @field_validator("name", "network")
    @classmethod
    def valid_identifier(cls, value: str) -> str:
        netlab.validate_identifier(value, "interface field")
        return value


class Route(BaseModel):
    destination: str
    via: str


class DNSRecord(BaseModel):
    name: str
    ipv4: str

    @field_validator("name")
    @classmethod
    def valid_hostname(cls, value: str) -> str:
        value = value.strip().rstrip(".").lower()
        labels = value.split(".")
        if len(value) > 253 or not labels or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        ):
            raise ValueError("DNS name must be a valid hostname")
        return value

    @field_validator("ipv4")
    @classmethod
    def valid_ipv4(cls, value: str) -> str:
        try:
            return str(ipaddress.IPv4Address(value))
        except ipaddress.AddressValueError as exc:
            raise ValueError("DNS record address must be IPv4") from exc


class Node(BaseModel):
    name: str
    image: str
    command: list[str] = Field(default_factory=lambda: ["sleep", "infinity"])
    backend: str = "docker"
    cpu_cores: float = Field(default=1, gt=0, le=128)
    memory_mb: int = Field(default=512, gt=0, le=1_048_576)
    disk_gb: int = Field(default=0, ge=0, le=10_240)
    license_id: str | None = Field(default=None, max_length=128)
    console: str | None = Field(default=None, max_length=32)
    position: Position = Field(default_factory=Position)
    service_id: str | None = None
    published_port: int | None = Field(default=None, ge=1, le=65535)
    type: str = "linux"
    router: bool = False
    interfaces: list[Interface] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    dns_records: list[DNSRecord] | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("name", "image")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        netlab.validate_identifier(value, "node.name")
        return value

    @field_validator("command")
    @classmethod
    def non_empty_command(cls, value: list[str]) -> list[str]:
        if not value or not all(isinstance(item, str) for item in value):
            raise ValueError("command must be a non-empty string list")
        return value

    @field_validator("environment")
    @classmethod
    def bounded_environment(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key):
                raise ValueError("environment keys must be uppercase identifiers")
            if len(item) > 4096:
                raise ValueError("environment values must be at most 4096 characters")
        return value

    @field_validator("secret_refs")
    @classmethod
    def bounded_secret_refs(cls, value: dict[str, str]) -> dict[str, str]:
        for key, reference in value.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key):
                raise ValueError("secret reference keys must be uppercase identifiers")
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", reference):
                raise ValueError("secret references must be safe identifiers")
        return value

    @field_validator("depends_on")
    @classmethod
    def bounded_dependencies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("depends_on must not contain duplicates")
        for dependency in value:
            netlab.validate_identifier(dependency, "node dependency")
        return value

    @field_validator("backend")
    @classmethod
    def supported_backend(cls, value: str) -> str:
        if value not in {"docker", "libvirt"}:
            raise ValueError("node backend must be docker or libvirt")
        return value

    @field_validator("console")
    @classmethod
    def supported_console(cls, value: str | None) -> str | None:
        if value is not None and value not in {"vnc", "spice", "rdp", "ssh"}:
            raise ValueError("console must be vnc, spice, rdp or ssh")
        return value


class Link(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    from_port: str | None = None
    to_port: str | None = None


class ConnectivityCheck(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    command: list[str]

    model_config = ConfigDict(populate_by_name=True)


class Topology(BaseModel):
    version: int = 1
    lab: str
    laboratory_id: str | None = None
    network: Network | None = None
    networks: list[Network] = Field(default_factory=list)
    nodes: list[Node]
    connectivity_check: ConnectivityCheck
    links: list[Link] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "Topology":
        if self.version not in {1, 2}:
            raise ValueError("only topology format versions 1 and 2 are supported")
        netlab.validate_identifier(self.lab, "lab")
        if self.laboratory_id is not None:
            try:
                UUID(self.laboratory_id)
            except ValueError as exc:
                raise ValueError("laboratory_id must be a UUID") from exc
        if self.version == 1:
            if self.network is None:
                raise ValueError("version 1 requires network")
            self.networks = [self.network]
        else:
            if not self.networks:
                raise ValueError("version 2 requires networks")
            if self.network is None:
                self.network = self.networks[0]
        if len(self.nodes) < 2:
            raise ValueError("nodes must contain at least two nodes")
        names = [node.name for node in self.nodes]
        if len(names) != len(set(names)):
            raise ValueError("node names must be unique")
        network_names = {network.name for network in self.networks}
        if len(network_names) != len(self.networks):
            raise ValueError("network names must be unique")
        known = set(names)
        host_ports: set[int] = set()
        for node in self.nodes:
            validate_catalog_node(
                node.service_id,
                node.image,
                node.command,
                node.published_port,
                node.environment,
                node.secret_refs,
            )
            if any(dependency not in known for dependency in node.depends_on):
                raise ValueError(f"node {node.name} depends on an unknown node")
            if node.name in node.depends_on:
                raise ValueError(f"node {node.name} cannot depend on itself")
            if node.service_id == "coredns" and not node.dns_records:
                raise ValueError(f"CoreDNS node {node.name} requires at least one A record")
            if node.service_id != "coredns" and node.dns_records:
                raise ValueError(f"DNS records are only supported on CoreDNS nodes")
            if node.published_port is not None:
                if node.published_port in host_ports:
                    raise ValueError("published host ports must be unique in a topology")
                host_ports.add(node.published_port)
            if self.version == 2:
                if not node.interfaces:
                    raise ValueError(f"node {node.name} requires at least one interface")
                if any(interface.network not in network_names for interface in node.interfaces):
                    raise ValueError(f"node {node.name} references an unknown network")
        if any(network.driver != "bridge" for network in self.networks):
            raise ValueError("prototype only supports bridge networks")
        if self.connectivity_check.from_node not in known or self.connectivity_check.to_node not in known:
            raise ValueError("connectivity check references an unknown node")
        if self.connectivity_check.from_node == self.connectivity_check.to_node:
            raise ValueError("connectivity check needs two different nodes")
        if not self.connectivity_check.command or self.connectivity_check.command[0] not in netlab.ALLOWED_CONNECTIVITY_COMMANDS:
            allowed = ", ".join(sorted(netlab.ALLOWED_CONNECTIVITY_COMMANDS))
            raise ValueError(f"connectivity check command must start with one of: {allowed}")
        for link in self.links:
            if link.from_node not in known or link.to_node not in known:
                raise ValueError("link references an unknown node")
            if link.from_node == link.to_node:
                raise ValueError("a link cannot connect a node to itself")
            if (link.from_port is None) != (link.to_port is None):
                raise ValueError("link ports must be provided for both endpoints")
            if link.from_port is not None and link.to_port is not None:
                source = next(node for node in self.nodes if node.name == link.from_node)
                target = next(node for node in self.nodes if node.name == link.to_node)
                if link.from_port not in {interface.name for interface in source.interfaces}:
                    raise ValueError(f"link references unknown port {link.from_node}.{link.from_port}")
                if link.to_port not in {interface.name for interface in target.interfaces}:
                    raise ValueError(f"link references unknown port {link.to_node}.{link.to_port}")
        return self

    def to_topology_dict(self) -> dict[str, Any]:
        data = self.model_dump(by_alias=True, exclude_none=True)
        if self.version == 1:
            data.pop("networks", None)
            data.pop("type", None)
        return data


class TopologyEnvelope(BaseModel):
    topology: Topology


class TerminalRequest(BaseModel):
    command: list[str] = Field(min_length=1, max_length=8)

    @field_validator("command")
    @classmethod
    def bounded_command(cls, value: list[str]) -> list[str]:
        if any(len(argument) > 256 for argument in value) or sum(map(len, value)) > 4096:
            raise ValueError("terminal command arguments exceed the size limit")
        return value


class VersionInfo(BaseModel):
    version: int
    lab: str
    created_at: str
    reason: str


class VersionsResponse(BaseModel):
    lab: str
    versions: list[VersionInfo]


class CloneRequest(BaseModel):
    new_lab: str


class CreateLaboratoryRequest(BaseModel):
    topology: dict[str, Any]


class LaboratoryMemberRequest(BaseModel):
    email: str
    role: str = "viewer"
