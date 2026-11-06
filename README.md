<img src="docs/logo.png" alt="Comfortable" width="160" align="right" />

# Comfortable for Vast.ai

*Formerly Comfy-Xtra.*

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
  disk, and installs node packs through ComfyUI-Manager (after a pip dry run: a pack that would change
  torch, numpy & co. is held back with a warning). One click fixes everything; the model lists
  refresh without reloading the page.
  Civitai is searched with the words in the file name (`RealisticSnapshotKrea2V2` → "Realistic
  Snapshot"), which finds 90% of real Civitai files exactly. Files only match when their folder fits
  (a `vae/` file never fills a ControlNet slot), and generic names such as
  `diffusion_pytorch_model.safetensors`, or names several models share, are never downloaded on a
  guess: you pick from suggestions ranked by your checkpoint's base model, and the pick is
  remembered in your library. A downloaded file that turns out to be a VAE is refused anywhere but
  the VAE folders.
- **Saved workflows on every instance.** Workflows you save in ComfyUI are kept in the shared
  database and restored on new instances; one edited on two instances keeps both versions.
- **Library and bundles.** Save models (Civitai, Hugging Face, any URL) into bundles; turn a
  workflow's models into a bundle (its custom node packs are pinned to their git commits and
  installed at those versions elsewhere); mark bundles to install automatically on every new instance.
  Library entries are re-checked in the background and flagged when their source disappears.
- **Host health.** About 20 s after boot the dashboard measures usable VRAM, power limit, PCIe
  link, host→GPU copy speed, disk read and download speed, and warns about hosts that would give
  you a fraction of the GPU you paid for.
  While jobs run it keeps watching: a GPU that throttles (heat, power brake) for most of a
  10-minute stretch triggers a warning and marks the machine poor, so renting skips it next time.
- **Spending.** Every instance records what it costs (GPU + disk at Vast's price, estimated
  bandwidth, and GPU time per workflow) in the shared database: a Monitor card and `comfortable spend`.
- **GPU value.** Standard SD 1.5, SDXL and Flux benchmarks, saved with the price, give images per
  dollar for every GPU you rent (the dashboard downloads the SDXL / Flux test model on request).
  `offers --for workflow.json` ranks with the benchmark matching the workflow's model family.
- **Auto-stop or auto-destroy** after N idle minutes (editing in ComfyUI counts as activity; destroy
  backs up first and falls back to stop), plus an hours or dollars **budget cap** that applies even
  while busy (warns 5 minutes ahead, inside ComfyUI too), **output backup**
  to a private Hugging Face dataset, **update in place** from Settings, browser notifications,
  Ctrl+K command palette.

## Template environment variables

| Variable | Default | Effect |
|---|---|---|
| `COMFORTABLE_REF` | `main` | Branch, tag or commit to install (and to update to). Use a branch to test changes. |
| `COMFORTABLE_REPO` | `kanokpan-m/comfortable-vastai` | Repository to install from. |
| `COMFORTABLE_BUNDLES` | | Bundle names or ids to download on boot, comma separated (in addition to bundles marked auto-install). |
| `COMFORTABLE_MODEL_VOLUME` | | Path of a mounted Vast volume (e.g. `/mnt/models`). Model folders live there, so they survive the instance. |
| `COMFORTABLE_COMFY_EXTENSION` | `1` | `0`: don't add the Comfortable tab and workflow checks to ComfyUI. |
| `COMFORTABLE_HF_AUTHORS` | `Comfy-Org,Kijai,city96,QuantStack,lllyasviel` | Hugging Face accounts the fixer indexes to find missing models by filename. |
| `SAGE_ATTENTION` | `0` | `1`: SageAttention 1. `2`: SageAttention 2 from a prebuilt wheel (seconds), else a source build (3-5 min), else falls back to 1. |
| `COMFORTABLE_TUNE` | `1` | `0`: skip auto-tuning and use the template's `COMFYUI_ARGS` unchanged. |
| `COMFORTABLE_ATTENTION` | `auto` | Force `sage`, `ck`, `xformers` or `pytorch` instead of the benchmark winner. |
| `COMFY_FAST` | `0` | `1`: the `--fast` features this GPU supports (fp16 accumulation, autotune, fp8 matmul on RTX 40+). `all`: every `--fast` feature. |
| `MONGO_URI` | | MongoDB for library/bundles/settings/benchmarks shared between instances; SQLite is used if unset or unreachable. |
| `DISCORD_WEBHOOK` | | Provisioning, auto-stop and host-health notifications. |
| `COMFORTABLE_SECRET_KEY` | | Passphrase that encrypts your API keys in MongoDB (same value on every instance). Unset, keys are stored unencrypted on purpose so you can read them there. |

