"""Offline tests for auto-stop: idle vs. activity, budget cap, stop vs. destroy (Vast API faked)."""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from comfortable import autostop, backup, config, notify, store, system, workflowsync  # noqa: E402


class Downloads:
    running = 0
    tasks = {}


class AutoStop(unittest.TestCase):
    def setUp(self):
        config.LOCAL_DB = Path(tempfile.mkdtemp()) / "t.db"
        self.st = store.Store()
        self.calls = []
        self.cost = {"uptime": 3600, "dph": 0.5, "spent": 0.5}
        self.busy_gpu = 0
        self.pending = []
        fakes = {
            (system, "vast_instance"): self.fake_cost,
            (system, "snapshot"): self.fake_snapshot,
            (notify, "discord"): self.fake_discord,
            (autostop, "stop_instance"): lambda: self.record("stop"),
            (autostop, "destroy_instance"): lambda: self.record("destroy"),
            (backup, "run"): lambda st, reason: self.calls.append("backup"),
            (backup, "pending"): lambda: self.pending,
            (workflowsync, "sync_once"): lambda st: 0,
            (store.Store, "sync"): lambda st: True,
        }
        for (mod, name), fake in fakes.items():
            old = getattr(mod, name)
            setattr(mod, name, fake)
            self.addCleanup(setattr, mod, name, old)
        autostop._state.update(idle_since=time.time(), warned=False, stopping=False, snoozed_until=0.0,
                               last_activity=0.0, reason="", cost=None)

    async def fake_cost(self):
        return self.cost

    async def fake_snapshot(self):
        return {"comfy": {}, "gpus": [{"util": self.busy_gpu}]}

    async def fake_discord(self, *a, **kw):
        self.calls.append("discord")

    async def record(self, what):
        self.calls.append(what)

    def check(self):
        asyncio.run(autostop.check(self.st, Downloads()))

    def idle_for(self, minutes):
        autostop._state["idle_since"] = time.time() - minutes * 60

    def test_idle_warns_then_stops(self):
        self.st.update_settings({"auto_stop_minutes": 30})
        self.idle_for(26); self.check()
        self.assertTrue(autostop._state["warned"])
        self.assertNotIn("stop", self.calls)
        self.idle_for(31); self.check()
        self.assertEqual(self.calls[-1], "stop")

    def test_editing_in_comfyui_counts_as_activity(self):
        self.st.update_settings({"auto_stop_minutes": 30})
        self.idle_for(31)
        autostop.activity()
        self.check()
        self.assertNotIn("stop", self.calls)
        self.assertLess(time.time() - autostop._state["idle_since"], 5)

    def test_budget_cap_applies_even_when_busy(self):
        self.st.update_settings({"max_spend": 0.5})  # already spent $0.50
        self.busy_gpu = 95
        self.check()
        self.assertEqual(self.calls[-1], "stop")
        self.assertEqual(autostop._state["reason"], "budget")

    def test_budget_warns_five_minutes_ahead(self):
        self.st.update_settings({"max_hours": 1.05})  # uptime 1 h: 3 min left
        self.check()
        self.assertTrue(autostop._state["warned"])
        self.assertNotIn("stop", self.calls)
        self.assertLess(autostop.status(self.st)["budget_left"], 300)

    def test_snooze_does_not_lift_the_budget_cap(self):
        self.st.update_settings({"max_hours": 1})
        autostop.snooze(self.st, 60)
        self.check()
        self.assertEqual(self.calls[-1], "stop")

    def test_destroy_backs_up_first(self):
        self.st.update_settings({"auto_stop_minutes": 15, "auto_stop_action": "destroy",
                                 "backup_repo": "me/out", "hf_token": "hf_x"})
        self.idle_for(16); self.check()
        self.assertIn("destroy", self.calls)
        self.assertLess(self.calls.index("backup"), self.calls.index("destroy"))

    def test_destroy_falls_back_to_stop_when_outputs_are_not_backed_up(self):
        self.st.update_settings({"auto_stop_minutes": 15, "auto_stop_action": "destroy"})
        self.pending = [{"path": "out.png"}]  # outputs, and no backup configured
        self.idle_for(16); self.check()
        self.assertIn("stop", self.calls)
        self.assertNotIn("destroy", self.calls)

    def test_off_by_default(self):
        self.idle_for(600); self.check()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
