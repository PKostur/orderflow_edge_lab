import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.trend_core_positions import build_sheet, render_markdown

CFG = json.loads(Path("config/crypto_trend_core_v1.json").read_text(encoding="utf-8"))
COINS = [c for m in CFG["groups"].values() for c in m]
IDX = pd.date_range("2026-05-01T00:00:00Z", periods=500, freq="8h")


def frame(drift, seed, n=500):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.002,
                         "low": np.minimum(open_, close) * 0.998, "close": close}, index=IDX[:n])


def frames(up=(), down=()):
    return {c: frame(0.004 if c in up else (-0.004 if c in down else 0.0), k) for k, c in enumerate(COINS)}


class PositionSheetTests(unittest.TestCase):
    def test_trend_direction_sets_side_and_weight_is_sleeve_sum_over_34(self):
        f = frames(up=["BTC_USDT"], down=["ETH_USDT"])
        s = build_sheet(CFG, f, as_of=IDX[-1] + pd.Timedelta(hours=8), leverage=1.0, equity=10_000)
        rows = {r["coin"]: r for r in s["rows"]}
        self.assertEqual(rows["BTC_USDT"]["side"], "LONG")
        self.assertEqual(rows["ETH_USDT"]["side"], "SHORT")
        for r in s["rows"]:
            self.assertAlmostEqual(r["weight_1x"], sum(r["sleeves"].values()) / 34)
            self.assertLessEqual(max(abs(v) for v in r["sleeves"].values()), 1.0)

    def test_leverage_scales_notional_and_quantity(self):
        f = frames(up=["BTC_USDT"])
        a = build_sheet(CFG, f, as_of=IDX[-1] + pd.Timedelta(hours=8), leverage=1.0, equity=10_000)
        b = build_sheet(CFG, f, as_of=IDX[-1] + pd.Timedelta(hours=8), leverage=3.0, equity=10_000)
        ra, rb = a["rows"][COINS.index("BTC_USDT")], b["rows"][COINS.index("BTC_USDT")]
        self.assertAlmostEqual(rb["notional_usdt"], 3 * ra["notional_usdt"])
        self.assertAlmostEqual(rb["quantity"] * rb["reference_price"], rb["notional_usdt"])
        self.assertAlmostEqual(b["gross_exposure"], 3 * a["gross_exposure"])

    def test_bar_still_open_is_not_used(self):
        f = frames(up=["BTC_USDT"])
        s = build_sheet(CFG, f, as_of=IDX[-1] + pd.Timedelta(hours=7), leverage=1.0, equity=10_000)
        self.assertEqual(s["signal_bar_close_utc"], IDX[-1].isoformat())

    def test_matches_target_canonical_v3_enters_next_bar(self):
        from orderflow_edge_lab.universal_backtest import legacy_strategy
        from orderflow_edge_lab.vol_sizing import vol_sized_strategy
        f = frames(up=["SOL_USDT"])
        s = build_sheet(CFG, f, as_of=IDX[-1] + pd.Timedelta(hours=8), leverage=1.0, equity=1.0)
        z = CFG["sizing"]
        for spec in CFG["strategies"]:
            strat = vol_sized_strategy(legacy_strategy(spec["family"]), window=z["window_bars"],
                                       target_vol=z["target_annual_vol"], cap=z["cap"], bars_per_year=z["bars_per_year"])
            t = strat.generate_target(f["SOL_USDT"], spec["parameters"], None)
            self.assertAlmostEqual(s["rows"][COINS.index("SOL_USDT")]["sleeves"][spec["audit_id"]], float(t.iloc[-1]))

    def test_action_reflects_changes_in_the_last_24h(self):
        n = 400
        flat = {c: frame(0.0, k, n) for k, c in enumerate(COINS)}
        # a coin that starts trending up in the last bars: earlier sheet flat or different, later sheet long
        base = frame(0.0, 99, n)
        jump = base.copy()
        jump.iloc[-3:, :] = jump.iloc[-3:, :] * 1.25
        flat["ADA_USDT"] = jump
        s = build_sheet(CFG, flat, as_of=IDX[n - 1] + pd.Timedelta(hours=8), leverage=1.0, equity=10_000)
        r = s["rows"][COINS.index("ADA_USDT")]
        self.assertGreater(r["sleeves"]["DON8"], 0)                  # the breakout sleeve went long on the jump
        self.assertNotEqual(r["action"], "HOLD")
        self.assertTrue(r["changed_sleeves"])
        for row in s["rows"]:
            if not row["changed_sleeves"]:
                self.assertEqual(row["action"], "HOLD")
        self.assertIn("| ADA |", render_markdown(s))

    def test_missing_coin_is_an_error(self):
        f = frames()
        del f["BTC_USDT"]
        with self.assertRaises(ValueError):
            build_sheet(CFG, f, as_of=IDX[-1] + pd.Timedelta(hours=8), leverage=1.0, equity=1.0)


if __name__ == "__main__":
    unittest.main()
