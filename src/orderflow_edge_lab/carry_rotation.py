"""carry-rotation-v1 (config/carry_rotation_v1.json): weekly rotation of delta-neutral funding carry into the five
large caps paying the most funding.  Descriptive only; sends no orders."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.carry import Costs


def rotation_book(spot: pd.DataFrame, perp: pd.DataFrame, funding: pd.DataFrame, *, top_n: int = 5,
                  lookback_days: int = 7, costs: Costs = Costs()) -> dict[str, Any]:
    """Daily P&L per unit notional of the rotating book.

    Inputs are daily frames (index 00:00 UTC, one column per coin): spot close, perp close, funding settled in
    (t-1, t].  On each Monday the book picks the top_n coins by mean funding over the lookback ending that Monday
    (mean > 0 only) and holds them, equal weight, from the next day to the following Monday.
    """
    idx = spot.index.intersection(perp.index).intersection(funding.index)
    spot, perp, funding = spot.reindex(idx), perp.reindex(idx), funding.reindex(idx)
    basis = spot.pct_change() - perp.pct_change()
    eligible = spot.notna() & perp.notna() & funding.notna() & spot.shift(1).notna() & perp.shift(1).notna()
    mean_f = funding.rolling(lookback_days, min_periods=lookback_days).mean()
    pair = costs.pair_bps / 1e4
    weights = pd.DataFrame(0.0, index=idx, columns=spot.columns)
    current = pd.Series(0.0, index=spot.columns)
    cost = pd.Series(0.0, index=idx)
    picks: dict[str, list[str]] = {}
    for i, t in enumerate(idx):
        if i > 0:
            weights.iloc[i] = current                      # decided at t-1, earns day t
        if t.dayofweek == 0 and i + 1 < len(idx):
            cand = mean_f.loc[t].where(eligible.loc[t] & (mean_f.loc[t] > 0)).dropna().sort_values(ascending=False)
            chosen = list(cand.index[:top_n])
            new = pd.Series(0.0, index=spot.columns)
            if chosen:
                new[chosen] = 1.0 / top_n                  # unfilled slots stay in cash
            # entering, leaving or resizing a coin pays the pair cost on the traded notional (booked on the next day)
            if i + 1 < len(idx):
                cost.iloc[i + 1] += float((new - current).abs().sum()) * pair
            current = new
            picks[t.isoformat()] = chosen
    held = weights > 0
    pnl = (basis.fillna(0.0) + funding.fillna(0.0)).where(held, 0.0) * weights
    if float(current.abs().sum()) > 0:
        cost.iloc[-1] += float(current.abs().sum()) * pair  # final exit
    net = pnl.sum(axis=1) - cost
    return {"net": net, "funding": (funding.fillna(0.0) * weights).sum(axis=1),
            "basis": (basis.fillna(0.0).where(held, 0.0) * weights).sum(axis=1), "cost": cost,
            "weights": weights, "picks": picks}


def pick_stats(picks: Mapping[str, list[str]]) -> dict[str, Any]:
    from collections import Counter

    c = Counter(s for v in picks.values() for s in v)
    n = len(picks)
    return {"rebalances": n, "mean_coins_held": (sum(len(v) for v in picks.values()) / n) if n else 0.0,
            "times_picked": dict(c.most_common())}
