from pathlib import Path
import unittest


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

    def test_frontend_proxies_api_and_websocket(self) -> None:
        nginx = (ROOT / "docker/nginx.conf").read_text(encoding="utf-8")
        self.assertIn("location /api/", nginx)
        self.assertIn("location /ws/", nginx)
        self.assertIn('proxy_set_header Upgrade $http_upgrade;', nginx)

    def test_dockerfiles_use_locked_frontend_install(self) -> None:
        frontend = (ROOT / "docker/frontend.Dockerfile").read_text(encoding="utf-8")
        self.assertIn("npm ci", frontend)
        self.assertIn("npm run build", frontend)


if __name__ == "__main__":
    unittest.main()
