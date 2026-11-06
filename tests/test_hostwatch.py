"""Offline tests for the during-jobs host watch (nvidia-smi output parsed from strings)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("COMFORTABLE_WORKSPACE", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from comfortable import hostwatch  # noqa: E402

NOW = 1_000_000.0


def samples(lines, start=NOW - 570):
    """One sample per WATCH_INTERVAL, ending at NOW."""
    return [hostwatch.parse(line, at=start + i * hostwatch.WATCH_INTERVAL) for i, line in enumerate(lines)]


HEALTHY = "0x0000000000000004, 71, 2700, 2850, 98"       # power cap only: normal at full load
THERMAL = "0x0000000000000020, 89, 1500, 2850, 99"       # thermal slowdown, clocks halved
LOW_CLOCK = "0x0000000000000000, 80, 1600, 2850, 97"     # no reason given, but clocks at 56%
IDLE_HOT = "0x0000000000000040, 90, 600, 2850, 3"        # throttled while idle: no job affected


class HostWatch(unittest.TestCase):
    def test_parse(self):
        s = hostwatch.parse(THERMAL, at=1)
        self.assertEqual(s["reasons"], ["thermal (software)"])
        self.assertEqual((s["temp"], s["util"]), (89, 99))
        self.assertAlmostEqual(s["clock_ratio"], 1500 / 2850)
        self.assertEqual(hostwatch.parse(HEALTHY)["reasons"], [])  # the power cap is not a slowdown
        self.assertIsNone(hostwatch.parse("garbage"))

    def test_healthy_host_at_its_power_limit_is_fine(self):
        self.assertIsNone(hostwatch.assess(samples([HEALTHY] * 20), at=NOW))

    def test_sustained_thermal_throttling_is_reported(self):
        f = hostwatch.assess(samples([HEALTHY] * 6 + [THERMAL] * 14), at=NOW)
        self.assertIsNotNone(f)
        self.assertIn("thermal (software)", f["warning"])
        self.assertIn("89 °C", f["warning"])
        self.assertEqual(f["slow_seconds"], 14 * hostwatch.WATCH_INTERVAL)

    def test_low_clocks_without_a_reason_are_reported(self):
        f = hostwatch.assess(samples([LOW_CLOCK] * 20), at=NOW)
        self.assertIn("clocks well below maximum", f["warning"])

    def test_brief_throttling_is_ignored(self):
        self.assertIsNone(hostwatch.assess(samples([HEALTHY] * 16 + [THERMAL] * 4), at=NOW))

    def test_throttling_while_idle_is_ignored(self):
        self.assertIsNone(hostwatch.assess(samples([IDLE_HOT] * 20), at=NOW))

    def test_old_samples_fall_out_of_the_window(self):
        old = samples([THERMAL] * 20, start=NOW - 5000)
        self.assertIsNone(hostwatch.assess(old + samples([HEALTHY] * 20), at=NOW))


if __name__ == "__main__":
    unittest.main()
