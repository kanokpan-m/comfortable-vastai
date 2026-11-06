"""Custom node versions: pin them in bundles, and check a pack's Python requirements first.

A workflow that works today can break when a node pack it uses changes. When a
bundle is made from a workflow, every custom node pack the workflow uses is
recorded with its git commit (ComfyUI's /object_info says which custom_nodes
folder each node type comes from; each folder is a git checkout). Installing the
bundle on another instance clones missing packs at that commit; packs already
installed at another version are reported, not changed, since other workflows
may rely on them.

Before a pack's requirements.txt is installed, pip resolves it in a dry run and
the result is compared with what is installed. A pack that would change torch,
numpy or another package ComfyUI depends on is held back with a warning instead
of breaking ComfyUI for every workflow.
"""
import asyncio
import importlib.metadata
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

from . import config
from .events import bus
from .util import log

# Changing these breaks ComfyUI or most node packs: never done without asking.
CRITICAL = {"torch", "torchvision", "torchaudio", "xformers", "numpy", "transformers", "diffusers", "safetensors",
            "accelerate", "triton", "sageattention", "pillow", "opencv-python", "opencv-python-headless", "aiohttp",
            "comfyui-frontend-package"}
_cache = {}


def custom_nodes_dir():
    return config.COMFY_DIR / "custom_nodes"


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def node_modules():
    """{node type: custom_nodes folder} for every node from a custom pack (core nodes left out)."""
    def load():
        r = requests.get(config.COMFY_URL + "/object_info", timeout=60)
        r.raise_for_status()
        out = {}
        for node_type, info in r.json().items():
            mod = (info or {}).get("python_module") or ""
            if mod.startswith("custom_nodes."):
                out[node_type] = mod.split(".", 2)[1]
        return out
    return _cached("node_modules", 600, load)


def _git(folder, *args):
    r = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    return r.stdout.strip()


def _version(folder):
    try:
        m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (folder / "pyproject.toml").read_text())
        return m.group(1) if m else ""
    except OSError:
        return ""


def pack_info(folder_name):
    """Where a custom_nodes folder came from and which commit it is at."""
    folder = custom_nodes_dir() / folder_name
    pin = {"dir": folder_name, "repository": "", "commit": "", "version": _version(folder)}
    try:
        pin["repository"] = re.sub(r"\.git$", "", _git(folder, "remote", "get-url", "origin"))
        pin["commit"] = _git(folder, "rev-parse", "HEAD")
    except Exception as exc:
        pin["note"] = f"not a git checkout ({exc})"[:160]
    return pin


def pins_for(node_types):
    """Pins for the custom node packs that provide these node types."""
    modules = node_modules()
    folders = sorted({modules[t] for t in node_types if t in modules})
    return [pack_info(f) for f in folders]


# ---- requirement conflicts ---------------------------------------------------------------------
def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_versions():
    return {_norm(d.metadata["Name"]): d.version for d in importlib.metadata.distributions() if d.metadata["Name"]}


def changes_from_report(report, installed):
    """What a pip --dry-run --report would change: [{name, installed, wanted, critical}]."""
    out = []
    for item in report.get("install") or []:
        meta = item.get("metadata") or {}
        name, wanted = _norm(meta.get("name") or ""), meta.get("version")
        if name and installed.get(name) and installed[name] != wanted:
            out.append({"name": name, "installed": installed[name], "wanted": wanted, "critical": name in CRITICAL})
    return sorted(out, key=lambda c: (not c["critical"], c["name"]))


def check_requirements(text):
    """Dry-run a requirements.txt against this Python. {changes, critical, error}."""
    lines = [l for l in text.splitlines() if l.strip() and not l.strip().startswith(("#", "-e", "--"))]
    if not lines:
        return {"changes": [], "critical": [], "error": ""}
    req = config.DATA_DIR / "req-check.txt"
    req.parent.mkdir(parents=True, exist_ok=True)
    req.write_text("\n".join(lines))
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--quiet", "--report", "-", "-r", str(req)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            return {"changes": [], "critical": [], "error": (r.stderr or "pip could not resolve the requirements").strip()[-300:]}
        changes = changes_from_report(json.loads(r.stdout or "{}"), installed_versions())
    except Exception as exc:
        return {"changes": [], "critical": [], "error": str(exc)[:300]}
    return {"changes": changes, "critical": [c for c in changes if c["critical"]], "error": ""}


