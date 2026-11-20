from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parent


class DeploymentContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    def test_compose_contains_the_four_runtime_services(self) -> None:
        for service in ("db:", "worker:", "control:", "frontend:"):
            self.assertIn(f"\n  {service}", self.compose)

    def test_only_frontend_publishes_a_host_port(self) -> None:
        self.assertIn('"${NETLAB_HTTP_PORT:-8080}:80"', self.compose)
        self.assertNotIn('"9000:9000"', self.compose)
        self.assertNotIn('"5432:5432"', self.compose)

    def test_docker_socket_is_mounted_only_for_worker(self) -> None:
        self.assertEqual(self.compose.count("/var/run/docker.sock:/var/run/docker.sock"), 1)
        worker_start = self.compose.index("  worker:")
        control_start = self.compose.index("  control:")
        socket_index = self.compose.index("/var/run/docker.sock:/var/run/docker.sock")
        self.assertLess(worker_start, socket_index)
        self.assertLess(socket_index, control_start)

    def test_worker_scale_uses_unique_hostnames_and_mounts_tls_material_read_only(self) -> None:
        worker_start = self.compose.index("  worker:")
        control_start = self.compose.index("  control:")
        worker = self.compose[worker_start:control_start]
        self.assertIn("NETLAB_WORKER_ID: ${NETLAB_WORKER_ID:-}", worker)
        self.assertIn(":/run/netlab/worker-certs:ro", worker)
        self.assertIn("socket.create_connection", worker)
        self.assertIn("NETLAB_WORKER_URL: ${NETLAB_COMPOSE_WORKER_URL:-http://worker:9000}", self.compose)
        self.assertIn("NETLAB_CONTROL_URL: ${NETLAB_COMPOSE_CONTROL_URL:-http://control:8000}", worker)
        self.assertIn("NETLAB_DATABASE_URL: ${NETLAB_DATABASE_URL:-", self.compose)

    def test_frontend_proxies_api_and_websocket(self) -> None:
        nginx = (ROOT / "docker/nginx.conf").read_text(encoding="utf-8")
        self.assertIn("location /api/", nginx)
        self.assertIn("location /ws/", nginx)
        self.assertIn('proxy_set_header Upgrade $http_upgrade;', nginx)

    def test_dockerfiles_use_locked_frontend_install(self) -> None:
        frontend = (ROOT / "docker/frontend.Dockerfile").read_text(encoding="utf-8")
        self.assertIn("npm ci", frontend)
        self.assertIn("npm run build", frontend)

    def test_setup_generates_secrets_only_when_env_is_missing(self) -> None:
        from scripts import setup

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_example = root / ".env.example"
            env_file = root / ".env"
            env_example.write_text(
                "POSTGRES_PASSWORD=replace-with-a-long-random-password\n"
                "NETLAB_WORKER_TOKEN=replace-with-a-long-random-token\n"
                "NETLAB_BOOTSTRAP_TOKEN=replace-with-a-long-random-bootstrap-token\n",
                encoding="utf-8",
            )
            with patch.object(setup, "ENV_EXAMPLE", env_example), patch.object(setup, "ENV_FILE", env_file):
                self.assertTrue(setup.setup())
                first = env_file.read_text(encoding="utf-8")
                self.assertNotIn("replace-with-a-", first)
                self.assertTrue(setup.setup())
                self.assertEqual(env_file.read_text(encoding="utf-8"), first)

    def test_ready_endpoint_and_make_targets_are_wired(self) -> None:
        nginx = (ROOT / "docker/nginx.conf").read_text(encoding="utf-8")
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("location = /ready", nginx)
        self.assertIn("setup:", makefile)
        self.assertIn("lab-images:", makefile)
        self.assertIn("up: setup lab-images", makefile)


if __name__ == "__main__":
    unittest.main()
