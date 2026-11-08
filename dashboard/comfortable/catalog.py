"""The "Suggested by AI" catalog: curated packs (every file one setup needs) and starter workflows.

Two copies exist: the one shipped in catalog/ with this version of Comfortable, and the one
published to the database with tools/catalog.py (shared by every instance, updatable without a
release). The newer version wins. Documents (see docs/database.md):

  category  {id, title, icon, group, mature, description, order}
  pack      {id, title, kind, categories, base_model, nsfw, summary, why, vram_gb, settings,
             trigger_words, requires: [pack ids], files: [file], node_packs: [{id, title, repository}],
             workflows: [workflow ids], links, preview: {url, nsfw_level}, rank}
  file      {name, category, filename, url, size, sha256, source, optional, needs_token, civitai?, hf?}
  workflow  {id, title, task, categories, nsfw, summary, steps, inputs, packs, node_packs, graph, rank}

plan() and install() take any mix of pack and workflow ids (the MCP server, `comfortable rent
--install` and COMFORTABLE_INSTALL at boot all go through them).
Blocking helpers (file reads, ComfyUI-Manager lookups): call through asyncio.to_thread.
"""
import json
import os
import re
import shutil
import time
import urllib.parse

import requests

from . import config, manager, models, sources
from .downloads import ACTIVE
from .util import human_size, log, now

_bundled = {"mtime": None, "data": None}
FAMILIES = (
    ("krea2", ("krea 2", "krea2")), ("krea1", ("krea",)), ("flux2", ("flux.2", "flux2", "flux 2")),
    ("flux1", ("flux",)), ("qwen-edit", ("qwen-image-edit", "qwen image edit", "qwen edit")), ("qwen", ("qwen",)),
    ("zimage", ("z-image", "zimage", "z image")), ("chroma", ("chroma",)), ("minimax-h3", ("minimax",)),
    ("wan22", ("wan video 2.2", "wan 2.2", "wan2.2", "wan22")), ("wan21", ("wan",)), ("ltx", ("ltx",)),
    ("hunyuan", ("hunyuan",)), ("pony", ("pony",)), ("illustrious", ("illustrious", "noobai", "noob")),
    ("sdxl", ("sdxl", "xl")), ("sd15", ("sd 1.5", "sd1.5", "sd15")),
)


def family(base_model):
    """A coarse base-model family: 'Krea 2 Turbo' -> krea2, 'NoobAI' -> illustrious (LoRAs mix)."""
    t = (base_model or "").lower()
    for fam, words in FAMILIES:
        if any(w in t for w in words):
            return fam
    return ""


# ---- loading ---------------------------------------------------------------------------------
def bundled():
    """The catalog shipped in catalog/ ({version, categories, packs, workflows}); graphs load lazily."""
    path = config.CATALOG_DIR / "catalog.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"version": "", "categories": [], "packs": [], "workflows": []}
    if _bundled["mtime"] != mtime:
        data = json.loads(path.read_text(encoding="utf-8"))
        _bundled.update(mtime=mtime, data=data)
    return _bundled["data"]


def current(store):
    """The newest catalog: the database copy when its version is at least the shipped one."""
    shipped = bundled()
    meta = store.get("meta", "catalog") or {}
    if meta.get("version") and meta["version"] >= (shipped.get("version") or "") and store.all("catalog_packs"):
        return {"version": meta["version"], "source": "database", "published_at": meta.get("published_at"),
                "categories": store.all("catalog_categories"), "packs": store.all("catalog_packs"),
                "workflows": store.all("catalog_workflows")}
    return {**shipped, "source": "bundled"}


def _by_id(items, item_id):
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        raise FileNotFoundError(item_id)
    return item


def graph(wf):
    """A workflow's ComfyUI graph (inline in the database copy, a file next to the shipped one)."""
    g = wf.get("graph")
    if isinstance(g, dict):
        return g
    if isinstance(g, str):
        from .util import contained
        return json.loads(contained(config.CATALOG_DIR, g).read_text(encoding="utf-8"))
    raise FileNotFoundError(f"{wf['id']} has no graph")


