---
name: comfortable
description: Set up, run and manage ComfyUI on rented Vast.ai GPUs with the user's Comfortable stack (Vast template "Comfortable" id 733467, the Comfortable dashboard and ComfyUI tab, the `comfortable` MCP server and CLI). Use it whenever the user wants ComfyUI ready for something - a checkpoint, LoRA, video model, custom node pack or a whole workflow (image/text to video, first/last frame, lip sync, NSFW photo/video/hentai, pose transfer, ControlNet, inpainting, upscaling, artist or style looks, image edit, new camera angles, background removal, image to 3D, music) installed correctly and fast; wants a GPU found, rented, checked, stopped or destroyed; asks what their instance is doing or costing; wants a workflow checked or fixed for missing models or nodes; works with bundles, the "Suggested by AI" catalog or starter workflows; or changes the comfortable-vastai repo (catalog, database, dashboard). Use it even when they only say "get DaSiWa running" or "set me up for Wan 2.2 on a 4090". Not for chatting with an LLM on Vast (vast-llm skill).
---

# Comfortable: ComfyUI on Vast.ai

The user's own stack, repo `kanokpan-m/comfortable-vastai` (checked out at
`D:\Projects\Apps\comfortable-vastai` on their PC). An instance rented with the Vast template
"Comfortable" provisions ComfyUI plus the **Comfortable dashboard**: model library and bundles,
a download queue with checksums, a fixer for missing models and node packs, the curated
**"Suggested by AI" catalog** (model packs + starter workflows with every model selected), host
health check, GPU benchmark, gallery, auto-stop. A **Comfortable tab** inside ComfyUI shows the
fixer. The usual job: get the user from an idea ("NSFW image to video") to a ComfyUI tab with the
right workflow open and every file in place, spending as little money and waiting as possible.

## Which interface

1. **MCP tools `mcp__comfortable__*`** when they are listed: structured results, one-call batch
   installs, offline catalog answers, and renting guarded by `confirm`. Tool-by-tool notes,
   setup and troubleshooting: [references/mcp.md](references/mcp.md).
2. **The CLI** otherwise: `python D:\Projects\Apps\comfortable-vastai\tools\comfortable.py <cmd>`
   (same ranking and rent logic; use the Python that has `vastai` installed; on Windows plain
   `python` may be the Store stub). Commands and the rent procedure: [references/cli.md](references/cli.md).
3. **Any dashboard route**: MCP `call_dashboard_api` or `comfortable.py api PATH`. Architecture,
   ports, logs, env vars and routes: [references/ecosystem.md](references/ecosystem.md).

If the user wants the MCP server and it isn't loaded, offer to register it (references/mcp.md).

## Recipes

### Set something up on a running instance
1. `status` first: GPU and VRAM, free disk, whether ComfyUI is busy, running downloads, whether
   the Civitai key is set. Say in one line what you found.
2. `find_setups` with the user's words; filter with `nsfw`, `category`, `max_vram_gb` (their GPU).
   Prefer **starter workflows** (`type: workflow`): every model is already selected in every node.
   Packs are for adding a model or LoRA to a workflow of their own. `get_setup` gives a starter's
   how-to steps and a pack's recommended settings, trigger words and what it works with.
3. `plan_install` and read its warnings before downloading tens of GB:
   - Civitai key missing (most NSFW files need it): ask the user to paste their key into the
     dashboard's Settings themselves, so it never lands in the chat.
   - Not enough disk: an instance's disk can't be grown; free space or rent a bigger disk.
   - VRAM short: offer a lighter alternative from `find_setups` or a bigger GPU.
