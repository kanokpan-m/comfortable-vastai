"""Document store: a local SQLite copy, kept in sync with MongoDB Atlas in the background.

Collections (schema v2, same names in MongoDB and SQLite):
  settings  {id: <key>, value}
  library   saved models (v1 "favorites"), see sources.library_item()
  bundles   named groups of library items (v1 "groups")
  stars     starred gallery files {id: <relative path>}
  benchmarks  GPU value benchmark results (see bench.py)
  workflows   ComfyUI's saved workflows {id, path, data, hash, deleted} (see workflowsync.py)
  meta      {id: "schema", version}

Reads and writes only touch SQLite, so nothing a user does waits on the
network. A background thread pushes local writes to MongoDB and then pulls
what changed in MongoDB (the source of truth, shared by every instance) every
SYNC_INTERVAL seconds, straight after a write, or as soon as MongoDB reports a
change (change streams, where the server supports them).

Each MongoDB record carries _rev (bumped on every write) and _ts (when it was
edited). A write only applies on top of the version this instance last saw; if
another instance changed the record in between, the newer edit wins and the
conflict is reported instead of silently lost. Pulls fetch records with a recent
_ts plus deletion markers (collection "_deleted"); a full pull every FULL_SYNC
seconds also picks up writes from older dashboards, which set neither field.
The v1 collections ("favorites", "groups") are left untouched so older
dashboards keep working.
"""
import json
import re
import sqlite3
import threading
import time

from . import config, crypto
from .util import log, now

COLLECTIONS = ("settings", "library", "bundles", "stars", "meta", "benchmarks", "hosts", "workflows")
SCHEMA_VERSION = 2
SYNC_INTERVAL = 15
FULL_SYNC = 600          # seconds between full pulls
CLOCK_SKEW = 120         # incremental pulls look back this far, for clocks that disagree
TOMBSTONE_DAYS = 30
META = ("_rev", "_ts")
SECRET_KEYS = {"hf_token", "civitai_token", "discord_webhook"}
DEFAULT_SETTINGS = {
    "hf_token": "",
    "civitai_token": "",
    "discord_webhook": "",
    "concurrency": 3,
    "verify_hashes": True,
    "show_nsfw": False,
    "notify_downloads": True,
    "auto_stop_minutes": 0,   # 0 = never
    "auto_stop_action": "stop",  # or "destroy" (after backing up outputs and syncing workflows)
    "max_hours": 0,           # budget cap: act after this many hours, busy or not (0 = no cap)
    "max_spend": 0,           # budget cap in dollars since the instance started (0 = no cap)
    "backup_repo": "",        # Hugging Face dataset, e.g. "you/comfy-outputs"
    "backup_auto": False,     # back up after each finished ComfyUI job
    "sync_workflows": True,   # keep ComfyUI's saved workflows in the shared store (workflowsync.py)
}


