"""Derive config/crypto_trend_core_voltarget_v1.json from the frozen core config (one-off)."""

import json

c = json.load(open("config/crypto_trend_core_v1.json", encoding="utf-8"))
c["watch_id"] = "crypto-trend-core-voltarget-v1"
c["question"] = ("Does a portfolio-level volatility target on the crypto-trend-core book improve capital use and "
                 "consistency going forward, net of costs and funding?")
c["registration_note"] = ("Registered 2026-09-27, before any day at or after the start existed. Companion of "
                          "crypto-trend-core-v1 (same book, same start); only the portfolio overlay differs, so their "
                          "daily difference is the forward test of the overlay.")
c["portfolio_overlay"] = {
    "method": "vol_target", "target_annual_vol": 0.12, "window_days": 60, "max_leverage": 3.0, "rebalance": "W-MON",
    "cost": "|change in L| x book gross x half round trip",
    "target_choice_disclosed": ("12% chosen so that realized vol lands near 15% given the 1.25x overshoot measured in "
                                "portfolio-vol-target-v1 on seen data"),
}
c["evidence_basis"]["portfolio_vol_target_v1"] = ("descriptive 2020-26: Sharpe 1.40 -> 1.42, return 20.5% -> 26.6%, "
                                                  "2023-26 returns roughly doubled, realized vol 18.7% vs 15% target")
c["reporting"]["comparison"] = "daily difference versus crypto-trend-core-v1 over the same days"
json.dump(c, open("config/crypto_trend_core_voltarget_v1.json", "w", encoding="utf-8"), indent=2)
print("written")
