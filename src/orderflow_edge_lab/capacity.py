"""Descriptive capacity / square-root price-impact helpers for the multi-premia blend.

Nothing here feeds back into any forward watch. Impact model: cost_fraction = Y * sigma_daily * sqrt(Q / ADV),
Q = |delta weight| * AUM (USD), ADV = trailing median daily dollar volume, sigma = trailing daily return std.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365.0
DEFAULT_Y = 1.0
FEE_ROUND_TRIP_BPS = 20.0
REFERENCE_GROSS_EDGE = 0.10  # assumption: approximate consistent-venue return of the blend, per year
THRESHOLD_SHARES = (0.25, 0.5, 1.0)
LIQUIDITY_WINDOW_DAYS = 30


def impact_cost_fraction(q_usd, adv_usd, sigma_daily, y: float = DEFAULT_Y):
    """Square-root-law cost as a fraction of traded notional. Elementwise; NaN where adv or sigma is missing/invalid."""
    q = np.asarray(q_usd, dtype=float)
    adv = np.asarray(adv_usd, dtype=float)
    sig = np.asarray(sigma_daily, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = y * sig * np.sqrt(np.abs(q) / np.where(adv > 0, adv, np.nan))
    return out


def per_coin_impact_drag(dw: pd.DataFrame, adv: pd.DataFrame, sigma: pd.DataFrame, aum: float, y: float = DEFAULT_Y) -> pd.Series:
    """Annualized impact drag (fraction of AUM per year) per coin: mean over days of |dw| * cost_fraction * 365."""
    d = dw.abs()
    cost = impact_cost_fraction(d.to_numpy() * aum, adv.reindex_like(d).to_numpy(), sigma.reindex_like(d).to_numpy(), y)
    term = pd.DataFrame(d.to_numpy() * cost, index=d.index, columns=d.columns).fillna(0.0)
    return term.mean(axis=0) * DAYS_PER_YEAR


def impact_drag(dw: pd.DataFrame, adv: pd.DataFrame, sigma: pd.DataFrame, aum: float, y: float = DEFAULT_Y) -> float:
    return float(per_coin_impact_drag(dw, adv, sigma, aum, y).sum())


def fee_drag(dw: pd.DataFrame, round_trip_bps: float = FEE_ROUND_TRIP_BPS) -> float:
    """Annualized fixed-fee drag; the round trip is split evenly over the two legs of a trade (one-way = rt/2)."""
    return float(dw.abs().sum(axis=1).mean() * DAYS_PER_YEAR * round_trip_bps / 2.0 / 1e4)


def solve_aum_threshold(drag_fn: Callable[[float], float], target: float, lo: float = 1.0, hi: float = 1e13,
                        iters: int = 200) -> float:
    """Smallest AUM with drag_fn(AUM) >= target, by bisection in log space (drag_fn must be non-decreasing).

    Returns 0.0 if already reached at lo and inf if not reached by hi."""
    if target <= 0 or drag_fn(lo) >= target:
        return float(lo) if target > 0 else 0.0
    if drag_fn(hi) < target:
        return float("inf")
    a, b = np.log(lo), np.log(hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        if drag_fn(float(np.exp(m))) >= target:
            b = m
        else:
            a = m
    return float(np.exp(b))


def trailing_liquidity(dollar_volume: pd.DataFrame, returns: pd.DataFrame, window: int = LIQUIDITY_WINDOW_DAYS,
                       min_periods: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Causal (shifted one day) trailing median daily dollar volume and daily return std."""
    adv = dollar_volume.rolling(window, min_periods=min_periods).median().shift(1)
    sigma = returns.rolling(window, min_periods=min_periods).std(ddof=1).shift(1)
    return adv, sigma
