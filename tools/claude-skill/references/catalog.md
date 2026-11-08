# Maintaining the "Suggested by AI" catalog

What the dashboard's Suggested and Workflows screens, the MCP `find_setups` / `install_setups`
tools, `comfortable.py catalog` and `rent --install` all read. Schema: `catalog/README.md` in the
repo; research notes: `docs/model-research-2026-11.md`.

## Contents
- What's in it
- Adding or updating a pack
- Adding or updating a starter workflow
- Check, verify, previews, publish
- Content rules

## What's in it

- `catalog/catalog.json`: `version` (`YYYY.MM.DD`, a `.N` suffix for same-day releases),
  `categories`, `packs`, `workflows`. A **pack** is every file one setup needs (model, text encoder,
  VAE, speed LoRA, node packs) with `requires` (shared component packs installed with it),
  `settings` (steps, CFG, sampler, scheduler, shift, resolution, frames, fps, strength), trigger
  words, `vram_gb`, `nsfw`, `previews`. A **workflow** (starter) is a ComfyUI graph in
  `catalog/workflows/<id>.json` plus `packs`, `node_packs`, `steps` (how to use it) and `inputs`.
- Each file entry: `category` (ComfyUI models folder), `filename` (path inside it, sub-folder
  included, exactly as the starter's loader names it), `url`, `size`, `sha256`, `source`,
  `needs_token` (Civitai serves it only with an API key: most mature files), `optional`.
- Dashboards use the database copy when its `version` is at least the shipped one.

## Adding or updating a pack

1. Research with the APIs, not guesses: Civitai `GET https://civitai.com/api/v1/models?query=...&types=LORA&nsfw=true`
   and `/api/v1/model-versions/<id>` (files with `sizeKB`, `hashes.SHA256`, `downloadUrl`, base model,
   trained words, images with `nsfwLevel`); Hugging Face `GET https://huggingface.co/api/models/<repo>/tree/main?recursive=true`
   (`lfs.oid` is the sha256). Use the newest free version (no early-access / Buzz-paid ones). The
   user's Civitai key and HF token can be read from the environment (`CIVITAI_TOKEN`, `HF_TOKEN`) or
   the dashboard settings; never print them.
2. Pick the folder and filename the workflows will use. Official Comfy-Org repackages and DaSiWa's
   workflows expect sub-folders (`MiniMaxH3/`, `WAN22/`, `bbox/` under `ultralytics`).
3. Shared encoders / VAEs go in a component pack (`kind: component`) that others `require`, so one
   copy serves every finetune.
4. Write `summary` (what it does), `why` (when to pick it, what it pairs with), `settings` from the
   creator's notes, `vram_gb` from file sizes (fp8 12B ≈ 13 GB file → 16 GB card).
5. Bump `version`.

## Adding or updating a starter workflow

- Built from an official template: add a recipe to `catalog/starters.json` (base template, `swap`
  model files, `set` exposed subgraph inputs, `nodes` widget overrides / modes, `loras` to chain an
  extra LoRA after a loader (shown on the main node), `note`), then
  `python tools/starters.py <id> --templates <ComfyUI venv>/Lib/site-packages/comfyui_workflow_templates_json/templates`
  (or from GitHub without `--templates`). `"base": "catalog:<id>"` starts from one of our own
  starters instead (e.g. the hand-built Illustrious one with an artist + style LoRA chained in).
- Templates saved by another frontend can have shifted widget values (a seed control the current
  frontend doesn't create): validation shows it, fix the values with `nodes`.
- Built by hand: save the graph from ComfyUI (UI format) into `catalog/workflows/<id>.json`; every
  loader should carry `properties.models` (name, url, directory) so the fixer can fetch files even
  when the workflow is shared alone.
- Then save its run-ready copy for the Create screen (phones): `uv run --script tools/starter_api.py <id>
  --comfy <local ComfyUI>` writes `catalog/workflows/<id>.api.json`; `catalog.py check` fails when it's
  missing or older than the graph.
- Validate it really runs: in a local ComfyUI (CPU is fine) with placeholder files at the expected
  paths, queue it through `/prompt` and expect no validation errors (bypassed/muted nodes are not
  validated). Then add the workflow entry (`task`, `categories`, `nsfw`, `steps`, `inputs`, `packs`).

## Check, verify, previews, publish

```bash
python tools/catalog.py check                       # ids, references, folders, sizes, every model a starter's active nodes load is installed by its packs
CIVITAI_TOKEN=... HF_TOKEN=... python tools/catalog.py verify --fix   # sizes and sha256 against the sources
CIVITAI_TOKEN=... python tools/catalog.py previews  # refresh sample images / videos shown on the cards
MONGO_URI=... python tools/catalog.py publish       # every dashboard picks it up on its next sync (15 s)
```

`publish` needs `--public-dns` on networks whose router drops SRV lookups (`mongodb+srv` URIs),
takes `--uri-file` instead of `MONGO_URI`, and refuses when `check` finds problems (`--force` to
override). Publishing writes the user's shared database: do it when they asked for it. CI runs
`check` on every push.

## Content rules

Adult content is in scope (NSFW photo, video, hentai, concepts). Leave out real-person or celebrity
likeness LoRAs, age sliders and anything child-coded, Krea 2 filter-bypass LoRAs, and face-swap tools
that silently refuse NSFW (ReActor). Respect creators' redistribution terms: link to their files,
don't mirror them.
