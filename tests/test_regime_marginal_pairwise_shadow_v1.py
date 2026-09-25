import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.regime_marginal_pairwise_shadow_v1 import (
    _validate_frame,
    all_specs,
    classify_ledger_trade,
)

ROOT=Path(__file__).resolve().parents[1]


def frame(n=700):
    idx=pd.date_range("2026-01-01",periods=n,freq="8h",tz="UTC")
    close=100*np.cumprod(np.full(n,1.001))
    open_=np.r_[close[0]/1.001,close[:-1]]
    return pd.DataFrame({
        "open":open_,
        "high":np.maximum(open_,close)*1.002,
        "low":np.minimum(open_,close)*0.998,
        "close":close,
        "volume":1000.0,
    },index=idx)


class Tests(unittest.TestCase):
    def test_fixed_contrast_family_is_92(self):
        specs=all_specs()
        self.assertEqual(len(specs),92)
        self.assertEqual(sum(row["tier"]=="marginal" for row in specs),14)
        self.assertEqual(sum(row["tier"]=="pairwise" for row in specs),78)
        self.assertEqual(len({row["contrast_id"] for row in specs}),92)

    def test_incomplete_current_8h_bar_is_excluded(self):
        f=frame()
        as_of=f.index[-1]+pd.Timedelta(hours=4)
        clean=_validate_frame(f,symbol="BTC_USDT",as_of=as_of)
        self.assertEqual(clean.index[-1],f.index[-2])

    def test_trade_partition_excludes_prestart_and_terminal_snapshot(self):
        start=pd.Timestamp("2026-09-26T00:00:00Z")
        self.assertEqual(
            classify_ledger_trade({"entry":"2026-09-25T16:00:00Z","terminal_liquidation":False},start),
            "PRE_START_EXCLUDED",
        )
        self.assertEqual(
            classify_ledger_trade({"entry":"2026-09-26T00:00:00Z","terminal_liquidation":True},start),
            "OPEN_SNAPSHOT_NOT_SCORED",
        )
        self.assertEqual(
            classify_ledger_trade({"entry":"2026-09-26T00:00:00Z","terminal_liquidation":False},start),
            "COMPLETED_SCORED",
        )

    def test_watch_and_zero_anchor_binding_are_consistent(self):
        cfg=json.loads((ROOT/"config/universal_regime_marginal_pairwise_shadow_v1.json").read_text())
        binding=json.loads((ROOT/"config/universal_regime_marginal_pairwise_shadow_v1_anchor_binding.json").read_text())
        self.assertEqual(cfg["prospective_start_utc"],"2026-09-26T00:00:00Z")
        self.assertEqual(binding["watch_id"],cfg["watch_id"])
        self.assertEqual(binding["total_anchor_count"],0)
        self.assertTrue(cfg["claims"]["all_92_contrasts_frozen_before_historical_marginal_pairwise_results_were_inspected"])
        self.assertFalse(cfg["claims"]["regime_filter_authorized"])

    def test_review_gate_is_ninety_days_and_no_early_verdict(self):
        cfg=json.loads((ROOT/"config/universal_regime_marginal_pairwise_shadow_v1.json").read_text())
        self.assertEqual(cfg["prospective_reporting"]["review_after_calendar_days"],90)
        self.assertTrue(cfg["prospective_reporting"]["no_early_pass_fail"])
        self.assertEqual(cfg["prospective_reporting"]["contrast_eligibility"]["minimum_group_blocks"],3)


if __name__=="__main__":
    unittest.main()
