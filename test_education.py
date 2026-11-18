import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import education
from backend.app.education import EducationStore
from netlab import load_topology


class EducationApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_store = education.store
        self.previous_token = os.environ.get("NETLAB_BOOTSTRAP_TOKEN")
        os.environ["NETLAB_BOOTSTRAP_TOKEN"] = "test-setup-secret"
        education.store = EducationStore(Path(self.tempdir.name) / "education.sqlite3")
        from backend.app.main import app
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        education.store = self.previous_store
        if self.previous_token is None:
            os.environ.pop("NETLAB_BOOTSTRAP_TOKEN", None)
        else:
            os.environ["NETLAB_BOOTSTRAP_TOKEN"] = self.previous_token
        self.tempdir.cleanup()

    def csrf_headers(self, client):
        return {"X-Netlab-CSRF": client.cookies.get("netlab_csrf", "")}

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
        group_response = self.client.post("/api/education/groups", headers=teacher_headers, json={"name": "Class A"})
        self.assertEqual(group_response.status_code, 201, group_response.text)
        group_id = group_response.json()["group"]["id"]
        response = self.client.post(f"/api/education/groups/{group_id}/members", headers=teacher_headers, json={"email": "student@example.test"})
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(f"/api/education/groups/{group_id}/assignments", headers=teacher_headers, json={"title": "Ping lab", "topology": topology})
        self.assertEqual(response.status_code, 201, response.text)

        student = TestClient(self.client.app)
        response = student.post("/api/auth/login", json={"email": "student@example.test", "password": "student-password-123"})
        self.assertEqual(response.status_code, 200, response.text)
        assignments = student.get("/api/education/my-assignments").json()["assignments"]
        self.assertEqual(len(assignments), 1)
        assignment_id = assignments[0]["id"]
        self.assertEqual(assignments[0]["topology"]["lab"], topology["lab"])

        response = student.post(f"/api/education/my-assignments/{assignment_id}/clone", headers=self.csrf_headers(student), json={})
        self.assertEqual(response.status_code, 200, response.text)
        copied = response.json()["topology"]
        self.assertIn("-student-", copied["lab"])
        response = student.post("/api/up", headers=self.csrf_headers(student), json={})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(f"/api/education/groups/{group_id}/submissions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["submissions"][0]["status"], "in_progress")
        student.close()

    def test_private_api_requires_login_and_csrf(self):
        response = self.client.get("/api/topology")
        self.assertEqual(response.status_code, 401)
        self.client.post("/api/auth/bootstrap", json={
            "bootstrap_token": "test-setup-secret", "email": "teacher@example.test",
            "display_name": "Teacher", "password": "long-password-123",
        })
        response = self.client.get("/api/services")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({service["id"] for service in response.json()["services"] if service["deployable"]}, {"nginx", "apache"})
        response = self.client.post("/api/education/groups", json={"name": "No CSRF"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
