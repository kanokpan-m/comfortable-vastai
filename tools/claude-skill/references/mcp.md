# The `comfortable` MCP server

`tools/comfortable_mcp.py` in the repo: a stdio MCP server (Python SDK `mcp` 2.3, `MCPServer`) that
reuses `tools/comfortable.py` for everything Vast-related and talks to the Comfortable dashboard for
everything on the instance. 26 tools, all returning structured JSON.

## Contents
- Setup and removal
- How it connects
- Tools by job (catalog, install, workflows, models, instance state, Vast)
- Gotchas and troubleshooting

## Setup and removal

Registered for Claude Code at user scope:

```bash
claude mcp add comfortable --scope user -- uv run --script D:\Projects\Apps\comfortable-vastai\tools\comfortable_mcp.py
claude mcp remove comfortable --scope user     # to remove it
claude mcp list                                # to check it connects
```

`uv` reads the script's inline dependencies (`mcp`, `requests`) and caches them. Without uv:
`pip install "mcp>=2.3,<3" requests`, then register `python <repo>\tools\comfortable_mcp.py`.
It also needs what the CLI needs: the `vastai` CLI with the API key set (`vastai set api-key ...`) and
the user's SSH key added at vast.ai/account.

Environment (optional, set with `claude mcp add -e KEY=VALUE ...`):

| Variable | Effect |
|---|---|
| `COMFORTABLE_DASHBOARD_URL` | Talk to this dashboard instead of a Vast instance: `http://localhost:17890` (a `comfortable tunnel`), a local dev dashboard, or ComfyUI's proxy `http://localhost:8188/comfortable`. |
| `COMFORTABLE_COMFY_URL` | ComfyUI's address for `open_workflow` links when it can't be worked out from the above. |
| `COMFORTABLE_HOME`, `COMFORTABLE_TEMPLATE_ID`, `MONGO_URI` | Same as the CLI (bad-host memory folder, template, where benchmarks come from). |

## How it connects

The first tool that needs a dashboard picks one: `COMFORTABLE_DASHBOARD_URL`, else the user's only
running instance, through an SSH tunnel the server opens and keeps (local ports from 17990: one for
the dashboard, the next for ComfyUI). With several running instances call `connect(instance_id)`.
If port forwarding fails it falls back to plain SSH per call (slower, no ComfyUI link). A dropped
tunnel is reopened on the next call. The tunnel dies with the server, so `open_url` links work on
this computer while the session runs; the Vast "Open" buttons work anywhere.

Without any connection, `find_setups`, `get_setup`, `plan_install` and `check_workflow` still answer
from the catalog in the checkout (sizes, VRAM, files) - use them before renting.

## Tools by job

### Catalog (work offline)
| Tool | Use | Notes |
|---|---|---|
| `find_setups(query, category, task, kind, nsfw, max_vram_gb, limit)` | Find starters and packs | No arguments → categories. Connected: adds `installed` and `missing_gb`. Categories: nsfw-video, nsfw-photo, hentai, nsfw-concepts, base-image, anime, edit, video, artist, stylize, realism, pose, upscale, detail, speed. |
| `get_setup(setup_id)` | Details of one entry | Starter: steps, inputs, packs, files. Pack: settings (steps, CFG, sampler, resolution, strength), trigger words, works_with, used_by_starters. |
| `plan_install(setup_ids, include_optional)` | Before installing | Connected: per-file state (installed / downloading / missing), disk and VRAM fit vs the GPU, node packs, warnings. Offline: sizes and VRAM only. |

### Install on the instance
| Tool | Use | Notes |
|---|---|---|
| `install_setups(setup_ids, include_optional, save_to_comfyui=true, save_as_bundle, auto_install_next_time)` | One call installs everything | Required packs included, files already there skipped (safe to repeat), node packs through ComfyUI-Manager. Returns `task_ids`, `restart_needed`, `errors`. |
| `install_progress(task_ids?, wait_seconds)` | Watch downloads | No ids: everything running or finished in the last hour, plus `boot_install` (what `rent_gpu` / `COMFORTABLE_INSTALL` set up) and the Manager queue. `wait_seconds` up to 900 with progress updates. |
| `restart_comfyui(force)` | Load new node packs | Refuses while a job is queued or running unless `force` (ask first). Waits until ComfyUI is back. |
| `open_workflow(workflow_id)` | Open a starter | Saves it to ComfyUI's Workflows sidebar (Comfortable/...), returns `open_url`, `ready`, what's still missing, steps and inputs. |

