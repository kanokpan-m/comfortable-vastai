"""Offline tests for the MCP server (tools/comfortable_mcp.py) and the CLI's catalog helpers.

Vast and the dashboard are faked: nothing is rented and no network is used.
Run: python -m unittest tests/test_mcp.py   (needs: pip install "mcp>=2.3,<3" requests)
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
os.environ.pop("COMFORTABLE_DASHBOARD_URL", None)

import comfortable_mcp as m  # noqa: E402
from mcp import Client  # noqa: E402

cli = m.cli  # the CLI module the server uses (faked below); not the dashboard's `comfortable` package


def fake_offer(oid=42, cost=0.5, gpu="RTX 4090"):
    return {"id": oid, "machine_id": 1000 + oid, "gpu_name": gpu, "gpu_ram": 24 * 1024, "_cost_h": cost, "_hourly": cost - 0.05,
            "_fee": 0.05, "_dl_tb": 2.0, "_ul_tb": 4.0, "_power": 1.0, "gpu_max_power": 450, "_ips": 9000, "_measured": False,
            "_ipd": 18000, "_perf": 1.0, "inet_down": 1000, "disk_bw": 3000, "geolocation": "Sweden, SE"}


class McpCase(unittest.IsolatedAsyncioTestCase):
    """Each test starts offline (no dashboard, no instances) with Vast faked."""

    def setUp(self):
        self.saved = {}
        self.vast_calls = []
        self.offers = [fake_offer()]
        fakes = {
            "instances": lambda: [],
            "shared_data": lambda refresh=False: {"benchmarks": [], "hosts": []},
            "bad_hosts": lambda shared=None: {},
            "search_offers": lambda a, machine_id=None, bad=None, shared=None: (list(self.offers), {"slow": 0, "bad": 0, "bandwidth": 0}),
            "template": lambda: {"hash_id": "tmpl-hash"},
            "vast": self.fake_vast,
            "find_volume": lambda: None,
        }
        for name, fn in fakes.items():
            self.saved[name] = getattr(cli, name)
            setattr(cli, name, fn)
        m.STATE.update(conn=None, offers={}, rented={}, none_at=0)

    def tearDown(self):
        for name, fn in self.saved.items():
            setattr(cli, name, fn)
        m.STATE.update(conn=None, offers={}, rented={}, none_at=0)

    def fake_vast(self, *args, raw=True, check=True):
        self.vast_calls.append(args)
        if args[:2] == ("create", "instance"):
            return {"new_contract": 777}
        return "done" if not raw else []

    async def call(self, name, args=None):
        async with Client(m.server) as c:
            r = await c.call_tool(name, args or {})
        return r.is_error, (r.content[0].text if r.is_error else r.structured_content)


class Tools(McpCase):
    async def test_tool_list_and_annotations(self):
        async with Client(m.server) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
        for name in ("find_setups", "plan_install", "install_setups", "install_progress", "open_workflow", "check_workflow",
                     "fix_workflow", "find_gpu", "rent_gpu", "wait_for_instance", "manage_instance", "connect", "status"):
            self.assertIn(name, tools)
        self.assertTrue(tools["rent_gpu"].annotations.destructive_hint)
        self.assertTrue(tools["manage_instance"].annotations.destructive_hint)
        self.assertTrue(tools["find_gpu"].annotations.read_only_hint)
        self.assertTrue(tools["find_setups"].annotations.read_only_hint)
        self.assertFalse(tools["install_setups"].annotations.destructive_hint)
        self.assertTrue(all(t.output_schema for t in tools.values()), "every tool returns structured content")
        self.assertIn("confirm", tools["rent_gpu"].input_schema["properties"])

    async def test_find_setups_offline(self):
        err, out = await self.call("find_setups", {"query": "nsfw video", "limit": 5})
        self.assertFalse(err, out)
        self.assertEqual(out["source"], "local")
        ids = [r["id"] for r in out["results"]]
        self.assertTrue({"dasiwa-h3-i2v", "dasiwa-wan22-i2v"} & set(ids), ids)
        first = out["results"][0]
        self.assertTrue(first["download_gb"] > 1 and first["nsfw"])
        err, out = await self.call("find_setups")
        self.assertTrue(any(c["id"] == "nsfw-video" for c in out["categories"]))

    async def test_get_setup_and_plan_offline(self):
        err, wf = await self.call("get_setup", {"setup_id": "interpolate"})
        self.assertFalse(err, wf)
        self.assertEqual(wf["type"], "workflow")
        self.assertTrue(wf["steps"] and len(wf["files"]) == 2)
        err, plan = await self.call("plan_install", {"setup_ids": ["dasiwa-h3-i2v"]})
        self.assertFalse(err, plan)
        self.assertFalse(plan["connected"])
        self.assertGreater(plan["download_gb"], 30)
        self.assertTrue(plan["needs_civitai_key"])
        self.assertTrue(any(f["path"].startswith("diffusion_models/MiniMaxH3/") for f in plan["files"]))
        err, msg = await self.call("plan_install", {"setup_ids": ["dasiwa-h3-i2v", "no-such-thing"]})
        self.assertTrue(err)
        self.assertIn("no-such-thing", msg)

    async def test_check_workflow_offline_estimates_vram(self):
        wf = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea2_turbo_fp8_scaled.safetensors"}},
              "2": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}}}
        err, out = await self.call("check_workflow", {"workflow_json": wf})
        self.assertFalse(err, out)
        self.assertFalse(out["connected"])
        self.assertGreaterEqual(out["min_vram_gb"], 12)

    async def test_connected_tools_need_a_dashboard(self):
        err, msg = await self.call("install_setups", {"setup_ids": ["interpolate"]})
        self.assertTrue(err)
        self.assertIn("no running instance", msg)


class Renting(McpCase):
    async def find(self):
        err, out = await self.call("find_gpu", {"for_setups": ["dasiwa-h3-i2v"], "limit": 3})
        self.assertFalse(err, out)
        return out

    async def test_find_gpu_sizes_from_the_catalog(self):
        out = await self.find()
        self.assertEqual(out["offers"][0]["id"], 42)
        self.assertEqual(out["filters"]["min_vram_gb"], 24)
        self.assertGreater(out["filters"]["download_gb"], 30)
        self.assertEqual(self.vast_calls, [])  # searching rents nothing

    async def test_rent_refuses_unseen_offer_and_missing_confirm(self):
        err, msg = await self.call("rent_gpu", {"offer_id": 42, "confirm": True})
        self.assertTrue(err)
        self.assertIn("wasn't shown", msg)
        await self.find()
        err, msg = await self.call("rent_gpu", {"offer_id": 42})
        self.assertTrue(err)
        self.assertIn("Nothing rented", msg)
        self.assertEqual(self.vast_calls, [])

    async def test_rent_exactly_the_shown_offer_with_boot_install(self):
        await self.find()
        err, out = await self.call("rent_gpu", {"offer_id": 42, "confirm": True})
        self.assertFalse(err, out)
        self.assertEqual(out["instance_id"], 777)
        create = [c for c in self.vast_calls if c[:2] == ("create", "instance")]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0][2], "42")
        env = create[0][create[0].index("--env") + 1]
        self.assertIn("-e COMFORTABLE_INSTALL=dasiwa-h3-i2v", env)
        self.assertIn(f"-e PROVISIONING_SCRIPT={cli.PROVISIONING_URL}", env)
        err, msg = await self.call("rent_gpu", {"offer_id": 42, "confirm": True})
        self.assertTrue(err, "one approval rents once")

    async def test_rent_refuses_a_gone_or_pricier_offer(self):
        await self.find()
        self.offers = [fake_offer(cost=0.8)]
        err, msg = await self.call("rent_gpu", {"offer_id": 42, "confirm": True})
        self.assertTrue(err)
        self.assertIn("now costs", msg)
        self.offers = []
        err, msg = await self.call("rent_gpu", {"offer_id": 42, "confirm": True})
        self.assertTrue(err)
        self.assertIn("is gone", msg)
        self.assertFalse([c for c in self.vast_calls if c[:1] == ("create",)])

    async def test_manage_instance_needs_confirm_and_cli_errors_stay_tool_errors(self):
        original = cli.pick_instance
        cli.pick_instance = lambda iid: {"id": int(iid), "gpu_name": "RTX 4090", "actual_status": "running", "dph_total": 0.5}
        try:
            err, msg = await self.call("manage_instance", {"instance_id": 5, "action": "destroy"})
            self.assertTrue(err)
            self.assertIn("deletes its disk", msg)
            err, out = await self.call("manage_instance", {"instance_id": 5, "action": "destroy", "confirm": True})
            self.assertFalse(err, out)
            self.assertIn(("destroy", "instance", "5"), self.vast_calls)
            cli.pick_instance = lambda iid: cli.die(f"instance {iid} not found")
            err, msg = await self.call("manage_instance", {"instance_id": 6, "action": "stop", "confirm": True})
            self.assertTrue(err)
            self.assertIn("instance 6 not found", msg)
            err, out = await self.call("find_setups", {"query": "upscale"})  # the server is still alive
            self.assertFalse(err)
        finally:
            cli.pick_instance = original


class CatalogHelpers(unittest.TestCase):
    def test_requirements_come_first(self):
        cat = cli.catalog_data()
        order, wfs, unknown = cli.catalog_resolve(cat, "krea2-turbo")
        self.assertEqual(order[-1], "krea2-turbo")
        self.assertIn("krea2-core", order[:-1])
        self.assertEqual((wfs, unknown), ([], []))

    def test_unknown_ids_fail_before_renting(self):
        with self.assertRaises(SystemExit):
            cli.catalog_needs(cli.catalog_data(), ["interpolate", "nope"])
        saved = cli.template
        cli.template = lambda: {"hash_id": "h"}
        try:
            with self.assertRaises(SystemExit):
                cli.instance_env(install="interpolate,nope")
            with self.assertRaises(SystemExit):
                cli.instance_env(bundles="my bundle")
            env = cli.instance_env(bundles="a,b", install=["interpolate"], sets=["X=1"])
            self.assertEqual((env["COMFORTABLE_BUNDLES"], env["COMFORTABLE_INSTALL"], env["X"]), ("a,b", "interpolate", "1"))
        finally:
            cli.template = saved

    def test_search_filters(self):
        cat = cli.catalog_data()
        sfw = cli.catalog_search(cat, "pose", nsfw=False, limit=50)
        self.assertTrue(sfw and not any(r["nsfw"] for r in sfw))
        loras = cli.catalog_search(cat, "", kind="lora", category="artist", limit=50)
        self.assertTrue(loras and all(r["kind"] == "lora" and "artist" in r["categories"] for r in loras))
        self.assertFalse(any(r["kind"] == "component" for r in cli.catalog_search(cat, "", limit=500)))


if __name__ == "__main__":
    unittest.main()
