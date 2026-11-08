"""Create: run starter workflows from a plain form (the Create screen, made for phones).

Every starter ships as catalog/workflows/<id>.api.json (tools/starter_api.py): the prompt ComfyUI runs
and the widgets its template puts on its main node. Here that becomes a form: the main fields (prompt,
pictures, size, seed, the template's switches), the models and LoRAs, and every other setting. A run
writes the form into a copy of the prompt, chains any LoRAs added on the phone after the model loader,
and queues it in ComfyUI under the dashboard's own client id, so the progress and results reach the
dashboard's ComfyUI connection (system.py) like any other job.
"""
import copy
import json
import random
import time
import uuid

import aiohttp

from . import config
from .util import log

CLIENT_ID = "comfortable-monitor"  # system.py listens to ComfyUI under this id
SEED_INPUTS = {"seed", "noise_seed"}
MEDIA = {"LoadImage": ("image", "image"), "LoadImageMask": ("image", "image"), "LoadAudio": ("audio", "audio"),
         "LoadVideo": ("file", "video"), "VHS_LoadVideo": ("video", "video")}
MODEL_FOLDERS = {"ckpt_name": "checkpoints", "unet_name": "diffusion_models", "lora_name": "loras", "vae_name": "vae",
                 "clip_name": "text_encoders", "clip_name1": "text_encoders", "clip_name2": "text_encoders",
                 "text_encoder": "text_encoders", "model_name": "", "control_net_name": "controlnet", "name": "model_patches"}
MODEL_LOADERS = ("UNETLoader", "CheckpointLoaderSimple", "UnetLoaderGGUF", "ImageOnlyCheckpointLoader")
TEXT_INPUTS = {"text", "prompt", "value", "caption", "lyrics", "negative_prompt", "string_b"}
MAIN_SAMPLER = {"steps", "cfg"}
MAIN_LATENT = {"width", "height", "length", "aspect_ratio", "megapixels"}
_cache = {}
_jobs = {}  # prompt id -> {"workflow", "at"}


# ---- the starter, as saved by tools/starter_api.py -------------------------------------------------------
def doc(workflow_id):
    path = config.CATALOG_DIR / "workflows" / f"{workflow_id}.api.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(("doc", workflow_id))
    if not hit or hit[0] != mtime:
        hit = (mtime, json.loads(path.read_text(encoding="utf-8")))
        _cache[("doc", workflow_id)] = hit
    return hit[1]


def available():
    folder = config.CATALOG_DIR / "workflows"
    return sorted(p.name[: -len(".api.json")] for p in folder.glob("*.api.json")) if folder.is_dir() else []


async def comfy(method, path, **kw):
    timeout = aiohttp.ClientTimeout(total=kw.pop("timeout", 30))
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.request(method, config.COMFY_URL + path, **kw) as r:
            body = await r.json(content_type=None) if r.content_length != 0 else None
            return r.status, body


async def object_info():
    hit = _cache.get("object_info")
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    status, info = await comfy("GET", "/object_info", timeout=60)
    if status != 200 or not isinstance(info, dict):
        raise RuntimeError("ComfyUI isn't answering yet")
    _cache["object_info"] = (time.time(), info)
    return info


# ---- the form ------------------------------------------------------------------------------------------
def _spec(info, cls, name):
    inputs = (info.get(cls) or {}).get("input") or {}
    for part in ("required", "optional"):
        if name in (inputs.get(part) or {}):
            return inputs[part][name]
    return None


def _field(info, prompt, node, inp, label=None, group="main"):
    n = prompt[node]
    value = n["inputs"][inp]
    title = (n.get("_meta") or {}).get("title") or n["class_type"]
    f = {"key": f"{node}|{inp}", "node": node, "input": inp, "label": label or inp, "title": title, "group": group, "value": value}
    spec = _spec(info, n["class_type"], inp)
    kind, opts = (spec[0], spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}) if spec else (None, {})
    if isinstance(kind, list) or kind == "COMBO":
        f.update(kind="combo", options=kind if isinstance(kind, list) else opts.get("options") or [])
    elif kind in ("INT", "FLOAT"):
        f.update(kind="int" if kind == "INT" else "float", min=opts.get("min"), max=opts.get("max"), step=opts.get("step"))
    elif kind == "BOOLEAN" or isinstance(value, bool):
        f["kind"] = "bool"
    elif kind == "STRING" or isinstance(value, str):
        f.update(kind="text", multiline=bool(opts.get("multiline")) or (isinstance(value, str) and (len(value) > 60 or "\n" in value)))
    else:
        f["kind"] = "int" if isinstance(value, int) else "float" if isinstance(value, float) else "text"
    if n["class_type"] in MEDIA and inp == MEDIA[n["class_type"]][0]:
        f.update(kind="media", media=MEDIA[n["class_type"]][1])
    if inp in SEED_INPUTS:
        f["role"] = "seed"
    elif f["kind"] == "text" and f.get("multiline"):
        f["role"] = "negative" if "negative" in f"{label} {title} {inp}".lower() else "prompt"
    if inp in MODEL_FOLDERS and f["kind"] == "combo":
        f.update(role="model", folder=MODEL_FOLDERS[inp] or None)
    if inp == "strength_model":
        f["role"] = "strength"
    return f


