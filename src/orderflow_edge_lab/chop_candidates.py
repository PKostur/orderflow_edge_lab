"""Candidate strategies for CHOP-labelled regimes (declared in config/chop_regime_search_v1.json).

Each builder returns per-coin raw targets in {-1, 0, +1} (or fractions) on the
8h index.  They are combined with the frozen trend core outside CHOP.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.funding_overlay import funding_avg_per_8h
from orderflow_edge_lab.strategy_tournament import generate_target_position

TEXTBOOK = {
    "C1_bb_meanrev": ("bb_mean_reversion", {"period": 20, "std": 2.0, "rsi_period": 14, "rsi_low": 30, "rsi_high": 70, "max_hold": 20}),
    "C2_zscore_reversal": ("intraday_reversal", {"lookback": 3, "z": 1.5, "max_hold": 6, "vol_window": 60}),
    "C3_squeeze_breakout": ("bb_squeeze_breakout", {"period": 20, "std": 2.0, "squeeze_q": 0.2, "max_hold": 40}),
    "C4_trend_pullback": ("trend_pullback", {"fast": 24, "slow": 96, "long_rsi_max": 40, "short_rsi_min": 60, "max_hold": 30}),
}


def family_target(frame: pd.DataFrame, name: str) -> pd.Series:
    fam, params = TEXTBOOK[name]
    return generate_target_position(frame, fam, dict(params)).reindex(frame.index).fillna(0.0)


def cross_sectional_reversal(frames: Mapping[str, pd.DataFrame], eligible: Mapping[str, pd.Series], *,
                             lookback: int = 3, n_side: int = 3) -> dict[str, pd.Series]:
    """Each bar, among eligible (CHOP) coins: long the n_side worst, short the n_side best lookback returns."""
    idx = sorted(set().union(*[f.index for f in frames.values()]))
    idx = pd.DatetimeIndex(idx)
    ret = pd.DataFrame({s: f["close"].pct_change(lookback) for s, f in frames.items()}).reindex(idx)
    ok = pd.DataFrame({s: e for s, e in eligible.items()}).reindex(idx).fillna(False).astype(bool)
    out = pd.DataFrame(0.0, index=idx, columns=list(frames))
    for t in idx:
        r = ret.loc[t][ok.loc[t]].dropna()
        if len(r) >= 2 * n_side:
            order = r.sort_values()
            out.loc[t, order.index[:n_side]] = 1.0
            out.loc[t, order.index[-n_side:]] = -1.0
    return {s: out[s].reindex(frames[s].index).fillna(0.0) for s in frames}


def funding_carry(frame: pd.DataFrame, funding: pd.Series, *, min_abs_per_8h: float = 0.0001) -> pd.Series:
    """Hold the side that receives funding: short when funding is positive, long when negative."""
    avg = funding_avg_per_8h(funding, frame.index)
    return pd.Series(np.where(avg > min_abs_per_8h, -1.0, np.where(avg < -min_abs_per_8h, 1.0, 0.0)), index=frame.index)
