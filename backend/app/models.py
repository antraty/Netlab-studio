from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Position(BaseModel):
    x: float = 100
    y: float = 100


class Network(BaseModel):
    name: str
    driver: str = "bridge"
    subnet: str | None = None


class Node(BaseModel):
    name: str
    image: str
    command: list[str] = Field(default_factory=lambda: ["sleep", "infinity"])
    position: Position = Field(default_factory=Position)

    @field_validator("name", "image")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
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
    network: Network
    nodes: list[Node]
    connectivity_check: ConnectivityCheck
    links: list[Link] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "Topology":
        if self.version != 1:
            raise ValueError("only topology format version 1 is supported")
        if len(self.nodes) < 2:
            raise ValueError("nodes must contain at least two nodes")
        names = [node.name for node in self.nodes]
        if len(names) != len(set(names)):
            raise ValueError("node names must be unique")
        known = set(names)
        if self.network.driver != "bridge":
            raise ValueError("prototype only supports the bridge network driver")
        if self.connectivity_check.from_node not in known or self.connectivity_check.to_node not in known:
            raise ValueError("connectivity check references an unknown node")
        if self.connectivity_check.from_node == self.connectivity_check.to_node:
            raise ValueError("connectivity check needs two different nodes")
        for link in self.links:
            if link.from_node not in known or link.to_node not in known:
                raise ValueError("link references an unknown node")
            if link.from_node == link.to_node:
                raise ValueError("a link cannot connect a node to itself")
        return self

    def to_topology_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


class TopologyEnvelope(BaseModel):
    topology: Topology


class TerminalRequest(BaseModel):
    command: list[str]
