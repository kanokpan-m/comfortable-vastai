# Model packs for image and video workflows (November 2026)

This research turns current image and video workflows into **43 ready-made bundles** for Comfortable's
library. It covers the official mainstream models (Qwen-Image, Krea, FLUX, Z-Image, MOSS-Image, Wan,
LTX, MiniMax H3, HunyuanVideo) and the community favourites on Civitai (DaSiWa, SmoothMix, Remix, and
the most-downloaded finetunes and LoRAs).

Every file was resolved on 2026-11-07 against the live Hugging Face and Civitai APIs. Each one has an
exact URL, size and SHA-256 in [`model-packs.json`](model-packs.json). Settings come from the official
ComfyUI workflow templates where one exists, otherwise from the model or creator page.

## Using the packs

```bash
python tools/model_packs.py list                                   # ids, sizes, mature/gated flags
python tools/comfortable.py tunnel                                 # dashboard on localhost:17890
python tools/model_packs.py install wan22-i2v dasiwa-i2v           # adds library items + bundles
python tools/model_packs.py build                                  # re-resolve everything (refresh)
```

**What `install` does**
- Calls the dashboard's existing `/api/bundles/from-workflow` route, then fills in the bundle description
  (summary, settings, VRAM, licence).
- Links files that several packs share (umt5, VAEs, Qwen encoders) to the library item that already
  exists, so they are never downloaded twice. Their SHA-256 values match across repos.
- Skips packs that already exist as a bundle.
- Doesn't download anything. Install a bundle from the Library, or mark it auto-install, or put its
  name in `COMFORTABLE_BUNDLES`.

**Tokens**
- **Hugging Face token:** needed for the two **gated** packs (`flux3-klein`, `ltx-2.5`). Accept the licence
  on each repo page first.
- **Civitai token:** set it in Settings for Civitai files. Mature-flagged models need it to download.

The file names are the ones the official templates use. Load a template, and the Fixer will find these
files already in your library.

## What changed in 2026 (the short version)

