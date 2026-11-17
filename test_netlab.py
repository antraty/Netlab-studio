import json
import unittest
from pathlib import Path

from netlab import TopologyError, load_topology, validate_topology


ROOT = Path(__file__).parent


class TopologyTests(unittest.TestCase):
    def test_example_topology_is_valid(self):
        topology = load_topology(ROOT / "topology.json")
        self.assertEqual(topology["version"], 1)
        self.assertEqual(len(topology["nodes"]), 2)

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
