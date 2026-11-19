import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestrator import DockerOrchestrator
from netlab import TopologyError, load_topology


class OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topology = load_topology(Path(__file__).parent / "topology.json")

    def test_docker_status_is_reported_without_crashing_when_unavailable(self):
        nodes = DockerOrchestrator(self.topology).status()
        self.assertEqual(len(nodes), 3)
        self.assertIn(nodes[0]["state"], {"docker-unavailable", "docker-error", "stopped"})

    def test_terminal_rejects_arbitrary_shell_commands(self):
        with self.assertRaises(ValueError):
            DockerOrchestrator(self.topology).terminal("client-ubuntu", ["sh", "-c", "id"])

    def test_terminal_bounds_ping_and_only_allows_read_only_network_commands(self):
        DockerOrchestrator._validate_terminal_command(["ping", "-c", "3", "-W", "2", "10.0.2.10"])
        DockerOrchestrator._validate_terminal_command(["ip", "-4", "route", "show"])
        for command in (
            ["ping", "-f", "10.0.2.10"],
            ["ping", "-c", "0", "10.0.2.10"],
            ["ping", "-c", "5", "10.0.2.10"],
            ["ping", "2001:db8::1"],
            ["ip", "route", "add", "default"],
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                DockerOrchestrator._validate_terminal_command(command)

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

    def test_worker_proxies_observability_with_bearer_authentication(self):
        import worker.main as worker_main

        previous = worker_main.TOKEN
        worker_main.TOKEN = "test-observability-token"
        sample = {"available": True, "active_lab_count": 3, "nodes": []}
        try:
            with patch.object(worker_main.DockerOrchestrator, "observability", return_value=sample) as observe:
                with TestClient(worker_main.app) as client:
                    payload = {"job_id": "test-job", "action": "observability", "topology": self.topology}
                    denied = client.post("/v1/jobs", json=payload)
                    self.assertEqual(denied.status_code, 401)
                    response = client.post(
                        "/v1/jobs",
                        json=payload,
                        headers={"Authorization": "Bearer test-observability-token"},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["observability"]["active_lab_count"], 3)
                    observe.assert_called_once_with()
        finally:
            worker_main.TOKEN = previous
