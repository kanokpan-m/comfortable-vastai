"""Offline tests for the phone hub (tools/comfortable_hub.py): PIN, sessions, lockout, the rent and action
guards, the pass-through without an instance, and the backup folder. Vast is faked; nothing is rented.
Run: python -m unittest tests/test_hub.py   (needs: pip install "mcp>=2.3,<3" requests aiohttp)
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
os.environ.pop("COMFORTABLE_DASHBOARD_URL", None)
os.environ["COMFORTABLE_HUB_HOME"] = tempfile.mkdtemp()

import comfortable_hub as hub  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

M = hub.M


def config(pin="2468"):
    cfg = {}
    hub.set_pin(cfg, pin)
    return cfg


class Pin(unittest.TestCase):
    def test_pin_and_tokens(self):
        cfg = config()
        self.assertTrue(hub.check_pin(cfg, "2468"))
        self.assertFalse(hub.check_pin(cfg, "2469"))
        self.assertFalse(hub.check_pin(cfg, "12"))  # too short to be a PIN at all
        token = hub.make_token(cfg)
        self.assertTrue(hub.token_ok(cfg, token))
        self.assertFalse(hub.token_ok(cfg, token + "0"))
        self.assertFalse(hub.token_ok(cfg, token, now=time.time() + 40 * 86400))  # expired
        hub.set_pin(cfg, "1357")  # a new PIN signs everyone out
        self.assertFalse(hub.token_ok(cfg, token))

    def test_lockout_grows(self):
        lock = hub.Lockout()
        for _ in range(hub.MAX_TRIES - 1):
            lock.failed("1.2.3.4", now=100)
        self.assertEqual(lock.locked_for("1.2.3.4", now=100), 0)
        lock.failed("1.2.3.4", now=100)
        self.assertEqual(lock.locked_for("1.2.3.4", now=100), hub.LOCK_SECONDS)
        lock.failed("1.2.3.4", now=100)
        self.assertEqual(lock.locked_for("1.2.3.4", now=100), 2 * hub.LOCK_SECONDS)
        lock.passed("1.2.3.4")
        self.assertEqual(lock.locked_for("1.2.3.4", now=100), 0)

    def test_ready_estimate(self):
        self.assertEqual(hub.eta_minutes({"inet_down_mbps": 1000}, 0), 4)
        self.assertGreater(hub.eta_minutes({"inet_down_mbps": 200}, 40), hub.eta_minutes({"inet_down_mbps": 2000}, 40))


class BackupFolder(unittest.TestCase):
    def test_paths_stay_inside_and_listing_is_newest_first(self):
        b = hub.Backup(tempfile.mkdtemp())
        self.assertTrue(str(b.path_of("123/a/b.png")).startswith(str(b.dir.resolve())))
        for bad in ("../x.png", "123/../../x.png"):
            with self.assertRaises(PermissionError):
                b.path_of(bad)
        b.manifest = {"1/old.png": {"size": 1, "saved": 10}, "1/new.png": {"size": 2, "saved": 20}}
        b._count()
        listing = b.listing()
        self.assertEqual([i["path"] for i in listing["items"]], ["1/new.png", "1/old.png"])
        self.assertEqual((listing["count"], listing["bytes"]), (2, 3))


class Http(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = {name: getattr(M, name) for name in ("list_instances", "rent_gpu", "manage_instance", "get_conn", "wait_for_instance")}

        async def never_starts(ctx, iid, **kw):
            return {"state": "failed", "reason": "test"}
        M.wait_for_instance = never_starts
        M.list_instances = lambda with_health=False: {"instances": [{"id": 7, "gpu": "RTX 4090", "status": "running",
                                                                    "price_per_hour": 0.4, "uptime_hours": 2.0}]}
        M.get_conn = lambda *a, **k: None
        self.rented = []
        M.rent_gpu = lambda *a, **k: self.rented.append(a) or {"instance_id": 99, "gpu": "RTX 4090", "cost_per_hour": 0.4}
        M.manage_instance = lambda iid, action, confirm=False: {"instance_id": iid, "action": action}
        M.STATE["offers"].clear()
        M.STATE["conn"] = None
        app = hub.make_app(config())
        app["backup"] = hub.Backup(tempfile.mkdtemp())
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        hubobj = self.client.app["hub"]
        if hubobj.runner:
            hubobj.runner.cancel()
        await self.client.close()
        for name, fn in self.saved.items():
            setattr(M, name, fn)

    async def login(self, pin="2468"):
        return await self.client.post("/hub/login", json={"pin": pin})

    async def test_everything_private_needs_the_pin(self):
        r = await self.client.get("/hub/whoami")
        self.assertEqual((await r.json())["authed"], False)
        for path in ("/hub/state", "/api/bootstrap", "/comfy/view", "/hub/backups"):
            r = await self.client.get(path)
            self.assertEqual(r.status, 401, path)
        r = await self.login("1111")
        self.assertEqual(r.status, 401)
        r = await self.login()
        self.assertEqual(r.status, 200)
        r = await self.client.get("/hub/state")
        data = await r.json()
        self.assertEqual(data["instances"][0]["spent"], 0.8)
        self.assertIsNone(data["connected"])

    async def test_five_wrong_pins_lock_sign_in(self):
        for _ in range(hub.MAX_TRIES):
            await self.login("0000")
        r = await self.login()  # even the right PIN waits now
        self.assertEqual(r.status, 429)

    async def test_posts_must_be_json(self):
        await self.login()
        r = await self.client.post("/hub/rent", data="offer_id=1", headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 415)

    async def test_rent_needs_a_recent_offer_at_the_shown_price_and_a_confirmation(self):
        await self.login()
        r = await self.client.post("/hub/rent", json={"offer_id": 5, "cost_per_hour": 0.4})
        self.assertEqual(r.status, 400)  # no confirm
        r = await self.client.post("/hub/rent", json={"offer_id": 5, "cost_per_hour": 0.4, "confirm": True})
        self.assertEqual(r.status, 409)  # never shown
        M.STATE["offers"][5] = {"row": {"cost_per_hour": 0.45}, "at": time.time(), "for_setups": ["h3-t2v"]}
        r = await self.client.post("/hub/rent", json={"offer_id": 5, "cost_per_hour": 0.4, "confirm": True})
        self.assertEqual(r.status, 409)  # not the price the phone showed
        M.STATE["offers"][5]["at"] = time.time() - M.OFFER_TTL - 1
        r = await self.client.post("/hub/rent", json={"offer_id": 5, "cost_per_hour": 0.45, "confirm": True})
        self.assertEqual(r.status, 409)  # too old
        self.assertEqual(self.rented, [])
        M.STATE["offers"][5]["at"] = time.time()
        r = await self.client.post("/hub/rent", json={"offer_id": 5, "cost_per_hour": 0.45, "confirm": True, "autostop_minutes": 30})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.rented[0][:2], (5, True))
        self.assertEqual((await r.json())["task"]["setups"], ["h3-t2v"])

    async def test_instance_actions_need_a_confirmation(self):
        await self.login()
        r = await self.client.post("/hub/instances/7", json={"action": "destroy"})
        self.assertEqual(r.status, 400)
        r = await self.client.post("/hub/instances/7", json={"action": "destroy", "confirm": True})
        self.assertEqual((await r.json())["action"], "destroy")
        r = await self.client.post("/hub/instances/7", json={"action": "reboot", "confirm": True})
        self.assertEqual(r.status, 400)

    async def test_no_instance_means_503_not_a_hang(self):
        await self.login()
        r = await self.client.get("/api/bootstrap")
        self.assertEqual(r.status, 503)
        self.assertTrue((await r.json())["no_instance"])

    async def test_saved_files_are_served_and_contained(self):
        await self.login()
        b = self.client.app["backup"]
        f = b.path_of("1/out.png")
        f.parent.mkdir(parents=True)
        f.write_bytes(b"\x89PNG")
        b.manifest = {"1/out.png": {"size": 4, "saved": 1}}
        r = await self.client.get("/hub/backups/file", params={"path": "1/out.png"})
        self.assertEqual((r.status, await r.read()), (200, b"\x89PNG"))
        r = await self.client.get("/hub/backups/file", params={"path": "../hub.json"})
        self.assertEqual(r.status, 403)


if __name__ == "__main__":
    unittest.main()
