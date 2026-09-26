"""Effective number of independent bets (descriptive, PnL-blind for universe screening).

Participation ratio of the correlation-matrix eigenvalues:
``N_eff = (sum lambda)^2 / sum lambda^2``; equals N for independent series and 1
for perfectly correlated ones.  Used to decide whether adding markets or
strategies can shorten the time needed to detect an edge (information rate
scales with sqrt(breadth)).
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


def participation_ratio(returns: pd.DataFrame, *, min_overlap: int = 60) -> float | None:
    data = returns.dropna(axis=1, how="all")
    data = data.loc[:, data.notna().sum() >= min_overlap]
    if data.shape[1] == 0:
        return None
    if data.shape[1] == 1:
        return 1.0
    corr = data.corr(min_periods=min_overlap).to_numpy(dtype=float)
    if not np.isfinite(corr).all():
        return None
    eig = np.clip(np.linalg.eigvalsh(corr), 0.0, None)
    return float(eig.sum() ** 2 / (eig ** 2).sum())


def average_pairwise_correlation(returns: pd.DataFrame) -> float | None:
    corr = returns.corr().to_numpy(dtype=float)
    n = corr.shape[0]
    if n < 2:
        return None
    return float((corr.sum() - n) / (n * (n - 1)))


def daily_open_returns(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    cols = {}
    for symbol, frame in frames.items():
        opens = frame["open"].astype(float)
        daily = opens.loc[(opens.index.hour == 0) & (opens.index.minute == 0)]
        cols[symbol] = daily.pct_change()
    return pd.DataFrame(cols).iloc[1:]


def marginal_gain(base: pd.DataFrame, candidates: pd.DataFrame) -> list[dict[str, float | str | None]]:
    """Effective-N change from adding each candidate alone to the base set."""
    reference = participation_ratio(base)
    rows = []
    for column in candidates.columns:
        joined = pd.concat([base, candidates[[column]]], axis=1)
        after = participation_ratio(joined)
        rows.append({
            "symbol": str(column),
            "effective_n_after": after,
            "gain": (after - reference) if after is not None and reference is not None else None,
            "mean_abs_corr_to_base": float(base.corrwith(candidates[column]).abs().mean()),
        })
    return rows
