# Model research, November 2026

Research behind the "Suggested by AI" catalog ([catalog/](../catalog/README.md)), done on
2026-11-08 with the Civitai API (with an API key), the Hugging Face API, the official ComfyUI
templates (`comfyui-workflow-templates` 0.11.103, ComfyUI 0.44) and web sources. Every file
in the catalog was looked up live: size, sha256 and a working download link. Image quality
was not test-generated; VRAM figures are estimates from file sizes and creators' notes.

## What changed in 2026

- **Civitai split (April 2026).** civitai.com shows SFW only; mature content lives on
  civitai.red. One account and one database: the REST API on civitai.com still returns mature
  models with `nsfw=true`, but most mature files need an API key to download (112 of the 149
  NSFW image picks answer 401 without one).
- **New quantisation default.** Official repacks now ship `int8_convrot` (ComfyUI 0.27+); NVFP4
  files run fast only on RTX 50xx/B200, so the catalog avoids them except where an official
  template uses one.
- **Much moved into core ComfyUI:** SeedVR2 upscaling, frame interpolation (RIFE/FILM), SDPose
  pose extraction, Depth Anything 3, Qwen-Image 2.1, Krea 2, MiniMax H3, Wan Animate 2, Z-Image
  and Qwen Fun ControlNets. Most starters need no custom nodes.
- **ComfyUI-Manager inside ComfyUI** (`--enable-manager`, comfyui-manager 4.x) serves `/v2/...`
  only; Comfortable now speaks both that and the old custom-node Manager.

## Image: mainstream bases

| Base | Released | What it is | NSFW |
|---|---|---|---|
| **Krea 2 Turbo** (12B) | Jun 2026 | Strongest open photoreal model, 8 steps, Qwen3-VL 4B encoder | Base refuses explicit content; finetunes (LUSTIFY v10, RedCraft, FinePorn, Moody, PornMaster, SNOFS-merged) and LoRAs (SNOFS v1.6) do it |
| **Qwen-Image 2.1** (7B) | Sep-Oct 2026 | One model for generation and editing, up to 10 reference images; the most-used open edit template | Soft nudity only; NSFW LoRAs and finetunes (Noct Q); licence is now non-commercial |
| **Z-Image Turbo** (6B) | Nov 2025 | Fast photoreal on 12-16 GB, second most-used template | Nudity yes, sex needs finetunes (PornMaster, IntoRealism) or LoRAs (NSFW MASTER, Mystic XXX) |
| **MOSS-Image** (5B) | 16 Oct 2026 | Apache-2.0, photo and anime, strong text | Uncensored out of the box; turn its prompt enhancer off for adult prompts |
| **Anima** (2B) | 2026 | Anime base (Danbooru tags + language), 90 of the month's top-300 checkpoints | Yes |
| Illustrious / NoobAI (SDXL) | 2024-25 | Still the default anime NSFW family; WAI-illustrious v17 is the benchmark | Yes |
| FLUX.3 klein, FLUX.2 | Oct 2026 / Nov 2025 | BFL's open models | Safety-filtered; left out of the starters |

Legacy but kept for LoRA compatibility: Qwen-Image 2512 / Edit 2511 (Apache-2.0), FLUX.1 Krea
dev, Pony V6, SDXL photo checkpoints (LUSTIFY V9, PornMaster Pro, CyberRealistic Pony, Big Love).

## Video

- **MiniMax H3** (open weights 3 Aug 2026, 33B): text / image / first+last frame / reference to
  video *with stereo audio* in one pass; the most-used local video template. The base keeps its
  guardrails, so adult clips need an H3 NSFW LoRA (HMNSFW V3, Mystic XXX, ...) or a merge.
- **DaSiWa** (darksidewalker), the community favourite:
  - *MiniMax H3 Hybrid v4 Turbo*: one pruned file for T2VA / I2VA / FL2VA / REF2VA, 4-step
    turbo baked in (euler/simple, CFG 1, shift 10 video / 3 audio, 24 fps, 124-362 frames).
    Never add turbo LoRAs; one NSFW LoRA such as HMNSFW at 0.6-1.0.
  - *WAN 2.2 I2V SnatchKiss v11 Lightspeed*: NSFW-tuned high/low pair with the lightx2v 4-step
    distill baked in (2+2 steps, CFG 1, shift 5, 81 frames at 16 fps); concept LoRAs at 0.3-0.6.
    *TrueVision* is the undistilled, slower, higher-fidelity build. Also S2V LittleDemon and
    LTX 2.3 DragonLeap.
