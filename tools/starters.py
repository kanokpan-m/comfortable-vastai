#!/usr/bin/env python3
"""Build the starter workflows in catalog/workflows/ from ComfyUI's official templates.

  python tools/starters.py                       build every recipe in catalog/starters.json
  python tools/starters.py krea2-nsfw-lustify    build one
  python tools/starters.py --templates DIR       read templates from a local copy (e.g. the
                                                 comfyui_workflow_templates_json package) instead of GitHub

A recipe (catalog/starters.json) names an official template and what to change in it:

  {"id": "...", "base": "image_krea2_turbo_t2i",           template name (templates/<base>.json)
   "swap": {"old_file.safetensors": {"name": "new_file.safetensors", "url": "...", "directory": "loras"}},
                                                            replace a model file everywhere it is used,
                                                            including the node's download link
   "set": {"lora_name_1": "...", "value_3": true},          values of the main subgraph's exposed widgets,
                                                            by input name
   "nodes": {"15": {"widgets": {"0": "..."}, "mode": 0}},  a node's own widgets (by index) or mode
                                                            (0 = on, 4 = bypassed); ids may be inner nodes
   "loras": [{"after": "78", "name": "style.safetensors", "url": "...", "strength": 0.8, "title": "Style LoRA"}],
                                                            chain a LoRA right after a model loader (or another
                                                            LoRA): everything that used its model uses the LoRA's.
                                                            A loader with a CLIP output gets a LoraLoader (with
                                                            "strength_clip", default = strength), others a
                                                            LoraLoaderModelOnly; inside a subgraph its file and
                                                            strength are shown on the main node; "mode": 4
                                                            adds it bypassed (an optional slot)
   "note": "markdown shown at the top of the workflow",     replaces the template's notes
   "thumbnail": false}                                      the card shows its packs' samples, not the template's
                                                            thumbnail (style starters: the base model's picture
                                                            isn't their look; read by `catalog.py previews`)

"base" can also be "catalog:<id>": one of our own starters (catalog/workflows/<id>.json), e.g. a
hand-built one, as it is now.
Graphs built by hand (no official template) live in catalog/workflows/ directly and have no recipe.
"""
import argparse
import copy
import json
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
RAW = "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/{}.json"
WIDGET_TYPES = {"COMBO", "INT", "FLOAT", "STRING", "BOOLEAN"}


def template(name, local_dir=None):
    if name.startswith("catalog:"):
        return json.loads((CATALOG / "workflows" / f"{name[8:]}.json").read_text(encoding="utf-8"))
    if local_dir:
        return json.loads((Path(local_dir) / f"{name}.json").read_text(encoding="utf-8"))
    with urllib.request.urlopen(urllib.request.Request(RAW.format(name), headers={"User-Agent": "comfortable"}), timeout=60) as r:
        return json.loads(r.read())


def graphs(wf):
    return [wf] + list((wf.get("definitions") or {}).get("subgraphs") or [])


def all_nodes(wf):
    for g in graphs(wf):
        for n in g.get("nodes") or []:
            yield g, n


def _replace(value, old, new):
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_replace(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: _replace(v, old, new) for k, v in value.items()}
    return value


def swap(wf, old, new):
    """Use `new` (name, url, directory) wherever the template uses the model file `old`."""
    hits = 0
    for _g, n in all_nodes(wf):
        before = json.dumps(n.get("widgets_values"))
        n["widgets_values"] = _replace(n.get("widgets_values"), old, new["name"])
        changed = before != json.dumps(n.get("widgets_values"))
        models = (n.get("properties") or {}).get("models") or []
        for m in models:
            if m.get("name") == old or m.get("name", "").rsplit("/", 1)[-1] == old:
                m.update(name=new["name"], url=new["url"], directory=new.get("directory") or m.get("directory"))
                changed = True
        if changed and not any(m.get("name") == new["name"] for m in models) and n.get("type") != _subgraph_type(wf, n):
            n.setdefault("properties", {}).setdefault("models", []).append(
                {"name": new["name"], "url": new["url"], "directory": new.get("directory", "")})
        hits += changed
    if not hits:
        raise SystemExit(f"  {old} is not used in the template")


def _subgraph_type(wf, n):
    ids = {g.get("id") for g in graphs(wf)[1:]}
    return n.get("type") if n.get("type") in ids else None


def set_exposed(wf, values):
    """Set the main subgraph instance's exposed widgets by the subgraph's input names."""
    defs = {g.get("id"): g for g in graphs(wf)[1:]}
    inst = next((n for n in wf.get("nodes") or [] if n.get("type") in defs), None)
    if not inst:
        raise SystemExit("  the template has no subgraph to set values on")
    names = [i["name"] for i in defs[inst["type"]].get("inputs") or [] if i.get("type") in WIDGET_TYPES]
    for key, value in values.items():
        if key not in names:
            raise SystemExit(f"  {key} is not an exposed widget (have: {', '.join(names)})")
        inst["widgets_values"][names.index(key)] = value