# ---- install state ----------------------------------------------------------------------------
def disk_index():
    """{(folder, relative path lowercased)} of every model file on disk. Workflows name files by
    their path inside the folder (MiniMaxH3/model.safetensors), so a copy in another sub-folder
    doesn't count: ComfyUI wouldn't find it where the starter looks."""
    return {(config.canonical_category(cat), f["name"].lower()) for cat, files in models.scan().items() for f in files}


def _installed(f, idx):
    return (config.canonical_category(f.get("category")), (f.get("filename") or "").replace("\\", "/").lower()) in idx


def requirements(cat, pack_id, seen=None):
    """The pack and every pack it requires, dependencies first."""
    seen = seen if seen is not None else []
    pack = _by_id(cat["packs"], pack_id)
    for req in pack.get("requires") or []:
        if req not in seen and any(p["id"] == req for p in cat["packs"]):
            requirements(cat, req, seen)
    if pack_id not in seen:
        seen.append(pack_id)
    return seen


def pack_state(pack, idx, library_items, bundles):
    files = pack.get("files") or []
    required = [f for f in files if not f.get("optional")]
    have = [f for f in files if _installed(f, idx)]
    urls = {i.get("url") for i in library_items}
    names = {(os.path.basename(i.get("filename") or "").lower()) for i in library_items}
    saved_bundle = next((b for b in bundles if b.get("origin") == f"catalog:{pack['id']}"), None)
    return {
        "files": len(files), "installed": len(have),
        "complete": bool(required) and all(_installed(f, idx) for f in required),
        "missing_bytes": sum(int(f.get("size") or 0) for f in required if not _installed(f, idx)),
        "total_bytes": sum(int(f.get("size") or 0) for f in required),
        "in_library": sum(1 for f in files if f.get("url") in urls or os.path.basename(f.get("filename") or "").lower() in names),
        "bundle_id": saved_bundle and saved_bundle["id"],
        "needs_token": any(f.get("needs_token") for f in files),
    }


def overview(store):
    """Everything the Suggested and Workflows screens show, with install and library state."""
    cat = current(store)
    idx = disk_index()
    lib, bundles = store.all("library"), store.all("bundles")
    fams = {}
    for i in lib:
        # Only what sets a base model (checkpoints, diffusion models, LoRAs): a Krea 2 text encoder
        # is called qwen3vl_4b_..., which says nothing about using Qwen-Image.
        if config.canonical_category(i.get("category")) not in ("checkpoints", "diffusion_models", "loras"):
            continue
        fam = family(i.get("base_model")) or family(i.get("name"))
        if fam:
            fams[fam] = fams.get(fam, 0) + 1
    packs = []
    for p in cat["packs"]:
        state = pack_state(p, idx, lib, bundles)
        packs.append({**p, "state": state, "family": family(p.get("base_model")),
                      "for_you": family(p.get("base_model")) in fams})
    by_pack = {p["id"]: p for p in packs}
    workflows = []
    for w in cat["workflows"]:
        needed = []
        for pid in w.get("packs") or []:
            if pid in by_pack:
                for rid in requirements(cat, pid):
                    if rid not in needed:
                        needed.append(rid)
        missing = sum(by_pack[r]["state"]["missing_bytes"] for r in needed if r in by_pack)
        complete = all(by_pack[r]["state"]["complete"] for r in needed if r in by_pack)
        workflows.append({**{k: v for k, v in w.items() if k != "graph"}, "all_packs": needed,
                          "state": {"complete": complete, "missing_bytes": missing,
                                    "needs_token": any(by_pack[r]["state"]["needs_token"] for r in needed if r in by_pack)},
                          "for_you": any(by_pack[r]["for_you"] for r in needed if r in by_pack)})
    categories = sorted(cat["categories"], key=lambda c: (c.get("order", 999), c.get("title", "")))
    return {"version": cat.get("version"), "source": cat.get("source"), "published_at": cat.get("published_at"),
            "categories": categories, "packs": sorted(packs, key=lambda p: (p.get("rank", 999), p["title"].lower())),
            "workflows": sorted(workflows, key=lambda w: (w.get("rank", 999), w["title"].lower())),
            "library_families": sorted(fams, key=lambda f: -fams[f])}


