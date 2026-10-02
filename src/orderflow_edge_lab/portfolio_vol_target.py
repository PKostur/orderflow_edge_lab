"""Portfolio-level volatility targeting overlay (capital efficiency, not a signal).

Scales a whole book's daily returns by L_t = min(max_leverage, target / realized),
where realized volatility uses only days strictly before the rebalance.  L is
updated on a calendar schedule and each change is charged as turnover on the
book's gross exposure.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def vol_target_overlay(
    returns: pd.Series,
    gross: pd.Series,
    *,
    target_annual_vol: float,
    window_days: int,
    max_leverage: float,
    rebalance: str = "W-MON",
    cost_bps: float = 20.0,
    periods_per_year: int = 365,
) -> dict[str, Any]:
    r = returns.dropna()
    g = gross.reindex(r.index).ffill().fillna(0.0)
    realized = r.rolling(window_days, min_periods=window_days).std(ddof=1).shift(1) * np.sqrt(periods_per_year)
    raw = (target_annual_vol / realized).clip(upper=max_leverage)
    stamps = pd.date_range(r.index.min(), r.index.max(), freq=rebalance, tz=r.index.tz)
    lev = raw.reindex(stamps, method="ffill").reindex(r.index, method="ffill").fillna(0.0)
    change = lev.diff().abs().fillna(lev.abs())
    cost = change * g * cost_bps / 2.0 / 10_000.0
    scaled = lev * r - cost
    return {
        "returns": scaled,
        "leverage": lev,
        "gross_exposure": lev * g,
        "total_cost": float(cost.sum()),
    }
