"""ComfyUI-Manager, whichever version ComfyUI runs.

ComfyUI-Manager 3.x (a custom node) serves /customnode/* and /manager/*. The Manager built into
ComfyUI (`--enable-manager`, the comfyui-manager 4.x package) serves /v2/* instead, has no pack
list endpoint, and installs through a task queue. This module hides the difference:

  flavor()        "v2", "legacy" or None (no Manager)
  mappings()      ({node type: [pack keys]}, [(name pattern, pack key)])
  packs()         {pack key: info} with title, repository, stars, id (registry id) and state
  install(ids)    queue installs; returns {id: result}
  queue_status()

Pack keys are the Manager's list keys (legacy) or repository URLs (v2); registry ids (cnr_id, the
id ComfyUI writes into node properties) and repository URLs are accepted everywhere.
Blocking (requests); call through asyncio.to_thread.
"""
import re
import time
import uuid

import requests

from . import config
from .util import log

PACK_LIST_URL = "https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main/custom-node-list.json"
REGISTRY = "https://api.comfy.org"
_cache = {}


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def forget():
    """Drop cached lists (after installing packs)."""
    for key in ("packs", "installed", "mappings"):
        _cache.pop(key, None)


def _get(path, timeout=60):
    r = requests.get(config.COMFY_URL + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _ok(path):
    try:
        return requests.get(config.COMFY_URL + path, timeout=10).status_code == 200
    except requests.RequestException:
        return False


def flavor(refresh=False):
    """"v2", "legacy" or None. A missing Manager is only remembered for 15 s: ComfyUI may be
    starting or restarting."""
    hit = _cache.get("flavor")
    if not refresh and hit and time.time() - hit[0] < (300 if hit[1] else 15):
        return hit[1]
    kind = "v2" if _ok("/v2/manager/version") else "legacy" if _ok("/manager/version") else None
    _cache["flavor"] = (time.time(), kind)
    return kind


def norm_repo(url):
    return (url or "").strip().rstrip("/").removesuffix(".git").lower()


def mappings():
    def load():
        if flavor() is None:
            raise RuntimeError("ComfyUI-Manager is not available")
        prefix = "/v2" if flavor() == "v2" else ""
        data = _get(f"{prefix}/customnode/getmappings?mode=cache")
        index, patterns = {}, []
        for key, (types, meta) in data.items():
            for t in types:
                index.setdefault(t, []).append(key)
            if meta.get("nodename_pattern"):
                patterns.append((meta["nodename_pattern"], key))
        return index, patterns
    return _cached("mappings", 1800, load)


def _installed_v2():
    """{registry id or repo: {ver, enabled}} of packs on disk (v2)."""
    def load():
        out = {}
        for name, info in (_get("/v2/customnode/installed") or {}).items():
            for key in (info.get("cnr_id"), info.get("aux_id"), name):
                if key:
                    out[key.lower()] = info
        return out
    return _cached("installed", 30, load)


def packs():
    """{key: {title, repository, id, stars, description, state, version}} for every known pack."""
    def load():
        kind = flavor()
        if kind is None:
            raise RuntimeError("ComfyUI-Manager is not available")
        if kind == "legacy":
            data = _get("/customnode/getlist?mode=cache&skip_update=true", timeout=60)
            return data.get("node_packs") or data
        # v2 has no list endpoint: use the Manager's published list, keyed by repository URL.
        try:
            r = requests.get(PACK_LIST_URL, timeout=60)
            r.raise_for_status()
            listing = r.json().get("custom_nodes") or []
        except (requests.RequestException, ValueError) as exc:
            log.info("ComfyUI-Manager pack list unavailable: %s", exc)
            listing = []
        installed = _installed_v2()
        out = {}
        for p in listing:
            repo = p.get("reference") or (p.get("files") or [""])[0]
            if not repo:
                continue
            cnr = p.get("id") or ""
            aux = "/".join(norm_repo(repo).split("/")[-2:])
            info = installed.get(cnr.lower()) or installed.get(aux)
            out[repo] = {"id": cnr or repo, "title": p.get("title") or cnr or repo, "repository": repo,
                         "description": p.get("description") or "", "stars": p.get("stars") or 0,
                         "state": ("enabled" if info.get("enabled", True) else "disabled") if info else "not-installed",
                         "version": (info or {}).get("ver") or "unknown", "cnr": cnr}
        return out
    return _cached("packs", 1800, load)


def pack_info(key):
    """Info for a list key, registry id or repository URL; None when the Manager doesn't know it.
    `key` in the result is the key install() takes."""
    all_packs = packs()
    if key in all_packs:
        return {**all_packs[key], "id": all_packs[key].get("id") or key, "key": key}
    norm = norm_repo(key)
    for k, p in all_packs.items():
        repo = norm_repo(p.get("repository") or (p.get("files") or [""])[0])
        if (repo and repo == norm) or p.get("id") == key or p.get("cnr") == key:
            return {**p, "id": p.get("id") or k, "key": k}
    return None


def registry_pack(cnr_id):
    """A pack straight from the Comfy Registry (when the Manager's list doesn't have it)."""
    def load():
        try:
            r = requests.get(f"{REGISTRY}/nodes/{cnr_id}", timeout=20)
            if r.status_code != 200:
                return None
            d = r.json()
            return {"id": d.get("id") or cnr_id, "title": d.get("name") or cnr_id, "repository": d.get("repository") or "",
                    "description": (d.get("description") or "")[:300], "stars": d.get("github_stars") or 0,
                    "version": ((d.get("latest_version") or {}).get("version")) or "unknown"}
        except (requests.RequestException, ValueError):
            return None
    return _cached(f"registry:{cnr_id}", 3600, load)


def is_installed(cnr_id="", repository=""):
    """Whether a pack is on disk (by registry id or repository)."""
    try:
        if flavor() == "v2":
            installed = _installed_v2()
            aux = "/".join(norm_repo(repository).split("/")[-2:]) if repository else ""
            return bool((cnr_id and cnr_id.lower() in installed) or (aux and aux in installed))
        info = pack_info(cnr_id) if cnr_id else None
        info = info or (pack_info(repository) if repository else None)
        return bool(info and info.get("state") in ("enabled", "installed", "disabled"))
    except Exception:
        return False


def install(pack_ids):
    """Queue node packs for installation and start the queue. Returns {id: result}."""
    kind = flavor()
    if not kind:
        return {pid: "ComfyUI-Manager is not available" for pid in pack_ids}
    results = {}
    queued = False
    for pid in dict.fromkeys(pack_ids):
        p = pack_info(pid)
        if p and p.get("state") in ("enabled", "installed"):
            results[pid] = "already installed"
            continue
        if kind == "v2":
            cnr = (p or {}).get("cnr") or (p or {}).get("id") or pid
            if re.match(r"https?://", cnr) or not (registry_pack(cnr) or (p and p.get("cnr"))):
                results[pid] = ("not in the Comfy Registry: the built-in ComfyUI-Manager only installs registry packs. "
                                "Install it by hand (git clone into custom_nodes) or start ComfyUI with the legacy Manager")
                continue
            body = {"ui_id": uuid.uuid4().hex, "client_id": "comfortable", "kind": "install",
                    "params": {"id": cnr, "version": "latest", "selected_version": "latest", "mode": "remote",
                               "channel": "default", "skip_post_install": False}}
            r = requests.post(config.COMFY_URL + "/v2/manager/queue/task", json=body, timeout=30)
            results[pid] = "queued" if r.ok else f"refused ({r.status_code}): {r.text[:160]}"
            queued = queued or r.ok
            continue
        if not p and re.match(r"https://github\.com/[\w.\-]+/[\w.\-]+$", pid):
            # Not in the Manager's list: it installs from the git URL only if its config allows it.
            r = requests.post(config.COMFY_URL + "/customnode/install/git_url", json={"url": pid}, timeout=600)
            if r.ok:
                results[pid] = "installed"
            elif r.status_code == 403:
                results[pid] = ("ComfyUI-Manager only installs packs that aren't in its list when allow_git_url_install = True "
                                "is set in ComfyUI/user/__manager/config.ini; set it and restart ComfyUI, or install the pack by hand")
            else:
                results[pid] = f"install failed ({r.status_code}): {r.text[:160]}"
            continue
        if not p:
            results[pid] = "not found in ComfyUI-Manager's list"
            continue
        body = {**{k: v for k, v in p.items() if k not in ("key", "cnr")},
                "selected_version": "latest" if p.get("version", "unknown") != "unknown" else "unknown",
                "ui_id": pid, "channel": "default", "mode": "cache", "skip_post_install": False}
        r = requests.post(config.COMFY_URL + "/manager/queue/install", json=body, timeout=30)
        results[pid] = "queued" if r.ok else f"refused ({r.status_code}): {r.text[:160]}"
        queued = queued or r.ok
    if queued:
        requests.post(config.COMFY_URL + ("/v2/manager/queue/start" if kind == "v2" else "/manager/queue/start"), timeout=30)
    forget()
    return results


def queue_status():
    try:
        return _get("/v2/manager/queue/status" if flavor() == "v2" else "/manager/queue/status", timeout=10)
    except Exception as exc:
        return {"error": str(exc)}


def summary(p):
    """The pack fields the UI shows."""
    if not p:
        return None
    return {"id": p.get("key") or p.get("id"), "title": p.get("title") or p.get("id"), "git_url": p.get("git_url"),
            "repository": p.get("repository") or (p.get("files") or [""])[0], "stars": p.get("stars") or 0,
            "state": p.get("state") or "not-installed", "version": p.get("version") or "unknown",
            "description": (p.get("description") or "")[:200]}