# ---- actions ------------------------------------------------------------------------------------
def download_spec(f, pack):
    preview = pack.get("preview") or {}
    return {"url": f["url"], "category": f["category"], "filename": f["filename"],
            "name": f.get("name") or pack["title"], "size": f.get("size") or 0, "sha256": f.get("sha256") or "",
            "source": f.get("source") or ("civitai" if "civitai." in f["url"] else "hf" if "huggingface.co" in f["url"] else "url"),
            "preview": preview.get("url") or "", "preview_mature": (preview.get("nsfw_level") or 1) >= 4}


def split_ids(cat, ids):
    """Mixed pack / workflow ids -> (pack ids, workflow ids, unknown ids). A workflow wins a tie."""
    wf_ids, pack_ids = {w["id"] for w in cat["workflows"]}, {p["id"] for p in cat["packs"]}
    packs, workflows, unknown = [], [], []
    for i in dict.fromkeys(str(i).strip() for i in ids or []):
        if i:
            (workflows if i in wf_ids else packs if i in pack_ids else unknown).append(i)
    return packs, workflows, unknown


def resolve(cat, packs=(), workflows=(), ids=()):
    """(pack ids to install, the packs they require first; workflow docs). Unknown ids raise."""
    more_packs, more_wfs, unknown = split_ids(cat, ids)
    wf_by, pack_ids = {w["id"]: w for w in cat["workflows"]}, {p["id"] for p in cat["packs"]}
    workflows, packs = list(workflows or []) + more_wfs, list(packs or []) + more_packs
    unknown += [w for w in workflows if w not in wf_by] + [p for p in packs if p not in pack_ids]
    if unknown:
        raise FileNotFoundError("unknown catalog id(s): " + ", ".join(dict.fromkeys(unknown)))
    wfs = [wf_by[w] for w in dict.fromkeys(workflows)]
    order = []
    for pid in [p for wf in wfs for p in wf.get("packs") or [] if p in pack_ids] + packs:
        for rid in requirements(cat, pid):
            if rid not in order:
                order.append(rid)
    return order, wfs


def node_ids(cat, order, wfs):
    """Node pack ids (Comfy Registry ids or repository URLs) these packs and workflows need."""
    ids = [np["id"] for pid in order for np in _by_id(cat["packs"], pid).get("node_packs") or []]
    ids += [np["id"] for wf in wfs for np in wf.get("node_packs") or []]
    return list(dict.fromkeys(ids))


def _source(f):
    return f.get("source") or ("civitai" if "civitai." in f["url"] else "hf" if "huggingface.co" in f["url"] else "url")


