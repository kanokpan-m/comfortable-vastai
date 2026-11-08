#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3,<3", "requests>=2.31"]
# ///
"""Comfortable MCP server: lets an AI assistant set up ComfyUI on Vast.ai correctly and fast.

It finds setups in the curated catalog (starter workflows + model packs), plans and installs them
in one call (exact files and sub-folders, node packs through ComfyUI-Manager, Civitai key checks),
watches the downloads, opens starters in ComfyUI, checks and fixes any workflow, searches
Civitai / Hugging Face / ComfyUI-Manager, manages bundles, and finds, rents and manages GPUs with
the same ranking as the `comfortable` CLI (this file reuses tools/comfortable.py).

  uv run tools/comfortable_mcp.py          (stdio; uv installs `mcp` and `requests` itself)
  claude mcp add comfortable --scope user -- uv run --script <repo>/tools/comfortable_mcp.py

Which dashboard it talks to (docs/mcp.md):
  - COMFORTABLE_DASHBOARD_URL, e.g. http://localhost:17890 (a `comfortable tunnel`), a local
    dashboard, or ComfyUI's proxy http://localhost:8188/comfortable; COMFORTABLE_COMFY_URL for
    ComfyUI's own address when it can't be worked out;
  - otherwise your running Vast instance (the `vastai` CLI with your API key, and your SSH key
    added at vast.ai): an SSH tunnel to its dashboard and ComfyUI is opened and kept open.
Nothing here prints to stdout (it carries the MCP protocol); renting, stopping, starting and
destroying need confirm=true, which the assistant may only pass after the user said yes.
"""
import argparse
import asyncio
import atexit
import functools
import importlib.util
import inspect
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Annotated, Any, Literal

import requests
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

