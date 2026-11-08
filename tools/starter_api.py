#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["aiohttp>=3.9"]
# ///
"""Save each starter workflow in the form ComfyUI runs (its "API prompt") plus the controls its template
shows, so the dashboard's Create screen (phone) can run starters without ComfyUI's editor.

  uv run --script tools/starter_api.py [ids...] [--comfy http://127.0.0.1:8188] [--validate]

Needs a local ComfyUI with the same frontend as the instances (0.44 / 1.58.5; CPU is fine) and Chrome:
the starter is loaded in ComfyUI's own editor (headless) and turned into a prompt exactly the way its
Run button does. Writes catalog/workflows/<id>.api.json:

  {"workflow": id, "graph_sha256": <the graph it was made from>, "frontend": "1.58.5",
   "prompt": {node id: {class_type, inputs, _meta}},
   "controls": [{"node": "90:77", "input": "text", "label": "positive_prompt"}, ...]}

`controls` are the widgets the template puts on its main node (subgraph inputs and promoted widgets),
in order: what the template's author considered the knobs. Inner nodes of a subgraph get the id
"<subgraph node id>:<inner id>" in the prompt, the same as when ComfyUI runs it.
--validate also queues each prompt (then removes it) so ComfyUI checks every input; with model files
missing locally it reports them (the validator in the catalog README uses empty placeholder files).
"""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
WIDGET_TYPES = {"COMBO", "INT", "FLOAT", "STRING", "BOOLEAN"}
CHROMES = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser"]
JS = r"""
(async (text, name, validate) => {
  await app.loadGraphData(JSON.parse(text), true, true, name);
  await new Promise((r) => setTimeout(r, 300));
  const p = await app.graphToPrompt();
  let check = null;
  if (validate) {
    const r = await fetch('/prompt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: p.output, client_id: 'starter-api' }) });
    const body = await r.json();
    if (body.prompt_id) {
      await fetch('/queue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ delete: [body.prompt_id] }) });
      await fetch('/interrupt', { method: 'POST' });
    }
    check = { ok: !!body.prompt_id, error: body.error || null, node_errors: body.node_errors || {} };
  }
  return { prompt: p.output, frontend: window.__COMFYUI_FRONTEND_VERSION__ || null, check };
})
"""


def chrome_path(given):
    for c in [given] + CHROMES if given else CHROMES:
        if c and (Path(c).is_file() or shutil.which(c)):
            return c if Path(c).is_file() else shutil.which(c)
    sys.exit("Chrome not found: pass --chrome PATH")


def controls(ui, prompt):
    """The widgets on each subgraph node of the main graph (its inputs, then promoted widgets), as
    (prompt node id, input) with the label the template shows. Only ones that are plain values."""
    subs = {s["id"]: s for s in (ui.get("definitions") or {}).get("subgraphs") or []}
    out, seen = [], set()

    def add(node, inp, label):
        if (node, inp) in seen or node not in prompt or isinstance(prompt[node]["inputs"].get(inp, []), list):
            return
        seen.add((node, inp))
        out.append({"node": node, "input": inp, "label": label})

    for n in ui.get("nodes") or []:
        s = subs.get(n.get("type"))
        if not s or n.get("mode") in (2, 4):
            continue
        inst = str(n["id"])
        inner = {str(x["id"]): x for x in s.get("nodes") or []}
        links = [lk for lk in s.get("links") or [] if isinstance(lk, dict) and lk.get("origin_id") == -10]
        for idx, i in enumerate(s.get("inputs") or []):
            if i.get("type") not in WIDGET_TYPES:
                continue
            for lk in links:
                if lk.get("origin_slot") != idx:
                    continue
                target = inner.get(str(lk.get("target_id")))
                ins = (target or {}).get("inputs") or []
                slot = lk.get("target_slot")
                if target and isinstance(slot, int) and slot < len(ins):
                    name = (ins[slot].get("widget") or {}).get("name") or ins[slot].get("name")
                    add(f"{inst}:{target['id']}", name, i.get("label") or i.get("localized_name") or i.get("name"))
        for inner_id, widget in (n.get("properties") or {}).get("proxyWidgets") or []:
            target = inner.get(str(inner_id))
            if target:
                add(f"{inst}:{inner_id}", widget, target.get("title") or widget)
    return out


async def main(a):
    data = json.loads((CATALOG / "catalog.json").read_text(encoding="utf-8"))
    wfs = [w for w in data["workflows"] if not a.ids or w["id"] in a.ids]
    chrome = chrome_path(a.chrome)
    port = 9339
    profile = tempfile.mkdtemp(prefix="starter-api-")
    proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bad = 0
    try:
        async with aiohttp.ClientSession() as s:
            tabs = []
            for _ in range(100):
                try:
                    tabs = await (await s.get(f"http://127.0.0.1:{port}/json")).json()
                    if any(t.get("type") == "page" for t in tabs):
                        break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.2)
            page = next(t for t in tabs if t.get("type") == "page")
            async with s.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                seq = 0

                async def cmd(method, **params):
                    nonlocal seq
                    seq += 1
                    me = seq
                    await ws.send_json({"id": me, "method": method, "params": params})
                    while True:
                        msg = await ws.receive_json()
                        if msg.get("id") == me:
                            if "error" in msg:
                                raise RuntimeError(f"{method}: {msg['error']}")
                            return msg.get("result", {})

                await cmd("Page.navigate", url=a.comfy.rstrip("/") + "/")
                for _ in range(120):
                    r = await cmd("Runtime.evaluate", returnByValue=True, expression=(
                        "!!(window.app && window.app.graph && window.LiteGraph && Object.keys(LiteGraph.registered_node_types).length > 300)"))
                    if r.get("result", {}).get("value"):
                        break
                    await asyncio.sleep(0.5)
                else:
                    sys.exit(f"ComfyUI's editor didn't load at {a.comfy}")
                await asyncio.sleep(2)
                for w in wfs:
                    path = CATALOG / w["graph"]
                    ui = json.loads(path.read_text(encoding="utf-8"))
                    expr = f"({JS})({json.dumps(json.dumps(ui))}, {json.dumps(w['id'])}, {json.dumps(a.validate)})"
                    r = await cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
                    v = r.get("result", {}).get("value")
                    if not v:
                        bad += 1
                        print(f"✗ {w['id']}: {json.dumps(r)[:300]}")
                        continue
                    prompt = v["prompt"]
                    doc = {"workflow": w["id"], "graph_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "frontend": v.get("frontend"),
                           "prompt": prompt, "controls": controls(ui, prompt)}
                    out = path.with_name(f"{w['id']}.api.json")
                    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                    line = f"{w['id']}: {len(prompt)} nodes, {len(doc['controls'])} controls"
                    check = v.get("check")
                    if check and not check["ok"]:
                        errs = [f"{e.get('class_type')}[{nid}] {x.get('message')}: {x.get('details')}"[:160]
                                for nid, e in check["node_errors"].items() for x in e.get("errors") or []]
                        line += f"  (ComfyUI: {(check.get('error') or {}).get('message', '')}; {'; '.join(errs[:4])})"
                    print(("✓ " if not check or check["ok"] else "~ ") + line)
    finally:
        proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ids", nargs="*")
    p.add_argument("--comfy", default=os.environ.get("COMFYUI_URL") or "http://127.0.0.1:8188")
    p.add_argument("--chrome")
    p.add_argument("--validate", action="store_true")
    sys.exit(asyncio.run(main(p.parse_args())))
