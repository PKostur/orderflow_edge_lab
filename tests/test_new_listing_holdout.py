from __future__ import annotations

import unittest

import pandas as pd

from orderflow_edge_lab.new_listing_holdout import batch_window, select_batch


class NewListingTests(unittest.TestCase):
    def test_batch_windows_are_consecutive_quarters(self):
        a0, b0, e0 = batch_window("2026-09-12T00:00:00Z", 0)
        a1, _, _ = batch_window("2026-09-12T00:00:00Z", 1)
        self.assertEqual(str(a0.date()), "2026-09-12")
        self.assertEqual(b0, a1)
        self.assertEqual(str(e0.date()), "2027-03-12")

    def test_selection_filters(self):
        ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
        detail = {
            "NEW_USDT": {"quoteCoin": "USDT", "state": 0, "openingTime": ms("2026-10-01"), "conceptPlate": []},
            "OLD_USDT": {"quoteCoin": "USDT", "state": 0, "openingTime": ms("2025-01-01"), "conceptPlate": []},
            "STK_USDT": {"quoteCoin": "USDT", "state": 0, "openingTime": ms("2026-10-01"), "conceptPlate": ["mc-trade-zone-Stock"]},
            "THIN_USDT": {"quoteCoin": "USDT", "state": 0, "openingTime": ms("2026-10-01"), "conceptPlate": []},
            "USED_USDT": {"quoteCoin": "USDT", "state": 0, "openingTime": ms("2026-10-01"), "conceptPlate": []},
        }
        turnover = {"NEW_USDT": 5e6, "OLD_USDT": 5e6, "STK_USDT": 5e6, "THIN_USDT": 1e5, "USED_USDT": 5e6}
        a, b, _ = batch_window("2026-09-12T00:00:00Z", 0)
        self.assertEqual(select_batch(detail, turnover, listed_from=a, listed_until=b, min_turnover=3e6,
                                      exclude={"USED_USDT"}), ["NEW_USDT"])


if __name__ == "__main__":
    unittest.main()
