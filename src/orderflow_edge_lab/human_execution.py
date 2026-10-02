"""Human-constrained execution simulator for the crypto trend core.

Signals are the frozen 8h DON8/EMA8 rules (8h bars rebuilt from 1h data at
00/08/16 UTC).  A human acts only at local check-in times, holds at most K
coins, and trades with market or limit orders.  Accounting is fixed quantity,
marked to market hourly on 1h opens, with fees, slippage and (where
available) funding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.portfolio_optimizer import mean_variance_weights, shrunk_means
from orderflow_edge_lab.strategy_tournament import _atr, _ema
from orderflow_edge_lab.universal_backtest import legacy_strategy

STRATEGIES = {
    "DON8": ("donchian_breakout", {"lookback": 55}),
    "EMA8": ("ema_tsmom", {"fast": 24, "slow": 96, "min_atr_spread": 0.25}),
}


@dataclass(frozen=True)
class HumanPlan:
    checkins_local: tuple[int, ...] = (9, 15, 21)
    timezone: str = "Europe/Berlin"
    sessions: tuple[tuple[str, int], ...] = ()  # optional (timezone, local hour) pairs; overrides the two fields above
    max_coins: int = 5
    buffer: int = 0
    strategies: tuple[str, ...] = ("DON8", "EMA8")
    execution: str = "market"  # or "limit"
    allocation: str = "invvol"  # or "mvo_shrunk"
    target_vol: float = 0.15
    slippage_bps: float = 5.0
    vol_window_bars: int = 180  # 8h bars
    mvo_lookback_days: int = 180
    mvo_risk_aversion: float = 10.0


def to_8h(h1: pd.DataFrame) -> pd.DataFrame:
    agg = h1.resample("8h", origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    return agg


def signals_8h(h8: pd.DataFrame, strategies: Sequence[str]) -> pd.DataFrame:
    """Per-strategy target (+1/0/-1) and trend strength, stamped at each bar's CLOSE time."""
    out = pd.DataFrame(index=h8.index)
    for name in strategies:
        family, params = STRATEGIES[name]
        out[name] = legacy_strategy(family).generate_target(h8, params, None).reindex(h8.index).fillna(0.0)
    close = h8["close"].astype(float)
    atr = _atr(h8, 14).replace(0.0, np.nan)
    out["strength"] = ((_ema(close, 24) - _ema(close, 96)) / atr).abs().fillna(0.0)
    logret = np.log(close).diff()
    out["vol"] = logret.rolling(180, min_periods=180).std(ddof=1) * math.sqrt(3 * 365)
    out.index = out.index + pd.Timedelta(hours=8)  # known only once the bar has closed
    return out


def checkin_times(index: pd.DatetimeIndex, plan: HumanPlan) -> pd.DatetimeIndex:
    pairs = plan.sessions or tuple((plan.timezone, h) for h in plan.checkins_local)
    mask = np.zeros(len(index), dtype=bool)
    for tz, hour in pairs:
        local = index.tz_convert(tz)
        mask |= (local.hour == hour) & (local.minute == 0)
    return index[mask]


@dataclass
class _Book:
    qty: dict[str, float] = field(default_factory=dict)
    entry: dict[str, tuple[float, float]] = field(default_factory=dict)  # symbol -> (direction, budget) at entry
    pending: dict[str, float] = field(default_factory=dict)  # symbol -> target qty awaiting limit fill
    limit_px: dict[str, float] = field(default_factory=dict)


