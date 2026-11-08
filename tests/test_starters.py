"""tools/starters.py: chaining a LoRA into a template graph (root graphs and both subgraph styles)."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import starters  # noqa: E402

LORA = {"name": "style.safetensors", "url": "https://example.com/style.safetensors", "strength": 0.7, "title": "Style LoRA"}


def root_graph():
    return {"last_node_id": 3, "last_link_id": 2, "links": [[1, 1, 0, 2, 0, "MODEL"], [2, 1, 1, 3, 0, "CLIP"]], "nodes": [
        {"id": 1, "type": "CheckpointLoaderSimple", "pos": [0, 0], "size": [300, 100], "inputs": [],
         "outputs": [{"name": "MODEL", "type": "MODEL", "links": [1]}, {"name": "CLIP", "type": "CLIP", "links": [2]}],
         "widgets_values": ["model.safetensors"]},
        {"id": 2, "type": "KSampler", "inputs": [{"name": "model", "type": "MODEL", "link": 1}], "outputs": []},
        {"id": 3, "type": "CLIPTextEncode", "inputs": [{"name": "clip", "type": "CLIP", "link": 2}], "outputs": []}]}


def sub_graph(proxy):
    sg = {"id": "sg-1", "inputNode": {"id": -10, "bounding": [0, 0, 100, 60]}, "state": {"lastNodeId": 11, "lastLinkId": 101},
          "inputs": [{"id": "a", "name": "unet_name", "type": "COMBO", "linkIds": [101], "pos": [0, 20]}],
          "links": [{"id": 100, "origin_id": 10, "origin_slot": 0, "target_id": 11, "target_slot": 0, "type": "MODEL"},
                    {"id": 101, "origin_id": -10, "origin_slot": 0, "target_id": 10, "target_slot": 0, "type": "COMBO"}],
          "nodes": [{"id": 10, "type": "UNETLoader", "pos": [0, 0], "size": [300, 80],
                     "inputs": [{"name": "unet_name", "type": "COMBO", "widget": {"name": "unet_name"}, "link": 101}],
                     "outputs": [{"name": "MODEL", "type": "MODEL", "links": [100]}], "widgets_values": ["model.safetensors", "default"]},
                    {"id": 11, "type": "KSampler", "inputs": [{"name": "model", "type": "MODEL", "link": 100}], "outputs": []}]}
    inst = {"id": 5, "type": "sg-1", "inputs": [], "outputs": [], "properties": {},
            "widgets_values": [] if proxy else ["model.safetensors"]}
    if proxy:
        inst["properties"]["proxyWidgets"] = [["10", "unet_name"]]
    return {"last_node_id": 5, "last_link_id": 0, "links": [], "nodes": [inst], "definitions": {"subgraphs": [sg]}}


class AddLora(unittest.TestCase):
    def test_root_checkpoint_gets_a_lora_loader_for_model_and_clip(self):
        wf = root_graph()
        nid = starters.add_lora(wf, {"after": "1", **LORA})
        node = next(n for n in wf["nodes"] if n["id"] == nid)
        self.assertEqual(node["type"], "LoraLoader")
        self.assertEqual(node["widgets_values"], ["style.safetensors", 0.7, 0.7])
        self.assertEqual(node["properties"]["models"][0]["url"], LORA["url"])
        links = {lk[0]: lk for lk in wf["links"]}
        # The sampler and the text encoder now read from the LoRA, which reads from the checkpoint.
        self.assertEqual(links[1][1:3], [nid, 0])
        self.assertEqual(links[2][1:3], [nid, 1])
        src = wf["nodes"][0]
        model_in, clip_in = (links[src["outputs"][0]["links"][0]], links[src["outputs"][1]["links"][0]])
        self.assertEqual(model_in[1:5], [1, 0, nid, 0])
        self.assertEqual(clip_in[1:5], [1, 1, nid, 1])
        self.assertEqual([o["links"] for o in node["outputs"]], [[1], [2]])
        self.assertEqual((wf["last_node_id"], wf["last_link_id"]), (nid, 4))

    def test_two_loras_chain_in_order(self):
        wf = root_graph()
        first = starters.add_lora(wf, {"after": "1", **LORA})
        second = starters.add_lora(wf, {"after": str(first), **LORA, "name": "b.safetensors"})
        links = {lk[0]: lk for lk in wf["links"]}
        self.assertEqual(links[1][1], second)  # the sampler reads from the last LoRA
        first_node = next(n for n in wf["nodes"] if n["id"] == first)
        self.assertEqual(links[first_node["outputs"][0]["links"][0]][3], second)

    def test_proxy_subgraph_shows_the_lora_as_promoted_widgets(self):
        wf = sub_graph(proxy=True)
        nid = starters.add_lora(wf, {"after": "10", **LORA})
        sg = wf["definitions"]["subgraphs"][0]
        node = next(n for n in sg["nodes"] if n["id"] == nid)
        self.assertEqual(node["type"], "LoraLoaderModelOnly")
        self.assertEqual(next(lk for lk in sg["links"] if lk["id"] == 100)["origin_id"], nid)
        self.assertEqual(wf["nodes"][0]["properties"]["proxyWidgets"][-2:], [[str(nid), "lora_name"], [str(nid), "strength_model"]])
        self.assertEqual(wf["nodes"][0]["widgets_values"], [])
        self.assertGreaterEqual(sg["state"]["lastLinkId"], max(lk["id"] for lk in sg["links"]))

    def test_widget_input_subgraph_gets_new_inputs_with_values_on_the_node(self):
        wf = sub_graph(proxy=False)
        nid = starters.add_lora(wf, {"after": "10", **LORA})
        sg, inst = wf["definitions"]["subgraphs"][0], wf["nodes"][0]
        self.assertEqual([i["name"] for i in sg["inputs"]], ["unet_name", "lora_name", "strength_model"])
        self.assertEqual(inst["widgets_values"], ["model.safetensors", "style.safetensors", 0.7])
        self.assertNotIn("proxyWidgets", inst["properties"])
        node = next(n for n in sg["nodes"] if n["id"] == nid)
        for slot, (name, inp) in enumerate([("lora_name", 1), ("strength_model", 2)], start=1):
            lid = node["inputs"][inp]["link"]
            lk = next(lk for lk in sg["links"] if lk["id"] == lid)
            self.assertEqual((lk["origin_id"], lk["origin_slot"], lk["target_id"], lk["target_slot"]), (-10, slot, nid, inp))
            self.assertEqual(sg["inputs"][slot]["linkIds"], [lid])
        self.assertEqual([i["name"] for i in inst["inputs"]], ["lora_name", "strength_model"])

    def test_optional_slot_is_added_bypassed(self):
        wf = root_graph()
        nid = starters.add_lora(wf, {"after": "1", **LORA, "mode": 4})
        self.assertEqual(next(n for n in wf["nodes"] if n["id"] == nid)["mode"], 4)

    def test_unknown_node_is_an_error(self):
        with self.assertRaises(SystemExit):
            starters.add_lora(root_graph(), {"after": "99", **LORA})

    def test_build_applies_loras_after_node_changes(self):
        base = root_graph()
        orig = starters.template
        starters.template = lambda name, local_dir=None: copy.deepcopy(base)
        try:
            wf = starters.build({"id": "x", "base": "t", "nodes": {"1": {"widgets": {"0": "other.safetensors"}}}, "loras": [{"after": "1", **LORA}]})
        finally:
            starters.template = orig
        self.assertEqual(wf["nodes"][0]["widgets_values"], ["other.safetensors"])
        self.assertEqual(sum(1 for n in wf["nodes"] if n["type"] == "LoraLoader"), 1)
        self.assertEqual(wf["extra"]["comfortable"], {"starter": "x", "base_template": "t"})


if __name__ == "__main__":
    unittest.main()
