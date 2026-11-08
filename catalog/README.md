# The "Suggested by AI" catalog

What the dashboard's **Suggested by AI** and **Workflows** screens show. Researched on
2026-11-08 from the Civitai and Hugging Face APIs (every file checked live: size, sha256,
download link) and the official ComfyUI templates; the research notes are in
[docs/model-research-2026-11.md](../docs/model-research-2026-11.md).

| File | What it is |
|---|---|
| `catalog.json` | `version`, `categories`, `packs`, `workflows` (graphs are referenced by path) |
| `workflows/*.json` | Starter workflows, ComfyUI graphs (UI format) |
| `starters.json` | Recipes that build most starters from ComfyUI's official templates (`tools/starters.py`) |

## Packs

A pack is everything one setup needs, installed with one click:

```
{id, title, kind: base|checkpoint|lora|video|controlnet|upscaler|tool|embedding|component,
 categories: [category ids], base_model, nsfw, summary, why, works_with,
 settings: {steps, cfg, sampler, scheduler, shift, resolution, frames, fps, strength, notes},
 trigger_words: [], requires: [pack ids], vram_gb, preview: {url, nsfw_level},
 previews: [{url, type: image|video, nsfw_level, width, height, animated?, source?}],
 files: [{name, category, filename, url, size, sha256, source, civitai?|hf?, needs_token?, optional?}],
 node_packs: [{id: <Comfy Registry id>, title, repository}], links: [{title, url}],
 component?: true, rank}
```

- `filename` is the path inside the ComfyUI models folder, sub-folder included
  (`MiniMaxH3/...`, `WAN22/...`, `bbox/face_yolov8m.pt` under `ultralytics`), exactly as
  the starter workflows (and DaSiWa's own workflows) look for it.
- `requires` lists packs that must be there too (a Krea 2 finetune needs the Krea 2 text
  encoder + VAE). Installing a pack installs what it requires; LoRAs require nothing and say
  what they work with instead.
- `component` packs (shared text encoders / VAEs) are not shown in the grid, only under "Needs".
- `needs_token`: Civitai only serves the file to signed-in users (most mature models): the
  dashboard sends the Civitai API key from Settings.
- `previews`: sample images and videos, at most 4 safe and 4 mature (`nsfw_level` 4 or more), taken
  from the model version's Civitai gallery by `tools/catalog.py previews`. Samples Civitai flags as
  showing a minor or a real person are never used, nor any whose prompt has a word that could read
  as young; mature samples, and every sample of an 18+ pack, also need a known prompt. Official
  models without a Civitai gallery get the thumbnail of the official ComfyUI template they star in
  (`source: "template"`, an animated WebP for video templates, served by jsDelivr from the
  `workflow_templates` release); Hugging Face models with no template get their model card's
  picture (`source: "card"`, from `preview`). The dashboard shows mature samples only with "Show mature
  content" on (or revealed for the session), and then first. `preview` is the older single
  picture, still used for library thumbnails.
- When samples don't load (missing, blocked, or hanging for 10 s; 25 s on a host that has loaded
  others), the dashboard tries the next one, skips a host that keeps failing with nothing loaded
  from it, then shows images people generated with the model
  (Civitai's public feed, safe ones only, same prompt screen), and otherwise a poster in the
  model's own colours with its icon. The poster also shows while anything loads. Every model
  picture in the dashboard uses this chain (library, Discover, downloads, Fixer, add-model),
  starting from the model's own preview and its Civitai gallery (video models: a clip's first
  frame), and a gallery output that can't be shown gets a poster with its file name.

## Starter workflows

```
{id, title, task: t2i|edit|pose|controlnet|upscale|style|detail|inpaint|layout|angles|cutout|caption|
       i2v|t2v|flf2v|lipsync|video|audio|3d,
 categories, nsfw, summary, steps: [how to use], inputs: [what to load],
 packs: [pack ids], node_packs: [...], graph: "workflows/<id>.json",
 previews: [official template thumbnail], rank}
```

A starter's card shows what it makes: its packs' samples and its template thumbnail, rotating
(videos play), with every model it uses as a circle; the details panel has the full gallery.

Each starter also ships as `workflows/<id>.api.json`: the prompt ComfyUI runs, made by ComfyUI's own
editor (`tools/starter_api.py`, needs a local ComfyUI and Chrome), plus the widgets its template
puts on its main node, and the hash of the graph it came from. The dashboard's Create screen runs
starters from these without ComfyUI's editor; `check` fails when one is missing or older than its
graph.

Every loader in a starter carries its download link (`properties.models`), so the Fixer
inside ComfyUI can fetch anything missing even when the workflow is shared on its own.
`tools/catalog.py check` makes sure every model a starter's active nodes use is installed by
its packs, at the path the node expects.

## Updating

```bash
python tools/starters.py --templates <ComfyUI venv>/Lib/site-packages/comfyui_workflow_templates_json/templates
uv run --script tools/starter_api.py --comfy http://127.0.0.1:8188   # run-ready copies for the Create screen
python tools/catalog.py check                      # ids, references, folders, starter models
CIVITAI_TOKEN=... python tools/catalog.py verify --fix   # every file against Hugging Face / Civitai
CIVITAI_TOKEN=... python tools/catalog.py previews       # sample images / videos (about 2 minutes)
MONGO_URI=... python tools/catalog.py publish      # every instance picks it up on its next sync
```

Bump `version` (`YYYY.MM.DD`, `YYYY.MM.DD.N` for another change the same day) when you change
anything: dashboards use the database copy when its version is at least the one shipped with
them, otherwise the shipped `catalog.json`.
Starters without a recipe (`illustrious-hentai`, `illustrious-pose`, `upscale-fast`) were built
by hand in ComfyUI 0.44 / frontend 1.58.5 and are edited there. A recipe can start from one of
them (`"base": "catalog:illustrious-hentai"`) and chain extra LoRAs after a loader (`loras`); the
style starters do that to put an artist or style LoRA into an official template.
