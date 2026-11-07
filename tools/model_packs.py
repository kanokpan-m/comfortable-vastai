#!/usr/bin/env python3
"""Curated model packs (bundles) for current image and video workflows.

The packs below are hand-picked (see docs/model-packs.md for the research behind them).
`build` resolves every file against the live Hugging Face and Civitai APIs, failing on any
file that no longer exists, and writes docs/model-packs.json with exact URLs, sizes and SHA-256.
`install` loads packs into a running dashboard as library items and bundles.

    python tools/model_packs.py build                          # refresh docs/model-packs.json
    python tools/model_packs.py list
    python tools/model_packs.py install wan22-i2v dasiwa-i2v   # dashboard on 127.0.0.1:17890
    python tools/model_packs.py install --all --dashboard http://127.0.0.1:17890

Gated Hugging Face repos need HF_TOKEN (and the licence accepted on the repo page) for `build`;
the dashboard's own Hugging Face / Civitai tokens are used for the downloads themselves.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "model-packs.json")
UA = {"User-Agent": "comfortable-model-packs"}

# ---- shared files (one canonical source per filename) ------------------------------------
WAN_TE = {"hf": "Comfy-Org/Wan_2.1_ComfyUI_repackaged/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "cat": "text_encoders", "role": "text encoder"}
WAN21_VAE = {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/vae/wan_2.1_vae.safetensors", "cat": "vae", "role": "VAE (all 14B Wan models)"}
CLIP_VISION_H = {"hf": "Comfy-Org/Wan_2.1_ComfyUI_repackaged/split_files/clip_vision/clip_vision_h.safetensors", "cat": "clip_vision", "role": "image encoder"}
QWEN25_TE = {"hf": "Comfy-Org/Qwen-Image_ComfyUI/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", "cat": "text_encoders", "role": "text encoder"}
QWEN_VAE = {"hf": "Comfy-Org/Qwen-Image_ComfyUI/split_files/vae/qwen_image_vae.safetensors", "cat": "vae", "role": "VAE"}
FLUX1_AE = {"hf": "Comfy-Org/Lumina_Image_2.0_Repackaged/split_files/vae/ae.safetensors", "cat": "vae", "role": "VAE"}
CLIP_L = {"hf": "comfyanonymous/flux_text_encoders/clip_l.safetensors", "cat": "text_encoders", "role": "text encoder (CLIP-L)"}
T5_FP16 = {"hf": "comfyanonymous/flux_text_encoders/t5xxl_fp16.safetensors", "cat": "text_encoders", "role": "text encoder (T5-XXL)"}
T5_FP8 = {"hf": "comfyanonymous/flux_text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors", "cat": "text_encoders", "role": "text encoder (T5-XXL fp8)"}
FLUX2_VAE = {"hf": "Comfy-Org/flux2-dev/split_files/vae/flux2-vae.safetensors", "cat": "vae", "role": "VAE"}
QWEN3_4B = {"hf": "Comfy-Org/z_image_turbo/split_files/text_encoders/qwen_3_4b.safetensors", "cat": "text_encoders", "role": "text encoder"}
ZIMAGE_AE = {"hf": "Comfy-Org/z_image_turbo/split_files/vae/ae.safetensors", "cat": "vae", "role": "VAE"}
KREA2_TE = {"hf": "Comfy-Org/Krea-2/text_encoders/qwen3vl_4b_fp8_scaled.safetensors", "cat": "text_encoders", "role": "text encoder (load with CLIPLoader type krea2)"}
KREA2_VAE = {"hf": "Comfy-Org/Krea-2/vae/qwen_image_vae.safetensors", "cat": "vae", "role": "VAE"}
MOSS_TE = {"hf": "Comfy-Org/MOSS-Image/text_encoders/qwen3.5_9b_w4a8_gptq.safetensors", "cat": "text_encoders", "role": "text encoder"}
MOSS_VAE = {"hf": "Comfy-Org/MOSS-Image/vae/flux2-vae_small.safetensors", "cat": "vae", "role": "VAE"}
QWEN21_TE = {"hf": "Comfy-Org/Qwen-Image-2.1/text_encoders/qwen3vl_8b_int8_convrot.safetensors", "cat": "text_encoders", "role": "text encoder"}
QWEN21_VAE = {"hf": "Comfy-Org/Qwen-Image-2.1/vae/qwen_image_2.1_vae_bf16.safetensors", "cat": "vae", "role": "VAE"}
QWEN21_PE_T2I = {"hf": "Comfy-Org/Qwen-Image-2.1/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors", "cat": "text_encoders", "role": "prompt enhancer (text to image)"}
WAN_I2V_LIGHT = [
    {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "cat": "loras", "role": "4-step LoRA, high noise"},
    {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "cat": "loras", "role": "4-step LoRA, low noise"},
]
WAN_T2V_LIGHT = [
    {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors", "cat": "loras", "role": "4-step LoRA, high noise"},
    {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors", "cat": "loras", "role": "4-step LoRA, low noise"},
]
WAN22 = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/diffusion_models/"


def civ(version_id, filename, cat, role):
    return {"civ": version_id, "file": filename, "cat": cat, "role": role}


# ---- packs ------------------------------------------------------------------------------
# status: current (newest mainstream), stable (still the default for many), community, legacy.
PACKS = [
    # ===== Image: Qwen family =====
    {"id": "qwen-image-2.1", "name": "Qwen-Image 2.1 (T2I + edit)", "icon": "🟣", "task": "image", "family": "Qwen", "status": "current",
     "description": "Alibaba's newest open image model (7B, Sep 2026): text-to-image, editing and background removal (RGBA) from one checkpoint, native 2K.",
     "template": "image_qwen_image_2_1_t2i, image_qwen_image_2_1_image_edit, image_qwen_image_2_1_background_removal",
     "settings": "25 steps, CFG 1 (CFG 5 degrades badly), euler / simple, 1024² and up.",
     "vram": "16 GB+ (int8 model 7.3 GB + int8 encoder 9.4 GB, offloaded between stages).",
     "license": "Qwen Research licence: non-commercial.",
     "items": [{"hf": "Comfy-Org/Qwen-Image-2.1/diffusion_models/qwen_image_2.1_int8_convrot.safetensors", "cat": "diffusion_models", "role": "model"},
               QWEN21_TE, QWEN21_VAE, QWEN21_PE_T2I,
               {"hf": "Comfy-Org/Qwen-Image-2.1/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors", "cat": "text_encoders", "role": "prompt enhancer (edit)"}]},
    {"id": "qwen-image-2.1-turbo", "name": "Qwen-Image 2.1 Turbo (8-step)", "icon": "🟣", "task": "image", "family": "Qwen", "status": "current",
     "description": "Distilled Qwen-Image 2.1 (Oct 2026): 8 steps for text-to-image and edits.",
     "template": "image_qwen_image_2_1_turbo_t2i, image_qwen_image_2_1_turbo_image_edit",
     "settings": "8 steps, CFG 1, euler, with the template's fixed ManualSigmas (keep the schedule if you change steps).",
     "vram": "16 GB+.", "license": "Qwen Research licence: non-commercial.",
     "items": [{"hf": "Comfy-Org/Qwen-Image-2.1/diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors", "cat": "diffusion_models", "role": "model"},
               QWEN21_TE, QWEN21_VAE, QWEN21_PE_T2I]},
    {"id": "qwen-image-2512", "name": "Qwen-Image 2512 (20B, Lightning)", "icon": "🟪", "task": "image", "family": "Qwen", "status": "stable",
     "description": "The 20B Apache-2.0 Qwen-Image (Dec 2025 refresh): best open text rendering with a commercial-friendly licence. Includes the 4-step Lightning LoRA and the 2512 Fun ControlNet Union.",
     "template": "image_qwen_Image_2512, image_qwen_Image_2512_controlnet",
     "settings": "Standard: 50 steps, CFG 4, euler / simple, AuraFlow shift 3.1, 1328². Lightning: 4 steps, CFG 1.",
     "vram": "24 GB+ (20.4 GB fp8 model; text encoder offloads).", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/Qwen-Image_ComfyUI/split_files/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors", "cat": "diffusion_models", "role": "model"},
               QWEN25_TE, QWEN_VAE,
               {"hf": "lightx2v/Qwen-Image-2512-Lightning/Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors", "cat": "loras", "role": "4-step Lightning LoRA"},
               {"hf": "alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union/Qwen-Image-2512-Fun-Controlnet-Union-2602.safetensors", "cat": "controlnet", "role": "ControlNet union (canny, depth, pose)"}]},
    {"id": "qwen-image-edit-2511", "name": "Qwen-Image-Edit 2511 (Lightning)", "icon": "✏️", "task": "image-edit", "family": "Qwen", "status": "stable",
     "description": "The 20B Apache-2.0 instruction editor (multi-image input, consistent identity). Includes the 4-step Lightning LoRA and the most-used camera-angle LoRA.",
     "template": "image_qwen_image_edit_2511",
     "settings": "Standard: 40 steps, CFG 3, euler / simple, shift 3.1. Lightning: 4 steps, CFG 1. Multiple-angles LoRA at 0.8-1.0.",
     "vram": "24 GB+.", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/Qwen-Image-Edit_ComfyUI/split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors", "cat": "diffusion_models", "role": "model"},
               QWEN25_TE, QWEN_VAE,
               {"hf": "lightx2v/Qwen-Image-Edit-2511-Lightning/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", "cat": "loras", "role": "4-step Lightning LoRA"},
               {"hf": "fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA/qwen-image-edit-2511-multiple-angles-lora.safetensors", "cat": "loras", "role": "camera-angle LoRA"}]},
    {"id": "qwen-image-layered", "name": "Qwen-Image Layered (RGBA layers)", "icon": "🧅", "task": "image-edit", "family": "Qwen", "status": "stable",
     "description": "Splits an image into editable RGBA layers.",
     "template": "image_qwen_image_layered (switch its loader to the fp8mixed file)",
     "settings": "20 steps, CFG 2.5, euler / simple, AuraFlow shift 1; 640 px input (1024 px for high-res).",
     "vram": "24 GB+ with fp8 (the template's bf16 file is 40.9 GB).", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/Qwen-Image-Layered_ComfyUI/split_files/diffusion_models/qwen_image_layered_fp8mixed.safetensors", "cat": "diffusion_models", "role": "model"},
               {"hf": "Comfy-Org/Qwen-Image-Layered_ComfyUI/split_files/vae/qwen_image_layered_vae.safetensors", "cat": "vae", "role": "layered VAE"},
               QWEN25_TE]},
    {"id": "qwen-image-gguf", "name": "Qwen-Image 2512 + Edit 2511 GGUF (low VRAM)", "icon": "🪶", "task": "image", "family": "Qwen", "status": "stable",
     "description": "Q4_K_M quantisations of Qwen-Image 2512 and Edit 2511 for 12-16 GB cards. Needs the ComfyUI-GGUF node pack (Unet Loader GGUF).",
     "settings": "As the fp8 packs; pair with the Lightning LoRAs for 4 steps.", "vram": "12-16 GB.", "license": "Apache-2.0.",
     "nodes": ["ComfyUI-GGUF"],
     "items": [{"hf": "unsloth/Qwen-Image-2512-GGUF/qwen-image-2512-Q4_K_M.gguf", "cat": "diffusion_models", "role": "model (GGUF)"},
               {"hf": "unsloth/Qwen-Image-Edit-2511-GGUF/qwen-image-edit-2511-Q4_K_M.gguf", "cat": "diffusion_models", "role": "edit model (GGUF)"},
               QWEN25_TE, QWEN_VAE,
               {"hf": "lightx2v/Qwen-Image-2512-Lightning/Qwen-Image-2512-Lightning-4steps-V1.0-bf16.safetensors", "cat": "loras", "role": "4-step Lightning LoRA (T2I)"},
               {"hf": "lightx2v/Qwen-Image-Edit-2511-Lightning/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", "cat": "loras", "role": "4-step Lightning LoRA (edit)"}]},
    {"id": "qwen-community", "name": "Qwen community LoRAs (realism + edit)", "icon": "🎞️", "task": "image", "family": "Qwen", "status": "community",
     "description": "Most-downloaded SFW Qwen LoRAs on Civitai: Danrisi's UltraReal series for Qwen-Image 2.1, the Real Life and iPhone realism LoRAs for the 20B model, and the Next Scene and Comfy-Org edit LoRAs.",
     "settings": "Realism LoRAs 0.6-1.0 (Lenovo UltraReal trigger: l3n0v0). Next Scene: start the prompt with 'Next Scene:', 0.7-0.8.",
     "license": "Per LoRA (see each Civitai page).",
     "items": [civ(3349565, "lenovo_qwen21.safetensors", "loras", "Lenovo UltraReal (Qwen 2.1)"),
               civ(3352222, "grainscape_qwen21.safetensors", "loras", "GrainScape UltraReal (Qwen 2.1)"),
               civ(3378081, "analogcore_qwen21.safetensors", "loras", "2000s Analog Core (Qwen 2.1)"),
               civ(2106185, "lenovo.safetensors", "loras", "Lenovo UltraReal (Qwen-Image 20B)"),
               civ(2327746, "real_life_qwen.safetensors", "loras", "Real Life (Qwen-Image 20B)"),
               civ(2431035, "iPhone_Realism_v0.9.safetensors", "loras", "iPhone realism (Qwen-Image 20B)"),
               {"hf": "lovis93/next-scene-qwen-image-lora-2509/next-scene_lora-v2-3000.safetensors", "cat": "loras", "role": "Next Scene (Edit 2509+)"},
               {"hf": "Comfy-Org/Qwen-Image-Edit_ComfyUI/split_files/loras/Qwen-Image-Edit-2509-Relight.safetensors", "cat": "loras", "role": "relight (Edit 2509+)"},
               {"hf": "Comfy-Org/Qwen-Image-Edit_ComfyUI/split_files/loras/Qwen-Image-Edit-2509-Anything2RealAlpha.safetensors", "cat": "loras", "role": "anything-to-real (Edit 2509+)"}]},

    # ===== Image: Krea / FLUX family =====
    {"id": "krea2-turbo", "name": "Krea 2 Turbo", "icon": "🌈", "task": "image", "family": "Krea", "status": "current",
     "description": "Krea's own 12.9B model (open weights Jun 2026, not FLUX-based). The most active base on Civitai in late 2026. Includes the official style-reference LoRA.",
     "template": "image_krea2_turbo_t2i, image_krea2_turbo_int8_image_style_reference",
     "settings": "8 steps, CFG 1, euler / simple, 1024². Load the text encoder with CLIPLoader type 'krea2'. Style LoRAs at 0.8.",
     "vram": "16 GB+ (12.5 GB loaded on fp8).", "license": "Krea 2 Community Licence (custom; commercial use has conditions, read krea.ai/krea-2-licensing).",
     "items": [{"hf": "Comfy-Org/Krea-2/diffusion_models/krea2_turbo_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "model"},
               KREA2_TE, KREA2_VAE,
               {"hf": "Comfy-Org/Krea-2/loras/krea2_style_reference.safetensors", "cat": "loras", "role": "style-reference LoRA"}]},
    {"id": "krea2-styles", "name": "Krea 2 official style LoRAs", "icon": "🎨", "task": "image", "family": "Krea", "status": "current",
     "description": "The ten official Krea 2 style LoRAs (darkbrush, dotmatrix, kidsdrawing, neondrip, rainywindow, retroanime, softwatercolor, sunsetblur, vintagetarot) plus the Turbo LoRA for the Raw model.",
     "settings": "0.8 on Krea 2 Turbo. krea2_turbo_lora turns Krea 2 Raw (or Raw-based finetunes) into an 8-step model.",
     "license": "Krea 2 Community Licence.",
     "items": [{"hf": f"Comfy-Org/Krea-2/loras/krea2_{s}.safetensors", "cat": "loras", "role": f"style: {s}"}
               for s in ("darkbrush", "dotmatrix", "kidsdrawing", "neondrip", "rainywindow", "retroanime", "softwatercolor", "sunsetblur", "vintagetarot")]
              + [{"hf": "Comfy-Org/Krea-2/loras/krea2_turbo_lora_rank_64_bf16.safetensors", "cat": "loras", "role": "Turbo LoRA (for Raw)"}]},
    {"id": "krea2-community", "name": "Krea 2 community realism", "icon": "📸", "task": "image", "family": "Krea", "status": "community",
     "description": "The most-downloaded SFW Krea 2 finetune on Civitai (Muse by Stable Yogi, 90k) and the top realism/edit LoRAs: Realistic Snapshot (the file in the Fixer's README example), Lenovo UltraReal, UltraReal Pro, Famegrid Natural, Phone Photography and Identity Edit.",
     "settings": "Same as Krea 2 Turbo (8 steps, CFG 1). Realistic Snapshot: author suggests 1.5-2.0 on v0.5, start at 1.0 on V2. Other LoRAs 0.6-1.0.",
     "vram": "16 GB+.", "license": "Krea 2 Community Licence + each model's Civitai terms.",
     "items": [civ(3425119, "Muse By Stable Yogi Krea2 V4.0 Extended CIV INT8-ConvRot C86.safetensors", "diffusion_models", "finetune (Muse by Stable Yogi v4, int8)"),
               KREA2_TE, KREA2_VAE,
               civ(3371723, "RealisticSnapshotKrea2V2.safetensors", "loras", "Realistic Snapshot Krea2 v1.0"),
               civ(3075606, "lenovo_krea2.safetensors", "loras", "Lenovo UltraReal"),
               civ(3182356, "ultra_real_krea2_v2.safetensors", "loras", "UltraReal Pro v2"),
               civ(3248281, "Famegrid-Natural-V1-Krea-2.safetensors", "loras", "Famegrid Natural"),
               civ(3123277, "phone_photography_2025_krea2.safetensors", "loras", "Phone Photography 2025"),
               civ(3409322, "krea2_identity_edit_v2.safetensors", "loras", "Identity Edit v2")]},
    {"id": "flux1-krea-dev", "name": "FLUX.1 Krea [dev]", "icon": "🌅", "task": "image", "family": "FLUX", "status": "stable",
     "description": "The 2025 Krea x BFL photoreal FLUX.1 model. Superseded by Krea 2 but still compatible with the huge FLUX.1-dev LoRA ecosystem.",
     "template": "flux1_krea_dev",
     "settings": "20-28 steps, CFG 1, FluxGuidance 4.5, euler / simple, 1024-1280 px.",
     "vram": "16 GB+ on fp8 (24 GB with the fp16 T5).", "license": "FLUX.1 [dev] Non-Commercial (generated images are usable commercially).",
     "items": [{"hf": "Comfy-Org/FLUX.1-Krea-dev_ComfyUI/split_files/diffusion_models/flux1-krea-dev_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "model"},
               CLIP_L, T5_FP16, FLUX1_AE,
               civ(2080589, "Flux_Krea_Real.safetensors", "loras", "Flux Krea Realism LoRA (trigger: in the style of R34L)")]},
    {"id": "flux1-kontext-dev", "name": "FLUX.1 Kontext [dev] (edit)", "icon": "🪄", "task": "image-edit", "family": "FLUX", "status": "legacy",
     "description": "FLUX.1 instruction editing. Largely replaced by Qwen-Image-Edit, FLUX.2/3 Klein and MOSS edit, but many workflows still use it.",
     "template": "flux_kontext_dev_basic", "settings": "20 steps, CFG 1, FluxGuidance 2.5, euler / simple.",
     "vram": "16 GB+.", "license": "FLUX.1 [dev] Non-Commercial.",
     "items": [{"hf": "Comfy-Org/flux1-kontext-dev_ComfyUI/split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "model"},
               CLIP_L, T5_FP8, FLUX1_AE]},
    {"id": "flux2-dev", "name": "FLUX.2 [dev] (+ Turbo LoRA)", "icon": "🔷", "task": "image", "family": "FLUX", "status": "stable",
     "description": "BFL's 32B FLUX.2 [dev] (Nov 2025) with multi-reference editing; the Turbo LoRA brings it to 8 steps.",
     "template": "image_flux2 (switch the text encoder to the fp8 file)",
     "settings": "20 steps, FluxGuidance 4, euler, Flux2Scheduler; Turbo LoRA: 8 steps.",
     "vram": "48 GB class (35.5 GB model + 18 GB fp8 encoder; 24 GB works with heavy offloading).", "license": "FLUX [dev] Non-Commercial.",
     "items": [{"hf": "Comfy-Org/flux2-dev/split_files/diffusion_models/flux2_dev_fp8mixed.safetensors", "cat": "diffusion_models", "role": "model"},
               {"hf": "Comfy-Org/flux2-dev/split_files/text_encoders/mistral_3_small_flux2_fp8.safetensors", "cat": "text_encoders", "role": "text encoder (Mistral 3 Small fp8)"},
               FLUX2_VAE,
               {"hf": "Comfy-Org/flux2-dev/split_files/loras/Flux_2-Turbo-LoRA_comfyui.safetensors", "cat": "loras", "role": "Turbo LoRA (8 steps)"}]},
    {"id": "flux2-klein-4b", "name": "FLUX.2 [klein] 4B", "icon": "🔹", "task": "image", "family": "FLUX", "status": "stable",
     "description": "Small, fast FLUX.2 (Jan 2026) for text-to-image and editing; the only Apache-licensed FLUX.2. Distilled (4 steps) and base models.",
     "template": "image_flux2_klein_text_to_image, image_flux2_klein_image_edit_4b_distilled",
     "settings": "Distilled: 4 steps, CFG 1, euler. Base: 20-50 steps, CFG 5.",
     "vram": "12 GB+.", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/Flux-2-Klein-4B/split_files/diffusion_models/flux-2-klein-4b.safetensors", "cat": "diffusion_models", "role": "distilled model"},
               {"hf": "Comfy-Org/Flux-2-Klein-4B/split_files/diffusion_models/flux-2-klein-base-4b.safetensors", "cat": "diffusion_models", "role": "base model"},
               QWEN3_4B, FLUX2_VAE]},
    {"id": "flux3-klein", "name": "FLUX 3 [klein] (image)", "icon": "💠", "task": "image", "family": "FLUX", "status": "current",
     "description": "BFL's open FLUX 3 Image Klein (Oct 2026): text-to-image and editing, distilled and base, with a Qwen3.5 prompt upsampler. Gated: accept the licence on Hugging Face and add an HF token.",
     "template": "image_flux3_klein_distilled_t2i, image_flux3_klein_t2i, image_flux3_klein_image_edit",
     "settings": "Distilled: 15 steps, CFG 1, er_sde / simple. Base: 15-50 steps (edit template 50, euler).",
     "vram": "16 GB+ (5.8 GB model, 4.9 GB encoder, 6.7 GB upsampler).", "license": "FLUX Kommunity Licence (gated; read the terms before commercial use).",
     "items": [{"hf": "black-forest-labs/flux-3-image-klein-comfy/diffusion_models/flux3-image-klein-int8-convrot.safetensors", "cat": "diffusion_models", "role": "distilled model"},
               {"hf": "black-forest-labs/flux-3-image-klein-comfy/diffusion_models/flux3-image-klein-base-int8-convrot.safetensors", "cat": "diffusion_models", "role": "base model (edit)"},
               {"hf": "black-forest-labs/flux-3-image-klein-comfy/text_encoders/qwen3vl_4b_int8_convrot.safetensors", "cat": "text_encoders", "role": "text encoder"},
               {"hf": "black-forest-labs/flux-3-image-klein-comfy/text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors", "cat": "text_encoders", "role": "prompt upsampler"},
               FLUX2_VAE]},
    {"id": "chroma1-hd", "name": "Chroma1-HD", "icon": "🌀", "task": "image", "family": "FLUX", "status": "stable",
     "description": "Apache-2.0, uncensored 8.9B model derived from FLUX.1 [schnell]; uses real CFG and negative prompts.",
     "template": "image_chroma_text_to_image", "settings": "26 steps, CFG 3.5, euler / beta, AuraFlow shift 1. Needs a negative prompt.",
     "vram": "12-16 GB on fp8.", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/Chroma1-HD_repackaged/split_files/diffusion_models/Chroma1-HD-fp8mixed.safetensors", "cat": "diffusion_models", "role": "model"},
               T5_FP8, FLUX1_AE]},

    # ===== Image: other current bases =====
    {"id": "moss-image", "name": "MOSS-Image (T2I + edit + control)", "icon": "🌿", "task": "image", "family": "MOSS", "status": "current",
     "description": "OpenMOSS's Apache-2.0 model (Oct 2026), adopted by Civitai within days. SFT model, the official edit LoRA, the colour/depth control LoRA with its MoGe depth estimator, and the most-downloaded 4-step turbo LoRA.",
     "template": "image_moss_image_t2i, image_moss_image_edit, image_moss_image_color_depth_control",
     "settings": "T2I: 25 steps, CFG 2.5, er_sde / simple. Edit LoRA: 30 steps, CFG 4, euler / normal. Turbo LoRA: 4 steps, CFG 1.",
     "vram": "12 GB+ (5.4 GB int8 model, 7.3 GB w4a8 encoder).", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/MOSS-Image/diffusion_models/moss_image_sft_int8_convrot.safetensors", "cat": "diffusion_models", "role": "SFT model"},
               MOSS_TE, MOSS_VAE,
               {"hf": "Comfy-Org/MOSS-Image/loras/moss_image_edit_lora_rank_64_bf16.safetensors", "cat": "loras", "role": "edit LoRA"},
               {"hf": "Comfy-Org/MOSS-Image/loras/moss_image_color_depth_control.safetensors", "cat": "loras", "role": "colour/depth control LoRA"},
               {"hf": "Comfy-Org/MoGe/geometry_estimation/moge_3_vitg_fp16.safetensors", "cat": "geometry_estimation", "role": "depth estimator (MoGe 3)"},
               civ(3414934, "moss_image_sft_4_steps_lora_v2_600_avg_rank_72_bf16.safetensors", "loras", "4-step turbo LoRA (v2)")]},
    {"id": "moss-community", "name": "MOSS-Image community realism", "icon": "🍃", "task": "image", "family": "MOSS", "status": "community",
     "description": "Top SFW MOSS LoRAs from its first weeks on Civitai: Lenovo UltraReal, UltraReal v2, GrainScape, Realistic Snapshot, Phone Photography 2025, Realism Enhancer, 2000s Analog Core.",
     "settings": "0.6-1.0 on MOSS SFT (Lenovo trigger: l3n0v0).", "license": "Each model's Civitai terms.",
     "items": [civ(3410543, "lenovo_moss.safetensors", "loras", "Lenovo UltraReal"),
               civ(3416438, "ultra_real_moss_v2.safetensors", "loras", "UltraReal v2"),
               civ(3410552, "grainscape_moss.safetensors", "loras", "GrainScape UltraReal"),
               civ(3417962, "MOSSRealisticSnapshotV1.safetensors", "loras", "Realistic Snapshot"),
               civ(3426517, "phone_photography_2025_moss.safetensors", "loras", "Phone Photography 2025"),
               civ(3433342, "Moss-RealismEnhancer-V1.safetensors", "loras", "Realism Enhancer"),
               civ(3415542, "hi8_v2_moss.safetensors", "loras", "2000s Analog Core")]},
    {"id": "z-image-turbo", "name": "Z-Image Turbo (+ ControlNet)", "icon": "⚡", "task": "image", "family": "Z-Image", "status": "stable",
     "description": "Tongyi's 6B 8-step model (Apache-2.0): fast photoreal, the 2026 community workhorse. Includes the Fun ControlNet Union 2.1.",
     "template": "image_z_image_turbo, image_z_image_turbo_fun_union_controlnet",
     "settings": "8 steps, CFG 1, res_multistep / simple, AuraFlow shift 3, no negative prompt. Text encoder: CLIPLoader type lumina2.",
     "vram": "12-16 GB (bf16 model 12.3 GB; an int8 file is in the same repo).", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/z_image_turbo/split_files/diffusion_models/z_image_turbo_bf16.safetensors", "cat": "diffusion_models", "role": "model"},
               QWEN3_4B, ZIMAGE_AE,
               {"hf": "alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/Z-Image-Turbo-Fun-Controlnet-Union-2.1-8steps.safetensors", "cat": "model_patches", "role": "ControlNet union 2.1 (model patch)"}]},
    {"id": "z-image-base", "name": "Z-Image Base", "icon": "⚡", "task": "image", "family": "Z-Image", "status": "stable",
     "description": "The non-distilled Z-Image (Jan 2026): full CFG and negative prompts, the base most Z-Image LoRAs are trained on.",
     "template": "image_z_image", "settings": "25 steps, CFG 4, res_multistep / simple, shift 3.",
     "vram": "16 GB+.", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/z_image/split_files/diffusion_models/z_image_bf16.safetensors", "cat": "diffusion_models", "role": "model"}, QWEN3_4B, ZIMAGE_AE]},
    {"id": "z-image-community", "name": "Z-Image Turbo community", "icon": "🔆", "task": "image", "family": "Z-Image", "status": "community",
     "description": "CyberRealistic ZIT v10 (the most-downloaded SFW Z-Image finetune) and the top SFW Z-Image Turbo LoRAs: Realistic Snapshot v5, Lenovo UltraReal, GrainScape, 2000s Analog Core, Aesthetic, Flow-DPO and Pixel Art.",
     "settings": "Same as Z-Image Turbo. LoRAs 0.6-1.0 (Pixel Art trigger: 'Pixel Art style.').",
     "vram": "12 GB+.", "license": "Apache-2.0 base + each model's Civitai terms.",
     "items": [civ(3411348, "CyberRealistic_zit_v10.0_int8_convrot.safetensors", "diffusion_models", "finetune (CyberRealistic ZIT v10, int8)"),
               QWEN3_4B, ZIMAGE_AE,
               civ(2617751, "RealisticSnapshot-Zimage-Turbov5.safetensors", "loras", "Realistic Snapshot v5"),
               civ(2452071, "lenovo_z.safetensors", "loras", "Lenovo UltraReal"),
               civ(2460872, "grainscape_zimage.safetensors", "loras", "GrainScape UltraReal"),
               civ(2456725, "HI8.safetensors", "loras", "2000s Analog Core"),
               civ(2493457, "Z-Image-Aesthetic_v1.safetensors", "loras", "Z-Image Aesthetic"),
               civ(2721846, "zit_fdpo_v1.safetensors", "loras", "Flow-DPO lighting"),
               civ(2454660, "pixel_art_style_z_image_turbo.safetensors", "loras", "Pixel Art style")]},
    {"id": "ernie-image", "name": "ERNIE-Image Turbo", "icon": "🔶", "task": "image", "family": "ERNIE", "status": "stable",
     "description": "Baidu's 8B Apache-2.0 model with a prompt enhancer; strong on Chinese and English text.",
     "template": "image_ernie_image_turbo", "settings": "8 steps, CFG 1, euler / simple. Base model: ~50 steps, CFG 4-5.",
     "vram": "16-24 GB.", "license": "Apache-2.0.",
     "items": [{"hf": "Comfy-Org/ERNIE-Image/diffusion_models/ernie-image-turbo.safetensors", "cat": "diffusion_models", "role": "model"},
               {"hf": "Comfy-Org/ERNIE-Image/text_encoders/ministral-3-3b.safetensors", "cat": "text_encoders", "role": "text encoder"},
               {"hf": "Comfy-Org/ERNIE-Image/text_encoders/ernie-image-prompt-enhancer.safetensors", "cat": "text_encoders", "role": "prompt enhancer"},
               FLUX2_VAE]},

    # ===== Image: SDXL =====
    {"id": "sdxl-photo", "name": "SDXL photoreal + essentials", "icon": "📷", "task": "image", "family": "SDXL", "status": "legacy",
     "description": "The two most-used SDXL photo checkpoints (Juggernaut XL Ragnarok, 528k downloads; RealVisXL V5) with the DMD2 4-step LoRA, Xinsir ControlNet Union ProMax and the SDXL VAE. Runs on 8 GB.",
     "template": "image_sdxl_simple",
     "settings": "Juggernaut: 30-40 steps, CFG 3-6, DPM++ 2M SDE, 832x1216. DMD2: 4-8 steps, CFG 1, lcm / sgm_uniform.",
     "vram": "8 GB+.", "license": "RealVisXL: OpenRAIL++. Juggernaut: RunDiffusion licence (read before commercial/API use). DMD2: CC BY-NC 4.0.",
     "items": [civ(1759168, "JuggernautXL_Ragnarok_ByRunDiffusion.safetensors", "checkpoints", "Juggernaut XL Ragnarok"),
               {"hf": "SG161222/RealVisXL_V5.0/RealVisXL_V5.0_fp16.safetensors", "cat": "checkpoints", "role": "RealVisXL V5"},
               {"hf": "stabilityai/sdxl-vae/sdxl_vae.safetensors", "cat": "vae", "role": "VAE"},
               {"hf": "tianweiy/DMD2/dmd2_sdxl_4step_lora_fp16.safetensors", "cat": "loras", "role": "DMD2 4-step LoRA"},
               {"hf": "xinsir/controlnet-union-sdxl-1.0/diffusion_pytorch_model_promax.safetensors", "cat": "controlnet", "role": "ControlNet Union ProMax", "filename": "xinsir_union_sdxl_promax.safetensors"}]},
    {"id": "sdxl-anime", "name": "Illustrious anime (WAI v17)", "icon": "🌸", "task": "image", "family": "SDXL", "status": "community", "mature": True,
     "description": "WAI-illustrious-SDXL, the most-downloaded anime checkpoint on Civitai (1.58M). Mature-capable; the file is named WAI-Nsfw-Illustrious-17.",
     "settings": "Euler a, 25-30 steps, CFG 5-7, 832x1216, Danbooru-style tags.", "vram": "8 GB+.", "license": "Illustrious licence + Civitai terms.",
     "items": [civ(2883731, "WAI-Nsfw-Illustrious-17.safetensors", "checkpoints", "WAI-illustrious v17")]},

    # ===== Utilities =====
    {"id": "upscale-restore", "name": "Upscale, restore & interpolate", "icon": "🔍", "task": "utility", "family": "Utility", "status": "current",
     "description": "SeedVR2 3B int8 (native ComfyUI image/video upscaler), 4x-UltraSharp and Real-ESRGAN x4+, RIFE 4.26 and FILM frame interpolation, face/hand YOLO detectors for detailers, BiRefNet background removal.",
     "template": "utility_seedvr2_3b_int8_upscale_video, utility_video_frame_interpolation, utility-gan_upscaler",
     "settings": "SeedVR2: 1 step, CFG 1. RIFE 4.26 is the fast default, FILM the quality option.",
     "vram": "SeedVR2 3B int8: 12 GB+. Everything else: any GPU.",
     "license": "Apache-2.0 / BSD / MIT; 4x-UltraSharp is CC BY-NC-SA.",
     "nodes": ["ComfyUI-Impact-Pack + Impact-Subpack (YOLO detectors)", "ComfyUI-RMBG (BiRefNet)"],
     "items": [{"hf": "Comfy-Org/SeedVR2/diffusion_models/seedvr2_3b_int8_convrot.safetensors", "cat": "diffusion_models", "role": "SeedVR2 3B upscaler"},
               {"hf": "Comfy-Org/SeedVR2/vae/seedvr2_ema_vae_fp16.safetensors", "cat": "vae", "role": "SeedVR2 VAE"},
               {"hf": "Kim2091/UltraSharp/4x-UltraSharp.pth", "cat": "upscale_models", "role": "4x-UltraSharp"},
               {"hf": "Comfy-Org/Real-ESRGAN_repackaged/RealESRGAN_x4plus.safetensors", "cat": "upscale_models", "role": "Real-ESRGAN x4+"},
               {"hf": "Comfy-Org/frame_interpolation/frame_interpolation/rife_v4.26.safetensors", "cat": "frame_interpolation", "role": "RIFE 4.26"},
               {"hf": "Comfy-Org/frame_interpolation/frame_interpolation/film_net_fp16.safetensors", "cat": "frame_interpolation", "role": "FILM"},
               {"hf": "Bingsu/adetailer/face_yolov8m.pt", "cat": "detection", "role": "face detector"},
               {"hf": "Bingsu/adetailer/hand_yolov8s.pt", "cat": "detection", "role": "hand detector"},
               {"hf": "ZhengPeng7/BiRefNet/model.safetensors", "cat": "background_removal", "role": "BiRefNet", "filename": "BiRefNet.safetensors"}]},

    # ===== Video: Wan 2.2 official =====
    {"id": "wan22-i2v", "name": "Wan 2.2 I2V 14B (+ first/last frame)", "icon": "🎬", "task": "video", "family": "Wan", "status": "stable",
     "description": "Official Wan 2.2 image-to-video (MoE high/low-noise pair) with the template's 4-step lightx2v LoRAs. Also drives first-last-frame (FLF2V). The base every Civitai Wan merge builds on.",
     "template": "video_wan2_2_14B_i2v, video_wan2_2_14B_flf2v",
     "settings": "4-step: CFG 1, euler / simple, shift 5, steps 0-2 high then 2-4 low. Without LoRAs: 20 steps, CFG 3.5, split 10/10, shift 8. 640-720p, 81 frames, 16 fps.",
     "vram": "24 GB recommended (two 14.3 GB experts load one at a time); 16 GB with offloading.", "license": "Apache-2.0.",
     "items": [{"hf": WAN22 + "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "high-noise expert"},
               {"hf": WAN22 + "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "low-noise expert"},
               WAN_TE, WAN21_VAE, *WAN_I2V_LIGHT]},
    {"id": "wan22-t2v", "name": "Wan 2.2 T2V 14B", "icon": "🎥", "task": "video", "family": "Wan", "status": "stable",
     "description": "Official Wan 2.2 text-to-video with the template's 4-step lightx2v LoRAs (v1.1).",
     "template": "video_wan2_2_14B_t2v",
     "settings": "4-step: CFG 1, euler / simple, shift 5, split 2/2. Without LoRAs: 20 steps, CFG 3.5, split 10/10, shift 8. 640-720p, 81 frames, 16 fps.",
     "vram": "24 GB recommended.", "license": "Apache-2.0.",
     "items": [{"hf": WAN22 + "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "high-noise expert"},
               {"hf": WAN22 + "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "low-noise expert"},
               WAN_TE, WAN21_VAE, *WAN_T2V_LIGHT]},
    {"id": "wan22-ti2v-5b", "name": "Wan 2.2 TI2V 5B (8 GB)", "icon": "📼", "task": "video", "family": "Wan", "status": "stable",
     "description": "The small Wan 2.2: text- or image-to-video at 720p/24 fps on 8 GB cards. Uses the Wan 2.2 VAE (not 2.1).",
     "template": "video_wan2_2_5B_ti2v", "settings": "20 steps, CFG 5, uni_pc / simple, shift 8, 1280x704, 121 frames, 24 fps.",
     "vram": "8 GB+ with offloading.", "license": "Apache-2.0.",
     "items": [{"hf": WAN22 + "wan2.2_ti2v_5B_fp16.safetensors", "cat": "diffusion_models", "role": "model"},
               WAN_TE, {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/vae/wan2.2_vae.safetensors", "cat": "vae", "role": "Wan 2.2 VAE"}]},
    {"id": "wan22-i2v-gguf", "name": "Wan 2.2 I2V GGUF Q4 (12-16 GB)", "icon": "🪶", "task": "video", "family": "Wan", "status": "stable",
     "description": "QuantStack Q4_K_M Wan 2.2 I2V pair for 12-16 GB cards, with the 4-step LoRAs. Needs ComfyUI-GGUF.",
     "settings": "As Wan 2.2 I2V (4 steps, CFG 1, split 2/2).", "vram": "12-16 GB.", "license": "Apache-2.0.", "nodes": ["ComfyUI-GGUF"],
     "items": [{"hf": "QuantStack/Wan2.2-I2V-A14B-GGUF/HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf", "cat": "diffusion_models", "role": "high-noise expert (GGUF)"},
               {"hf": "QuantStack/Wan2.2-I2V-A14B-GGUF/LowNoise/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf", "cat": "diffusion_models", "role": "low-noise expert (GGUF)"},
               WAN_TE, WAN21_VAE, *WAN_I2V_LIGHT]},
    {"id": "wan22-fun-control", "name": "Wan 2.2 Fun Control (pose/depth/canny)", "icon": "🕹️", "task": "video", "family": "Wan", "status": "stable",
     "description": "Wan 2.2 Fun Control 14B: drive video with pose, depth, canny, MLSD or trajectories. Uses the I2V 4-step LoRAs.",
     "template": "video_wan2_2_14B_fun_control", "settings": "20 steps, CFG 3.5, split 10/10, shift 8; or 4 steps CFG 1 with the LoRAs.",
     "vram": "24 GB recommended.", "license": "Apache-2.0.", "nodes": ["comfyui_controlnet_aux (preprocessors)"],
     "items": [{"hf": WAN22 + "wan2.2_fun_control_high_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "high-noise expert"},
               {"hf": WAN22 + "wan2.2_fun_control_low_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "low-noise expert"},
               WAN_TE, WAN21_VAE, *WAN_I2V_LIGHT]},
    {"id": "wan22-vace", "name": "Wan 2.2 Fun VACE (all-in-one editing)", "icon": "🧩", "task": "video", "family": "Wan", "status": "stable",
     "description": "Wan 2.2 Fun VACE 14B: reference-to-video, video inpainting/outpainting and control in one model.",
     "template": "video_wan_vace_14B_ref2v, video_wan_vace_inpainting, video_wan_vace_outpainting (2.1 templates; swap in these models)",
     "settings": "20 steps, CFG 3.5, split 10/10; or 4 steps CFG 1 with the T2V LoRAs.", "vram": "24-32 GB (17.4 GB experts).", "license": "Apache-2.0.",
     "items": [{"hf": WAN22 + "wan2.2_fun_vace_high_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "high-noise expert"},
               {"hf": WAN22 + "wan2.2_fun_vace_low_noise_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "low-noise expert"},
               WAN_TE, WAN21_VAE, *WAN_T2V_LIGHT]},
    {"id": "wan22-s2v", "name": "Wan 2.2 S2V (talking video)", "icon": "🗣️", "task": "video", "family": "Wan", "status": "stable",
     "description": "Wan 2.2 speech-to-video: image + audio to a talking/singing video.",
     "template": "video_wan2_2_14B_s2v", "settings": "10 steps per chunk, CFG 6, uni_pc / simple, shift 8, 77-frame chunks, 16 fps. The 4-step LoRA path loses motion quality.",
     "vram": "24 GB recommended.", "license": "Apache-2.0.",
     "items": [{"hf": WAN22 + "wan2.2_s2v_14B_fp8_scaled.safetensors", "cat": "diffusion_models", "role": "model"},
               {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors", "cat": "audio_encoders", "role": "audio encoder"},
               WAN_TE, WAN21_VAE, WAN_T2V_LIGHT[0]]},
    {"id": "wan-animate-2", "name": "Wan Animate 2 (character animation)", "icon": "💃", "task": "video", "family": "Wan", "status": "current",
     "description": "Wan-AI's Animate 2 (Aug 2026): animate a character image from a driving video, or replace a character in a video. Distilled model, no speed LoRA needed.",
     "template": "video_wan_animate2_distilled (video_wan_animate2 for the non-distilled model)",
     "settings": "10 steps, lcm / simple, shift 5, 30 fps output.", "vram": "24 GB+ (16.7 GB int8 model).", "license": "Apache-2.0.",
     "nodes": ["ComfyUI-KJNodes", "comfyui_controlnet_aux"],
     "items": [{"hf": "Comfy-Org/Wan-Animate-2/diffusion_models/wan_animate_2_distill_int8_convrot.safetensors", "cat": "diffusion_models", "role": "model (distilled)"},
               {"hf": "Comfy-Org/Wan-Animate-2/vae/Wan2_1_VAE_bf16.safetensors", "cat": "vae", "role": "VAE"},
               WAN_TE, CLIP_VISION_H]},
    {"id": "wan22-addons", "name": "Wan 2.2 add-ons (newer speed LoRAs, long video, camera)", "icon": "🧰", "task": "video", "family": "Wan", "status": "community",
     "description": "lightx2v's newer distill LoRAs (I2V 1022, T2V 1217), SVI 2.0 Pro for long continuous videos, and the most-downloaded SFW motion/style LoRAs: CameraRotation, Face-to-Feet camera, Anime Style v2.",
     "settings": "Speed LoRAs replace the Comfy v1/v1.1 ones (1.0 each, 4 steps). SVI Pro needs its workflow (e.g. DaSiWa C-SVI). Camera LoRAs 0.8-1.0 on the expert they were trained for.",
     "license": "Apache-2.0 (lightx2v, SVI) + each LoRA's Civitai terms.",
     "items": [{"hf": "lightx2v/Wan2.2-Distill-Loras/wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors", "cat": "loras", "role": "I2V speed LoRA 1022, high"},
               {"hf": "lightx2v/Wan2.2-Distill-Loras/wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors", "cat": "loras", "role": "I2V speed LoRA 1022, low"},
               {"hf": "lightx2v/Wan2.2-Distill-Loras/wan2.2_t2v_A14b_high_noise_lora_rank64_lightx2v_4step_1217.safetensors", "cat": "loras", "role": "T2V speed LoRA 1217, high"},
               {"hf": "lightx2v/Wan2.2-Distill-Loras/wan2.2_t2v_A14b_low_noise_lora_rank64_lightx2v_4step_1217.safetensors", "cat": "loras", "role": "T2V speed LoRA 1217, low"},
               {"hf": "Kijai/WanVideo_comfy/LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors", "cat": "loras", "role": "SVI 2.0 Pro, high"},
               {"hf": "Kijai/WanVideo_comfy/LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors", "cat": "loras", "role": "SVI 2.0 Pro, low"},
               civ(2108675, "wan22-video13-CameraRotation-16-sel-2.safetensors", "loras", "CameraRotation (high noise; trigger: camera rotation effect)"),
               civ(2632191, "Wan2.2 I2V Face-to-Feet Motion camera high_noise.safetensors", "loras", "Face-to-Feet camera, high"),
               civ(2632200, "Wan2.2 I2V Face-to-Feet Motion camera low_noise.safetensors.safetensors", "loras", "Face-to-Feet camera, low"),
               civ(2516837, "wan2.2_i2v_animestyle_v2_high.safetensors", "loras", "Anime Style v2, high (trigger: An1meStyl3, AnimeStyle)"),
               civ(2516839, "wan2.2_i2v_animestyle_v2_low.safetensors", "loras", "Anime Style v2, low")]},

    # ===== Video: community merges =====
    {"id": "dasiwa-i2v", "name": "DaSiWa Wan 2.2 I2V Lightspeed v11", "icon": "💀", "task": "video", "family": "Wan (community)", "status": "community", "mature": True,
     "description": "Darksidewalker's DaSiWa, the most popular Wan 2.2 I2V merge on Civitai (184k downloads, 11 releases). v11 'SnatchKiss' (May 2026), lightning distillation baked in. Mature-oriented (SFW and NSFW).",
     "template": "Creator's FastFidelity C-AiO workflow: civitai.com/models/1823089 (needs VideoHelperSuite, KJNodes, ComfyUI-GGUF, ComfyUI-DaSiWa-Nodes)",
     "settings": "4 steps, CFG 1, euler / simple (or uni_pc_bh2), shift 5, up to 720p, 81-97 frames at 16-24 fps. Don't add Lightning LoRAs; other LoRAs at 0.3-0.6. Negative prompts do nothing at CFG 1.",
     "vram": "16 GB+ (14.2 GB per expert). The fp8_mixed files in the same versions (18.8 GB) are higher fidelity for 32 GB+ cards.",
     "license": "Apache-2.0 tag, but the creator forbids re-hosting: download from Civitai or the official HF repo only.",
     "nodes": ["ComfyUI-VideoHelperSuite", "ComfyUI-KJNodes", "ComfyUI-DaSiWa-Nodes"],
     "items": [civ(2953474, "DaSiWa_Wan22_I2V_14B_SnatchKiss_v11_HIGH_fp8.safetensors", "diffusion_models", "high-noise expert"),
               civ(2953485, "DaSiWa_Wan22_I2V_14B_SnatchKiss_v11_LOW_fp8.safetensors", "diffusion_models", "low-noise expert"),
               WAN_TE, WAN21_VAE]},
    {"id": "dasiwa-i2v-gguf", "name": "DaSiWa Wan 2.2 I2V v11 GGUF Q4 (low VRAM)", "icon": "💀", "task": "video", "family": "Wan (community)", "status": "community", "mature": True,
     "description": "The creator's official Q4_K_M quantisation of DaSiWa v11 (made from the FP16 master) for 12-16 GB cards. Mature-oriented.",
     "settings": "As DaSiWa Lightspeed (4 steps, CFG 1).", "vram": "12-16 GB (Q8 on 16 GB + 64 GB RAM per the creator).",
     "license": "As DaSiWa.", "nodes": ["ComfyUI-GGUF"],
     "items": [civ(2956320, "DaSiWa_Wan22_I2V_14B_HIGH_v11_Q4_K_M-fix.gguf", "diffusion_models", "high-noise expert (GGUF)"),
               civ(2957206, "DaSiWa_Wan22_I2V_14B_LOW_v11_Q4_K_M-fix.gguf", "diffusion_models", "low-noise expert (GGUF)"),
               WAN_TE, WAN21_VAE]},
    {"id": "dasiwa-truevision", "name": "DaSiWa Wan 2.2 I2V TrueVision v11 (non-distilled)", "icon": "💠", "task": "video", "family": "Wan (community)", "status": "community", "mature": True,
     "description": "The non-distilled DaSiWa line: no speed-up baked in, for full-quality 20-30 step renders and LoRA training-style fidelity. Mature-oriented.",
     "settings": "20-30 steps, CFG 3.5, euler / simple, shift 5-8, split half/half.", "vram": "24 GB+ (19 GB per expert).", "license": "As DaSiWa.",
     "items": [civ(2959309, "DaSiWa_Wan22_I2V_14B_SnatchKiss_HIGH_v11_TrueVision_fp8_mixed.safetensors", "diffusion_models", "high-noise expert"),
               civ(2959520, "DaSiWa_Wan22_I2V_14B_SnatchKiss_LOW_v11_TrueVision_fp8_mixed.safetensors", "diffusion_models", "low-noise expert"),
               WAN_TE, WAN21_VAE]},
    {"id": "dasiwa-s2v", "name": "DaSiWa Wan 2.2 S2V LittleDemon v2", "icon": "🔊", "task": "video", "family": "Wan (community)", "status": "community", "mature": True,
     "description": "DaSiWa's speech-to-video merge (v2, Dec 2025). Use with the Wan 2.2 S2V workflow and audio encoder.",
     "settings": "As the creator's page: distilled, few steps at CFG 1.", "vram": "24 GB+ (18.1 GB).", "license": "As DaSiWa.",
     "items": [civ(2511306, "WAN22-14B-S2V-DaSiWa-LittleDemon-fp8-v20.safetensors", "diffusion_models", "model"),
               {"hf": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors", "cat": "audio_encoders", "role": "audio encoder"},
               WAN_TE, WAN21_VAE]},
    {"id": "smoothmix-wan22", "name": "SmoothMix Wan 2.2 (I2V v2 + T2V v4)", "icon": "🌊", "task": "video", "family": "Wan (community)", "status": "community", "mature": True,
     "description": "DigitalPastel's SmoothMix, the most-downloaded Wan 2.2 merge overall (224k): smooth motion, realism and anime styles. Mature-capable.",
     "settings": "4-6 steps, CFG 1, euler / simple or uni_pc (e.g. 2 high + 4 low). I2V v2 does not bake in lightx2v: the showcases use the I2V speed LoRA at 3.0 high / 1.5 low. T2V triggers: smoothmixrealism, smoothmixanime.",
     "vram": "16 GB+ (14.2-15.7 GB per expert).", "license": "Civitai terms.",
     "items": [civ(2513182, "SmoothMix_I2V_High_v2.safetensors", "diffusion_models", "I2V high-noise expert"),
               civ(2513186, "SmoothMix_I2V_Low_v2.safetensors", "diffusion_models", "I2V low-noise expert"),
               civ(3138094, "SmoothMix_T2V_High_v4.safetensors", "diffusion_models", "T2V high-noise expert"),
               civ(3138091, "SmoothMix_T2V_Low_v4.safetensors", "diffusion_models", "T2V low-noise expert"),
               WAN_TE, WAN21_VAE, *WAN_I2V_LIGHT]},
    {"id": "wan22-remix", "name": "Wan2.2-Remix I2V v3", "icon": "🔁", "task": "video", "family": "Wan (community)", "status": "community", "mature": True,
     "description": "FX_FeiHou's Remix (140k downloads), lightning built in; v3.0 is the final I2V release. Uncensored / mature-oriented (the file names say NSFW).",
     "settings": "4-8 steps, CFG 1, euler / simple, shift 5-10.", "vram": "16 GB+ (14 GB per expert).", "license": "Civitai terms.",
     "items": [civ(2770795, "Wan2.2_Remix_NSFW_i2v_14b_high_lighting_fp8_e4m3fn_v3.0.safetensors", "diffusion_models", "high-noise expert"),
               civ(2771407, "Wan2.2_Remix_NSFW_i2v_14b_low_lighting_fp8_e4m3fn_v3.0.safetensors", "diffusion_models", "low-noise expert"),
               WAN_TE, WAN21_VAE]},

    # ===== Video: other current models =====
    {"id": "ltx-2.5", "name": "LTX-2.5 (video + audio)", "icon": "🎞️", "task": "video", "family": "LTX", "status": "current",
     "description": "Lightricks' 22B LTX-2.5 (Aug 2026): text/image/first-last-frame to video with synchronised audio, two-stage with a 2x latent upscaler. Gated: accept the licence on Hugging Face and add an HF token.",
     "template": "video_ltx2_5_t2v, video_ltx2_5_i2v, video_ltx2_5_flf2v",
     "settings": "Distilled two-stage: euler_ancestral, CFG 1, the template's ManualSigmas (8 + 3 steps), 768x512, 97 frames, 24 fps; the spatial upscaler doubles resolution.",
     "vram": "24 GB+ (21.5 GB int8 transformer + 15.4 GB encoder, offloaded).", "license": "LTX-2.x Community Licence (gated; read before commercial use).",
     "items": [{"hf": "Lightricks/LTX-2.5/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "cat": "diffusion_models", "role": "model (distilled)"},
               {"hf": "Lightricks/LTX-2.5/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors", "cat": "text_encoders", "role": "text encoder (Gemma 4 12B)"},
               {"hf": "Comfy-Org/gemma-4/text_encoders/gemma4_e2b_it_int8_convrot.safetensors", "cat": "text_encoders", "role": "prompt enhancer (Gemma 4 E2B)"},
               {"hf": "Lightricks/LTX-2.5/vae/ltx-2.5-video-vae-bf16.safetensors", "cat": "vae", "role": "video VAE"},
               {"hf": "Lightricks/LTX-2.5/vae/ltx-2.5-audio-vae-bf16.safetensors", "cat": "vae", "role": "audio VAE"},
               {"hf": "Lightricks/LTX-2.5/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors", "cat": "latent_upscale_models", "role": "2x spatial upscaler"}]},
    {"id": "minimax-h3", "name": "MiniMax H3 (video + audio)", "icon": "🎦", "task": "video", "family": "MiniMax", "status": "current",
     "description": "MiniMax H3 open weights (Aug 2026): text/image/first-last-frame to video with audio, plus text-to-image. Native ComfyUI, with lightx2v's 8-step Turbo LoRA. Community LoRAs (tagged MH3) are appearing on Civitai.",
     "template": "video_minimax_h3_t2v, video_minimax_h3_i2v, image_minimax_h3_t2i",
     "settings": "Turbo LoRA: 4-8 steps, res_multistep / simple, CFG 1, 24 fps.",
     "vram": "24-32 GB (21 GB int8 model; the nvfp4 text encoder is fastest on RTX 50-series; an int8 encoder, 27 GB, is in the same repo).",
     "license": "MiniMax H3 Community Licence (check before commercial use).",
     "items": [{"hf": "Comfy-Org/MiniMax-H3/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors", "cat": "diffusion_models", "role": "model"},
               {"hf": "Comfy-Org/MiniMax-H3/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "cat": "text_encoders", "role": "text encoder (Qwen3-VL 32B nvfp4)"},
               {"hf": "Comfy-Org/MiniMax-H3/vae/minimax_h3_video_vae_int8_convrot.safetensors", "cat": "vae", "role": "video VAE"},
               {"hf": "Comfy-Org/MiniMax-H3/vae/minimax_h3_audio_vae_fp32.safetensors", "cat": "vae", "role": "audio VAE"},
               {"hf": "Comfy-Org/MiniMax-H3/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "cat": "loras", "role": "8-step Turbo LoRA"}]},
    {"id": "hunyuanvideo-1.5", "name": "HunyuanVideo 1.5 (720p T2V + I2V)", "icon": "🐉", "task": "video", "family": "Hunyuan", "status": "stable",
     "description": "Tencent's 8.3B HunyuanVideo 1.5: 720p text- and image-to-video with an optional 1080p super-resolution stage.",
     "template": "video_hunyuan_video_1.5_720p_t2v, video_hunyuan_video_1.5_720p_i2v",
     "settings": "20 steps (official 50), CFG 6, euler / simple, shift 7 (T2V 9 in the paper), 1280x720, 121 frames, 24 fps. SR stage: 1080p distilled + latent upsampler.",
     "vram": "24 GB recommended (16.7 GB fp16 models).", "license": "Tencent Hunyuan Community Licence (has territory and usage conditions; read before use).",
     "items": [{"hf": "Comfy-Org/HunyuanVideo_1.5_repackaged/split_files/diffusion_models/hunyuanvideo1.5_720p_t2v_fp16.safetensors", "cat": "diffusion_models", "role": "T2V model"},
               {"hf": "Comfy-Org/HunyuanVideo_1.5_repackaged/split_files/diffusion_models/hunyuanvideo1.5_720p_i2v_fp16.safetensors", "cat": "diffusion_models", "role": "I2V model"},
               {"hf": "Comfy-Org/HunyuanVideo_1.5_repackaged/split_files/diffusion_models/hunyuanvideo1.5_1080p_sr_distilled_fp16.safetensors", "cat": "diffusion_models", "role": "1080p super-resolution"},
               {"hf": "Comfy-Org/HunyuanVideo_1.5_repackaged/split_files/latent_upscale_models/hunyuanvideo15_latent_upsampler_1080p.safetensors", "cat": "latent_upscale_models", "role": "latent upsampler"},
               {"hf": "Comfy-Org/HunyuanVideo_1.5_repackaged/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", "cat": "text_encoders", "role": "text encoder"},
               {"hf": "Comfy-Org/HunyuanVideo_1.5_repackaged/split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors", "cat": "text_encoders", "role": "glyph encoder"},
               {"hf": "Comfy-Org/HunyuanVideo_1.5_repackaged/split_files/vae/hunyuanvideo15_vae_fp16.safetensors", "cat": "vae", "role": "VAE"},
               {"hf": "Comfy-Org/sigclip_vision_384/sigclip_vision_patch14_384.safetensors", "cat": "clip_vision", "role": "image encoder (I2V)"}]},
]


# ---- resolution -----------------------------------------------------------------------------
def _get(url, token=""):
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as r:
        return json.loads(r.read())


_hf_trees, _hf_info = {}, {}


def resolve_hf(spec):
    parts = spec["hf"].split("/")
    repo, path = "/".join(parts[:2]), "/".join(parts[2:])
    token = os.environ.get("HF_TOKEN", "")
    if repo not in _hf_trees:
        _hf_info[repo] = _get(f"https://huggingface.co/api/models/{repo}", token)
        files = _get(f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true", token)
        _hf_trees[repo] = {f["path"]: f for f in files if f["type"] == "file"}
    f = _hf_trees[repo].get(path)
    if not f:
        raise LookupError(f"{repo}: {path} not found")
    lfs = f.get("lfs") or {}
    info = _hf_info[repo]
    name = spec.get("filename") or os.path.basename(path)
    return {
        "source": "hf", "name": spec.get("role") or name, "filename": name,
        "url": f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(path)}",
        "category": spec["cat"], "size": int(lfs.get("size") or f.get("size") or 0), "sha256": lfs.get("oid", ""),
        "page_url": f"https://huggingface.co/{repo}", "base_model": "", "trigger_words": [],
        "hf": {"repo": repo, "revision": "main", "path": path},
        "gated": bool(info.get("gated")), "license": (info.get("cardData") or {}).get("license_name") or (info.get("cardData") or {}).get("license") or "",
    }


def resolve_civ(spec):
    v = _get(f"https://civitai.com/api/v1/model-versions/{spec['civ']}", os.environ.get("CIVITAI_TOKEN", ""))
    f = next((x for x in v.get("files", []) if x.get("name") == spec["file"]), None)
    if not f:
        raise LookupError(f"civitai version {spec['civ']}: no file {spec['file']!r} (has {[x.get('name') for x in v.get('files', [])]})")
    model = v.get("model") or {}
    return {
        "source": "civitai", "name": f"{model.get('name')} - {v.get('name')}", "filename": f["name"],
        "url": f.get("downloadUrl") or f"https://civitai.com/api/download/models/{spec['civ']}",
        "category": spec["cat"], "size": int(float(f.get("sizeKB") or 0) * 1024),
        "sha256": ((f.get("hashes") or {}).get("SHA256") or "").lower(),
        "page_url": f"https://civitai.com/models/{v.get('modelId')}?modelVersionId={spec['civ']}",
        "base_model": v.get("baseModel") or "", "trigger_words": [w for w in v.get("trainedWords") or [] if w],
        "civitai": {"model_id": v.get("modelId"), "version_id": int(spec["civ"]), "file_id": f.get("id")},
        "nsfw": bool(model.get("nsfw")),
    }


def build():
    out, errors, by_name = [], [], {}
    for pack in PACKS:
        models = []
        for spec in pack["items"]:
            try:
                cand = resolve_hf(spec) if "hf" in spec else resolve_civ(spec)
            except (LookupError, urllib.error.URLError, ValueError) as exc:
                errors.append(f"{pack['id']}: {exc}")
                continue
            cand["role"] = spec["role"]
            prev = by_name.setdefault(cand["filename"].lower(), cand)
            if prev["url"] != cand["url"] and prev["sha256"] and cand["sha256"] and prev["sha256"] != cand["sha256"]:
                errors.append(f"{pack['id']}: {cand['filename']} differs from the file of the same name at {prev['url']}")
            models.append({"filename": cand["filename"], "category": cand["category"], "role": spec["role"], "candidate": cand})
        meta = {k: v for k, v in pack.items() if k != "items"}
        meta["mature"] = bool(pack.get("mature"))
        meta["gated"] = any(m["candidate"].get("gated") for m in models)
        meta["total_bytes"] = sum(m["candidate"]["size"] for m in models)
        out.append({**meta, "models": models})
        print(f"{pack['id']:<22} {len(models):>2} files {meta['total_bytes'] / 1e9:7.1f} GB{'  gated' if meta['gated'] else ''}")
    if errors:
        print("\n".join(["", "ERRORS:"] + errors), file=sys.stderr)
        sys.exit(1)
    doc = {"generated_by": "tools/model_packs.py build", "about": "docs/model-packs.md",
           "usage": "POST any element of packs to /api/bundles/from-workflow, or run tools/model_packs.py install <id>.",
           "packs": out}
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"\nWrote {OUT}: {len(out)} packs")


def install(ids, dashboard, all_packs):
    packs = json.load(open(OUT))["packs"]
    chosen = packs if all_packs else [p for p in packs if p["id"] in ids]
    missing = set(ids) - {p["id"] for p in packs}
    if missing:
        sys.exit(f"Unknown pack(s): {', '.join(sorted(missing))}. Run `list`.")
    with urllib.request.urlopen(f"{dashboard}/api/bundles", timeout=60) as r:
        existing = {b.get("name") for b in json.loads(r.read())}
    for p in chosen:
        if p["name"] in existing:
            print(f"{p['name']}: already a bundle, skipped")
            continue
        body = json.dumps({"name": p["name"], "icon": p["icon"], "models": p["models"]}).encode()
        req = urllib.request.Request(f"{dashboard}/api/bundles/from-workflow", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read())
        res = res.get("data", res)
        bid = res["bundle"]["id"]
        desc = json.dumps({"description": f"{p['description']}\n\nSettings: {p.get('settings', '')}\nVRAM: {p.get('vram', '')}\nLicence: {p.get('license', '')}"}).encode()
        urllib.request.urlopen(urllib.request.Request(f"{dashboard}/api/bundles/{bid}", data=desc, method="PATCH",
                                                      headers={"Content-Type": "application/json"}), timeout=60).read()
        print(f"{p['name']}: {res['added']} added, {res['linked']} already in library")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="resolve every file and write docs/model-packs.json")
    sub.add_parser("list", help="list the packs in docs/model-packs.json")
    ins = sub.add_parser("install", help="add packs to a running dashboard as bundles")
    ins.add_argument("ids", nargs="*")
    ins.add_argument("--all", action="store_true")
    ins.add_argument("--dashboard", default="http://127.0.0.1:17890")
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "list":
        for p in json.load(open(OUT))["packs"]:
            flags = " ".join(f for f, on in (("mature", p["mature"]), ("gated", p["gated"])) if on)
            print(f"{p['id']:<22} {p['total_bytes'] / 1e9:6.1f} GB  {p['task']:<10} {p['name']}  {flags}")
    else:
        if not a.ids and not a.all:
            ap.error("name at least one pack id, or --all")
        install(a.ids, a.dashboard.rstrip("/"), a.all)


if __name__ == "__main__":
    main()
