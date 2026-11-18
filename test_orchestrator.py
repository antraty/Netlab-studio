import unittest
from pathlib import Path

from fastapi import HTTPException

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

    def test_worker_refuses_jobs_without_a_configured_token(self):
        import worker.main as worker_main

        previous = worker_main.TOKEN
        try:
            worker_main.TOKEN = ""
            with self.assertRaises(HTTPException) as caught:
                worker_main.require_token(None)
            self.assertEqual(caught.exception.status_code, 503)
            worker_main.TOKEN = "test-worker-token"
            worker_main.require_token("Bearer test-worker-token")
        finally:
            worker_main.TOKEN = previous


if __name__ == "__main__":
    unittest.main()
