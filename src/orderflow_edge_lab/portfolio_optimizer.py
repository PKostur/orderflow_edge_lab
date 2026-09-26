"""Walk-forward portfolio construction across strategy sleeves.

Markowitz mean-variance with estimation-risk safeguards, compared against
minimum variance and equal weight.  Weights are long-only across sleeves (each
sleeve already goes long or short internally), sum to 1 and are capped per
sleeve.  Estimates use only data strictly before each rebalance date, and
weight changes are charged as turnover cost.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

METHODS = ("equal", "min_variance", "mvo_sample", "mvo_shrunk")


def _solve(objective, n: int, cap: float) -> np.ndarray:
    cap = max(cap, 1.0 / n)
    x0 = np.full(n, 1.0 / n)
    res = minimize(
        objective, x0, method="SLSQP",
        bounds=[(0.0, cap)] * n,
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
        options={"maxiter": 500, "ftol": 1e-12},
    )
    w = np.clip(res.x if res.success else x0, 0.0, cap)
    return w / w.sum()


def mean_variance_weights(mu: np.ndarray, cov: np.ndarray, *, risk_aversion: float, cap: float) -> np.ndarray:
    """argmax  w'mu - (lambda/2) w'Σw  s.t. sum w = 1, 0 <= w <= cap."""
    return _solve(lambda w: -(w @ mu) + 0.5 * risk_aversion * (w @ cov @ w), len(mu), cap)


def min_variance_weights(cov: np.ndarray, *, cap: float) -> np.ndarray:
    return _solve(lambda w: w @ cov @ w, cov.shape[0], cap)


def shrunk_means(returns: pd.DataFrame) -> np.ndarray:
    """James-Stein shrinkage of sleeve means toward the grand mean."""
    x = returns.to_numpy(dtype=float)
    t, n = x.shape
    mu = x.mean(axis=0)
    grand = mu.mean()
    if n < 3 or t < 2:
        return np.full(n, grand)
    se2 = x.var(axis=0, ddof=1).mean() / t
    spread = ((mu - grand) ** 2).sum()
    k = 0.0 if spread <= 0 else max(0.0, min(1.0, (n - 3) * se2 / spread))
    return grand + (1.0 - k) * (mu - grand)


def target_weights(window: pd.DataFrame, method: str, *, cap: float, risk_aversion: float) -> np.ndarray:
    n = window.shape[1]
    if method == "equal":
        return np.full(n, 1.0 / n)
    if method == "min_variance":
        return min_variance_weights(LedoitWolf().fit(window.to_numpy()).covariance_, cap=cap)
    if method == "mvo_sample":
        return mean_variance_weights(window.mean().to_numpy(), np.cov(window.to_numpy(), rowvar=False),
                                     risk_aversion=risk_aversion, cap=cap)
    if method == "mvo_shrunk":
        return mean_variance_weights(shrunk_means(window), LedoitWolf().fit(window.to_numpy()).covariance_,
                                     risk_aversion=risk_aversion, cap=cap)
    raise ValueError(f"unknown method {method}")


def walk_forward(
    returns: pd.DataFrame,
    *,
    method: str,
    lookback_days: int = 365,
    rebalance: str = "MS",
    cost_bps: float = 20.0,
    cap: float = 0.15,
    risk_aversion: float = 10.0,
) -> dict[str, Any]:
    """Rebalance on calendar starts; weights drift with sleeve returns in between."""
    r = returns.fillna(0.0)
    dates = pd.date_range(r.index.min() + pd.Timedelta(days=lookback_days), r.index.max(), freq=rebalance,
                          tz=r.index.tz)
    if len(dates) == 0:
        raise ValueError("not enough history for one rebalance")
    weights_rows = {}
    out = pd.Series(0.0, index=r.index)
    held = np.zeros(r.shape[1])
    cost_total = 0.0
    for k, date in enumerate(dates):
        window = r.loc[(r.index < date) & (r.index >= date - pd.Timedelta(days=lookback_days))]
        active = window.columns[(window != 0).sum() >= 0.5 * len(window)]
        w = pd.Series(0.0, index=r.columns)
        if len(active) >= 2:
            w[active] = target_weights(window[active], method, cap=cap, risk_aversion=risk_aversion)
        elif len(active) == 1:
            w[active] = 1.0
        w_arr = w.to_numpy()
        trade_cost = float(np.abs(w_arr - held).sum()) * cost_bps / 2.0 / 10_000.0
        cost_total += trade_cost
        weights_rows[date] = w
        end = dates[k + 1] if k + 1 < len(dates) else r.index.max() + pd.Timedelta(days=1)
        period = r.loc[(r.index >= date) & (r.index < end)]
        cur = w_arr.copy()
        first = True
        for ts, row in period.iterrows():
            gross = float(cur @ row.to_numpy())
            out[ts] = gross - (trade_cost if first else 0.0)
            first = False
            grown = cur * (1.0 + row.to_numpy())
            cur = grown / grown.sum() if grown.sum() > 0 else cur
        held = cur
    returns_out = out.loc[out.index >= dates[0]]
    return {
        "returns": returns_out,
        "weights": pd.DataFrame(weights_rows).T,
        "turnover_cost_total": cost_total,
    }
