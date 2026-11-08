# MCP server for AI assistants

`tools/comfortable_mcp.py` lets an AI assistant (Claude Code, Claude Desktop, any MCP client) set up
ComfyUI on your Vast instances the way the dashboard would, correctly and fast:

- **finds setups** in the "Suggested by AI" catalog (starter workflows with every model selected,
  model packs) with VRAM, download size and Civitai-key needs; works offline before renting;
- **plans and installs** them in one call: exact files and sub-folders, checksums, required packs,
  node packs through ComfyUI-Manager, starters saved into ComfyUI, optionally saved as bundles;
- **watches** downloads, restarts ComfyUI for new node packs, **opens** starters in ComfyUI;
- **checks and fixes** any workflow (missing models with their source, missing node packs);
- **searches** Civitai, Hugging Face and ComfyUI-Manager, adds single models, manages bundles;
- **finds, rents and manages GPUs** with the same ranking as `tools/comfortable.py` (real cost per
  hour, your benchmarks, bad-host memory), and sets the chosen setups up at boot.

It reuses `tools/comfortable.py` and talks to the dashboard's API; nothing new runs on the instance.

## Install

Needs [uv](https://docs.astral.sh/uv/) (or Python 3.10+ with `pip install "mcp>=2.3,<3" requests`), the
`vastai` CLI with your API key (`pip install vastai`, `vastai set api-key ...`) and your SSH key added at
vast.ai/account.

Claude Code:

```bash
claude mcp add comfortable --scope user -- uv run --script /path/to/comfortable-vastai/tools/comfortable_mcp.py
claude mcp list                              # shows whether it connects
claude mcp remove comfortable --scope user   # uninstall
```

Other clients (`mcpServers` JSON):

```json
{"mcpServers": {"comfortable": {"command": "uv", "args": ["run", "--script", "/path/to/comfortable-vastai/tools/comfortable_mcp.py"]}}}
```

The Claude Code skill in `tools/claude-skill/` (copy it to `~/.claude/skills/comfortable/`) teaches the
assistant the workflows and rules that go with these tools.

## Which dashboard it talks to

1. `COMFORTABLE_DASHBOARD_URL` if set: `http://localhost:17890` (while `comfortable.py tunnel` runs), a
   local dashboard, or ComfyUI's proxy `http://localhost:8188/comfortable`. `COMFORTABLE_COMFY_URL`
   sets ComfyUI's address for "open this workflow" links when it can't be worked out.
2. Otherwise your only running instance (or the one picked with the `connect` tool): the server opens
   an SSH tunnel (local ports from 17990) and keeps it while it runs; if forwarding is refused it uses
   plain SSH per call.

Without either, catalog search, install planning and workflow checks answer offline from
`catalog/catalog.json`.

## Tools

| Job | Tools |
|---|---|
| Catalog | `find_setups`, `get_setup`, `plan_install` |
| Install | `install_setups`, `install_progress`, `restart_comfyui`, `open_workflow` |
| Any workflow | `check_workflow`, `fix_workflow`, `list_comfyui_workflows` |
| Models, nodes, bundles | `search_models`, `add_model`, `search_node_packs`, `install_node_packs`, `list_bundles`, `install_bundle`, `list_installed_models` |
| Instance | `connect`, `status`, `call_dashboard_api` |
| Vast | `list_instances`, `find_gpu`, `rent_gpu`, `wait_for_instance`, `manage_instance`, `instance_logs` |

Every tool returns structured JSON and carries MCP annotations (read-only, destructive, idempotent).

## Safety

- `rent_gpu` only rents an offer `find_gpu` showed in the same session, within 30 minutes, after
  re-checking it is still there and no more than 5% pricier, and only with `confirm=true`, which the
  assistant is told to pass only after you said yes. One shown offer, one rental; no automatic host
  swaps.
- `manage_instance` (stop / start / destroy) needs `confirm=true` too; without it, it returns the
  question to ask you.
- `restart_comfyui` refuses while a job is running unless forced.
- Keys and tokens never appear in tool output (settings come back as "set" / "not set").
- Nothing is printed to stdout but the protocol; diagnostics go to stderr.

## Setting up at boot

`rent_gpu(..., install=[ids])` (default: the `for_setups` of the search) and
`comfortable.py rent --install ID,ID` pass `COMFORTABLE_INSTALL` to the instance. The dashboard queues
those files as soon as it starts, installs their node packs once ComfyUI-Manager answers, restarts
ComfyUI if nobody is using it, and saves the starters into ComfyUI's Workflows sidebar.
`install_progress` (or `GET /api/catalog/progress` → `boot`) shows where it is.

## Development

```bash
python -m unittest tests/test_mcp.py      # offline: catalog, renting guards (Vast faked), tool schemas
```

`tests/test_mcp.py` runs the tools in-process through the MCP client; for a live run, start a local
dashboard (README "Development") and point `COMFORTABLE_DASHBOARD_URL` at it.
