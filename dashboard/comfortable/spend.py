"""What renting costs: per instance, per day and per workflow, kept in the shared store ("spend").

Every TICK seconds the dashboard adds the time since the last tick, at Vast's current
price for this instance (GPU + disk, dph_total), to today's total. Only time this
container was running counts, so a stopped instance isn't billed here (Vast still bills
its storage). Bandwidth is estimated from the container's network counters and the
host's $/TB prices. While ComfyUI is busy, the time is also credited to the workflow
last queued from the ComfyUI page (the extension reports its name), as an estimate of
what each workflow costs.

`comfortable spend` on your computer reads the same records from MongoDB.
"""
import asyncio
import time

from . import system
from .util import log, now

TICK = 300
COLL = "spend"
_current = {"workflow": ""}


def set_workflow(name):
    """The workflow the user just queued in ComfyUI."""
    if name:
        _current["workflow"] = str(name)[:120]


def _day(t=None):
    return time.strftime("%Y-%m-%d", time.localtime(t or time.time()))


def container_start():
    try:
        import psutil
        return psutil.Process(1).create_time()
    except Exception:
        return time.time()


def net_bytes():
    try:
        import psutil
        c = psutil.net_io_counters()
        return c.bytes_recv, c.bytes_sent
    except Exception:
        return 0, 0


def add(doc, seconds, dph, busy, net, prices, workflow="", day=None):
    """Account `seconds` of uptime (and the bytes moved since the last tick) into an instance record."""
    day = day or _day()
    cost = seconds / 3600 * (dph or 0)
    d = doc.setdefault("days", {}).setdefault(day, {"hours": 0.0, "cost": 0.0, "bandwidth": 0.0})
    d["hours"] += seconds / 3600
    d["cost"] += cost
    down, up = net
    bw = down / 1e12 * (prices.get("down_tb") or 0) + up / 1e12 * (prices.get("up_tb") or 0)
    d["bandwidth"] += bw
    doc["hours"] = doc.get("hours", 0.0) + seconds / 3600
    doc["cost"] = doc.get("cost", 0.0) + cost
    doc["bandwidth"] = doc.get("bandwidth", 0.0) + bw
    doc["bytes_down"] = doc.get("bytes_down", 0) + down
    doc["bytes_up"] = doc.get("bytes_up", 0) + up
    if busy:
        w = doc.setdefault("workflows", {}).setdefault(workflow or "(not named)", {"hours": 0.0, "cost": 0.0})
        w["hours"] += seconds / 3600
        w["cost"] += cost
    return doc


def account(doc, at, started, net, dph, busy, prices, workflow=""):
    """Add the time and traffic since this container's last tick. The session (container start,
    last tick, network counters) lives in the record, so a dashboard restart continues where it
    left off and a new container (after a stop/start) starts from zero."""
    sess = doc.get("session") or {}
    if sess.get("start") == round(started):
        since, prev = sess["tick"], tuple(sess["net"])
    else:
        since, prev = started, (0, 0)
    seconds = max(0.0, at - since)
    moved = (max(0, net[0] - prev[0]), max(0, net[1] - prev[1]))
    doc["session"] = {"start": round(started), "tick": at, "net": list(net)}
    return add(doc, seconds, dph, busy, moved, prices, workflow, _day(at))


async def tick(store, at=None):
    at = at or time.time()
    vast = await system.vast_instance()
    if not vast or not vast.get("id"):
        return None
    snap = await system.snapshot()
    busy = bool((snap.get("comfy") or {}).get("running") or ((snap.get("gpus") or [{}])[0].get("util") or 0) >= 50)
    doc_id = str(vast["id"])
    doc = store.get(COLL, doc_id) or {"id": doc_id, "instance_id": vast["id"], "first_seen": now()}
    doc.update(gpu=vast.get("gpu"), machine_id=vast.get("machine_id"), dph=vast.get("dph"), label=vast.get("label"),
               last_seen=now())
    prices = {"down_tb": (vast.get("inet_down_cost") or 0) * 1000, "up_tb": (vast.get("inet_up_cost") or 0) * 1000}
    account(doc, at, container_start(), net_bytes(), vast.get("dph"), busy, prices, _current["workflow"])
    await asyncio.to_thread(store.put, COLL, doc)
    return doc


def summary(records, days=30, at=None):
    """Totals per instance, per day and per workflow over the last `days` days."""
    at = at or time.time()
    first = _day(at - days * 86400)
    per_day, per_wf, instances = {}, {}, []
    total = {"hours": 0.0, "cost": 0.0, "bandwidth": 0.0}
    for r in records:
        inst = {"hours": 0.0, "cost": 0.0, "bandwidth": 0.0}
        for day, d in (r.get("days") or {}).items():
            if day < first:
                continue
            p = per_day.setdefault(day, {"day": day, "hours": 0.0, "cost": 0.0, "bandwidth": 0.0})
            for k in inst:
                p[k] += d.get(k, 0.0)
                inst[k] += d.get(k, 0.0)
        if not inst["hours"]:
            continue
        for k in total:
            total[k] += inst[k]
        instances.append({"id": r["id"], "gpu": r.get("gpu"), "dph": r.get("dph"), "label": r.get("label"),
                          "last_seen": r.get("last_seen"), **{k: round(v, 3) for k, v in inst.items()}})
        if (r.get("last_seen") or 0) >= at - days * 86400:
            for name, w in (r.get("workflows") or {}).items():
                p = per_wf.setdefault(name, {"workflow": name, "hours": 0.0, "cost": 0.0})
                p["hours"] += w.get("hours", 0.0)
                p["cost"] += w.get("cost", 0.0)
    rnd = lambda d: {k: round(v, 3) if isinstance(v, float) else v for k, v in d.items()}
    return {"days": days, "total": rnd({**total, "all": total["cost"] + total["bandwidth"]}),
            "per_day": [rnd(d) for d in sorted(per_day.values(), key=lambda d: d["day"], reverse=True)],
            "instances": sorted(instances, key=lambda i: i.get("last_seen") or 0, reverse=True),
            "workflows": [rnd(w) for w in sorted(per_wf.values(), key=lambda w: -w["cost"])]}


async def loop(store):
    await asyncio.sleep(60)
    while True:
        try:
            await tick(store)
        except Exception as exc:
            log.info("Spend tick failed: %s", exc)
        await asyncio.sleep(TICK)