def plan(store, packs=(), workflows=(), ids=(), optional=False, active=()):
    """What installing these packs and starter workflows takes, before anything is downloaded:
    every file (on disk, downloading, needs a Civitai key), node packs, bytes to fetch, disk and
    VRAM needs and warnings. active: (category, filename) of downloads already running."""
    cat = current(store)
    order, wfs = resolve(cat, packs, workflows, ids)
    if not order and not wfs:
        raise ValueError("Name at least one catalog pack or starter workflow")
    idx = disk_index()
    running ={(config.canonical_category(c), (f or "").replace("\\", "/").lower()) for c, f in active}
    files, seen = [], set()
    for pid in order:
        for f in _by_id(cat["packs"], pid).get("files") or []:
            if f.get("optional") and not optional:
                continue
            key = (config.canonical_category(f.get("category")), (f.get("filename") or "").replace("\\", "/").lower())
            if key in seen:
                continue
            seen.add(key)
            installed = _installed(f, idx)
            files.append({"pack": pid, "name": f.get("name") or os.path.basename(f["filename"]), "category": f["category"],
                          "filename": f["filename"], "size": int(f.get("size") or 0), "installed": installed,
                          "downloading": not installed and key in running, "needs_token": bool(f.get("needs_token")),
                          "optional": bool(f.get("optional")), "source": _source(f)})
    kind = manager.flavor()
    nodes = []
    for nid in node_ids(cat, order, wfs):
        np = _node_pack(cat, nid)
        nodes.append({"id": nid, "title": np.get("title") or nid, "repository": np.get("repository", ""),
                      "installed": manager.is_installed(np["id"], np.get("repository", "")) if kind else None})
    missing = [f for f in files if not f["installed"]]
    need = sum(f["size"] for f in missing)
    free = shutil.disk_usage(config.MODELS_DIR if config.MODELS_DIR.exists() else config.WORKSPACE).free
    vram = max([_by_id(cat["packs"], p).get("vram_gb") or 0 for p in order] + [w.get("vram_gb") or 0 for w in wfs], default=0)
    token_files = [f for f in missing if f["needs_token"]]
    has_token = bool(store.setting("civitai_token"))
    missing_nodes = [n for n in nodes if n["installed"] is False]
    warnings = []
    if token_files and not has_token:
        warnings.append(f"{len(token_files)} file(s) only download with a Civitai API key (Settings > Civitai token): "
                        + ", ".join(f["name"] for f in token_files[:5]) + ("..." if len(token_files) > 5 else ""))
    if need > free * 0.97:
        warnings.append(f"Not enough disk: {human_size(need)} to download, {human_size(free)} free")
    if nodes and not kind:
        warnings.append("ComfyUI-Manager isn't answering (ComfyUI down, or started without --enable-manager): "
                        "node packs can't be checked or installed yet")
    if missing_nodes:
        warnings.append(f"Installs {len(missing_nodes)} node pack(s): restart ComfyUI afterwards to load them")
    requested = [{"id": w["id"], "type": "workflow", "title": w["title"]} for w in wfs]
    requested += [{"id": p, "type": "pack", "title": _by_id(cat["packs"], p)["title"]} for p in list(packs or []) + split_ids(cat, ids)[0]]
    return {"catalog_version": cat.get("version"), "requested": requested, "packs": order,
            "workflows": [{"id": w["id"], "title": w["title"], "task": w.get("task"), "inputs": w.get("inputs") or [],
                           "steps": w.get("steps") or []} for w in wfs],
            "files": files, "node_packs": nodes, "files_missing": len(missing),
            "bytes_total": sum(f["size"] for f in files), "bytes_needed": need,
            "unknown_sizes": sum(1 for f in missing if not f["size"]), "disk_free": free, "fits_disk": need < free * 0.97,
            "vram_gb": vram, "needs_token": bool(token_files), "civitai_token_set": has_token,
            "ready": not missing and not missing_nodes and (bool(kind) or not nodes), "warnings": warnings}


def install(store, downloads, packs=(), workflows=(), ids=(), optional=False, nodes=True, save_bundle=False,
            auto_install=False, to_comfy=False):
    """Install packs and starter workflows in one call: queue every missing file (the packs they
    require included), install missing node packs (nodes=False leaves them for later), and
    optionally save them as bundles and the starters into ComfyUI's Workflows sidebar."""
    cat = current(store)
    order, wfs = resolve(cat, packs, workflows, ids)
    if not order and not wfs:
        raise ValueError("Name at least one catalog pack or starter workflow")
    tasks, errors = [], []
    for pid in order:
        pack = _by_id(cat["packs"], pid)
        for f in pack.get("files") or []:
            if f.get("optional") and not optional:
                continue
            try:
                tasks.append(downloads.add(download_spec(f, pack)))
            except Exception as exc:
                errors.append({"filename": f.get("filename"), "error": str(exc)})
    needed = node_ids(cat, order, wfs)
    results = install_nodes(cat, needed) if nodes else {}
    out = {"packs": order, "workflows": [w["id"] for w in wfs], "tasks": tasks, "errors": errors,
           "node_packs": results, "node_pack_ids": needed,
           "queued": sum(1 for t in tasks if t["status"] in ACTIVE),
           "already_installed": sum(1 for t in tasks if t["status"] == "done"),
           "bytes_queued": sum(int(t.get("size") or 0) for t in tasks if t["status"] in ACTIVE),
           "restart_needed": any(v in ("queued", "installed") for v in results.values())}
    if save_bundle:
        explicit = list(packs or []) + split_ids(cat, ids)[0]
        out["bundles"] = [save_pack(store, p, auto_install)["bundle"]["id"] for p in dict.fromkeys(explicit)]
        out["bundles"] += [save_workflow(store, w["id"], auto_install)["bundle"]["id"] for w in wfs]
    if to_comfy:
        out["saved_to_comfy"] = []
        for w in wfs:
            try:
                out["saved_to_comfy"].append({"id": w["id"], **save_to_comfy(store, w["id"])})
            except Exception as exc:
                errors.append({"workflow": w["id"], "error": f"not saved into ComfyUI: {exc}"})
    return out


