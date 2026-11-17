import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.app.storage import TopologyStore
from netlab import load_topology


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.topology = load_topology(Path(__file__).parent / "topology.json")
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = TopologyStore(Path(self.tempdir.name))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_versions_are_immutable_and_listed_newest_first(self):
        self.store.save(self.topology)
        changed = copy.deepcopy(self.topology)
        changed["nodes"][0]["position"]["x"] = 300
        self.store.save(changed)
        versions = self.store.list_versions(self.topology["lab"])
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual(self.store.load(self.topology["lab"], 1)["nodes"][0]["position"]["x"], 120)

    def test_restore_creates_a_new_reproducible_version(self):
        self.store.save(self.topology)
        changed = copy.deepcopy(self.topology)
        changed["nodes"][0]["position"]["x"] = 300
        self.store.save(changed)
        restored = self.store.restore(self.topology["lab"], 1)
        self.assertEqual(restored["nodes"][0]["position"]["x"], 120)
        self.assertEqual(self.store.list_versions(self.topology["lab"])[0]["reason"], "restore:1")

    def test_clone_and_export(self):
        self.store.save(self.topology)
        clone = self.store.clone(self.topology["lab"], "copy-lab")
        self.assertEqual(clone["lab"], "copy-lab")
        exported = self.store.export("copy-lab")
        self.assertEqual(exported["format"], "netlab-laboratory-v1")
        self.assertEqual(exported["topology"]["lab"], "copy-lab")


if __name__ == "__main__":
    unittest.main()
