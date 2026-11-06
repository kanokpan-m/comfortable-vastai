"""Keep ComfyUI's saved workflows in the shared store, so they survive the instance.

ComfyUI saves workflows as files under user/default/workflows. Every
SYNC_INTERVAL seconds each file is compared three ways: the file here, the copy
in the store ("workflows" collection, synced through MongoDB), and the version
both had at the last sync (kept in DATA_DIR). That tells an edit here from an
edit on another instance from a deletion:

  changed here only         -> upload
  changed elsewhere only    -> write the file here
  changed on both           -> keep both: upload ours, save theirs next to it
  new in the store          -> write it here (a new instance gets every workflow)
  deleted here              -> mark it deleted in the store
  deleted elsewhere         -> move the file here to DATA_DIR/workflow-trash
"""
import asyncio
import hashlib
import json
import shutil
import time
from pathlib import Path

from . import config
from .events import bus
from .util import log, now

COLL = "workflows"
SYNC_INTERVAL = 30
MAX_BYTES = 4 * 1024 * 1024  # MongoDB records are capped at 16 MB; real workflows are far smaller
_state = {"last": None, "error": "", "synced": 0}


def workflows_dir():
    return config.COMFY_DIR / "user" / "default" / "workflows"


def state_file():
    return config.DATA_DIR / "workflow_sync.json"


def trash_dir():
    return config.DATA_DIR / "workflow-trash"


def doc_id(path):
    return "wf-" + hashlib.sha1(path.encode()).hexdigest()[:20]


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _load_state():
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state):
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def _local_files():
    root = workflows_dir()
    out = {}
    if not root.is_dir():
        return out
    for f in root.rglob("*.json"):
        rel = f.relative_to(root).as_posix()
        if any(part.startswith(".") for part in f.relative_to(root).parts):
            continue
        try:
            if f.stat().st_size > MAX_BYTES:
                continue
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out[rel] = {"text": text, "hash": _hash(text), "mtime": f.stat().st_mtime}
    return out


def _write_local(path, text):
    target = workflows_dir() / path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.sync")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)


def _trash_local(path):
    src = workflows_dir() / path
    if src.exists():
        dst = trash_dir() / time.strftime("%Y%m%d-%H%M%S") / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), dst)


def _conflict_name(path):
    p = Path(path)
    return (p.parent / f"{p.stem} (from another instance){p.suffix}").as_posix()


def sync_once(store):
    """One three-way pass. Returns how many files or records changed."""
    local = _local_files()
    remote = {d["path"]: d for d in store.all(COLL) if d.get("path")}
    state = _load_state()
    changes = 0

    def upload(path, f):
        store.put(COLL, {"id": doc_id(path), "path": path, "data": f["text"], "hash": f["hash"],
                         "deleted": False, "updated_at": now()})
        state[path] = f["hash"]

    for path in sorted(set(local) | set(remote)):
        f, d, base = local.get(path), remote.get(path), state.get(path)
        if d and d.get("deleted"):
            if f and f["hash"] == base:          # deleted elsewhere, untouched here
                _trash_local(path)
                state.pop(path, None)
                changes += 1
            elif f:                               # edited here after it was deleted elsewhere: keep it
                upload(path, f)
                changes += 1
            continue
        if f and d:
            if f["hash"] == d.get("hash"):
                state[path] = f["hash"]
            elif f["hash"] == base:               # changed elsewhere
                _write_local(path, d["data"])
                state[path] = d["hash"]
                changes += 1
            elif d.get("hash") == base:           # changed here
                upload(path, f)
                changes += 1
            else:                                 # changed on both: keep both
                copy = _conflict_name(path)
                _write_local(copy, d["data"])
                upload(path, f)
                log.warning("Workflow %s changed on two instances; theirs saved as %s", path, copy)
                changes += 1
        elif f:                                   # new here
            upload(path, f)
            changes += 1
        elif d:
            if base is not None:                  # deleted here
                store.put(COLL, {**d, "data": "", "deleted": True, "updated_at": now()})
                state.pop(path, None)
            else:                                 # new elsewhere, or this is a new instance
                _write_local(path, d["data"])
                state[path] = d["hash"]
            changes += 1
    _save_state(state)
    _state.update(last=now(), error="", synced=len([p for p in state if p in local or p in remote]))
    return changes


def status(store):
    return {"enabled": bool(store.setting("sync_workflows")), "folder": str(workflows_dir()), **_state}


async def loop(store):
    await asyncio.sleep(10)  # let the first MongoDB pull land, so a new instance restores before it uploads
    while True:
        if store.setting("sync_workflows"):
            try:
                if await asyncio.to_thread(sync_once, store):
                    bus.publish("workflow-sync", status(store))
            except Exception as exc:
                _state["error"] = str(exc)[:300]
                log.warning("Workflow sync failed: %s", exc)
        await asyncio.sleep(SYNC_INTERVAL)
