from copy import deepcopy
from contextlib import redirect_stdout
import io
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import education
from backend.app import admin
from backend.app.education import DatabaseConnection, EducationStore
from backend.app.storage import TopologyStore
from netlab import load_topology


class EducationApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_store = education.store
        self.previous_token = os.environ.get("NETLAB_BOOTSTRAP_TOKEN")
        os.environ["NETLAB_BOOTSTRAP_TOKEN"] = "test-setup-secret"
        education.store = EducationStore(Path(self.tempdir.name) / "education.sqlite3")
        from backend.app import main
        self.main_module = main
        self.previous_topology_store = main.control.store
        main.control.store = TopologyStore(Path(self.tempdir.name) / "topologies")
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        education.store = self.previous_store
        self.main_module.control.store = self.previous_topology_store
        if self.previous_token is None:
            os.environ.pop("NETLAB_BOOTSTRAP_TOKEN", None)
        else:
            os.environ["NETLAB_BOOTSTRAP_TOKEN"] = self.previous_token
        self.tempdir.cleanup()

    def csrf_headers(self, client):
        return {"X-Netlab-CSRF": client.cookies.get("netlab_csrf", "")}

    def test_postgres_connection_translates_sqlite_placeholders_and_collation(self):
        class FakeConnection:
            statement = ""
            parameters = ()

            def execute(self, statement, parameters):
                self.statement = statement
                self.parameters = parameters

        connection = FakeConnection()
        DatabaseConnection(connection, postgres=True).execute(
            "SELECT id FROM users WHERE email=? ORDER BY display_name COLLATE NOCASE",
            ("teacher@example.test",),
        )
        self.assertEqual(
            connection.statement,
            "SELECT id FROM users WHERE email=%s ORDER BY lower(display_name)",
        )
        self.assertEqual(connection.parameters, ("teacher@example.test",))

    def test_educational_flow_is_authenticated_and_student_cannot_deploy(self):
        topology = load_topology(Path(__file__).parent / "topology.json")
        state = self.client.get("/api/auth/state").json()
        self.assertFalse(state["has_users"])
        self.assertTrue(state["bootstrap_enabled"])

        response = self.client.post("/api/auth/bootstrap", json={
            "bootstrap_token": "wrong", "email": "teacher@example.test",
            "display_name": "Teacher", "password": "long-password-123",
        })
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/auth/bootstrap", json={
            "bootstrap_token": "test-setup-secret", "email": "teacher@example.test",
            "display_name": "Teacher", "password": "long-password-123",
        })
        self.assertEqual(response.status_code, 200, response.text)
        teacher_headers = self.csrf_headers(self.client)

        response = self.client.post("/api/education/users", headers=teacher_headers, json={
            "email": "student@example.test", "display_name": "Student", "password": "student-password-123",
        })
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post("/api/education/users", headers=teacher_headers, json={
            "email": "peer@example.test", "display_name": "Peer", "password": "peer-password-123",
        })
        self.assertEqual(response.status_code, 201, response.text)
        group_response = self.client.post("/api/education/groups", headers=teacher_headers, json={"name": "Class A"})
        self.assertEqual(group_response.status_code, 201, group_response.text)
        group_id = group_response.json()["group"]["id"]
        response = self.client.post(f"/api/education/groups/{group_id}/members", headers=teacher_headers, json={"email": "student@example.test"})
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(f"/api/education/groups/{group_id}/members", headers=teacher_headers, json={"email": "peer@example.test"})
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(f"/api/education/groups/{group_id}/assignments", headers=teacher_headers, json={
            "title": "Ping lab", "topology": topology,
            "instructions": "Configurez le client puis vérifiez la connectivité.",
            "criteria": ["Le client atteint le serveur", "La route est configurée"],
        })
        self.assertEqual(response.status_code, 201, response.text)

        student = TestClient(self.client.app)
        response = student.post("/api/auth/login", json={"email": "student@example.test", "password": "student-password-123"})
        self.assertEqual(response.status_code, 200, response.text)
        assignments = student.get("/api/education/my-assignments").json()["assignments"]
        self.assertEqual(len(assignments), 1)
        assignment_id = assignments[0]["id"]
        self.assertEqual(assignments[0]["topology"]["lab"], topology["lab"])
        self.assertEqual(assignments[0]["instructions"], "Configurez le client puis vérifiez la connectivité.")
        self.assertEqual(assignments[0]["criteria"], ["Le client atteint le serveur", "La route est configurée"])

        response = student.post(f"/api/education/my-assignments/{assignment_id}/clone", headers=self.csrf_headers(student), json={})
        self.assertEqual(response.status_code, 200, response.text)
        copied = response.json()["topology"]
        self.assertIn("-student-", copied["lab"])
        self.assertEqual(str(uuid.UUID(copied["laboratory_id"])), copied["laboratory_id"])
        peer = TestClient(self.client.app)
        response = peer.post("/api/auth/login", json={"email": "peer@example.test", "password": "peer-password-123"})
        self.assertEqual(response.status_code, 200, response.text)
        peer_assignment = peer.get("/api/education/my-assignments").json()["assignments"][0]
        self.assertEqual(peer_assignment["id"], assignment_id)
        peer_copy = peer.post(
            f"/api/education/my-assignments/{assignment_id}/clone",
            headers=self.csrf_headers(peer),
            json={},
        ).json()["topology"]
        self.assertNotEqual(copied["laboratory_id"], peer_copy["laboratory_id"])
        copied["nodes"][0]["interfaces"][0]["ipv4"] = "10.0.1.11/24"
        tampered_runtime = deepcopy(copied)
        tampered_runtime["nodes"][0]["command"] = ["sh", "-c", "unexpected command"]
        response = student.put(
            f"/api/education/my-assignments/{assignment_id}/topology",
            headers=self.csrf_headers(student),
            json={"topology": tampered_runtime},
        )
        self.assertEqual(response.status_code, 400, response.text)
        response = student.put(
            f"/api/education/my-assignments/{assignment_id}/topology",
            headers=self.csrf_headers(student),
            json={"topology": copied},
        )
        self.assertEqual(response.status_code, 200, response.text)
        persisted = student.get("/api/education/my-assignments").json()["assignments"][0]["topology"]
        self.assertEqual(persisted["laboratory_id"], copied["laboratory_id"])
        peer_persisted = peer.get("/api/education/my-assignments").json()["assignments"][0]["topology"]
        self.assertEqual(peer_persisted["nodes"][0]["position"]["x"], peer_copy["nodes"][0]["position"]["x"])
        self.assertNotEqual(peer_persisted["laboratory_id"], persisted["laboratory_id"])
        tampered = dict(copied)
        tampered["laboratory_id"] = "00000000-0000-0000-0000-000000000001"
        response = student.put(
            f"/api/education/my-assignments/{assignment_id}/topology",
            headers=self.csrf_headers(student),
            json={"topology": tampered},
        )
        self.assertEqual(response.status_code, 400, response.text)
        response = student.post("/api/up", headers=self.csrf_headers(student), json={})
        self.assertEqual(response.status_code, 403)

        from backend.app import main
        with patch.object(main, "build_orchestrator") as build:
            build.return_value.status.return_value = [{"name": "client-ubuntu", "state": "running"}]
            build.return_value.action.return_value = SimpleNamespace(ok=True, exit_code=0, output="runtime ok")
            build.return_value.terminal.return_value = SimpleNamespace(ok=True, exit_code=0, output="client-ubuntu")
            runtime = student.get(f"/api/education/my-assignments/{assignment_id}/runtime")
            self.assertEqual(runtime.status_code, 200, runtime.text)
            self.assertEqual(runtime.json()["status"], "stopped")
            deployed = student.post(
                f"/api/education/my-assignments/{assignment_id}/runtime/up",
                headers=self.csrf_headers(student),
                json={},
            )
            self.assertEqual(deployed.status_code, 200, deployed.text)
            self.assertEqual(deployed.json()["output"], "runtime ok")
            self.assertEqual(build.call_args.args[0]["laboratory_id"], copied["laboratory_id"])
            reset_while_running = student.post(
                f"/api/education/my-assignments/{assignment_id}/clone",
                headers=self.csrf_headers(student),
                json={},
            )
            self.assertEqual(reset_while_running.status_code, 409, reset_while_running.text)
            blocked_terminal = student.post(
                f"/api/education/my-assignments/{assignment_id}/runtime/nodes/not-my-node/terminal",
                headers=self.csrf_headers(student),
                json={"command": ["hostname"]},
            )
            self.assertEqual(blocked_terminal.status_code, 404)
            terminal = student.post(
                f"/api/education/my-assignments/{assignment_id}/runtime/nodes/client-ubuntu/terminal",
                headers=self.csrf_headers(student),
                json={"command": ["hostname"]},
            )
            self.assertEqual(terminal.status_code, 200, terminal.text)
            stopped = student.post(
                f"/api/education/my-assignments/{assignment_id}/runtime/down",
                headers=self.csrf_headers(student),
                json={},
            )
            self.assertEqual(stopped.status_code, 200, stopped.text)
            reset = student.post(
                f"/api/education/my-assignments/{assignment_id}/clone",
                headers=self.csrf_headers(student),
                json={},
            )
            self.assertEqual(reset.status_code, 200, reset.text)
            redeployed = student.post(
                f"/api/education/my-assignments/{assignment_id}/runtime/up",
                headers=self.csrf_headers(student),
                json={},
            )
            self.assertEqual(redeployed.status_code, 200, redeployed.text)
            student_id = student.get("/api/auth/me").json()["user"]["id"]
            with education.store._connect() as db:
                db.execute(
                    "UPDATE student_lab_runtime SET expires_at=?,updated_at=? "
                    "WHERE assignment_id=? AND user_id=?",
                    (0, 0, assignment_id, student_id),
                )
            main.expire_laboratories()
            expired_runtime = student.get(f"/api/education/my-assignments/{assignment_id}/runtime")
            self.assertEqual(expired_runtime.status_code, 410)
            reset_expired = student.post(
                f"/api/education/my-assignments/{assignment_id}/clone",
                headers=self.csrf_headers(student),
                json={},
            )
            self.assertEqual(reset_expired.status_code, 200, reset_expired.text)

        response = self.client.get(f"/api/education/groups/{group_id}/submissions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["submissions"]), 2)
        response = student.post(
            f"/api/education/my-assignments/{assignment_id}/submit",
            headers=self.csrf_headers(student),
            json={},
        )
        self.assertEqual(response.status_code, 200, response.text)
        student_history = student.get(f"/api/education/my-assignments/{assignment_id}/submissions")
        self.assertEqual(student_history.status_code, 200, student_history.text)
        self.assertEqual(len(student_history.json()["submissions"]), 1)
        self.assertEqual(student_history.json()["submissions"][0]["topology"]["laboratory_id"], copied["laboratory_id"])
        self.assertEqual(peer.get(f"/api/education/my-assignments/{assignment_id}/submissions").json()["submissions"], [])
        teacher_submissions = self.client.get(f"/api/education/groups/{group_id}/submissions").json()["submissions"]
        submitted = next(item for item in teacher_submissions if item["email"] == "student@example.test")
        self.assertEqual(submitted["status"], "submitted")
        self.assertEqual(submitted["attempt_count"], 1)
        teacher_history_url = f"/api/education/assignments/{assignment_id}/students/{student.get('/api/auth/me').json()['user']['id']}/submissions"
        teacher_history = self.client.get(teacher_history_url)
        self.assertEqual(teacher_history.status_code, 200, teacher_history.text)
        submission_id = teacher_history.json()["submissions"][0]["id"]
        reviewed = self.client.post(
            f"/api/education/assignments/{assignment_id}/students/{student.get('/api/auth/me').json()['user']['id']}/submissions/{submission_id}/feedback",
            headers=teacher_headers,
            json={"feedback": "Bon travail, vérifiez également la route retour."},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(
            student.get(f"/api/education/my-assignments/{assignment_id}/submissions").json()["submissions"][0]["feedback"],
            "Bon travail, vérifiez également la route retour.",
        )
        response = student.post(
            f"/api/education/my-assignments/{assignment_id}/submit",
            headers=self.csrf_headers(student),
            json={},
        )
        self.assertEqual(response.status_code, 200, response.text)
        history_after_resubmit = student.get(f"/api/education/my-assignments/{assignment_id}/submissions").json()["submissions"]
        self.assertEqual([attempt["attempt"] for attempt in history_after_resubmit], [2, 1])
        self.assertIsNone(history_after_resubmit[0]["feedback"])
        self.assertEqual(history_after_resubmit[1]["feedback"], "Bon travail, vérifiez également la route retour.")
        self.assertEqual(
            peer.post(
                f"/api/education/assignments/{assignment_id}/students/{student.get('/api/auth/me').json()['user']['id']}/submissions/{submission_id}/feedback",
                headers=self.csrf_headers(peer),
                json={"feedback": "Unauthorized"},
            ).status_code,
            403,
        )
        peer.close()
        student.close()

    def test_private_api_requires_login_and_csrf(self):
        response = self.client.get("/api/topology")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/api/observability").status_code, 401)
        self.client.post("/api/auth/bootstrap", json={
            "bootstrap_token": "test-setup-secret", "email": "teacher@example.test",
            "display_name": "Teacher", "password": "long-password-123",
        })
        response = self.client.get("/api/services")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({service["id"] for service in response.json()["services"] if service["deployable"]}, {"nginx", "apache", "coredns", "postgresql", "mysql", "mongodb"})
        laboratory = self.client.get("/api/laboratories").json()["laboratories"][0]
        from backend.app.main import control
        sample = {
            "available": True,
            "active_lab_count": 1,
            "running_node_count": 2,
            "labs": [
                {"name": laboratory["name"], "laboratory_id": laboratory["id"], "running_count": 1},
                {"name": "another-owner-lab", "laboratory_id": "unshared", "running_count": 8},
            ],
            "nodes": [
                {"lab": laboratory["name"], "laboratory_id": laboratory["id"], "state": "running"},
                {"lab": "another-owner-lab", "laboratory_id": "unshared", "state": "running"},
            ],
            "networks": [
                {"lab": laboratory["name"], "laboratory_id": laboratory["id"]},
                {"lab": "another-owner-lab", "laboratory_id": "unshared"},
            ],
            "storage": [{"kind": "Images", "used_bytes": 100}],
            "alerts": [
                {"severity": "warning", "lab": laboratory["name"], "message": "own"},
                {"severity": "warning", "lab": "another-owner-lab", "message": "other"},
            ],
            "errors": ["global host error"],
            "events": [], "truncated": False,
            "thresholds": {"cpu_percent": 80, "memory_percent": 80, "writable_storage_mb": 1024},
        }
        with patch.object(control.orchestrator, "observability", return_value=sample):
            response = self.client.get("/api/observability")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["active_lab_count"], 1)
        self.assertEqual(len(response.json()["labs"]), 1)
        self.assertEqual(len(response.json()["nodes"]), 1)
        self.assertEqual(len(response.json()["networks"]), 1)
        self.assertEqual(response.json()["storage"], [])
        self.assertEqual([alert["lab"] for alert in response.json()["alerts"]], [laboratory["name"]])
        self.assertEqual(response.json()["errors"], [])
        response = self.client.post("/api/education/groups", json={"name": "No CSRF"})
        self.assertEqual(response.status_code, 403)

    def test_multiple_teacher_accounts_are_created_by_authenticated_teacher(self):
        created = self.client.post("/api/auth/bootstrap", json={
            "bootstrap_token": "test-setup-secret", "email": "owner@example.test",
            "display_name": "Owner", "password": "owner-password-123",
        })
        self.assertEqual(created.status_code, 200, created.text)
        payload = {
            "email": "colleague@example.test",
            "display_name": "Colleague",
            "password": "colleague-password-123",
        }
        guest = TestClient(self.client.app)
        self.assertEqual(guest.post("/api/education/teachers", json=payload).status_code, 401)
        guest.close()
        created_teacher = self.client.post(
            "/api/education/teachers",
            headers=self.csrf_headers(self.client),
            json=payload,
        )
        self.assertEqual(created_teacher.status_code, 201, created_teacher.text)
        self.assertEqual(created_teacher.json()["user"]["role"], "teacher")
        student_payload = {
            "email": "student@example.test",
            "display_name": "Student",
            "password": "student-password-123",
        }
        student_created = self.client.post(
            "/api/education/users",
            headers=self.csrf_headers(self.client),
            json=student_payload,
        )
        self.assertEqual(student_created.status_code, 201, student_created.text)
        colleague = TestClient(self.client.app)
        login = colleague.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(colleague.get("/api/auth/me").json()["user"]["role"], "teacher")
        colleague.close()
        student = TestClient(self.client.app)
        student_login = student.post(
            "/api/auth/login",
            json={"email": student_payload["email"], "password": student_payload["password"]},
        )
        self.assertEqual(student_login.status_code, 200, student_login.text)
        self.assertEqual(
            student.post(
                "/api/education/teachers",
                headers=self.csrf_headers(student),
                json={**payload, "email": "unauthorized@example.test"},
            ).status_code,
            403,
        )
        student.close()

    def test_local_admin_creates_teacher_only_after_confirmation(self):
        local_store = EducationStore(Path(self.tempdir.name) / "admin.sqlite3")
        output = io.StringIO()
        with (
            patch.object(admin, "store", local_store),
            patch("builtins.input", side_effect=[
                "recovery@example.test", "Recovery Teacher", "CREER",
            ]),
            patch("backend.app.admin.getpass.getpass", side_effect=[
                "recovery-password-123", "recovery-password-123",
            ]),
            redirect_stdout(output),
        ):
            self.assertEqual(admin.create_teacher(), 0)
        self.assertEqual(local_store.user_count(), 1)
        self.assertNotIn("recovery-password-123", output.getvalue())

    def test_login_attempts_are_throttled(self):
        from backend.app.education import login_throttle

        login_throttle._failures.clear()
        for _ in range(5):
            response = self.client.post("/api/auth/login", json={"email": "nobody@example.test", "password": "wrong-password"})
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/auth/login", json={"email": "nobody@example.test", "password": "wrong-password"})
        self.assertEqual(response.status_code, 429)
        login_throttle._failures.clear()

    def test_laboratory_records_are_scoped_and_roles_are_enforced(self):
        state = self.client.post("/api/auth/bootstrap", json={
            "bootstrap_token": "test-setup-secret", "email": "teacher@example.test",
            "display_name": "Teacher", "password": "long-password-123",
        })
        self.assertEqual(state.status_code, 200, state.text)
        teacher_headers = self.csrf_headers(self.client)
        topology = load_topology(Path(__file__).parent / "topology.json")

        initial = self.client.get("/api/laboratories")
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(len(initial.json()["laboratories"]), 1)
        default_topology = self.client.get("/api/topology").json()["topology"]
        self.assertEqual(default_topology["laboratory_id"], initial.json()["laboratories"][0]["id"])
        created = self.client.post("/api/laboratories", headers=teacher_headers, json={"topology": topology})
        self.assertEqual(created.status_code, 201, created.text)
        laboratory = created.json()["laboratory"]
        laboratory_id = laboratory["id"]
        self.assertEqual(created.json()["topology"]["laboratory_id"], laboratory_id)
        self.assertNotEqual(created.json()["topology"]["lab"], topology["lab"])
        self.assertNotEqual(created.json()["topology"]["lab"], default_topology["lab"])
        versions = self.client.get(f"/api/laboratories/{laboratory_id}/versions")
        self.assertEqual(versions.status_code, 200, versions.text)
        self.assertEqual(len(versions.json()["versions"]), 1)
        saved = self.client.put(
            f"/api/laboratories/{laboratory_id}/topology",
            headers=teacher_headers,
            json={"topology": created.json()["topology"]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        restored = self.client.post(
            f"/api/laboratories/{laboratory_id}/versions/1/restore",
            headers=teacher_headers,
            json={},
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        exported = self.client.get(f"/api/laboratories/{laboratory_id}/export")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(len(exported.json()["versions"]), 3)
        self.assertEqual(exported.json()["versions"][0]["reason"], "restore:1")

        with patch("backend.app.main.build_orchestrator") as build:
            build.return_value.action.return_value = SimpleNamespace(ok=True, exit_code=0, output="")
            deploy = self.client.post(
                f"/api/laboratories/{laboratory_id}/actions/up",
                headers=teacher_headers,
                json={},
            )
        self.assertEqual(deploy.status_code, 200, deploy.text)
        self.assertEqual(deploy.json()["action"], "up")
        self.assertEqual(self.client.get(f"/api/laboratories/{laboratory_id}").json()["laboratory"]["status"], "running")
        repeated_deploy = self.client.post(
            f"/api/laboratories/{laboratory_id}/actions/up",
            headers=teacher_headers,
            json={},
        )
        self.assertEqual(repeated_deploy.status_code, 409)

        other_teacher = education.store.create_user(
            "other-teacher@example.test", "Other teacher", "another-password-123", "teacher",
        )
        other = TestClient(self.client.app)
        other_login = other.post(
            "/api/auth/login",
            json={"email": other_teacher["email"], "password": "another-password-123"},
        )
        self.assertEqual(other_login.status_code, 200, other_login.text)
        other_topology = other.get("/api/topology").json()["topology"]
        self.assertNotEqual(other_topology["laboratory_id"], default_topology["laboratory_id"])
        self.assertEqual(other.get(f"/api/laboratories/{laboratory_id}").status_code, 404)
        self.assertEqual(other.get(f"/api/laboratories/{laboratory['name']}/export").status_code, 404)
        other.close()

        student_response = self.client.post("/api/education/users", headers=teacher_headers, json={
            "email": "viewer@example.test", "display_name": "Viewer", "password": "student-password-123",
        })
        self.assertEqual(student_response.status_code, 201, student_response.text)
        member_response = self.client.post(
            f"/api/laboratories/{laboratory_id}/members",
            headers=teacher_headers,
            json={"email": "viewer@example.test", "role": "viewer"},
        )
        self.assertEqual(member_response.status_code, 201, member_response.text)

        viewer = TestClient(self.client.app)
        login = viewer.post("/api/auth/login", json={"email": "viewer@example.test", "password": "student-password-123"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(viewer.get(f"/api/laboratories/{laboratory_id}").status_code, 200)
        update = viewer.put(
            f"/api/laboratories/{laboratory_id}/topology",
            headers=self.csrf_headers(viewer),
            json={"topology": created.json()["topology"]},
        )
        self.assertEqual(update.status_code, 403)
        deploy = viewer.post(
            f"/api/laboratories/{laboratory_id}/actions/up",
            headers=self.csrf_headers(viewer),
            json={},
        )
        self.assertEqual(deploy.status_code, 403)
        self.assertEqual(viewer.get("/api/laboratories").json()["laboratories"][0]["role"], "viewer")
        viewer.close()

    def test_laboratory_quotas_and_expiration_are_persisted(self):
        teacher = education.store.create_user(
            "quota@example.test", "Quota", "long-password-123", "teacher",
        )
        topology = load_topology(Path(__file__).parent / "topology.json")
        with patch.dict(os.environ, {
            "NETLAB_MAX_LABS_PER_USER": "1",
            "NETLAB_MAX_NODES_PER_LAB": "3",
            "NETLAB_LAB_TTL_HOURS": "1",
        }):
            laboratory = education.store.create_laboratory(teacher["id"], topology)
            self.assertEqual(laboratory["status"], "stopped")
            self.assertGreater(laboratory["expires_at"], laboratory["created_at"])
            with self.assertRaisesRegex(education.EducationError, "quota reached"):
                education.store.create_laboratory(teacher["id"], topology)
        with education.store._connect() as db:
            db.execute(
                "UPDATE laboratories SET status='running',expires_at=?,updated_at=? WHERE id=?",
                (0, 0, laboratory["id"]),
            )
        expired = education.store.expired_laboratories()
        self.assertEqual([item["id"] for item in expired], [laboratory["id"]])
        self.assertEqual(education.store.expired_laboratories(), [])
        with education.store._connect() as db:
            db.execute(
                "UPDATE laboratories SET updated_at=? WHERE id=?",
                (0, laboratory["id"]),
            )
        self.assertEqual(
            [item["id"] for item in education.store.expired_laboratories()],
            [laboratory["id"]],
        )

    def test_laboratory_versions_survive_reopening_the_database(self):
        teacher = education.store.create_user(
            "versions@example.test", "Versions", "long-password-123", "teacher",
        )
        topology = load_topology(Path(__file__).parent / "topology.json")
        laboratory = education.store.create_laboratory(teacher["id"], topology)
        education.store.save_laboratory_topology(
            laboratory["id"], teacher["id"], laboratory["topology"], reason="edit",
        )

        reopened = EducationStore(Path(self.tempdir.name) / "education.sqlite3")
        versions = reopened.list_laboratory_versions(laboratory["id"])
        self.assertEqual([version["version"] for version in versions], [2, 1])
        self.assertEqual(versions[0]["reason"], "edit")

    def test_laboratory_storage_quota_rejects_version_without_changing_current_topology(self):
        teacher = education.store.create_user(
            "storage@example.test", "Storage", "long-password-123", "teacher",
        )
        topology = load_topology(Path(__file__).parent / "topology.json")
        laboratory = education.store.create_laboratory(teacher["id"], topology)
        with education.store._connect() as db:
            db.execute(
                "UPDATE laboratory_versions SET topology_json=? WHERE laboratory_id=?",
                ("x" * (1024 * 1024), laboratory["id"]),
            )

        with patch.dict(os.environ, {"NETLAB_MAX_STORAGE_MB_PER_LAB": "1"}):
            with self.assertRaisesRegex(education.EducationError, "storage quota"):
                education.store.save_laboratory_topology(
                    laboratory["id"], teacher["id"], laboratory["topology"],
                )
        current = education.store.laboratory(laboratory["id"], teacher["id"])
        self.assertEqual(current["topology"], laboratory["topology"])
        self.assertEqual(len(education.store.list_laboratory_versions(laboratory["id"])), 1)

    def test_cpu_and_memory_quotas_are_enforced_before_running(self):
        teacher = education.store.create_user(
            "resources@example.test", "Resources", "long-password-123", "teacher",
        )
        topology = load_topology(Path(__file__).parent / "topology.json")
        with patch.dict(os.environ, {"NETLAB_MAX_CPU_CORES_PER_LAB": "2"}):
            with self.assertRaisesRegex(education.EducationError, "CPU quota"):
                education.store.create_laboratory(teacher["id"], topology)

        with patch.dict(os.environ, {
            "NETLAB_MAX_CPU_CORES_PER_LAB": "8",
            "NETLAB_MAX_RUNNING_CPU_CORES_PER_USER": "5",
            "NETLAB_MAX_RUNNING_MEMORY_MB_PER_USER": "8192",
            "NETLAB_MAX_RUNNING_LABS_PER_USER": "2",
        }):
            first = education.store.create_laboratory(teacher["id"], topology)
            second = education.store.create_laboratory(teacher["id"], topology)
            education.store.claim_laboratory_run(first["id"], teacher["id"])
            with self.assertRaisesRegex(education.EducationError, "CPU user quota"):
                education.store.claim_laboratory_run(second["id"], teacher["id"])

    def test_expiration_sweeper_cleans_expired_runtime(self):
        teacher = education.store.create_user(
            "expiry@example.test", "Expiry", "long-password-123", "teacher",
        )
        topology = load_topology(Path(__file__).parent / "topology.json")
        laboratory = education.store.create_laboratory(teacher["id"], topology)
        with education.store._connect() as db:
            db.execute(
                "UPDATE laboratories SET status='running',expires_at=?,updated_at=? WHERE id=?",
                (0, 0, laboratory["id"]),
            )
        from backend.app import main
        with patch.object(main, "build_orchestrator") as build:
            build.return_value.action.return_value = SimpleNamespace(ok=True, exit_code=0, output="")
            main.expire_laboratories()
        stored = education.store.laboratory(laboratory["id"], teacher["id"])
        self.assertEqual(stored["status"], "expired")


if __name__ == "__main__":
    unittest.main()