The `XTRA_*` names from before the rename (`XTRA_REF`, `XTRA_BUNDLES`, ...) still work; the
`COMFORTABLE_*` name wins when both are set. The shared MongoDB database keeps its old name,
`comfy_xtra`, so every instance still sees the same library.

An attention backend is only chosen after it runs on the GPU and matches PyTorch's
output. The chosen flags are written to `/workspace/.env`, which ComfyUI's launcher
reads on every start.

## Renting from your terminal (or from Claude)

`tools/comfortable.py` wraps the `vastai` CLI (`pip install vastai`, then `vastai set api-key ...`) and
talks to the dashboard over SSH, so no portal token is needed:

```bash
python tools/comfortable.py go my_workflow.json        # rent the best host for it, set it up, open it in ComfyUI
python tools/comfortable.py offers --for my_workflow.json                    # best value for this workflow
python tools/comfortable.py offers --rank speed --max-price 1.0                # fastest under $1/h
python tools/comfortable.py rent --for my_workflow.json --auto-swap --bundles starter
python tools/comfortable.py status            # GPU, ComfyUI, disk, host health
python tools/comfortable.py tunnel            # dashboard on localhost:17890, ComfyUI on localhost:17891
python tools/comfortable.py fix my_workflow.json
python tools/comfortable.py destroy 12345678
python tools/comfortable.py spend --days 30   # what renting cost: per day, per instance, per workflow
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
afterwards; local volumes are tied to one machine. `tools/claude-skill/` is the same tool packaged
as a Claude Code skill: copy that folder plus `tools/comfortable.py` to `~/.claude/skills/comfortable/`.

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
| `dashboard/comfortable/` | Backend: `store` (SQLite + background MongoDB sync), `sources` (Civitai / Hugging Face), `downloads` (aria2 queue with resume + SHA-256 checks), `models`, `workflows`, `fixer` (model and node-pack resolution), `library`, `health`, `bench`, `autostop`, `backup`, `updater`, `system`, `gallery`, `api` / `api_more` (routes), `events` (SSE). |
| `dashboard/ui/` | Web UI source: Vue 3 + Tailwind CSS 4 + reka-ui + Lucide, the same stack and design tokens as ComfyUI's frontend. |
| `dashboard/web/` | Built web UI (committed, so instances need no Node), served at `/`. |
| `supervisor/` | supervisord program definition and launcher. |
| `tools/` | `comfortable.py` (rent/manage CLI), `claude-skill/`, `build-sage-wheel.sh` (the SageAttention wheel published as a release). |
| `tests/api_test.py` | End-to-end API test, run by CI against a local server. |

## Development

```bash
cd dashboard/ui && npm install
npm run dev     # hot-reload dev server; proxies /api to COMFORTABLE_API (default http://127.0.0.1:17891)
npm run build   # writes ../web — commit it
```

Run the backend locally with `COMFORTABLE_WORKSPACE=<folder> COMFORTABLE_PORT=17891 python dashboard/server.py`
(needs aiohttp, psutil, pillow, requests, huggingface_hub, pymongo, certifi, av), then
`BASE=http://127.0.0.1:17891 python tests/api_test.py <folder>`.
