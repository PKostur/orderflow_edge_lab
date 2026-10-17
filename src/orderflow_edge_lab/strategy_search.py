"""strategy-search-v1: candidate weight functions, accounting and the eight registered gates.

Implements ``config/strategy_search_v1.json`` (gates G1-G8) and the seven candidates of
``config/strategy_search_v1_round1.json`` exactly as registered.  Descriptive research code only: no
promotion, no filters, no leverage, no order placement.

Conventions
-----------
* ``data`` is a dict.  ``data["prices"]`` is a dates x tickers DataFrame of adjusted closes (UTC-normalised
  index).  FRED series are stored under their series id (``"DTB3"``, ``"DCOILWTICO"``) as raw daily Series
  indexed by observation date.  ``data["_calendar"]`` (optional) is the trading calendar; it is never
  truncated by the G1 test because a trading calendar is public information.  Without it the price index is
  the calendar.
* ``weights_<id>(data, params)`` returns a dates x assets DataFrame.  Row ``t`` is the target weight decided
  with data up to and including the close of ``t`` and applied to the return from close ``t`` to close
  ``t+1``.  Rows with no signal yet (history too short) are NaN and are treated as 0 by the backtest.
* FRED values dated ``d`` are usable from the next business day (release lag of one business day).
* Returns are stamped at the date on which the return is earned (close ``t-1`` to close ``t`` -> ``t``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any
import urllib.request

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_evaluation import deflated_sharpe_probability
from orderflow_edge_lab.etf_history_holdout import fetch_yahoo_daily
from orderflow_edge_lab.review_methods import (
    action_matched_null_p,
    cost_wall_bps,
    matched_random_selection_returns,
)
from orderflow_edge_lab.trend_portfolio_forward import newey_west_t

SEED = 20261011
TRADING_DAYS = 252
NW_LAGS = 5
N_NULL_DRAWS = 999
N_TRUNCATION_DATES = 50
COST_BPS_ROUND_TRIP = 10.0
FRED_LAG_BUSINESS_DAYS = 1
# Implementation note (GEM perturbations): the L-month return R_L is compared with the T-bill return over the same
# L months, tbill_L = mean(DTB3 over the last L months)/100 * L/12.  For the registered L = 12 the factor is exactly
# 1.0, i.e. the registered rule; for the 10 and 14 month perturbations it keeps the units comparable.
GEM_TBILL_SCALING_NOTE = "tbill_L = mean(DTB3 over last L months)/100 * L/12"
CRYPTO_REFERENCE_CODE_VERSION = "crypto-ref-v2"
CRYPTO_REFERENCE_PROVENANCE = ("MEXC 8h prices + Binance funding (venue substitution: MEXC funding history starts "
                               "2025-04)")
CACHE_DIRNAME = "strategy_search_cache"

# Universes exactly as registered (a unit test compares these with the round-1 config).
VAA_RISKY = ["SPY", "IWM", "QQQ", "VGK", "EWJ", "VWO", "VNQ", "GSG", "GLD", "TLT", "LQD", "HYG"]
VAA_CASH = ["SHY", "IEF", "LQD"]
PAA_RISKY = ["SPY", "QQQ", "IWM", "VGK", "EWJ", "EEM", "IYR", "GSG", "GLD", "HYG", "LQD", "TLT"]
PAA_SAFE = "IEF"
GEM_US, GEM_EXUS, GEM_BONDS = "SPY", "EFA", "AGG"
STYLE_UNIVERSE = ["IJJ", "IJK", "IJS", "IJT", "IVE", "IVW"]
VIX_TICKERS = ("^VIX", "^VIX3M")


class StrategySearchError(ValueError):
    pass


# --------------------------------------------------------------------------------------------- data


def cache_dir() -> Path:
    path = Path(os.environ.get("TEMP", tempfile.gettempdir())) / CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_fred(series_id: str, *, start: str = "1990-01-01", end: str = "2026-09-30", cache: bool = True,
               directory: Path | None = None, timeout: float = 120.0, retries: int = 3) -> pd.Series:
    """Daily FRED series via fredgraph.csv.  '.' is parsed as NaN.  Cached as raw csv text."""
    base = directory if directory is not None else cache_dir()
    path = base / f"fred_{series_id}_{start}_{end}.csv"
    if cache and path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        # explicit cosd/coed: the bare full-history query times out from some networks
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
        # no browser User-Agent: fred.stlouisfed.org stalls requests that send "Mozilla/5.0"
        request = urllib.request.Request(url)
        text = ""
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    text = response.read().decode("utf-8")
                break
            except (TimeoutError, OSError):
                if attempt == retries - 1:
                    raise
                time.sleep(5.0)
        if cache:
            base.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return parse_fred_csv(text, series_id)


def parse_fred_csv(text: str, series_id: str) -> pd.Series:
    from io import StringIO

    frame = pd.read_csv(StringIO(text))
    if frame.shape[1] < 2:
        raise StrategySearchError(f"unexpected FRED csv for {series_id}")
    dates = pd.to_datetime(frame.iloc[:, 0], utc=True).dt.normalize()
    values = pd.to_numeric(frame.iloc[:, 1].replace(".", np.nan), errors="coerce")
    out = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(dates), name=series_id)
    return out[~out.index.duplicated(keep="last")].sort_index()


def fetch_close(symbol: str, start: str, end: str, *, cache: bool = True, directory: Path | None = None) -> pd.Series:
    """Adjusted close from Yahoo through ``etf_history_holdout.fetch_yahoo_daily`` (cached)."""
    base = directory if directory is not None else cache_dir()
    safe = symbol.replace("^", "_idx_")
    path = base / f"yahoo_{safe}_{start}_{end}.csv"
    if cache and path.exists():
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        series = frame["close"]
        series.index = pd.DatetimeIndex(series.index).tz_localize("UTC") if series.index.tz is None else series.index
        return series.rename(symbol)
    series = fetch_yahoo_daily(symbol, start, end)["close"].astype(float)
    if cache:
        base.mkdir(parents=True, exist_ok=True)
        series.to_frame("close").to_csv(path)
    return series.rename(symbol)


def build_prices(closes: Mapping[str, pd.Series], *, calendar_symbol: str = "SPY", ffill_limit: int = 5) -> pd.DataFrame:
    """Price frame on the ``calendar_symbol`` trading calendar (no union index).

    Every series is reindexed to the SPY dates first (extra dates of e.g. ^VIX are dropped), then forward-filled
    with ``ffill_limit`` inside that calendar only.
    """
    if calendar_symbol not in closes:
        raise StrategySearchError(f"calendar symbol {calendar_symbol} missing")
    calendar = pd.DatetimeIndex(closes[calendar_symbol].dropna().index)
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise StrategySearchError("calendar index must be unique and increasing")
    cols = {}
    for name, series in closes.items():
        if series.index.has_duplicates:
            raise StrategySearchError(f"{name}: duplicate dates")
        cols[name] = series.sort_index().reindex(calendar)
    frame = pd.DataFrame(cols, index=calendar).ffill(limit=ffill_limit)
    if not frame.index.equals(calendar):
        raise StrategySearchError("price frame is not on the calendar")
    return frame


def frame_sha256(obj: pd.DataFrame | pd.Series) -> str:
    return sha256(pd.util.hash_pandas_object(obj, index=True).to_numpy().tobytes()).hexdigest()


def _series_provenance(s: pd.Series) -> dict[str, Any]:
    v = s.dropna()
    return {"first_date": str(v.index[0].date()) if len(v) else None,
            "last_date": str(v.index[-1].date()) if len(v) else None,
            "rows": int(len(v)), "sha256": frame_sha256(s)}


def data_provenance(prices: pd.DataFrame, fred: Mapping[str, pd.Series]) -> dict[str, Any]:
    """First date, last date, row count and sha256 per Yahoo ticker (as used) and FRED series, plus the frame hash."""
    return {
        "price_frame_sha256": frame_sha256(prices),
        "price_frame_rows": int(len(prices)),
        "calendar": "SPY trading days",
        "tickers": {str(c): _series_provenance(prices[c]) for c in prices.columns},
        "fred": {str(k): _series_provenance(v) for k, v in fred.items()},
    }


def asset_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None)


def fred_available(series: pd.Series, index: pd.DatetimeIndex, lag_business_days: int = FRED_LAG_BUSINESS_DAYS) -> pd.Series:
    """Latest FRED value usable on each date of ``index`` (observation d is usable from d + lag business days)."""
    s = series.dropna().sort_index()
    shifted = pd.Series(s.to_numpy(dtype=float), index=s.index + pd.offsets.BDay(lag_business_days))
    shifted = shifted[~shifted.index.duplicated(keep="last")]
    union = shifted.index.union(index)
    return shifted.reindex(union).ffill().reindex(index)


# ---------------------------------------------------------------------------------------- calendar


def _month_key(index: pd.DatetimeIndex) -> np.ndarray:
    return (index.year * 12 + index.month).to_numpy(dtype=np.int64)


def calendar_of(data: Mapping[str, Any]) -> pd.DatetimeIndex:
    cal = data.get("_calendar")
    if cal is not None:
        return pd.DatetimeIndex(cal)
    return pd.DatetimeIndex(data["prices"].index)


def month_end_dates(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each month of the calendar.

    The final calendar date counts as a month end only when the next weekday falls in a later month
    (the calendar cannot say more about its own future).
    """
    if len(calendar) == 0:
        return calendar
    key = _month_key(calendar)
    flags = np.empty(len(calendar), dtype=bool)
    flags[:-1] = key[1:] != key[:-1]
    nxt = calendar[-1] + pd.offsets.BDay(1)
    flags[-1] = (nxt.year * 12 + nxt.month) != key[-1]
    return calendar[flags]