def set_nodes(wf, changes):
    found = set()
    for _g, n in all_nodes(wf):
        c = changes.get(str(n.get("id")))
        if not c:
            continue
        found.add(str(n["id"]))
        for idx, value in (c.get("widgets") or {}).items():
            n["widgets_values"][int(idx)] = value
        if "mode" in c:
            n["mode"] = c["mode"]
        if "title" in c:
            n["title"] = c["title"]
    missing = set(changes) - found
    if missing:
        raise SystemExit(f"  no node with id {', '.join(sorted(missing))}")


def _link_ids(g):
    return [lk["id"] if isinstance(lk, dict) else lk[0] for lk in g.get("links") or []]


def _relink_origin(g, link_id, origin_id, origin_slot):
    for lk in g.get("links") or []:
        if isinstance(lk, dict) and lk["id"] == link_id:
            lk["origin_id"], lk["origin_slot"] = origin_id, origin_slot
        elif isinstance(lk, list) and lk[0] == link_id:
            lk[1], lk[2] = origin_id, origin_slot


def _add_link(g, link_id, origin_id, origin_slot, target_id, target_slot, kind):
    if g.get("links") and isinstance(g["links"][0], dict) or "inputNode" in g:
        g.setdefault("links", []).append({"id": link_id, "origin_id": origin_id, "origin_slot": origin_slot,
                                          "target_id": target_id, "target_slot": target_slot, "type": kind})
    else:
        g.setdefault("links", []).append([link_id, origin_id, origin_slot, target_id, target_slot, kind])


def add_lora(wf, spec):
    """Chain a LoRA after the node spec["after"] (a model loader or another LoRA)."""
    hits = [(g, n) for g, n in all_nodes(wf) if str(n.get("id")) == str(spec["after"])]
    if len(hits) != 1:
        raise SystemExit(f"  loras: {len(hits)} nodes with id {spec['after']}")
    g, src = hits[0]
    outs = src.get("outputs") or []
    kinds = ["MODEL", "CLIP"] if spec.get("clip", any(o.get("type") == "CLIP" for o in outs)) else ["MODEL"]
    node_id = max(int(n.get("id") or 0) for _g, n in all_nodes(wf)) + 1
    link_id = max([0, *_link_ids(g), int((g.get("state") or {}).get("lastLinkId") or 0),
                   int(g.get("last_link_id") or 0) if g is wf else 0]) + 1
    strength = spec.get("strength", 1.0)
    node = {"id": node_id, "type": "LoraLoader" if "CLIP" in kinds else "LoraLoaderModelOnly",
            "pos": [src.get("pos", [0, 0])[0], src.get("pos", [0, 0])[1] + (src.get("size") or [0, 100])[1] + 60],
            "size": [340, 130 if "CLIP" in kinds else 82], "flags": {}, "order": src.get("order", 0), "mode": 0,
            "inputs": [{"name": k.lower(), "type": k, "link": None} for k in kinds] +
                      [{"name": w, "type": t, "widget": {"name": w}, "link": None} for w, t in
                       [("lora_name", "COMBO"), ("strength_model", "FLOAT")] + ([("strength_clip", "FLOAT")] if "CLIP" in kinds else [])],
            "outputs": [{"name": k, "type": k, "links": []} for k in kinds],
            "properties": {"Node name for S&R": "LoraLoader" if "CLIP" in kinds else "LoraLoaderModelOnly", "cnr_id": "comfy-core",
                           "models": [{"name": spec["name"], "url": spec["url"], "directory": "loras"}]},
            "widgets_values": [spec["name"], strength] + ([spec.get("strength_clip", strength)] if "CLIP" in kinds else [])}
    if spec.get("title"):
        node["title"] = spec["title"]
    if spec.get("mode") is not None:
        node["mode"] = spec["mode"]  # 4 = bypassed: an optional slot the user turns on with Ctrl+B
    for i, kind in enumerate(kinds):
        slot = next((j for j, o in enumerate(outs) if o.get("type") == kind), None)
        if slot is None:
            raise SystemExit(f"  loras: node {spec['after']} has no {kind} output")
        old = list(outs[slot].get("links") or [])
        for lid in old:
            _relink_origin(g, lid, node_id, i)
        # Downstream nodes keep their input links; only the origin moved.
        outs[slot]["links"] = [link_id]
        node["inputs"][i]["link"] = link_id
        node["outputs"][i]["links"] = old
        _add_link(g, link_id, src["id"], slot, node_id, i, kind)
        link_id += 1
    g["nodes"].append(node)
    if g is wf:
        wf["last_node_id"] = max(int(wf.get("last_node_id") or 0), node_id)
        wf["last_link_id"] = max(int(wf.get("last_link_id") or 0), link_id - 1)
    else:
        # Show the LoRA on the subgraph's node the way the template shows its own widgets: as promoted
        # widgets (properties.proxyWidgets) or as subgraph inputs with the value on the node.
        for _g, inst in all_nodes(wf):
            if inst.get("type") != g.get("id"):
                continue
            props = inst.setdefault("properties", {})
            if props.get("proxyWidgets") is not None:
                props["proxyWidgets"] = list(props["proxyWidgets"]) + [[str(node_id), "lora_name"], [str(node_id), "strength_model"]]
            else:
                for widget, kind, value, label in (("lora_name", "COMBO", spec["name"], spec.get("label", "style_lora")),
                                                   ("strength_model", "FLOAT", strength, spec.get("label", "style_lora") + "_strength")):
                    _expose(g, inst, node, widget, kind, value, label, link_id)
                    link_id += 1
        g.setdefault("state", {}).update(lastNodeId=max(int(g["state"].get("lastNodeId") or 0), node_id),
                                         lastLinkId=max(int(g["state"].get("lastLinkId") or 0), link_id - 1))
    return node_id