def form(workflow_id, info):
    d = doc(workflow_id)
    if not d:
        raise KeyError(f"{workflow_id} has no Create form (no {workflow_id}.api.json in the catalog)")
    prompt = d["prompt"]
    fields, seen = [], set()

    def add(node, inp, label=None, group="main"):
        if (node, inp) in seen or node not in prompt or inp not in prompt[node]["inputs"]:
            return
        if isinstance(prompt[node]["inputs"][inp], list):
            return  # wired to another node, not a setting
        seen.add((node, inp))
        f = _field(info, prompt, node, inp, label, group)
        if f.get("role") == "model" and group == "main":
            f["group"] = "model"
        fields.append(f)

    # 1. What the template's author put on its main node, in their order.
    for c in d.get("controls") or []:
        add(c["node"], c["input"], c.get("label"))
    # 2. What any workflow has: pictures / audio / video to load, prompts, size, seed, sampler basics.
    for node, n in prompt.items():
        cls, ins = n["class_type"], n["inputs"]
        if cls in MEDIA:
            add(node, MEDIA[cls][0], (n.get("_meta") or {}).get("title"))
        for inp, v in ins.items():
            if isinstance(v, str) and inp in TEXT_INPUTS and (len(v) > 15 or "\n" in v) and "Save" not in cls:
                add(node, inp, (n.get("_meta") or {}).get("title"))
            elif inp in SEED_INPUTS or (inp in MAIN_LATENT and ("Latent" in cls or cls == "ResolutionSelector")):
                add(node, inp)
            elif inp in MAIN_SAMPLER and cls.startswith("KSampler"):
                add(node, inp)
    # 3. Models and LoRAs.
    for node, n in prompt.items():
        for inp in n["inputs"]:
            if inp in MODEL_FOLDERS or inp == "strength_model":
                add(node, inp, f"{(n.get('_meta') or {}).get('title') or n['class_type']}: {inp}", group="model")
    # 4. Everything else, by node (a primitive's only input is "value": its title says what it is).
    for node, n in prompt.items():
        for inp in n["inputs"]:
            title = (n.get("_meta") or {}).get("title")
            add(node, inp, title if inp == "value" and title else inp, group="advanced")
    for f in fields:  # nicer labels for the template's generic input names
        if f["label"] in ("value", "text", "string_b", "input") and f.get("role") in ("prompt", "negative"):
            f["label"] = "Negative prompt" if f["role"] == "negative" else "Prompt"
        elif f.get("role") == "seed" and f["label"] in SEED_INPUTS:
            f["label"] = "Seed"
        elif f.get("role") == "strength" and "strength" not in f["label"].lower():
            f["label"] = f"{f['label']} strength"
        elif f["label"] == "value":
            f["label"] = f["title"]
    return {"workflow": workflow_id, "fields": fields, "lora_points": len(_model_sources(prompt))}


# ---- running it ----------------------------------------------------------------------------------------
def _model_sources(prompt):
    """Loader nodes whose MODEL output something uses (LoRAs added on the phone go right after them)."""
    used = {tuple(v) for n in prompt.values() for v in n["inputs"].values() if isinstance(v, list) and len(v) == 2}
    return [nid for nid, n in prompt.items() if n["class_type"] in MODEL_LOADERS and (nid, 0) in used]


def chain_loras(prompt, loras):
    """Put each LoRA (name, strength) after the first model loader: everything that used the model uses
    the LoRA's. (Wan's high/low pairs need their own LoRA per expert: add those in ComfyUI.)"""
    sources = _model_sources(prompt)
    if not loras:
        return prompt
    if not sources:
        raise ValueError("This workflow has no model loader to add a LoRA after")
    src = sources[0]
    for i, l in enumerate(loras, 1):
        name = str(l.get("name") or "").strip()
        if not name:
            continue
        nid = f"phone-lora-{i}"
        for n in prompt.values():
            for k, v in n["inputs"].items():
                if v == [src, 0]:
                    n["inputs"][k] = [nid, 0]
        prompt[nid] = {"class_type": "LoraLoaderModelOnly", "_meta": {"title": f"LoRA added on the phone: {name}"},
                       "inputs": {"model": [src, 0], "lora_name": name, "strength_model": float(l.get("strength", 1.0))}}
        src = nid
    return prompt


def build(workflow_id, values=None, loras=None, new_seed=True):
    d = doc(workflow_id)
    if not d:
        raise KeyError(f"{workflow_id} has no Create form")
    prompt = copy.deepcopy(d["prompt"])
    for key, v in (values or {}).items():
        node, _, inp = str(key).partition("|")
        cur = prompt.get(node, {}).get("inputs", {})
        if inp in cur and not isinstance(cur[inp], list):
            cur[inp] = v
    if new_seed:
        for n in prompt.values():
            for k in SEED_INPUTS & set(n["inputs"]):
                if not isinstance(n["inputs"][k], list) and f"{k}" not in (values or {}).get("_fixed", []):
                    n["inputs"][k] = random.randint(0, 2 ** 50)
    return chain_loras(prompt, loras or [])


