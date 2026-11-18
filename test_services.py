import copy
import unittest
from pathlib import Path

from backend.app.services import list_services
from netlab import (
    TopologyError,
    _write_runtime_configs,
    docker_run_args,
    load_topology,
    runtime_config_path,
    validate_topology,
)


class ServiceCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_topology = load_topology(Path(__file__).parent / "topology.json")

    def nginx_topology(self, port=8088):
        topology = copy.deepcopy(self.base_topology)
        node = topology["nodes"][0]
        node.update({
            "service_id": "nginx",
            "image": "nginx:stable-alpine",
            "command": ["nginx", "-g", "daemon off;"],
            "published_port": port,
        })
        return topology, node

    def test_catalog_marks_only_the_initial_web_profiles_deployable(self):
        services = list_services()
        deployable = {service["id"] for service in services if service["deployable"]}
        self.assertEqual(deployable, {"nginx", "apache", "coredns"})
        self.assertIn("POSTGRES_PASSWORD", {item["name"] for service in services for item in service["environment"]})

    def test_nginx_run_args_have_resource_limits_and_loopback_publish(self):
        topology, node = self.nginx_topology()
        validate_topology(topology)
        args = docker_run_args(topology, node, "lab-network")
        self.assertIn("--memory", args)
        self.assertIn("512m", args)
        self.assertIn("--cpus", args)
        self.assertIn("0.5", args)
        self.assertIn("--pids-limit", args)
        self.assertIn("io.netlab.studio.memory-mb=512", args)
        self.assertIn("io.netlab.studio.cpu-cores=0.5", args)
        self.assertIn("io.netlab.studio.pids=128", args)
        self.assertIn("127.0.0.1:8088:80/tcp", args)
        self.assertNotIn("0.0.0.0:8088:80/tcp", args)

    def test_router_run_args_enable_forwarding(self):
        node = self.base_topology["nodes"][1]
        args = docker_run_args(self.base_topology, node, "lan-a-runtime", node["interfaces"][0])
        self.assertIn("--cap-add", args)
        self.assertIn("NET_ADMIN", args)
        self.assertIn("--sysctl", args)
        self.assertIn("net.ipv4.ip_forward=1", args)
        self.assertIn("--ip", args)
        self.assertIn("10.0.1.1", args)

    def test_coredns_generates_a_read_only_lab_config(self):
        topology = copy.deepcopy(self.base_topology)
        node = topology["nodes"][0]
        node.update({
            "service_id": "coredns",
            "image": "coredns/coredns:1.12.0",
            "command": ["-conf", "/etc/coredns/Corefile"],
            "dns_records": [{"name": "server.lab.test", "ipv4": "10.0.2.10"}],
        })
        topology["laboratory_id"] = "2de2ac28-f610-4c1d-8a22-f79b79012e1e"
        validate_topology(topology)
        args = docker_run_args(topology, node, "lan-a-runtime", node["interfaces"][0])
        self.assertIn("--mount", args)
        mount = args[args.index("--mount") + 1]
        self.assertIn("target=/etc/coredns/Corefile,readonly", mount)
        self.assertIn("256m", args)
        self.assertIn("0.25", args)

        with self.subTest("generated configuration"):
            from tempfile import TemporaryDirectory
            from unittest.mock import patch

            with TemporaryDirectory() as directory, patch.dict("os.environ", {"NETLAB_DATA_DIR": directory}):
                _write_runtime_configs(topology)
                config = runtime_config_path(topology, node)
                self.assertEqual(config.stat().st_mode & 0o777, 0o644)
                contents = config.read_text()
                self.assertIn("10.0.2.10 server.lab.test", contents)
                self.assertIn("forward . /etc/resolv.conf", contents)

    def test_coredns_records_are_confined_to_lab_subnets(self):
        topology = copy.deepcopy(self.base_topology)
        node = topology["nodes"][0]
        node.update({
            "service_id": "coredns",
            "image": "coredns/coredns:1.12.0",
            "command": ["-conf", "/etc/coredns/Corefile"],
            "dns_records": [{"name": "outside.lab.test", "ipv4": "192.0.2.10"}],
        })
        with self.assertRaisesRegex(TopologyError, "laboratory subnet"):
            validate_topology(topology)

    def test_unavailable_profiles_and_modified_images_are_rejected(self):
        topology, _ = self.nginx_topology()
        topology["nodes"][0]["service_id"] = "postgresql"
        topology["nodes"][0]["image"] = "postgres:17-alpine"
        topology["nodes"][0]["command"] = ["postgres"]
        topology["nodes"][0].pop("published_port")
        with self.assertRaises(TopologyError):
            validate_topology(topology)

        topology, _ = self.nginx_topology()
        topology["nodes"][0]["image"] = "attacker/image:latest"
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_host_published_port_must_be_valid_and_unique(self):
        topology, _ = self.nginx_topology(port=0)
        with self.assertRaises(TopologyError):
            validate_topology(topology)

        topology, _ = self.nginx_topology(port=8088)
        second = copy.deepcopy(topology["nodes"][0])
        second["name"] = "nginx-copy"
        second["position"] = {"x": 240, "y": 120}
        topology["nodes"].append(second)
        with self.assertRaises(TopologyError):
            validate_topology(topology)


if __name__ == "__main__":
    unittest.main()
