from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

import netlab

MAX_MONITORED_CONTAINERS = 100
_PS_FORMAT = "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Labels}}\t{{.Networks}}\t{{.Ports}}\t{{.Size}}"
_STATS_FORMAT = "{{.ID}}\t{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.BlockIO}}\t{{.NetIO}}"
_NETWORK_FORMAT = "{{.Name}}\t{{.Driver}}\t{{.Scope}}\t{{.Labels}}"
_DF_FORMAT = "{{.Type}}\t{{.TotalCount}}\t{{.Active}}\t{{.Size}}\t{{.Reclaimable}}"


def _bytes(value: str) -> int | None:
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(B|kB|KB|KiB|MB|MiB|GB|GiB|TB|TiB)\s*$", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    multiplier = {
        "B": 1,
        "kB": 1000,
        "KB": 1000,
        "KiB": 1024,
        "MB": 1000**2,
        "MiB": 1024**2,
        "GB": 1000**3,
        "GiB": 1024**3,
        "TB": 1000**4,
        "TiB": 1024**4,
    }[unit]
    return int(number * multiplier)


def _size_bytes(value: str) -> int | None:
    """Parse Docker system-df sizes and writable-layer size prefixes."""
    return _bytes(value.split(" (", 1)[0].strip())


def _percent(value: str) -> float | None:
    try:
        number = float(value.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _pair(value: str, parser: Callable[[str], int | None] = _bytes) -> tuple[int | None, int | None]:
    left, separator, right = value.partition("/")
    if not separator:
        return None, None
    return parser(left.strip()), parser(right.strip())


def _labels(value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in value.split(","):
        key, separator, content = item.partition("=")
        if separator:
            parsed[key.strip()] = content.strip()
    return parsed


def _threshold(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    if not math.isfinite(value):
        value = default
    return min(max(value, minimum), maximum)


def _error_text(prefix: str, result: Any) -> str:
    detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "commande Docker en échec").strip()
    return f"{prefix}: {detail[:500]}"


def _parse_ps(stdout: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        columns = line.split("\t", 8)
        if len(columns) != 9:
            continue
        container_id, name, image, state, status, raw_labels, raw_networks, ports, size = columns
        labels = _labels(raw_labels)
        lab = labels.get("io.netlab.studio.lab")
        if not lab:
            continue
        nodes.append({
            "id": container_id,
            "lab": lab,
            "name": name,
            "image": image,
            "state": state,
            "status": status,
            "networks": [value.strip() for value in raw_networks.split(",") if value.strip()],
            "ports": ports,
            "cpu_percent": None,
            "memory_usage_bytes": None,
            "memory_limit_bytes": None,
            "memory_percent": None,
            "cpu_limit_cores": _float_label(labels, "io.netlab.studio.cpu-cores"),
            "pids_limit": _int_label(labels, "io.netlab.studio.pids"),
            "writable_size_bytes": _size_bytes(size),
            "block_read_bytes": None,
            "block_write_bytes": None,
            "network_rx_bytes": None,
            "network_tx_bytes": None,
        })
    return nodes


def _float_label(labels: dict[str, str], key: str) -> float | None:
    try:
        value = float(labels[key])
        return value if math.isfinite(value) and value >= 0 else None
    except (KeyError, ValueError):
        return None


def _int_label(labels: dict[str, str], key: str) -> int | None:
    try:
        value = int(labels[key])
        return value if value >= 0 else None
    except (KeyError, ValueError):
        return None


def _apply_stats(nodes: list[dict[str, Any]], stdout: str) -> None:
    by_id = {node["id"].lower(): node for node in nodes}
    for line in stdout.splitlines():
        columns = line.split("\t", 6)
        if len(columns) != 7:
            continue
        container_id, _name, cpu, memory, memory_percent, block_io, network_io = columns
        node = by_id.get(container_id.lower())
        if node is None:
            continue
        node["cpu_percent"] = _percent(cpu)
        node["memory_usage_bytes"], node["memory_limit_bytes"] = _pair(memory)
        node["memory_percent"] = _percent(memory_percent)
        node["block_read_bytes"], node["block_write_bytes"] = _pair(block_io)
        node["network_rx_bytes"], node["network_tx_bytes"] = _pair(network_io)


def _docker_storage(stdout: str) -> list[dict[str, Any]]:
    storage: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        columns = line.split("\t", 4)
        if len(columns) != 5:
            continue
        kind, total_count, active_count, used, reclaimable = columns
        try:
            total = int(total_count)
        except ValueError:
            total = None
        try:
            active = int(active_count)
        except ValueError:
            active = None
        storage.append({
            "kind": kind,
            "total_count": total,
            "active_count": active,
            "used_bytes": _size_bytes(used),
            "reclaimable_bytes": _size_bytes(reclaimable),
        })
    return storage


def collect_docker_observability(docker: Callable[..., Any] = netlab.docker) -> dict[str, Any]:
    """Collect a bounded, read-only snapshot of Netlab-labelled Docker resources."""
    cpu_threshold = _threshold("NETLAB_ALERT_CPU_PERCENT", 80, 1, 1000)
    memory_threshold = _threshold("NETLAB_ALERT_MEMORY_PERCENT", 80, 1, 100)
    storage_threshold_mb = _threshold("NETLAB_ALERT_WRITABLE_STORAGE_MB", 1024, 1, 1_000_000)
    snapshot: dict[str, Any] = {
        "available": False,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "active_lab_count": 0,
        "running_node_count": 0,
        "labs": [],
        "nodes": [],
        "networks": [],
        "storage": [],
        "alerts": [],
        "errors": [],
        "events": [],
        "truncated": False,
        "thresholds": {
            "cpu_percent": cpu_threshold,
            "memory_percent": memory_threshold,
            "writable_storage_mb": storage_threshold_mb,
        },
    }

    ps = docker(
        "ps", "--all", "--size", "--filter", "label=io.netlab.studio.lab",
        "--format", _PS_FORMAT, capture=True,
    )
    if ps.returncode:
        message = _error_text("docker ps", ps)
        snapshot["errors"].append(message)
        snapshot["alerts"].append({"severity": "error", "message": message})
        return snapshot

    nodes = _parse_ps(ps.stdout)
    if len(nodes) > MAX_MONITORED_CONTAINERS:
        nodes = nodes[:MAX_MONITORED_CONTAINERS]
        snapshot["truncated"] = True
        snapshot["alerts"].append({
            "severity": "warning",
            "message": f"Inventaire tronqué aux {MAX_MONITORED_CONTAINERS} premiers conteneurs Netlab.",
        })
    snapshot["available"] = True

    running_ids = [node["id"] for node in nodes if node["state"].lower() == "running"]
    # IDs originate in Docker's ps output. Only allow normal hexadecimal IDs into argv.
    safe_ids = [value for value in running_ids if re.fullmatch(r"[0-9a-fA-F]{6,64}", value)]
    if safe_ids:
        stats = docker(
            "stats", "--no-stream", "--format", _STATS_FORMAT, *safe_ids, capture=True,
        )
        if stats.returncode:
            message = _error_text("docker stats", stats)
            snapshot["errors"].append(message)
            snapshot["alerts"].append({"severity": "error", "message": message})
        else:
            _apply_stats(nodes, stats.stdout)

    network_result = docker(
        "network", "ls", "--filter", "label=io.netlab.studio.lab",
        "--format", _NETWORK_FORMAT, capture=True,
    )
    network_records: dict[str, dict[str, Any]] = {}
    if network_result.returncode:
        message = _error_text("docker network ls", network_result)
        snapshot["errors"].append(message)
    else:
        for line in network_result.stdout.splitlines():
            columns = line.split("\t", 3)
            if len(columns) != 4:
                continue
            name, driver, scope, raw_labels = columns
            lab = _labels(raw_labels).get("io.netlab.studio.lab")
            network_records[name] = {"name": name, "lab": lab, "driver": driver, "scope": scope}

    for node in nodes:
        for network_name in node["networks"]:
            network_records.setdefault(network_name, {
                "name": network_name,
                "lab": node["lab"],
                "driver": "inconnu",
                "scope": "inconnu",
            })

    df = docker("system", "df", "--format", _DF_FORMAT, capture=True)
    if df.returncode:
        message = _error_text("docker system df", df)
        snapshot["errors"].append(message)
    else:
        snapshot["storage"] = _docker_storage(df.stdout)

    alerts: list[dict[str, str]] = snapshot["alerts"]
    for node in nodes:
        for metric, threshold, display in (
            ("cpu_percent", cpu_threshold, "CPU"),
            ("memory_percent", memory_threshold, "mémoire"),
        ):
            value = node[metric]
            if value is not None and value >= threshold:
                alerts.append({
                    "severity": "warning",
                    "lab": node["lab"],
                    "node": node["name"],
                    "message": f"{display} à {value:.1f}% (seuil d’alerte {threshold:.0f}%).",
                })
        writable = node["writable_size_bytes"]
        if writable is not None and writable >= storage_threshold_mb * 1024 * 1024:
            alerts.append({
                "severity": "warning",
                "lab": node["lab"],
                "node": node["name"],
                "message": f"Couche inscriptible au-dessus du seuil de {storage_threshold_mb:.0f} Mo.",
            })

    labs: dict[str, dict[str, Any]] = {}
    for node in nodes:
        lab = labs.setdefault(node["lab"], {
            "name": node["lab"],
            "node_count": 0,
            "running_count": 0,
            "cpu_percent": 0.0,
            "memory_usage_bytes": 0,
            "network_rx_bytes": 0,
            "network_tx_bytes": 0,
            "_cpu_samples": 0,
            "_memory_samples": 0,
            "_rx_samples": 0,
            "_tx_samples": 0,
        })
        lab["node_count"] += 1
        if node["state"].lower() == "running":
            lab["running_count"] += 1
        for target, source, count_key in (
            ("cpu_percent", "cpu_percent", "_cpu_samples"),
            ("memory_usage_bytes", "memory_usage_bytes", "_memory_samples"),
            ("network_rx_bytes", "network_rx_bytes", "_rx_samples"),
            ("network_tx_bytes", "network_tx_bytes", "_tx_samples"),
        ):
            value = node[source]
            if value is not None:
                lab[target] += value
                lab[count_key] += 1
    for lab in labs.values():
        for key, sample_key in (
            ("cpu_percent", "_cpu_samples"),
            ("memory_usage_bytes", "_memory_samples"),
            ("network_rx_bytes", "_rx_samples"),
            ("network_tx_bytes", "_tx_samples"),
        ):
            if not lab[sample_key]:
                lab[key] = None
            del lab[sample_key]

    snapshot["nodes"] = nodes
    snapshot["labs"] = sorted(labs.values(), key=lambda item: item["name"].lower())
    snapshot["networks"] = sorted(
        network_records.values(),
        key=lambda item: (str(item["lab"] or "").lower(), item["name"].lower()),
    )
    snapshot["running_node_count"] = sum(1 for node in nodes if node["state"].lower() == "running")
    snapshot["active_lab_count"] = sum(1 for lab in labs.values() if lab["running_count"] > 0)
    return snapshot