def install_packs(store, downloads, pack_ids, optional=False):
    """Queue every missing file of these packs (and the packs they require) and their node packs."""
    return install(store, downloads, packs=pack_ids, optional=optional)


def install_nodes(cat, ids):
    """Install the node packs of `ids` that aren't on disk yet. Returns {id: result}."""
    missing = [n for n in ids if not _node_pack_installed(cat, n)]
    return manager.install(missing) if missing else {}


def progress(downloads, task_ids=None):
    """Download progress of these tasks (default: running ones and the last hour's), plus the
    ComfyUI-Manager install queue."""
    tasks = downloads.snapshot()
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t["id"] in wanted]
    else:
        tasks = [t for t in tasks if t["status"] in ACTIVE or (t.get("finished_at") or 0) > time.time() - 3600]
    counts = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    active = [t for t in tasks if t["status"] in ACTIVE]
    speed = sum(t.get("speed") or 0 for t in active)
    left = sum(max(0, (t.get("size") or 0) - (t.get("done") or 0)) for t in active)
    keys = ("id", "name", "filename", "category", "status", "size", "done", "speed", "eta", "error")
    return {"tasks": [{k: t.get(k) for k in keys} for t in tasks], "counts": counts, "active": len(active),
            "failed": counts.get("failed", 0), "finished": not active,
            "bytes_total": sum(t.get("size") or 0 for t in tasks), "bytes_done": sum(t.get("done") or 0 for t in tasks),
            "speed": speed, "eta_s": int(left / speed) if speed else None,
            "node_queue": manager.queue_status() if manager.flavor() else None}


def search_nodes(query, limit=15):
    """Node packs ComfyUI-Manager knows that match every word of `query`, best first."""
    terms = [t for t in (query or "").lower().split() if t]
    if not terms:
        raise ValueError("Say what to look for")
    if not manager.flavor():
        raise sources.SourceError("ComfyUI-Manager isn't answering (ComfyUI down, or started without --enable-manager)")
    hits = []
    for key, p in manager.packs().items():
        title, pid = (p.get("title") or "").lower(), str(p.get("id") or p.get("cnr") or "").lower()
        repo = (p.get("repository") or p.get("reference") or key).lower()
        hay = f"{title} {pid} {repo} {(p.get('description') or '').lower()}"
        if all(t in hay for t in terms):
            score = sum(3 if t in title or t in pid else 1 if t in repo else 0.3 for t in terms)
            hits.append((score + (5 if " ".join(terms) in (title, pid) else 0), p.get("stars") or 0, key, p))
    hits.sort(key=lambda h: (-h[0], -h[1]))
    return [{**manager.summary({**p, "key": key}), "registry_id": p.get("cnr") or p.get("id") or ""}
            for _, _, key, p in hits[:limit]]


def _node_pack(cat, node_id):
    for p in cat["packs"] + cat["workflows"]:
        for np in p.get("node_packs") or []:
            if np["id"] == node_id:
                return np
    return {"id": node_id}


def _node_pack_installed(cat, node_id):
    np = _node_pack(cat, node_id)
    return manager.is_installed(np["id"], np.get("repository", ""))


