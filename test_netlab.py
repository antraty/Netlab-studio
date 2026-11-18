import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from netlab import TopologyError, deploy, load_topology, validate_topology


ROOT = Path(__file__).parent


class TopologyTests(unittest.TestCase):
    def test_example_topology_is_valid(self):
        topology = load_topology(ROOT / "topology.json")
        self.assertEqual(topology["version"], 2)
        self.assertEqual(len(topology["nodes"]), 3)
        self.assertEqual(len(topology["networks"]), 2)
        self.assertEqual(topology["nodes"][1]["interfaces"][1]["ipv4"], "10.0.2.1/24")

    def test_v2_rejects_unknown_interface_network(self):
        topology = load_topology(ROOT / "topology.json")
        topology["nodes"][0]["interfaces"][0]["network"] = "missing-lan"
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_v2_rejects_overlapping_subnets(self):
        topology = load_topology(ROOT / "topology.json")
        topology["networks"][1]["subnet"] = "10.0.1.0/25"
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_duplicate_node_names_are_rejected(self):
        topology = load_topology(ROOT / "topology.json")
        topology["nodes"][1]["name"] = topology["nodes"][0]["name"]
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_connectivity_check_must_reference_existing_nodes(self):
        topology = load_topology(ROOT / "topology.json")
        topology["connectivity_check"]["to"] = "missing-node"
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_links_must_reference_existing_nodes(self):
        topology = load_topology(ROOT / "topology.json")
        topology["links"].append({"from": "client-ubuntu", "to": "missing-node"})
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_docker_identifiers_are_restricted(self):
        topology = load_topology(ROOT / "topology.json")
        topology["lab"] = "demo/lab"
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_connectivity_check_cannot_run_an_arbitrary_command(self):
        topology = load_topology(ROOT / "topology.json")
        topology["connectivity_check"]["command"] = ["sh", "-c", "id"]
        with self.assertRaises(TopologyError):
            validate_topology(topology)

    def test_v2_deploys_networks_interfaces_and_routes(self):
        topology = load_topology(ROOT / "topology.json")
        calls: list[tuple[str, ...]] = []

        def fake_docker(*args: str, capture: bool = False):
            calls.append(args)
            if args[:2] == ("network", "inspect") or args[:2] == ("rm", "-f"):
                return subprocess.CompletedProcess(args, 1, "", "not found")
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch("netlab.docker", side_effect=fake_docker):
            self.assertEqual(deploy(topology), 0)
        creates = [call for call in calls if call[:2] == ("network", "create")]
        connects = [call for call in calls if call[:2] == ("network", "connect")]
        routes = [call for call in calls if call[:2] == ("exec", "netlab-static-routing-demo-client-ubuntu") or call[:2] == ("exec", "netlab-static-routing-demo-server-debian")]
        self.assertEqual(len(creates), 2)
        self.assertEqual(len(connects), 1)
        self.assertEqual(len(routes), 2)
        self.assertIn("10.0.2.0/24", routes[0])

    def test_invalid_json_is_rejected(self):
        path = ROOT / ".invalid-topology.json"
        path.write_text("{not json", encoding="utf-8")
        try:
            with self.assertRaises(TopologyError):
                load_topology(path)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
