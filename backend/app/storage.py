from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StorageError(ValueError):
    pass


class TopologyStore:
    """Filesystem repository for immutable topology versions.

    Runtime container state is intentionally not stored here; only the desired
    topology is persisted so a laboratory can be recreated deterministically.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
        if not slug:
            raise StorageError("lab name must contain letters or numbers")
        return slug[:64]

    def _lab_dir(self, lab: str) -> Path:
        return self.root / self._slug(lab)

    def _versions_dir(self, lab: str) -> Path:
        path = self._lab_dir(lab) / "versions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, topology: dict[str, Any], reason: str = "save") -> dict[str, Any]:
        lab = topology["lab"]
        versions = self._versions_dir(lab)
        existing = sorted(versions.glob("*.json"))
        version = (int(existing[-1].stem) + 1) if existing else 1
        timestamp = datetime.now(timezone.utc).isoformat()
        record = {"version": version, "lab": lab, "created_at": timestamp, "reason": reason, "topology": topology}
        target = versions / f"{version:06d}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        current = self._lab_dir(lab) / "current.json"
        current.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return {key: record[key] for key in ("version", "lab", "created_at", "reason")}

    def list_versions(self, lab: str) -> list[dict[str, Any]]:
        versions = []
        for path in sorted(self._versions_dir(lab).glob("*.json"), reverse=True):
            record = json.loads(path.read_text(encoding="utf-8"))
            versions.append({key: record[key] for key in ("version", "lab", "created_at", "reason")})
        return versions

    def load(self, lab: str, version: int | None = None) -> dict[str, Any]:
        path = self._lab_dir(lab) / "current.json" if version is None else self._versions_dir(lab) / f"{version:06d}.json"
        if not path.exists():
            raise StorageError(f"topology version not found: {lab}/{version or 'current'}")
        return json.loads(path.read_text(encoding="utf-8"))["topology"]

    def restore(self, lab: str, version: int) -> dict[str, Any]:
        topology = self.load(lab, version)
        self.save(topology, reason=f"restore:{version}")
        return topology

    def clone(self, lab: str, new_lab: str) -> dict[str, Any]:
        if self._lab_dir(new_lab).exists():
            raise StorageError(f"laboratory already exists: {new_lab}")
        topology = dict(self.load(lab))
        topology["lab"] = new_lab
        self.save(topology, reason=f"clone:{lab}")
        return topology

    def export(self, lab: str) -> dict[str, Any]:
        return {"format": "netlab-laboratory-v1", "topology": self.load(lab), "versions": self.list_versions(lab)}
