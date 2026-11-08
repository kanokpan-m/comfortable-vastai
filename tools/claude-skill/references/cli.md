# The `comfortable` CLI

`tools/comfortable.py` in the repo. Run it with the Python that has the `vastai` package
(`pip install vastai`; the user sets the key with `vastai set api-key`). On Windows plain `python`
may be the Microsoft Store stub: use the full path of the Python that owns `vastai`. It reaches
instances over SSH, so the user's SSH key must be on vast.ai. Most commands take `--json`.

## Contents
- Commands
- Renting safely
- Money facts
- Working with the CLI (no MCP)

## Commands

```
comfortable.py status [ID] [--json]       # instances + dashboard, ComfyUI, GPU use, disk, host health
comfortable.py catalog [WORDS] [--category nsfw-video] [--task i2v] [--kind lora] [--nsfw only|no] [--max-vram 24] [--json]
comfortable.py catalog --ids ID,ID [--json]   # what these packs / starters install: files, GB, VRAM, Civitai key
comfortable.py offers [--install ID,ID] [--gpu RTX_5090,RTX_4090] [--max-price 0.8] [--min-vram 24]
                      [--rank value|speed] [--for WORKFLOW.json] [--disk 100] [--hours 4] [--json]
comfortable.py rent --offer ID [--install ID,ID] [--disk 100] [--bundles a,b] [--keep-models] [--set KEY=VALUE] --yes [--dry-run]
comfortable.py needs WORKFLOW.json        # VRAM and download size a workflow needs (no instance required)
comfortable.py hosts [--forget ID|all]    # machines skipped after failing the host check
comfortable.py tunnel [ID]                # dashboard http://localhost:17890, ComfyUI http://localhost:17891 (blocks: run in background)
comfortable.py fix WORKFLOW.json [ID]     # missing models / custom nodes and where each would come from
comfortable.py api PATH [ID] [-X POST -d JSON]   # any dashboard route, JSON out
comfortable.py logs [ID] [--lines 80]
comfortable.py stop|start|destroy ID
```

`--install` takes catalog ids (packs or starter workflows): `offers` sizes VRAM and download from
them, `rent` also sets them up at boot (`COMFORTABLE_INSTALL` on the instance: files download
before ComfyUI is even up, node packs install and ComfyUI restarts once it answers, starters are
saved into its Workflows sidebar). Unknown ids fail before anything is rented.

## Renting safely

Renting spends the user's money. Follow this every time, even when the user says "just rent one":

1. **Search with the user's real numbers.** Their disk size (`--disk`), what they'll run
   (`--install` ids or `--for` a workflow; ask if unclear), their budget (`--max-price`). Don't invent
   `--download-gb` or `--hours`: they decide how much the download fee weighs. If you must guess, say so.
2. **Show before you rent.** For the top 2-3 offers: offer id, GPU + VRAM, location, $/h (GPU + disk),
   **download price in $/TB**, network speed, host score, and which you'd pick and why. Wait for the
   user to pick one in chat.
3. **Rent exactly that offer:** `rent --offer <ID> --disk <GB> --yes`. If it's gone, `--offer` rents
   nothing: search again and ask again. Never fall through to an offer the user hasn't seen, and don't
   use `--auto-swap` unless they asked for it (it rents unseen hosts).
4. **Bandwidth is not a footnote.** Hosts set their own download price: most charge $0-5/TB, a few
   $40+/TB. Models are re-downloaded on every new instance (about 20 GB for a Krea or Qwen set, 40 GB+
   for video stacks), so it's a recurring cost. Hosts over $10/TB are hidden; raise
   `--max-download-per-tb` only if the user asks.
5. **Upload and power count too.** Upload ($/TB) is what viewing/downloading outputs and backups
   cost; hosts over $20/TB upload are hidden. POWER is a host's power cap vs. a full card (many RTX 5090s
   run 450-520 W of 575-600); speed estimates already include it. Mention both when recommending.
6. **If the user says stop, stop first:** kill the running `rent`, destroy (or stop, if it holds their
   data) what was just rented, confirm with `status`, then explain.

What went wrong once (2026-10-16): the user asked for "at least a 4090, 50 GB disk". The best offer
(RTX 4090, Bulgaria, $0.53/h) was taken a minute later, and `rent` without `--offer` silently took the
next one: an RTX 5090 in Estonia charging **$40/TB** to download. It ranked "best value" only because
the fee was spread over an assumed 4-hour session, and the $/TB was never shown. Cheaper, faster hosts
at $1-4/TB were available. Hence rules 2-4 and `--offer`.

## Money facts

Measured on Vast (2026-10-16):

- Stopped instances keep paying for storage (about $0.40-1.80/day for 80 GB), possibly at a higher
  rate than running. Recreating costs one model download (~$0.10 at $2-3/TB) plus a few minutes, and
  bundles with auto-install + the fixer restore models automatically. For breaks longer than ~6-8
  hours, destroying (after a backup) is cheaper than stopping; for short breaks, stopping is.
- Interruptible (bid) instances are 35-40% cheaper but can be paused when outbid: fine for batch
  jobs, not for interactive sessions.
- Setup time is set by the host's network: 40 GB took 333 s at 1 Gbps and 74 s at 6.6 Gbps (single
  files top out near 2.2 Gbps). Disk can't be resized: size it from the catalog / `needs` download
  size + room for outputs.
- Some hosts look fine idle and halve their speed under load (driver clock limits); the host check's
  30 s load test marks those "poor". Offer to replace a poor host.
- VRAM rules of thumb: 16 GB for SDXL / Illustrious / Z-Image / Krea 2 fp8, 24 GB for Qwen-Image, Wan
  2.2 14B and MiniMax H3 turbo setups, 32 GB+ for heavier video.

## Working with the CLI (no MCP)

- **Start by looking:** `status --json`, then `api system` (`comfy.queue_remaining`, `gpus[0].util`),
  `api downloads` and `api health/host` as needed.
- **Set up catalog entries on a running instance:** `api catalog/plan -X POST -d '{"ids": ["..."]}'`,
  then `api catalog/install -X POST -d '{"ids": ["..."], "to_comfy": true}'`, watch
  `api "catalog/progress"`, restart with `api comfy/restart -X POST` if node packs were installed.
- **After renting**, `rent` waits for the dashboard and the host check (about 2 minutes). A `poor` host
  or one that never starts (stuck loading over 8 minutes) is remembered and skipped; without
  `--auto-swap`, tell the user and offer to destroy it and pick another offer together. The first
  rental of a GPU model the user hasn't benchmarked runs the 2-minute benchmark (`--no-bench` skips).
- **Missing models or nodes:** `fix` shows what's missing, what's optional (switched-off nodes) and
  where each file would come from; apply by posting the `models` entries (each carries its `fix`) and
  pack ids from `fix --json` to `api fix/apply -X POST -d '{"models": [...], "packs": [...]}'`, or point
  the user to the Comfortable tab in ComfyUI.
- **Keep models between instances:** `rent --keep-models` creates (first time) or links a Vast local
  volume `comfortable-models` at `/mnt/models`. Local volumes are tied to one machine: later rentals
  must use it; if it has no free GPU, say so rather than renting elsewhere.
- **Auto-stop:** `api settings -X PUT -d '{"auto_stop_minutes": 30}'` stops the instance after 30 idle
  minutes.