def first_trading_days(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """First trading day of each month (a row whose previous row lies in an earlier month)."""
    if len(calendar) < 2:
        return calendar[:0]
    key = _month_key(calendar)
    flags = np.zeros(len(calendar), dtype=bool)
    flags[1:] = key[1:] != key[:-1]
    return calendar[flags]


def _empty_weights(index: pd.DatetimeIndex, columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(np.nan, index=index, columns=list(columns), dtype=float)


def _hold(index: pd.DatetimeIndex, columns: Sequence[str], decisions: Mapping[pd.Timestamp, Mapping[str, float]]) -> pd.DataFrame:
    """Place decided weight vectors on their dates and hold them until the next decision."""
    w = _empty_weights(index, columns)
    for t, row in decisions.items():
        if t not in w.index:
            continue
        w.loc[t, :] = 0.0
        for asset, value in row.items():
            w.loc[t, asset] = value
    return w.ffill()


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5 + 1e-12))


def _month_end_table(data: Mapping[str, Any], assets: Sequence[str]) -> pd.DataFrame:
    prices = data["prices"]
    me = month_end_dates(calendar_of(data))
    me = me[me <= prices.index[-1]]
    return prices.reindex(me)[list(assets)]


# ------------------------------------------------------------------------------------- candidates