class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._mongo = None
        self._mongo_error = ""
        self.on_change = None    # callback(collections: set) after a pull changed data
        self.on_conflict = None  # callback(conflict: dict) when two instances edited the same record
        self.conflicts = []      # the most recent conflicts, newest first
        self._last_pull = 0.0
        self._last_full = 0.0
        self._watching = False
        self._db = sqlite3.connect(config.LOCAL_DB, check_same_thread=False)
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS docs (coll TEXT, id TEXT, data TEXT, PRIMARY KEY (coll, id))")
            self._db.execute("CREATE TABLE IF NOT EXISTS pending (coll TEXT, id TEXT, op TEXT, PRIMARY KEY (coll, id))")
            # The MongoDB version each local record is based on.
            self._db.execute("CREATE TABLE IF NOT EXISTS revs (coll TEXT, id TEXT, rev INTEGER, PRIMARY KEY (coll, id))")
            if "ts" not in [r[1] for r in self._db.execute("PRAGMA table_info(pending)")]:
                self._db.execute("ALTER TABLE pending ADD COLUMN ts REAL")  # when the local edit was made

    # ---- local document API (never blocks on the network) ------------------------
    def all(self, coll):
        with self._lock:
            rows = self._db.execute("SELECT data FROM docs WHERE coll=?", (coll,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get(self, coll, doc_id):
        with self._lock:
            row = self._db.execute("SELECT data FROM docs WHERE coll=? AND id=?", (coll, str(doc_id))).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, coll, doc):
        doc = {k: v for k, v in doc.items() if k != "_id"}
        doc_id = str(doc["id"])
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO docs VALUES (?, ?, ?)", (coll, doc_id, json.dumps(doc)))
            self._db.execute("INSERT OR REPLACE INTO pending VALUES (?, ?, 'put', ?)", (coll, doc_id, time.time()))
        self._wake.set()
        return doc

    def delete(self, coll, doc_id):
        doc_id = str(doc_id)
        with self._lock, self._db:
            self._db.execute("DELETE FROM docs WHERE coll=? AND id=?", (coll, doc_id))
            self._db.execute("INSERT OR REPLACE INTO pending VALUES (?, ?, 'delete', ?)", (coll, doc_id, time.time()))
        self._wake.set()

    def status(self):
        with self._lock:
            pending = self._db.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
        return {"mongo_configured": bool(config.MONGO_URI), "mongo_connected": self._mongo is not None,
                "mongo_error": self._mongo_error, "pending_writes": pending, "live": self._watching,
                "conflicts": self.conflicts[:10], "keys": crypto.status(self.unreadable_keys())}

    # ---- settings -------------------------------------------------------------------
    def settings(self):
        values = dict(DEFAULT_SETTINGS)
        if config.DISCORD_WEBHOOK_ENV:
            values["discord_webhook"] = config.DISCORD_WEBHOOK_ENV
        for doc in self.all("settings"):
            value = doc.get("value")
            if doc["id"] in SECRET_KEYS:
                value = crypto.decrypt(value)
            if doc["id"] in values and value not in (None, ""):
                values[doc["id"]] = value
        return values

    def unreadable_keys(self):
        return sorted(d["id"] for d in self.all("settings")
                      if d["id"] in SECRET_KEYS and crypto.is_encrypted(d.get("value")) and crypto.decrypt(d["value"]) is None)

    def setting(self, key):
        return self.settings().get(key, DEFAULT_SETTINGS.get(key))

    def update_settings(self, changes):
        for key, value in changes.items():
            if key in DEFAULT_SETTINGS:
                self.put("settings", {"id": key, "value": crypto.encrypt(value) if key in SECRET_KEYS else value})

    def encrypt_existing_keys(self):
        """With a passphrase set, encrypt keys that were saved before it was."""
        if not crypto.enabled():
            return
        plain = {d["id"]: d["value"] for d in self.all("settings")
                 if d["id"] in SECRET_KEYS and d.get("value") and not crypto.is_encrypted(d["value"])}
        if plain:
            self.update_settings(plain)
            log.info("Encrypted %d saved key(s)", len(plain))

    # ---- MongoDB sync -----------------------------------------------------------------
    def _connect(self):
        if self._mongo is not None or not config.MONGO_URI:
            return self._mongo
        try:
            import certifi
            from pymongo import MongoClient
            client = MongoClient(config.MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000,
                                 connectTimeoutMS=5000, socketTimeoutMS=10000)
            client.admin.command("ping")
            self._mongo = client[config.MONGO_DB]
            self._mongo_error = ""
            self._ensure_indexes(self._mongo)
            log.info("MongoDB connected")
        except Exception as exc:
            self._mongo, self._mongo_error = None, str(exc)[:300]
            log.warning("MongoDB unavailable, working from the local copy: %s", exc)
        return self._mongo

    def sync(self):
        """Push pending local writes, then pull what changed in MongoDB."""
        db = self._connect()
        if db is None:
            return False
        try:
            self._push(db)
            changed = self._pull(db)
            if changed and self.on_change:
                self.on_change(changed)
            return True
        except Exception as exc:
            log.warning("MongoDB sync failed: %s", exc)
            self._mongo, self._mongo_error = None, str(exc)[:300]
            return False

    def _rev(self, coll, doc_id):
        row = self._db.execute("SELECT rev FROM revs WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
        return row[0] if row else 0

    def _push(self, db):
        with self._lock:
            pending = self._db.execute("SELECT coll, id, op, ts FROM pending").fetchall()
        for coll, doc_id, op, queued_ts in pending:
            ts = queued_ts or time.time()  # queued before edit times were recorded
            if op == "delete":
                db[coll].delete_one({"id": doc_id})
                db["_deleted"].replace_one({"id": f"{coll}:{doc_id}"}, {"id": f"{coll}:{doc_id}", "coll": coll,
                                                                         "doc_id": doc_id, "_ts": ts}, upsert=True)
                done = True
            else:
                done = self._push_doc(db, coll, doc_id, ts)
            if done:
                with self._lock, self._db:  # unless it was edited again meanwhile
                    self._db.execute("DELETE FROM pending WHERE coll=? AND id=? AND ts IS ?", (coll, doc_id, queued_ts))

    def _push_doc(self, db, coll, doc_id, ts):
        """Write one record on top of the version we last saw. False: try again next round."""
        doc = self.get(coll, doc_id)
        if doc is None:
            return True
        base = self._rev(coll, doc_id)
        # Records written by older dashboards have no _rev: they count as version 0.
        match = {"id": doc_id, "_rev": base if base else {"$in": [None, 0]}}
        if db[coll].replace_one(match, {**doc, "_rev": base + 1, "_ts": ts}).matched_count:
            self._set_rev(coll, doc_id, base + 1)
            return True
        current = db[coll].find_one({"id": doc_id}, {"_id": 0})
        if current is None:
            db[coll].insert_one({**doc, "_rev": base + 1, "_ts": ts})
            self._set_rev(coll, doc_id, base + 1)
            return True
        # Another instance changed it since we last pulled: the newer edit wins.
        theirs = current.get("_rev") or 0
        if (current.get("_ts") or 0) <= ts:
            if not db[coll].replace_one({"id": doc_id, "_rev": theirs or {"$in": [None, 0]}},
                                        {**doc, "_rev": theirs + 1, "_ts": ts}).matched_count:
                return False
            self._set_rev(coll, doc_id, theirs + 1)
            self._conflict(coll, doc, "kept the change made here (it was newer)")
        else:
            with self._lock, self._db:  # drop ours; the pull brings theirs
                self._db.execute("DELETE FROM revs WHERE coll=? AND id=?", (coll, doc_id))
                self._db.execute("INSERT OR REPLACE INTO docs VALUES (?, ?, ?)", (coll, doc_id, json.dumps(_strip(current))))
            self._set_rev(coll, doc_id, theirs)
            self._conflict(coll, doc, "kept a newer change made on another instance")
        return True

    def _set_rev(self, coll, doc_id, rev):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO revs VALUES (?, ?, ?)", (coll, doc_id, rev))

    def _conflict(self, coll, doc, outcome):
        c = {"collection": coll, "id": str(doc.get("id")), "name": doc.get("name") or doc.get("path") or str(doc.get("id")),
             "outcome": outcome, "at": now()}
        log.warning("Sync conflict on %s/%s: %s", coll, c["id"], outcome)
        self.conflicts = [c] + self.conflicts[:19]
        if self.on_conflict:
            self.on_conflict(c)

    def _pull(self, db):
        started = time.time()
        full = started - self._last_full > FULL_SYNC
        query = {} if full else {"_ts": {"$gt": self._last_pull - CLOCK_SKEW}}
        remote = {c: [d for d in db[c].find(query, {"_id": 0}) if "id" in d] for c in COLLECTIONS}
        deleted = [] if full else list(db["_deleted"].find(query, {"_id": 0}))
        changed = set()
        with self._lock, self._db:
            pending = {(c, i) for c, i in self._db.execute("SELECT coll, id FROM pending")}
            for coll, docs in remote.items():
                before = {i: d for i, d in self._db.execute("SELECT id, data FROM docs WHERE coll=?", (coll,))}
                after = {str(d["id"]): d for d in docs}
                if full:  # anything MongoDB no longer has was deleted elsewhere
                    for doc_id in set(before) - set(after) - {i for c, i in pending if c == coll}:
                        self._db.execute("DELETE FROM docs WHERE coll=? AND id=?", (coll, doc_id))
                        self._db.execute("DELETE FROM revs WHERE coll=? AND id=?", (coll, doc_id))
                        changed.add(coll)
                for doc_id, d in after.items():
                    if (coll, doc_id) in pending:
                        continue
                    data = json.dumps(_strip(d))
                    if before.get(doc_id) != data:
                        self._db.execute("INSERT OR REPLACE INTO docs VALUES (?, ?, ?)", (coll, doc_id, data))
                        changed.add(coll)
                    self._db.execute("INSERT OR REPLACE INTO revs VALUES (?, ?, ?)", (coll, doc_id, d.get("_rev") or 0))
            for t in deleted:
                coll, doc_id = t.get("coll"), str(t.get("doc_id"))
                recreated = any(str(d["id"]) == doc_id and (d.get("_ts") or 0) > (t.get("_ts") or 0) for d in remote.get(coll, []))
                if coll in COLLECTIONS and (coll, doc_id) not in pending and not recreated:
                    if self._db.execute("DELETE FROM docs WHERE coll=? AND id=?", (coll, doc_id)).rowcount:
                        changed.add(coll)
                    self._db.execute("DELETE FROM revs WHERE coll=? AND id=?", (coll, doc_id))
        self._last_pull = started
        if full:
            self._last_full = started
            db["_deleted"].delete_many({"_ts": {"$lt": started - TOMBSTONE_DAYS * 86400}})
        return changed

    def _watch(self):
        """Wake the sync as soon as MongoDB reports a change (needs a replica set, e.g. Atlas)."""
        while True:
            db = self._connect()
            if db is None:
                time.sleep(SYNC_INTERVAL)
                continue
            try:
                with db.watch() as stream:
                    self._watching = True
                    for _ in stream:
                        self._wake.set()
            except Exception as exc:
                self._watching = False
                log.info("MongoDB change notifications unavailable, polling every %d s (%s)", SYNC_INTERVAL, str(exc)[:120])
                return

    def _ensure_indexes(self, db):
        for coll in COLLECTIONS + ("_deleted",):
            for keys in ("id", "_ts"):
                try:
                    db[coll].create_index(keys)
                except Exception:
                    pass

    def start_sync_thread(self):
        def loop():
            while True:
                self._wake.wait(SYNC_INTERVAL)
                self._wake.clear()
                time.sleep(0.5)  # batch bursts of writes
                self.sync()
        threading.Thread(target=loop, daemon=True, name="mongo-sync").start()
        threading.Thread(target=self._watch, daemon=True, name="mongo-watch").start()

    # ---- v1 -> v2 migration -----------------------------------------------------------
    def migrate(self):
        meta = self.get("meta", "schema") or {}
        if meta.get("version", 1) >= SCHEMA_VERSION:
            return
        favorites, groups, settings = self._read_v1()
        if not self.all("library") and not self.all("bundles"):
            for g in groups:
                self.put("bundles", bundle_from_v1(g))
            for f in favorites:
                self.put("library", library_from_v1(f))
            log.info("Migrated %d favorites and %d groups to schema v2", len(favorites), len(groups))
        for key, value in settings.items():
            if key in SECRET_KEYS and value and not self.get("settings", key):
                self.put("settings", {"id": key, "value": crypto.encrypt(value)})
        self.put("meta", {"id": "schema", "version": SCHEMA_VERSION, "migrated_at": now()})
        self.sync()

    def _read_v1(self):
        db = self._connect()
        if db is not None:
            db = db.client[config.MONGO_V1_DB]
            try:
                favs = list(db["favorites"].find({}, {"_id": 0}))
                groups = []
                for g in db["groups"].find():
                    g["id"] = str(g.get("id") or g.get("_id"))
                    g.pop("_id", None)
                    groups.append(g)
                settings = {d["key"]: d.get("value") for d in db["settings"].find({"key": {"$exists": True}})}
                return favs, groups, settings
            except Exception as exc:
                log.warning("Could not read v1 data from MongoDB: %s", exc)
        if not config.LEGACY_DB.exists():
            return [], [], {}
        try:
            legacy = sqlite3.connect(config.LEGACY_DB)
            legacy.row_factory = sqlite3.Row
            favs = [dict(r) for r in legacy.execute("SELECT * FROM favorites")]
            groups = [dict(r) for r in legacy.execute("SELECT * FROM groups")]
            settings = {r["key"]: r["value"] for r in legacy.execute("SELECT key, value FROM settings")}
            return favs, groups, settings
        except Exception as exc:
            log.warning("Could not read legacy SQLite database: %s", exc)
            return [], [], {}


def _strip(doc):
    return {k: v for k, v in doc.items() if k not in META and k != "_id"}


def _as_list(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.startswith("["):
            try:
                return [str(v).strip() for v in json.loads(text) if str(v).strip()]
            except ValueError:
                pass
        return [v.strip() for v in text.split(",") if v.strip()]
    return []


def bundle_from_v1(g):
    return {"id": str(g["id"]), "name": g.get("name") or "Untitled", "icon": g.get("emoji") or "📁",
            "description": "", "created_at": now()}


def library_from_v1(f):
    url = (f.get("url") or "").strip()
    item = {
        "id": str(f.get("id")),
        "name": f.get("name") or f.get("filename") or "Untitled",
        "url": url,
        "source": "civitai" if "civitai." in url else "hf" if "huggingface.co" in url else "url",
        "category": config.normalize_category(f.get("category")),
        "filename": f.get("filename") or "",
        "size": int(f.get("total_bytes") or 0),
        "sha256": "",
        "preview": f.get("image_url") or "",
        "trigger_words": _as_list(f.get("trained_words")),
        "base_model": "",
        "page_url": "",
        "bundle_ids": _as_list(f.get("group_ids")),
        "auto_install": bool(f.get("auto_install")),
        "notes": "",
        "created_at": now(),
        "updated_at": now(),
    }
    m = re.search(r"(?:/api/download/models/|modelVersionId=)(\d+)", url)
    if m:
        item["civitai"] = {"version_id": int(m.group(1))}
    return item


store: Store | None = None


def init():
    """Open the local store, do a first sync and the v1 migration, start background sync."""
    global store
    store = Store()
    store.sync()
    try:
        store.migrate()
    except Exception as exc:
        log.exception("Schema migration failed: %s", exc)
    try:
        store.encrypt_existing_keys()
    except Exception as exc:
        log.exception("Could not encrypt saved keys: %s", exc)
    store.start_sync_thread()
    return store
