import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import json

from orderflow_edge_lab.public_strategy_shadow import Bar
from orderflow_edge_lab.public_bot_batch2 import indicators, extension_indicators, execute, portfolio, smooth, build


def candles(n=260):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [Bar(start + timedelta(hours=8 * i), 100 + i / 10, 102 + i / 10,
                98 + i / 10, 101 + i / 10, 1000) for i in range(n)]


class PublicBotBatch2Tests(TestCase):
    def test_prefix_invariance_after_arbitrary_future_change(self):
        bars = candles()
        prefix = indicators(bars[:220])
        altered = bars[:220] + [Bar(b.timestamp, b.open * 3, b.high * 3, b.low * 3,
                                   b.close * 3, b.volume * 20) for b in bars[220:]]
        full = indicators(altered)
        for key in prefix:
            self.assertEqual(prefix[key], full[key][:220], key)

    def test_sma_seed_and_wilder_recursion_hand_calculation(self):
        self.assertEqual(smooth([None, 1, 2, 3, 9], 3, wilder=True), [None, None, None, 2, 13 / 3])

    def test_extension_prefix_causality_and_constant_price_zero_deviation(self):
        bars = candles()
        prefix = extension_indicators(bars[:220])
        full = extension_indicators(bars)
        for key in prefix:
            self.assertEqual(prefix[key], full[key][:220], key)
        constant = [Bar(b.timestamp, 100, 100, 100, 100, 1) for b in bars]
        flat = extension_indicators(constant)
        self.assertEqual(flat["cci200"][-1], 0)
        self.assertEqual(flat["rsi2"][-1], 0)

    def test_rsi2_wilder_gain_loss_from_known_price_path(self):
        prices = [100, 99, 101, 100, 104]
        bars = [Bar(b.timestamp, p, p + 1, p - 1, p, 100) for b, p in zip(candles(5), prices)]
        values = extension_indicators(bars)["rsi2"]
        self.assertIsNone(values[1])
        self.assertAlmostEqual(values[2], 100 * 1 / 1.5)
        self.assertAlmostEqual(values[3], 100 * .5 / 1.25)
        self.assertAlmostEqual(values[4], 100 * 2.25 / 2.625)

    def test_entry_exit_next_open_and_no_same_decision_reentry(self):
        bars = candles(8)
        spec = {"warmup_bars": 1, "max_hold_bars": 3, "baseline_round_trip_bps": 40}
        with patch("orderflow_edge_lab.public_bot_batch2.rules", return_value=(True, True)):
            result = execute("ASDTSRockwellTrading", "A", bars, bars, {}, spec)
        self.assertEqual([r["entry_index"] for r in result["rows"]], [2, 4, 6])
        self.assertEqual([r["exit_index"] for r in result["rows"]], [3, 5, 7])
        self.assertEqual(result["pending"]["status"], "awaiting_next_open")
        self.assertEqual(len(result["signal_origin_times"]), len(result["rows"]) + result["overlap_skipped"] + 1)
        self.assertTrue(all(r["hold_bars"] == 1 for r in result["rows"]))
        self.assertTrue(all(r["excess_bps"] == 0 for r in result["rows"]))

    def test_timeout_uses_completed_bar_and_pending_mark_is_included(self):
        bars = candles(8)
        spec = {"warmup_bars": 1, "max_hold_bars": 3, "baseline_round_trip_bps": 40, "symbols": ["A"]}
        with patch("orderflow_edge_lab.public_bot_batch2.rules", return_value=(True, False)):
            result = execute("ASDTSRockwellTrading", "A", bars, bars, {}, spec)
        self.assertEqual(result["rows"][0]["entry_index"], 2)
        self.assertEqual(result["rows"][0]["exit_index"], 5)
        self.assertEqual(result["pending"]["entry_index"], 6)
        curve = portfolio(result["rows"], [result["pending"]], {"A": bars}, spec, 40)
        expected = (1 - .002) ** 3 * bars[5].open / bars[2].open * bars[-1].close / bars[6].open
        self.assertAlmostEqual(curve["return_pct"], (expected - 1) * 100)
        self.assertEqual(curve["pending_marked_symbols"], ["A"])

    def test_modified_definition_refused_before_source_read(self):
        root = Path(__file__).resolve().parents[1]
        spec = json.loads((root / "config/public_bot_batch2_v1.json").read_text())
        changed = copy.deepcopy(spec)
        changed["max_hold_bars"] = 31
        with self.assertRaisesRegex(ValueError, "immutable"):
            build(changed, root)
