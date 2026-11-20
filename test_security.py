from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import Response

from backend.app.education import EducationStore, _set_session
from backend.app import migrate_db
from backend.app.security import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    client_ssl_context,
    validate_production_settings,
    validate_production_topology,
    validate_worker_settings,
)


class ProductionSecurityTests(unittest.TestCase):
    def production_environment(self) -> dict[str, str]:
        return {
            "NETLAB_ENV": "production",
            "NETLAB_COOKIE_SECURE": "true",
            "NETLAB_DATABASE_URL": "postgresql://db.internal/netlab?sslmode=verify-full",
            "NETLAB_ALLOWED_ORIGINS": "https://netlab.example.test",
            "NETLAB_ALLOWED_HOSTS": "netlab.example.test",
            "NETLAB_WORKER_URL": "https://worker.internal",
            "NETLAB_WORKER_TOKEN": "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6",
            "NETLAB_ALLOWED_IMAGES": "netlab/ubuntu-lab:24.04,nginx:stable-alpine",
            "NETLAB_MTLS_CA_FILE": "/unused/ca.crt",
            "NETLAB_MTLS_CERT_FILE": "/unused/control.crt",
            "NETLAB_MTLS_KEY_FILE": "/unused/control.key",
        }

    def test_production_settings_fail_closed_and_accept_secure_values(self):
        with patch("backend.app.security.client_ssl_context", return_value=object()) as client_context, patch.dict(
            os.environ, self.production_environment(), clear=True,
        ):
            validate_production_settings()
            client_context.assert_called_once_with("NETLAB_MTLS", required=True)

        unsafe = self.production_environment()
        unsafe["NETLAB_ALLOWED_ORIGINS"] = "http://netlab.example.test"
        with patch("backend.app.security.client_ssl_context", return_value=object()), patch.dict(os.environ, unsafe, clear=True):
            with self.assertRaisesRegex(RuntimeError, "HTTPS origins"):
                validate_production_settings()

        unsafe = self.production_environment()
        unsafe["NETLAB_WORKER_URL"] = "http://worker.internal"
        with patch("backend.app.security.client_ssl_context", return_value=object()), patch.dict(os.environ, unsafe, clear=True):
            with self.assertRaisesRegex(RuntimeError, "WORKER_URL.*HTTPS"):
                validate_production_settings()

        unsafe = self.production_environment()
        del unsafe["NETLAB_MTLS_CERT_FILE"]
        with patch.dict(os.environ, unsafe, clear=True):
            with self.assertRaisesRegex(RuntimeError, "mTLS configuration is invalid"):
                validate_production_settings()

    def test_worker_must_use_private_bind_address_and_strong_token(self):
        worker_environment = {
            "NETLAB_ENV": "production",
            "NETLAB_WORKER_TOKEN": "B1c2D3e4F5g6H7i8J9k0L1m2N3o4P5q6",
            "NETLAB_WORKER_HOST": "10.10.0.5",
            "NETLAB_ALLOWED_IMAGES": "netlab/ubuntu-lab:24.04",
            "NETLAB_CONTROL_URL": "https://control.internal",
            "NETLAB_WORKER_TLS_ENABLED": "true",
            "NETLAB_CONTROL_MTLS_CA_FILE": "/unused/ca.crt",
            "NETLAB_CONTROL_MTLS_CERT_FILE": "/unused/worker-client.crt",
            "NETLAB_CONTROL_MTLS_KEY_FILE": "/unused/worker-client.key",
            "NETLAB_MTLS_SERVER_CERT_FILE": "/unused/worker.crt",
            "NETLAB_MTLS_SERVER_KEY_FILE": "/unused/worker.key",
            "NETLAB_MTLS_SERVER_CA_FILE": "/unused/ca.crt",
        }
        with patch("backend.app.security.client_ssl_context", return_value=object()), patch(
            "backend.app.security._validate_server_mtls",
        ), patch.dict(os.environ, worker_environment, clear=True):
            validate_worker_settings()
        worker_environment["NETLAB_WORKER_HOST"] = "0.0.0.0"
        with patch("backend.app.security.client_ssl_context", return_value=object()), patch(
            "backend.app.security._validate_server_mtls",
        ), patch.dict(os.environ, worker_environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "private IP"):
                validate_worker_settings()

    def test_production_requires_mtls_for_both_worker_directions(self):
        control = self.production_environment()
        control.pop("NETLAB_MTLS_CA_FILE")
        control.pop("NETLAB_MTLS_CERT_FILE")
        control.pop("NETLAB_MTLS_KEY_FILE")
        with patch.dict(os.environ, control, clear=True):
            with self.assertRaisesRegex(RuntimeError, "mTLS configuration is invalid"):
                validate_production_settings()

        worker = {
            "NETLAB_ENV": "production",
            "NETLAB_WORKER_TOKEN": "B1c2D3e4F5g6H7i8J9k0L1m2N3o4P5q6",
            "NETLAB_WORKER_HOST": "10.10.0.5",
            "NETLAB_ALLOWED_IMAGES": "netlab/ubuntu-lab:24.04",
            "NETLAB_CONTROL_URL": "https://control.internal",
        }
        with patch.dict(os.environ, worker, clear=True):
            with self.assertRaisesRegex(RuntimeError, "mTLS server requires"):
                validate_worker_settings()

        worker.update({
            "NETLAB_WORKER_TLS_ENABLED": "true",
            "NETLAB_MTLS_SERVER_CERT_FILE": "/unused/worker.crt",
            "NETLAB_MTLS_SERVER_KEY_FILE": "/unused/worker.key",
            "NETLAB_MTLS_SERVER_CA_FILE": "/unused/ca.crt",
        })
        with patch("backend.app.security._validate_server_mtls"), patch.dict(os.environ, worker, clear=True):
            with self.assertRaisesRegex(RuntimeError, "worker-to-control mTLS"):
                validate_worker_settings()

    def test_client_tls_context_requires_complete_identity(self):
        with patch.dict(os.environ, {"NETLAB_MTLS_CA_FILE": "/ca.crt"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "requires CA, client certificate and private key"):
                client_ssl_context("NETLAB_MTLS")

    def test_sqlite_migration_includes_runtime_and_worker_tables(self):
        self.assertTrue({
            "remote_workers",
            "worker_jobs",
            "execution_metrics",
            "alert_notifications",
            "cleanup_attempts",
            "execution_resources",
            "license_manifests",
            "license_acceptances",
            "execution_snapshots",
            "console_audit",
        }.issubset(migrate_db._TABLES))

    def test_production_topology_uses_exact_image_allowlist(self):
        topology = {"nodes": [{"image": "netlab/ubuntu-lab:24.04"}, {"image": "nginx:stable-alpine"}]}
        with patch.dict(os.environ, self.production_environment(), clear=True):
            validate_production_topology(topology)
            topology["nodes"][1]["image"] = "attacker/image:latest"
            with self.assertRaisesRegex(ValueError, "not approved"):
                validate_production_topology(topology)

    def test_failed_login_throttle_persists_and_resets(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = EducationStore(Path(tempdir) / "education.sqlite3")
            keys = ["email:student@example.test", "ip:192.0.2.1"]
            for _ in range(5):
                store.record_login_failure(keys)
            self.assertGreater(store.login_throttle_remaining(keys), 0)
            store.clear_login_failures(keys)
            self.assertEqual(store.login_throttle_remaining(keys), 0)

    def test_production_session_cookie_is_secure_and_headers_are_added(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = EducationStore(Path(tempdir) / "education.sqlite3")
            teacher = store.create_user(
                "teacher@example.test", "Teacher", "long-password-123", "teacher",
            )
            response = Response()
            with patch("backend.app.education.store", store), patch.dict(
                os.environ, {"NETLAB_ENV": "production", "NETLAB_COOKIE_SECURE": "false"},
            ):
                _set_session(response, teacher["id"])
            self.assertIn("netlab_session=", response.headers["set-cookie"])
            self.assertIn("secure", response.headers["set-cookie"].lower())

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/health")
        def health():
            return {"ok": True}

        with patch.dict(os.environ, {"NETLAB_ENV": "production"}):
            response = TestClient(app).get("/health")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("max-age=31536000", response.headers["strict-transport-security"])
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])

    def test_request_body_limit_returns_413(self):
        app = FastAPI()
        app.add_middleware(BodySizeLimitMiddleware, max_bytes=8)

        @app.post("/payload")
        def payload():
            return {"ok": True}

        response = TestClient(app).post("/payload", content=b"x" * 9)
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