def _save_bundle(store, base, entries, auto_install):
    """Create (or update) the bundle `base` describes and link a library item for every
    (file, pack) in entries, adding the items the library doesn't have yet."""
    bundle = next((b for b in store.all("bundles") if b.get("origin") == base["origin"]), None) or {**base, "created_at": now()}
    bundle.update(auto_install=bool(auto_install) or bool(bundle.get("auto_install")), updated_at=now())
    store.put("bundles", bundle)
    library = store.all("library")
    by_url = {i.get("url"): i for i in library}
    by_name = {(config.canonical_category(i.get("category")), os.path.basename(i.get("filename") or "").lower()): i for i in library}
    added, linked = 0, 0
    for f, pack in entries:
        item = by_url.get(f["url"]) or by_name.get((config.canonical_category(f["category"]), os.path.basename(f["filename"]).lower()))
        if item:
            linked += 1
        else:
            spec = download_spec(f, pack)
            # One-file packs take the pack's title; multi-file packs name each file inside the title.
            files = pack.get("files") or []
            spec["name"] = pack["title"] if len(files) == 1 else f"{pack['title']} · {f.get('name') or os.path.basename(f['filename'])}"
            cand = {**spec, "page_url": f.get("page") or (pack.get("links") or [{}])[0].get("url", ""),
                    "trigger_words": f.get("trigger_words") or pack.get("trigger_words") or [],
                    "base_model": pack.get("base_model") or "", "type": f.get("type") or "", "nsfw": bool(pack.get("nsfw")),
                    "civitai": f.get("civitai"), "hf": f.get("hf")}
            item = sources.library_item(cand, {"origin": f"catalog:{pack['id']}", "tags": pack.get("categories") or [],
                                               "notes": pack.get("why") or ""})
            added += 1
        item["bundle_ids"] = sorted(set(item.get("bundle_ids") or []) | {bundle["id"]})
        item["updated_at"] = now()
        store.put("library", item)
    return {"bundle": bundle, "added": added, "linked": linked}


def _entries(cat, order, main=None):
    """(file, pack) for every file of these packs: all of `main`'s, the required ones of the rest."""
    out = []
    for pid in order:
        pack = _by_id(cat["packs"], pid)
        out += [(f, pack) for f in pack.get("files") or [] if pid == main or not f.get("optional")]
    return out


def save_pack(store, pack_id, auto_install=False):
    """Save a pack's files, and those of the packs it requires (a finetune's text encoder and VAE),
    to the library as a bundle, or update the bundle saved before."""
    cat = current(store)
    pack = _by_id(cat["packs"], pack_id)
    base = {"id": f"cat-{pack_id}", "name": pack["title"], "icon": pack.get("icon") or "✨",
            "description": pack.get("summary") or "", "tags": pack.get("categories") or [], "origin": f"catalog:{pack_id}"}
    return _save_bundle(store, base, _entries(cat, requirements(cat, pack_id), main=pack_id), auto_install)


def save_workflow(store, wf_id, auto_install=False):
    """Save every file a starter workflow needs to the library as one bundle."""
    cat = current(store)
    order, wfs = resolve(cat, workflows=[wf_id])
    wf = wfs[0]
    base = {"id": f"wf-{wf_id}", "name": wf["title"], "icon": "🧩", "description": wf.get("summary") or "",
            "tags": wf.get("categories") or [], "origin": f"catalog-workflow:{wf_id}"}
    return _save_bundle(store, base, _entries(cat, order), auto_install)


def workflow(store, wf_id):
    cat = current(store)
    wf = _by_id(cat["workflows"], wf_id)
    return {**wf, "graph": graph(wf)}


