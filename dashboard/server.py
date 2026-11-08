"""Comfortable dashboard server (aiohttp). Run: python dashboard/server.py"""
import asyncio
import logging
import os
import re
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiohttp import web  # noqa: E402

from comfortable import (__version__, api, api_catalog, api_create, api_more, autostop, backup, catalog, config, fixer, health,  # noqa: E402
                         library, manager, models, notify, store, system)
from comfortable.downloads import DownloadManager  # noqa: E402
from comfortable.events import bus  # noqa: E402
from comfortable.util import human_size, log, now  # noqa: E402


def auto_install(app):
    """Queue library items marked auto-install, plus every item in auto-install bundles
    (flagged in the UI, or named in the COMFORTABLE_BUNDLES env var), that are not on disk yet."""
    st = app["store"]
    wanted = {b.strip().lower() for b in config.env("BUNDLES", "").split(",") if b.strip()}
    bundle_ids = {b["id"] for b in st.all("bundles")
                  if b.get("auto_install") or b["id"].lower() in wanted or (b.get("name") or "").lower() in wanted}
    idx = models.index()
    queued = 0
    for item in st.all("library"):
        if not (item.get("auto_install") or bundle_ids & set(item.get("bundle_ids") or [])):
            continue
        where = idx.get(os.path.basename(item.get("filename") or "").lower(), [])
        if any(config.same_folder(item.get("category"), c) for c in where):
            continue
        try:
            app["downloads"].add(api._download_spec(item), auto=True)
            queued += 1
        except Exception as exc:
            log.warning("Auto-install of %s skipped: %s", item.get("name"), exc)
    if queued:
        log.info("Auto-install queued %d model(s)", queued)


def boot_install(app):
    """COMFORTABLE_INSTALL=<catalog pack / starter workflow ids> (`comfortable rent --install`):
    queue their files right away; node packs and the starters' ComfyUI copies follow once ComfyUI
    answers (boot_finish). Progress: GET /api/catalog/progress -> boot."""
    ids = [i for i in re.split(r"[,\s]+", config.env("INSTALL", "")) if i]
    if not ids:
        return
    try:
        packs, workflows = catalog.boot_install(app["store"], app["downloads"], ids)
    except Exception as exc:
        log.warning("COMFORTABLE_INSTALL failed: %s", exc)
        catalog.boot_state.update(step="failed", errors=[{"error": str(exc)}])
        return
    if packs or workflows:
        app["bg"].append(asyncio.create_task(boot_finish(app, packs, workflows)))


async def boot_finish(app, packs, workflows, wait=900):
    """Install the node packs, restart ComfyUI if it's idle, save the starters into ComfyUI."""
    state, st = catalog.boot_state, app["store"]
    deadline = time.time() + wait
    while not await asyncio.to_thread(manager.flavor, True):
        if time.time() > deadline:
            state["errors"].append({"error": "ComfyUI-Manager never answered: node packs were not installed"})
            state.update(step="done", finished_at=now())
            return
        await asyncio.sleep(10)
    cat = catalog.current(st)
    order, wfs = catalog.resolve(cat, packs, workflows)
    state["step"] = "node packs"
    results = await asyncio.to_thread(catalog.install_nodes, cat, catalog.node_ids(cat, order, wfs))
    state["node_packs"] = results
    if "queued" in results.values():
        end = time.time() + 900
        while time.time() < end and catalog.manager_busy(await asyncio.to_thread(manager.queue_status)):
            await asyncio.sleep(5)
    if any(v in ("queued", "installed") for v in results.values()):
        comfy = system._comfy_state
        if comfy.get("running") or comfy.get("queue_remaining"):
            state["restart_needed"] = True  # someone is already using ComfyUI: don't pull it away
        else:
            state["step"] = "restarting ComfyUI"
            try:
                await system.restart_comfy()
            except Exception as exc:
                state["restart_needed"] = True
                state["errors"].append({"error": f"restart ComfyUI to load the new node packs ({exc})"})
            end = time.time() + 300
            while time.time() < end and not await asyncio.to_thread(manager.flavor, True):
                await asyncio.sleep(5)
    if workflows:
        state["step"] = "saving starters"
        for wid in workflows:
            try:
                state["saved"].append({"id": wid, **await asyncio.to_thread(catalog.save_to_comfy, st, wid, False)})
            except Exception as exc:
                state["errors"].append({"workflow": wid, "error": f"not saved into ComfyUI: {exc}"})
    state.update(step="done", finished_at=now())
    log.info("COMFORTABLE_INSTALL done: node packs %s, starters saved %s", results or "none", [s["id"] for s in state["saved"]])