def vaa_allocation(mom_risky: Mapping[str, float], mom_cash: Mapping[str, float], B: int, T: int) -> dict[str, float]:
    """VAA slot logic: b = #risky with momentum < 0, CF = min(1, b/B), n = round_half_up((1-CF)*T)."""
    b = sum(1 for v in mom_risky.values() if v < 0)
    cf = min(1.0, b / B)
    n = _round_half_up((1.0 - cf) * T)
    order = {a: i for i, a in enumerate(mom_risky)}
    ranked = sorted(mom_risky, key=lambda a: (-mom_risky[a], order[a]))
    weights: dict[str, float] = {}
    for asset in ranked[:n]:
        weights[asset] = weights.get(asset, 0.0) + 1.0 / T
    cash_weight = 1.0 - n / T
    if cash_weight > 1e-12:
        corder = {a: i for i, a in enumerate(mom_cash)}
        best = sorted(mom_cash, key=lambda a: (-mom_cash[a], corder[a]))[0]
        weights[best] = weights.get(best, 0.0) + cash_weight
    return weights


def weights_R1C1_VAA_G12(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    assets = list(dict.fromkeys(VAA_RISKY + VAA_CASH))
    tbl = _month_end_table(data, assets)
    mom = (12 * (tbl / tbl.shift(1) - 1) + 4 * (tbl / tbl.shift(3) - 1)
           + 2 * (tbl / tbl.shift(6) - 1) + 1 * (tbl / tbl.shift(12) - 1))
    decisions: dict[pd.Timestamp, dict[str, float]] = {}
    for t, row in mom.iterrows():
        if row.isna().any():
            continue
        decisions[t] = vaa_allocation({a: float(row[a]) for a in VAA_RISKY}, {a: float(row[a]) for a in VAA_CASH},
                                      int(params["B"]), int(params["T"]))
    return _hold(data["prices"].index, assets, decisions)


def paa_allocation(mom_risky: Mapping[str, float], protection_divisor: float, top_n: int) -> dict[str, float]:
    """PAA: safe share = min(1, n0/divisor); remainder over the top ``top_n`` positive-MOM risky; rest to the safe asset."""
    n0 = sum(1 for v in mom_risky.values() if v <= 0)
    safe = min(1.0, n0 / protection_divisor)
    order = {a: i for i, a in enumerate(mom_risky)}
    positives = sorted((a for a, v in mom_risky.items() if v > 0), key=lambda a: (-mom_risky[a], order[a]))
    chosen = positives[:top_n]
    slot = (1.0 - safe) / top_n
    weights = {a: slot for a in chosen}
    weights[PAA_SAFE] = safe + (top_n - len(chosen)) * slot
    return weights


def weights_R1C2_PAA2(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    assets = PAA_RISKY + [PAA_SAFE]
    tbl = _month_end_table(data, assets)
    look = int(params["lookback_months"])
    sma = tbl.rolling(look, min_periods=look).mean()
    mom = tbl / sma - 1.0
    decisions: dict[pd.Timestamp, dict[str, float]] = {}
    for t, row in mom[PAA_RISKY].iterrows():
        if row.isna().any() or pd.isna(tbl.loc[t, PAA_SAFE]):
            continue
        decisions[t] = paa_allocation({a: float(row[a]) for a in PAA_RISKY}, float(params["protection_divisor"]),
                                      int(params["top_n"]))
    return _hold(data["prices"].index, assets, decisions)


def weights_R1C3_GEM(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    assets = [GEM_US, GEM_EXUS, GEM_BONDS]
    look = int(params["lookback_months"])
    tbl = _month_end_table(data, assets)
    r = tbl / tbl.shift(look) - 1.0
    tbill = fred_available(data["DTB3"], pd.DatetimeIndex(data["prices"].index))
    decisions: dict[pd.Timestamp, dict[str, float]] = {}
    for t, row in r.iterrows():
        if row.isna().any():
            continue
        window = tbill.loc[(tbill.index > t - pd.DateOffset(months=look)) & (tbill.index <= t)].dropna()
        if window.empty:
            continue
        tbill12 = float(window.mean()) / 100.0 * (look / 12.0)  # GEM_TBILL_SCALING_NOTE
        if row[GEM_US] > tbill12:
            pick = GEM_US if row[GEM_US] >= row[GEM_EXUS] else GEM_EXUS
        else:
            pick = GEM_BONDS
        decisions[t] = {pick: 1.0}
    return _hold(data["prices"].index, assets, decisions)


def weights_R1C4_turn_of_month(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    """Hold SPY over trading days -1, +1..+after around each month end (enter close of day -(before+1))."""
    before, after = int(params["days_before"]), int(params["days_after"])
    cal = calendar_of(data)
    prices_index = pd.DatetimeIndex(data["prices"].index)
    key = pd.Series(_month_key(cal), index=cal)
    from_start = key.groupby(key).cumcount().to_numpy()
    from_end = key.groupby(key).cumcount(ascending=False).to_numpy()
    in_window = pd.Series((from_end < before) | (from_start < after), index=cal)
    # the first calendar month may be incomplete: its head cannot be told from the start of a month
    prev = cal[0] - pd.offsets.BDay(1)
    if len(cal) and (prev.year * 12 + prev.month) == key.iloc[0]:
        in_window[(key == key.iloc[0]).to_numpy() & (from_start < after) & (from_end >= before)] = False
    # the final calendar month may be incomplete: its tail cannot be told from a month end
    if len(cal) and cal[-1] not in month_end_dates(cal):
        in_window[(key == key.iloc[-1]).to_numpy() & (from_end < before)] = False
    next_in_window = in_window.shift(-1, fill_value=False).astype(float)
    w = pd.DataFrame({"SPY": next_in_window.reindex(prices_index)})
    return w.astype(float)


def weights_R1C5_vix_ratio_short_vol(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    """Long SVXY on day t if ratio(t-2) < threshold and < SMA(ratio)(t-2): decided at close t-1."""
    prices = data["prices"]
    ratio = prices["^VIX"] / prices["^VIX3M"]
    sma = ratio.rolling(int(params["sma_days"]), min_periods=int(params["sma_days"])).mean()
    ok = ratio.notna() & sma.notna()
    ind = ((ratio < float(params["threshold"])) & (ratio < sma)).astype(float).where(ok)
    w = ind.shift(int(params["lag_days"]) - 1)
    w = w.where(prices["SVXY"].notna())
    return pd.DataFrame({"SVXY": w}).astype(float)


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    xm, ym = x.mean(), y.mean()
    var = float(((x - xm) ** 2).sum())
    if var <= 0.0:
        return None
    slope = float(((x - xm) * (y - ym)).sum() / var)
    return float(ym - slope * xm), slope


def weights_R1C6_oil_spy(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    prices = data["prices"]
    window = int(params["window_months"])
    index = pd.DatetimeIndex(prices.index)
    me = month_end_dates(calendar_of(data))
    me = me[me <= index[-1]]
    spy = prices["SPY"].reindex(me)
    wti = fred_available(data["DCOILWTICO"], index).reindex(me)
    rf = fred_available(data["DTB3"], index).reindex(me)
    y = (spy / spy.shift(1) - 1.0).to_numpy(dtype=float)
    x = (wti / wti.shift(1) - 1.0).to_numpy(dtype=float)
    rf_m = (rf / 100.0 / 12.0).to_numpy(dtype=float)
    decisions: dict[pd.Timestamp, dict[str, float]] = {}
    for k, t in enumerate(me):
        lo = k - window + 1
        if lo < 1 or not np.isfinite(x[k]) or not np.isfinite(rf_m[k]):
            continue
        xs, ys = x[lo - 1:k], y[lo:k + 1]  # pair (oil return of month j-1, SPY return of month j)
        if len(xs) != window or not (np.isfinite(xs).all() and np.isfinite(ys).all()):
            continue
        fit = _ols(xs, ys)
        if fit is None:
            continue
        forecast = fit[0] + fit[1] * x[k]
        decisions[t] = {"SPY": 1.0 if forecast > rf_m[k] else 0.0}
    return _hold(index, ["SPY"], decisions)


def weights_R1C7_style_momentum(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    prices = data["prices"][STYLE_UNIVERSE]
    look = int(params["lookback_days"])
    mom = prices / prices.shift(look) - 1.0
    firsts = first_trading_days(calendar_of(data))
    firsts = firsts[firsts <= prices.index[-1]]
    decisions: dict[pd.Timestamp, dict[str, float]] = {}
    for t in firsts:
        if t not in mom.index:
            continue
        row = mom.loc[t]
        if row.isna().any():
            continue
        values = row.to_numpy(dtype=float)
        top = int(np.argmax(values))
        bottom = int(np.argmin(values))
        decisions[t] = {STYLE_UNIVERSE[top]: 0.5, STYLE_UNIVERSE[bottom]: -0.5}
    return _hold(pd.DatetimeIndex(prices.index), STYLE_UNIVERSE, decisions)


CANDIDATE_FUNCS: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], pd.DataFrame]] = {
    "R1C1_VAA_G12": weights_R1C1_VAA_G12,
    "R1C2_PAA2": weights_R1C2_PAA2,
    "R1C3_GEM": weights_R1C3_GEM,
    "R1C4_turn_of_month": weights_R1C4_turn_of_month,
    "R1C5_vix_ratio_short_vol": weights_R1C5_vix_ratio_short_vol,
    "R1C6_oil_spy": weights_R1C6_oil_spy,
    "R1C7_style_momentum": weights_R1C7_style_momentum,
}


def perturbation_param_sets(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One-at-a-time perturbations from the registration.  The turn-of-month ``window`` is a (before, after) pair."""
    base = dict(spec["params"])
    out: list[dict[str, Any]] = []
    for name, values in spec["perturb"].items():
        for value in values:
            if name == "window":
                out.append({**base, "days_before": int(value[0]), "days_after": int(value[1])})
            else:
                out.append({**base, name: value})
    return out


# -------------------------------------------------------------------------------------- accounting


def backtest_detail(weights: pd.DataFrame, returns: pd.DataFrame, cost_bps_round_trip: float) -> pd.DataFrame:
    """Gross, net and turnover per day.  Cost = turnover * cost_bps_round_trip / 2 / 1e4 (per-side)."""
    wp = weights.shift(1)  # weight decided at close t-1 earns the return of day t
    valid = wp.notna().any(axis=1)
    if not valid.any():
        return pd.DataFrame({"gross": [], "net": [], "turnover": []}, index=weights.index[:0])
    start = valid.idxmax()
    wp = wp.loc[start:].fillna(0.0)
    rets = returns.reindex(index=wp.index, columns=wp.columns).fillna(0.0)
    gross = (wp * rets).sum(axis=1)
    turnover = wp.diff().abs().sum(axis=1)
    turnover.iloc[0] = float(wp.iloc[0].abs().sum())
    net = gross - turnover * (cost_bps_round_trip / 2.0 / 1e4)
    return pd.DataFrame({"gross": gross, "net": net, "turnover": turnover})


def backtest(weights: pd.DataFrame, returns: pd.DataFrame, cost_bps_round_trip: float) -> tuple[pd.Series, pd.Series]:
    """Daily net return and turnover (sum of absolute weight changes) series."""
    detail = backtest_detail(weights, returns, cost_bps_round_trip)
    return detail["net"], detail["turnover"]


def perf_stats(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> dict[str, Any]:
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"days": 0, "mean_daily": None, "sharpe_daily": None, "sharpe": None, "newey_west_t": None,
                "cumulative_return": None, "max_drawdown": None}
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    sharpe_daily = float(r.mean() / sd) if sd > 0 else None
    equity = (1.0 + r).cumprod()
    return {
        "days": int(n),
        "mean_daily": float(r.mean()),
        "sharpe_daily": sharpe_daily,
        "sharpe": None if sharpe_daily is None else float(sharpe_daily * math.sqrt(periods_per_year)),
        "newey_west_t": newey_west_t(r, NW_LAGS),
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float((equity / equity.cummax() - 1.0).min()),
    }


def series_sha256(series: pd.Series) -> str:
    h = sha256()
    for ts, value in series.items():
        h.update(f"{pd.Timestamp(ts).isoformat()},{float(value)!r}\n".encode("ascii"))
    return h.hexdigest()


def _utc_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def resolve_window(window: Sequence[str], first_return_date: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = first_return_date if str(window[0]).startswith("first") else max(_utc_ts(window[0]), first_return_date)
    return start, _utc_ts(window[1])


def slice_window(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    return series.loc[(series.index >= start) & (series.index <= end)]


# --------------------------------------------------------------------------------------- the gates


def truncate_data(data: Mapping[str, Any], t: pd.Timestamp) -> dict[str, Any]:
    """Remove everything dated after ``t``.  Keys starting with ``_`` (the trading calendar) are kept."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key.startswith("_"):
            out[key] = value
        elif isinstance(value, (pd.DataFrame, pd.Series)):
            out[key] = value.loc[:t]
        else:
            out[key] = value
    return out


def _rows_equal(a: pd.Series, b: pd.Series) -> bool:
    return bool(np.array_equal(a.to_numpy(dtype=float), b.to_numpy(dtype=float), equal_nan=True))


def truncation_test(
    fn: Callable[[Mapping[str, Any], Mapping[str, Any]], pd.DataFrame],
    data: Mapping[str, Any],
    params: Mapping[str, Any],
    dates: Sequence[pd.Timestamp],
    full_weights: pd.DataFrame | None = None,
) -> dict[str, Any]:
    full = fn(data, params) if full_weights is None else full_weights
    mismatches: list[str] = []
    for t in dates:
        try:
            trunc = fn(truncate_data(data, t), params)
            row_trunc = trunc.reindex(columns=full.columns).loc[t]
        except Exception as exc:  # a function that cannot run on truncated data fails the test
            mismatches.append(f"{pd.Timestamp(t).date()}: {type(exc).__name__}")
            continue
        if not _rows_equal(full.loc[t], row_trunc):
            mismatches.append(str(pd.Timestamp(t).date()))
    return {"pass": not mismatches, "dates_checked": len(dates), "mismatches": mismatches[:10],
            "n_mismatches": len(mismatches)}


def g1_truncation(fn, data, params, weights: pd.DataFrame, *, seed: int = SEED, n_dates: int = N_TRUNCATION_DATES) -> dict[str, Any]:
    """G1 as registered: ``n_dates`` random dates (seed 20261011) from the rows after the first signal.

    Also reports (non-gating) the same check on random decision dates (rows where the weights change), because a
    one-day look-ahead at a monthly decision is only visible at the decision date itself.
    """
    valid = weights.dropna(how="all").index
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(valid), size=min(n_dates, len(valid)), replace=False)) if len(valid) else []
    result = truncation_test(fn, data, params, [valid[i] for i in pick], weights)
    changed = weights.loc[valid].ffill().diff().abs().sum(axis=1) > 0
    decision_dates = changed[changed].index
    rng2 = np.random.default_rng(seed)
    pick2 = np.sort(rng2.choice(len(decision_dates), size=min(n_dates, len(decision_dates)), replace=False)) if len(decision_dates) else []
    diag = truncation_test(fn, data, params, [decision_dates[i] for i in pick2], weights)
    result["decision_date_diagnostic"] = {**diag, "gating": False}
    return result


def g2_development(dev_net: pd.Series) -> dict[str, Any]:
    s = perf_stats(dev_net)
    ok = bool(s["sharpe"] is not None and s["newey_west_t"] is not None and s["sharpe"] >= 0.5 and s["newey_west_t"] >= 2.0)
    return {"pass": ok, **s}


def g3_validation(dev_stats: Mapping[str, Any], val_net: pd.Series) -> dict[str, Any]:
    s = perf_stats(val_net)
    dev_sharpe, val_sharpe = dev_stats.get("sharpe"), s["sharpe"]
    ok = bool(dev_sharpe is not None and val_sharpe is not None and dev_sharpe > 0 and val_sharpe > 0
              and val_sharpe >= 0.4 and val_sharpe >= 0.4 * dev_sharpe)
    return {"pass": ok, **s}


def run_length_shuffle(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Block shuffle of runs: invested and out-of-market spells are permuted separately and re-interleaved with the
    same starting state, so invested-day count and the spell-length distribution are preserved exactly."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return arr.copy()
    state = arr != 0
    boundaries = np.flatnonzero(state[1:] != state[:-1]) + 1
    blocks = np.split(arr, boundaries)
    first_on = bool(state[0])
    on_blocks = [b for b in blocks if b[0] != 0]
    off_blocks = [b for b in blocks if b[0] == 0]
    on_order = rng.permutation(len(on_blocks))
    off_order = rng.permutation(len(off_blocks))
    out: list[np.ndarray] = []
    i_on = i_off = 0
    on_turn = first_on
    for _ in blocks:
        if on_turn:
            out.append(on_blocks[on_order[i_on]])
            i_on += 1
        else:
            out.append(off_blocks[off_order[i_off]])
            i_off += 1
        on_turn = not on_turn
    return np.concatenate(out)


def timing_null_draws(positions: pd.Series, asset_ret: pd.Series, *, n_draws: int = N_NULL_DRAWS, seed: int = SEED) -> np.ndarray:
    pos = positions.fillna(0.0).to_numpy(dtype=float)
    ret = asset_ret.reindex(positions.index).fillna(0.0).to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    return np.array([float(np.mean(run_length_shuffle(pos, rng) * ret)) for _ in range(n_draws)])


def spell_frames(positions: pd.DataFrame, returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Collapse daily rows into spells (maximal runs of identical weight vectors, i.e. between weight changes).

    Spell returns are the SUM of the daily asset returns over the spell (so weight . spell return equals the sum of the
    daily gross returns of the constant-weight book).  An asset is available in a spell only if it has a return on
    every day of the spell.  Returns (spell asset returns, spell weight vectors, spell lengths in days).
    """
    pos = positions.fillna(0.0)
    changed = (pos != pos.shift(1)).any(axis=1)
    sid = changed.cumsum().to_numpy()
    rets = returns.reindex(index=pos.index, columns=pos.columns)
    spell_ret = rets.groupby(sid).sum(min_count=1)
    spell_ret = spell_ret.where(~rets.isna().groupby(sid).any())
    spell_pos = pos.groupby(sid).first()
    days = pd.Series(1, index=pos.index).groupby(sid).sum().astype(float)
    return spell_ret, spell_pos, days


def allocation_null_draws(
    spell_returns: pd.DataFrame, spell_positions: pd.DataFrame, spell_days: pd.Series, *,
    n_draws: int = N_NULL_DRAWS, seed: int = SEED,
) -> np.ndarray:
    """One random asset permutation per spell (rebalance), held until the next weight change.

    Each draw is the mean daily gross return = sum over valid spells of (permuted weight . spell return) divided by the
    days of those spells; spells whose names cannot be filled are NaN in every draw and excluded.
    """
    rng = np.random.default_rng(seed)
    days = spell_days.to_numpy(dtype=float)
    draws = []
    for _ in range(n_draws):
        s = matched_random_selection_returns(spell_returns, spell_positions, rng).to_numpy(dtype=float)
        ok = np.isfinite(s)
        draws.append(float(s[ok].sum() / days[ok].sum()) if ok.any() else float("nan"))
    return np.array(draws)


def g4_matched_null(
    null_type: str,
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    dev_start: pd.Timestamp,
    dev_end: pd.Timestamp,
    *,
    n_draws: int = N_NULL_DRAWS,
    seed: int = SEED,
) -> dict[str, Any]:
    """Development mean gross return versus ``n_draws`` action-matched random books (gross: nulls pay no cost)."""
    cols = list(weights.columns)
    pos = weights.shift(1).fillna(0.0)
    pos = pos.loc[(pos.index >= dev_start) & (pos.index <= dev_end)]
    rets = returns.reindex(index=pos.index, columns=cols)
    if null_type == "timing":
        col = cols[0]
        observed = float((pos[col] * rets[col].fillna(0.0)).mean())
        draws = timing_null_draws(pos[col], rets[col], n_draws=n_draws, seed=seed)
    elif null_type == "allocation":
        # one permutation per rebalance (spell); the observed statistic is computed on the same spell frame and mask
        spell_ret, spell_pos, spell_days = spell_frames(pos, rets)
        need = (spell_pos != 0).sum(axis=1)
        avail = spell_ret.notna().sum(axis=1)
        ok = (need <= avail).to_numpy()
        spell_gross = (spell_pos * spell_ret.fillna(0.0)).sum(axis=1).to_numpy(dtype=float)
        observed = float(spell_gross[ok].sum() / spell_days.to_numpy(dtype=float)[ok].sum())
        draws = allocation_null_draws(spell_ret, spell_pos, spell_days, n_draws=n_draws, seed=seed)
    else:
        raise StrategySearchError(f"unknown null type {null_type}")
    res = action_matched_null_p(observed, draws, alternative="greater")
    return {"pass": bool(res["p"] <= 0.05), "observed_mean_daily_gross": observed, "null_type": null_type, **res}


def dsr_gate(dev_net: pd.Series, prior_trial_sharpes: Sequence[float], round_trial_sharpes: Sequence[float]) -> dict[str, Any]:
    """Deflated Sharpe probability >= 0.95 with trials = every candidate tested so far (ledger + this round).

    Sharpe ratios are unannualised daily ones, the unit ``deflated_sharpe_probability`` expects.
    """
    trial_sharpes = [float(x) for x in list(prior_trial_sharpes) + list(round_trial_sharpes)]
    res = deflated_sharpe_probability(dev_net.dropna().to_numpy(dtype=float), trial_sharpes)
    prob = res["probability"]
    return {"pass": bool(np.isfinite(prob) and prob >= 0.95), "n_trials": len(trial_sharpes),
            "trial_sharpe_std": float(np.std(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else None, **res}


def g6_robustness(
    base_dev_stats: Mapping[str, Any],
    dev_net: pd.Series,
    variant_sharpes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    base = base_dev_stats.get("sharpe")
    n = len(dev_net)
    first, second = dev_net.iloc[: n // 2], dev_net.iloc[n // 2:]
    halves = [float(first.mean()) if len(first) else None, float(second.mean()) if len(second) else None]
    halves_ok = all(h is not None and h > 0 for h in halves)
    variants_ok = bool(base is not None and base > 0 and variant_sharpes
                       and all(v["sharpe"] is not None and v["sharpe"] >= 0.5 * base for v in variant_sharpes))
    return {"pass": bool(variants_ok and halves_ok), "variants_ok": variants_ok, "halves_positive": halves_ok,
            "half_mean_daily": halves, "variants": list(variant_sharpes)}


def g7_costs(dev_gross: pd.Series, dev_turnover: pd.Series, cost_bps: float) -> dict[str, Any]:
    wall = cost_wall_bps(dev_gross, dev_turnover)
    return {"pass": bool(wall is not None and wall >= 3.0 * cost_bps), "cost_wall_bps": wall, "assumed_cost_bps": cost_bps,
            "required_bps": 3.0 * cost_bps}


def g8_independence(
    net: pd.Series,
    crypto_reference: pd.Series | None,
    spy_returns: pd.Series,
    *,
    min_overlap: int = 60,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    ok = True
    if crypto_reference is None:
        out["crypto_core"] = {"corr": None, "overlap_days": 0, "note": "no reference supplied"}
        ok = False
    else:
        ref = crypto_reference.copy()
        # the crypto sleeve return stamped d+1 covers day d: restamp to the day the return is earned
        ref.index = ref.index - pd.Timedelta("1D")
        joined = pd.concat([net.rename("c"), ref.rename("r")], axis=1).dropna()
        corr = float(joined["c"].corr(joined["r"])) if len(joined) >= min_overlap else None
        out["crypto_core"] = {"corr": corr, "overlap_days": int(len(joined)), "limit": 0.5}
        ok = ok and corr is not None and np.isfinite(corr) and corr <= 0.5
    joined = pd.concat([net.rename("c"), spy_returns.rename("s")], axis=1).dropna()
    corr_spy = float(joined["c"].corr(joined["s"])) if len(joined) >= min_overlap else None
    out["spy_buy_and_hold"] = {"corr": corr_spy, "overlap_days": int(len(joined)), "limit": 0.7}
    ok = ok and corr_spy is not None and np.isfinite(corr_spy) and corr_spy <= 0.7
    return {"pass": bool(ok), **out}


# --------------------------------------------------------------------------- candidate evaluation


def evaluate_candidate(
    spec: Mapping[str, Any],
    data: Mapping[str, Any],
    returns: pd.DataFrame,
    *,
    validation_window: Sequence[str],
    crypto_reference: pd.Series | None,
    spy_returns: pd.Series,
    cost_bps: float = COST_BPS_ROUND_TRIP,
    n_draws: int = N_NULL_DRAWS,
    seed: int = SEED,
    fn: Callable[[Mapping[str, Any], Mapping[str, Any]], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Everything except G5 (which needs the whole round's Sharpe ratios)."""
    fn = fn or CANDIDATE_FUNCS[spec["id"]]
    params = dict(spec["params"])
    weights = fn(data, params)
    detail = backtest_detail(weights, returns, cost_bps)
    if detail.empty:
        raise StrategySearchError(f"{spec['id']}: no signal")
    first_day = detail.index[0]
    dev_start, dev_end = resolve_window(spec["development"], first_day)
    val_start = max(_utc_ts(validation_window[0]), dev_end + pd.Timedelta("1D"))
    val_end = _utc_ts(validation_window[1])
    dev = detail.loc[(detail.index >= dev_start) & (detail.index <= dev_end)]
    val = detail.loc[(detail.index >= val_start) & (detail.index <= val_end)]

    gates: dict[str, Any] = {}
    gates["G1"] = g1_truncation(fn, data, params, weights, seed=seed)
    gates["G2"] = g2_development(dev["net"])
    gates["G3"] = g3_validation(gates["G2"], val["net"])
    gates["G4"] = g4_matched_null(spec["null"], weights, returns, dev_start, dev_end, n_draws=n_draws, seed=seed)

    variants = []
    for variant in perturbation_param_sets(spec):
        vw = fn(data, variant)
        vd = backtest_detail(vw, returns, cost_bps)
        if vd.empty:
            variants.append({"params": variant, "sharpe": None, "days": 0})
            continue
        v_start = max(dev_start, vd.index[0])
        v_dev = vd.loc[(vd.index >= v_start) & (vd.index <= dev_end), "net"]
        s = perf_stats(v_dev)
        variants.append({"params": variant, "sharpe": s["sharpe"], "days": s["days"]})
    gates["G6"] = g6_robustness(gates["G2"], dev["net"], variants)
    gates["G7"] = g7_costs(dev["gross"], dev["turnover"], cost_bps)
    gates["G8"] = g8_independence(detail["net"], crypto_reference, spy_returns)

    return {
        "id": spec["id"],
        "params": params,
        "null": spec["null"],
        "windows": {"development": [str(dev_start.date()), str(dev_end.date())],
                    "validation": [str(val_start.date()), str(val_end.date())],
                    "first_return_date": str(first_day.date())},
        "dev": gates["G2"],
        "validation": gates["G3"],
        "gates": gates,
        "return_series_sha256": series_sha256(detail["net"]),
        "return_days": int(len(detail)),
        "_dev_net": dev["net"],
    }


def apply_dsr(results: list[dict[str, Any]], prior_trial_sharpes: Sequence[float]) -> list[dict[str, Any]]:
    """G5 over the cumulative trial set: ledger trials + every candidate of this round (ordering-free)."""
    round_sharpes = [float(r["dev"]["sharpe_daily"]) if r["dev"].get("sharpe_daily") is not None else 0.0 for r in results]
    for r in results:
        r["gates"]["G5"] = dsr_gate(r["_dev_net"], prior_trial_sharpes, round_sharpes)
    return results


GATE_ORDER = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


def verdict(result: Mapping[str, Any]) -> tuple[bool, str | None]:
    for g in GATE_ORDER:
        if not result["gates"].get(g, {}).get("pass", False):
            return False, g
    return True, None


# ------------------------------------------------------------------------------------- the ledger


def read_trials(path: Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def ledger_trial_sharpes(records: Sequence[Mapping[str, Any]]) -> list[float]:
    out = []
    for rec in records:
        s = (rec.get("dev") or {}).get("sharpe_daily")
        if s is not None and np.isfinite(s):
            out.append(float(s))
    return out


def ledger_record(result: Mapping[str, Any], round_no: int, *, now: datetime | None = None) -> dict[str, Any]:
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    gates = {g: {"pass": bool(result["gates"][g]["pass"])} for g in GATE_ORDER}
    passed, first_fail = verdict(result)
    return {
        "id": result["id"],
        "round": round_no,
        "status": "tested",
        "params": result["params"],
        "windows": result["windows"],
        "dev": _json_clean(result["dev"]),
        "validation": _json_clean(result["validation"]),
        "gates": gates,
        "all_gates_pass": passed,
        "first_failing_gate": first_fail,
        "return_series_sha256": result["return_series_sha256"],
        "timestamp_utc": stamp,
    }


def screened_out_records(round_cfg: Mapping[str, Any], round_no: int, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Ineligible candidates are logged with the registered reason; they are not trials and carry no Sharpe."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    return [{"id": str(name), "round": round_no, "status": "ineligible", "reason": str(reason), "timestamp_utc": stamp}
            for name, reason in round_cfg.get("screened_out", {}).items()]


def append_trial(path: Path, record: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(_json_clean(record), sort_keys=True, allow_nan=False) + "\n")


def _json_clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_json_clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def json_clean(value: Any) -> Any:
    return _json_clean(value)


# -------------------------------------------------------------------- crypto trend core reference


def crypto_reference_cache_key(config_path: Path, pickle_path: Path, as_of: str = "2026-10-01") -> str:
    """Hash of (config bytes, source pickle mtime and size, as-of, code version): changes whenever any input does."""
    config_bytes = Path(config_path).read_bytes()
    stat = Path(pickle_path).stat()
    payload = config_bytes + f"|{stat.st_mtime_ns}|{stat.st_size}|{as_of}|{CRYPTO_REFERENCE_CODE_VERSION}".encode()
    return sha256(payload).hexdigest()[:20]


def crypto_trend_core_reference(
    config_path: Path,
    pickle_path: Path,
    *,
    as_of: str = "2026-10-01",
    cache: bool = True,
) -> pd.Series:
    """crypto-trend-core-v1 combined book: equal-weight mean of the DON8 and EMA8 sleeves over the 17 coins.

    Built with ``trend_portfolio_forward.sleeve_daily_returns`` (canonical v3.1 accounting, 20 bps) on the cached
    ``multi_premia_data.pkl`` frames: MEXC 8h prices with BINANCE funding, not MEXC funding (venue substitution:
    MEXC funding history starts 2025-04); all 17 coins are in it and data ends 2026-09-11.  Leading all-zero days
    are dropped.  Stamps follow the repo: the value at d+1 covers day d.  The cache file name carries a hash of
    (config bytes, source pickle mtime and size, code version), so a stale cache is never reused.
    """
    import pickle

    from orderflow_edge_lab.trend_portfolio_forward import completed_bars, sleeve_daily_returns

    config_bytes = Path(config_path).read_bytes()
    cached = cache_dir() / f"crypto_trend_core_reference_{crypto_reference_cache_key(config_path, pickle_path, as_of)}.pkl"
    if cache and cached.exists():
        return pickle.loads(cached.read_bytes())
    cfg = json.loads(config_bytes.decode("utf-8"))
    symbols = [str(s) for s in cfg["groups"]["crypto"]]
    with open(pickle_path, "rb") as handle:
        frames, funding = pickle.load(handle)
    missing = [s for s in symbols if s not in frames]
    if missing:
        raise StrategySearchError(f"crypto reference missing frames: {missing}")
    as_of_ts = _utc_ts(as_of)
    clean = {s: completed_bars(frames[s], as_of_ts) for s in symbols}
    sleeves = sleeve_daily_returns({**cfg, "source": {**cfg["source"], "symbols": symbols}}, clean, funding)
    book = sleeves.mean(axis=1).dropna()
    book = book[book.index >= book[book != 0].index[0]]
    if cache:
        cached.write_bytes(pickle.dumps(book))
    return book
