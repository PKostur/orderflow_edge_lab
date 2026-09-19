import importlib.util
import unittest
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fx_asian_range_breakout.py"
spec = importlib.util.spec_from_file_location("fxarb", SCRIPT)
fxarb = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fxarb)

class FxAsianRangeBreakoutTests(unittest.TestCase):
    def _base_day(self):
        h = {}
        for hour in range(17):
            h[hour] = {"o": 1.10, "h": 1.11, "l": 1.09, "c": 1.10}
        return h

    def test_long_signal_enters_next_hour_and_pays_friction(self):
        h = self._base_day()
        for hour in range(6):
            h[hour] = {"o": 1.10, "h": 1.20, "l": 1.00, "c": 1.10}
        h[6]["c"] = 1.15
        h[7]["c"] = 1.21
        h[8]["o"] = 1.21
        h[16]["o"] = 1.22
        rows = fxarb.evaluate_pair({date(2025, 1, 6): h}, "2025-01-01", "2025-01-31")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], 1)
        self.assertEqual(rows[0]["signal_hour"], 7)
        self.assertEqual(rows[0]["entry_hour"], 8)
        self.assertAlmostEqual(rows[0]["net2_bps"], rows[0]["gross_bps"] - 2.0, places=10)

    def test_missing_earlier_search_hour_invalidates_later_breakout(self):
        h = self._base_day()
        for hour in range(6):
            h[hour] = {"o": 1.10, "h": 1.20, "l": 1.00, "c": 1.10}
        del h[6]
        h[7]["c"] = 1.21
        rows = fxarb.evaluate_pair({date(2025, 1, 6): h}, "2025-01-01", "2025-01-31")
        self.assertEqual(rows, [])

    def test_short_signal_reversed_control_is_exact_direction_flip(self):
        h = self._base_day()
        for hour in range(6):
            h[hour] = {"o": 1.10, "h": 1.20, "l": 1.00, "c": 1.10}
        h[6]["c"] = 0.99
        h[7]["o"] = 0.99
        h[16]["o"] = 0.98
        rows = fxarb.evaluate_pair({date(2025, 1, 6): h}, "2025-01-01", "2025-01-31")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], -1)
        self.assertAlmostEqual(rows[0]["reversed_net2_bps"], -rows[0]["gross_bps"] - 2.0, places=10)

if __name__ == "__main__":
    unittest.main()
