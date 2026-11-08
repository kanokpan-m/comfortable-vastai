#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3,<3", "requests>=2.31", "aiohttp>=3.9"]
# ///
"""Comfortable hub: your phone's way in. Runs on your PC for now (a small always-on server later).

  uv run --script tools/comfortable_hub.py             start on port 17880, on every network of this PC
  uv run --script tools/comfortable_hub.py --set-pin   choose the PIN your phone signs in with

On the phone open http://<this PC>:17880 (same Wi-Fi; with Tailscale on both, from anywhere):
  - Start: what you want to make -> which starter workflows -> the best GPUs for them right now ->
    one tap rents the offer you saw, at that price -> live setup progress (boot, host check, model
    downloads) -> ready.
  - Your instances with their cost so far; connect, stop, start, destroy (each after a confirmation).
  - Everything else is the Comfortable dashboard of the connected instance, passed through an SSH
    tunnel, so the phone never needs the instance's portal address or token.
Renting, stopping and destroying go through the MCP server's code and rules (tools/comfortable_mcp.py):
only offers shown here in the last 30 minutes, re-checked before renting. The PIN lives hashed in
~/.comfortable/hub.json; five wrong tries lock sign-in for a while.
"""
import argparse
import asyncio
import getpass
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import sys
import time
import urllib.parse
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"
HOME = Path(os.environ.get("COMFORTABLE_HUB_HOME") or (Path.home() / ".comfortable"))
CONFIG_FILE = HOME / "hub.json"
PORT = 17880
VERSION = "1.0.0"
COOKIE = "comfortable_hub"
SESSION_DAYS = 30
MAX_TRIES, LOCK_SECONDS = 5, 300
INSTANCES_TTL = 15
# Headers that belong to one hop, not to the request or answer being passed on.
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host"}
OPEN_PATHS = {"/hub/whoami", "/hub/login"}

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/manifest+json", ".webmanifest")


