"""Offline tests for the Create screen's backend (dashboard/comfortable/create.py): forms from a starter's
saved prompt, values and LoRAs written into a copy, new seeds, the files a job made. ComfyUI is not needed.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))
from comfortable import create  # noqa: E402

PROMPT = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}, "_meta": {"title": "Load Checkpoint"}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red fox in the snow, detailed fur", "clip": ["4", 1]}, "_meta": {"title": "Positive prompt"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality, watermark", "clip": ["4", 1]}, "_meta": {"title": "Negative prompt"}},
    "7": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "_meta": {"title": "Empty Latent Image"}},
    "8": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 25, "cfg": 6.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                                               "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0]},
          "_meta": {"title": "KSampler"}},
    "9": {"class_type": "LoadImage", "inputs": {"image": "example.png"}, "_meta": {"title": "Start image"}},
    "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "test", "images": ["8", 0]}, "_meta": {"title": "Save Image"}},
}
INFO = {
    "KSampler": {"input": {"required": {"seed": ["INT", {"min": 0, "max": 2 ** 64}], "steps": ["INT", {"min": 1, "max": 10000}],
                                        "cfg": ["FLOAT", {"min": 0, "max": 100, "step": 0.1}], "sampler_name": [["euler", "dpmpp_2m"]],
                                        "scheduler": [["normal", "karras"]], "denoise": ["FLOAT", {"min": 0, "max": 1}]}}},
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["base.safetensors", "other.safetensors"]]}}},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {"multiline": True}]}}},
    "LoadImage": {"input": {"required": {"image": [["example.png"], {"image_upload": True}]}}},
}


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "workflows").mkdir()
        (self.dir / "workflows" / "t.api.json").write_text(json.dumps({"workflow": "t", "prompt": PROMPT, "controls": []}))
        self.saved_dir, create.config.CATALOG_DIR = create.config.CATALOG_DIR, self.dir
        create._cache.clear()

    def tearDown(self):
        create.config.CATALOG_DIR = self.saved_dir
        create._cache.clear()

    def test_form_finds_prompts_picture_seed_and_models(self):
        f = create.form("t", INFO)
        by = {x["key"]: x for x in f["fields"]}
        self.assertEqual(by["5|text"]["role"], "prompt")
        self.assertEqual(by["6|text"]["role"], "negative")
        self.assertEqual((by["9|image"]["kind"], by["9|image"]["media"]), ("media", "image"))
        self.assertEqual(by["8|seed"]["role"], "seed")
        self.assertEqual(by["8|steps"]["group"], "main")
        self.assertEqual(by["8|sampler_name"]["group"], "advanced")
        self.assertEqual(by["4|ckpt_name"]["group"], "model")
        self.assertEqual(by["4|ckpt_name"]["options"], ["base.safetensors", "other.safetensors"])
        self.assertNotIn("5|clip", by)  # wired inputs aren't settings
        self.assertEqual(f["lora_points"], 1)
        self.assertEqual(create.available(), ["t"])

    def test_build_writes_values_new_seeds_and_chains_loras(self):
        p = create.build("t", {"5|text": "a cat", "8|clip": "nope", "nope|x": 1}, [{"name": "a.safetensors", "strength": 0.7},
                                                                                  {"name": "b.safetensors"}])
        self.assertEqual(p["5"]["inputs"]["text"], "a cat")
        self.assertEqual(p["5"]["inputs"]["clip"], ["4", 1])  # links can't be overwritten
        self.assertNotEqual(p["8"]["inputs"]["seed"], 1)
        self.assertEqual(p["8"]["inputs"]["model"], ["phone-lora-2", 0])
        self.assertEqual(p["phone-lora-2"]["inputs"]["model"], ["phone-lora-1", 0])
        self.assertEqual(p["phone-lora-1"]["inputs"]["model"], ["4", 0])
        self.assertEqual(p["phone-lora-1"]["inputs"]["strength_model"], 0.7)
        self.assertEqual(PROMPT["8"]["inputs"]["model"], ["4", 0])  # the saved starter is untouched
        fixed = create.build("t", {"8|seed": 42}, new_seed=False)
        self.assertEqual(fixed["8"]["inputs"]["seed"], 42)

    def test_files_of_a_finished_job(self):
        files = create._files({"10": {"images": [{"filename": "a.png", "subfolder": "x", "type": "output"},
                                                {"filename": "p.png", "subfolder": "", "type": "temp"}]},
                               "11": {"audio": [{"filename": "s.mp3", "subfolder": "", "type": "output"}], "animated": [True]}})
        self.assertEqual([(f["filename"], f["path"]) for f in files], [("a.png", "x/a.png"), ("p.png", None), ("s.mp3", "s.mp3")])
        self.assertEqual(files[1]["view"], {"filename": "p.png", "subfolder": "", "type": "temp"})

    def test_view_refuses_paths_outside_comfyui(self):
        import asyncio
        for bad in ({"filename": "a.png", "subfolder": "../..", "type": "output"}, {"filename": "a.png", "type": "user"},
                    {"filename": "x/../a.png", "type": "output"}):
            with self.assertRaises(PermissionError):
                asyncio.run(create.view(bad))


if __name__ == "__main__":
    unittest.main()
