import copy
import unittest
from pathlib import Path

from backend.app.services import list_services
from netlab import TopologyError, docker_run_args, load_topology, validate_topology


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
        self.assertEqual(deployable, {"nginx", "apache"})
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
        self.assertIn("127.0.0.1:8088:80/tcp", args)
        self.assertNotIn("0.0.0.0:8088:80/tcp", args)

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
