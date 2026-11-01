"""Point-in-time variant of ``xs_premia.run_xs`` for successor versions (not used by any frozen watch).

``run_xs`` marks a coin tradable on day d only if day d+1's open exists, so a coin that delists after d is dropped
from day d's selection using one day of future knowledge (evidence audit 2026-10-16, Part D).  Here a coin is
tradable on d if day d's open exists.  A held coin whose next open is missing settles on day d at the last traded
price of day d (the close of its last bar that day) and then leaves the book as cash; if no such price exists it
earns 0 on day d and is flagged.  Without delistings or data holes the result is identical to ``run_xs``.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.xs_premia import quantile_weights


def daily_last_close_panel(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Close of the last bar of each UTC day, indexed at that day's 00:00 (the settlement price for day d)."""
    out = {s: f["close"].astype(float).groupby(f.index.floor("D")).last() for s, f in frames.items()}
    return pd.DataFrame(out).sort_index()


def run_xs_pit(opens: pd.DataFrame, last_close: pd.DataFrame, fund: pd.DataFrame, score: pd.DataFrame, *,
               rebalance_days: int, q: float, cost_bps: float, min_names: int = 8) -> dict[str, Any]:
    """Same accounting as ``run_xs`` with a day-d-only tradability mask and explicit delisting settlement."""
    nxt = opens.shift(-1)
    last_close = last_close.reindex(index=opens.index, columns=opens.columns)
    w = pd.Series(0.0, index=opens.columns)
    rows, turnover, weights, settlements = {}, {}, {}, []
    last = len(opens.index) - 1
    for i, d in enumerate(opens.index):
        if i % rebalance_days == 0:
            sc = score.loc[d].where(opens.loc[d].notna())
            new = quantile_weights(sc, q) if sc.notna().sum() >= min_names else pd.Series(0.0, index=opens.columns)
            if i < last:
                turnover[d] = float((new - w).abs().sum())
            w = new
        weights[d] = w.copy()
        if i == last:
            break    # the book for the latest day is decided; its return needs the next open
        r = nxt.loc[d] / opens.loc[d] - 1.0
        ending = w.index[(w != 0) & opens.loc[d].notna() & nxt.loc[d].isna()]
        for s in ending:
            px = last_close.at[d, s]
            if pd.notna(px):
                r[s] = px / opens.at[d, s] - 1.0
                settlements.append({"date": d.isoformat(), "symbol": s, "price": "last_close"})
            else:
                r[s] = 0.0
                settlements.append({"date": d.isoformat(), "symbol": s, "price": "none_zero_return"})
        r = r.fillna(0.0)
        f = fund.loc[d] if d in fund.index else 0.0
        cost = turnover.get(d, 0.0) * cost_bps / 2.0 / 10_000.0
        rows[d] = float((w * r).sum() - (w * f).sum() - cost)
        w = w * (1.0 + r)
        if len(ending):
            w[ending] = 0.0      # settled: proceeds held as cash until the next rebalance
    return {"returns": pd.Series(rows).sort_index(), "turnover": pd.Series(turnover),
            "weights": pd.DataFrame(weights).T, "settlements": settlements}
