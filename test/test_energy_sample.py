#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import energy_sample as es  # noqa: E402


STAT = (
    "1200 (chrome helper) S 1 1 1 0 -1 4194304 0 0 0 0 "
    "30 10 0 0 20 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
)


class ParseTest(unittest.TestCase):
    def test_parse_stat_comm_with_space(self):
        parsed = es.parse_stat(STAT)
        self.assertIsNotNone(parsed)
        pid, comm, ticks = parsed
        self.assertEqual(pid, 1200)
        self.assertEqual(comm, "chrome helper")
        self.assertEqual(ticks, 40)

    def test_parse_cpu_total(self):
        text = "cpu  10 0 10 80 0 0 0 0 0 0\ncpu0 5 0 5 40 0 0 0 0 0 0\n"
        total, idle = es.parse_cpu_total(text)
        self.assertEqual(total, 100)
        self.assertEqual(idle, 80)

    def test_group_and_attribute_share_of_all_ticks(self):
        first = {1: ("chrome", 10), 2: ("chrome", 5), 3: ("hyprland", 1)}
        second = {1: ("chrome", 30), 2: ("chrome", 15), 3: ("hyprland", 6)}
        grouped = es.group_deltas(first, second)
        self.assertEqual(grouped["chrome"]["ticks"], 30)
        self.assertEqual(grouped["chrome"]["n"], 2)
        self.assertEqual(grouped["hyprland"]["ticks"], 5)
        rows = es.attribute(grouped, total_delta=100, watts=10.0, limit=5)
        by_name = {r["name"]: r for r in rows}
        self.assertAlmostEqual(by_name["chrome"]["cpu"], 30.0)
        self.assertAlmostEqual(by_name["chrome"]["watts"], 3.0)
        self.assertAlmostEqual(by_name["hyprland"]["watts"], 0.5)

    def test_no_watts_without_source(self):
        grouped = {"chrome": {"name": "chrome", "ticks": 20, "n": 1}}
        rows = es.attribute(grouped, total_delta=100, watts=None)
        self.assertIsNone(rows[0]["watts"])
        self.assertAlmostEqual(rows[0]["cpu"], 20.0)

    def test_significant_only_on_battery(self):
        rows = [{"name": "chrome", "cpu": 40.0, "watts": 5.0, "n": 1}]
        self.assertTrue(es.significant(rows, 20.0, True))
        self.assertFalse(es.significant(rows, 20.0, False))

    def test_live_sample_emits_rows(self):
        result = es.sample(0.25)
        self.assertIn("source", result)
        self.assertIn("rows", result)
        self.assertIsInstance(result["rows"], list)


if __name__ == "__main__":
    unittest.main()