**Image**
- **Krea 2** (open weights in Jun 2026, a 12.9B model that isn't based on FLUX) is now the most active
  base on Civitai. Its top finetunes have 90k downloads and its realism LoRAs over 100k. FLUX.1 Krea
  [dev] is now legacy.
- **MOSS-Image** (OpenMOSS, Apache-2.0, released 2026-10-16) was taken up straight away.
  - Comfy-Org's repack shows 5.3M Hugging Face downloads in its first 30 days.
  - Civitai already has a dedicated base-model category with dozens of finetunes.
  - The UltraReal, Realistic Snapshot and Phone Photography LoRA authors released MOSS versions within a week.
  - It is one of the lightest current models: a 5.4 GB int8 model with a 7.3 GB encoder.
- **Qwen-Image 2.1** (7B, Sep 2026; Turbo in Oct) replaces the 20B line for quality per GB. Its licence
  is **Qwen Research (non-commercial)**. The **20B Apache-2.0 models (2512 / Edit 2511)** stay the choice
  when you need a commercial licence or top text rendering.
- **Z-Image Turbo** is still the community's fast photoreal workhorse, and **FLUX 3 [klein]**
  (Oct 2026, gated) is BFL's new open model. **FLUX.2 [klein] 4B** is the only Apache-licensed FLUX.

**Video**
- **Wan 2.2 is still the newest open Wan base.** Wan 2.5, 2.6, 2.7 and 3.0 are API-only; ComfyUI ships
  them only as API nodes. New in the Wan family is **Wan Animate 2** (Aug 2026).
- **LTX-2.5** (Aug 2026) and **MiniMax H3** (Aug 2026) are the new open video+audio models, both native
  in ComfyUI. MiniMax H3 already has community LoRAs on Civitai, tagged "MH3".
- On Civitai, **Wan 2.2 merges remain the community's video favourites**: SmoothMix (224k downloads),
  DaSiWa (184k), Remix (140k).

## Pick by task

The "Pack" column gives the pack id. Install it with `python tools/model_packs.py install <id>`.

| Task | Pack | Alternatives | VRAM |
|---|---|---|---|
| Text→image, best quality per GB | `qwen-image-2.1` / `qwen-image-2.1-turbo` | `krea2-turbo`, `moss-image` | 16 GB |
| Text→image, commercial-safe | `qwen-image-2512` (Apache) | `moss-image`, `z-image-turbo`, `flux2-klein-4b`, `chroma1-hd` | 24 / 12 GB |
| Photoreal portraits / "phone photo" look | `krea2-community` | `z-image-community`, `moss-community` | 16 GB |
| Fast drafts | `z-image-turbo` | `flux2-klein-4b`, `qwen-image-2.1-turbo` | 12 GB |
| Instruction image editing | `qwen-image-edit-2511` | `qwen-image-2.1`, `moss-image` (edit LoRA), `flux3-klein`, `flux1-kontext-dev` | 24 GB |
| Layers / background removal | `qwen-image-layered` | `qwen-image-2.1` (RGBA), BiRefNet in `upscale-restore` | 24 GB |
| ControlNet (pose/depth/canny) | `qwen-image-2512` (Fun Union) | `z-image-turbo` (Union 2.1), `moss-image` (colour/depth LoRA), `sdxl-photo` | |
| Anime | `sdxl-anime` (mature-capable) | Krea 2 `retroanime` style LoRA | 8 GB |
| Image→video | `wan22-i2v` | `dasiwa-i2v`, `smoothmix-wan22`, `ltx-2.5`, `minimax-h3` | 24 GB |
| Text→video | `wan22-t2v` | `smoothmix-wan22` (T2V v4), `ltx-2.5`, `minimax-h3`, `hunyuanvideo-1.5` | 24 GB |
| Video on 8-16 GB | `wan22-ti2v-5b`, `wan22-i2v-gguf` | `dasiwa-i2v-gguf` | 8-16 GB |
| Video with sound | `ltx-2.5`, `minimax-h3` | | 24-32 GB |
| Talking head / lip sync | `wan22-s2v` | `dasiwa-s2v` | 24 GB |
| Character animation / replacement | `wan-animate-2` | | 24 GB |
| Pose/depth-driven video, video inpainting | `wan22-fun-control`, `wan22-vace` | | 24-32 GB |
| Long continuous video | `wan22-addons` (SVI 2.0 Pro) + an I2V pack | DaSiWa C-SVI workflow | |
| Upscale image/video, interpolate frames | `upscale-restore` | | 12 GB |

## The packs

Sizes are the full download. Settings come from the official template unless marked "creator", and
the full text is in each bundle's description. For a commercial project, check the licences that are
"non-commercial", "Research", "Kommunity" or "Community".

### Qwen family
| Pack | Contents | Size | Settings | Licence |
|---|---|---|---|---|
| `qwen-image-2.1` | int8 model, Qwen3-VL 8B encoder, 2.1 VAE, T2I + edit prompt enhancers | 36.2 GB | 25 steps, CFG 1 (5 breaks it), euler/simple | Qwen Research (non-commercial) |
| `qwen-image-2.1-turbo` | Turbo int8 model + shared files | 26.8 GB | 8 steps, CFG 1, template's ManualSigmas | Qwen Research |
| `qwen-image-2512` | 20B fp8, Qwen2.5-VL encoder, VAE, Lightning 4-step, Fun ControlNet Union 2602 | 35.3 GB | 50 steps CFG 4 shift 3.1, or Lightning 4 steps CFG 1 | Apache-2.0 |
| `qwen-image-edit-2511` | Edit 2511 fp8mixed, Lightning 4-step, fal Multiple-Angles LoRA | 31.3 GB | 40 steps CFG 3 shift 3.1, or Lightning 4 steps CFG 1 | Apache-2.0 |
| `qwen-image-layered` | Layered fp8mixed + layered VAE | 30.2 GB | 20 steps, CFG 2.5, shift 1 | Apache-2.0 |
| `qwen-image-gguf` | 2512 + Edit 2511 Q4_K_M (unsloth), both Lightning LoRAs | 37.5 GB | needs ComfyUI-GGUF | Apache-2.0 |
| `qwen-community` | UltraReal Lenovo/GrainScape/Analog for 2.1; Real Life, iPhone realism; Next Scene; Relight, Anything2Real | 2.2 GB | 0.6-1.0 | per LoRA |

### Krea and FLUX
| Pack | Contents | Size | Settings | Licence |
|---|---|---|---|---|
| `krea2-turbo` | Turbo fp8, Qwen3-VL 4B (CLIPLoader type `krea2`), Qwen VAE, style-reference LoRA | 19.1 GB | 8 steps, CFG 1, euler/simple | Krea 2 Community |
| `krea2-styles` | 9 official style LoRAs + Turbo LoRA for Raw | 4.7 GB | 0.8 | Krea 2 Community |
| `krea2-community` | Muse by Stable Yogi v4 (int8), Realistic Snapshot V2, Lenovo UltraReal, UltraReal Pro, Famegrid Natural, Phone Photography 2025, Identity Edit v2 | 24.5 GB | as Turbo | Krea 2 + Civitai terms |
| `flux1-krea-dev` | Krea dev fp8, CLIP-L, T5 fp16, ae, gokaygokay Krea Realism LoRA | 22.4 GB | 20-28 steps, FluxGuidance 4.5 | FLUX.1 [dev] NC |
| `flux1-kontext-dev` | Kontext fp8, CLIP-L, T5 fp8, ae | 17.6 GB | 20 steps, FluxGuidance 2.5 | FLUX.1 [dev] NC |
| `flux2-dev` | FLUX.2 dev fp8mixed, Mistral 3 Small fp8, FLUX.2 VAE, Turbo LoRA | 56.6 GB | 20 steps, guidance 4 (Turbo: 8) | FLUX [dev] NC |
| `flux2-klein-4b` | distilled + base 4B, Qwen3 4B, FLUX.2 VAE | 23.9 GB | distilled 4 steps CFG 1; base 20-50 steps CFG 5 | Apache-2.0 |
| `flux3-klein` | distilled + base int8, Qwen3-VL 4B, Qwen3.5 prompt upsampler (**gated**) | 23.6 GB | 15 steps, CFG 1, er_sde | FLUX Kommunity |
| `chroma1-hd` | Chroma1-HD fp8mixed, T5 fp8, ae | 14.7 GB | 26 steps, CFG 3.5, beta, negative prompt | Apache-2.0 |

### MOSS-Image, Z-Image, ERNIE, SDXL
| Pack | Contents | Size | Settings | Licence |
|---|---|---|---|---|
| `moss-image` | SFT int8, Qwen3.5 9B w4a8, small FLUX.2 VAE, edit LoRA, colour/depth LoRA + MoGe 3, 4-step turbo LoRA | 16.4 GB | 25 steps, CFG 2.5, er_sde; turbo 4 steps CFG 1 | Apache-2.0 |
| `moss-community` | Lenovo, UltraReal v2, GrainScape, Realistic Snapshot, Phone Photography 2025, Realism Enhancer, Analog Core | 1.1 GB | 0.6-1.0 | Civitai terms |
| `z-image-turbo` | Turbo bf16, Qwen3 4B, ae, Fun ControlNet Union 2.1 (8-step) | 27.4 GB | 8 steps, CFG 1, res_multistep, shift 3 | Apache-2.0 |
| `z-image-base` | Base bf16 + shared | 20.7 GB | 25 steps, CFG 4 | Apache-2.0 |
| `z-image-community` | CyberRealistic ZIT v10 (int8) + 7 SFW LoRAs | 16.5 GB | as Turbo | Civitai terms |
| `ernie-image` | Turbo, Ministral 3B, prompt enhancer, FLUX.2 VAE | 31.0 GB | 8 steps, CFG 1 | Apache-2.0 |
| `sdxl-photo` | Juggernaut XL Ragnarok, RealVisXL V5, SDXL VAE, DMD2 4-step, Xinsir Union ProMax | 17.3 GB | 30-40 steps CFG 3-6; DMD2 4-8 steps CFG 1 | mixed (see bundle) |
| `sdxl-anime` | WAI-illustrious v17 (**mature-capable**) | 6.9 GB | Euler a, 25-30 steps, CFG 5-7 | Illustrious |
| `upscale-restore` | SeedVR2 3B int8 + VAE, 4x-UltraSharp, Real-ESRGAN x4+, RIFE 4.26, FILM, face/hand YOLO, BiRefNet | 4.7 GB | SeedVR2: 1 step | mixed |

### Wan 2.2 (official)
All 14B packs share `umt5_xxl_fp8_e4m3fn_scaled` and `wan_2.1_vae`. The 5B model alone uses `wan2.2_vae`.

| Pack | Contents | Size | Settings |
|---|---|---|---|
| `wan22-i2v` | I2V high/low fp8 + 4-step LoRAs v1 | 38.0 GB | 4 steps CFG 1 shift 5, split 2/2; or 20 steps CFG 3.5 split 10/10 shift 8; 81 frames @16 fps |
| `wan22-t2v` | T2V high/low fp8 + 4-step LoRAs v1.1 | 38.0 GB | as I2V |
| `wan22-ti2v-5b` | TI2V 5B fp16 + Wan 2.2 VAE | 18.1 GB | 20 steps, CFG 5, uni_pc, 1280x704, 121 frames @24 fps |
| `wan22-i2v-gguf` | QuantStack Q4_K_M pair + LoRAs | 28.7 GB | needs ComfyUI-GGUF |
| `wan22-fun-control` | Fun Control high/low fp8 + I2V LoRAs | 38.0 GB | 20 steps CFG 3.5, or 4-step |
| `wan22-vace` | Fun VACE high/low fp8 + T2V LoRAs | 44.1 GB | 20 steps CFG 3.5, or 4-step |
| `wan22-s2v` | S2V fp8, wav2vec2 audio encoder | 25.2 GB | 10 steps, CFG 6, uni_pc, 77-frame chunks |
| `wan-animate-2` | Animate 2 distilled int8, CLIP vision H | 24.9 GB | 10 steps, lcm, shift 5, 30 fps |
| `wan22-addons` | lightx2v I2V 1022 / T2V 1217 speed LoRAs, SVI 2.0 Pro, CameraRotation, Face-to-Feet, Anime Style v2 | 6.3 GB | swap-in replacements for the template LoRAs |

### Community Wan merges

#### DaSiWa
DaSiWa is by Darksidewalker: [Civitai](https://civitai.com/models/1981116), and the official Hugging Face
repo `darksidewalker/DaSiWa-WAN2.2-I2V` (gated).

**What it is.** A Wan 2.2 I2V A14B merge, shipped as a high-noise + low-noise pair.
- The **Lightspeed** line has lightning distillation baked in.
- The **TrueVision** line is the non-distilled one.
- It goes in `diffusion_models`, with the stock umt5 encoder and the Wan **2.1** VAE (the creator's
  pages list these).

**Popularity (2026-11-07).** 184,348 downloads for Lightspeed safetensors, 20,439 for TrueVision and
8,864 for GGUF. The creator's workflow pack has 48,758.

**Releases.** 11 in about 8 months, each named:

| Version | Name |
|---|---|
| v4 | TeasingKiss |
| v5 | RadiantCrush |
| v6 | LureNoir |
| v7 | MidnightFlirt |
| v8 | TastySin |
| v9 | SynthSeduction |
| v10 | BoundBite |
| **v11** | **SnatchKiss** (2026-05-17; current) |

**Settings (creator).**
- 4 steps, CFG 1, euler/simple (or uni_pc_bh2), shift 5.
- Up to 720p; 81-97 frames at 16-24 fps.
- **Don't stack Lightning LoRAs**. Run other LoRAs at 0.3-0.6.
- Negative prompts have no effect at CFG 1.

**Which files.** Each v11 version has three files.

| File | Size per expert | Used by |
|---|---|---|
| `_fp8` | 14.2 GB | the pack |
| `_fp8_mixed` | 18.8 GB | higher fidelity, for 32 GB+ cards |
| `_int8_..._convrot` | 14.2 GB | — |

The official GGUF quants are made from the FP16 master, and the creator says FP8-derived quants aren't
comparable.

**Workflow.** "FastFidelity C-AiO" from [civitai.com/models/1823089](https://civitai.com/models/1823089)
(also on GitHub at `darksidewalker/dasiwa-comfyui-workflows`). It needs VideoHelperSuite, KJNodes,
ComfyUI-GGUF and ComfyUI-DaSiWa-Nodes. The C-SVI variant does long video with SVI 2.0 Pro.

**Content.** The creator describes it as "NSFW and SFW", and the version names are suggestive, so these
packs are flagged **mature**.

**Licence.** The Hugging Face card carries an Apache-2.0 tag but adds a no-rehosting clause. Download from
Civitai or the official repo only; the packs do.

| Pack | Files | Size |
|---|---|---|
| `dasiwa-i2v` | v11 Lightspeed fp8 high/low | 36.0 GB |
| `dasiwa-i2v-gguf` | v11 Q4_K_M high/low (official) | 26.3 GB |
| `dasiwa-truevision` | v11 TrueVision fp8_mixed high/low (20-30 steps, CFG 3.5) | 45.9 GB |
| `dasiwa-s2v` | S2V LittleDemon v2 + wav2vec2 | 26.2 GB |

DaSiWa doesn't publish a Wan 2.2 T2V model.

#### Other merges
| Pack | What | Downloads | Settings |
|---|---|---|---|
| `smoothmix-wan22` | SmoothMix I2V v2.0 + T2V v4.0 (Jul 2026), plus I2V speed LoRAs | 224,338 | 4-6 steps CFG 1. I2V v2 has **no** lightx2v baked in (page showcases: 3.0 high / 1.5 low). T2V triggers `smoothmixrealism` / `smoothmixanime` |
| `wan22-remix` | Wan2.2-Remix I2V v3.0 (the final I2V release), lightning baked in | 139,681 | 4-8 steps, CFG 1, shift 5-10 |

All of these are flagged **mature**.

### Other video
| Pack | Contents | Size | Settings | Licence |
|---|---|---|---|---|
| `ltx-2.5` | 22B distilled int8, Gemma 4 12B encoder, Gemma 4 E2B enhancer, video + audio VAE, 2x spatial upscaler (**gated**) | 44.9 GB | euler_ancestral, CFG 1, template sigmas (8 + 3 steps), 768x512, 97 frames @24 fps | LTX-2.x Community |
| `minimax-h3` | fl2va pruned int8, Qwen3-VL 32B nvfp4 encoder, video + audio VAE, lightx2v 8-step Turbo LoRA | 42.0 GB | 4-8 steps, res_multistep, CFG 1 | MiniMax H3 Community |
| `hunyuanvideo-1.5` | 720p T2V + I2V fp16, 1080p SR + upsampler, Qwen2.5-VL + ByT5, VAE, SigCLIP | 63.4 GB | 20 steps, CFG 6, shift 7, 121 frames @24 fps | Tencent Hunyuan Community |

## Community favourites: the numbers behind the picks

Download counts are lifetime totals from the Civitai API on 2026-11-07. Rankings come from
`sort=Most Downloaded&period=Month`, per base model.

| Base | Most downloaded (SFW-flagged picks in **bold**) |
|---|---|
| Wan 2.2 merges | SmoothMix 224k · **DaSiWa** 184k · Remix 140k · FusionX (Wan 2.1) 40k |
| Krea 2 finetunes | **Muse by Stable Yogi** 90k · Realism by Stable Yogi 50k · CyberRealistic 16k · Krealism 11k |
| Z-Image finetunes | **CyberRealistic ZIT** 46k (the merges above it are mature-oriented) |
| MOSS finetunes | **MOSS Image (official)** 26k · Realism by Stable Yogi Moss 14k · Moody Moss Mix 14k (all within three weeks of release) |
| Multi-base realism LoRAs | **Lenovo UltraReal** 218k · **Realistic Snapshot** 114k · **Famegrid** 54k · **UltraReal** 53k · **2000s Analog Core** 40k · **Phone Photography** 33k · **GrainScape** 27k |
| SDXL | Juggernaut XL 1.69M · WAI-illustrious 1.59M |

**What the packs leave out.** Many of the top monthly LoRAs, for every base, are sexual-content LoRAs.
The packs skip those on purpose and use the most-downloaded LoRAs that Civitai flags SFW. Merges that
are popular but mature-oriented (the DaSiWa, SmoothMix and Remix packs, and WAI) are included because
they're the community's standard video and anime models. They are flagged `mature` in the catalog and
their descriptions.

**Model families.** Lenovo UltraReal, GrainScape and 2000s Analog Core are Danrisi's realism series.
Realistic Snapshot and UltraReal now each publish one version per base (Z-Image, Krea 2, MOSS, Qwen 2.1).
The file name `RealisticSnapshotKrea2V2`, used as an example in the README, is the Krea 2 v1.0 release of
Realistic Snapshot.

## Superseded and left out
- **Wan 2.5 / 2.6 / 2.7 / 3.0, FLUX 3 Video, Krea 3:** API-only, available only as ComfyUI API nodes.
- **LTX-2 and LTX-2.3:** replaced by LTX-2.5.
  - `Comfy-Org/ltx-2.3` and `Lightricks/LTX-2.3` still exist.
  - The IC-LoRA templates for object removal and outpainting are still built on LTX-2.3.
- **HunyuanVideo 1.0, Wan 2.1 base models, FusionX:** superseded.
  - The Wan 2.1 VAE, umt5 encoder and CLIP vision H are still required, and they're in the Wan packs.
- **Original Qwen-Image (Aug 2025) and Qwen-Image-Edit / Edit 2509:** replaced by 2512 / Edit 2511.
  - The 2509 LoRAs still work on 2511, and `qwen-community` keeps the useful ones.
- **FLUX.1 [dev] base and its ControlNets / Redux:** these are FLUX.1-only ecosystems. Keep using
  `flux1-krea-dev` for FLUX.1 LoRAs.
- **Chroma1-Radiance:** experimental pixel-space model with rolling, unstable file names.
- **Pony Diffusion V6, NoobAI-XL:** not packaged. For anime, WAI-illustrious is the community default
  by downloads.

## Method and sources
- **File lists:** live Hugging Face tree API, checked for every repo (size and SHA-256 come from the
  LFS pointers).
- **Civitai metadata:** `api/v1/models/<id>` and `api/v1/model-versions/<id>`, for files, sizes, hashes,
  download counts and base models. Per-base rankings came from `api/v1/models?sort=Most Downloaded&period=Month&baseModels=...`.
- **Settings and default file names:** read from the official templates in
  [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates) (`templates/*.json`;
  the pack's `template` field names each one).
- **Licences:** each repo's model card (`license_name`). Where a licence has conditions, the bundle points
  to it rather than paraphrasing it.
- **DaSiWa, SmoothMix and Remix behaviour:** creator pages and articles on Civitai. Settings marked
  "creator" weren't re-tested.

Model files change often. Run `python tools/model_packs.py build` to re-check every URL; it fails on any
file that has gone, before a stale pack can reach an instance.