### Any workflow
| Tool | Use | Notes |
|---|---|---|
| `check_workflow(workflow_path | workflow_json | comfyui_path)` | What's missing | Connected: missing models with their source and size, missing node types with the pack providing them. Offline: VRAM and download size (to pick a GPU). `workflow_json` takes text or an object. |
| `fix_workflow(...same..., include_optional, install_node_packs=true)` | Fix it | Downloads what has a source (exact name and sub-folder), moves misplaced files, installs node packs. `not_fixed` lists the rest. Gated files are skipped (need licence + HF token). |
| `list_comfyui_workflows()` | Pick a saved workflow | Paths for `comfyui_path`. |

### Models, node packs, bundles
| Tool | Use | Notes |
|---|---|---|
| `search_models(query, source=civitai|hf, model_type, base_model, sort, hf_repo)` | Find anything outside the catalog | Uses the instance's Civitai key; NSFW results follow the dashboard's "show mature" setting. `hf_repo` lists a repo's model files with URLs. |
| `add_model(url, category?, filename?, install=true, bundle_id?)` | Save + download one model | Civitai model/version URL or HF file URL; `filename` may include a sub-folder. |
| `search_node_packs(query)` / `install_node_packs(ids)` | Custom nodes | Registry ids or GitHub URLs; restart afterwards. The built-in Manager (`--enable-manager`) installs registry packs only. |
| `list_bundles()` / `install_bundle(bundle_id, auto_install?)` | The user's groups of models | Saved catalog packs are `cat-<pack>`, saved starters `wf-<workflow>`. |
| `list_installed_models(category?, name_contains?)` | What's on disk | By ComfyUI folder, sub-folders included. |

### Instance state
| Tool | Use | Notes |
|---|---|---|
| `connect(instance_id? | dashboard_url?)` | Choose the target | Returns the same overview as `status`. |
| `status()` | Look first | GPU, VRAM use, disk, ComfyUI (running, queue, last error), downloads, boot install, keys set (true/false only), money spent. |
| `call_dashboard_api(path, method, body)` | Anything else | e.g. `GET benchmark`, `POST downloads/<id>/retry`, `GET health/host`, `PUT settings {"auto_stop_minutes": 30}`. |

### Vast
| Tool | Use | Notes |
|---|---|---|
| `list_instances(with_health)` | Your instances | `with_health` asks each running dashboard (slower). |
| `find_gpu(for_setups, min_vram_gb, gpu, max_price, rank, disk_gb, download_gb, hours, keep_models, allow_slow, limit)` | Rank offers | Read-only. Real cost per hour, images/hour from the user's benchmarks (else estimated), hosts that are slow for their GPU, too pricey on bandwidth (> $10/TB down, > $20/TB up) or failed a host check in the last 30 days are hidden (`hidden` counts them). Remembers the offers for `rent_gpu` for 30 minutes. |
| `rent_gpu(offer_id, confirm, install?, bundles?, label, env?)` | Rent | Only offers shown by `find_gpu` in this session; re-checked (gone or > 5% pricier → nothing rented); one rental per offer shown. `install` defaults to the `for_setups` of the search. Returns immediately. |
| `wait_for_instance(instance_id, timeout_seconds=300, benchmark=true)` | After renting or starting | Phases: image pull, provisioning, dashboard, host check. `ready` (connected), `waiting` (call again) or `failed` (machine remembered as bad). Benchmarks GPU models the user hasn't measured (~2 min, < $0.02). |
| `manage_instance(instance_id, action=stop|start|destroy, confirm)` | Billing changes | Without `confirm` it returns what to ask the user. |
| `instance_logs(instance_id?, lines)` | Debug boot | Provisioning log + dashboard log. |

## Gotchas and troubleshooting

- `confirm=true` is the user's yes, not yours: pass it only after they approved that action in chat.
- A tool error that says "Nothing rented" / "Nothing done" is the safety check working; relay what it
  asks.
- "vastai CLI is not installed" → `pip install vastai` and `vastai set api-key ...` (the user does
  the key). "SSH ... failed / Permission denied" → their SSH public key isn't on vast.ai/account.
- "Several instances are running" → `connect(instance_id)`.
- Dashboard not answering on a new instance → still provisioning: `wait_for_instance`, `instance_logs`.
- Downloads failing with 401/403 on Civitai → Civitai key missing or the file needs one (most
  mature files); `install_progress` shows the error.
- Node packs "not in the Comfy Registry" → the built-in Manager can't install it; install by hand
  (git clone into `custom_nodes` over SSH) only if the user wants.
- The server never writes to stdout except the protocol; its own diagnostics go to stderr (the
  client's MCP log).
