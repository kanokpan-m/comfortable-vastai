"""Offline tests of the v3 store: push, incremental pull, tombstones, full sync, local upgrade.

Two Store instances (two "Vast instances") share one in-memory fake of the MongoDB database.
Run: COMFORTABLE_WORKSPACE=<tmp> python -m unittest tests/test_store.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))

from comfortable import config, store as store_mod  # noqa: E402


def _match(doc, query):
    for key, cond in query.items():
        value = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$exists" and (key in doc) != arg:
                    return False
                if op == "$gt" and not (value is not None and value > arg):
                    return False
                if op == "$lt" and not (value is not None and value < arg):
                    return False
                if op == "$in" and value not in arg:
                    return False
                if op == "$nin" and value in arg:
                    return False
                if op == "$ne" and value == arg:
                    return False
        elif value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def create_index(self, *a, **k):
        return "ok"

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs.values():
            if _match(d, query or {}):
                d = json.loads(json.dumps(d))
                if projection and any(v == 1 for v in projection.values()):
                    d = {k: v for k, v in d.items() if projection.get(k) == 1}
                out.append(d)
        return out

    def find_one(self, query=None, projection=None):
        found = self.find(query, projection)
        return found[0] if found else None

    def replace_one(self, flt, doc, upsert=False):
        if flt["id"] in self.docs or upsert:
            self.docs[flt["id"]] = json.loads(json.dumps(doc))

    def bulk_write(self, ops, ordered=True):
        for op in ops:
            self.replace_one(op._filter, op._doc, op._upsert)

    def delete_many(self, query):
        for k in [k for k, d in self.docs.items() if _match(d, query)]:
            del self.docs[k]

    def count_documents(self, query):
        return len(self.find(query))


class FakeDB(dict):
    def __missing__(self, key):
        self[key] = FakeCollection()
        return self[key]

    def __getattr__(self, name):
        return self[name]


def make_store(db, path):
    s = store_mod.Store(path)
    s._connect = lambda: db  # noqa: SLF001 - talk to the fake database
    return s


class StoreSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = FakeDB()
        self.a = make_store(self.db, os.path.join(self.tmp, "a.db"))
        self.b = make_store(self.db, os.path.join(self.tmp, "b.db"))

    def test_put_is_pushed_with_version_and_mtime(self):
        self.a.put("bundles", {"id": "b1", "name": "krea2"})
        self.assertTrue(self.a.sync(full=False))
        remote = self.db["bundles"].docs["b1"]
        self.assertEqual((remote["v"], remote["name"], remote["origin"]), (3, "krea2", "user"))
        self.assertGreater(remote["mtime"], 0)
        self.assertEqual(self.a.status()["pending_writes"], 0)

    def test_other_instance_sees_changes_incrementally(self):
        self.a.put("library", {"id": "m1", "name": "LUSTIFY", "url": "https://civitai.com/api/download/models/1", "category": "unet",
                               "filename": "lustify.safetensors"})
        self.a.sync(full=False)
        self.b.sync(full=False)
        got = self.b.get("library", "m1")
        self.assertEqual(got["category"], "diffusion_models")  # unet is stored as the folder ComfyUI really uses
        self.assertEqual(got["civitai"], {"version_id": 1})

    def test_delete_travels_as_tombstone(self):
        self.a.put("bundles", {"id": "b2", "name": "gone soon"})
        self.a.sync(full=False)
        self.b.sync(full=False)
        self.assertIsNotNone(self.b.get("bundles", "b2"))
        self.a.delete("bundles", "b2")
        self.a.sync(full=False)
        self.assertTrue(self.db["bundles"].docs["b2"]["deleted"])
        self.b.sync(full=False)
        self.assertIsNone(self.b.get("bundles", "b2"))
        self.assertNotIn("b2", [d["id"] for d in self.b.all("bundles")])

    def test_full_sync_drops_what_the_database_no_longer_has(self):
        self.b.put("stars", {"id": "x.png"})
        self.b.sync(full=False)
        del self.db["stars"].docs["x.png"]  # removed by hand in MongoDB
        self.b.sync(full=True)
        self.assertIsNone(self.b.get("stars", "x.png"))

    def test_full_sync_keeps_unpushed_local_writes(self):
        self.b.put("stars", {"id": "y.png"})
        saved = self.b._push
        self.b._push = lambda db: None  # this round can't push
        self.b.sync(full=True)
        self.b._push = saved
        self.assertIsNotNone(self.b.get("stars", "y.png"))
        self.b.sync(full=False)
        self.assertIn("y.png", self.db["stars"].docs)

    def test_write_during_push_is_not_lost(self):
        self.a.put("bundles", {"id": "b3", "name": "first"})
        real = self.db["bundles"].bulk_write

        def slow_write(ops, ordered=True):
            real(ops, ordered)
            self.a.put("bundles", {"id": "b3", "name": "second"})  # changed again while pushing
        self.db["bundles"].bulk_write = slow_write
        self.a.sync(full=False)
        self.db["bundles"].bulk_write = real
        self.assertEqual(self.a.status()["pending_writes"], 1)
        self.a.sync(full=False)
        self.assertEqual(self.db["bundles"].docs["b3"]["name"], "second")

    def test_old_tombstones_are_purged_on_full_sync(self):
        self.db["hosts"].docs["old"] = {"id": "old", "deleted": True, "mtime": time.time() - 40 * 86400}
        self.a.sync(full=True)
        self.assertNotIn("old", self.db["hosts"].docs)

    def test_settings_round_trip(self):
        self.a.update_settings({"show_nsfw": True, "civitai_token": "abc", "not_a_setting": 1})
        self.a.sync(full=False)
        self.b.sync(full=False)
        self.assertTrue(self.b.settings()["show_nsfw"])
        self.assertEqual(self.b.setting("civitai_token"), "abc")
        self.assertNotIn("not_a_setting", self.b.settings())


class LocalUpgrade(unittest.TestCase):
    def test_v2_local_copy_is_normalised(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE docs (coll TEXT, id TEXT, data TEXT, PRIMARY KEY (coll, id))")
        db.execute("CREATE TABLE pending (coll TEXT, id TEXT, op TEXT, PRIMARY KEY (coll, id))")
        db.execute("INSERT INTO docs VALUES ('library', 'm', ?)", (json.dumps(
            {"id": "m", "name": "Krea 2 TE", "url": "https://huggingface.co/x/y/resolve/main/te.safetensors", "category": "clip",
             "filename": "te.safetensors", "size": "5"}),))
        db.commit()
        db.close()
        s = store_mod.Store(path)
        doc = s.get("library", "m")
        self.assertEqual((doc["category"], doc["size"], doc["source"], doc["v"]), ("text_encoders", 5, "hf", 3))
        self.assertEqual(doc["bundle_ids"], [])
        self.assertTrue(config.same_folder("clip", "text_encoders"))


if __name__ == "__main__":
    unittest.main()
