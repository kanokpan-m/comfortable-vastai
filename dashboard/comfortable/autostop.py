"""Stop (or destroy) the instance when it is idle or over budget. Off unless set in Settings.

Idle means: ComfyUI not running anything, empty queue, no active downloads, no
backup or benchmark in progress, GPU load under 10%, and nobody using the ComfyUI
page in the last few minutes (the extension reports clicks and typing, so
editing a workflow without running it counts as activity).

The budget cap (hours or dollars since the instance started, from Vast's API)
applies whether busy or not: it is the "I forgot it was running" guard. Raise
the limit in Settings to keep going; "Keep running" only postpones idle stops.

Five minutes before acting it warns everywhere (dashboard banner, ComfyUI
banner via the extension, Discord). Then it backs up outputs (if configured)
and syncs saved workflows, and stops the instance (disk kept, storage still
billed) or destroys it (nothing billed afterwards). Destroy only goes ahead if
the backup succeeded; otherwise it stops instead, so nothing is lost.
"""
import asyncio
import time

import aiohttp

from . import backup, bench, config, notify, system, workflowsync
from .events import bus
from .util import log

WARN_BEFORE = 5 * 60
ACTIVE_WINDOW = 5 * 60  # someone used the ComfyUI page this recently: not idle
_state = {"idle_since": time.time(), "warned": False, "stopping": False, "snoozed_until": 0.0,
          "last_activity": 0.0, "reason": "", "cost": None}


def snooze(store, minutes=None):
    _state["idle_since"] = time.time()
    _state["warned"] = False
    if minutes:
        _state["snoozed_until"] = time.time() + minutes * 60
    bus.publish("autostop", status(store))


def activity():
    """Someone is using ComfyUI (reported by the extension)."""
    _state["last_activity"] = time.time()


def _limits(store):
    return {"minutes": int(store.setting("auto_stop_minutes") or 0) if store else 0,
            "action": (store.setting("auto_stop_action") if store else None) or "stop",
            "max_hours": float(store.setting("max_hours") or 0) if store else 0.0,
            "max_spend": float(store.setting("max_spend") or 0) if store else 0.0}


def _budget_left(lim, cost):
    """Seconds until the budget cap, or None without a cap (or without Vast's figures)."""
    if not cost or not cost.get("uptime"):
        return None
    left = []
    if lim["max_hours"]:
        left.append(lim["max_hours"] * 3600 - cost["uptime"])
    if lim["max_spend"] and cost.get("dph"):
        left.append((lim["max_spend"] - (cost.get("spent") or 0)) / cost["dph"] * 3600)
    return min(left) if left else None


def status(store):
    lim = _limits(store)
    idle = time.time() - _state["idle_since"]
    idle_left = lim["minutes"] * 60 - idle if lim["minutes"] else None
    budget_left = _budget_left(lim, _state["cost"])
    candidates = [x for x in (idle_left, budget_left) if x is not None]
    return {"enabled": bool(lim["minutes"] or lim["max_hours"] or lim["max_spend"]), **lim,
            "idle_seconds": int(idle), "stops_in": int(min(candidates)) if candidates else None,
            "budget_left": int(budget_left) if budget_left is not None else None,
            "reason": _state["reason"], "warned": _state["warned"], "stopping": _state["stopping"],
            "active_recently": time.time() - _state["last_activity"] < ACTIVE_WINDOW,
            "available": bool(config.VAST_CONTAINER_ID and config.VAST_API_KEY)}


def _busy(snap, downloads):
    comfy = snap.get("comfy") or {}
    gpu = (snap.get("gpus") or [{}])[0]
    return bool(comfy.get("running") or comfy.get("queue_remaining") or downloads.running or
                any(t["status"] in ("queued", "starting", "downloading", "verifying") for t in downloads.tasks.values()) or
                backup._state["running"] or bench._state["running"] or (gpu.get("util") or 0) >= 10 or
                time.time() - _state["last_activity"] < ACTIVE_WINDOW)


