import unittest
from pathlib import Path

from orchestrator import DockerOrchestrator
from netlab import TopologyError, load_topology


class OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topology = load_topology(Path(__file__).parent / "topology.json")

    def test_docker_status_is_reported_without_crashing_when_unavailable(self):
        nodes = DockerOrchestrator(self.topology).status()
        self.assertEqual(len(nodes), 2)
        self.assertIn(nodes[0]["state"], {"docker-unavailable", "docker-error", "stopped"})

    def test_terminal_rejects_arbitrary_shell_commands(self):
        with self.assertRaises(ValueError):
            DockerOrchestrator(self.topology).terminal("client-ubuntu", ["sh", "-c", "id"])

    def test_invalid_topology_is_rejected_at_orchestrator_boundary(self):
        invalid = dict(self.topology)
        invalid["nodes"] = []
        with self.assertRaises(TopologyError):
            DockerOrchestrator(invalid)


if __name__ == "__main__":
    unittest.main()
