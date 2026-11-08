#!/usr/bin/env python3
"""Check and publish the "Suggested by AI" catalog (catalog/catalog.json + catalog/workflows/).

  python tools/catalog.py check            validate the catalog: ids, references, folders, graphs
  python tools/catalog.py verify [--fix]   look every file up on Hugging Face / Civitai (size, sha256);
                                           --fix writes the real values back into catalog.json
  python tools/catalog.py previews         refresh sample images / videos: each pack's Civitai gallery,
                                           official template thumbnails for starters and official models
  python tools/catalog.py publish          write it to MongoDB (MONGO_URI), where every dashboard reads it

verify and previews use CIVITAI_TOKEN / HF_TOKEN from the environment when set (mature Civitai
models and their galleries need it).
publish replaces the catalog collections in COMFORTABLE_MONGO_DB (default "comfortable"): documents
that are no longer in the catalog get tombstones, so dashboards drop them on their next sync.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
sys.path.insert(0, str(ROOT / "dashboard"))
from comfortable import config, schema  # noqa: E402

UA = {"User-Agent": "Comfortable-catalog/1"}
HF = re.compile(r"https://huggingface\.co/([^/]+/[^/]+)/resolve/([^/]+)/(.+)")
CIVITAI = re.compile(r"https://civitai\.(?:com|red)/api/download/models/(\d+)")
TASKS = {"t2i", "edit", "pose", "controlnet", "upscale", "style", "detail", "inpaint", "layout", "angles", "cutout", "caption",
         "i2v", "t2v", "flf2v", "lipsync", "video", "audio", "3d"}
VIDEO_TASKS = {"i2v", "t2v", "flf2v", "lipsync", "video"}
# Thumbnails of ComfyUI's official templates, from the workflow_templates release the starters were built from.
TEMPLATES_REF = "v0.11.103"
TEMPLATE_MEDIA = "https://cdn.jsdelivr.net/gh/Comfy-Org/workflow_templates@{ref}/templates/{name}-1.webp"
# Sample media: a few safe and a few mature items per pack. Civitai flags minors and real people
# (minor / poi) and those are never used. A sample whose prompt has a word that could read as young
# is never used either (strict on purpose: "young woman" and "petite" go too), and mature samples,
# like every sample of an 18+ model, are only used when their prompt is known.
# The dashboard's live fallback (dashboard/ui/src/lib/media.js) applies the same YOUTHFUL screen.
MAX_SAFE, MAX_MATURE = 4, 4
MATURE = 4  # Civitai nsfwLevel: 1 PG, 2 PG-13, 4 R, 8 X, 16 XXX, 32 blocked
YOUTHFUL = re.compile(r"\b(loli\w*|shota\w*|child\w*|kids?|toddler|underage|minor|preteen|teen\w*|baby|infant|"
                      r"young(?:er|est)?|youthful|little|tiny|petite|flat[ -]?chest\w*|small (?:breasts?|body|chest)|"
                      r"school\w*|student|uniform|chibi|cute girl|innocent|kawaii|aged? down|age[ -]?regression)\b", re.I)


def load():
    return json.loads((CATALOG / "catalog.json").read_text(encoding="utf-8"))


def save(data):
    (CATALOG / "catalog.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def graph_models(graph):
    """(node, model path) for every model file an active node of the workflow uses, subgraphs and
    their exposed panels included. ComfyUI checks all of them before it runs, even on switched-off
    branches; bypassed and muted nodes (mode 4 / 2) are skipped."""
    subs = (graph.get("definitions") or {}).get("subgraphs") or []
    for g in [graph] + subs:
        for n in g.get("nodes") or []:
            if (n.get("mode") or 0) in (2, 4):
                continue
            for v in _strings(n.get("widgets_values")):
                if v.lower().endswith(config.MODEL_EXTS) and "\n" not in v and len(v) < 300:
                    yield n, v.replace("\\", "/")


def requirements(packs, ids):
    """Pack ids plus every pack they require (recursively)."""
    out, todo = [], list(ids)
    while todo:
        pid = todo.pop(0)
        if pid in out or pid not in packs:
            continue
        out.append(pid)
        todo += packs[pid].get("requires") or []
    return out


def problems(data):
    """Everything wrong with the catalog, as readable lines (empty = fine)."""
    out = []
    cats = {c["id"] for c in data["categories"]}
    packs = {p["id"]: p for p in data["packs"]}
    if len(packs) != len(data["packs"]):
        out.append("duplicate pack ids")
    for p in data["packs"]:
        where = f"pack {p['id']}"
        for c in p.get("categories") or []:
            if c not in cats:
                out.append(f"{where}: unknown category {c}")
        for r in p.get("requires") or []:
            if r not in packs:
                out.append(f"{where}: requires unknown pack {r}")
        if not p.get("files"):
            out.append(f"{where}: no files")
        if p.get("kind") in ("checkpoint", "base", "video") and not p.get("vram_gb"):
            out.append(f"{where}: no vram_gb (the GPU search would offer cards too small for it)")
        for f in p.get("files") or []:
            if config.normalize_category(f.get("category"), default="") != f.get("category"):
                out.append(f"{where}: {f.get('filename')}: unknown folder {f.get('category')}")
            if not f.get("url", "").startswith("https://"):
                out.append(f"{where}: {f.get('filename')}: no https url")
            if not f.get("size"):
                out.append(f"{where}: {f.get('filename')}: size unknown (run verify --fix)")
            if ".." in (f.get("filename") or "") or (f.get("filename") or "").startswith("/"):
                out.append(f"{where}: unsafe filename {f.get('filename')}")
    wf_ids = set()
    for w in data["workflows"]:
        where = f"workflow {w['id']}"
        if w["id"] in wf_ids:
            out.append(f"{where}: duplicate id")
        wf_ids.add(w["id"])
        if w.get("task") not in TASKS:
            out.append(f"{where}: unknown task {w.get('task')}")
        for pid in w.get("packs") or []:
            if pid not in packs:
                out.append(f"{where}: unknown pack {pid}")
        g = CATALOG / (w.get("graph") or "")
        if not w.get("graph") or not g.is_file():
            out.append(f"{where}: graph file {w.get('graph')} missing")
            continue
        api_doc = g.with_name(g.name.removesuffix(".json") + ".api.json")
        try:
            made_from = json.loads(api_doc.read_text(encoding="utf-8")).get("graph_sha256")
        except (OSError, ValueError):
            made_from = None
        if made_from != hashlib.sha256(g.read_bytes()).hexdigest():
            out.append(f"{where}: {api_doc.name} is missing or older than the graph (the Create screen runs it): "
                       "uv run --script tools/starter_api.py " + w["id"])
        installs = {f["filename"].lower() for rid in requirements(packs, w.get("packs") or []) for f in packs[rid]["files"]}
        for node, name in graph_models(json.loads(g.read_text(encoding="utf-8"))):
            if name.lower() not in installs:
                out.append(f"{where}: node {node.get('id')} ({node.get('type')}) uses {name}, which none of its packs install there")
    for p in data["packs"]:
        for wid in p.get("workflows") or []:
            if wid not in wf_ids:
                out.append(f"pack {p['id']}: unknown workflow {wid}")
    for kind, items in (("pack", data["packs"]), ("workflow", data["workflows"])):
        for it in items:
            for m in it.get("previews") or []:
                if not str(m.get("url", "")).startswith("https://") or m.get("type") not in ("image", "video") \
                        or not isinstance(m.get("nsfw_level"), int):
                    out.append(f"{kind} {it['id']}: bad preview {m}")
    return out


def hf_meta(url, token):
    m = HF.match(url)
    if not m:
        return None
    repo, rev, path = m.group(1), m.group(2), urllib.parse.unquote(m.group(3))
    folder = os.path.dirname(path)
    r = requests.get(f"https://huggingface.co/api/models/{repo}/tree/{rev}/{urllib.parse.quote(folder)}",
                     headers={**UA, **({"Authorization": f"Bearer {token}"} if token else {})}, timeout=30)
    if r.status_code != 200:
        return {"error": f"HF {r.status_code}"}
    for e in r.json():
        if e.get("path") == path:
            return {"size": e.get("size") or 0, "sha256": (e.get("lfs") or {}).get("oid") or "", "hf": {"repo": repo, "revision": rev, "path": path}}
    return {"error": "not in the repository"}


def civitai_meta(url, token):
    m = CIVITAI.match(url)
    if not m:
        return None
    vid = int(m.group(1))
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    r = requests.get(f"https://civitai.com/api/v1/model-versions/{vid}",
                     headers={**UA, **({"Authorization": f"Bearer {token}"} if token else {})}, timeout=30)
    if r.status_code != 200:
        return {"error": f"Civitai {r.status_code}"}
    d = r.json()
    files = d.get("files") or []
    f = next((x for x in files if str(x.get("id")) == q.get("fileId")), None) or next((x for x in files if x.get("primary")), files[0] if files else None)
    if not f:
        return {"error": "no files"}
    return {"size": int(float(f.get("sizeKB") or 0) * 1024), "sha256": ((f.get("hashes") or {}).get("SHA256") or "").lower(),
            "civitai": {"model_id": d.get("modelId"), "version_id": vid, "file_id": f.get("id")}, "remote_name": f.get("name")}


def civitai_media(version_id, token, strict=False):
    """Sample images / videos of a Civitai model version (the creator's gallery), or None.
    strict (18+ models): safe samples need a known, clean prompt too."""
    r = requests.get(f"https://civitai.com/api/v1/model-versions/{version_id}",
                     headers={**UA, **({"Authorization": f"Bearer {token}"} if token else {})}, timeout=30)
    if r.status_code != 200:
        return None
    out = []
    for im in r.json().get("images") or []:
        level = int(im.get("nsfwLevel") or 1)
        if not im.get("url") or im.get("minor") or im.get("poi") or level >= 32:
            continue
        prompt = str((im.get("meta") or {}).get("prompt") or "").strip()
        if YOUTHFUL.search(prompt) or (not prompt and (level >= MATURE or strict)):
            continue
        out.append({"url": im["url"], "type": "video" if im.get("type") == "video" else "image", "nsfw_level": level,
                    "width": int(im.get("width") or 0), "height": int(im.get("height") or 0)})
    return out


def pick_media(items, moving_first=False):
    """Up to MAX_SAFE safe + MAX_MATURE mature items, the creator's order kept (moving ones first for video)."""
    seen, uniq = set(), []
    for m in items:
        if m["url"] not in seen:
            seen.add(m["url"])
            uniq.append(m)
    key = (lambda m: not (m["type"] == "video" or m.get("animated"))) if moving_first else (lambda m: 0)
    safe = sorted((m for m in uniq if m["nsfw_level"] < MATURE), key=key)
    mature = sorted((m for m in uniq if m["nsfw_level"] >= MATURE), key=key)
    return safe[:MAX_SAFE] + mature[:MAX_MATURE]


def template_media(name):
    """The official template's thumbnail (an animated WebP for video templates), or None."""
    url = TEMPLATE_MEDIA.format(ref=TEMPLATES_REF, name=name)
    try:
        r = requests.get(url, headers={**UA, "Range": "bytes=0-63"}, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code not in (200, 206) or r.content[:4] != b"RIFF" or r.content[8:12] != b"WEBP":
        return None
    # VP8X chunk flags: bit 1 = animation. Dimensions are 24-bit, minus one.
    head = r.content
    animated = head[12:16] == b"VP8X" and bool(head[20] & 0x02)
    width = (int.from_bytes(head[24:27], "little") + 1) if head[12:16] == b"VP8X" else 0
    height = (int.from_bytes(head[27:30], "little") + 1) if head[12:16] == b"VP8X" else 0
    return {"url": url, "type": "image", "nsfw_level": 1, "width": width, "height": height, "animated": animated, "source": "template"}


def cmd_previews(a):
    data = load()
    token = os.environ.get("CIVITAI_TOKEN", "")
    recipes = json.loads((CATALOG / "starters.json").read_text(encoding="utf-8")) if (CATALOG / "starters.json").is_file() else []
    # starter -> official template (a starter built from one of ours, "catalog:<id>", has no template thumbnail;
    # nor does one whose recipe says "thumbnail": false, like the style starters: the base model's picture
    # doesn't show their look, their style LoRA's samples do)
    templates = {r["id"]: r["base"] for r in recipes if r.get("id") and r.get("base") and not r["base"].startswith("catalog:")
                 and r.get("thumbnail", True)}
    video_packs = {pid for w in data["workflows"] if w.get("task") in VIDEO_TASKS or "video" in w["id"] for pid in w.get("packs") or []}
    thumbs = {}
    for w in data["workflows"]:
        name = templates.get(w["id"])
        if name and name not in thumbs:
            thumbs[name] = template_media(name)
        w["previews"] = [thumbs[name]] if name and thumbs.get(name) else []
    media = {}
    for p in data["packs"]:
        if p.get("component"):
            continue
        items = []
        for vid in dict.fromkeys(f["civitai"]["version_id"] for f in p["files"] if (f.get("civitai") or {}).get("version_id")):
            got = civitai_media(vid, token, strict=bool(p.get("nsfw")))
            if got is None:
                print(f"  ✗ {p['id']}: Civitai version {vid} not readable")
            items += got or []
            time.sleep(0.2)
        media[p["id"]] = items
    # Official models have no Civitai gallery: each official template's thumbnail goes to one model of
    # its starter, the first that has no sample yet (single-model starters first, where it is obviously
    # that model's), so two circles never show the same picture.
    # Hugging Face models (no Civitai file, so no gallery): the picture from their model card (`preview`).
    # Never for Civitai models: their samples must pass the screen above, which `preview` didn't.
    for p in data["packs"]:
        pv = p.get("preview") or {}
        civitai = any((f.get("civitai") or {}).get("version_id") for f in p["files"])
        if p["id"] in media and not media[p["id"]] and not civitai and pv.get("url", "").startswith("https://huggingface.co/"):
            media[p["id"]] = [{"url": pv["url"], "type": "video" if pv["url"].lower().endswith((".mp4", ".webm")) else "image",
                               "nsfw_level": pv.get("nsfw_level") or 1, "source": "card"}]
    gallery = {pid for pid, items in media.items() if items}
    for w in sorted(data["workflows"], key=lambda w: len(w.get("packs") or [])):
        cands = [pid for pid in w.get("packs") or [] if pid in media and pid not in gallery]
        if w["previews"] and cands:
            owner = next((pid for pid in cands if not media[pid]), cands[0])
            media[owner] += w["previews"]
    missing = 0
    for p in data["packs"]:
        p.pop("previews", None)
        if p["id"] not in media:
            continue
        p["previews"] = pick_media(media[p["id"]], moving_first=p.get("kind") == "video" or p["id"] in video_packs)
        if not p["previews"]:
            missing += 1
            p.pop("previews")
    save(data)
    with_media = sum(1 for p in data["packs"] if p.get("previews"))
    print(f"previews: {with_media} packs with samples, {missing} without (tools, upscalers, ...), "
          f"{sum(1 for w in data['workflows'] if w['previews'])}/{len(data['workflows'])} starters with a template thumbnail")
    return 0


def cmd_check(_a):
    data = load()
    issues = problems(data)
    for line in issues:
        print("  " + line)
    print(f"{len(data['packs'])} packs, {len(data['workflows'])} workflows, {len(data['categories'])} categories: "
          + ("OK" if not issues else f"{len(issues)} problem(s)"))
    return 1 if issues else 0


def cmd_verify(a):
    data = load()
    hf_token, civ_token = os.environ.get("HF_TOKEN", ""), os.environ.get("CIVITAI_TOKEN", "")
    bad = 0
    for p in data["packs"]:
        for f in p["files"]:
            meta = hf_meta(f["url"], hf_token) or civitai_meta(f["url"], civ_token)
            if meta is None:
                print(f"  ? {p['id']}: {f['filename']}: not a Hugging Face or Civitai link, skipped")
                continue
            if meta.get("error"):
                bad += 1
                print(f"  ✗ {p['id']}: {f['filename']}: {meta['error']}")
                continue
            diff = [k for k in ("size", "sha256") if meta.get(k) and f.get(k) != meta[k]]
            if diff:
                print(f"  ~ {p['id']}: {f['filename']}: {', '.join(f'{k} {f.get(k)} -> {meta[k]}' for k in diff)}")
            if a.fix:
                f.update({k: meta[k] for k in ("size", "sha256", "civitai", "hf") if meta.get(k)})
            time.sleep(0.15)
    if a.fix:
        save(data)
        print("catalog.json updated")
    print("verify:", "OK" if not bad else f"{bad} file(s) not found")
    return 1 if bad else 0


def cmd_publish(a):
    data = load()
    issues = problems(data)
    if issues and not a.force:
        print("Not publishing, the catalog has problems (see `check`):")
        for line in issues:
            print("  " + line)
        return 1
    uri = os.environ.get("MONGO_URI") or (Path(a.uri_file).read_text().strip() if a.uri_file else "")
    if not uri:
        print("Set MONGO_URI (or --uri-file)")
        return 1
    import certifi
    from pymongo import MongoClient, ReplaceOne
    if a.public_dns:
        import dns.resolver
        dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
        dns.resolver.default_resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
    db = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=15000)[os.environ.get("COMFORTABLE_MONGO_DB", "comfortable")]
    now = time.time()
    docs = {
        "catalog_categories": data["categories"],
        "catalog_packs": data["packs"],
        "catalog_workflows": [{**w, "graph": json.loads((CATALOG / w["graph"]).read_text(encoding="utf-8"))} for w in data["workflows"]],
    }
    for coll, items in docs.items():
        db[coll].create_index("id", unique=True, name="id_unique")
        db[coll].create_index("mtime", name="mtime")
        ops = [ReplaceOne({"id": d["id"]}, {**d, "v": schema.VERSION, "mtime": now}, upsert=True) for d in items]
        keep = [d["id"] for d in items]
        gone = [d["id"] for d in db[coll].find({"id": {"$nin": keep}, "deleted": {"$ne": True}}, {"id": 1})]
        ops += [ReplaceOne({"id": i}, {"id": i, "deleted": True, "v": schema.VERSION, "mtime": now}) for i in gone]
        if ops:
            db[coll].bulk_write(ops, ordered=False)
        print(f"  {coll}: {len(items)} published" + (f", {len(gone)} removed" if gone else ""))
    db.meta.replace_one({"id": "catalog"}, {"id": "catalog", "version": data["version"], "published_at": int(now), "v": schema.VERSION,
                                            "mtime": now, "counts": {k: len(v) for k, v in docs.items()}}, upsert=True)
    print(f"catalog {data['version']} published to {db.name}")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    v = sub.add_parser("verify")
    v.add_argument("--fix", action="store_true")
    v.set_defaults(fn=cmd_verify)
    sub.add_parser("previews").set_defaults(fn=cmd_previews)
    pub = sub.add_parser("publish")
    pub.add_argument("--uri-file", help="file holding the MongoDB URI (instead of MONGO_URI)")
    pub.add_argument("--public-dns", action="store_true", help="resolve mongodb+srv through 8.8.8.8 (for routers that drop SRV queries)")
    pub.add_argument("--force", action="store_true", help="publish even when check finds problems")
    pub.set_defaults(fn=cmd_publish)
    a = p.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