def _load_cli():
    """tools/comfortable.py, loaded by path: the dashboard's package is also called `comfortable`."""
    path = Path(__file__).resolve().parent / "comfortable.py"
    for name in ("comfortable_cli", "comfortable"):
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, "__file__", None) and Path(mod.__file__).resolve() == path:
            return mod
    spec = importlib.util.spec_from_file_location("comfortable_cli", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["comfortable_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


cli = _load_cli()

VERSION = "3.0.0"
DASH_PORT, COMFY_PORT = 17890, 18188  # on the instance
SSH_OPTS = ["-o", "LogLevel=ERROR", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes"]
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
OFFER_TTL = 1800  # an offer shown more than 30 minutes ago must be looked up again before renting
JSON = dict[str, Any]

if NO_WINDOW:
    class _Subprocess:
        """subprocess for the CLI code, minus the console window Windows opens for each child."""

        def __getattr__(self, name):
            return getattr(subprocess, name)

        @staticmethod
        def run(*args, **kw):
            return subprocess.run(*args, **{**NO_WINDOW, **kw})

        @staticmethod
        def Popen(*args, **kw):
            return subprocess.Popen(*args, **{**NO_WINDOW, **kw})

    cli.subprocess = _Subprocess()

INSTRUCTIONS = """\
Comfortable runs ComfyUI on rented Vast.ai GPUs with a dashboard that installs models and node packs.

Set up something on the connected instance:
  find_setups -> plan_install -> install_setups -> install_progress (wait) ->
  restart_comfyui if node packs were installed -> open_workflow (starters) and tell the user how to use it.
Any other workflow: check_workflow -> fix_workflow. Single models: search_models -> add_model.
Need a GPU: find_setups -> find_gpu(for_setups=[...]) -> show the user the exact offer and price ->
  only after a clear yes: rent_gpu(offer_id, confirm=true) -> wait_for_instance (it connects when ready).
Rules: rent_gpu, manage_instance (stop/start/destroy) and restart_comfyui(force) cost money or lose data or
work: run them only after the user approved that exact action. Never rent an offer the user hasn't seen,
never swap hosts on your own. Never repeat API keys or tokens. Adult content is fine for this user; real
people's likeness, minors and Krea 2 filter-bypass LoRAs are not.
Without a connection, find_setups / plan_install / check_workflow still work offline from the catalog."""

server = MCPServer("comfortable", title="Comfortable (ComfyUI on Vast.ai)", instructions=INSTRUCTIONS, version=VERSION,
                   website_url=f"https://github.com/{cli.REPO}")


# ---- plumbing ------------------------------------------------------------------------------------
def tool(name, title, description, *, read_only=False, destructive=False, idempotent=False, open_world=True):
    """Register a tool; CLI errors, SystemExit and network errors become tool errors (a stray
    SystemExit would otherwise stop the server)."""
    annotations = ToolAnnotations(title=title, readOnlyHint=read_only, destructiveHint=destructive,
                                  idempotentHint=idempotent, openWorldHint=open_world)

    def convert(exc):
        if isinstance(exc, ToolError):
            return exc
        if isinstance(exc, cli.CliError):
            return ToolError(exc.message)
        if isinstance(exc, SystemExit):
            return ToolError(f"stopped: {exc}")
        if isinstance(exc, requests.RequestException):
            return ToolError(f"network error: {exc}")
        if isinstance(exc, (OSError, ValueError, KeyError, subprocess.SubprocessError)):
            return ToolError(f"{type(exc).__name__}: {exc}")
        return None

    def deco(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def wrapped(*args, **kwargs):
                try:
                    return await fn(*args, **kwargs)
                except BaseException as exc:
                    err = convert(exc)
                    if err is None:
                        raise
                    raise err from None
        else:
            @functools.wraps(fn)
            def wrapped(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except BaseException as exc:
                    err = convert(exc)
                    if err is None:
                        raise
                    raise err from None
        server.tool(name=name, title=title, description=description, annotations=annotations, structured_output=True)(wrapped)
        return fn
    return deco


def gb(n):
    return round((n or 0) / 1e9, 2)


class Conn:
    """The dashboard this session talks to: a URL, a managed SSH tunnel to an instance, or plain SSH."""

    def __init__(self, kind, base=None, comfy=None, inst=None, proc=None):
        self.kind, self.base, self.comfy, self.inst, self.proc = kind, base, comfy, inst, proc

    @property
    def label(self):
        return f"instance {self.inst['id']} ({self.inst.get('gpu_name')})" if self.inst else self.base

    def alive(self):
        return self.proc is None or self.proc.poll() is None

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


STATE = {"conn": None, "offers": {}, "rented": {}}
_lock = threading.RLock()
HTTP = requests.Session()
HTTP.headers["User-Agent"] = f"comfortable-mcp/{VERSION}"
atexit.register(lambda: STATE["conn"] and STATE["conn"].close())


def _free_port(start):
    for port in range(start, start + 200):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise ToolError("no free local port for the SSH tunnel")


def _healthy(base, timeout=5):
    try:
        r = HTTP.get(f"{base}/api/health", timeout=timeout)
        return r.ok and r.json().get("service") == "comfortable"
    except (requests.RequestException, ValueError):
        return False


def connect_url(url):
    base = url.strip().rstrip("/").removesuffix("/api")
    if not _healthy(base, timeout=10):
        raise ToolError(f"No Comfortable dashboard answers at {base}")
    comfy = os.environ.get("COMFORTABLE_COMFY_URL")
    if not comfy and base.endswith("/comfortable"):
        comfy = base.removesuffix("/comfortable")  # ComfyUI's /comfortable proxy: ComfyUI is the parent
    if not comfy:
        try:
            internal = HTTP.get(f"{base}/api/bootstrap", timeout=10).json().get("comfy_url") or ""
            host = urllib.parse.urlparse(base).hostname
            if host in ("localhost", "127.0.0.1") and urllib.parse.urlparse(internal).hostname in ("localhost", "127.0.0.1"):
                comfy = internal
        except (requests.RequestException, ValueError):
            pass
    return Conn("url", base=base, comfy=comfy and comfy.rstrip("/"))


def connect_instance(inst):
    if inst.get("actual_status") != "running":
        raise ToolError(f"instance {inst['id']} is {inst.get('actual_status') or 'not running'}"
                        " (wait_for_instance, or manage_instance start)")
    host, port = cli.ssh_target(inst)
    local = _free_port(17990)
    comfy_local = _free_port(local + 1)
    cmd = ["ssh", "-N", *SSH_OPTS, "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
           "-L", f"127.0.0.1:{local}:127.0.0.1:{DASH_PORT}", "-L", f"127.0.0.1:{comfy_local}:127.0.0.1:{COMFY_PORT}",
           "-p", str(port), f"root@{host}"]
    errlog = tempfile.TemporaryFile()  # not a pipe: an unread pipe would block ssh once it fills
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errlog, **NO_WINDOW)
    base = f"http://127.0.0.1:{local}"
    for _ in range(40):
        if proc.poll() is not None:
            errlog.seek(0)
            err = errlog.read().decode(errors="replace").strip()[:300] or f"ssh exited with {proc.returncode}"
            break
        if _healthy(base, timeout=3):
            return Conn("tunnel", base=base, comfy=f"http://127.0.0.1:{comfy_local}", inst=inst, proc=proc)
        time.sleep(0.5)
    else:
        err = "the dashboard didn't answer through the tunnel"
        proc.terminate()
    # No tunnel (forwarding refused, dashboard still starting): talk over plain SSH instead.
    if cli.ssh(inst, f"curl -fs -m 5 http://127.0.0.1:{DASH_PORT}/api/health", timeout=40):
        return Conn("ssh", inst=inst)
    raise ToolError(f"Can't reach the dashboard on instance {inst['id']} over SSH ({err}). Is your SSH key added at "
                    "vast.ai/account? Is it still provisioning (wait_for_instance, instance_logs)?")


def get_conn(instance_id=None, dashboard_url=None, required=True):
    """The connection to use (made on first use): an explicit URL or instance, the current one, the
    COMFORTABLE_DASHBOARD_URL, or the only running instance."""
    with _lock:
        cur = STATE["conn"]
        if dashboard_url:
            new = connect_url(dashboard_url)
        elif instance_id is not None:
            if cur and cur.inst and cur.inst["id"] == int(instance_id) and cur.alive():
                new = cur
            else:
                new = connect_instance(cli.pick_instance(instance_id))
        elif cur and cur.alive():
            new = cur
        elif cur and cur.inst:
            new = connect_instance(cli.pick_instance(cur.inst["id"]))  # the tunnel dropped: reopen it
        elif os.environ.get("COMFORTABLE_DASHBOARD_URL"):
            new = connect_url(os.environ["COMFORTABLE_DASHBOARD_URL"])
        elif not required and time.time() - STATE.get("none_at", 0) < 60:
            return None  # looked a moment ago: no instance to talk to (offline answers stay fast)
        else:
            try:
                running = [i for i in cli.instances() if i.get("actual_status") == "running"]
            except cli.CliError:
                if not required:
                    STATE["none_at"] = time.time()
                    return None
                raise
            if not running and not required:
                STATE["none_at"] = time.time()
            if len(running) == 1:
                new = connect_instance(running[0])
            elif not required:
                return None
            elif not running:
                raise ToolError("Not connected to any Comfortable dashboard: you have no running instance (find_gpu, then "
                                "rent_gpu with the user's OK) and COMFORTABLE_DASHBOARD_URL isn't set")
            else:
                raise ToolError("Several instances are running; call connect with one of: "
                                + ", ".join(f"{i['id']} ({i.get('gpu_name')})" for i in running))
        if cur is not None and cur is not new:
            cur.close()
        STATE["conn"] = new
        return new


def _decode(status, text, where):
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    if status >= 400 or status == 0:
        msg = (data or {}).get("error") if isinstance(data, dict) else None
        raise ToolError(f"{where} answered {status or 'nothing'}: {msg or (text or '').strip()[:300]}")
    if data is None and text:
        raise ToolError(f"{where} sent something that isn't JSON: {text[:200]}")
    return data


def _ssh_api(inst, path, method, body, params, timeout):
    host, port = cli.ssh_target(inst)
    url = f"http://127.0.0.1:{DASH_PORT}/api/{path}" + (("?" + urllib.parse.urlencode(params)) if params else "")
    curl = (f"curl -s -m {int(timeout)} -X {method} -w '\\n%{{http_code}}' "
            + ("-H 'Content-Type: application/json' --data-binary @- " if body is not None else "") + shlex.quote(url))
    try:
        p = subprocess.run(["ssh", *SSH_OPTS, "-p", str(port), f"root@{host}", curl], capture_output=True, text=True,
                           input=json.dumps(body) if body is not None else "", timeout=timeout + 30, **NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ToolError(f"instance {inst['id']} didn't answer within {timeout + 30} s")
    if p.returncode != 0:
        raise ToolError(f"SSH to instance {inst['id']} failed: {(p.stderr or p.stdout).strip()[:300]}")
    text, _, code = p.stdout.rpartition("\n")
    return _decode(int(code) if code.strip().isdigit() else 0, text, f"The dashboard on instance {inst['id']}")


def api(path, method="GET", body=None, params=None, timeout=60, conn=None):
    """Call a dashboard route (path without /api/) and return its JSON; errors become tool errors."""
    c = conn or get_conn()
    path = path.lstrip("/").removeprefix("api/")
    if c.kind == "ssh":
        return _ssh_api(c.inst, path, method, body, params, timeout)
    for attempt in (1, 2):
        try:
            r = HTTP.request(method, f"{c.base}/api/{path}", json=body, params=params, timeout=timeout)
            return _decode(r.status_code, r.text, f"The dashboard ({c.label})")
        except requests.ConnectionError:
            if attempt == 1 and c.inst and not c.alive():
                c = get_conn(c.inst["id"])  # tunnel died: reopen once
                if c.kind == "ssh":
                    return _ssh_api(c.inst, path, method, body, params, timeout)
                continue
            raise ToolError(f"The dashboard ({c.label}) isn't answering. Is the instance still running? (list_instances, instance_logs)")


async def run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def _setup_line(it):
    return {k: it.get(k) for k in ("id", "type", "title", "kind", "base_model", "nsfw", "vram_gb", "download_gb",
                                   "needs_civitai_key", "node_packs", "categories", "summary")}


# ---- catalog: find and plan (works offline) ---------------------------------------------------------
def _catalog(conn):
    """The catalog to search: the connected dashboard's (the database copy may be newer, with install
    state), else the one in this checkout."""
    if conn:
        data = api("catalog", conn=conn, timeout=90)
        return data, "instance"
    return cli.catalog_data(), "local"


@tool("find_setups", "Find setups",
      "Search Comfortable's curated catalog of starter workflows (ready ComfyUI graphs with every model "
      "selected: text/image to video, pose transfer, ControlNet, upscalers, style transfer, edits, NSFW "
      "photo/video/hentai...) and model packs (checkpoints, LoRAs, video models, artist and style LoRAs, "
      "ControlNets, upscalers). Returns ids for plan_install / install_setups / find_gpu with VRAM, "
      "download size and whether a Civitai key is needed; when connected, also what's already installed. "
      "Call with no arguments to see the categories.", read_only=True, idempotent=True, open_world=False)
def find_setups(
        query: Annotated[str, Field(description="Words to match, e.g. 'nsfw video', 'pose', 'anime artist', 'upscale video'")] = "",
        category: Annotated[str | None, Field(description="Category id, e.g. nsfw-video, nsfw-photo, hentai, nsfw-concepts, "
                                                         "base-image, anime, edit, video, artist, stylize, realism, pose, upscale, detail, speed")] = None,
        task: Annotated[str | None, Field(description="Starter task: t2i, edit, pose, controlnet, upscale, style, detail, inpaint, layout, angles, cutout, caption, i2v, t2v, flf2v, lipsync, video, audio, 3d")] = None,
        kind: Annotated[str | None, Field(description="workflow, checkpoint, lora, video, base, controlnet, upscaler, tool, embedding")] = None,
        nsfw: Annotated[bool | None, Field(description="true: only NSFW entries, false: none, omit: both")] = None,
        max_vram_gb: Annotated[int | None, Field(description="Only what fits this much VRAM")] = None,
        limit: Annotated[int, Field(ge=1, le=60)] = 12) -> JSON:
    conn = get_conn(required=False)
    cat, source = _catalog(conn)
    hits = cli.catalog_search(cat, query, task=task, category=category, nsfw=nsfw, max_vram_gb=max_vram_gb, kind=kind, limit=limit)
    out = {"catalog_version": cat.get("version"), "source": source, "results": [_setup_line(h) for h in hits]}
    if conn:
        state = {p["id"]: p.get("state") or {} for p in cat.get("packs") or []}
        state.update({w["id"]: w.get("state") or {} for w in cat.get("workflows") or []})
        for r in out["results"]:
            s = state.get(r["id"]) or {}
            r["installed"] = bool(s.get("complete"))
            r["missing_gb"] = gb(s.get("missing_bytes"))
    if not (query or category or task or kind) or not hits:
        out["categories"] = [{"id": c["id"], "title": c.get("title"), "group": c.get("group"), "mature": bool(c.get("mature"))}
                             for c in cat.get("categories") or []]
    if not hits:
        out["hint"] = "Nothing matched; try fewer words, a category id, or search_models for anything outside the catalog."
    return out


@tool("get_setup", "Setup details",
      "Everything about one catalog entry: for a starter workflow its steps (how to use it), inputs to load, "
      "packs, node packs and files; for a pack its files, recommended settings (steps, CFG, sampler, "
      "resolution, LoRA strength), trigger words, what it works with and which starters use it.",
      read_only=True, idempotent=True, open_world=False)
def get_setup(setup_id: Annotated[str, Field(description="A pack or workflow id from find_setups")]) -> JSON:
    conn = get_conn(required=False)
    cat, source = _catalog(conn)
    packs = {p["id"]: p for p in cat.get("packs") or []}
    wfs = {w["id"]: w for w in cat.get("workflows") or []}
    item = wfs.get(setup_id) or packs.get(setup_id)
    if not item:
        raise ToolError(f"No catalog entry {setup_id!r}: find ids with find_setups")
    needs = cli.catalog_needs(cat, [setup_id])
    files = [{"name": f.get("name"), "path": f"{f['category']}/{f['filename']}", "size_gb": gb(f.get("size")),
              "needs_civitai_key": bool(f.get("needs_token")), "pack": f["pack"]} for f in needs["files"]]
    common = {"id": item["id"], "title": item["title"], "nsfw": bool(item.get("nsfw")), "categories": item.get("categories") or [],
              "summary": item.get("summary"), "download_gb": needs["download_gb"], "vram_gb": needs["vram_gb"],
              "needs_civitai_key": needs["needs_token"], "node_packs": needs["node_packs"], "files": files,
              "catalog_version": cat.get("version"), "source": source,
              "previews": [p.get("url") for p in (item.get("previews") or [])[:3] if p.get("url")]}
    if setup_id in wfs:
        return {**common, "type": "workflow", "task": item.get("task"), "steps": item.get("steps") or [],
                "inputs": item.get("inputs") or [],
                "packs": [{"id": p, "title": packs[p]["title"], "kind": packs[p].get("kind")} for p in needs["packs"] if p in packs]}
    return {**common, "type": "pack", "kind": item.get("kind"), "base_model": item.get("base_model"), "why": item.get("why"),
            "settings": item.get("settings") or {}, "trigger_words": item.get("trigger_words") or [],
            "works_with": item.get("works_with"), "requires": item.get("requires") or [],
            "used_by_starters": [w["id"] for w in wfs.values() if setup_id in (w.get("packs") or [])],
            "links": [l.get("url") for l in item.get("links") or [] if l.get("url")]}


@tool("plan_install", "Plan an install",
      "What installing catalog setups takes, without downloading anything: every file with its size and "
      "whether it's already on disk or downloading, node packs, total download, free disk, VRAM needed vs "
      "the GPU, and warnings (Civitai key missing, not enough disk, node packs need a ComfyUI restart). "
      "Works offline (sizes and VRAM only) when no instance is connected, e.g. before renting.",
      read_only=True, idempotent=True, open_world=False)
def plan_install(setup_ids: Annotated[list[str], Field(description="Pack and/or workflow ids from find_setups", min_length=1)],
                 include_optional: Annotated[bool, Field(description="Also optional files (alternative precisions, extras)")] = False) -> JSON:
    conn = get_conn(required=False)
    if not conn:
        needs = cli.catalog_needs(cli.catalog_data(), setup_ids, include_optional)
        return {"connected": False, "note": "Not connected to an instance: sizes and VRAM from the catalog, install state unknown.",
                "packs": needs["packs"], "workflows": needs["workflows"], "download_gb": needs["download_gb"],
                "vram_gb": needs["vram_gb"], "needs_civitai_key": needs["needs_token"], "node_packs": needs["node_packs"],
                "files": [{"path": f"{f['category']}/{f['filename']}", "size_gb": gb(f.get("size")),
                           "needs_civitai_key": bool(f.get("needs_token"))} for f in needs["files"]]}
    p = api("catalog/plan", "POST", {"ids": setup_ids, "optional": include_optional}, conn=conn, timeout=120)
    return {"connected": True, "target": conn.label, "ready": p["ready"], "warnings": p["warnings"],
            "download_gb": gb(p["bytes_needed"]), "total_gb": gb(p["bytes_total"]), "disk_free_gb": gb(p["disk_free"]),
            "fits_disk": p["fits_disk"], "vram_gb": p["vram_gb"], "gpu": p.get("gpu"), "fits_vram": p.get("fits_vram"),
            "needs_civitai_key": p["needs_token"], "civitai_key_set": p["civitai_token_set"],
            "files": [{"path": f"{f['category']}/{f['filename']}", "size_gb": gb(f["size"]),
                       "state": "installed" if f["installed"] else "downloading" if f["downloading"] else "missing",
                       "needs_civitai_key": f["needs_token"], "pack": f["pack"]} for f in p["files"]],
            "node_packs": p["node_packs"], "workflows": p["workflows"], "packs": p["packs"]}


# ---- install on the connected instance --------------------------------------------------------------
def _task_line(t):
    return {"id": t["id"], "file": f"{t['category']}/{t['filename']}", "status": t["status"], "size_gb": gb(t.get("size")),
            **({"error": t["error"]} if t.get("error") and t["status"] != "done" else {})}


@tool("install_setups", "Install setups",
      "Install catalog packs and starter workflows on the connected instance in one call: queues every "
      "missing file (and the packs they require) with verified checksums, installs missing node packs "
      "through ComfyUI-Manager, and by default saves the starters into ComfyUI's Workflows sidebar. "
      "Files already on disk are skipped, so it's safe to repeat. Follow with install_progress.",
      idempotent=True)
def install_setups(
        setup_ids: Annotated[list[str], Field(description="Pack and/or workflow ids from find_setups", min_length=1)],
        include_optional: bool = False,
        save_to_comfyui: Annotated[bool, Field(description="Save starter workflows into ComfyUI (Workflows > Comfortable)")] = True,
        save_as_bundle: Annotated[bool, Field(description="Also save them to the library as bundles")] = False,
        auto_install_next_time: Annotated[bool, Field(description="With save_as_bundle: every new instance installs them at boot")] = False,
        instance_id: Annotated[int | None, Field(description="Default: the connected instance")] = None) -> JSON:
    conn = get_conn(instance_id)
    r = api("catalog/install", "POST", {"ids": setup_ids, "optional": include_optional, "to_comfy": save_to_comfyui,
                                       "save_bundle": save_as_bundle or auto_install_next_time,
                                       "auto_install": auto_install_next_time}, conn=conn, timeout=180)
    out = {"target": conn.label, "queued": r["queued"], "already_installed": r["already_installed"],
           "download_gb": gb(r["bytes_queued"]), "task_ids": [t["id"] for t in r["tasks"] if t["status"] != "done"],
           "tasks": [_task_line(t) for t in r["tasks"]], "node_packs": r["node_packs"], "restart_needed": r["restart_needed"],
           "errors": r["errors"], "bundles": r.get("bundles") or [], "saved_to_comfyui": r.get("saved_to_comfy") or []}
    out["next"] = ("install_progress(task_ids, wait_seconds=300) until finished"
                   + ("; then restart_comfyui to load the new node packs" if r["restart_needed"] else "")
                   + ("; then open_workflow" if r.get("workflows") else ""))
    return out


@tool("install_progress", "Install progress",
      "Progress of downloads on the connected instance (default: everything running or finished in the "
      "last hour), the ComfyUI-Manager node-pack queue, and the boot-time install of a new instance. "
      "wait_seconds > 0 keeps watching (with progress updates) until all downloads finish or time is up.",
      read_only=True, idempotent=True, open_world=False)
async def install_progress(
        ctx: Context,
        task_ids: Annotated[list[str] | None, Field(description="Download task ids from install_setups / add_model")] = None,
        wait_seconds: Annotated[int, Field(ge=0, le=900)] = 0,
        instance_id: int | None = None) -> JSON:
    conn = await run(get_conn, instance_id)
    params = {"ids": ",".join(task_ids)} if task_ids else None
    t0 = time.time()
    while True:
        p = await run(api, "catalog/progress", params=params, conn=conn)
        boot = p.get("boot") or {}
        busy = not p["finished"] or (boot and boot.get("step") not in (None, "done", "failed"))
        if p["bytes_total"]:
            await ctx.report_progress(p["bytes_done"], p["bytes_total"],
                                      f"{p['active']} downloading, {gb(p['bytes_done']):.1f}/{gb(p['bytes_total']):.1f} GB")
        if not busy or time.time() - t0 >= wait_seconds:
            break
        await asyncio.sleep(5)
    tasks = p["tasks"]
    out = {"finished": not busy, "counts": p["counts"], "downloaded_gb": gb(p["bytes_done"]), "total_gb": gb(p["bytes_total"]),
           "speed_mb_s": round((p["speed"] or 0) / 1e6, 1), "eta_seconds": p["eta_s"],
           "active": [_task_line(t) | {"done_gb": gb(t["done"])} for t in tasks if t["status"] not in ("done", "failed", "cancelled")],
           "failed": [_task_line(t) for t in tasks if t["status"] == "failed"],
           "node_queue": p.get("node_queue"), "boot_install": boot or None}
    if out["failed"]:
        out["hint"] = ("A failed Civitai download usually means the file needs the Civitai API key (Settings in the dashboard) "
                       "or the link moved; retry with call_dashboard_api('downloads/<id>/retry', 'POST') after fixing it.")
    return out


@tool("restart_comfyui", "Restart ComfyUI",
      "Restart ComfyUI on the connected instance, e.g. to load node packs just installed. Refuses while a "
      "generation is running or queued unless force=true (which cancels it: ask the user first).",
      destructive=False, open_world=False)
async def restart_comfyui(ctx: Context, force: bool = False, instance_id: int | None = None) -> JSON:
    conn = await run(get_conn, instance_id)
    comfy = ((await run(api, "system", conn=conn)) or {}).get("comfy") or {}
    if (comfy.get("running") or comfy.get("queue_remaining")) and not force:
        raise ToolError(f"ComfyUI is busy ({comfy.get('queue_remaining') or 1} job(s) queued or running). "
                        "Wait, or ask the user and call again with force=true.")
    result = await run(api, "comfy/restart", "POST", conn=conn, timeout=90)
    for i in range(30):  # ComfyUI takes ~20-60 s to load again
        await asyncio.sleep(3)
        await ctx.report_progress(i + 1, 30, "waiting for ComfyUI to come back")
        state = ((await run(api, "system", conn=conn)) or {}).get("comfy") or {}
        if state.get("connected") and i > 2:
            return {"restarted": True, "back_up": True, "result": result.get("result")}
    return {"restarted": True, "back_up": False, "result": result.get("result"),
            "hint": "ComfyUI hasn't reconnected yet; check status in a minute or instance_logs."}


@tool("open_workflow", "Open a starter",
      "Save a starter workflow into ComfyUI (Workflows sidebar > Comfortable) and return a link that opens "
      "it in a new ComfyUI tab, plus whether everything it needs is installed and how to use it.",
      idempotent=True, open_world=False)
def open_workflow(workflow_id: Annotated[str, Field(description="A starter workflow id (find_setups kind=workflow)")],
                  instance_id: int | None = None) -> JSON:
    conn = get_conn(instance_id)
    saved = api(f"catalog/workflows/{urllib.parse.quote(workflow_id)}/comfy", "POST", conn=conn)
    status = api(f"catalog/workflows/{urllib.parse.quote(workflow_id)}/status", conn=conn)
    wf = api(f"catalog/workflows/{urllib.parse.quote(workflow_id)}", conn=conn)
    out = {"saved_as": saved["path"], "ready": status["ready"],
           "missing_files": [f"{f['category']}/{f['filename']}" for f in status["files"] if not f["installed"]],
           "missing_node_packs": [n["title"] for n in status["nodes"] if not n["installed"]],
           "steps": wf.get("steps") or [], "inputs": wf.get("inputs") or [],
           "how_to_open": f"In ComfyUI: Workflows sidebar > {saved['path'].removesuffix('.json')}"}
    if conn.comfy:
        out["open_url"] = f"{conn.comfy}/?comfortable_open={urllib.parse.quote(workflow_id)}"
        if conn.kind == "tunnel":
            out["note"] = "open_url goes through this session's SSH tunnel: it works on this computer while the MCP server runs."
    if not status["ready"]:
        out["hint"] = "Not everything is installed yet: install_setups([workflow_id]) then install_progress."
    return out


# ---- any workflow: check and fix ---------------------------------------------------------------------
def _load_workflow(workflow_path, workflow_json, comfyui_path, conn):
    if workflow_path:
        return json.loads(Path(workflow_path).expanduser().read_text(encoding="utf-8"))
    if workflow_json:
        return json.loads(workflow_json) if isinstance(workflow_json, str) else workflow_json
    if comfyui_path:
        if not conn:
            raise ToolError("comfyui_path needs a connected instance")
        return api("workflows/comfy/raw", params={"path": comfyui_path}, conn=conn)
    raise ToolError("Give workflow_path (a .json on this computer), workflow_json, or comfyui_path (saved in ComfyUI)")


def _fix_entry(m):
    fix = m.get("fix") or {}
    cand = fix.get("candidate") or {}
    return {"file": m.get("name"), "category": m.get("category"), "status": m.get("status"), "optional": bool(m.get("optional")),
            "fix": fix.get("kind"), "source": m.get("origin") or cand.get("source"), "size_gb": gb(cand.get("size")),
            "gated": bool(cand.get("gated")), "suggestions": [p.get("name") for p in (m.get("possible") or [])[:3]]}


WorkflowPath = Annotated[str | None, Field(description="Path of a workflow .json on this computer")]
WorkflowJson = Annotated[str | dict[str, Any] | None, Field(description="The workflow itself (UI or API format), as JSON text or an object")]
ComfyuiPath = Annotated[str | None, Field(description="A workflow saved in ComfyUI, path under workflows/ (list_comfyui_workflows)")]


@tool("check_workflow", "Check a workflow",
      "Check any ComfyUI workflow against the connected instance: which models are missing (and where each "
      "can be downloaded from: Hugging Face, Civitai, the library, model lists), which node types are "
      "missing and which node pack provides them, download sizes and disk. Offline (no instance): the VRAM "
      "and download size it needs, to pick a GPU.", read_only=True, idempotent=True)
def check_workflow(workflow_path: WorkflowPath = None, workflow_json: WorkflowJson = None,
                   comfyui_path: ComfyuiPath = None, instance_id: int | None = None) -> JSON:
    conn = get_conn(instance_id, required=False) if not comfyui_path else get_conn(instance_id)
    wf = _load_workflow(workflow_path, workflow_json, comfyui_path, conn)
    if not conn:
        n = cli.workflow_needs(wf)
        return {"connected": False, "min_vram_gb": n["min_vram_gb"], "comfortable_vram_gb": n["comfortable_vram_gb"],
                "video": n["video"], "download_gb": n["download_gb"], "download_gb_with_disabled_nodes": n["download_gb_max"],
                "files": [{"file": f["name"], "kind": f["kind"], "size_gb": f["gb"], "how": f["how"], "active": f["active"]}
                          for f in n["files"]], "unknown_sizes": n["unknown"]}
    plan = api("fix/plan", "POST", {"workflow": wf}, conn=conn, timeout=180)
    s = plan["summary"]
    return {"connected": True, "target": conn.label, "summary": {
                "models_missing": s["models_missing"], "models_fixable": s["models_fixable"], "optional_missing": s.get("models_optional", 0),
                "nodes_missing": s["nodes_missing"], "nodes_fixable": s["nodes_fixable"], "download_gb": gb(s["download_bytes"]),
                "disk_free_gb": gb(s.get("disk_free"))},
            "models": [_fix_entry(m) for m in plan["models"] if m.get("status") != "installed"],
            "nodes": [{"type": n["type"], "pack": (n.get("pack") or {}).get("title"), "pack_id": (n.get("pack") or {}).get("id"),
                       "state": (n.get("pack") or {}).get("state")} for n in plan["nodes"]],
            "next": "fix_workflow with the same workflow to download what's fixable and install the node packs"}


@tool("fix_workflow", "Fix a workflow",
      "Make a workflow runnable on the connected instance: downloads every missing model a source was found "
      "for (named and placed exactly as the workflow expects), moves misplaced files, and installs the "
      "missing node packs. Models it can't find are listed for search_models / add_model. Follow with "
      "install_progress, then restart_comfyui if node packs were installed.", idempotent=True)
def fix_workflow(workflow_path: WorkflowPath = None, workflow_json: WorkflowJson = None,
                 comfyui_path: ComfyuiPath = None, include_optional: bool = False,
                 install_node_packs: bool = True, instance_id: int | None = None) -> JSON:
    conn = get_conn(instance_id)
    wf = _load_workflow(workflow_path, workflow_json, comfyui_path, conn)
    plan = api("fix/plan", "POST", {"workflow": wf}, conn=conn, timeout=180)
    todo = [m for m in plan["models"] if m.get("status") != "installed" and (m.get("fix") or {}).get("kind") in ("download", "move")
            and (include_optional or not m.get("optional")) and not ((m.get("fix") or {}).get("candidate") or {}).get("gated")]
    packs = [n["pack"]["id"] for n in plan["nodes"] if install_node_packs and n.get("pack")
             and n["pack"].get("state") not in ("enabled", "installed")]
    body = {"models": [{"filename": m.get("filename") or m.get("name"), "name": m.get("name"), "category": m.get("category"),
                        "fix": m["fix"]} for m in todo], "packs": list(dict.fromkeys(packs))}
    r = api("fix/apply", "POST", body, conn=conn, timeout=600) if body["models"] or body["packs"] else \
        {"tasks": [], "moves": [], "packs": {}, "errors": [], "restart_needed": False}
    unresolved = [_fix_entry(m) for m in plan["models"] if m.get("status") != "installed" and m not in todo
                  and (include_optional or not m.get("optional"))]
    return {"target": conn.label, "task_ids": [t["id"] for t in r["tasks"] if t["status"] != "done"],
            "tasks": [_task_line(t) for t in r["tasks"]], "moved": r["moves"], "node_packs": r["packs"],
            "restart_needed": r["restart_needed"], "errors": r["errors"], "not_fixed": unresolved,
            "next": "install_progress(task_ids, wait_seconds=300)" + ("; restart_comfyui" if r["restart_needed"] else "")
                    + ("; search_models for what wasn't found (gated files need the licence accepted on Hugging Face and an HF token)"
                       if unresolved else "")}


@tool("list_comfyui_workflows", "ComfyUI's saved workflows",
      "Workflows saved in ComfyUI on the connected instance (for check_workflow / fix_workflow comfyui_path).",
      read_only=True, idempotent=True, open_world=False)
def list_comfyui_workflows(instance_id: int | None = None) -> JSON:
    files = api("workflows/comfy", conn=get_conn(instance_id))
    return {"workflows": sorted((f["path"] for f in files), key=str.lower)}


# ---- models, node packs, bundles --------------------------------------------------------------------
@tool("search_models", "Search models",
      "Search Civitai (checkpoints, LoRAs, ... with the instance's Civitai key, NSFW included when its "
      "settings allow) or Hugging Face repos, through the connected dashboard. With hf_repo, lists that "
      "repo's model files instead. Results carry the url add_model takes.", read_only=True, idempotent=True)
def search_models(query: Annotated[str, Field(description="What to look for")] = "",
                  source: Literal["civitai", "hf"] = "civitai",
                  model_type: Annotated[str | None, Field(description="Civitai type: Checkpoint, LORA, TextualInversion, VAE, Controlnet, Upscaler, Workflows")] = None,
                  base_model: Annotated[str | None, Field(description="Civitai base model, e.g. 'Illustrious', 'Wan Video 2.2 I2V-A14B', 'Krea 2'")] = None,
                  sort: Literal["Most Downloaded", "Highest Rated", "Newest"] = "Most Downloaded",
                  hf_repo: Annotated[str | None, Field(description="owner/name: list this Hugging Face repo's files")] = None,
                  limit: Annotated[int, Field(ge=1, le=50)] = 10, instance_id: int | None = None) -> JSON:
    conn = get_conn(instance_id)
    if hf_repo:
        data = api("hf/files", params={"repo": hf_repo}, conn=conn)
        files = data.get("files") if isinstance(data, dict) else data
        return {"repo": hf_repo, "files": [{"path": f.get("path") or f.get("filename"), "size_gb": gb(f.get("size")), "url": f.get("url"),
                                           "category": f.get("category")} for f in (files or [])[:200]]}
    if source == "hf":
        data = api("search/hf", params={"q": query}, conn=conn)
        return {"results": [{"repo": i["repo"], "downloads": i["downloads"], "likes": i["likes"], "gated": i["gated"],
                             "page": i["page_url"]} for i in data["items"][:limit]],
                "next": "search_models(hf_repo=...) to list a repo's files"}
    params = {"q": query, "sort": sort}
    if model_type:
        params["types"] = model_type
    if base_model:
        params["base"] = base_model
    data = api("search/civitai", params=params, conn=conn, timeout=60)
    return {"results": [{"name": i["name"], "version": i["version_name"], "type": i["type"], "base_model": i["base_model"],
                         "category": i["category"], "file": i["filename"], "size_gb": gb(i["size"]), "nsfw": i["nsfw"],
                         "downloads": i["downloads"], "likes": i["likes"], "creator": i.get("creator"),
                         "url": f"https://civitai.com/models/{i['model_id']}?modelVersionId={i['version_id']}"}
                        for i in data["items"][:limit]]}


@tool("add_model", "Add a model",
      "Save a model to the library from a Civitai or Hugging Face link (model page, version or file URL) and "
      "download it to the right ComfyUI folder on the connected instance. category / filename override "
      "where it goes (e.g. a workflow expects a sub-folder).", idempotent=True)
def add_model(url: Annotated[str, Field(description="Civitai model/version URL or Hugging Face file URL")],
              category: Annotated[str | None, Field(description="ComfyUI models folder: checkpoints, loras, diffusion_models, vae, text_encoders, controlnet, upscale_models, ...")] = None,
              filename: Annotated[str | None, Field(description="Name inside that folder, sub-folders allowed, e.g. WAN22/model.safetensors")] = None,
              install: bool = True,
              bundle_id: Annotated[str | None, Field(description="Also put it in this bundle (list_bundles)")] = None,
              instance_id: int | None = None) -> JSON:
    conn = get_conn(instance_id)
    body = {"url": url, **({"category": category} if category else {}), **({"filename": filename} if filename else {}),
            **({"bundle_ids": [bundle_id]} if bundle_id else {})}
    item = api("library", "POST", body, conn=conn, timeout=90)
    out = {"library_id": item["id"], "name": item["name"], "path": f"{item['category']}/{item['filename']}",
           "size_gb": gb(item.get("size")), "already_in_library": bool(item.get("duplicate"))}
    if install:
        task = api(f"library/{item['id']}/install", "POST", conn=conn)
        out["task"] = _task_line(task)
    return out


@tool("search_node_packs", "Search node packs",
      "Search the custom node packs ComfyUI-Manager can install (title, registry id, repository, "
      "description), with whether each is installed.", read_only=True, idempotent=True)
def search_node_packs(query: str, limit: Annotated[int, Field(ge=1, le=40)] = 10, instance_id: int | None = None) -> JSON:
    return {"results": api("catalog/nodes", params={"q": query, "limit": limit}, conn=get_conn(instance_id), timeout=90)}


@tool("install_node_packs", "Install node packs",
      "Install custom node packs through ComfyUI-Manager (Comfy Registry ids or GitHub URLs from "
      "search_node_packs). Restart ComfyUI afterwards (restart_comfyui) to load them.", idempotent=True)
def install_node_packs(ids: Annotated[list[str], Field(min_length=1)], instance_id: int | None = None) -> JSON:
    r = api("catalog/nodes/install", "POST", {"ids": ids}, conn=get_conn(instance_id), timeout=600)
    return {**r, "next": "restart_comfyui" if r["restart_needed"] else None}


@tool("list_bundles", "List bundles",
      "The user's bundles (groups of models from the library, e.g. one per project or saved catalog pack) "
      "with how many of their models are installed on the connected instance and whether they auto-install "
      "on every new instance.", read_only=True, idempotent=True, open_world=False)
def list_bundles(instance_id: int | None = None) -> JSON:
    conn = get_conn(instance_id)
    bundles, library = api("bundles", conn=conn), api("library", conn=conn, timeout=90)
    out = []
    for b in bundles:
        items = [i for i in library if b["id"] in (i.get("bundle_ids") or [])]
        out.append({"id": b["id"], "name": b.get("name"), "description": b.get("description") or "", "origin": b.get("origin"),
                    "auto_install": bool(b.get("auto_install")), "models": len(items),
                    "installed": sum(1 for i in items if i.get("installed")),
                    "missing_gb": gb(sum(int(i.get("size") or 0) for i in items if not i.get("installed")))})
    return {"bundles": out, "library_models": len(library)}


@tool("install_bundle", "Install a bundle",
      "Download every model of a bundle that isn't on the connected instance yet; optionally switch its "
      "auto-install (every new instance installs it at boot).", idempotent=True)
def install_bundle(bundle_id: str, auto_install: Annotated[bool | None, Field(description="Set auto-install on or off; omit to leave it")] = None,
                   instance_id: int | None = None) -> JSON:
    conn = get_conn(instance_id)
    out = {}
    if auto_install is not None:
        out["auto_install"] = bool(api(f"bundles/{urllib.parse.quote(bundle_id)}", "PATCH", {"auto_install": auto_install}, conn=conn).get("auto_install"))
    r = api(f"bundles/{urllib.parse.quote(bundle_id)}/install", "POST", conn=conn, timeout=120)
    return {**out, "queued": r["queued"], "task_ids": [t["id"] for t in r["tasks"] if t["status"] != "done"],
            "tasks": [_task_line(t) for t in r["tasks"]]}


@tool("list_installed_models", "Installed models",
      "Model files on the connected instance, by ComfyUI folder (sub-folders included), filtered by folder "
      "or name.", read_only=True, idempotent=True, open_world=False)
def list_installed_models(category: str | None = None, name_contains: str | None = None,
                          instance_id: int | None = None) -> JSON:
    data = api("models", conn=get_conn(instance_id), timeout=90)
    out, total = {}, 0
    for cat, files in data.items():
        if category and cat != category:
            continue
        hits = [f for f in files if not name_contains or name_contains.lower() in f["name"].lower()]
        if hits:
            out[cat] = [{"name": f["name"], "size_gb": gb(f["size"])} for f in hits[:300]]
            total += len(hits)
    return {"files": total, "by_folder": out}


# ---- connection and status --------------------------------------------------------------------------
def _overview(conn):
    boot, sysd = api("bootstrap", conn=conn), api("system", conn=conn)
    prog = api("catalog/progress", conn=conn)
    settings, gpu = boot.get("settings") or {}, (sysd.get("gpus") or [{}])[0]
    out = {"connected_to": conn.label, "via": conn.kind, "dashboard_version": boot.get("version"),
           "database": "MongoDB" if (boot.get("store") or {}).get("mongo_connected") else "local only",
           "gpu": {"name": gpu.get("name"), "vram_gb": round((gpu.get("mem_total") or 0) / 2**30, 1),
                   "vram_used_gb": round((gpu.get("mem_used") or 0) / 2**30, 1), "util": gpu.get("util")} if gpu else None,
           "disk_free_gb": gb((sysd.get("disk") or {}).get("free")), "comfyui": sysd.get("comfy"),
           "civitai_key_set": bool(settings.get("civitai_token")), "hf_token_set": bool(settings.get("hf_token")),
           "downloads": {"active": prog["active"], "failed": prog["failed"], "eta_seconds": prog["eta_s"]},
           "boot_install": prog.get("boot")}
    if conn.kind != "ssh":
        out["dashboard_url"], out["comfyui_url"] = conn.base, conn.comfy
    if conn.inst:
        out["instance"] = {"id": conn.inst["id"], "gpu": conn.inst.get("gpu_name"), "price_per_hour": conn.inst.get("dph_total")}
    vast = sysd.get("vast") or {}
    if vast.get("spent") is not None:
        out["spent_usd"] = vast["spent"]
    return out


@tool("connect", "Connect",
      "Choose which Comfortable dashboard the other tools use: a Vast instance (an SSH tunnel is opened) or "
      "a dashboard URL. Without arguments: COMFORTABLE_DASHBOARD_URL or your only running instance. "
      "Returns the instance's state: GPU, disk, ComfyUI, downloads, keys set.", read_only=True, idempotent=True)
def connect(instance_id: Annotated[int | None, Field(description="Vast instance id (list_instances)")] = None,
            dashboard_url: Annotated[str | None, Field(description="e.g. http://localhost:17890 or http://localhost:8188/comfortable")] = None) -> JSON:
    return _overview(get_conn(instance_id, dashboard_url))


@tool("status", "Status",
      "State of the connected instance: GPU and VRAM use, disk, ComfyUI (running job, queue, last error), "
      "downloads, boot-time install, money spent.", read_only=True, idempotent=True)
def status(instance_id: int | None = None) -> JSON:
    return _overview(get_conn(instance_id))


@tool("call_dashboard_api", "Call the dashboard API",
      "Escape hatch: call any Comfortable dashboard route on the connected instance, e.g. GET 'benchmark', "
      "POST 'downloads/<id>/retry', GET 'health/host', PUT 'settings'. Prefer the dedicated tools.",
      destructive=True, open_world=False)
def call_dashboard_api(path: Annotated[str, Field(description="Route after /api/, e.g. 'downloads' or 'bundles/abc/plan'")],
                       method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET",
                       body: dict[str, Any] | None = None, instance_id: int | None = None) -> JSON:
    data = api(path, method, body, conn=get_conn(instance_id), timeout=120)
    return data if isinstance(data, dict) else {"result": data}


# ---- Vast: instances and GPUs ------------------------------------------------------------------------
def _instance_line(i):
    return {"id": i["id"], "gpu": i.get("gpu_name"), "status": i.get("actual_status"), "price_per_hour": i.get("dph_total"),
            "label": i.get("label"), "machine_id": i.get("machine_id"), "vram_gb": round((i.get("gpu_ram") or 0) / 1024),
            "disk_gb": i.get("disk_space"), "uptime_hours": round((time.time() - i["start_date"]) / 3600, 2) if i.get("start_date") else None}


@tool("list_instances", "List instances",
      "Your Vast.ai instances: id, GPU, status, price, label. with_health also asks each running one's "
      "dashboard for ComfyUI state, disk and the host check (slower).", read_only=True, idempotent=True)
def list_instances(with_health: bool = False) -> JSON:
    insts = cli.instances()
    out = [_instance_line(i) for i in insts]
    if with_health:
        for row, inst in zip(out, insts):
            if inst.get("actual_status") == "running":
                info = cli.show_status(inst, as_json=True)
                row.update({k: info.get(k) for k in ("dashboard", "comfy", "gpu_util", "health")}, disk_free_gb=gb(info.get("disk_free")))
    conn = STATE["conn"]
    return {"instances": out, "connected": conn.label if conn else None}


@tool("find_gpu", "Find a GPU",
      "Rank Vast.ai offers for the user's template by value (images per dollar, from their own benchmarks) "
      "or speed: real cost per hour (GPU + disk + the host's download fee for the models), power-limited "
      "and slow hosts and hosts that failed the host check before are left out. for_setups sizes VRAM and "
      "download from catalog ids. Read-only: show the user the offer you'd pick before rent_gpu.",
      read_only=True, idempotent=True)
def find_gpu(for_setups: Annotated[list[str] | None, Field(description="Catalog ids: sets min VRAM and download size, and what rent_gpu installs at boot")] = None,
             min_vram_gb: int | None = None,
             gpu: Annotated[str | None, Field(description="GPU model(s), comma separated, e.g. RTX_4090,RTX_5090")] = None,
             max_price: Annotated[float | None, Field(description="Max real cost in $/hour")] = None,
             rank: Literal["value", "speed"] = "value",
             disk_gb: Annotated[int, Field(ge=30, le=2000)] = 100,
             download_gb: Annotated[float | None, Field(description="GB of models to download (default from for_setups, else 20)")] = None,
             hours: Annotated[float, Field(description="Planned hours of use, spreads the download fee")] = 4,
             keep_models: Annotated[bool, Field(description="Keep models on a Vast volume that outlives instances (limits hosts)")] = False,
             allow_slow: bool = False, limit: Annotated[int, Field(ge=1, le=30)] = 8) -> JSON:
    a = argparse.Namespace(gpu=gpu, min_vram=min_vram_gb, max_price=max_price, rank=rank, disk=disk_gb, download_gb=download_gb,
                           hours=hours, allow_slow=allow_slow, refresh=False, max_download_per_tb=cli.MAX_DOWNLOAD_PER_TB,
                           max_upload_per_tb=cli.MAX_UPLOAD_PER_TB, install=",".join(for_setups or []), workflow_for=None)
    setup = cli.apply_install(a)
    if a.download_gb is None:
        a.download_gb = 20.0
    shared = cli.shared_data()
    bad = cli.bad_hosts(shared)
    machine, volume, vol_offers = None, None, {}
    if keep_models:
        volume = cli.find_volume()
        machine = volume and volume.get("machine_id")
    offers, hidden = cli.search_offers(a, machine, bad, shared)
    if keep_models and not machine:
        vol_offers = {v["machine_id"]: v for v in cli.vast("search", "volumes", "disk_space>=150", check=False) or []}
        offers = [o for o in offers if o["machine_id"] in vol_offers]
    rows = []
    for o in offers[:limit]:
        row = cli.offer_row(o)
        STATE["offers"][o["id"]] = {"row": row, "args": a, "at": time.time(), "for_setups": list(for_setups or []),
                                   "keep_models": keep_models, "volume": volume, "vol_offer": vol_offers.get(o["machine_id"]),
                                   "machine": machine}
        rows.append(row)
    out = {"offers": rows, "hidden": hidden, "filters": {"min_vram_gb": a.min_vram, "download_gb": a.download_gb, "disk_gb": a.disk,
                                                          "hours": a.hours, "rank": rank},
           "explain": "cost_per_hour = GPU + disk + download fee spread over the hours; images_per_hour = SD 1.5 512px "
                      "(speed_measured=false: estimated); host_perf = this host vs healthy hosts of the same GPU."}
    if setup:
        out["setup"] = {k: v for k, v in setup.items() if k != "files"} | {"files": len(setup["files"])}
    if keep_models:
        out["volume"] = (f"reuses your models volume {volume.get('id')} on machine {machine}" if volume else
                         "a new 150 GB models volume is created on the chosen machine (billed monthly until deleted)")
    if not rows:
        out["hint"] = "No offer matches: try another GPU, a higher max_price, allow_slow, or no keep_models."
    return out


@tool("rent_gpu", "Rent a GPU",
      "Rent exactly one offer shown by find_gpu in this session with the user's Comfortable template. COSTS "
      "MONEY: only call with confirm=true after the user clearly approved this offer and price. The offer is "
      "re-checked first (gone or pricier: nothing is rented). install (default: find_gpu's for_setups) is "
      "set up at boot. Returns at once; then wait_for_instance.", destructive=True)
def rent_gpu(offer_id: int,
             confirm: Annotated[bool, Field(description="true only after the user said yes to this exact offer")] = False,
             install: Annotated[list[str] | None, Field(description="Catalog ids to set up at boot (default: find_gpu's for_setups; [] for none)")] = None,
             bundles: Annotated[list[str] | None, Field(description="Bundle ids to auto-install at boot")] = None,
             label: str = "comfortable",
             env: Annotated[dict[str, str] | None, Field(description="Extra env vars for the instance (no spaces)")] = None) -> JSON:
    entry = STATE["offers"].get(offer_id)
    if not entry or time.time() - entry["at"] > OFFER_TTL:
        raise ToolError(f"Offer {offer_id} wasn't shown in this session (or over 30 minutes ago). Run find_gpu, show the user "
                        "the offer and price, and rent only after they say yes.")
    row = entry["row"]
    if not confirm:
        raise ToolError(f"Nothing rented. Show the user offer {offer_id}: {row['gpu']} {row['vram_gb']} GB in {row['where']} "
                        f"for about ${row['cost_per_hour']:.3f}/h, and call again with confirm=true only after a clear yes.")
    a = entry["args"]
    shared = cli.shared_data()
    offers, _ = cli.search_offers(a, entry["machine"], cli.bad_hosts(shared), shared)
    o = next((x for x in offers if x["id"] == offer_id), None)
    if not o:
        raise ToolError(f"Offer {offer_id} is gone (rented by someone else or now outside the filters). Nothing was rented: "
                        "run find_gpu again and show the user the new choice.")
    if o["_cost_h"] > row["cost_per_hour"] * 1.05 + 0.005:
        raise ToolError(f"Offer {offer_id} now costs ${o['_cost_h']:.3f}/h instead of ${row['cost_per_hour']:.3f}/h. Nothing was "
                        "rented: ask the user about the new price.")
    ids = entry["for_setups"] if install is None else install
    sets = [f"{k}={v}" for k, v in (env or {}).items()]
    env_vars = cli.instance_env(",".join(bundles or []), ",".join(ids or []), sets)
    extra = []
    if entry["keep_models"]:
        env_vars["COMFORTABLE_MODEL_VOLUME"] = cli.VOLUME_MOUNT
        if entry["volume"]:
            extra = ["--link-volume", str(entry["volume"]["id"]), "--mount-path", cli.VOLUME_MOUNT]
        elif entry["vol_offer"]:
            extra = ["--create-volume", str(entry["vol_offer"]["id"]), "--volume-size", "150", "--mount-path", cli.VOLUME_MOUNT,
                     "--volume-label", cli.VOLUME_LABEL]
    args = ["create", "instance", str(o["id"]), "--template_hash", cli.template()["hash_id"], "--disk", str(a.disk), "--label", label] + extra
    if env_vars:
        args += ["--env", " ".join(f"-e {k}={v}" for k, v in env_vars.items())]
    r = cli.vast(*args)
    iid = (r or {}).get("new_contract")
    if not iid:
        raise ToolError(f"Vast didn't rent it: {r}")
    STATE["offers"].pop(offer_id, None)  # one approval, one rental
    STATE["rented"][int(iid)] = {"machine_id": o["machine_id"], "gpu": o["gpu_name"], "measured": o["_measured"], "at": time.time()}
    return {"instance_id": iid, "gpu": o["gpu_name"], "cost_per_hour": round(o["_cost_h"], 4), "where": o.get("geolocation"),
            "installs_at_boot": ids or [], "bundles_at_boot": bundles or [],
            "next": "wait_for_instance(instance_id) - boot and provisioning take about 2-5 minutes"}


@tool("wait_for_instance", "Wait for an instance",
      "Watch a new (or restarted) instance boot: image pull, provisioning, dashboard, then the host check "
      "(VRAM, power limit, PCIe, disk, network). Connects to it when ready and benchmarks a GPU model you "
      "haven't measured (about 2 minutes, under $0.02). Returns 'waiting' if time runs out: call again. "
      "A failed or poor host is remembered and skipped by find_gpu for 30 days.", read_only=False, idempotent=True)
async def wait_for_instance(ctx: Context, instance_id: int, timeout_seconds: Annotated[int, Field(ge=10, le=900)] = 300,
                            benchmark: bool = True) -> JSON:
    info = STATE["rented"].setdefault(int(instance_id), {"at": time.time()})
    t0, phase = time.time(), "looking it up"
    while True:
        inst = await run(lambda: next((i for i in cli.instances() if i["id"] == int(instance_id)), None))
        if not inst:
            raise ToolError(f"Instance {instance_id} doesn't exist (destroyed?)")
        state, age = inst.get("actual_status"), time.time() - info["at"]
        if state != "running":
            gave_up = "stopped" in (inst.get("intended_status"), inst.get("next_state")) and age > 90
            if gave_up or state in ("exited", "offline") or age > 480:
                reason = f"never started (still {state or 'loading'} after {int(age)} s{', Vast stopped it' if gave_up else ''})"
                if inst.get("machine_id"):
                    cli.remember_bad(inst["machine_id"], inst.get("gpu_name"), f"container {reason}")
                return {"state": "failed", "instance_id": instance_id, "reason": reason,
                        "advice": "It's still billed while it exists: ask the user, then manage_instance(destroy, confirm=true) "
                                  "and find_gpu again (this machine is now skipped)."}
            phase = f"starting: {state or 'loading'} (pulling the image, booting)"
        else:
            out = await run(cli.ssh, inst, "ls /.provisioning_complete /.provisioning_failed 2>/dev/null; "
                                           f"curl -fs -m 3 http://127.0.0.1:{DASH_PORT}/api/health >/dev/null && echo DASH_OK", 30) or ""
            if "provisioning_failed" in out:
                logs = await run(cli.ssh, inst, "tail -n 30 /var/log/provisioning_comfortable.log", 30)
                return {"state": "failed", "instance_id": instance_id, "reason": "provisioning failed", "log_tail": logs,
                        "advice": "See instance_logs; destroying it needs the user's OK."}
            if "DASH_OK" in out:
                info.setdefault("dash_at", time.time())
                h = await run(cli.dash, inst, "health/host", "GET", None, 30) or {}
                if (h.get("result") and not h.get("running")) or time.time() - info["dash_at"] > 240:
                    return await _ready(ctx, inst, info, h.get("result"), benchmark)
                phase = "dashboard up; checking the host (VRAM, power, PCIe, disk, network)"
            else:
                phase = "provisioning: installing Comfortable and starting ComfyUI"
        elapsed = time.time() - t0
        await ctx.report_progress(min(elapsed, timeout_seconds), timeout_seconds, phase)
        if elapsed >= timeout_seconds:
            return {"state": "waiting", "instance_id": instance_id, "phase": phase, "seconds_since_rent": int(age),
                    "next": "call wait_for_instance again"}
        await asyncio.sleep(10)


async def _ready(ctx, inst, info, health, benchmark):
    out = {"state": "ready", "instance_id": inst["id"], "gpu": inst.get("gpu_name"),
           "host_health": health and {"score": health["score"], "warnings": health["warnings"]}}
    if health and health["score"] == "poor":
        cli.remember_bad(inst["machine_id"], inst.get("gpu_name"), "; ".join(health["warnings"]))
        out["advice"] = ("Poor host (skipped by find_gpu from now on). Tell the user; destroying it and renting another needs "
                         "their OK (manage_instance destroy, then find_gpu / rent_gpu).")
    if health is None:
        out["host_health_note"] = "The host check didn't finish in time; status or call_dashboard_api('health/host') later."
    try:
        conn = await run(get_conn, inst["id"])
        out["connected"] = conn.label
        if conn.comfy:
            out["comfyui_url"], out["dashboard_url"] = conn.comfy, conn.base
        prog = await run(api, "catalog/progress", conn=conn)
        if prog.get("boot"):
            out["boot_install"] = prog["boot"]
            out["next"] = "install_progress(wait_seconds=300) to watch the boot-time install"
    except ToolError as exc:
        out["connect_error"] = str(exc)
    if benchmark and info.get("measured") is False and (not health or health["score"] != "poor"):
        if await run(cli.dash, inst, "benchmark/run", "POST", {}) is not None:
            out["benchmark"] = f"started: no benchmark of yours for the {inst.get('gpu_name')} yet (about 2 minutes)"
    return out


@tool("manage_instance", "Stop, start or destroy",
      "stop (GPU billing stops, disk is still billed; the GPU may be taken by someone else meanwhile), start "
      "(billing resumes), or destroy (deletes the instance and everything on its disk: models, outputs; "
      "irreversible). Only with confirm=true after the user approved this exact action.", destructive=True)
def manage_instance(instance_id: int, action: Literal["stop", "start", "destroy"],
                    confirm: Annotated[bool, Field(description="true only after the user said yes to this action")] = False) -> JSON:
    inst = cli.pick_instance(instance_id)
    if not confirm:
        raise ToolError(f"Nothing done. Ask the user to confirm: {action} instance {instance_id} ({inst.get('gpu_name')}, "
                        f"{inst.get('actual_status')}, ${inst.get('dph_total') or 0:.3f}/h)"
                        + (" - this deletes its disk (models, outputs) for good" if action == "destroy" else "")
                        + "; then call again with confirm=true.")
    with _lock:
        conn = STATE["conn"]
        if conn and conn.inst and conn.inst["id"] == int(instance_id) and action != "start":
            conn.close()
            STATE["conn"] = None
    result = cli.vast(action, "instance", str(instance_id), raw=False).strip()
    return {"instance_id": instance_id, "action": action, "result": result}


@tool("instance_logs", "Instance logs",
      "The end of the provisioning log and the dashboard log on an instance (over SSH).", read_only=True, idempotent=True)
def instance_logs(instance_id: int | None = None, lines: Annotated[int, Field(ge=5, le=500)] = 60) -> JSON:
    inst = cli.pick_instance(instance_id)
    logs = {}
    for name, path in (("provisioning", "/var/log/provisioning_comfortable.log"), ("dashboard", "/var/log/comfortable.log")):
        logs[name] = cli.ssh(inst, f"tail -n {int(lines)} {path} 2>/dev/null || true", 40) or "(empty or unreachable)"
    return {"instance_id": inst["id"], **logs}


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