async def boot_tasks(app):
    """Slow one-off work after startup: host health (once per boot), library metadata, HF index."""
    await asyncio.sleep(20)
    try:
        import psutil
        cached = health.cached()
        if not cached or cached.get("at", 0) < psutil.Process(1).create_time():
            await api_more.run_health(app, notify_warnings=True)
    except Exception as exc:
        log.warning("Host health check failed: %s", exc)
    try:
        result = await asyncio.to_thread(library.refresh, app["store"], None, True)
        if result["updated"] or result["failed"]:
            bus.publish("library", {"refreshed": True})
    except Exception as exc:
        log.warning("Library refresh failed: %s", exc)
    fixer.warm_hf_index()


def schedule_backup(app, loop):
    """Debounced auto-backup after ComfyUI finishes a job (if enabled)."""
    def trigger():
        st = app["store"]
        if not (st.setting("backup_auto") and st.setting("backup_repo") and st.setting("hf_token")):
            return
        if app.get("backup_handle"):
            app["backup_handle"].cancel()
        app["backup_handle"] = loop.call_later(60, lambda: asyncio.ensure_future(asyncio.to_thread(_backup_quietly, st)))
    return lambda: loop.call_soon_threadsafe(trigger)


def _backup_quietly(st):
    try:
        backup.run(st, "auto")
    except Exception as exc:
        log.warning("Auto-backup failed: %s", exc)


async def on_startup(app):
    loop = asyncio.get_running_loop()
    # The store syncs MongoDB on its own thread; hop back to the loop to notify browsers.
    app["store"].on_change = lambda colls: loop.call_soon_threadsafe(bus.publish, "data", {"collections": sorted(colls)})
    app["downloads"].start()
    system.on_job_done = schedule_backup(app, loop)
    app["bg"] = [asyncio.create_task(system.monitor_loop()), asyncio.create_task(system.comfy_ws_loop()),
                 asyncio.create_task(autostop.loop(app["store"], app["downloads"])), asyncio.create_task(boot_tasks(app))]
    auto_install(app)
    boot_install(app)
    st = app["store"]
    disk = (await system.snapshot())["disk"]
    await notify.discord(st.setting("discord_webhook"), "🚀 Comfortable online",
                         f"Dashboard v{__version__} is running on `{socket.gethostname()}`.", color=0x58A6FF,
                         fields=[{"name": "Database", "value": "MongoDB" if st.status()["mongo_connected"] else "Local only", "inline": True},
                                 {"name": "Disk free", "value": human_size(disk["free"]), "inline": True}])


async def on_cleanup(app):
    for t in app.get("bg", []):
        t.cancel()


def register_mimetypes():
    # mimetypes reads the OS registry/mime.types, which may not know these (e.g. .webp on
    # some hosts), and the browser needs the right type for thumbnails, video and JS modules.
    import mimetypes
    for ext, mime in ((".webp", "image/webp"), (".webm", "video/webm"), (".mp4", "video/mp4"),
                      (".mov", "video/quicktime"), (".js", "text/javascript"), (".mjs", "text/javascript"),
                      (".css", "text/css"), (".svg", "image/svg+xml"), (".woff2", "font/woff2"),
                      (".json", "application/json"), (".wasm", "application/wasm")):
        mimetypes.add_type(mime, ext)


def make_app():
    register_mimetypes()
    config.ensure_dirs()
    app = web.Application(middlewares=[api.errors], client_max_size=64 * 1024 * 1024)
    app["store"] = store.init()
    app["downloads"] = DownloadManager(app["store"])
    app.add_routes(api_more.routes)
    app.add_routes(api_catalog.routes)
    app.add_routes(api_create.routes)
    app.add_routes(api.routes)  # last: its catch-all serves the web UI
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    host = config.env("HOST", "127.0.0.1")  # reached through the Instance Portal's Caddy proxy
    log.info("Comfortable %s listening on %s:%d", __version__, host, config.PORT)
    web.run_app(make_app(), host=host, port=config.PORT, access_log=None, print=None)


if __name__ == "__main__":
    main()
