"""Paths, environment and model-category definitions."""
import os
from pathlib import Path


def env(name, default=None):
    """The COMFORTABLE_<name> environment variable, or default."""
    return os.environ.get(f"COMFORTABLE_{name}") or default


# COMFORTABLE_WORKSPACE lets the dashboard run outside a Vast instance for development.
WORKSPACE = Path(env("WORKSPACE", "/workspace"))
COMFY_DIR = WORKSPACE / "ComfyUI"
MODELS_DIR = COMFY_DIR / "models"
OUTPUT_DIR = COMFY_DIR / "output"
DATA_DIR = WORKSPACE / ".comfortable"
STAGING_DIR = DATA_DIR / "staging"
THUMB_DIR = DATA_DIR / "thumbs"
LOCAL_DB = DATA_DIR / "comfortable.db"
ENV_FILE = WORKSPACE / ".comfortable.env"
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# The curated "Suggested by AI" catalog shipped with this version (see catalog/README.md).
CATALOG_DIR = Path(env("CATALOG_DIR", str(Path(__file__).resolve().parents[2] / "catalog")))

# Optional Vast volume holding the model folders (survives destroying the instance).
MODEL_VOLUME = Path(env("MODEL_VOLUME")) if env("MODEL_VOLUME") else None

PORT = int(env("PORT", "17890"))
# Port 8188 is Vast's authenticated Caddy proxy; ComfyUI itself listens on 18188.
COMFY_URL = (os.environ.get("COMFYUI_API_BASE") or "http://127.0.0.1:18188").rstrip("/")

MONGO_URI = (os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL") or "").strip()
MONGO_DB = env("MONGO_DB", "comfortable")
DISCORD_WEBHOOK_ENV = (os.environ.get("DISCORD_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()

# Vast injects these into every container; used for the instance cost readout.
VAST_CONTAINER_ID = os.environ.get("CONTAINER_ID", "").strip()
VAST_API_KEY = os.environ.get("CONTAINER_API_KEY", "").strip()

MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".sft")
PARTIAL_EXTS = (".aria2", ".part", ".tmp", ".crdownload", ".incomplete")

# Folder name, label, and whether it is shown by default (the rest live under "More").
CATEGORIES = [
    ("checkpoints", "Checkpoints", True),
    ("diffusion_models", "Diffusion models", True),
    ("loras", "LoRAs", True),
    ("text_encoders", "Text encoders", True),
    ("vae", "VAE", True),
    ("controlnet", "ControlNet", True),
    ("upscale_models", "Upscalers", True),
    ("embeddings", "Embeddings", True),
    ("clip_vision", "CLIP vision", True),
    ("unet", "UNet (old folder name)", False),
    ("clip", "CLIP (old folder name)", False),
    ("audio_encoders", "Audio encoders", False),
    ("background_removal", "Background removal", False),
    ("configs", "Configs", False),
    ("detection", "Detection", False),
    ("diffusers", "Diffusers", False),
    ("frame_interpolation", "Frame interpolation", False),
    ("geometry_estimation", "Geometry estimation", False),
    ("gligen", "GLIGEN", False),
    ("hypernetworks", "Hypernetworks", False),
    ("ipadapter", "IP-Adapter", False),
    ("latent_upscale_models", "Latent upscalers", False),
    ("model_patches", "Model patches", False),
    ("optical_flow", "Optical flow", False),
    ("photomaker", "PhotoMaker", False),
    ("sams", "SAM", False),
    ("style_models", "Style models", False),
    ("ultralytics", "Ultralytics detectors", False),
    ("vae_approx", "VAE approx", False),
]
CATEGORY_NAMES = [c[0] for c in CATEGORIES]

# Folder names people (and Civitai) use that are not ComfyUI folders.
CATEGORY_ALIASES = {
    "lora": "loras", "locon": "loras", "lycoris": "loras", "dora": "loras",
    "checkpoint": "checkpoints", "ckpt": "checkpoints",
    "embedding": "embeddings", "textualinversion": "embeddings",
    "upscaler": "upscale_models", "upscale": "upscale_models",
    "text_encoder": "text_encoders", "textencoder": "text_encoders",
    "diffusion_model": "diffusion_models",
    "controlnets": "controlnet",
}
# Folders ComfyUI reads as one: a model in unet/ is found by the same loaders as diffusion_models/.
SAME_FOLDER = {"unet": "diffusion_models", "clip": "text_encoders"}


def normalize_category(value, default="loras"):
    v = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if v in CATEGORY_NAMES:
        return v
    return CATEGORY_ALIASES.get(v, default)


def canonical_category(value):
    """The folder ComfyUI really uses for a category: unet -> diffusion_models, clip -> text_encoders."""
    c = normalize_category(value, default="")
    return SAME_FOLDER.get(c, c)


def same_folder(a, b):
    return bool(a and b) and canonical_category(a) == canonical_category(b)


def staging_root(target):
    """Staging folder on the same filesystem as target, so the final move is an atomic rename."""
    if MODEL_VOLUME and MODEL_VOLUME.is_dir():
        try:
            if Path(target).resolve().is_relative_to(MODEL_VOLUME.resolve()):
                return MODEL_VOLUME / ".comfortable-staging"
        except (OSError, ValueError):
            pass
    return STAGING_DIR


def ensure_dirs():
    for d in (DATA_DIR, STAGING_DIR, THUMB_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for name in CATEGORY_NAMES:
        (MODELS_DIR / name).mkdir(parents=True, exist_ok=True)