def _expose(g, inst, node, widget, kind, value, label, link_id):
    """Make `widget` of inner `node` a subgraph input, with `value` on the subgraph's node."""
    inputs = g.setdefault("inputs", [])
    names = {i["name"] for i in inputs}
    name, k = widget, 1
    while name in names:
        name, k = f"{widget}_{k}", k + 1
    before = sum(1 for i in inputs if i.get("type") in WIDGET_TYPES)
    values = inst.setdefault("widgets_values", [])
    if len(values) != before:
        raise SystemExit(f"  loras: the subgraph node has {len(values)} values for {before} widgets")
    last = inputs[-1].get("pos") if inputs else None
    inputs.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{g.get('id')}/{node['id']}/{widget}")), "name": name, "type": kind,
                   "linkIds": [link_id], "label": label, "pos": [last[0], last[1] + 20] if last else [0, 0]})
    slot = next(j for j, i in enumerate(node["inputs"]) if i["name"] == widget)
    node["inputs"][slot]["link"] = link_id
    _add_link(g, link_id, -10, len(inputs) - 1, node["id"], slot, kind)
    box = (g.get("inputNode") or {}).get("bounding")
    if box and len(box) == 4:
        box[3] += 20
    inst.setdefault("inputs", []).append({"label": label, "name": name, "type": kind, "widget": {"name": name}, "link": None})
    values.append(value)


def set_note(wf, text):
    """Put our note where the template's main note was; drop its other notes."""
    notes = [n for n in wf.get("nodes") or [] if n.get("type") in ("MarkdownNote", "Note")]
    if notes:
        keep = max(notes, key=lambda n: (n.get("size") or [0, 0])[0] * (n.get("size") or [0, 0])[1])
        keep["widgets_values"] = [text]
        keep["title"] = "Read me"
        drop = {n["id"] for n in notes if n is not keep}
        wf["nodes"] = [n for n in wf["nodes"] if n.get("id") not in drop]
    else:
        nid = max((n.get("id") or 0 for n in wf.get("nodes") or []), default=0) + 1
        wf.setdefault("nodes", []).append({"id": nid, "type": "MarkdownNote", "pos": [-520, 0], "size": [480, 420], "flags": {}, "order": 0,
                                           "mode": 0, "inputs": [], "outputs": [], "properties": {}, "widgets_values": [text], "title": "Read me"})
        wf["last_node_id"] = max(wf.get("last_node_id") or 0, nid)


def build(recipe, local_dir=None):
    wf = copy.deepcopy(template(recipe["base"], local_dir))
    for old, new in (recipe.get("swap") or {}).items():
        swap(wf, old, new)
    if recipe.get("set"):
        set_exposed(wf, recipe["set"])
    if recipe.get("nodes"):
        set_nodes(wf, recipe["nodes"])
    for spec in recipe.get("loras") or []:
        add_lora(wf, spec)
    if recipe.get("note"):
        set_note(wf, recipe["note"])
    wf.setdefault("extra", {})["comfortable"] = {"starter": recipe["id"], "base_template": recipe["base"]}
    return wf


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ids", nargs="*")
    p.add_argument("--templates", help="local folder with the official template JSON files")
    a = p.parse_args()
    recipes = json.loads((CATALOG / "starters.json").read_text(encoding="utf-8"))
    out = CATALOG / "workflows"
    out.mkdir(exist_ok=True)
    for r in recipes:
        if a.ids and r["id"] not in a.ids:
            continue
        print(f"{r['id']} <- {r['base']}")
        wf = build(r, a.templates)
        (out / f"{r['id']}.json").write_text(json.dumps(wf, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
