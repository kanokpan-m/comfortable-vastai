"""Offline tests for the document store: key encryption (optional) and MongoDB sync."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from comfortable import config, crypto, store, workflowsync  # noqa: E402


def fresh_store():
    config.LOCAL_DB = Path(tempfile.mkdtemp()) / "test.db"
    return store.Store()


def set_passphrase(value):
    config.SECRET_KEY = value
    crypto._fernet = None


class KeyEncryption(unittest.TestCase):
    def tearDown(self):
        set_passphrase("")

    def test_unencrypted_by_default_and_says_so(self):
        st = fresh_store()
        st.update_settings({"hf_token": "hf_plain"})
        self.assertEqual(st.get("settings", "hf_token")["value"], "hf_plain")
        self.assertEqual(st.setting("hf_token"), "hf_plain")
        keys = st.status()["keys"]
        self.assertFalse(keys["encrypted"])
        self.assertIn("unencrypted", keys["message"])
        self.assertIn("on purpose", keys["message"])

    def test_passphrase_encrypts_stored_keys(self):
        set_passphrase("correct horse")
        st = fresh_store()
        st.update_settings({"civitai_token": "civ_secret", "concurrency": 4})
        stored = st.get("settings", "civitai_token")["value"]
        self.assertTrue(stored.startswith(crypto.PREFIX))
        self.assertNotIn("civ_secret", stored)
        self.assertEqual(st.setting("civitai_token"), "civ_secret")
        self.assertEqual(st.get("settings", "concurrency")["value"], 4)  # only keys are encrypted
        self.assertTrue(st.status()["keys"]["encrypted"])

    def test_keys_saved_before_the_passphrase_get_encrypted(self):
        st = fresh_store()
        st.update_settings({"hf_token": "hf_old"})
        set_passphrase("pw")
        st.encrypt_existing_keys()
        self.assertTrue(crypto.is_encrypted(st.get("settings", "hf_token")["value"]))
        self.assertEqual(st.setting("hf_token"), "hf_old")

    def test_missing_or_wrong_passphrase_reads_as_missing(self):
        set_passphrase("pw")
        st = fresh_store()
        st.update_settings({"hf_token": "hf_x"})
        for other in ("", "wrong"):
            set_passphrase(other)
            self.assertEqual(st.setting("hf_token"), "")
            self.assertEqual(st.status()["keys"]["unreadable"], ["hf_token"])

    def test_clearing_a_key(self):
        set_passphrase("pw")
        st = fresh_store()
        st.update_settings({"hf_token": "hf_x"})
        st.update_settings({"hf_token": ""})
        self.assertEqual(st.setting("hf_token"), "")


try:
    import mongomock
except ImportError:  # pip install mongomock
    mongomock = None


@unittest.skipIf(mongomock is None, "needs mongomock")
class Sync(unittest.TestCase):
    """Two instances sharing one (in-memory) MongoDB."""

    def setUp(self):
        self.mongo = mongomock.MongoClient()["test"]
        self.a, self.b = self.instance(), self.instance()

    def instance(self):
        st = fresh_store()
        st._connect = lambda: self.mongo
        return st

    def test_edit_reaches_the_other_instance(self):
        self.a.put("library", {"id": "1", "name": "lora"})
        self.a.sync(); self.b.sync()
        self.assertEqual(self.b.get("library", "1")["name"], "lora")
        self.assertEqual(self.mongo.library.find_one({"id": "1"})["_rev"], 1)
        self.assertNotIn("_rev", self.b.get("library", "1"))  # versions stay out of local records

    def test_incremental_pull_fetches_only_recent_changes(self):
        self.a.put("library", {"id": "1", "name": "one"}); self.a.sync(); self.b.sync()
        self.mongo.library.update_one({"id": "1"}, {"$set": {"name": "edited long ago", "_ts": 1.0}})
        self.b.sync()  # not full, and _ts is old: not fetched
        self.assertEqual(self.b.get("library", "1")["name"], "one")
        self.b._last_full = 0
        self.b.sync()  # the full pull catches it
        self.assertEqual(self.b.get("library", "1")["name"], "edited long ago")

    def test_newer_edit_wins_and_conflict_is_reported(self):
        self.a.put("bundles", {"id": "x", "name": "start"}); self.a.sync(); self.b.sync()
        self.a.put("bundles", {"id": "x", "name": "from a"})
        self.b.put("bundles", {"id": "x", "name": "from b (newer)"})
        self.a.sync()
        self.b.sync()  # b's base is stale, but b's edit is newer: b wins
        self.a.sync()
        self.assertEqual(self.mongo.bundles.find_one({"id": "x"})["name"], "from b (newer)")
        self.assertEqual(self.a.get("bundles", "x")["name"], "from b (newer)")
        self.assertIn("newer", self.b.conflicts[0]["outcome"])

    def test_older_edit_loses_and_takes_the_newer_copy(self):
        self.a.put("bundles", {"id": "x", "name": "start"}); self.a.sync(); self.b.sync()
        self.b.put("bundles", {"id": "x", "name": "from b (older)"})
        self.a.put("bundles", {"id": "x", "name": "from a (newer)"})
        self.a.sync(); self.b.sync()
        self.assertEqual(self.mongo.bundles.find_one({"id": "x"})["name"], "from a (newer)")
        self.assertEqual(self.b.get("bundles", "x")["name"], "from a (newer)")
        self.assertIn("another instance", self.b.conflicts[0]["outcome"])
        self.assertEqual(self.b.status()["pending_writes"], 0)

    def test_delete_spreads_without_a_full_pull(self):
        self.a.put("library", {"id": "1", "name": "one"}); self.a.sync(); self.b.sync()
        self.a.delete("library", "1"); self.a.sync()
        self.b.sync()
        self.assertIsNone(self.b.get("library", "1"))

    def test_records_from_older_dashboards_are_updated(self):
        self.mongo.library.insert_one({"id": "old", "name": "no version"})  # no _rev / _ts
        self.a.sync()
        self.a.put("library", {"id": "old", "name": "edited"}); self.a.sync()
        docs = list(self.mongo.library.find({"id": "old"}))
        self.assertEqual(len(docs), 1)
        self.assertEqual((docs[0]["name"], docs[0]["_rev"]), ("edited", 1))

    def test_edit_while_syncing_is_not_lost(self):
        self.a.put("library", {"id": "1", "name": "v1"})
        get = self.a.get
        def edit_during_push(coll, doc_id):
            doc = get(coll, doc_id)
            self.a.get = get
            self.a.put("library", {"id": "1", "name": "v2"})  # lands while v1 is being pushed
            return doc
        self.a.get = edit_during_push
        self.a.sync()
        self.assertEqual(self.a.status()["pending_writes"], 1)
        self.a.sync()
        self.assertEqual(self.mongo.library.find_one({"id": "1"})["name"], "v2")

    def test_writes_queued_by_the_previous_version_are_pushed(self):
        self.a.put("library", {"id": "1", "name": "queued"})
        with self.a._db:
            self.a._db.execute("UPDATE pending SET ts=NULL")  # older versions recorded no edit time
        self.a.sync()
        self.assertEqual(self.a.status()["pending_writes"], 0)
        self.assertEqual(self.mongo.library.find_one({"id": "1"})["name"], "queued")


@unittest.skipIf(mongomock is None, "needs mongomock")
class WorkflowSync(unittest.TestCase):
    """Two instances, each with its own ComfyUI folder, sharing one MongoDB."""

    def setUp(self):
        self.mongo = mongomock.MongoClient()["test"]
        self.dirs = {}
        self.a, self.b = self.instance("a"), self.instance("b")
        saved = config.COMFY_DIR, config.DATA_DIR
        self.addCleanup(lambda: (setattr(config, "COMFY_DIR", saved[0]), setattr(config, "DATA_DIR", saved[1])))

    def instance(self, name):
        st = fresh_store()
        st._connect = lambda: self.mongo
        self.dirs[name] = Path(tempfile.mkdtemp())
        return st

    def run_on(self, name):
        """Sync the store, run a workflow pass as that instance, push the result."""
        st = getattr(self, name)
        config.COMFY_DIR, config.DATA_DIR = self.dirs[name] / "ComfyUI", self.dirs[name] / "data"
        st._last_full = 0  # tests run within one second: always pull everything
        st.sync()
        changes = workflowsync.sync_once(st)
        st.sync()
        return changes

    def wf(self, name, path):
        return self.dirs[name] / "ComfyUI" / "user" / "default" / "workflows" / path

    def write(self, name, path, text):
        f = self.wf(name, path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def test_new_instance_gets_every_workflow(self):
        self.write("a", "flux.json", '{"v": 1}')
        self.write("a", "video/wan.json", '{"v": 2}')
        self.run_on("a")
        self.run_on("b")
        self.assertEqual(self.wf("b", "flux.json").read_text(), '{"v": 1}')
        self.assertEqual(self.wf("b", "video/wan.json").read_text(), '{"v": 2}')

    def test_edit_on_one_reaches_the_other(self):
        self.write("a", "x.json", "v1"); self.run_on("a"); self.run_on("b")
        self.write("b", "x.json", "v2"); self.run_on("b"); self.run_on("a")
        self.assertEqual(self.wf("a", "x.json").read_text(), "v2")

    def test_edits_on_both_keep_both(self):
        self.write("a", "x.json", "v1"); self.run_on("a"); self.run_on("b")
        self.write("a", "x.json", "from a"); self.write("b", "x.json", "from b")
        self.run_on("a"); self.run_on("b"); self.run_on("a")
        texts = {self.wf("b", "x.json").read_text(), self.wf("b", "x (from another instance).json").read_text()}
        self.assertEqual(texts, {"from a", "from b"})

    def test_delete_moves_the_other_copy_to_trash(self):
        self.write("a", "x.json", "v1"); self.run_on("a"); self.run_on("b")
        self.wf("a", "x.json").unlink(); self.run_on("a"); self.run_on("b")
        self.assertFalse(self.wf("b", "x.json").exists())
        self.assertTrue(list((self.dirs["b"] / "data" / "workflow-trash").rglob("x.json")))
        self.run_on("a")
        self.assertFalse(self.wf("a", "x.json").exists())  # not restored on the instance that deleted it

    def test_edit_after_delete_elsewhere_is_kept(self):
        self.write("a", "x.json", "v1"); self.run_on("a"); self.run_on("b")
        self.wf("a", "x.json").unlink(); self.run_on("a")
        self.write("b", "x.json", "edited"); self.run_on("b"); self.run_on("a")
        self.assertEqual(self.wf("a", "x.json").read_text(), "edited")

    def test_unchanged_pass_changes_nothing(self):
        self.write("a", "x.json", "v1"); self.run_on("a")
        self.assertEqual(self.run_on("a"), 0)


if __name__ == "__main__":
    unittest.main()