- **Wan 2.2** (14B high/low experts) remains the base of Civitai's biggest NSFW video LoRA
  catalog (General NSFW, DR34ML4Y, POV missionary, cowgirl, deepthroat, SmoothMix, ...). Kijai's
  extraction of lightx2v's 260412 4-step distill is the current speed LoRA. Wan 2.5-3.0 have no
  open weights. **Wan Animate 2** (core nodes) does character swap / motion transfer.
- Post-processing: SeedVR2 (3B for video, 7B for images) and RIFE 4.26 / FILM interpolation.

## Look: artists and styles

24 artist-style LoRAs for Illustrious/NoobAI (Takeda Hiromitsu, Cutesexyrobutts, 748cm, Zankuro,
Sakimichan, Yoneyama Mai, Urushihara Satoshi, Adam Hughes, ...), 20 artist tags Illustrious knows
natively (no download), and 25 style LoRAs (flat colour, screencap, semi-real, retro 90s, film
grain, phone/disposable camera, cinematic) for Illustrious, Krea 2, Z-Image and Qwen. Western
comic artists are not Danbooru tags, so they need LoRAs. Krea 2 style picks were checked to
work on Turbo.

## Tools

- Pose: SDPose skeletons (core) + NoobAI OpenPose / xinsir Union ProMax ControlNets for
  SDXL-family; Z-Image and Qwen 2.1 Fun ControlNet Union; H3 Fun ControlNet for video.
- Detail: Impact Pack FaceDetailer with face/hand/person detectors, plus NSFW body-part
  segmentation detectors.
- Upscale: 4x-UltraSharpV2 (photo), 2x-AnimeSharpV4 (anime), SeedVR2.
- Style transfer: Krea 2 style-reference LoRA (core), IP-Adapter Plus (SDXL, maintenance-only).

## Left out on purpose

- Real-person / celebrity likeness LoRAs, age sliders and anything child-coded.
- Krea 2 "filter bypass" LoRAs (the Krea 2 licence asks deployers to keep its content filter).
- ReActor face swap: it has an NSFW classifier with no off switch and returns flagged images
  unswapped.
- Buzz-paid (early access) versions: every pick is the newest free version.

## Second pass: more workflow types and looks (2026-11-08, catalog 2026.11.08.2)

The first pass covered generation, edit, pose, upscale and image/reference to video. The second
pass went through every open template in `comfyui-workflow-templates` 0.11.103 (264 of them, with
their usage counts) and added the kinds of workflow the catalog had no starter for. All are
built from official templates (`catalog/starters.json`), use core nodes only, and were queued in
a local ComfyUI 0.44 / frontend 1.58.5 with placeholder files: no validation errors.

