"""Document store: a local SQLite copy of the shared MongoDB database, synced in the background.

Schema v3, described in docs/database.md. One MongoDB database (COMFORTABLE_MONGO_DB, default
"comfortable") holds:

  user data, written here      settings, library, bundles, stars, benchmarks, hosts
  curated data, read here      catalog_categories, catalog_packs, catalog_workflows
                               (the "Suggested by AI" catalog, published with tools/catalog.py)
  meta                         {id: "schema", version: 3}, {id: "catalog", version, ...}

Every document has id (unique), v (schema version) and mtime (epoch seconds of its last write).
A delete leaves a tombstone {id, deleted: true, mtime} in MongoDB so every other instance drops
the document too; tombstones are purged after TOMBSTONE_DAYS.

Reads and writes only touch SQLite, so nothing a user does waits on the network. A background
thread pushes pending local writes, then pulls only the documents whose mtime moved past the last
pull (minus OVERLAP seconds, for clock skew between instances), every SYNC_INTERVAL seconds or
right after a write. A full check (ids and mtimes only, then the documents that differ) runs at
start and every FULL_SYNC_EVERY seconds, and drops local copies the database no longer has.
"""
import json
import sqlite3
import threading
import time

from . import config, schema
from .util import log

USER_COLLECTIONS = ("settings", "library", "bundles", "stars", "benchmarks", "hosts")
CATALOG_COLLECTIONS = ("catalog_categories", "catalog_packs", "catalog_workflows")
COLLECTIONS = USER_COLLECTIONS + CATALOG_COLLECTIONS + ("meta",)
SYNC_INTERVAL = 15
FULL_SYNC_EVERY = 1800
OVERLAP = 300
TOMBSTONE_DAYS = 30
FETCH_CHUNK = 500
INDEXES = {"library": ("bundle_ids", "category", "origin"), "bundles": ("origin",),
           "catalog_packs": ("categories",), "catalog_workflows": ("categories",)}
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
    "backup_repo": "",        # Hugging Face dataset, e.g. "you/comfy-outputs"
    "backup_auto": False,     # back up after each finished ComfyUI job
}