def _load_mcp():
    """tools/comfortable_mcp.py (and through it tools/comfortable.py), loaded by path."""
    if "comfortable_mcp" in sys.modules:
        return sys.modules["comfortable_mcp"]
    path = Path(__file__).resolve().parent / "comfortable_mcp.py"
    spec = importlib.util.spec_from_file_location("comfortable_mcp", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["comfortable_mcp"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load_mcp()
cli = M.cli


# ---- config and PIN -------------------------------------------------------------------------------
def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def pin_hash(pin, salt):
    return hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32).hex()


def valid_pin(pin):
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 12


def set_pin(cfg, pin):
    """A new PIN also gets a new signing secret, which signs every phone out."""
    salt = secrets.token_hex(16)
    cfg.update(pin_salt=salt, pin_hash=pin_hash(pin, salt), secret=secrets.token_hex(32))


def check_pin(cfg, pin):
    if not (cfg.get("pin_hash") and cfg.get("pin_salt")) or not valid_pin(pin):
        return False
    return hmac.compare_digest(pin_hash(pin, cfg["pin_salt"]), cfg["pin_hash"])


def make_token(cfg, now=None):
    exp = int((now or time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(bytes.fromhex(cfg["secret"]), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def token_ok(cfg, token, now=None):
    try:
        exp, sig = str(token).split(".", 1)
        good = hmac.new(bytes.fromhex(cfg["secret"]), exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good) and int(exp) > (now or time.time())
    except (ValueError, KeyError, TypeError):
        return False


class Lockout:
    """Wrong PINs per address: after MAX_TRIES, sign-in is locked for LOCK_SECONDS, doubling each time."""

    def __init__(self):
        self.fails = {}

    def locked_for(self, ip, now=None):
        f = self.fails.get(ip)
        return max(0, int(f["until"] - (now or time.time()))) if f else 0

    def failed(self, ip, now=None):
        now = now or time.time()
        f = self.fails.setdefault(ip, {"n": 0, "until": 0})
        f["n"] += 1
        if f["n"] >= MAX_TRIES:
            f["until"] = now + min(3600, LOCK_SECONDS * 2 ** (f["n"] - MAX_TRIES))

    def passed(self, ip):
        self.fails.pop(ip, None)


def authed(request):
    return token_ok(request.app["cfg"], request.cookies.get(COOKIE, ""))


# ---- the hub: instances, the setup being watched ---------------------------------------------------------
class Progress:
    """Stands in for the MCP context: wait_for_instance reports its phase here."""

    def __init__(self, hub):
        self.hub = hub

    async def report_progress(self, progress, total=None, message=None):
        if message:
            self.hub.task["phase"] = message

    async def info(self, *_a, **_k):
        pass


class Hub:
    def __init__(self):
        self.task = None           # the rent / start being watched (one at a time)
        self.runner = None
        self.cached = (0.0, None)  # (when, instances)
        self.error = ""

    async def instances(self, fresh=False):
        when, rows = self.cached
        if fresh or rows is None or time.time() - when > INSTANCES_TTL:
            try:
                rows = (await asyncio.to_thread(M.list_instances))["instances"]
                self.error = ""
            except Exception as exc:  # no Vast key, network: show it, keep the last list
                self.error = str(exc)
                rows = rows or []
            self.cached = (time.time(), rows)
        for r in rows:
            if r.get("status") == "running" and r.get("uptime_hours") is not None:
                r["spent"] = round((r.get("price_per_hour") or 0) * r["uptime_hours"], 3)
        return rows

    def busy(self):
        return bool(self.task and self.task.get("state") in ("starting", "installing"))

    def watch(self, instance_id, setups=(), autostop=None, gpu=None, price=None):
        # wait_for_instance times the boot from this moment (a stopped instance started again must not
        # look like one that never started).
        info = M.STATE["rented"].setdefault(int(instance_id), {})
        info["at"] = time.time()
        info.pop("dash_at", None)
        self.task = {"kind": "setup", "instance_id": int(instance_id), "state": "starting", "phase": "Renting",
                     "setups": list(setups), "gpu": gpu, "price_per_hour": price, "started": time.time(), "install": None}
        self.runner = asyncio.create_task(self._watch(int(instance_id), autostop))

    async def _watch(self, iid, autostop):
        t = self.task
        try:
            while True:
                r = await M.wait_for_instance(Progress(self), iid, timeout_seconds=60, benchmark=True)
                if r["state"] != "waiting":
                    break
            if r["state"] == "failed":
                t.update(state="failed", phase=r.get("reason") or "It didn't start", advice=r.get("advice"))
                return
            t.update(state="installing", phase="Connected; setting up your models", host_health=r.get("host_health"),
                     host_advice=r.get("advice"), connect_error=r.get("connect_error"))
            if autostop:
                try:
                    await asyncio.to_thread(M.api, "settings", "PUT", {"auto_stop_minutes": int(autostop)})
                except Exception as exc:
                    t["autostop_error"] = str(exc)
            while True:
                p = await asyncio.to_thread(M.api, "catalog/progress")
                boot = p.get("boot") or {}
                t["install"] = {"done_gb": M.gb(p.get("bytes_done")), "total_gb": M.gb(p.get("bytes_total")),
                                "speed_mb_s": round((p.get("speed") or 0) / 1e6, 1), "eta_seconds": p.get("eta_s"),
                                "failed": [f"{x['category']}/{x['filename']}" for x in p.get("tasks") or [] if x["status"] == "failed"],
                                "boot_step": boot.get("step")}
                busy = not p.get("finished") or (boot and boot.get("step") not in (None, "done", "failed"))
                if p.get("bytes_total"):
                    t["phase"] = f"Downloading models: {t['install']['done_gb']:.1f} of {t['install']['total_gb']:.1f} GB"
                elif boot.get("step"):
                    t["phase"] = f"Setting up: {boot['step']}"
                if not busy:
                    break
                await asyncio.sleep(5)
            t.update(state="ready", phase="Ready", ready_at=time.time())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # ToolError, CliError, network: show it on the phone
            t.update(state="failed", phase=str(exc) or type(exc).__name__)
        finally:
            self.cached = (0.0, self.cached[1])


class Backup:
    """Copies every new output of the connected instance (its gallery: images, video, audio) to a folder on
    this PC, <folder>/<instance id>/<path in ComfyUI's output>, so generations outlive the instance.
    .manifest.json remembers what was copied (by instance and path, with size)."""

    INTERVAL = 20

    def __init__(self, folder):
        self.dir = Path(folder).expanduser()
        self.file = self.dir / ".manifest.json"
        self.state = {"dir": str(self.dir), "count": 0, "bytes": 0, "last_sync": None, "error": "", "copying": None}
        self.manifest = {}
        try:
            self.manifest = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self._count()

    def _count(self):
        self.state.update(count=len(self.manifest), bytes=sum(v.get("size", 0) for v in self.manifest.values()))

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.manifest), encoding="utf-8")
        os.replace(tmp, self.file)

    def path_of(self, key):
        p = (self.dir / key).resolve()
        if self.dir.resolve() not in p.parents:
            raise PermissionError(key)
        return p

    @staticmethod
    def source_key(conn):
        if conn.inst:
            return str(conn.inst["id"])
        return "local-" + (urllib.parse.urlparse(conn.base).port and str(urllib.parse.urlparse(conn.base).port) or "dashboard")

    async def sync_once(self, client, conn):
        src = self.source_key(conn)
        new, offset = [], 0
        while True:  # newest first: stop at the first page that holds nothing new
            async with client.get(f"{conn.base}/api/gallery", params={"offset": offset, "limit": 200},
                                  timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status != 200:
                    raise RuntimeError(f"gallery answered {r.status}")
                page = json.loads(await r.read())
            items = page.get("items") or []
            fresh = [i for i in items if (self.manifest.get(f"{src}/{i['path']}") or {}).get("size") != i["size"]]
            new += fresh
            offset += len(items)
            if not items or not fresh or offset >= page.get("total", 0):
                break
        for it in reversed(new):  # oldest first, so a stopped copy resumes in order
            key = f"{src}/{it['path']}"
            target = self.path_of(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            self.state["copying"] = it["path"]
            async with client.get(f"{conn.base}/api/gallery/file", params={"path": it["path"]},
                                  timeout=aiohttp.ClientTimeout(total=None, sock_read=120)) as r:
                if r.status != 200:
                    continue  # deleted meanwhile
                with open(part, "wb") as fh:
                    async for chunk in r.content.iter_chunked(1 << 20):
                        fh.write(chunk)
            os.replace(part, target)
            self.manifest[key] = {"size": it["size"], "mtime": it.get("mtime"), "kind": it.get("kind"), "saved": time.time()}
            self._save()
        self.state.update(copying=None, last_sync=time.time(), error="")
        self._count()
        return len(new)

    async def loop(self, app):
        while True:
            conn = M.STATE.get("conn")
            if conn and conn.alive() and conn.kind != "ssh":
                try:
                    await self.sync_once(app["client"], conn)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # instance busy or gone: try again next round
                    self.state.update(error=f"{type(exc).__name__}: {exc}"[:300], copying=None)
            await asyncio.sleep(self.INTERVAL)

    def listing(self, offset=0, limit=60):
        rows = sorted(self.manifest.items(), key=lambda kv: kv[1].get("saved") or 0, reverse=True)
        return {"total": len(rows), "items": [{"path": k, **v} for k, v in rows[offset:offset + limit]], **self.state}


def connected_info():
    conn = M.STATE.get("conn")
    if not conn or not conn.alive():
        return None
    out = {"label": conn.label, "kind": conn.kind, "comfy": bool(conn.comfy)}
    if conn.inst:
        out.update(instance_id=conn.inst["id"], gpu=conn.inst.get("gpu_name"))
    return out


def eta_minutes(row, download_gb):
    """Rough time to ready: about 4 min to boot and check the host, plus the downloads at a realistic
    share of the host's line (Hugging Face / Civitai rarely fill a fast one)."""
    mbps = min(float(row.get("inet_down_mbps") or 500), 2000) * 0.6
    return round(4 + download_gb * 8000 / max(mbps, 50) / 60)


def setups_info(ids, cat=None):
    needs = cli.catalog_needs(cat or cli.catalog_data(), ids)
    return {"download_gb": needs["download_gb"], "vram_gb": needs["vram_gb"], "needs_civitai_key": needs["needs_token"],
            "node_packs": len(needs["node_packs"])}


# ---- HTTP: auth, hub API -----------------------------------------------------------------------------------
def jerr(message, status, **extra):
    return web.json_response({"error": message, **extra}, status=status)


@web.middleware
async def guard(request, handler):
    path = request.path
    private = path.startswith(("/api/", "/comfy/")) or (path.startswith("/hub/") and path not in OPEN_PATHS)
    if private and not authed(request):
        return jerr("Sign in with your PIN first", 401, signin=True)
    if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/hub/") \
            and not request.content_type.startswith("application/json"):
        return jerr("JSON only", 415)  # with the SameSite cookie, this keeps other sites from posting here
    resp = await handler(request)
    if not resp.prepared:
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


async def body_of(request):
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text=json.dumps({"error": "Invalid JSON"}), content_type="application/json")
    return data if isinstance(data, dict) else {}


async def whoami(request):
    cfg = request.app["cfg"]
    return web.json_response({"hub": True, "version": VERSION, "authed": authed(request), "pin_set": bool(cfg.get("pin_hash"))})


async def login(request):
    cfg, lock = request.app["cfg"], request.app["lockout"]
    ip = request.remote or "?"
    wait = lock.locked_for(ip)
    if wait:
        return jerr(f"Too many wrong PINs. Try again in {max(1, round(wait / 60))} min.", 429, retry_after=wait)
    pin = str((await body_of(request)).get("pin") or "")
    ok = await asyncio.to_thread(check_pin, cfg, pin)  # scrypt takes a moment
    if not ok:
        lock.failed(ip)
        wait = lock.locked_for(ip)
        return jerr("Wrong PIN" + (f". Locked for {max(1, round(wait / 60))} min." if wait else "."), 401)
    lock.passed(ip)
    resp = web.json_response({"ok": True})
    resp.set_cookie(COOKIE, make_token(cfg), max_age=SESSION_DAYS * 86400, httponly=True, samesite="Strict",
                    secure=request.secure, path="/")
    return resp


async def logout(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE, path="/")
    return resp


async def state(request):
    hub = request.app["hub"]
    rows = await hub.instances(fresh=request.query.get("fresh") == "1")
    return web.json_response({"version": VERSION, "instances": rows, "vast_error": hub.error, "connected": connected_info(),
                              "task": hub.task, "backup": request.app["backup"].state, "now": time.time()})


def _catalog_for_phone():
    cat = cli.catalog_data()
    wfs = [{**w, **setups_info([w["id"]], cat)} for w in cat.get("workflows") or []]
    return {"version": cat.get("version"), "categories": cat.get("categories") or [], "workflows": wfs,
            "packs": cat.get("packs") or []}


async def catalog(request):
    return web.json_response(await asyncio.to_thread(_catalog_for_phone))


async def offers(request):
    b = await body_of(request)
    ids = [str(i) for i in b.get("setups") or [] if i]
    max_price = b.get("max_price")
    try:
        res = await asyncio.to_thread(M.find_gpu, for_setups=ids or None, max_price=float(max_price) if max_price else None,
                                      rank="speed" if b.get("rank") == "speed" else "value",
                                      hours=float(b.get("hours") or 3), limit=int(b.get("limit") or 6))
    except Exception as exc:
        return jerr(str(exc), 502)
    dl = (res.get("filters") or {}).get("download_gb") or 0
    for row in res.get("offers") or []:
        row["ready_minutes"] = eta_minutes(row, dl)
    if ids:
        res["needs"] = await asyncio.to_thread(setups_info, ids)
    return web.json_response(res)


async def rent(request):
    hub = request.app["hub"]
    b = await body_of(request)
    try:
        oid, price = int(b["offer_id"]), float(b["cost_per_hour"])
    except (KeyError, TypeError, ValueError):
        return jerr("offer_id and cost_per_hour are needed", 400)
    if b.get("confirm") is not True:
        return jerr("Renting needs your confirmation", 400)
    if hub.busy():
        return jerr("Another GPU is still being set up: wait for it, or stop it first", 409)
    entry = M.STATE["offers"].get(oid)
    if not entry or time.time() - entry["at"] > M.OFFER_TTL:
        return jerr("That offer is too old. Look for GPUs again and pick one.", 409, refresh=True)
    if abs(entry["row"]["cost_per_hour"] - price) > 0.0005:
        return jerr(f"The price you saw (${price:.3f}/h) isn't this offer's (${entry['row']['cost_per_hour']:.3f}/h). "
                    "Look again.", 409, refresh=True)
    try:
        r = await asyncio.to_thread(M.rent_gpu, oid, True, None, None, "comfortable-phone", None)
    except Exception as exc:  # gone, pricier, Vast refused: nothing was rented
        return jerr(str(exc), 409, refresh=True)
    autostop = b.get("autostop_minutes")
    hub.watch(r["instance_id"], entry["for_setups"], autostop=int(autostop) if autostop else None,
              gpu=r.get("gpu"), price=r.get("cost_per_hour"))
    return web.json_response({"rented": r, "task": hub.task})


async def instance_action(request):
    hub = request.app["hub"]
    try:
        iid = int(request.match_info["id"])
    except ValueError:
        return jerr("Bad instance id", 400)
    b = await body_of(request)
    action = b.get("action")
    if action not in ("stop", "start", "destroy", "connect"):
        return jerr("action: stop, start, destroy or connect", 400)
    if action == "connect":
        try:
            conn = await asyncio.to_thread(M.get_conn, iid)
        except Exception as exc:
            return jerr(str(exc), 502)
        return web.json_response({"connected": connected_info() or {"label": conn.label}})
    if b.get("confirm") is not True:
        return jerr(f"{action.capitalize()} needs your confirmation", 400)
    if hub.task and hub.task.get("instance_id") == iid and hub.runner and not hub.runner.done() and action != "start":
        hub.runner.cancel()
        hub.task.update(state="cancelled", phase=f"{action.capitalize()} asked while setting up")
    try:
        r = await asyncio.to_thread(M.manage_instance, iid, action, True)
    except Exception as exc:
        return jerr(str(exc), 502)
    if action == "start":
        hub.watch(iid)
    hub.cached = (0.0, hub.cached[1])
    return web.json_response(r)


async def backups(request):
    q = request.query
    return web.json_response(request.app["backup"].listing(int(q.get("offset", 0)), min(200, int(q.get("limit", 60)))))


async def backup_file(request):
    try:
        path = request.app["backup"].path_of(request.query.get("path", ""))
    except PermissionError:
        return jerr("Not a saved file", 403)
    if not path.is_file():
        return jerr("Not found", 404)
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400",
                                           "Content-Type": mimetypes.guess_type(str(path))[0] or "application/octet-stream"})


async def dismiss_task(request):
    hub = request.app["hub"]
    if hub.busy():
        return jerr("Still setting up", 409)
    hub.task = None
    return web.json_response({"ok": True})


# ---- HTTP: pass-through to the connected instance ------------------------------------------------------------
def _conn_for(kind):
    conn = M.STATE.get("conn")
    if conn and not conn.alive() and conn.inst:
        try:
            conn = M.get_conn(conn.inst["id"])  # the tunnel dropped: reopen it
        except Exception:
            conn = None
    if not conn or conn.kind == "ssh" or (kind == "comfy" and not conn.comfy):
        return None
    return conn


async def passthrough(request):
    kind = "comfy" if request.path.startswith("/comfy/") else "api"
    conn = await asyncio.to_thread(_conn_for, kind)
    if conn is None:
        return jerr("No GPU instance is connected. Start or connect one on the Start screen.", 503, no_instance=True)
    tail = request.match_info.get("tail", "")
    url = f"{conn.base}/api/{tail}" if kind == "api" else f"{conn.comfy}/{tail}"
    if request.query_string:
        url += "?" + request.query_string
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await ws_passthrough(request, url)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP | {"cookie", "content-length"}}
    client = request.app["client"]
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)
    try:
        upstream = await client.request(request.method, url, headers=headers,
                                        data=request.content if request.body_exists else None,
                                        allow_redirects=False, timeout=timeout)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return jerr(f"The instance didn't answer: {exc}", 502)
    resp = web.StreamResponse(status=upstream.status, reason=upstream.reason)
    for k, v in upstream.headers.items():
        if k.lower() not in HOP:
            resp.headers.add(k, v)
    try:
        await resp.prepare(request)
        async for chunk in upstream.content.iter_any():
            await resp.write(chunk)
        await resp.write_eof()
    except (ConnectionResetError, aiohttp.ClientError, asyncio.CancelledError):
        pass  # the phone went away or the stream ended
    finally:
        upstream.release()
    return resp