| Starter | Type | Models (download) | Why this one |
|---|---|---|---|
| `h3-t2v`, `dasiwa-h3-t2v` | text to video + sound | MiniMax H3 (42 GB), or DaSiWa Hybrid + HMNSFW (41 GB); the same files as the i2v starters | 4,356 uses; the DaSiWa build does T2VA in 4 steps |
| `h3-flf2v` | first & last frame | H3 FL2VA + Pika H3 Flex adapter (44 GB) | Transitions and planned endings, with sound |
| `ltx23-i2v` | image to video + sound | LTX-2.3 22B fp8, distilled LoRA, x2 upscaler, Gemma 3 12B (43 GB) | 18,605 uses, the second most-used video template |
| `ltx23-lipsync` | image + audio to video | same LTX-2.3 files | Talking and singing heads (1,274 uses) |
| `anima-inpaint` | inpaint | Anima + LLLite inpainting (5.8 GB) | First inpaint starter; Anima is uncensored |
| `anima-lineart` | sketch / line art to art | Anima + LLLite any-control (5.8 GB) | Colour and finish a drawing |
| `moss-edit` | instruction edit | MOSS-Image + edit LoRA (13 GB) | A 12 GB-card editor next to Qwen 2.1 |
| `character-angles` | new camera angles | Qwen-Image-Edit 2511 int8 + Lightning + fal Multiple Angles (31 GB) | 928 uses; also gives SNOFS (Edit 2511) its base |
| `moss-layout` | layout boxes | MOSS-Image (13 GB) | Place every element (and printed text) with boxes |
| `remove-background` | cut-out | BiRefNet (0.4 GB) | Transparent PNGs; also used by image to 3D |
| `prompt-from-image` | image to prompt | Qwen3-VL 4B (5.5 GB, the same file as Krea 2's encoder) | Prompts for image to video or remakes |
| `image-to-3d` | 3D | Pixal3D + TRELLIS.2 int8, DINOv3, MoGe 2, BiRefNet (15 GB) | 831 uses, PBR-textured GLB |
| `text-to-music` | music | MiniMax Music 3 (14 GB) | 645 uses; songs with vocals, feeds the lip-sync starter |

Not added: LTX-2.5 (gated on Hugging Face: licence + token), VOID video object removal (34 GB),
Bernini-R video relight (39 GB), Qwen-Image-Layered (50 GB), SCAIL-2 character replacement
(swaps a person into real footage; Wan Animate 2 already covers motion transfer), InfiniteTalk
and Wan 2.2 S2V (LTX-2.3 lip sync is far more used), ACE-Step 1.5 (MiniMax Music 3 is more used),
the Qwen 2.1 background remover (20 GB for what BiRefNet does in 0.4 GB) and the Qwen Edit 2509
relight templates (an older model family).

Template quirks fixed in the recipes: `llm_qwen3vl_text_gen` stores a seed control value that
frontend 1.58.5 doesn't create, which shifts three widgets by one (validation fails); the MOSS
layout template names the SFT model but links the Base file, so the starter links the SFT file.
`tools/starters.py` gained two recipe tools for this pass: `loras` (chain an artist or style
LoRA after a loader, shown on the main node) and `"base": "catalog:<id>"` (start from one of our
own hand-built starters).

### More looks: artists and styles

The first pass's 49 looks were almost all Illustrious. The second pass covers every base in the
catalog and video, with 80 new looks (each checked live: public, free, no early access, model and
showcase not flagged `minor` or `poi`, galleries looked at, prompts scanned for youth words):

- **Anima** (no looks before; 62 of the month's top-300 LoRAs): artists Arthur Rackham, Simon
  Bisley, Kentaro Miura, Yusuke Murata, Dan DeCarlo, J. Scott Campbell; styles watercolor, sumi-e,
  impasto/impressionism/chiaroscuro, 90s retro, Octopath pixel art, colored pencil; plus the Anima
  builds of 18 looks the catalog had for Illustrious (Mixplin, Afrobull, Urushihara, Yoneyama Mai,
  Amano, BTAS, flat color, S1 lighting, ...).
- **Anima knows artists natively**: write `@name` (the @ is required; Gelbooru spelling wins,
  e.g. `@shirou masamune`), one artist per prompt (the Qwen3 encoder blends two poorly), weight like
  `(@guweiz:1.2)`, few score tags (they pull towards a generic look). 16 tags across pin-up,
  painterly, retro, manga ink and western are in Suggested > This artist, next to the Illustrious ones.
- **Illustrious**: ukiyo-e / shunga, sumi-e, Norman Rockwell, Art Nouveau, CPS II pixel art,
  Marvel Rivals game art, lineart, Ayami Kojima, Masami Obari, Tsutomu Nihei, Jim Lee.
- **MOSS-Image** (no looks before; 119 of the top 300): Velvet's dark lines, pencil sketch, fantasy
  paint, 70s European comics, pixel art, 80s horror, hentai studio, General Butch 3DCG.
- **Krea 2** (Turbo-checked; the first pass was photo looks only): colored pencil, impressionism,
  watercolor, Ink Riot comic, 90s anime, dark art, claymation, Commodore 64 pixels, dieselpunk
  posters, Velvet's fantasy portraits, and five official Krea LoRAs from Hugging Face (retro anime,
  vintage tarot, Art Deco watercolor, dot matrix, neon drip).
- **Z-Image Turbo / Qwen 2.1**: ink wash, Opus IX comic, cyberpunk anime, 90s anime, Octane 3D,
  Daubrez painterly; colored pencil, Octane 3D, Soyuzmultfilm cartoon.
- **Video**: H3 Ink Riot comic, Safari Eyes 80s cel anime, 1980s fantasy film; Wan 2.2 stylized PBR
  3D (high + low pair); LTX-2.3 claymation, Pixar-like toon, fantasy painterly. Adult LTX-2.3
  LoRAs for the new LTX starters: DR34ML4Y v3, SexGod Female Nudity, Daring's Deepthroat, DaSiWa
  NSFW Body Physics.

Seven style starters put them to work: `anima-artist-styles` (Arthur Rackham LoRA, or any
`@artist`), `illustrious-artist-styles` (Masami Obari LoRA + an optional sumi-e slot, hires fix,
face detailer), `krea2-art-styles` (impressionism), `moss-art-styles` (70s comics),
`zimage-art-styles` (ink wash), `h3-style-t2v` (comic-style video) and `ltx23-nsfw-i2v`. Each
note lists the other LoRAs that fit the same slot.

Left out: Greg Rutkowski's Anima LoRA (he has asked publicly not to be imitated by AI); Anime
Flat Style (its H3/LTX builds show a small nude fox-girl and "school uniform" prompts, so its MOSS
and Qwen builds went too); Dark Ghibli Fairytales ("young girl" prompts on its Anima build); Penile Praxis for LTX (a school-uniform community post); DaSiWa's LTX
2.3 DragonLeap merge (needs his own workflow and four more files); Krea's official `kidsdrawing`
style (the name); and, failing the content rules, Anime Style [Wan 2.2 I2V], LTX 2.5 3D Animation,
LTX Paper Cut-Out, Disney Golden Age (H3), H3 Looping Sketch Anime, 2D Anime NSFW (H3), several
90s-anime video LoRAs and the Redmond Qwen styles. Krea styles shown only on Krea 2 Raw were
skipped. Not verified: nothing was test-generated; Qwen picks were shown on non-turbo Qwen 2.1
(raise the weight on Turbo), most MOSS picks on an 8-step DMD LoRA rather than the catalog's
turbo LoRA, and video steps / CFG are mostly unstated.

## Licences to check before commercial use

Krea 2 Community License (free under USD 1M revenue), Qwen Research License (Qwen-Image 2.1,
non-commercial), CircleStone non-commercial (Anima), FLUX non-commercial (klein 9B / dev),
MiniMax H3 Community License, Apache-2.0 (MOSS-Image, Z-Image, Qwen-Image 2512/2511, Chroma),
CreativeML Open RAIL++-M (SDXL family), and each Civitai creator's own terms (DaSiWa's models
may not be redistributed outside Civitai and his own repositories: the catalog only links to
them). Second pass: LTX-2 Community License (LTX-2.3), MiniMax H3 Community License (Pika H3
Flex), CircleStone non-commercial (Anima LLLite), Apache-2.0 (MiniMax Music 3, Qwen-Image-Edit
2511 and its Lightning / Multiple Angles LoRAs, MOSS edit LoRA, Qwen3-VL), MIT (Pixal3D,
TRELLIS.2, MoGe, BiRefNet).

