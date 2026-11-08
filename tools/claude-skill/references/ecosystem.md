# How Comfortable fits together

Repo: `kanokpan-m/comfortable-vastai` (`D:\Projects\Apps\comfortable-vastai`). README "Layout" has
the file-by-file table; this is the map for debugging and for changing things.

## Contents
- Boot sequence
- On the instance: services, ports, logs, files
- The dashboard
- ComfyUI side: extension and ComfyUI-Manager
- Data: MongoDB, SQLite, catalog
- Environment variables
- API routes worth knowing
- Troubleshooting

## Boot sequence

1. Vast starts the `vastai/comfy` image with the "Comfortable" template (id 733467). The template's
   `PROVISIONING_SCRIPT` points at `provis.sh` on `main` (the CLI and MCP server override it per rental
   if the template points elsewhere).
2. `provis.sh` downloads the repo at `COMFORTABLE_REF` to `/opt/comfortable` and runs `lib/main.sh`
   (log: `/var/log/provisioning_comfortable.log`): packages and model folders (`lib/setup.sh`), the
   ComfyUI extension (`lib/extension.sh`), the dashboard service (`lib/service.sh`, started before the
   speed tuning so downloads run in parallel), then `lib/boost.sh` (attention backend benchmark,
   flags in `/workspace/.env`). `/.provisioning_complete` or `/.provisioning_failed` marks the end.
3. The dashboard starts: syncs the database, queues auto-install bundles (`COMFORTABLE_BUNDLES` +
   bundles marked auto-install) and `COMFORTABLE_INSTALL` catalog ids. About 20 s later it runs the
   host health check (VRAM, power limit, PCIe, copy speed, disk, network) and stores the verdict in
   the `hosts` collection; `rent` / `find_gpu` skip machines judged poor for 30 days.
4. Once ComfyUI-Manager answers, `COMFORTABLE_INSTALL` installs node packs, restarts ComfyUI if it's
   idle, and saves the starters into ComfyUI (`GET /api/catalog/progress` → `boot`).

## On the instance: services, ports, logs, files

| What | Where |
|---|---|
| Dashboard | supervisord program `comfortable`; listens on 127.0.0.1:**17890**; Vast Instance Portal exposes it on **7890** (token auth). Log `/var/log/comfortable.log`. |
| ComfyUI | supervisord program `comfyui` (from the image); listens on **18188**; the portal exposes **8188**. `supervisorctl restart comfyui`. |
| Phone hub | `tools/comfortable_hub.py` on the user's PC, port **17880**, PIN sign-in: GPU sessions (rent with the same rules as the MCP server), the connected instance's dashboard passed through an SSH tunnel, outputs copied to `~/Comfortable/outputs`. The Create screen (`/api/create/...` on the dashboard) runs starters from `catalog/workflows/*.api.json`. |
| SSH tunnel (CLI) | `comfortable.py tunnel`: localhost:17890 → dashboard, :17891 → ComfyUI. The MCP server opens its own from :17990. |
| Models | `/workspace/ComfyUI/models/<folder>/...` (or on `COMFORTABLE_MODEL_VOLUME`, e.g. `/mnt/models`). `unet`≡`diffusion_models`, `clip`≡`text_encoders`. |
| Dashboard data | `/workspace/.comfortable/` (SQLite `comfortable.db`, `hf_index.json`, `tune.json`, staging). |
| Installed code | `/opt/comfortable` (`VERSION` = commit); updated in place from Settings (`lib/update.sh`). |

## The dashboard

aiohttp backend `dashboard/server.py` + `dashboard/comfortable/*`, Vue 3 UI built into
`dashboard/web` (committed). Screens: Library, Suggested by AI, Workflows, Discover (Civitai / HF
search), Fixer, Downloads, Gallery, Monitor, Settings. Key modules: `store` (SQLite + MongoDB sync),
`downloads` (aria2c, resume, sha256), `fixer` (finds missing models: library, workflow links,
ComfyUI-Manager model list, HF index of Comfy-Org / Kijai / city96 / QuantStack / lllyasviel,
Civitai), `manager` (ComfyUI-Manager, both flavors), `catalog` (packs, starters, plan, install,
boot install), `health`, `bench`, `autostop`, `backup` (outputs to a private HF dataset), `updater`.
Settings hold the Civitai key, HF token, show-mature flag, download concurrency, auto-stop minutes,
backup repo, Discord webhook.

## ComfyUI side

- **Extension** `comfyui_ext/` (installed as `custom_nodes/ComfyUI-Comfortable`): proxies
  `/comfortable/*` to the dashboard, adds the **Comfortable** sidebar tab (the fixer, embedded at
  `/comfortable/?embed=1#/fix`), checks each loaded workflow for missing models/nodes and offers a
  fix, and opens starters from `?comfortable_open=<workflow id>`.
