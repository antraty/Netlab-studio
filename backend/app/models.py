from __future__ import annotations

from typing import Any

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


class Node(BaseModel):
    name: str
    image: str
    command: list[str] = Field(default_factory=lambda: ["sleep", "infinity"])
    position: Position = Field(default_factory=Position)
    service_id: str | None = None
    published_port: int | None = Field(default=None, ge=1, le=65535)
    type: str = "linux"
    router: bool = False
    interfaces: list[Interface] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)

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


class Link(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")


class ConnectivityCheck(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    command: list[str]

    model_config = ConfigDict(populate_by_name=True)


class Topology(BaseModel):
    version: int = 1
    lab: str
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
            validate_catalog_node(node.service_id, node.image, node.command, node.published_port)
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
    command: list[str]


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
