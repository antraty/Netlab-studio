import os
import subprocess
import unittest
from unittest.mock import patch

from backend.app.observability import collect_docker_observability


class ObservabilityTests(unittest.TestCase):
    def test_collects_read_only_global_metrics_and_threshold_alerts(self):
        container_id = "abc123def456"
        ps_row = "\t".join([
            container_id,
            "netlab-demo-web-1",
            "nginx:stable-alpine",
            "running",
            "Up 2 minutes",
            "io.netlab.studio.lab=demo,io.netlab.studio.cpu-cores=0.5,io.netlab.studio.pids=128",
            "netlab-demo-network",
            "127.0.0.1:8088->80/tcp",
            "1.5GB (virtual 1.6GB)",
        ])
        results = {
            "ps": subprocess.CompletedProcess([], 0, ps_row + "\n", ""),
            "stats": subprocess.CompletedProcess([], 0, "\t".join([
                container_id, "netlab-demo-web-1", "91.25%", "450MiB / 512MiB", "87.89%",
                "1.5MB / 2MiB", "5kB / 3kB",
            ]) + "\n", ""),
            "network": subprocess.CompletedProcess([], 0, "netlab-demo-network\tbridge\tlocal\tio.netlab.studio.lab=demo\n", ""),
            "system": subprocess.CompletedProcess([], 0, "Images\t4\t2\t1.25GB\t500MB (40%)\n", ""),
        }
        calls = []

        def docker(*args, capture=False):
            calls.append(args)
            self.assertTrue(capture)
            return results[args[0]]

        with patch.dict(os.environ, {
            "NETLAB_ALERT_CPU_PERCENT": "80",
            "NETLAB_ALERT_MEMORY_PERCENT": "80",
            "NETLAB_ALERT_WRITABLE_STORAGE_MB": "1024",
        }):
            snapshot = collect_docker_observability(docker)

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["active_lab_count"], 1)
        self.assertEqual(snapshot["running_node_count"], 1)
        self.assertEqual(snapshot["labs"][0]["name"], "demo")
        node = snapshot["nodes"][0]
        self.assertEqual(node["cpu_percent"], 91.25)
        self.assertEqual(node["memory_usage_bytes"], 450 * 1024 * 1024)
        self.assertEqual(node["memory_limit_bytes"], 512 * 1024 * 1024)
        self.assertEqual(node["memory_percent"], 87.89)
        self.assertEqual(node["writable_size_bytes"], 1_500_000_000)
        self.assertEqual(node["block_read_bytes"], 1_500_000)
        self.assertEqual(node["block_write_bytes"], 2 * 1024 * 1024)
        self.assertEqual(node["network_rx_bytes"], 5_000)
        self.assertEqual(node["network_tx_bytes"], 3_000)
        self.assertEqual(node["cpu_limit_cores"], 0.5)
        self.assertEqual(node["pids_limit"], 128)
        self.assertEqual(snapshot["networks"][0]["name"], "netlab-demo-network")
        self.assertEqual(snapshot["storage"][0]["used_bytes"], 1_250_000_000)
        self.assertEqual(snapshot["storage"][0]["reclaimable_bytes"], 500_000_000)
        self.assertEqual({alert["severity"] for alert in snapshot["alerts"]}, {"warning"})
        self.assertEqual([call[0] for call in calls], ["ps", "stats", "network", "system"])
        self.assertNotIn("run", [argument for call in calls for argument in call])

    def test_docker_unavailable_returns_error_snapshot_without_failing(self):
        def docker(*args, **kwargs):
            return subprocess.CompletedProcess([], 127, "", "Docker CLI missing")

        snapshot = collect_docker_observability(docker)
        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["nodes"], [])
        self.assertEqual(snapshot["alerts"][0]["severity"], "error")
        self.assertIn("Docker CLI missing", snapshot["errors"][0])

    def test_stopped_containers_count_in_inventory_but_not_active_lab_total(self):
        row = "\t".join([
            "abc123def456", "netlab-old-node", "ubuntu:24.04", "exited", "Exited (0) 1 hour ago",
            "io.netlab.studio.lab=old-lab", "netlab-old-network", "", "0B (virtual 72MB)",
        ])

        def docker(*args, **kwargs):
            if args[0] == "ps":
                return subprocess.CompletedProcess([], 0, row + "\n", "")
            if args[0] == "network":
                return subprocess.CompletedProcess([], 0, "", "")
            if args[0] == "system":
                return subprocess.CompletedProcess([], 0, "", "")
            self.fail("docker stats must be skipped when no container is running")

        snapshot = collect_docker_observability(docker)
        self.assertEqual(snapshot["active_lab_count"], 0)
        self.assertEqual(snapshot["running_node_count"], 0)
        self.assertEqual(snapshot["labs"][0]["node_count"], 1)
        self.assertEqual(snapshot["nodes"][0]["state"], "exited")


    def test_container_inventory_is_capped_at_one_hundred(self):
        rows = []
        for index in range(101):
            rows.append("\t".join([
                f"{index:012x}", f"netlab-cap-node-{index}", "ubuntu:24.04", "exited", "Exited (0)",
                "io.netlab.studio.lab=cap", "netlab-cap-network", "", "0B (virtual 72MB)",
            ]))

        def docker(*args, **kwargs):
            if args[0] == "ps":
                return subprocess.CompletedProcess([], 0, "\n".join(rows) + "\n", "")
            if args[0] == "network":
                return subprocess.CompletedProcess([], 0, "", "")
            if args[0] == "system":
                return subprocess.CompletedProcess([], 0, "", "")
            self.fail("docker stats must be skipped when containers are stopped")

        snapshot = collect_docker_observability(docker)
        self.assertTrue(snapshot["truncated"])
        self.assertEqual(len(snapshot["nodes"]), 100)
        self.assertTrue(any("100 premiers" in alert["message"] for alert in snapshot["alerts"]))


if __name__ == "__main__":
    unittest.main()