- **ComfyUI-Manager**: the built-in one (`--enable-manager`, comfyui-manager 4.x, `/v2/...` routes,
  installs Comfy Registry packs through a queue) or the legacy custom node (`/manager/...`,
  `/customnode/...`). `dashboard/comfortable/manager.py` hides the difference. New node packs load
  only after a ComfyUI restart.

## Data

- **MongoDB** (`MONGO_URI`, database `comfortable`, schema v3; `docs/database.md`): `settings`,
  `library`, `bundles`, `stars`, `benchmarks`, `hosts`, `catalog_categories`, `catalog_packs`,
  `catalog_workflows`, `meta`. Every document has `id`, `v`, `mtime`; deletes are tombstones; each
  instance keeps a SQLite copy and syncs incrementally every 15 s. Without `MONGO_URI` SQLite is all
  there is. Bundle ids: user bundles random, saved packs `cat-<pack id>`, saved starters
  `wf-<workflow id>`.
- **Catalog**: shipped in `catalog/` (`catalog.json`, `workflows/*.json`, `starters.json`) and
  publishable to the database; the dashboard uses whichever has the newer `version`. See
  [catalog.md](catalog.md).

## Environment variables

Template / instance (README has the full table): `COMFORTABLE_REF`, `COMFORTABLE_REPO`,
`COMFORTABLE_BUNDLES` (bundle ids or names to install at boot), `COMFORTABLE_INSTALL` (catalog pack /
starter ids to set up at boot), `COMFORTABLE_MODEL_VOLUME`, `COMFORTABLE_COMFY_EXTENSION`,
`COMFORTABLE_HF_AUTHORS`, `SAGE_ATTENTION`, `COMFORTABLE_TUNE`, `COMFORTABLE_ATTENTION`, `COMFY_FAST`,
`MONGO_URI`, `COMFORTABLE_MONGO_DB`, `DISCORD_WEBHOOK`.
Local development: `COMFORTABLE_WORKSPACE`, `COMFORTABLE_PORT`, `COMFYUI_API_BASE`,
`COMFORTABLE_CATALOG_DIR`.

## API routes worth knowing

All JSON under `/api/`:

| Route | What |
|---|---|
| `GET health`, `GET bootstrap`, `GET system` | Liveness; version + masked settings + store status; GPU / disk / ComfyUI state / Vast spend. |
| `GET catalog` | Catalog with install state per pack and starter. |
| `POST catalog/plan {ids}` | Files, sizes, on disk or downloading, node packs, disk / VRAM fit, warnings. |
| `POST catalog/install {ids, to_comfy, save_bundle, auto_install, nodes}` | Everything in one call. |
| `GET catalog/progress?ids=` | Downloads, Manager queue, boot install. |
| `GET catalog/nodes?q=`, `POST catalog/nodes/install {ids}` | Node packs. |
| `GET catalog/workflows/<id>[/status]`, `POST catalog/workflows/<id>/comfy` | Starter graph, readiness, save into ComfyUI. |
| `POST fix/plan {workflow}`, `POST fix/apply {models, packs}` | The fixer. |
| `GET/POST library`, `POST library/<id>/install`, `GET/POST/PATCH/DELETE bundles[/<id>]`, `POST bundles/<id>/install` | Library and bundles. |
| `GET/POST downloads`, `POST downloads/<id>/retry|cancel` | Download queue. |
| `GET search/civitai?q=&types=&base=`, `GET search/hf?q=`, `GET hf/files?repo=`, `GET resolve?url=` | Model search. |
| `POST comfy/restart|free|interrupt` | ComfyUI control. |
| `GET health/host`, `POST health/host/run`, `GET/POST benchmark[/run]`, `GET autostop`, `PUT settings` | Host check, benchmark, auto-stop, settings. |

## Troubleshooting

| Symptom | Look at |
|---|---|
| Instance "running" but no dashboard | Still provisioning: `instance_logs` (provisioning log). `/.provisioning_failed` → the log's last lines. |
| Downloads fail 401/403 | Civitai key missing in Settings (most mature files), or the HF file is gated (accept licence + HF token). |
| Node pack "not in the Comfy Registry" | Built-in Manager only installs registry packs. |
| Workflow still red after installing | ComfyUI not restarted after node packs, or a file is in the wrong sub-folder (`check_workflow` shows `wrong_folder` and `fix_workflow` moves it). |
| Slow generation on a new host | `GET health/host`: power limit, PCIe width, VRAM. Poor → offer to replace the host. |
| Dashboard shows the old catalog | The database copy's version is older than the shipped one, or vice versa: compare `GET catalog` `version` / `source`. |