## Sources

- Krea 2 open weights: [Comfy blog](https://blog.comfy.org/p/krea-2-open-source-models-are-now), [comfyui-wiki](https://comfyui-wiki.com/en/news/2026-06-22-krea-2-open-source-text-to-image)
- MiniMax H3: [Comfy blog](https://blog.comfy.org/minimax-h3-day-0-support-in-comfyui/), [comfyui-wiki](https://comfyui-wiki.com/en/news/2026-08-03-minimax-h3-open-weights-comfyui)
- Civitai split: [Civitai announcement](https://civitai.com/articles/28369), [kombitz](https://www.kombitz.com/2026/04/12/civitai-splits-into-two-platforms-in-major-policy-shift/)
- DaSiWa: [Hugging Face darksidewalker](https://huggingface.co/darksidewalker), [workflows](https://github.com/darksidewalker/dasiwa-comfyui-workflows), [ComfyUI-DaSiWa-Nodes](https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes)
- Official templates: [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)
- Artist tags: [Illustrious-NoobAI Style Explorer](https://github.com/ThetaCursed/Illustrious-NoobAI-Style-Explorer)
- Second pass: template usage counts from `comfyui_workflow_templates_json` 0.11.103 (`index.json`);
  Anima's `@artist` syntax and settings from the [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima)
  model card and its discussions; Krea's official style LoRAs in [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2/tree/main/loras);
  licences from each Hugging Face model card.
- Every pick's model page is linked from its pack in `catalog/catalog.json`.
