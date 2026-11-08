"""Document shapes of database schema v3 (see docs/database.md).

Every document has `id` (unique in its collection), `v` (schema version) and `mtime` (when it was
last written, set by the store). normalize(coll, doc) turns any stored document into its v3
shape, filling defaults, so the rest of the code can rely on every field being there.
"""
import re

from . import config

VERSION = 3


def _list(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def library(d):
    """A saved model file."""
    url = (d.get("url") or "").strip()
    out = {
        "id": str(d["id"]),
        "name": d.get("name") or d.get("filename") or "Untitled",
        "url": url,
        "source": d.get("source") or ("civitai" if "civitai." in url else "hf" if "huggingface.co" in url else "url"),
        # ComfyUI reads unet/ and clip/ as diffusion_models/ and text_encoders/: store the real folder.
        "category": config.canonical_category(d.get("category")) or "loras",
        "filename": (d.get("filename") or "").replace("\\", "/"),
        "aliases": _list(d.get("aliases")),
        "size": _int(d.get("size")),
        "sha256": (d.get("sha256") or "").lower(),
        "preview": d.get("preview") or "",
        "preview_mature": bool(d.get("preview_mature")),
        "trigger_words": _list(d.get("trigger_words")),
        "base_model": d.get("base_model") or "",
        "type": d.get("type") or "",
        "nsfw": bool(d.get("nsfw")),
        "tags": _list(d.get("tags")),
        "page_url": d.get("page_url") or "",
        "bundle_ids": _list(d.get("bundle_ids")),
        "auto_install": bool(d.get("auto_install")),
        "notes": d.get("notes") or "",
        # Where it was saved from: manual, fixer, catalog:<pack id>, migrated.
        "origin": d.get("origin") or "manual",
        "created_at": _int(d.get("created_at")),
        "updated_at": _int(d.get("updated_at") or d.get("created_at")),
    }
    for key in ("civitai", "hf"):
        if isinstance(d.get(key), dict) and d[key]:
            out[key] = d[key]
    if d.get("source_missing"):
        out["source_missing"] = True
    if d.get("meta_checked_at"):
        out["meta_checked_at"] = _int(d["meta_checked_at"])
    if out["source"] == "civitai" and "civitai" not in out:
        m = re.search(r"(?:/api/download/models/|modelVersionId=)(\d+)", url)
        if m:
            out["civitai"] = {"version_id": int(m.group(1))}
    return out


def bundle(d):
    """A named group of library items (membership lives on library.bundle_ids)."""
    return {
        "id": str(d["id"]),
        "name": d.get("name") or "Untitled",
        "icon": d.get("icon") or "📁",
        "description": d.get("description") or "",
        "tags": _list(d.get("tags")),
        "auto_install": bool(d.get("auto_install")),
        # user, or catalog:<pack id> when saved from a suggestion.
        "origin": d.get("origin") or "user",
        "created_at": _int(d.get("created_at")),
        "updated_at": _int(d.get("updated_at") or d.get("created_at")),
    }


NORMALIZERS = {"library": library, "bundles": bundle}


def normalize(coll, doc):
    fn = NORMALIZERS.get(coll)
    out = fn(doc) if fn else {k: v for k, v in doc.items() if k != "_id"}
    out["v"] = VERSION
    if doc.get("mtime"):
        out["mtime"] = doc["mtime"]
    return out