async def _vast(method, json=None):
    if not (config.VAST_CONTAINER_ID and config.VAST_API_KEY):
        raise RuntimeError("Not running on a Vast instance (no CONTAINER_ID / CONTAINER_API_KEY)")
    cid = config.VAST_CONTAINER_ID.removeprefix("C.")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
        async with s.request(method, f"https://console.vast.ai/api/v0/instances/{cid}/", json=json,
                             headers={"Authorization": f"Bearer {config.VAST_API_KEY}"}) as r:
            body = await r.text()
            if r.status >= 300:
                raise RuntimeError(f"Vast API refused ({r.status}): {body[:200]}")


async def stop_instance():
    await _vast("PUT", {"state": "stopped"})


async def destroy_instance():
    await _vast("DELETE")


async def _save_work(store):
    """Back up outputs and sync workflows. True when nothing would be lost by destroying."""
    safe = True
    if store.setting("backup_repo") and store.setting("hf_token"):
        try:
            await asyncio.to_thread(backup.run, store, "auto-stop")
            safe = not backup.pending()
        except Exception as exc:
            log.warning("Backup before auto-stop failed: %s", exc)
            safe = False
    elif backup.pending():
        safe = False  # outputs exist and there is nowhere to back them up
    if store.setting("sync_workflows"):
        try:
            await asyncio.to_thread(workflowsync.sync_once, store)
            safe = await asyncio.to_thread(store.sync) and safe
        except Exception as exc:
            log.warning("Workflow sync before auto-stop failed: %s", exc)
            safe = False
    return safe


async def act(store, why):
    lim = _limits(store)
    _state["stopping"] = True
    bus.publish("autostop", status(store))
    safe = await _save_work(store)
    hook = store.setting("discord_webhook")
    if lim["action"] == "destroy" and safe:
        await notify.discord(hook, "🗑️ Instance destroyed", f"{why}. Outputs were backed up and workflows synced.", color=0x8A8A8A)
        log.info("Auto-stop: %s, destroying instance", why)
        try:
            return await destroy_instance()
        except Exception as exc:
            log.warning("Destroy failed, stopping instead: %s", exc)
    elif lim["action"] == "destroy":
        why += ". Not destroyed because some outputs aren't backed up; stopped instead"
    await notify.discord(hook, "⏹️ Instance stopped", f"{why}. Models and outputs are kept on the disk; start it again from the Vast console.",
                         color=0x8A8A8A)
    log.info("Auto-stop: %s, stopping instance", why)
    await stop_instance()


async def loop(store, downloads, interval=20):
    while True:
        await asyncio.sleep(interval)
        try:
            await check(store, downloads)
        except Exception as exc:
            _state["stopping"] = False
            log.warning("Auto-stop check failed: %s", exc)


async def check(store, downloads):
    """One pass: warn, act or reset, depending on idle time and the budget."""
    lim = _limits(store)
    if not (lim["minutes"] or lim["max_hours"] or lim["max_spend"]) or _state["stopping"]:
        return
    _state["cost"] = await system.vast_instance()
    snap = await system.snapshot()
    budget_left = _budget_left(lim, _state["cost"])
    idle_left = None
    if lim["minutes"]:
        if _busy(snap, downloads) or time.time() < _state["snoozed_until"]:
            _state["idle_since"] = time.time()
        idle_left = lim["minutes"] * 60 - (time.time() - _state["idle_since"])
    if budget_left is not None and (idle_left is None or budget_left <= idle_left):
        caps = [f"{lim['max_hours']:g} h" if lim["max_hours"] else "", f"${lim['max_spend']:g}" if lim["max_spend"] else ""]
        left, why, _state["reason"] = budget_left, "Budget limit reached: " + " / ".join(c for c in caps if c), "budget"
    else:
        left, why, _state["reason"] = idle_left, f"Idle for {lim['minutes']} min", "idle"
    if left is None or left > WARN_BEFORE:
        if _state["warned"]:
            _state["warned"] = False
            bus.publish("autostop", status(store))
        return
    if not _state["warned"]:
        _state["warned"] = True
        bus.publish("autostop", status(store))
        verb = "Destroying" if lim["action"] == "destroy" else "Stopping"
        hint = ("Raise the limit in Comfortable's Settings to keep going." if _state["reason"] == "budget"
                else "Open Comfortable and press \"Keep running\" to postpone.")
        await notify.discord(store.setting("discord_webhook"), "⏸️ " + why.split(":")[0],
                             f"{verb} in about {max(1, int(left // 60))} min. {hint}", color=0xFD9903)
    if left <= 0:
        await act(store, why)
