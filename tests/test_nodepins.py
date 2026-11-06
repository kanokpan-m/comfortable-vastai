"""Offline tests for pinned custom node versions (a local git repo stands in for a node pack)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from comfortable import config, nodepins  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class NodePins(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        saved = config.COMFY_DIR, config.DATA_DIR
        self.addCleanup(lambda: (setattr(config, "COMFY_DIR", saved[0]), setattr(config, "DATA_DIR", saved[1])))
        config.COMFY_DIR, config.DATA_DIR = root / "ComfyUI", root / "data"
        nodepins.custom_nodes_dir().mkdir(parents=True)
        # An upstream node pack with two commits: v1 (pinned) and v2 (latest).
        self.upstream = root / "upstream-pack"
        self.upstream.mkdir()
        git(self.upstream, "init", "-q")
        (self.upstream / "nodes.py").write_text("VERSION = 1\n")
        (self.upstream / "requirements.txt").write_text("certifi\n")  # already installed: nothing to change
        git(self.upstream, "add", "-A"); git(self.upstream, "commit", "-qm", "v1")
        self.v1 = git(self.upstream, "rev-parse", "HEAD")
        (self.upstream / "nodes.py").write_text("VERSION = 2\n")
        git(self.upstream, "commit", "-qam", "v2")
        self.pin = {"dir": "ComfyUI-Test", "repository": str(self.upstream), "commit": self.v1}
        nodepins._cache.clear()

    def test_pins_record_the_commit_each_pack_is_at(self):
        git(nodepins.custom_nodes_dir(), "clone", "-q", str(self.upstream), "ComfyUI-Test")
        nodepins._cache["node_modules"] = (1e18, {"TestNode": "ComfyUI-Test", "OtherNode": "ComfyUI-Test"})
        pins = nodepins.pins_for(["TestNode", "OtherNode", "KSampler"])  # KSampler is core: not pinned
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]["dir"], "ComfyUI-Test")
        self.assertEqual(pins[0]["commit"], git(self.upstream, "rev-parse", "HEAD"))
        self.assertEqual(pins[0]["repository"], str(self.upstream))

    def test_missing_pack_is_installed_at_the_pinned_commit(self):
        status = nodepins.install_pinned(self.pin)
        self.assertEqual(status, "installed, restart ComfyUI")
        folder = nodepins.custom_nodes_dir() / "ComfyUI-Test"
        self.assertEqual((folder / "nodes.py").read_text(), "VERSION = 1\n")
        self.assertEqual(git(folder, "rev-parse", "HEAD"), self.v1)

    def test_installed_pack_at_another_version_is_left_alone(self):
        git(nodepins.custom_nodes_dir(), "clone", "-q", str(self.upstream), "ComfyUI-Test")
        status = nodepins.install_pinned(self.pin)
        self.assertIn("another version", status)
        self.assertEqual((nodepins.custom_nodes_dir() / "ComfyUI-Test" / "nodes.py").read_text(), "VERSION = 2\n")
        self.assertEqual(nodepins.install_pinned({**self.pin, "commit": git(self.upstream, "rev-parse", "HEAD")}),
                         "installed at the pinned version")

    def test_pack_that_would_change_torch_is_held_back(self):
        fake = {"changes": [], "critical": [{"name": "torch", "installed": "2.10.0", "wanted": "2.4.1", "critical": True}], "error": ""}
        real = nodepins.check_requirements
        nodepins.check_requirements = lambda text: fake
        self.addCleanup(setattr, nodepins, "check_requirements", real)
        status = nodepins.install_pinned(self.pin)
        self.assertIn("held back", status)
        self.assertIn("torch 2.10.0 → 2.4.1", status)
        self.assertFalse((nodepins.custom_nodes_dir() / "ComfyUI-Test").exists())
        self.assertFalse(list(nodepins.custom_nodes_dir().glob(".*")))  # no half-cloned folder left

    def test_requirement_changes_from_pip_report(self):
        report = {"install": [{"metadata": {"name": "torch", "version": "2.4.1"}},
                              {"metadata": {"name": "Some_Lib", "version": "2.0"}},
                              {"metadata": {"name": "new-lib", "version": "1.0"}}]}
        changes = nodepins.changes_from_report(report, {"torch": "2.10.0", "some-lib": "1.5"})
        self.assertEqual([(c["name"], c["critical"]) for c in changes], [("torch", True), ("some-lib", False)])

    def test_satisfied_requirements_change_nothing(self):
        check = nodepins.check_requirements("certifi\n# comment\n")
        self.assertEqual((check["changes"], check["critical"], check["error"]), ([], [], ""))


if __name__ == "__main__":
    unittest.main()
