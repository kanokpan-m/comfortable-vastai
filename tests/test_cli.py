"""Offline tests for tools/comfortable.py: workflow sizing, real-cost ranking, slow and bad host handling."""
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["COMFORTABLE_HOME"] = _tmp
_spec = importlib.util.spec_from_file_location("comfortable_cli", Path(__file__).resolve().parent.parent / "tools" / "comfortable.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def node(t, *values):
    return {"type": t, "widgets_values": list(values)}


def offer(oid, gpu, dlperf, dph, machine, mem_bw=1450, fee=0.003, ram=32768, up=0.004, power=None):
    return {"id": oid, "gpu_name": gpu, "dlperf": dlperf, "dph_total": dph, "machine_id": machine, "gpu_mem_bw": mem_bw,
            "inet_down_cost": fee, "inet_up_cost": up, "gpu_ram": ram, "reliability2": 0.99, "gpu_max_power": power}


class WorkflowNeeds(unittest.TestCase):
    def needs(self, nodes):
        return cli.workflow_needs({"nodes": nodes}, sizes={})

    def test_wan_14b_fp8_video(self):
        n = self.needs([node("UNETLoader", "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "default"),
                        node("UNETLoader", "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "default"),
                        node("CLIPLoader", "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "wan"),
                        node("VAELoader", "wan_2.1_vae.safetensors")])
        self.assertTrue(n["video"])
        self.assertEqual(n["min_vram_gb"], 20)
        self.assertEqual(n["comfortable_vram_gb"], 32)
        self.assertAlmostEqual(n["download_gb"], 34.0, delta=1)

    def test_sdxl_checkpoint(self):
        n = self.needs([node("CheckpointLoaderSimple", "juggernautXL_v9.safetensors"),
                        node("LoraLoader", "detail.safetensors", 1, 1)])
        self.assertFalse(n["video"])
        self.assertEqual(n["min_vram_gb"], 10)

    def test_gguf_quant_and_explicit_params(self):
        self.assertAlmostEqual(cli.estimate_size_gb("flux1-dev-Q4_K_S.gguf", "diffusion")[0], 6.7, delta=0.1)
        self.assertEqual(cli.estimate_size_gb("qwen_2.5_vl_7b_fp8_scaled.safetensors", "text")[0], 7.0)
        self.assertEqual(cli.estimate_size_gb("t5xxl_fp16.safetensors", "text")[0], 9.6)
        self.assertEqual(cli.estimate_size_gb("v1-5-pruned-emaonly-fp16.safetensors", "checkpoint")[0], 2.1)
        self.assertIsNone(cli.estimate_size_gb("mystery.safetensors", "other")[0])

    def test_minimum_and_maximum(self):
        n = cli.workflow_needs({"nodes": [
            {"type": "UNETLoader", "widgets_values": ["MiniMaxH3/model_14b_fp8.safetensors"]},
            {"type": "UpscaleModelLoader", "mode": 4, "widgets_values": ["2x-AnimeSharpV4_RCAN.safetensors"]},
            {"type": "UNETLoader", "widgets_values": ["MiniMaxH3/model_14b_fp8.safetensors"],
             "properties": {"models": [{"name": "model_14b_fp8.safetensors", "url": "https://x/model_14b_fp8.safetensors", "directory": "diffusion_models"},
                                       {"name": "other_20b_fp8.safetensors", "url": "https://x/o", "directory": "diffusion_models"}]}}]}, sizes={})
        names = {f["name"]: f["active"] for f in n["files"]}
        self.assertEqual(names, {"MiniMaxH3/model_14b_fp8.safetensors": True, "2x-AnimeSharpV4_RCAN.safetensors": False,
                                 "other_20b_fp8.safetensors": False})
        self.assertEqual(n["download_gb"], 14.0)
        self.assertAlmostEqual(n["download_gb_max"], 14.0 + 0.07 + 20.0, delta=0.1)

    def test_api_format_and_exact_sizes(self):
        wf = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "x.safetensors"}},
              "2": {"class_type": "KSampler", "inputs": {"seed": 1}}}
        n = cli.workflow_needs(wf, sizes={"x.safetensors": 23.8})
        self.assertEqual(n["files"][0]["how"], "exact")
        self.assertEqual(n["min_vram_gb"], 32)


class Ranking(unittest.TestCase):
    def setUp(self):
        self.offers = [
            offer(1, "RTX 5090", 200, 0.70, 11), offer(2, "RTX 5090", 199, 0.60, 12, fee=0.0156),
            offer(3, "RTX 5090", 99, 0.50, 13, mem_bw=712), offer(4, "RTX 5090", 201, 0.80, 14),
            offer(5, "RTX 5060 Ti", 38.4, 0.18, 15),
        ]

    def test_slow_hosts_hidden(self):
        ranked, hidden = cli.rank_offers([dict(o) for o in self.offers], [], download_gb=50, hours=4)
        self.assertNotIn(3, [o["id"] for o in ranked])
        self.assertEqual(hidden["slow"], 1)
        ranked, _ = cli.rank_offers([dict(o) for o in self.offers], [], allow_slow=True)
        self.assertIn(3, [o["id"] for o in ranked])

    def test_download_fee_counts(self):
        ranked, _ = cli.rank_offers([dict(o) for o in self.offers], [], download_gb=50, hours=4, max_download_per_tb=None)
        by = {o["id"]: o for o in ranked}
        self.assertAlmostEqual(by[2]["_fee"], 0.78, places=2)
        self.assertGreater(by[2]["_cost_h"], by[1]["_cost_h"])  # "cheaper" listing is dearer in practice

    def test_own_benchmark_overrides_estimate(self):
        ranked, _ = cli.rank_offers([dict(o) for o in self.offers], [{"gpu": "NVIDIA GeForce RTX 5090", "images_per_hour": 12000, "dlperf": 200}])
        by = {o["id"]: o for o in ranked}
        self.assertTrue(by[1]["_measured"])
        self.assertAlmostEqual(by[1]["_ips"], 12000, delta=100)
        self.assertFalse(by[5]["_measured"])

    def test_speed_vs_value(self):
        value, _ = cli.rank_offers([dict(o) for o in self.offers], [], mode="value")
        speed, _ = cli.rank_offers([dict(o) for o in self.offers], [], mode="speed")
        self.assertEqual([o["id"] for o in value], [o["id"] for o in sorted(value, key=lambda o: -o["_ipd"])])
        self.assertNotEqual(value[0]["id"], 4)  # the fastest 5090 is also the dearest, so not the best value
        self.assertEqual(speed[0]["id"], 4)  # fastest healthy 5090
        by = {o["id"]: o for o in speed}
        self.assertAlmostEqual(by[4]["_ips"] / by[5]["_ips"], 1.35 / .38, delta=0.05)

    def test_expensive_bandwidth_hidden(self):
        offers = [dict(o) for o in self.offers] + [offer(6, "RTX 5090", 200, 0.50, 16, fee=0.039)]  # $39/TB
        ranked, hidden = cli.rank_offers(offers, [], download_gb=20)
        self.assertNotIn(6, [o["id"] for o in ranked])
        self.assertEqual(hidden["bandwidth"], 2)  # offer 2 charges $15.6/TB too
        ranked, _ = cli.rank_offers([dict(o) for o in offers], [], max_download_per_tb=None)
        self.assertIn(6, [o["id"] for o in ranked])

    def test_expensive_upload_hidden_and_power_cap_scales_speed(self):
        offers = [offer(7, "RTX 5090", 200, 0.5, 17, up=0.05),                 # $50/TB upload
                  offer(8, "RTX 5090", 200, 0.5, 18, power=600), offer(9, "RTX 5090", 200, 0.5, 19, power=400)]
        ranked, hidden = cli.rank_offers(offers, [])
        by = {o["id"]: o for o in ranked}
        self.assertNotIn(7, by)
        self.assertEqual(hidden["bandwidth"], 1)
        self.assertAlmostEqual(by[9]["_power"], 400 / 600, places=3)
        self.assertAlmostEqual(by[9]["_ips"] / by[8]["_ips"], (400 / 600) ** cli.POWER_EXPONENT, places=3)

    def test_bad_hosts_skipped(self):
        ranked, hidden = cli.rank_offers([dict(o) for o in self.offers], [], bad={"11": {}})
        self.assertNotIn(1, [o["id"] for o in ranked])
        self.assertEqual(hidden["bad"], 1)


class Workloads(unittest.TestCase):
    def needs(self, *names):
        return cli.workflow_needs({"nodes": [node("CheckpointLoaderSimple", n) for n in names]}, sizes={})

    def test_workflow_family_is_detected(self):
        self.assertEqual(cli.workload_for(self.needs("flux1-dev-fp8.safetensors")), "flux")
        self.assertEqual(cli.workload_for(self.needs("juggernautXL_v9.safetensors")), "sdxl")
        self.assertEqual(cli.workload_for(self.needs("v1-5-pruned-emaonly.safetensors")), "sd15")
        self.assertIsNone(cli.workload_for(self.needs("mystery_model.safetensors")))
        video = cli.workflow_needs({"nodes": [node("UNETLoader", "wan2.2_t2v_14B_fp8_scaled.safetensors", "default")]}, sizes={})
        self.assertIsNone(cli.workload_for(video))

    def test_old_results_count_as_sd15(self):
        self.assertEqual(cli.workload_of({"test": "sd15-512-20steps-b4"}), "sd15")
        self.assertEqual(cli.workload_of({}), "sd15")
        self.assertEqual(cli.workload_of({"workload": "flux", "test": "flux-1024-20steps-b1"}), "flux")

    def test_ranking_uses_the_matching_workload(self):
        # SD 1.5 says the 4090 is the better value; on Flux the 5090's bandwidth wins.
        offers = lambda: [offer(1, "RTX 4090", 96, 0.40, 101), offer(2, "RTX 5090", 190, 0.60, 102, mem_bw=1790)]
        bench = [{"gpu": "RTX 4090", "images_per_hour": 9000, "workload": "sd15"},
                 {"gpu": "RTX 5090", "images_per_hour": 10000, "workload": "sd15"},
                 {"gpu": "RTX 4090", "images_per_hour": 100, "workload": "flux"},
                 {"gpu": "RTX 5090", "images_per_hour": 200, "workload": "flux"}]
        sd, h = cli.rank_offers(offers(), bench, workload="sd15")
        self.assertEqual((sd[0]["gpu_name"], h["workload"]), ("RTX 4090", "sd15"))
        fl, h = cli.rank_offers(offers(), bench, workload="flux")
        self.assertEqual((fl[0]["gpu_name"], h["workload"]), ("RTX 5090", "flux"))
        self.assertEqual(round(fl[0]["_ips"]), 200)

    def test_falls_back_to_sd15_without_matching_benchmarks(self):
        ranked, h = cli.rank_offers([offer(1, "RTX 4090", 96, 0.40, 101)], [], workload="sdxl")
        self.assertEqual(h["workload"], "sd15")
        self.assertGreater(ranked[0]["_ips"], 0)


class Go(unittest.TestCase):
    """comfortable go: rent (asks first), apply the fixer, wait, restart if packs came in, save into ComfyUI."""

    def run_go(self, answer="y", apply_result=None, extra=()):
        calls = []
        wf = Path(tempfile.mkdtemp()) / "My Flux workflow.json"
        wf.write_text(json.dumps({"nodes": [node("CheckpointLoaderSimple", "flux1-dev-fp8.safetensors")]}))
        offers = [dict(offer(1, "RTX 5090", 190, 0.6, 101), _hourly=0.6, _fee=0.1, _cost_h=0.63, _ips=300, _ipd=480,
                       _perf=1.0, _measured=True, inet_down=1000, disk_bw=3000, geolocation="X")]
        apply_result = apply_result or {"tasks": [{"id": "t"}], "moves": [], "packs": {}, "restart_needed": False}
        fakes = {
            "template": lambda: {"hash_id": "h"},
            "shared_data": lambda refresh=False: {"benchmarks": [], "hosts": []},
            "search_offers": lambda a, machine_id=None, bad=None, shared=None: (offers, {"slow": 0, "bad": 0, "workload": "flux"}),
            "vast": lambda *args, **kw: calls.append(("vast",) + args) or ({"new_contract": 900} if args[0] == "create" else ""),
            "wait_ready": lambda iid: {"id": iid},
            "wait_health": lambda inst: {"score": "good", "warnings": []},
            "show_status": lambda inst: None,
            "upload_workflow": lambda inst, path: calls.append(("upload", path)),
            "post_workflow": lambda inst, route, extra=None, timeout=180: calls.append(("post", route, extra)) or apply_result,
            "dash": lambda inst, path, method="GET", body=None, timeout=60: calls.append(("dash", path)) or ([] if path == "downloads" else {}),
            "ssh": lambda inst, cmd, timeout=60: calls.append(("ssh", cmd)) or "SAVED",
            "open_tunnel": lambda inst, port, browser=True: calls.append(("tunnel", port)),
        }
        saved = {k: getattr(cli, k) for k in fakes}
        for k, v in fakes.items():
            setattr(cli, k, v)
        import builtins
        real_input, builtins.input = builtins.input, lambda prompt="": answer
        argv, sys.argv = sys.argv, ["comfortable", "go", str(wf)] + list(extra)
        try:
            cli.main()
        except SystemExit:
            pass
        finally:
            sys.argv, builtins.input = argv, real_input
            for k, v in saved.items():
                setattr(cli, k, v)
        return calls

    def test_rents_sets_up_saves_and_opens(self):
        calls = self.run_go()
        kinds = [c[0] if c[0] != "post" else c[1] for c in calls]
        self.assertEqual(kinds[0], "vast")  # the rental
        self.assertLess(kinds.index("upload"), kinds.index("fix/apply"))
        self.assertIn(("post", "fix/apply", {"auto": True}), calls)
        save = next(c[1] for c in calls if c[0] == "ssh")
        self.assertIn("workflows%2FMy%20Flux%20workflow.json?overwrite=true", save)
        self.assertEqual(calls[-1][0], "tunnel")
        self.assertNotIn(("dash", "comfy/restart"), calls)  # no node packs: no restart

    def test_restarts_comfyui_after_node_packs(self):
        calls = self.run_go(apply_result={"tasks": [], "moves": [], "packs": {"kjnodes": "queued"}, "restart_needed": True})
        self.assertIn(("dash", "comfy/restart"), calls)

    def test_answering_no_rents_nothing(self):
        calls = self.run_go(answer="n")
        self.assertFalse([c for c in calls if c[0] == "vast" and c[1] == "create"])
        self.assertFalse([c for c in calls if c[0] in ("upload", "tunnel")])

    def test_no_tunnel(self):
        calls = self.run_go(extra=["--no-tunnel"])
        self.assertNotIn("tunnel", [c[0] for c in calls])


class GpuNames(unittest.TestCase):
    def test_driver_and_vast_names_match(self):
        pairs = [("NVIDIA RTX PRO 4000 Blackwell", "RTX PRO 4000"), ("NVIDIA GeForce RTX 5060 Ti", "RTX_5060_Ti"),
                 ("NVIDIA RTX 6000 Ada Generation", "RTX 6000Ada"), ("NVIDIA GeForce RTX 4080 SUPER", "RTX 4080S"),
                 ("NVIDIA A100-SXM4-80GB", "A100 SXM4"),
                 ("NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition", "RTX PRO 6000 Max-Q")]
        for driver, vast_name in pairs:
            self.assertEqual(cli.norm_gpu(driver), cli.norm_gpu(vast_name), driver)
        self.assertIn(cli.norm_gpu("RTX PRO 6000 Max-Q"), cli.RELATIVE_SPEED)
        self.assertIn(cli.norm_gpu("RTX 4070 Ti SUPER"), cli.RELATIVE_SPEED)


class BadHostMemory(unittest.TestCase):
    def test_remember_expire_and_forget(self):
        cli.save_json(cli.BAD_HOSTS_FILE, {"old": {"at": time.time() - 40 * 86400}})
        cli.remember_bad(777, "RTX 5090", "power limited")
        shared = {"hosts": [{"machine_id": 888, "score": "poor", "warnings": ["x4 PCIe"], "at": time.time()},
                            {"machine_id": 999, "score": "good", "warnings": [], "at": time.time()}]}
        bad = cli.bad_hosts(shared)
        self.assertEqual(set(bad), {"777", "888"})
        cli.shared_data = lambda refresh=False: shared
        cli.forget_bad("888")
        self.assertEqual(set(cli.bad_hosts(shared)), {"777"})


class AutoSwap(unittest.TestCase):
    """rent --auto-swap with Vast faked: the first host fails the check, the second passes."""

    def run_rent(self, auto_swap, healths, wait_ready=None, extra=()):
        calls, saved = [], {}
        offers = [dict(offer(i, "RTX 4090", 96, 0.5 + i / 100, 100 + i), _hourly=0.5, _fee=0.1, _cost_h=0.53, _ips=8900,
                       _ipd=16000, _perf=1.0, _measured=True, inet_down=1000, disk_bw=3000, geolocation="X") for i in (1, 2, 3)]
        fakes = {
            "template": lambda: {"hash_id": "h"},
            "shared_data": lambda refresh=False: {"benchmarks": [], "hosts": []},
            "search_offers": lambda a, machine_id=None, bad=None, shared=None: ([o for o in offers if str(o["machine_id"]) not in bad], {"slow": 0, "bad": 0}),
            "vast": lambda *args, **kw: calls.append(args) or ({"new_contract": 900 + len(calls)} if args[0] == "create" else ""),
            "wait_ready": wait_ready or (lambda iid: {"id": iid}),
            "wait_health": lambda inst: healths.pop(0),
            "dash": lambda *args, **kw: None,
            "show_status": lambda inst: None,
        }
        for k, v in fakes.items():
            saved[k] = getattr(cli, k)
            setattr(cli, k, v)
        try:
            cli.save_json(cli.BAD_HOSTS_FILE, {})
            args = ["rent", "--yes", "--gpu", "RTX_4090"] + (["--auto-swap"] if auto_swap else []) + list(extra)
            import sys
            argv, sys.argv = sys.argv, ["comfortable"] + args
            try:
                cli.main()
            finally:
                sys.argv = argv
        finally:
            for k, v in saved.items():
                setattr(cli, k, v)
        return calls

    def test_swaps_poor_host_and_remembers_it(self):
        poor = {"score": "poor", "warnings": ["Power limited to 60%"]}
        calls = self.run_rent(True, [poor, {"score": "good", "warnings": []}])
        self.assertEqual([c[:3] for c in calls], [("create", "instance", "1"), ("destroy", "instance", "901"), ("create", "instance", "2")])
        self.assertIn("101", cli.bad_hosts())

    def test_rent_installs_from_this_repo(self):
        calls = self.run_rent(False, [{"score": "good", "warnings": []}])
        env = calls[0][calls[0].index("--env") + 1]
        self.assertIn(f"-e PROVISIONING_SCRIPT={cli.PROVISIONING_URL}", env)
        self.assertIn(cli.REPO, cli.PROVISIONING_URL)

    def test_host_that_never_starts_is_swapped(self):
        def stuck_then_ok(iid, _n=[0]):
            _n[0] += 1
            if _n[0] == 1:
                raise cli.HostFailed("never started (still loading after 480 s)")
            return {"id": iid}
        calls = self.run_rent(True, [{"score": "good", "warnings": []}], wait_ready=stuck_then_ok)
        self.assertEqual([c[:3] for c in calls], [("create", "instance", "1"), ("destroy", "instance", "901"), ("create", "instance", "2")])
        self.assertIn("101", cli.bad_hosts())

    def test_offer_rents_exactly_that_offer(self):
        calls = self.run_rent(False, [{"score": "good", "warnings": []}], extra=["--offer", "2"])
        self.assertEqual([c[:3] for c in calls], [("create", "instance", "2")])

    def test_gone_offer_rents_nothing(self):
        with self.assertRaises(SystemExit):
            self.run_rent(True, [], extra=["--offer", "999"])

    def test_offer_never_swaps_to_an_unseen_host(self):
        calls = self.run_rent(True, [{"score": "poor", "warnings": ["x4 PCIe"]}], extra=["--offer", "1"])
        self.assertEqual([c[0] for c in calls], ["create"])

    def test_without_auto_swap_keeps_it(self):
        calls = self.run_rent(False, [{"score": "poor", "warnings": ["x4 PCIe"]}])
        self.assertEqual([c[0] for c in calls], ["create"])
        self.assertIn("101", cli.bad_hosts())


if __name__ == "__main__":
    unittest.main()
