import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.education import EducationStore, EducationError
from backend.app.execution import LibvirtExecutionBackend, selected_execution_backend


class ExecutionPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EducationStore(Path(self.tempdir.name) / "education.sqlite3")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_libvirt_backend_is_explicitly_unimplemented(self):
        backend = LibvirtExecutionBackend({"nodes": []})
        with self.assertRaisesRegex(RuntimeError, "Tranche 5"):
            backend.action("up")
        with patch.dict(os.environ, {"NETLAB_EXECUTION_BACKEND": "libvirt"}):
            self.assertEqual(selected_execution_backend(), "libvirt")
        with patch.dict(os.environ, {"NETLAB_EXECUTION_BACKEND": "unknown"}):
            with self.assertRaisesRegex(RuntimeError, "docker or libvirt"):
                selected_execution_backend()

    def test_vm_resource_license_snapshot_and_console_guards(self):
        topology = {
            "nodes": [
                {
                    "name": "windows",
                    "backend": "libvirt",
                    "cpu_cores": 4,
                    "memory_mb": 8192,
                    "disk_gb": 80,
                    "license_id": "windows-server-2022",
                    "console": "rdp",
                },
            ],
        }
        resources = self.store.validate_vm_resources(topology, "lab-test")
        self.assertEqual(resources["cpu_cores"], 4)
        self.assertEqual(resources["memory_mb"], 8192)

        with self.assertRaisesRegex(EducationError, "missing"):
            self.store.verify_license_acceptances("user-test", topology)

        manifest = self.store.register_license(
            "windows-server-2022",
            "Windows Server 2022",
            "Microsoft",
            "https://www.microsoft.com/licensing/",
            expires_at=None,
        )
        self.assertEqual(manifest["license_id"], "windows-server-2022")

        with self.assertRaisesRegex(EducationError, "acceptance"):
            self.store.verify_license_acceptances("user-test", topology)

        snapshot = self.store.create_snapshot(
            "lab-test", "windows", "before-ad", "libvirt",
        )
        self.assertEqual(snapshot["status"], "pending")
        available = self.store.set_snapshot_status(snapshot["id"], "available")
        self.assertEqual(available["status"], "available")

    def test_vm_resource_limits_are_bounded(self):
        topology = {
            "nodes": [
                {
                    "name": "large-vm",
                    "backend": "libvirt",
                    "cpu_cores": 64,
                    "memory_mb": 65536,
                    "disk_gb": 1000,
                },
            ],
        }
        with patch.dict(
            os.environ,
            {
                "NETLAB_MAX_LIBVIRT_CPU_CORES_PER_LAB": "8",
                "NETLAB_MAX_LIBVIRT_MEMORY_MB_PER_LAB": "16384",
                "NETLAB_MAX_LIBVIRT_DISK_GB_PER_LAB": "200",
            },
        ):
            with self.assertRaisesRegex(EducationError, "libvirt quota"):
                self.store.validate_vm_resources(topology, "lab-large")


if __name__ == "__main__":
    unittest.main()