def workflow_status(store, wf_id):
    """Files and node packs a workflow still needs (node packs need ComfyUI to answer)."""
    cat = current(store)
    wf = _by_id(cat["workflows"], wf_id)
    idx = disk_index()
    files = []
    for pid in wf.get("packs") or []:
        for rid in requirements(cat, pid):
            for f in _by_id(cat["packs"], rid).get("files") or []:
                if not f.get("optional"):
                    files.append({"filename": f["filename"], "category": f["category"], "size": f.get("size") or 0,
                                  "installed": _installed(f, idx), "pack": rid})
    nodes, comfy_ok = [], True
    ids = []
    for pid in wf.get("packs") or []:
        for rid in requirements(cat, pid):
            ids += [np["id"] for np in _by_id(cat["packs"], rid).get("node_packs") or []]
    ids += [np["id"] for np in wf.get("node_packs") or []]
    for nid in dict.fromkeys(ids):
        np = _node_pack(cat, nid)
        try:
            ok = manager.is_installed(np["id"], np.get("repository", "")) if manager.flavor() else False
        except Exception:
            ok, comfy_ok = False, False
        nodes.append({"id": nid, "title": np.get("title") or nid, "repository": np.get("repository", ""), "installed": ok})
    if not manager.flavor():
        comfy_ok = _comfy_up()
    return {"files": files, "nodes": nodes, "manager": manager.flavor(), "comfy": comfy_ok,
            "ready": all(f["installed"] for f in files) and all(n["installed"] for n in nodes)}


def _comfy_up():
    try:
        return requests.get(config.COMFY_URL + "/system_stats", timeout=5).ok
    except requests.RequestException:
        return False


def save_to_comfy(store, wf_id, overwrite=True):
    """Write the workflow into ComfyUI's workflows folder (Workflows sidebar → Comfortable/...).
    overwrite=False keeps a copy the user may have edited (returns existed=True)."""
    wf = workflow(store, wf_id)
    name = re.sub(r'[\\/:*?"<>|]+', " ", wf["title"]).strip()[:80] or wf_id
    path = f"workflows/Comfortable/{name}.json"
    r = requests.post(f"{config.COMFY_URL}/api/userdata/{urllib.parse.quote(path, safe='')}"
                      f"?overwrite={'true' if overwrite else 'false'}&full_info=true",
                      data=json.dumps(wf["graph"]), headers={"Content-Type": "application/json"}, timeout=20)
    if r.status_code == 409 and not overwrite:
        return {"path": path.removeprefix("workflows/"), "existed": True}
    if not r.ok:
        raise sources.SourceError(f"ComfyUI didn't save the workflow ({r.status_code}): {r.text[:160]}")
    log.info("Saved starter workflow %s to ComfyUI as %s", wf_id, path)
    return {"path": path.removeprefix("workflows/"), "saved_at": int(time.time())}


# ---- COMFORTABLE_INSTALL: set up packs and starters at boot ----------------------------------------
boot_state = {}


def boot_install(store, downloads, ids):
    """Queue the files of these pack / workflow ids now; returns (packs, workflows) whose node packs
    and ComfyUI copies wait for ComfyUI (boot_finish)."""
    cat = current(store)
    packs, workflows, unknown = split_ids(cat, ids)
    boot_state.update(ids=list(ids), unknown=unknown, step="downloading", tasks=[], node_packs={}, saved=[],
                      errors=[], restart_needed=False, started_at=now())
    if unknown:
        log.warning("COMFORTABLE_INSTALL: unknown catalog id(s): %s", ", ".join(unknown))
    if not packs and not workflows:
        boot_state["step"] = "done"
        return [], []
    result = install(store, downloads, packs, workflows, nodes=False)
    boot_state.update(tasks=[t["id"] for t in result["tasks"]], errors=result["errors"], packs=result["packs"])
    log.info("COMFORTABLE_INSTALL: %d file(s) queued, %d already there, for %s",
             result["queued"], result["already_installed"], ", ".join(packs + workflows))
    return packs, workflows


def manager_busy(status):
    """Whether ComfyUI-Manager's install queue is still working (both Manager flavors)."""
    if not isinstance(status, dict) or status.get("error"):
        return False
    total, done = status.get("total_count") or 0, status.get("done_count") or 0
    return bool(status.get("is_processing") or status.get("in_progress_count") or status.get("pending_count")
                or (total and done < total))
