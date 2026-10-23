"""Delta-neutral funding carry: long spot, short the same notional of the USDT perpetual (carry-study-v1).

Per unit of notional, the hedge earns spot_ret - perp_ret (basis drift, near zero) plus the funding the short perp
receives.  Legs are reset to equal notional at month end, paying for the accumulated drift; entry and exit pay both
legs.  Everything is descriptive; nothing here sends orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Costs:
    spot_taker_bps: float = 10.0
    perp_taker_bps: float = 5.0
    slippage_bps_per_leg: float = 2.0

    @property
    def pair_bps(self) -> float:
        """Cost of trading both legs once (entry or exit)."""
        return self.spot_taker_bps + self.perp_taker_bps + 2.0 * self.slippage_bps_per_leg

    @property
    def per_leg_bps(self) -> float:
        return self.pair_bps / 2.0


def daily_close(hourly: pd.DataFrame) -> pd.Series:
    """Close of the 1h bar ending at 00:00 UTC, indexed by that 00:00 (frames indexed by bar end)."""
    s = hourly["close"].astype(float)
    s = s[s.index.hour == 0]
    return s[~s.index.duplicated(keep="last")].sort_index()


def daily_funding(rates: pd.Series) -> pd.Series:
    """Sum of funding rates settled in (t-1 00:00, t 00:00], indexed by t."""
    r = rates.dropna().astype(float)
    if r.empty:
        return pd.Series(dtype=float)
    r = r[~r.index.duplicated(keep="first")]
    return r.groupby(r.index.ceil("D")).sum().sort_index()


def hedge_daily(spot_close: pd.Series, perp_close: pd.Series, funding: pd.Series, *,
                costs: Costs = Costs(), active: pd.Series | None = None, exit_at_end: bool = True) -> pd.DataFrame:
    """Daily P&L per unit notional of the hedge, after costs.

    ``active`` (optional, bool by day) switches the hedge on/off; every switch pays the pair cost, as do the first
    entry and the final exit.  Returns columns: basis, funding, cost, net, active.
    """
    idx = spot_close.index.intersection(perp_close.index)
    spot, perp = spot_close.reindex(idx), perp_close.reindex(idx)
    basis = (spot.pct_change() - perp.pct_change()).fillna(0.0)
    fund = funding.reindex(idx).fillna(0.0)
    on = (active.reindex(idx).fillna(False).astype(bool) if active is not None
          else pd.Series(True, index=idx))
    pair = costs.pair_bps / 1e4
    leg = costs.per_leg_bps / 1e4
    cost = pd.Series(0.0, index=idx)
    held = on.shift(1, fill_value=False)           # the hedge decided at t-1 earns day t
    switches = held.astype(int).diff().abs().fillna(held.astype(int))
    cost += switches * pair
    if exit_at_end and bool(held.iloc[-1]):
        cost.iloc[-1] += pair                       # final exit (a running forward book leaves it open)
    drift, last_month = 0.0, None
    for i, t in enumerate(idx):
        if not held.iloc[i]:
            drift = 0.0
            continue
        drift += float(basis.iloc[i])
        month = (t.year, t.month)
        if last_month is not None and month != last_month:
            cost.iloc[i] += 2.0 * leg * abs(drift)  # month-end reset to equal notional
            drift = 0.0
        last_month = month
    net = (basis + fund) * held - cost
    return pd.DataFrame({"basis": basis * held, "funding": fund * held, "cost": cost, "net": net, "active": held})


def funding_filter(funding: pd.Series, window: int = 7) -> pd.Series:
    """Declared variant: on at t if the mean daily funding over the window ending t is above 0 (used from t+1)."""
    return funding.rolling(window, min_periods=window).mean() > 0


def summarize(net: pd.Series, funding: pd.Series | None = None) -> dict[str, Any]:
    x = net.dropna()
    n = len(x)
    if n < 2:
        return {"days": n}
    eq = (1 + x).cumprod()
    ann = float(eq.iloc[-1] ** (365.0 / n) - 1)
    vol = float(x.std(ddof=1) * np.sqrt(365))
    monthly = (1 + x).groupby([x.index.year, x.index.month]).prod() - 1
    out: dict[str, Any] = {
        "days": n, "first": str(x.index[0].date()), "last": str(x.index[-1].date()),
        "total_return": float(eq.iloc[-1] - 1), "annual_return": ann, "annual_vol": vol,
        "sharpe": float(x.mean() / x.std(ddof=1) * np.sqrt(365)) if x.std(ddof=1) > 0 else None,
        "max_drawdown": float((eq / eq.cummax() - 1).min()),
        "positive_months": float((monthly > 0).mean()), "months": int(len(monthly)),
        "worst_30d": float(((1 + x).rolling(30).apply(np.prod, raw=True) - 1).min()) if n >= 30 else None,
        "worst_90d": float(((1 + x).rolling(90).apply(np.prod, raw=True) - 1).min()) if n >= 90 else None,
        "per_year": {str(y): float((1 + v).prod() - 1) for y, v in x.groupby(x.index.year)},
    }
    if funding is not None:
        f = funding.reindex(x.index).fillna(0.0)
        neg = (f < 0).astype(int)
        runs = neg.groupby((neg != neg.shift()).cumsum()).sum()
        out["longest_negative_funding_days"] = int(runs.max()) if len(runs) else 0
        out["negative_funding_day_share"] = float((f < 0).mean())
    return out
