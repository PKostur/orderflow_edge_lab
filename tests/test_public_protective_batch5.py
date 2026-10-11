import unittest
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from orderflow_edge_lab.public_protective_batch5 import CANDIDATES, bars8h, checked_spec, simulate, source_features, event_diagnostics, block_draws, randomized_flags


def fixture(blocks=4):
    values = np.column_stack([np.arange(blocks * 480, dtype=float) * 60, np.full(blocks * 480, 100.),
                              np.full(blocks * 480, 101.), np.full(blocks * 480, 99.),
                              np.full(blocks * 480, 100.), np.ones(blocks * 480)])
    return values


class ProtectiveBatch5Tests(unittest.TestCase):
    def setUp(self):
        self.spec = {"warmup_bars": 1, "episode_initial_cash_per_symbol": 1000, "max_symbol_histories": 64}
        self.data = fixture()
        self.candles = bars8h(self.data)
        self.features = {"long": np.array([True, False, False, False]), "short": np.zeros(4, dtype=bool),
                         "exit": np.zeros(4, dtype=bool), "atr": np.full(4, 5.), "stop_atr": 2.,
                         "target_atr": 2., "risk_fraction": .03}

    def test_aggregate_matches_hand_calculation_and_refuses_gap(self):
        self.data[3, 2], self.data[4, 3], self.data[479, 4] = 115, 80, 102
        candle = bars8h(self.data)[0]
        self.assertEqual(list(candle), [0, 100, 102, 115, 80, 480])
        self.data[8, 0] += 60
        with self.assertRaises(ValueError):
            bars8h(self.data)

    def test_pending_is_inventory_not_fictitious_sale(self):
        state = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")[0]
        self.assertEqual(state["counts"]["accepted_entries"], 1)
        self.assertEqual(state["events"][0]["status"], "CENSORED_MTM")
        self.assertIsNone(state["events"][0]["exit_interval"])
        self.assertEqual(state["position"]["quantity"], 3)
        self.assertAlmostEqual(state["cash"], 699.4)
        self.assertAlmostEqual(state["nav"][-1], 998.8)
        self.assertAlmostEqual(state["btc_nav_lower"][-1], state["nav"][-1])
        self.assertAlmostEqual(state["btc_nav_upper"][-1], state["nav"][-1])

    def test_both_touch_forks_cash_and_all_later_history(self):
        self.data[481, 2:4] = [115, 85]
        self.candles = bars8h(self.data)
        states = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")
        self.assertEqual(len(states), 2)
        self.assertEqual(sorted(s["events"][0]["endpoint_reference_price"] for s in states), [90, 110])
        self.assertEqual(sorted(round(s["cash"], 2) for s in states), [968.86, 1028.74])
        self.assertTrue(all(len(s["nav"]) == 4 and s["position"] is None for s in states))
        self.assertTrue(all(s["events"][0]["exit_interval"] == ["1970-01-01T08:01:00Z", "1970-01-01T08:02:00Z"] for s in states))

    def test_branch_limit_fails_closed(self):
        self.data[481, 2:4] = [115, 85]
        self.candles = bars8h(self.data)
        self.spec["max_symbol_histories"] = 1
        with self.assertRaisesRegex(ValueError, "HISTORY_LIMIT_EXCEEDED"):
            simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")

    def test_source_exit_at_next_open_does_not_use_later_extremes(self):
        self.features["exit"][1] = True
        self.data[960, 1:5] = [102, 500, 1, 300]
        self.candles = bars8h(self.data)
        state = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")[0]
        self.assertEqual(state["events"][0]["endpoint_minute_index"], 960)
        self.assertEqual(state["events"][0]["endpoint_reference_price"], 102)
        self.assertAlmostEqual(state["events"][0]["mfe_bps_bounds"][1], 200)

    def test_fee_reserved_quantity_rejects_gap_without_resizing(self):
        self.features["risk_fraction"] = None
        self.data[480, 1:5] = [102, 103, 101, 102]
        self.candles = bars8h(self.data)
        state = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[1], self.spec, 40, "conservative_limit")[0]
        self.assertEqual(state["counts"]["cash_rejected"], 1)
        self.assertEqual(state["cash"], 1000)
        self.assertEqual(state["events"], [])

    def test_cutoff_flag_is_unexecuted_without_debit(self):
        self.features["long"][:] = False
        self.features["long"][-1] = True
        state = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")[0]
        self.assertEqual(state["counts"], {"raw_entry_flags": 1, "unexecuted_final_entry": 1})
        self.assertEqual(state["cash"], 1000)

    def test_controls_do_not_replace_original_bracket_update_condition(self):
        self.features["long"][1] = True
        self.features["atr"][1] = 8
        random_flags = np.array([True, False, False, False])
        state = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[1], self.spec, 40,
                         "conservative_limit", entry_flags=random_flags)[0]
        self.assertEqual(state["counts"]["bracket_replacements"], 1)
        self.assertEqual(state["position"]["stop"], 84)

    def test_adverse_entry_gap_charges_entry_and_protective_exit(self):
        self.data[480, 1:5] = [80, 85, 75, 82]
        self.candles = bars8h(self.data)
        state = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")[0]
        self.assertEqual(state["events"][0]["reason"], "stop_gap")
        self.assertEqual(state["events"][0]["holding_minutes_to_endpoint"], 0)
        self.assertAlmostEqual(state["cash"], 999.04)

    def test_misaligned_benchmark_and_unregistered_model_refused(self):
        btc = self.data.copy()
        btc[480, 0] += 60
        with self.assertRaisesRegex(ValueError, "unaligned"):
            simulate(self.data, btc, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "guaranteed_fill")

    def test_ichimoku_feature_prefix_invariance_and_flat_abstention(self):
        spec = {"ichimoku": {"tenkan": 9, "kijun": 26, "span_b": 52, "atr_period": 14, "stop_atr": 3, "target_atr": 2}}
        data = fixture(80)
        candles = bars8h(data)
        candles[:, 2] += np.sin(np.arange(80)) * 2
        candles[:, 3] = np.maximum(candles[:, 3], candles[:, 2])
        candles[:, 4] = np.minimum(candles[:, 4], candles[:, 2])
        full = source_features(candles, CANDIDATES[1], spec)
        prefix = source_features(candles[:63], CANDIDATES[1], spec)
        for key in ("long", "short", "exit", "atr"):
            np.testing.assert_equal(prefix[key], full[key][:63])
        flat = source_features(bars8h(data), CANDIDATES[1], spec)
        self.assertFalse(flat["long"].any())
        self.assertFalse(flat["short"].any())

    def test_mutated_design_refused(self):
        repo = Path(__file__).resolve().parents[1]
        path = repo / "config/public_protective_batch5_v1.json"
        spec = json.loads(path.read_text())
        changed = deepcopy(spec)
        changed["warmup_bars"] = 200
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "changed.json"
            fake.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "changed frozen design"):
                checked_spec(repo, fake)

    def test_empty_calendar_weeks_do_not_count_as_entry_clusters(self):
        event = simulate(self.data, self.data, self.candles, self.features, CANDIDATES[0], self.spec, 40, "conservative_limit")[0]["events"][0]
        event.update(symbol="ETHUSDT", year=1970, month="1970-01", weekday=3, utc_hour=8,
                     btc_direction="flat", btc_volatility="low", entry_week="1969-12-29")
        spec = {**self.spec, "data_start": "1970-01-01T00:00:00Z", "data_end_exclusive": "1970-01-29T00:00:00Z",
                "bootstrap_calendar_block_weeks": 4, "bootstrap_replicates": 200, "symbols": ["ETHUSDT"]}
        result = event_diagnostics([event], spec, block_draws(spec, 42))
        self.assertEqual(result["entry_weeks"], 1)
        self.assertEqual(result["calendar_weeks_with_zeros"], 5)
        self.assertEqual(sum(result["entry_week_counts"].values()), 1)
        self.assertEqual(len(result["leave_week"]), 1)

    def test_randomized_flags_preserve_each_calendar_week_count(self):
        from datetime import datetime, timedelta, timezone
        candles = bars8h(fixture(100))
        flags = np.arange(100) % 4 == 0
        changed = randomized_flags(flags, candles, {"warmup_bars": 1}, np.random.default_rng(33))
        def counts(values):
            result = {}
            for i, value in enumerate(values):
                t = datetime.fromtimestamp(int(candles[i, 0] // 1000) + 28800, timezone.utc)
                week = (t - timedelta(days=t.weekday())).date().isoformat()
                result[week] = result.get(week, 0) + int(value)
            return result
        self.assertEqual(counts(flags), counts(changed))
        self.assertFalse(np.array_equal(flags, changed))


if __name__ == "__main__":
    unittest.main()