def simulate(
    h1: Mapping[str, pd.DataFrame],
    fees: Mapping[str, tuple[float, float]],  # symbol -> (taker, maker) fraction
    plan: HumanPlan,
    *,
    funding: Mapping[str, pd.Series] | None = None,
    start: str | None = None,
    end: str | None = None,
    equity0: float = 10_000.0,
) -> dict[str, Any]:
    symbols = sorted(h1)
    idx = pd.DatetimeIndex(sorted(set().union(*[h1[s].index for s in symbols])))
    if start:
        idx = idx[idx >= pd.Timestamp(start)]
    if end:
        idx = idx[idx < pd.Timestamp(end)]
    opens = pd.DataFrame({s: h1[s]["open"].astype(float) for s in symbols}).reindex(idx).ffill()
    highs = pd.DataFrame({s: h1[s]["high"].astype(float) for s in symbols}).reindex(idx)
    lows = pd.DataFrame({s: h1[s]["low"].astype(float) for s in symbols}).reindex(idx)
    sig = {s: signals_8h(to_8h(h1[s]), plan.strategies) for s in symbols}
    fund = pd.DataFrame(
        {s: (funding or {}).get(s, pd.Series(dtype=float)) for s in symbols}
    ).reindex(idx).fillna(0.0) if funding else None
    checkins = set(checkin_times(idx, plan))
    daily_px = opens.resample("1D").first()

    o, hi, lo = opens.to_numpy(), highs.to_numpy(), lows.to_numpy()
    book = _Book()
    equity = equity0
    equity_path = np.empty(len(idx))
    trades, fees_paid, funding_paid, notional_traded = 0, 0.0, 0.0, 0.0
    col = {s: j for j, s in enumerate(symbols)}

    def fill(sym: str, new_qty: float, px: float, maker: bool) -> None:
        nonlocal equity, trades, fees_paid, notional_traded
        dq = new_qty - book.qty.get(sym, 0.0)
        if dq == 0.0:
            return
        taker, mk = fees[sym]
        rate = mk if maker else taker + plan.slippage_bps / 10_000.0
        cost = abs(dq) * px * rate
        equity -= cost
        fees_paid += cost
        notional_traded += abs(dq) * px
        trades += 1
        book.qty[sym] = new_qty

    for i, ts in enumerate(idx):
        px = o[i]
        # 1) funding settles on positions held into this hour
        if fund is not None and book.qty:
            for sym, q in book.qty.items():
                rate = float(fund.iat[i, col[sym]])
                if rate and q:
                    flow = -q * px[col[sym]] * rate
                    equity += flow
                    funding_paid -= flow
        # 2) resting limit orders fill if this hour's range trades through them
        if book.pending:
            for sym in list(book.pending):
                j = col[sym]
                target = book.pending[sym]
                lim = book.limit_px[sym]
                buying = target > book.qty.get(sym, 0.0)
                if (buying and lo[i, j] <= lim) or ((not buying) and hi[i, j] >= lim):
                    fill(sym, target, lim, maker=True)
                    del book.pending[sym], book.limit_px[sym]
        # 3) human check-in: decide targets from the latest completed 8h bar
        if ts in checkins:
            # unfilled limits from the previous check-in are chased at market now
            for sym in list(book.pending):
                fill(sym, book.pending[sym], px[col[sym]], maker=False)
            book.pending.clear()
            book.limit_px.clear()
            cand = []
            for sym in symbols:
                s = sig[sym]
                known = s.loc[s.index <= ts]
                if known.empty or not np.isfinite(px[col[sym]]):
                    continue
                last = known.iloc[-1]
                direction = float(np.mean([last[n] for n in plan.strategies]))
                vol = float(last["vol"])
                if direction == 0.0 or not np.isfinite(vol) or vol <= 0:
                    continue
                cand.append((sym, direction, float(last["strength"]), vol))
            cand.sort(key=lambda c: -c[2])
            held = [s for s, q in book.qty.items() if q]
            rank = {c[0]: r for r, c in enumerate(cand)}
            keep = [s for s in held if s in rank and rank[s] < plan.max_coins + plan.buffer]
            chosen = keep[: plan.max_coins]
            for c in cand:
                if len(chosen) >= plan.max_coins:
                    break
                if c[0] not in chosen:
                    chosen.append(c[0])
            info = {c[0]: c for c in cand}
            if plan.allocation == "mvo_shrunk" and len(chosen) >= 2:
                hist = daily_px.loc[(daily_px.index < ts) & (daily_px.index >= ts - pd.Timedelta(days=plan.mvo_lookback_days)), chosen]
                signed = hist.pct_change().dropna() * np.array([np.sign(info[s][1]) for s in chosen])
                if len(signed) >= 60:
                    from sklearn.covariance import LedoitWolf
                    w = mean_variance_weights(shrunk_means(signed), LedoitWolf().fit(signed.to_numpy()).covariance_,
                                              risk_aversion=plan.mvo_risk_aversion, cap=0.5)
                    budget = {s: w[k] * len(chosen) for k, s in enumerate(chosen)}
                else:
                    budget = {s: 1.0 for s in chosen}
            else:
                budget = {s: 1.0 for s in chosen}
            targets = {}
            for sym in symbols:
                cur = book.qty.get(sym, 0.0)
                if sym in chosen:
                    _, direction, _, vol = info[sym]
                    prior = book.entry.get(sym)
                    if cur != 0.0 and prior is not None and prior[0] == direction:
                        targets[sym] = cur  # fixed quantity: hold until the signal itself changes
                        continue
                    size = min(1.0, plan.target_vol / vol) * budget[sym] / plan.max_coins
                    targets[sym] = direction * size * equity / px[col[sym]]
                    book.entry[sym] = (direction, budget[sym])
                else:
                    targets[sym] = 0.0
                    book.entry.pop(sym, None)
            for sym, tq in targets.items():
                cur = book.qty.get(sym, 0.0)
                if abs(tq - cur) * px[col[sym]] < 1e-6 * equity:
                    continue
                if plan.execution == "limit":
                    book.pending[sym], book.limit_px[sym] = tq, px[col[sym]]
                else:
                    fill(sym, tq, px[col[sym]], maker=False)
        # 4) mark to market to the next hour's open
        if i + 1 < len(idx):
            nxt = o[i + 1]
            for sym, q in book.qty.items():
                if q:
                    j = col[sym]
                    if np.isfinite(nxt[j]) and np.isfinite(px[j]):
                        equity += q * (nxt[j] - px[j])
        if equity <= 0:
            raise ValueError("equity non-positive")
        equity_path[i] = equity
    eq = pd.Series(equity_path, index=idx)
    # equity at each 00:00 UTC mark; the return stamped d covers d-1 00:00 -> d 00:00 (canonical convention)
    daily = eq.loc[(eq.index.hour == 0)].pct_change().dropna()
    years = max((idx[-1] - idx[0]).days / 365.25, 1e-9)
    return {
        "daily_returns": daily,
        "final_equity": float(eq.iloc[-1]),
        "trades": trades,
        "trades_per_week": trades / (years * 52.18),
        "fees_and_slippage_pct_per_year": fees_paid / equity0 / years,
        "funding_pct_per_year": funding_paid / equity0 / years,
        "turnover_x_per_year": notional_traded / equity0 / years,
    }
