"""GPU value benchmark: a fixed render on every instance, stored with price and host health.

Each workload is a fixed render, so results are comparable across GPUs and over time:
  sd15   SD 1.5 (shipped in the vastai/comfy image), 512x512, 20 steps, batch of 4
  sdxl   SDXL base 1.0, 1024x1024, 20 steps
  flux   Flux.1 (schnell, fp8 checkpoint), 1024x1024, 20 steps
Different model families rank GPUs differently (Flux leans on VRAM bandwidth far more
than SD 1.5), so `comfortable offers --for workflow.json` uses the matching workload.
SDXL and Flux need their checkpoint installed first (7 and 17 GB); the dashboard
offers to download it. Results go to the "benchmarks" collection (synced through
MongoDB) as images per hour and per dollar.
"""
import asyncio
import json
import time
import uuid

import aiohttp

from . import config, health, system
from .events import bus
from .util import log, new_id, now

STEPS, RUNS = 20, 3
WORKLOADS = {
    "sd15": {"label": "SD 1.5", "ckpt": "v1-5-pruned-emaonly-fp16.safetensors", "size": 512, "batch": 4, "cfg": 7.0,
             "scheduler": "normal", "gb": 2.1,
             "url": "https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors"},
    "sdxl": {"label": "SDXL", "ckpt": "sd_xl_base_1.0.safetensors", "size": 1024, "batch": 1, "cfg": 7.0,
             "scheduler": "normal", "gb": 6.9,
             "url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"},
    "flux": {"label": "Flux", "ckpt": "flux1-schnell-fp8.safetensors", "size": 1024, "batch": 1, "cfg": 1.0,
             "scheduler": "simple", "gb": 17.2,
             "url": "https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors"},
}
STANDARD_CKPT = WORKLOADS["sd15"]["ckpt"]
_state = {"running": False, "step": "", "error": "", "workload": ""}


def test_name(key):
    w = WORKLOADS[key]
    return f"{key}-{w['size']}-{STEPS}steps-b{w['batch']}"


def workload_of(result):
    """Results saved before workloads existed are SD 1.5."""
    return result.get("workload") or (result.get("test") or "sd15").split("-")[0]


def workflow(ckpt, seed, key="sd15"):
    w = WORKLOADS[key]
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w["size"], "height": w["size"], "batch_size": w["batch"]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a photo of a red fox in a snowy forest, detailed", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality", "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": STEPS, "cfg": w["cfg"], "sampler_name": "euler",
                                                   "scheduler": w["scheduler"], "denoise": 1.0, "model": ["4", 0],
                                                   "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},  # not saved to outputs
    }


async def installed_checkpoints(session=None):
    own = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    try:
        async with session.get(config.COMFY_URL + "/object_info/CheckpointLoaderSimple") as r:
            return (await r.json(content_type=None))["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    finally:
        if own:
            await session.close()


async def workloads():
    """Each workload, and whether its checkpoint is installed (None when ComfyUI isn't reachable)."""
    try:
        ckpts = set(await installed_checkpoints())
    except Exception:
        ckpts = None
    return [{"id": k, "label": w["label"], "test": test_name(k), "ckpt": w["ckpt"], "url": w["url"], "gb": w["gb"],
             "installed": None if ckpts is None else w["ckpt"] in ckpts} for k, w in WORKLOADS.items()]


async def _render(session, ckpt, seed, key="sd15"):
    t0 = time.perf_counter()
    async with session.post(config.COMFY_URL + "/prompt", json={"prompt": workflow(ckpt, seed, key), "client_id": f"comfortable-bench-{uuid.uuid4().hex[:6]}"}) as r:
        data = await r.json(content_type=None)
        if r.status != 200:
            raise RuntimeError(f"ComfyUI rejected the benchmark: {json.dumps(data)[:300]}")
    pid = data["prompt_id"]
    while True:
        await asyncio.sleep(0.2)
        async with session.get(f"{config.COMFY_URL}/history/{pid}") as r:
            h = await r.json(content_type=None)
        if pid in h:
            status = h[pid].get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(f"Benchmark render failed: {json.dumps(status)[:300]}")
            return time.perf_counter() - t0


def _publish(**kw):
    _state.update(kw)
    bus.publish("benchmark", dict(_state))


async def run(store, key="sd15"):
    if key not in WORKLOADS:
        raise ValueError(f"Unknown benchmark {key!r}: one of {', '.join(WORKLOADS)}")
    if _state["running"]:
        raise ValueError("A benchmark is already running")
    w = WORKLOADS[key]
    _publish(running=True, step="Checking ComfyUI", error="", workload=key)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as s:
            async with s.get(config.COMFY_URL + "/queue") as r:
                q = await r.json(content_type=None)
            if q.get("queue_running") or q.get("queue_pending"):
                raise ValueError("ComfyUI is busy. Run the benchmark when the queue is empty.")
            if w["ckpt"] not in await installed_checkpoints(s):
                raise ValueError(f"The {w['label']} test model {w['ckpt']} isn't installed on this instance "
                                 f"({w['gb']:g} GB; the GPU value card can download it).")
            _publish(step=f"{w['label']}: warm-up render (loads the model)")
            await _render(s, w["ckpt"], 1, key)
            times = []
            for i in range(RUNS):
                _publish(step=f"{w['label']}: timed render {i + 1} of {RUNS}")
                times.append(await _render(s, w["ckpt"], 100 + i, key))
        seconds = sorted(times)[len(times) // 2]  # median
        snap = await system.snapshot()
        vast = snap.get("vast") or {}
        gpu = (snap.get("gpus") or [{}])[0]
        h = health.cached() or {}
        tune = {}
        try:
            tune = json.loads((config.DATA_DIR / "tune.json").read_text())
        except (OSError, ValueError):
            pass
        images_per_hour = 3600 * w["batch"] / seconds
        result = {
            "id": new_id(), "created_at": now(), "workload": key, "test": test_name(key),
            "gpu": gpu.get("name") or "unknown", "vram_gb": round((gpu.get("mem_total") or 0) / 2**30),
            "seconds_per_batch": round(seconds, 2), "images_per_hour": round(images_per_hour),
            "dph": vast.get("dph"), "images_per_dollar": round(images_per_hour / vast["dph"]) if vast.get("dph") else None,
            "attention": tune.get("attention"), "args": tune.get("args"),
            "host_score": h.get("score"), "host_warnings": h.get("warnings", []),
            "instance_id": vast.get("id"), "machine_id": vast.get("machine_id"), "dlperf": vast.get("dlperf"),
        }
        await asyncio.to_thread(store.put, "benchmarks", result)
        _publish(running=False, step="Done", last=result)
        log.info("Benchmark %s: %s %.2fs/batch, %d img/h", key, result["gpu"], seconds, images_per_hour)
        return result
    except Exception as exc:
        _publish(running=False, step="", error=str(exc))
        raise


def state():
    return dict(_state)
