"""Offline tests for the spend report: accounting across dashboard restarts and container restarts."""
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
os.environ.setdefault("COMFORTABLE_HOME", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from comfortable import spend  # noqa: E402

_spec = importlib.util.spec_from_file_location("comfortable_cli_spend", Path(__file__).resolve().parent.parent / "tools" / "comfortable.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

PRICES = {"down_tb": 4.0, "up_tb": 10.0}
T0 = time.mktime((2026, 11, 6, 10, 0, 0, 0, 0, -1))


class Accounting(unittest.TestCase):
    def test_ticks_add_time_at_the_current_price(self):
        doc = {"id": "1"}
        spend.account(doc, T0 + 300, T0, (0, 0), 0.60, False, PRICES)
        spend.account(doc, T0 + 600, T0, (0, 0), 0.60, False, PRICES)
        self.assertAlmostEqual(doc["hours"], 600 / 3600)
        self.assertAlmostEqual(doc["cost"], 0.10)

    def test_dashboard_restart_continues_without_double_counting(self):
        doc = {"id": "1"}
        spend.account(doc, T0 + 300, T0, (5e9, 1e9), 0.60, False, PRICES)
        # Dashboard restarted 20 min later; same container, network counters kept running.
        spend.account(doc, T0 + 1500, T0, (6e9, 1e9), 0.60, False, PRICES)
        self.assertAlmostEqual(doc["hours"], 1500 / 3600)        # the gap counts: the instance was up
        self.assertEqual(doc["bytes_down"], 6e9)                  # not 5 + 6
        self.assertAlmostEqual(doc["bandwidth"], 6e9 / 1e12 * 4 + 1e9 / 1e12 * 10)

    def test_new_container_after_a_stop_starts_from_zero(self):
        doc = {"id": "1"}
        spend.account(doc, T0 + 3600, T0, (1e9, 0), 1.0, False, PRICES)
        # Stopped for a day, started again: new container, counters reset; the stopped day isn't GPU time.
        restart = T0 + 86400
        spend.account(doc, restart + 600, restart, (2e8, 0), 1.0, False, PRICES)
        self.assertAlmostEqual(doc["hours"], 1 + 600 / 3600)
        self.assertEqual(doc["bytes_down"], 1e9 + 2e8)

    def test_busy_time_goes_to_the_queued_workflow(self):
        doc = {"id": "1"}
        spend.account(doc, T0 + 1800, T0, (0, 0), 1.2, True, PRICES, "flux_portrait.json")
        spend.account(doc, T0 + 3600, T0, (0, 0), 1.2, False, PRICES, "flux_portrait.json")  # idle: not credited
        self.assertAlmostEqual(doc["workflows"]["flux_portrait.json"]["cost"], 0.6)
        self.assertAlmostEqual(doc["cost"], 1.2)

    def test_summary_per_day_instance_and_workflow(self):
        a, b = {"id": "1", "gpu": "RTX 5090", "last_seen": T0 + 7200}, {"id": "2", "gpu": "RTX 4090", "last_seen": T0 - 40 * 86400}
        spend.account(a, T0 + 3600, T0, (0, 0), 0.8, True, PRICES, "wan.json")
        spend.account(b, T0 - 40 * 86400 + 3600, T0 - 40 * 86400, (0, 0), 0.5, False, PRICES)
        s = spend.summary([a, b], days=30, at=T0 + 7200)
        self.assertEqual([i["id"] for i in s["instances"]], ["1"])  # b is older than 30 days
        self.assertAlmostEqual(s["total"]["cost"], 0.8)
        self.assertEqual(s["per_day"][0]["day"], "2026-11-06")
        self.assertEqual(s["workflows"][0]["workflow"], "wan.json")
        self.assertEqual(spend.summary([a, b], days=90, at=T0 + 7200)["total"]["cost"], 1.3)

    def test_cli_summary_matches_the_dashboard(self):
        a = {"id": "1", "gpu": "RTX 5090", "last_seen": T0 + 3600}
        spend.account(a, T0 + 3600, T0, (2e9, 0), 0.8, True, PRICES, "wan.json")
        dash, mine = spend.summary([a], 30, T0 + 3600), cli.spend_summary([a], 30, T0 + 3600)
        self.assertAlmostEqual(dash["total"]["cost"], mine["total"]["cost"])
        self.assertAlmostEqual(dash["total"]["bandwidth"], mine["total"]["bandwidth"])
        self.assertEqual(list(mine["workflows"]), ["wan.json"])


if __name__ == "__main__":
    unittest.main()