async def ws_passthrough(request, url):
    phone = web.WebSocketResponse(heartbeat=30)
    await phone.prepare(request)
    try:
        async with request.app["client"].ws_connect("ws" + url[4:], heartbeat=30) as inst:
            async def up():
                async for msg in phone:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await inst.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await inst.send_bytes(msg.data)

            async def down():
                async for msg in inst:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await phone.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await phone.send_bytes(msg.data)

            done, pending = await asyncio.wait([asyncio.create_task(up()), asyncio.create_task(down())],
                                               return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass
    await phone.close()
    return phone


# ---- HTTP: the web app ---------------------------------------------------------------------------------------
async def web_app(request):
    rel = request.match_info.get("tail", "")
    root = WEB.resolve()
    target = (root / rel).resolve() if rel else None
    if target and target.is_file() and root in target.parents:
        cache = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-cache"
        return web.FileResponse(target, headers={"Cache-Control": cache,
                                                 "Content-Type": mimetypes.guess_type(str(target))[0] or "application/octet-stream"})
    return web.FileResponse(root / "index.html", headers={"Cache-Control": "no-cache", "Content-Type": "text/html"})


async def on_startup(app):
    app["client"] = aiohttp.ClientSession(auto_decompress=False, cookie_jar=aiohttp.DummyCookieJar())
    # Already have a GPU running (or a dashboard URL set)? Connect in the background.
    app["connecting"] = asyncio.create_task(asyncio.to_thread(_connect_quietly))
    app["backing_up"] = asyncio.create_task(app["backup"].loop(app))


def _connect_quietly():
    try:
        M.get_conn(required=False)
    except Exception:
        pass


async def on_cleanup(app):
    hub = app["hub"]
    if hub.runner and not hub.runner.done():
        hub.runner.cancel()
    app["backing_up"].cancel()
    await app["client"].close()
    conn = M.STATE.get("conn")
    if conn:
        conn.close()


def make_app(cfg):
    app = web.Application(middlewares=[guard], client_max_size=2 * 1024 ** 3)
    app["cfg"], app["hub"], app["lockout"] = cfg, Hub(), Lockout()
    app["backup"] = Backup(os.environ.get("COMFORTABLE_HUB_BACKUP_DIR") or cfg.get("backup_dir")
                           or Path.home() / "Comfortable" / "outputs")
    r = app.router
    r.add_get("/hub/whoami", whoami)
    r.add_post("/hub/login", login)
    r.add_post("/hub/logout", logout)
    r.add_get("/hub/state", state)
    r.add_get("/hub/catalog", catalog)
    r.add_post("/hub/offers", offers)
    r.add_post("/hub/rent", rent)
    r.add_post("/hub/instances/{id}", instance_action)
    r.add_post("/hub/task/dismiss", dismiss_task)
    r.add_get("/hub/backups", backups)
    r.add_get("/hub/backups/file", backup_file)
    r.add_route("*", "/api/{tail:.*}", passthrough)
    r.add_route("*", "/comfy/{tail:.*}", passthrough)
    r.add_get("/{tail:.*}", web_app)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


# ---- command line ----------------------------------------------------------------------------------------------
def addresses(port):
    """Where the phone can reach this PC: Wi-Fi / LAN addresses and Tailscale's (100.64.0.0/10)."""
    out = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for ip in sorted({i[4][0] for i in infos}):
        addr = ipaddress.ip_address(ip)
        if addr.is_loopback or addr.is_link_local:
            continue
        kind = "Tailscale (from anywhere)" if addr in ipaddress.ip_network("100.64.0.0/10") else "same Wi-Fi / network"
        out.append(f"http://{ip}:{port}   {kind}")
    return out or [f"http://<this PC's address>:{port}"]


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=int(os.environ.get("COMFORTABLE_HUB_PORT") or PORT))
    p.add_argument("--host", default=os.environ.get("COMFORTABLE_HUB_HOST") or "0.0.0.0",
                   help="address to listen on (default: every network of this PC; 127.0.0.1 = this PC only)")
    p.add_argument("--set-pin", action="store_true", help="choose a new PIN (signs every phone out) and exit")
    a = p.parse_args()
    cfg = load_config()
    if a.set_pin or not cfg.get("pin_hash"):
        pin = os.environ.get("COMFORTABLE_HUB_PIN")
        if not pin and sys.stdin.isatty():
            pin = getpass.getpass("New PIN for your phone (4-12 digits): ").strip()
        if not pin:
            pin = f"{secrets.randbelow(10 ** 6):06d}"
            print(f"Your phone PIN is {pin}  (choose your own with --set-pin)")
        if not valid_pin(pin):
            sys.exit("The PIN must be 4-12 digits.")
        set_pin(cfg, pin)
        save_config(cfg)
        print(f"PIN saved in {CONFIG_FILE}")
        if a.set_pin:
            return
    if not (WEB / "index.html").is_file():
        sys.exit(f"The web app isn't built: run `npm install && npm run build` in {ROOT / 'dashboard' / 'ui'}")
    print(f"Comfortable hub {VERSION}: open on your phone")
    for line in addresses(a.port):
        print("  " + line)
    print("Stop with Ctrl+C. Windows may ask once to allow it on your network: allow private networks only.")
    web.run_app(make_app(cfg), host=a.host, port=a.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