def _raw_requirements(repository, commit="HEAD"):
    m = re.match(r"https://github\.com/([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?$", repository or "")
    if not m:
        return None
    r = requests.get(f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{commit or 'HEAD'}/requirements.txt", timeout=20)
    return r.text if r.ok else ""


def pack_conflicts(repository, commit="HEAD"):
    """Requirement changes installing this pack (from GitHub) would make here. Cached for an hour."""
    def load():
        text = _raw_requirements(repository, commit)
        if text is None:
            return {"changes": [], "critical": [], "error": "only GitHub packs can be checked before installing"}
        return check_requirements(text)
    return _cached(f"conflicts:{repository}@{commit}", 3600, load)


# ---- installing pinned packs ------------------------------------------------------------------
def install_pinned(pin, force=False):
    """Bring one pinned pack in. Returns a short status the UI shows as is."""
    folder = custom_nodes_dir() / pin["dir"]
    if folder.exists():
        try:
            current = _git(folder, "rev-parse", "HEAD")
        except Exception:
            return "installed (not a git checkout, version unknown)"
        if not pin.get("commit") or current == pin["commit"]:
            return "installed at the pinned version"
        return f"installed at another version ({current[:7]}, bundle pinned {pin['commit'][:7]}); left as is"
    if not pin.get("repository"):
        return "no repository recorded: install it by hand"
    tmp = folder.with_name(f".{pin['dir']}.clone")
    try:
        subprocess.run(["rm", "-rf", str(tmp)], check=False)
        _git(custom_nodes_dir(), "clone", "--quiet", pin["repository"], str(tmp))
        if pin.get("commit"):
            _git(tmp, "checkout", "--quiet", pin["commit"])
        req = tmp / "requirements.txt"
        if req.exists():
            check = check_requirements(req.read_text())
            if check["critical"] and not force:
                subprocess.run(["rm", "-rf", str(tmp)], check=False)
                return "held back: it would change " + ", ".join(f"{c['name']} {c['installed']} → {c['wanted']}" for c in check["critical"])
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)], capture_output=True, text=True, timeout=1800)
            if r.returncode:
                subprocess.run(["rm", "-rf", str(tmp)], check=False)
                return "requirements failed: " + (r.stderr or "").strip()[-200:]
        tmp.rename(folder)
        if (folder / "install.py").exists():
            subprocess.run([sys.executable, "install.py"], cwd=folder, capture_output=True, timeout=1800)
        _cache.pop("node_modules", None)
        log.info("Installed node pack %s at %s", pin["dir"], (pin.get("commit") or "HEAD")[:7])
        return "installed, restart ComfyUI"
    except Exception as exc:
        subprocess.run(["rm", "-rf", str(tmp)], check=False)
        return f"install failed: {exc}"[:240]


def install_bundle_nodes(bundle, force=False):
    return {pin["dir"]: install_pinned(pin, force) for pin in bundle.get("nodes") or []}


_tasks = set()


def start(bundle, force=False):
    """Install a bundle's pinned packs in the background; a "bundle-nodes" event reports the outcome."""
    if not bundle.get("nodes"):
        return False

    async def run():
        try:
            results = await asyncio.to_thread(install_bundle_nodes, bundle, force)
        except Exception as exc:
            results = {"error": str(exc)[:200]}
        bus.publish("bundle-nodes", {"bundle": bundle["id"], "name": bundle.get("name"), "results": results,
                                     "restart_needed": any(v.startswith("installed, restart") for v in results.values())})
    task = asyncio.get_running_loop().create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True