def _comfy_error(body):
    if not isinstance(body, dict):
        return str(body)[:300]
    lines = [(body.get("error") or {}).get("message") or "ComfyUI refused the job"]
    for nid, e in (body.get("node_errors") or {}).items():
        for x in e.get("errors") or []:
            lines.append(f"{e.get('class_type')} ({nid}): {x.get('message')}: {x.get('details')}")
    return "; ".join(lines)[:600]


async def run(workflow_id, values=None, loras=None, count=1, fixed_seed=False):
    ids = []
    for _ in range(max(1, min(8, int(count or 1)))):
        prompt = build(workflow_id, values, loras, new_seed=not fixed_seed)
        status, body = await comfy("POST", "/prompt", json={"prompt": prompt, "client_id": CLIENT_ID,
                                                            "extra_data": {"comfortable": {"workflow": workflow_id}}})
        if status != 200 or not (body or {}).get("prompt_id"):
            raise ValueError(_comfy_error(body))
        _jobs[body["prompt_id"]] = {"workflow": workflow_id, "at": time.time()}
        ids.append(body["prompt_id"])
    log.info("create: queued %d x %s", len(ids), workflow_id)
    return {"prompt_ids": ids}


VIEW_TYPES = {"output", "temp", "input"}


def _files(outputs):
    """Every file a finished job made (images, video, audio, 3D): saved ones (also in the gallery, as
    `path`) and previews ComfyUI keeps in its temp folder. `view` is the query for /api/create/view."""
    out, seen = [], set()
    for node_out in (outputs or {}).values():
        for items in node_out.values():
            for it in items if isinstance(items, list) else []:
                if not (isinstance(it, dict) and it.get("filename") and it.get("type") in VIEW_TYPES - {"input"}):
                    continue
                sub = it.get("subfolder") or ""
                key = (it["type"], sub, it["filename"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"filename": it["filename"], "type": it["type"],
                            "path": "/".join(x for x in (sub, it["filename"]) if x) if it["type"] == "output" else None,
                            "view": {"filename": it["filename"], "subfolder": sub, "type": it["type"]}})
    return out


async def view(params):
    """A file ComfyUI made or was given (its /view), for the phone: (status, headers, body)."""
    if params.get("type", "output") not in VIEW_TYPES or ".." in str(params.get("subfolder", "")) or "/" in str(params.get("filename", "")):
        raise PermissionError("Not a ComfyUI file")
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(config.COMFY_URL + "/view", params={k: params.get(k, "") for k in ("filename", "subfolder", "type")}) as r:
            if r.status != 200:
                raise FileNotFoundError(params.get("filename"))
            return r.headers.get("Content-Type") or "application/octet-stream", await r.read()


async def jobs(ids):
    _, queue = await comfy("GET", "/queue")
    running = {q[1] for q in (queue or {}).get("queue_running") or []}
    pending = {q[1] for q in (queue or {}).get("queue_pending") or []}
    out = []
    for pid in ids:
        if pid in running:
            out.append({"id": pid, "state": "running"})
            continue
        if pid in pending:
            out.append({"id": pid, "state": "queued"})
            continue
        _, hist = await comfy("GET", f"/history/{pid}")
        h = (hist or {}).get(pid)
        if not h:
            out.append({"id": pid, "state": "unknown"})
            continue
        st = h.get("status") or {}
        err = next((m[1] for m in st.get("messages") or [] if m and m[0] == "execution_error"), None)
        out.append({"id": pid, "state": "failed" if st.get("status_str") == "error" or err else "done",
                    "files": _files(h.get("outputs")),
                    "error": err and f"{err.get('node_type')}: {err.get('exception_message', '').strip()[:400]}"})
    return out


async def cancel(prompt_id):
    _, queue = await comfy("GET", "/queue")
    if prompt_id in {q[1] for q in (queue or {}).get("queue_running") or []}:
        await comfy("POST", "/interrupt", json={"prompt_id": prompt_id})
    else:
        await comfy("POST", "/queue", json={"delete": [prompt_id]})
    return {"cancelled": prompt_id}


async def upload(field):
    """A picture / audio / video from the phone, into ComfyUI's input folder."""
    data = aiohttp.FormData()
    name = f"phone-{uuid.uuid4().hex[:8]}-{(field.filename or 'upload').replace('/', '_')[-60:]}"
    data.add_field("image", await field.read(), filename=name,
                   content_type=field.headers.get("Content-Type") or "application/octet-stream")
    data.add_field("type", "input")
    status, body = await comfy("POST", "/upload/image", data=data, timeout=300)
    if status != 200 or not isinstance(body, dict):
        raise ValueError(f"ComfyUI didn't take the file ({status})")
    sub = body.get("subfolder") or ""
    return {"name": body.get("name"), "value": f"{sub}/{body['name']}" if sub else body["name"]}