4. `install_setups` (starters are saved into ComfyUI's Workflows sidebar by default). Add
   `save_as_bundle` + `auto_install_next_time` when they'll want it on every future instance.
5. `install_progress(task_ids, wait_seconds=300)` until `finished`; report GB done, speed and ETA
   briefly. A failed Civitai file is almost always the missing key (401) or a moved link.
6. Node packs installed (`restart_needed`) → `restart_comfyui`. It refuses while a job runs;
   `force` only after the user agrees to lose that job.
7. `open_workflow` → give the link (or the sidebar path), the starter's steps and inputs, and the
   settings that matter (steps, CFG, sampler, LoRA strength, trigger words).

### Rent a GPU for something
1. Pin down what will run: `find_setups` ids, or `check_workflow` on their workflow file (works
   offline: VRAM and download size).
2. `find_gpu(for_setups=[...], disk_gb=..., max_price=..., hours=...)` with the user's real numbers:
   disk = download size + 30-50 GB for outputs; hours = how long they'll really work (it spreads the
   host's download fee). Say what you assumed.
3. Show 2-3 offers: offer id, GPU + VRAM, location, real $/h, download and upload $/TB, power
   share, images/hour (estimated when `speed_measured` is false), host score; recommend one and
   why. Wait for the user to pick.
4. `rent_gpu(offer_id, confirm=true)` only after a clear yes to that offer and price. It sets up
   the `for_setups` at boot, so models download while the instance is still starting.
5. `wait_for_instance` (call again while it says `waiting`). It connects when ready and reports
   the host check; a `poor` or failed host is remembered and skipped from then on. Tell the user
   and offer to destroy it and pick another offer together.
6. `install_progress(wait_seconds=300)` to watch the boot install (`boot_install` shows node packs,
   ComfyUI restart and the starters saved), then `open_workflow`.

### Make any workflow run
`check_workflow` (a local file, JSON, or `comfyui_path` from `list_comfyui_workflows`) → explain
what's missing and where each file would come from → `fix_workflow` → `install_progress` →
`restart_comfyui` if node packs went in → tell them to reload the workflow. Gated Hugging Face files
need the licence accepted on the site and an HF token in Settings. For files nothing found, use
`search_models` and `add_model` with the exact filename and sub-folder the workflow expects
(`WAN22/...`, `MiniMaxH3/...`): ComfyUI only finds a file at that path.

### Add one model or node pack
Look in the catalog first (`find_setups` with `kind`: lora, checkpoint, video, ...), then
`search_models` (Civitai with type and base-model filters; Hugging Face repos; `hf_repo` lists a
repo's files) → `add_model(url, category?, filename?, bundle_id?)` → `install_progress`. Node packs:
`search_node_packs` → `install_node_packs` → `restart_comfyui`.

### What's going on, what it costs, ending a session
`status` (GPU use, ComfyUI queue and last error, downloads, money spent) or
`list_instances(with_health=true)`. To end: stopping keeps paying for storage, destroying deletes the
disk; for breaks over roughly 6-8 hours destroying (after backing up outputs) is usually cheaper, and
bundles with auto-install bring the models back on the next instance. Money facts:
[references/cli.md](references/cli.md#money-facts). Then `manage_instance(..., confirm=true)` once
they say which.

## Rules, and why

- **Money and destruction need the user's yes to that exact action.** Renting, start, stop and
  destroy cost money or delete data. Show the offer or instance first; never rent an offer they
  haven't seen, never swap hosts on your own. On 2026-10-16 a rental fell through to an unseen host
  charging $40/TB for downloads and the user had to stop it: that's why `rent_gpu` only takes
  offers shown in this session, re-checks the price, and needs `confirm`.
- **If the user says stop, stop**: cancel what's running, offer to destroy what was just rented,
  confirm with `list_instances`, then explain.
- **Don't pull ComfyUI from under a running job** (restart only when idle or with their OK).
- **Secrets stay out of the chat**: never print or repeat the Vast API key, MongoDB URI, Hugging
  Face / Civitai tokens or the portal token; keys go into the dashboard's Settings by the user.
- **Content**: adult content is fine for this user and the catalog covers it. Decline real people's
  likeness (celebrity or private-person LoRAs, face swaps of real people), anything sexual involving
  minors or child-like characters, and Krea 2 "filter bypass" LoRAs (its licence asks to keep the
  filter), with a one-line reason.
- **Downloads are real**: plan before tens of GB; when testing or developing, use small files.
- **Commits** in the repo only when asked, as `kanokpan-m` (see the user's CLAUDE.md).

## Presenting results

Keep it short; the user watches the same state in their dashboard. For setups: title, what it
does, VRAM, download GB, Civitai key needed, NSFW. For offers: the table above. After an install:
where to open it, the steps to use it, and the settings that matter. Give sizes in GB and costs
in $/h; mention the ETA when something will take minutes.

## Working on the repo itself

Architecture, ports, logs, env vars and API routes: [references/ecosystem.md](references/ecosystem.md).
Updating the catalog (new models, starters, publishing to MongoDB):
[references/catalog.md](references/catalog.md). Database layout: `docs/database.md` in the repo.
Tests: `python -m unittest tests/test_cli.py tests/test_fixer.py tests/test_store.py tests/test_mcp.py tests/test_starters.py tests/test_hub.py tests/test_create.py`,
and `tests/api_test.py` against a local dashboard (README "Development").