class Store:
    def __init__(self, path=None):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._mongo = None
        self._mongo_error = ""
        self._prepared = False      # indexes and schema marker checked on this connection
        self._last_full = 0.0
        self._last_sync = 0.0
        self.on_change = None       # callback(collections: set) after a pull changed data
        self._db = sqlite3.connect(path or config.LOCAL_DB, check_same_thread=False)
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS docs (coll TEXT, id TEXT, data TEXT, PRIMARY KEY (coll, id))")
            self._db.execute("CREATE TABLE IF NOT EXISTS pending (coll TEXT, id TEXT, op TEXT, PRIMARY KEY (coll, id))")
            self._db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
            for table, column, kind in (("docs", "mtime", "REAL DEFAULT 0"), ("pending", "seq", "INTEGER DEFAULT 0")):
                if column not in {r[1] for r in self._db.execute(f"PRAGMA table_info({table})")}:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        self._upgrade_local()

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
        doc = schema.normalize(coll, doc)
        doc["mtime"] = time.time()
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO docs (coll, id, data, mtime) VALUES (?, ?, ?, ?)",
                             (coll, doc["id"], json.dumps(doc), doc["mtime"]))
            self._db.execute("INSERT OR REPLACE INTO pending (coll, id, op, seq) VALUES (?, ?, 'put', ?)",
                             (coll, doc["id"], time.time_ns()))
        self._wake.set()
        return doc

    def delete(self, coll, doc_id):
        doc_id = str(doc_id)
        with self._lock, self._db:
            self._db.execute("DELETE FROM docs WHERE coll=? AND id=?", (coll, doc_id))
            self._db.execute("INSERT OR REPLACE INTO pending (coll, id, op, seq) VALUES (?, ?, 'delete', ?)",
                             (coll, doc_id, time.time_ns()))
        self._wake.set()

    def status(self):
        with self._lock:
            pending = self._db.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
        return {"mongo_configured": bool(config.MONGO_URI), "mongo_connected": self._mongo is not None,
                "mongo_error": self._mongo_error, "pending_writes": pending, "schema": schema.VERSION,
                "database": config.MONGO_DB if config.MONGO_URI else "", "last_sync": int(self._last_sync)}

    def _state(self, key, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def _set_state(self, key, value):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, str(value)))

    def _upgrade_local(self):
        """Bring a local copy written by an older dashboard to the v3 document shapes."""
        if self._state("schema") == str(schema.VERSION):
            return
        with self._lock, self._db:
            rows = self._db.execute("SELECT coll, id, data FROM docs").fetchall()
            for coll, doc_id, data in rows:
                doc = schema.normalize(coll, json.loads(data))
                self._db.execute("UPDATE docs SET data=?, mtime=? WHERE coll=? AND id=?",
                                 (json.dumps(doc), doc.get("mtime") or 0, coll, doc_id))
            self._db.execute("DELETE FROM state WHERE key LIKE 'cursor:%'")  # pull everything again
        self._set_state("schema", schema.VERSION)
        if rows:
            log.info("Local store upgraded to schema v%d (%d documents)", schema.VERSION, len(rows))

    # ---- settings -------------------------------------------------------------------
    def settings(self):
        values = dict(DEFAULT_SETTINGS)
        if config.DISCORD_WEBHOOK_ENV:
            values["discord_webhook"] = config.DISCORD_WEBHOOK_ENV
        for doc in self.all("settings"):
            if doc["id"] in values and doc.get("value") not in (None, ""):
                values[doc["id"]] = doc["value"]
        return values

    def setting(self, key):
        return self.settings().get(key, DEFAULT_SETTINGS.get(key))

    def update_settings(self, changes):
        for key, value in changes.items():
            if key in DEFAULT_SETTINGS:
                self.put("settings", {"id": key, "value": value})

    # ---- MongoDB sync -----------------------------------------------------------------
    def _connect(self):
        if self._mongo is not None or not config.MONGO_URI:
            return self._mongo
        try:
            import certifi
            from pymongo import MongoClient
            client = MongoClient(config.MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000,
                                 connectTimeoutMS=5000, socketTimeoutMS=20000)
            client.admin.command("ping")
            self._mongo = client[config.MONGO_DB]
            self._mongo_error, self._prepared = "", False
            log.info("MongoDB connected (database %s)", config.MONGO_DB)
        except Exception as exc:
            self._mongo, self._mongo_error = None, str(exc)[:300]
            log.warning("MongoDB unavailable, working from the local copy: %s", exc)
        return self._mongo

    def _prepare(self, db):
        """Indexes and the schema marker, once per connection."""
        for coll in COLLECTIONS:
            try:
                db[coll].create_index("id", unique=True, name="id_unique")
                db[coll].create_index("mtime", name="mtime")
                for field in INDEXES.get(coll, ()):
                    db[coll].create_index(field, name=field)
            except Exception as exc:
                log.warning("MongoDB index on %s not created: %s", coll, exc)
        marker = db.meta.find_one({"id": "schema"}, {"_id": 0}) or {}
        if not marker:
            db.meta.replace_one({"id": "schema"}, {"id": "schema", "version": schema.VERSION, "v": schema.VERSION,
                                                   "mtime": time.time()}, upsert=True)
        elif (marker.get("version") or 0) > schema.VERSION:
            log.warning("Database schema v%s is newer than this dashboard (v%d): update Comfortable",
                        marker.get("version"), schema.VERSION)
        self._prepared = True

    def sync(self, full=None):
        """Push pending local writes, then pull what changed. Returns False when offline."""
        db = self._connect()
        if db is None:
            return False
        try:
            if not self._prepared:
                self._prepare(db)
            full = (time.time() - self._last_full > FULL_SYNC_EVERY) if full is None else full
            self._push(db)
            changed = self._pull(db, full)
            if full:
                self._last_full = time.time()
                cutoff = time.time() - TOMBSTONE_DAYS * 86400
                for coll in COLLECTIONS:
                    db[coll].delete_many({"deleted": True, "mtime": {"$lt": cutoff}})
            self._last_sync = time.time()
            if changed and self.on_change:
                self.on_change(changed)
            return True
        except Exception as exc:
            log.warning("MongoDB sync failed: %s", exc)
            self._mongo, self._mongo_error = None, str(exc)[:300]
            return False

    def _push(self, db):
        from pymongo import ReplaceOne
        with self._lock:
            pending = self._db.execute("SELECT coll, id, op, seq FROM pending").fetchall()
        by_coll = {}
        for coll, doc_id, op, seq in pending:
            if op == "delete":
                doc = {"id": doc_id, "deleted": True, "v": schema.VERSION, "mtime": time.time()}
            else:
                doc = self.get(coll, doc_id)
                if doc is None:
                    continue
            by_coll.setdefault(coll, []).append((ReplaceOne({"id": doc_id}, doc, upsert=True), doc_id, seq))
        for coll, ops in by_coll.items():
            db[coll].bulk_write([op for op, _i, _s in ops], ordered=False)
            with self._lock, self._db:
                # Only clear what was pushed: a write made meanwhile has a newer seq and goes next time.
                self._db.executemany("DELETE FROM pending WHERE coll=? AND id=? AND seq=?",
                                     [(coll, doc_id, seq) for _op, doc_id, seq in ops])

    def _pull(self, db, full):
        changed = set()
        with self._lock:
            pending = {(c, i) for c, i in self._db.execute("SELECT coll, id FROM pending")}
        for coll in COLLECTIONS:
            cursor = float(self._state(f"cursor:{coll}") or 0)
            if full:
                remote = {str(d["id"]): d for d in db[coll].find({"id": {"$exists": True}}, {"_id": 0, "id": 1, "mtime": 1, "deleted": 1})}
                with self._lock:
                    local = {i: m for i, m in self._db.execute("SELECT id, mtime FROM docs WHERE coll=?", (coll,))}
                want = [i for i, d in remote.items() if not d.get("deleted") and (not d.get("mtime") or local.get(i) != d["mtime"])]
                docs = []
                for n in range(0, len(want), FETCH_CHUNK):
                    docs += list(db[coll].find({"id": {"$in": want[n:n + FETCH_CHUNK]}}, {"_id": 0}))
                gone = [i for i in local if (i not in remote or remote[i].get("deleted")) and (coll, i) not in pending]
                mtimes = [d.get("mtime") or 0 for d in remote.values()]
            else:
                docs = list(db[coll].find({"mtime": {"$gt": cursor - OVERLAP}}, {"_id": 0}))
                gone = [str(d["id"]) for d in docs if d.get("deleted") and (coll, str(d["id"])) not in pending]
                docs = [d for d in docs if not d.get("deleted")]
                mtimes = [d.get("mtime") or 0 for d in docs]
            with self._lock, self._db:
                for d in docs:
                    doc_id = str(d.get("id", ""))
                    if not doc_id or (coll, doc_id) in pending:
                        continue
                    data = json.dumps(d)
                    row = self._db.execute("SELECT data FROM docs WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
                    if not row or row[0] != data:
                        self._db.execute("INSERT OR REPLACE INTO docs (coll, id, data, mtime) VALUES (?, ?, ?, ?)",
                                         (coll, doc_id, data, d.get("mtime") or 0))
                        changed.add(coll)
                for doc_id in gone:
                    if self._db.execute("DELETE FROM docs WHERE coll=? AND id=?", (coll, doc_id)).rowcount:
                        changed.add(coll)
            if mtimes and max(mtimes) > cursor:
                self._set_state(f"cursor:{coll}", max(mtimes))
        return changed

    def start_sync_thread(self):
        def loop():
            while True:
                self._wake.wait(SYNC_INTERVAL)
                self._wake.clear()
                time.sleep(0.5)  # batch bursts of writes
                self.sync()
        threading.Thread(target=loop, daemon=True, name="mongo-sync").start()


store: Store | None = None


def init():
    """Open the local store, do a full first sync, start background sync."""
    global store
    store = Store()
    store.sync(full=True)
    store.start_sync_thread()
    return store
