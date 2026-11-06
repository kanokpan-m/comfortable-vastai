"""Watch the GPU while jobs run, to catch hosts that slow down after passing the boot check.

The boot check (health.py) runs a 30 s load; a badly cooled or power-starved host
can pass it and still throttle twenty minutes into a long video render. While the
GPU is busy this samples nvidia-smi every WATCH_INTERVAL seconds. If the GPU was
slowed for at least half of the busy time in the last WINDOW seconds (and for
MIN_SLOW seconds or more), it warns once an hour (Discord + dashboard) and marks
the machine "poor" in the shared hosts list, so `comfortable rent` (and vast-llm)
skip it next time. Hitting the power limit is normal at full load and doesn't count.
"""
import asyncio
import shutil
import time
from collections import Counter, deque

from . import notify, system
from .events import bus
from .util import log, now

WATCH_INTERVAL = 30
WINDOW = 600
MIN_SLOW = 300
BUSY_UTIL = 50          # % GPU load that counts as "a job is running"
LOW_CLOCK = 0.7         # SM clock under this share of its maximum, at load, counts as slowed
WARN_EVERY = 3600
# clocks_event_reasons bits that mean the GPU was slowed for the host's sake (not the power cap, 0x4).
SLOW_BITS = {0x8: "hardware slowdown", 0x20: "thermal (software)", 0x40: "thermal (hardware)",
             0x80: "power brake", 0x400: "reliability limit"}
_samples = deque(maxlen=WINDOW // WATCH_INTERVAL * 2)
_state = {"warned_at": 0.0, "finding": None}


def parse(line, at=None):
    """One nvidia-smi CSV line: reasons, temperature, SM clock, max SM clock, utilization."""
    p = [v.strip() for v in line.split(",")]
    if len(p) < 5:
        return None
    num = lambda v: float(v) if v.replace(".", "", 1).isdigit() else None
    try:
        bits = int(p[0], 16)
    except ValueError:
        bits = 0
    clock, max_clock = num(p[2]), num(p[3])
    return {"t": at or time.time(), "reasons": [name for bit, name in SLOW_BITS.items() if bits & bit],
            "temp": num(p[1]), "clock_ratio": clock / max_clock if clock and max_clock else None, "util": num(p[4]) or 0}


async def sample():
    if not shutil.which("nvidia-smi"):
        return None
    out = await system._run("nvidia-smi", "--query-gpu=clocks_event_reasons.active,temperature.gpu,clocks.sm,clocks.max.sm,utilization.gpu",
                            "--format=csv,noheader,nounits")
    lines = (out or "").strip().splitlines()
    return parse(lines[0]) if lines else None


def assess(samples, at=None):
    """A finding when the GPU was slowed for most of recent busy time, else None."""
    at = at or time.time()
    busy = [s for s in samples if at - s["t"] <= WINDOW and s["util"] >= BUSY_UTIL]
    slow = [s for s in busy if s["reasons"] or (s["clock_ratio"] is not None and s["clock_ratio"] < LOW_CLOCK)]
    slow_seconds = len(slow) * WATCH_INTERVAL
    if not busy or slow_seconds < MIN_SLOW or len(slow) * 2 < len(busy):
        return None
    reasons = [r for r, _ in Counter(r for s in slow for r in s["reasons"]).most_common(2)] or ["clocks well below maximum"]
    temps = [s["temp"] for s in slow if s["temp"] is not None]
    ratios = [s["clock_ratio"] for s in slow if s["clock_ratio"] is not None]
    text = (f"GPU slowed down during jobs for {slow_seconds // 60} of the last {len(busy) * WATCH_INTERVAL // 60} busy minutes "
            f"({', '.join(reasons)}" + (f", up to {max(temps):.0f} °C" if temps else "") +
            (f", clocks at {100 * sum(ratios) / len(ratios):.0f}% of max" if ratios else "") + ")")
    return {"warning": text, "reasons": reasons, "slow_seconds": slow_seconds, "at": now()}


async def record(store, finding):
    """Mark this machine poor in the shared hosts list, keeping what the boot check found."""
    vast = await system.vast_instance() or {}
    if not vast.get("machine_id"):
        return
    doc_id = str(vast["machine_id"])
    doc = store.get("hosts", doc_id) or {"id": doc_id, "machine_id": vast["machine_id"], "gpu": vast.get("gpu"),
                                         "dlperf": vast.get("dlperf"), "dph": vast.get("dph")}
    warnings = [w for w in doc.get("warnings") or [] if not w.startswith("GPU slowed down during jobs")]
    await asyncio.to_thread(store.put, "hosts", {**doc, "score": "poor", "warnings": warnings + [finding["warning"]],
                                                 "at": finding["at"], "during_jobs": True})


def status():
    return {"finding": _state["finding"], "watching": bool(shutil.which("nvidia-smi"))}


async def loop(store):
    while True:
        await asyncio.sleep(WATCH_INTERVAL)
        try:
            s = await sample()
            if not s:
                continue
            _samples.append(s)
            finding = assess(_samples)
            if finding and time.time() - _state["warned_at"] > WARN_EVERY:
                _state.update(warned_at=time.time(), finding=finding)
                log.warning("Host check during jobs: %s", finding["warning"])
                bus.publish("hostwatch", status())
                await record(store, finding)
                await notify.discord(store.setting("discord_webhook"), "🌡️ Host slowing down during jobs",
                                     finding["warning"] + ".\n\nThis machine is now skipped by `comfortable rent`. "
                                     "Finish what's running, then consider renting another host.", color=0xFD9903)
        except Exception as exc:
            log.info("Host watch sample failed: %s", exc)
