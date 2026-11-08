<img src="docs/logo.png" alt="Comfortable" width="160" align="right" />

# Comfortable for Vast.ai

Provisioning for the `vastai/comfy` image: installs the Comfortable model manager
dashboard (port 17890, exposed through the Instance Portal on 7890), a Comfortable tab inside
ComfyUI, and an auto-tuned ComfyUI speed boost.

Point the template's `PROVISIONING_SCRIPT` at:

```
https://raw.githubusercontent.com/kanokpan-m/comfortable-vastai/refs/heads/main/provis.sh
```

## What you get

- **Fixer, inside ComfyUI.** When a workflow loads, missing models and custom nodes are found and
  a toast offers to fix them. The Comfortable sidebar tab lists each one with where it will come from
  (your library, the workflow's own links, ComfyUI-Manager's model list, the Hugging Face repos of
  Comfy-Org / Kijai / city96 / QuantStack / lllyasviel, or Civitai), the download size against free
  disk, and installs node packs through ComfyUI-Manager. One click fixes everything; the model lists
  refresh without reloading the page.
  Civitai is searched with the words in the file name (`RealisticSnapshotKrea2V2` → "Realistic
  Snapshot"), which finds 90% of real Civitai files exactly. Files only match when their folder fits
  (a `vae/` file never fills a ControlNet slot), and generic names such as
  `diffusion_pytorch_model.safetensors`, or names several models share, are never downloaded on a
  guess: you pick from suggestions ranked by your checkpoint's base model, and the pick is
  remembered in your library. A downloaded file that turns out to be a VAE is refused anywhere but
  the VAE folders.
- **Library and bundles.** Save models (Civitai, Hugging Face, any URL) into bundles; turn a
  workflow's models into a bundle; mark bundles to install automatically on every new instance.
  Library entries are re-checked in the background and flagged when their source disappears.
- **Suggested by AI.** A researched catalog of packs, each one every file a setup needs (model,
  text encoder, VAE, speed LoRAs, node packs), in categories: NSFW video, NSFW photo, hentai,
  poses & concepts, base models, anime, image edit, video, music & audio, 3D, "this artist"
  styles, stylize, realism, pose & ControlNet, upscale, face & detail, speed, utilities. Packs
  that fit the base models in your library are ranked first ("For you"). One click installs a
  pack (and the packs it needs);
  another saves it as a bundle. Mature suggestions follow "Show mature content" in Settings.
- **Workflows.** Starter workflows (Krea 2, Qwen-Image edit, Z-Image ControlNet, Illustrious,
  MiniMax H3 and DaSiWa video from an image or text, first & last frame, LTX-2.3 with lip sync,
  Wan Animate character swap, anime inpainting and line art, artist and style looks, new camera
  angles, layout, background removal, image to prompt, image to 3D, text to music, SeedVR2
  upscaling, frame interpolation, ...): installs every model and node pack, then opens the
  workflow in ComfyUI with the right model in every node.
- **Create.** Run any starter from a plain form made for phones: prompt, pictures / audio / video
  from your camera roll, size, seed, the template's own switches, LoRAs added on the spot, model
  swaps and every other setting; progress and results on the same screen.
- **Host health.** About 20 s after boot the dashboard measures usable VRAM, power limit, PCIe
  link, host→GPU copy speed, disk read and download speed, and warns about hosts that would give
  you a fraction of the GPU you paid for.
- **GPU value.** A standard SD 1.5 benchmark, saved with the price, gives images per dollar for
  every GPU you rent.
- **Auto-stop** after N idle minutes (warns 5 minutes ahead, inside ComfyUI too), **output backup**
  to a private Hugging Face dataset, **update in place** from Settings, browser notifications,
  Ctrl+K command palette.

## From your phone: the hub

`tools/comfortable_hub.py` runs on your PC (later a small always-on server) and is the phone's way
in, even when no GPU is rented:

```bash
uv run --script tools/comfortable_hub.py --set-pin   # choose the PIN (4-12 digits)
uv run --script tools/comfortable_hub.py             # prints the address to open on the phone
```

- **Start:** what you want to make → which starter workflows → the best GPUs for them right now
  (real cost per hour, speed from your benchmarks, about when it's ready) → one tap rents the offer
  you saw at that price → live setup (boot, host check, model downloads) → Create. Your instances
  with their cost so far; connect, stop, start or destroy, each after a confirmation.
- **Everything else** is the connected instance's dashboard, passed through an SSH tunnel: no
  portal address or token on the phone.
- **Saved:** every new image, video and song is copied to `~/Comfortable/outputs/<instance>/`
  on the PC within about 20 s (`COMFORTABLE_HUB_BACKUP_DIR` to change it), and stays browsable
  from the phone after the instance is gone.

Same Wi-Fi works as is (Windows asks once to allow it: private networks only). From anywhere,
install [Tailscale](https://tailscale.com) on the PC and the phone and open the PC's Tailscale
address. Five wrong PINs lock sign-in for 5 minutes, doubling each time; `--set-pin` signs every
phone out. Renting goes through the MCP server's code and rules: only offers shown in the last 30
minutes, re-checked before renting.

## Template environment variables

| Variable | Default | Effect |
|---|---|---|
| `COMFORTABLE_REF` | `main` | Branch, tag or commit to install (and to update to). Use a branch to test changes. |
| `COMFORTABLE_REPO` | `kanokpan-m/comfortable-vastai` | Repository to install from. |
| `COMFORTABLE_BUNDLES` | | Bundle names or ids to download on boot, comma separated (in addition to bundles marked auto-install). |
| `COMFORTABLE_INSTALL` | | Catalog pack and starter workflow ids to set up on boot, comma separated: files, node packs (then a ComfyUI restart if it's idle), starters saved into ComfyUI. Set by `comfortable rent --install` and the MCP server. |
| `COMFORTABLE_MODEL_VOLUME` | | Path of a mounted Vast volume (e.g. `/mnt/models`). Model folders live there, so they survive the instance. |
| `COMFORTABLE_COMFY_EXTENSION` | `1` | `0`: don't add the Comfortable tab and workflow checks to ComfyUI. |
| `COMFORTABLE_HF_AUTHORS` | `Comfy-Org,Kijai,city96,QuantStack,lllyasviel` | Hugging Face accounts the fixer indexes to find missing models by filename. |
| `SAGE_ATTENTION` | `0` | `1`: SageAttention 1. `2`: SageAttention 2 from a prebuilt wheel (seconds), else a source build (3-5 min), else falls back to 1. |
| `COMFORTABLE_TUNE` | `1` | `0`: skip auto-tuning and use the template's `COMFYUI_ARGS` unchanged. |
| `COMFORTABLE_ATTENTION` | `auto` | Force `sage`, `ck`, `xformers` or `pytorch` instead of the benchmark winner. |
| `COMFY_FAST` | `0` | `1`: the `--fast` features this GPU supports (fp16 accumulation, autotune, fp8 matmul on RTX 40+). `all`: every `--fast` feature. |
| `MONGO_URI` | | MongoDB for library/bundles/settings/benchmarks and the suggestions catalog, shared between instances; SQLite is used if unset or unreachable. |
| `COMFORTABLE_MONGO_DB` | `comfortable` | Database name in that MongoDB (layout: [docs/database.md](docs/database.md)). |
| `DISCORD_WEBHOOK` | | Provisioning, auto-stop and host-health notifications. |

An attention backend is only chosen after it runs on the GPU and matches PyTorch's
output. The chosen flags are written to `/workspace/.env`, which ComfyUI's launcher
reads on every start.

## Renting from your terminal (or from Claude)

`tools/comfortable.py` wraps the `vastai` CLI (`pip install vastai`, then `vastai set api-key ...`) and
talks to the dashboard over SSH, so no portal token is needed:

```bash
python tools/comfortable.py offers --for my_workflow.json                    # best value for this workflow
python tools/comfortable.py offers --rank speed --max-price 1.0                # fastest under $1/h
python tools/comfortable.py rent --for my_workflow.json --auto-swap --bundles starter
python tools/comfortable.py status            # GPU, ComfyUI, disk, host health
python tools/comfortable.py tunnel            # dashboard on localhost:17890, ComfyUI on localhost:17891
python tools/comfortable.py fix my_workflow.json
python tools/comfortable.py destroy 12345678
```

`offers` and `rent` price hosts at what they really cost (GPU + your disk size + the host's
download fee for your models) and rank them by images per dollar (`--rank speed` for the fastest
within `--max-price`). Speed comes from your own benchmarks when you've run one on that GPU
model, else from a built-in table. Hosts scoring well below others with the same GPU
(power-limited, throttled) are hidden, and so are machines that failed the host check in the last
30 days, whether you rented them with `comfortable` or from the Vast website. `--for workflow.json` sets
the VRAM and download size from the workflow (`comfortable needs workflow.json` shows the breakdown), and
`--auto-swap` replaces a host that fails the check automatically.

`--keep-models` creates a Vast local volume (`comfortable-models`) on the first rent and links it
afterwards; local volumes are tied to one machine.

`comfortable catalog [words]` searches the "Suggested by AI" catalog (`--ids a,b` shows what they
install), and `offers` / `rent --install a,b` size the GPU for those packs and starter workflows and
set them up at boot (`COMFORTABLE_INSTALL`): files download while ComfyUI is still starting, node
packs install once it's up, and the starters appear in ComfyUI's Workflows sidebar.

## For AI assistants: MCP server and Claude skill

`tools/comfortable_mcp.py` is an MCP server with 26 tools: find, plan and install catalog setups in
one call, watch downloads, open starters in ComfyUI, check and fix any workflow, search models and
node packs, manage bundles, and find, rent (only offers it showed you, with your confirmation) and
manage GPUs. Install it in Claude Code with
`claude mcp add comfortable --scope user -- uv run --script /path/to/tools/comfortable_mcp.py`;
details in [docs/mcp.md](docs/mcp.md). `tools/claude-skill/` is the matching Claude Code skill (copy
the folder to `~/.claude/skills/comfortable/`).

## Layout

| Path | What it does |
|---|---|
| `provis.sh` | Entry point. Downloads this repo at `COMFORTABLE_REF` to `/opt/comfortable` and runs `lib/main.sh`, retrying up to 4 times. |
| `lib/main.sh` | Runs the steps below in order, logging to `/var/log/provisioning_comfortable.log`. |
| `lib/common.sh` | Shared paths, `log`, `retry`, `send_discord`. |
| `lib/version.sh` | Records the installed commit in `/opt/comfortable/VERSION`. |
| `lib/setup.sh` | apt/pip packages, model folders (on `COMFORTABLE_MODEL_VOLUME` when set), dashboard env file. |
| `lib/extension.sh` | Links `comfyui_ext` into ComfyUI's `custom_nodes` as `ComfyUI-Comfortable`. |
| `lib/service.sh` | Registers the dashboard with supervisord and waits for it to be healthy. Runs before the boost so bundles download in parallel. |
| `lib/boost.sh` | Installs SageAttention if asked, runs `lib/tune.py`, writes the chosen flags to `/workspace/.env`. |
| `lib/sage.sh` | SageAttention install helpers: prebuilt wheel from this repo's releases, else source build. |
| `lib/tune.py` | Benchmarks every attention backend on the GPU, checks accuracy, picks the fastest and the `--fast` features the GPU supports. Cached in `/workspace/.comfortable/tune.json`. |
| `lib/update.sh` | Update in place: swaps `/opt/comfortable` for the latest `COMFORTABLE_REF` and restarts the dashboard. |
| `comfyui_ext/` | The ComfyUI extension: proxies `/comfortable/*` to the dashboard and adds the Comfortable tab and workflow-load check. |
| `dashboard/server.py` | Dashboard entry point (aiohttp, runs in ComfyUI's venv; binds 127.0.0.1:17890 behind the portal). |
| `dashboard/comfortable/` | Backend: `store` (SQLite + incremental MongoDB sync, schema v3), `schema` (document shapes), `sources` (Civitai / Hugging Face), `downloads` (aria2 queue with resume + SHA-256 checks), `models`, `workflows`, `fixer` (model and node-pack resolution), `manager` (ComfyUI-Manager, legacy or built-in `/v2` API), `catalog` (suggestions and starter workflows), `create` (the Create screen: starter forms and runs), `library`, `health`, `bench`, `autostop`, `backup`, `updater`, `system`, `gallery`, `api` / `api_more` / `api_catalog` (routes), `events` (SSE). |
| `catalog/` | The "Suggested by AI" catalog (`catalog.json`), starter workflow graphs (`workflows/`) and the recipes that build them from ComfyUI's official templates (`starters.json`). See [catalog/README.md](catalog/README.md). |
| `docs/database.md` | The MongoDB / SQLite layout and how instances sync. |
| `dashboard/ui/` | Web UI source: Vue 3 + Tailwind CSS 4 + reka-ui + Lucide, the same stack and design tokens as ComfyUI's frontend. |
| `dashboard/web/` | Built web UI (committed, so instances need no Node), served at `/`. |
| `supervisor/` | supervisord program definition and launcher. |
| `tools/` | `comfortable.py` (rent/manage CLI), `comfortable_mcp.py` (MCP server for AI assistants, [docs/mcp.md](docs/mcp.md)), `catalog.py` (check, verify and publish the catalog to MongoDB), `starters.py` (build starter workflows from official templates), `starter_api.py` (save each starter in the form ComfyUI runs, for the Create screen), `comfortable_hub.py` (the phone hub), `claude-skill/` (the Claude Code skill), `build-sage-wheel.sh` (the SageAttention wheel published as a release). |
| `tests/` | `api_test.py` (end-to-end API test, run by CI against a local server) and offline unit tests (`test_cli`, `test_fixer`, `test_store`, `test_mcp`, `test_starters`, `test_hub`, `test_create`). |

## Development

```bash
cd dashboard/ui && npm install
npm run dev     # hot-reload dev server; proxies /api to COMFORTABLE_API (default http://127.0.0.1:17891)
npm run build   # writes ../web — commit it
```

Run the backend locally with `COMFORTABLE_WORKSPACE=<folder> COMFORTABLE_PORT=17891 python dashboard/server.py`
(needs aiohttp, psutil, pillow, requests, huggingface_hub, pymongo, certifi, av), then
`BASE=http://127.0.0.1:17891 python tests/api_test.py <folder>`.
