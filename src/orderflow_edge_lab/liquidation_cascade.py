"""Liquidation-cascade reversal (strategy-search-v3 round 2, candidate V3R2C1_liquidation_cascade_reversal).

Implements ``config/strategy_search_v3_round2.json`` as registered.  Descriptive research code only: no promotion, no
filters, no order placement.

Registered rule
---------------
At every 1h bar close ``t``: ``r4 = close_t / close_(t-4h) - 1`` and ``oi4 = OI_t / OI_(t-4h) - 1`` (``OI_x`` = the last
5-minute ``sum_open_interest`` known at ``x``).  LONG event if ``r4 <= -5%`` and ``oi4 <= -5%``; SHORT event if
``r4 >= +5%`` and ``oi4 <= -5%``.  Enter at ``close_t`` in the event direction, exit at the close 24h later.  One open
position per contract (events while in a position are ignored); notional per trade = 10% of account equity; at most 10
concurrent positions (if more qualify at the same ``t`` take the largest ``|r4|``).  Return = perp price return plus
realized funding over ``(entry, exit]`` (positive rate: longs pay, shorts receive; funding on the entry notional),
14 bps round trip per trade on the notional; daily account returns aggregated by EXIT day.

Conventions and the registration ambiguities fixed here (before any real return was computed)
----------------------------------------------------------------------------------------------
* Panels are indexed by the bar END time on a complete hourly grid, so ``shift(L)`` is exactly ``t - L hours``.
* OI lookup: the record stamped ``create_time`` is a snapshot label whose meaning changed (state at ``create_time`` in
  2021-2023 files, state at ``create_time + 5 min`` from about March 2024: see ``binance_futures_metrics``).  To use
  nothing after ``x`` in either era, ``OI_x`` is the last record with ``create_time <= x - OI_SNAPSHOT_LAG_MINUTES``
  (5).  ``OI_SNAPSHOT_LAG_MINUTES = 0`` reproduces the literal "stamp at or before x".
* Thresholds are compared with ``<=`` / ``>=`` and a 1e-12 tolerance, so a move of exactly 5.000% (which float division
  can land a hair on the wrong side of) is an event.  ``OI_(t-4h) <= 0`` makes ``oi4`` undefined: no event.
* A contract whose position exits at ``t`` is free again at ``t`` (the exit close is the same print a new entry gets).
* Ties in ``|r4|`` are broken by column (contract) order.
* ``10% of equity at entry`` is applied as a fixed fraction of the account (weights are fractions of equity, as in
  round 1 and in ``leverage_sim``); the daily account return is the sum over trades exiting that UTC day (a 00:00 exit
  belongs to the new day) of ``weight * (side * (price return - funding sum)) - cost``.
* Exit price: the close at ``entry + hold``; if the contract has no bar there, its last close in ``(entry, exit]``
  (flat if none).  A trade whose exit is after ``max_exit`` or whose exit lies beyond the data is not taken.
* Entries start at ``params['trade_start']`` (the development start, 2021-12-01 00:00 UTC): closes before it are never
  traded (BTCUSDT carries OI from 2021-11-30 for the look-back only), also in the G4 candidate pool.
* An event at close ``t`` needs perp quote volume > 0 in the bar ending at ``t`` (the archive keeps flat zero-volume
  bars after a delisting); the same holds for G4 candidates.  The raw events dropped by this are counted.
* Open-interest rows with ``sum_open_interest <= 0`` are treated as missing: the as-of lookup skips them.
* ``weights`` rows: NaN = no entry decided at that close; an event row holds ``+/-0.10`` for the entered contracts and
  0 for the rest.  The parameters travel with the frame in ``weights.attrs["params"]``.

Null (G4, registered): each real development trade is replaced by a trade in the same contract, same direction and the
same calendar month (of its entry) at a uniformly random 1h close; statistic = mean per-trade gross return.  Candidate
closes need a finite entry and exit price and an exit on or before the development end (nothing after it is read).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as fa
from orderflow_edge_lab import binance_futures_metrics as bfm
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab.binance_futures_archive import base_name
from orderflow_edge_lab.perp_basis_strategy import apply_cumulative_dsr, validate_funding  # noqa: F401  (re-export)
from orderflow_edge_lab.review_methods import action_matched_null_p

CANDIDATE_ID = "V3R2C1_liquidation_cascade_reversal"
DEFAULT_PARAMS: dict[str, Any] = {"price_threshold": 0.05, "oi_threshold": 0.05, "hold_hours": 24,
                                  "lookback_hours": 4}
POSITION_FRACTION = 0.10
MAX_CONCURRENT = 10
COST_BPS_ROUND_TRIP = 14.0
NULL_SEED = 20261012
N_NULL_DRAWS = 999
PERIODS_PER_YEAR = 365
OI_SNAPSHOT_LAG_MINUTES = 5
THRESHOLD_TOLERANCE = 1e-12
STALE_OI_MINUTES = 60.0
STALE_EVENT_OI_MINUTES = 30.0


class CascadeError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ panels


def hourly_grid(perp: Mapping[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """Complete hourly bar-end grid from the first to the last bar of any contract."""
    if not perp:
        raise CascadeError("no perp data")
    first = min(f.index[0] for f in perp.values())
    last = max(f.index[-1] for f in perp.values())
    return pd.date_range(first, last, freq="1h")


def asof_values(series: pd.Series, grid: pd.DatetimeIndex, lag_minutes: float = OI_SNAPSHOT_LAG_MINUTES
                ) -> tuple[np.ndarray, np.ndarray]:
    """Last value with ``create_time <= x - lag`` for every ``x`` in ``grid`` and its age in minutes (NaN if none).

    Never reads a record stamped after ``x - lag`` (``searchsorted(side='right') - 1``).
    """
    n = len(grid)
    series = series[series.to_numpy(dtype=float) > 0.0]  # rows <= 0 (or NaN) are missing data, not a value
    if len(series) == 0:
        return np.full(n, np.nan), np.full(n, np.nan)
    ts = pd.DatetimeIndex(series.index).as_unit("ns").asi8
    if (np.diff(ts) < 0).any():
        raise CascadeError("open-interest series is not sorted")
    vals = series.to_numpy(dtype=float)
    grid_ns = pd.DatetimeIndex(grid).as_unit("ns").asi8
    pos = np.searchsorted(ts, grid_ns - int(round(lag_minutes * 60e9)), side="right") - 1
    ok = pos >= 0
    safe = np.where(ok, pos, 0)
    values = np.where(ok, vals[safe], np.nan)
    age = np.where(ok, (grid_ns - ts[safe]) / 60e9, np.nan)
    return values, age


def build_panels(perp: Mapping[str, pd.DataFrame], oi: Mapping[str, pd.Series], *,
                 oi_lag_minutes: float = OI_SNAPSHOT_LAG_MINUTES) -> dict[str, pd.DataFrame]:
    """``close`` (perp close), ``volume`` (perp quote volume of the bar), ``oi`` (as-of open interest) and ``oi_age``
    (minutes since the as-of record was stamped) on the hourly grid; columns = contracts."""
    grid = hourly_grid(perp)
    names = list(perp)
    close = pd.concat({n: perp[n]["close"].reindex(grid) for n in names}, axis=1)
    volume = pd.concat({n: perp[n]["quote_volume"].reindex(grid) for n in names}, axis=1)
    looked = {n: asof_values(oi[n], grid, oi_lag_minutes) if n in oi
              else (np.full(len(grid), np.nan), np.full(len(grid), np.nan)) for n in names}
    oi_panel = pd.concat({n: pd.Series(looked[n][0], index=grid) for n in names}, axis=1)
    age_panel = pd.concat({n: pd.Series(looked[n][1], index=grid) for n in names}, axis=1)
    return {"close": close, "volume": volume, "oi": oi_panel, "oi_age": age_panel}


def oi_staleness(perp: Mapping[str, pd.DataFrame], oi: Mapping[str, pd.Series], *,
                 oi_lag_minutes: float = OI_SNAPSHOT_LAG_MINUTES) -> dict[str, Any]:
    """Descriptive: per contract the number of trading hours whose as-of OI record is older than 60 minutes, or absent."""
    grid = hourly_grid(perp)
    out: dict[str, Any] = {}
    for name, frame in perp.items():
        _, age = asof_values(oi.get(name, pd.Series(dtype=float)), grid, oi_lag_minutes)
        traded = pd.Series(frame["quote_volume"].reindex(grid).to_numpy(dtype=float) > 0, index=grid)
        age_t = age[traded.to_numpy()]
        out[name] = {"trading_hours": int(traded.sum()), "hours_without_oi": int(np.isnan(age_t).sum()),
                     "hours_oi_older_than_60min": int((age_t > STALE_OI_MINUTES).sum()),
                     "max_oi_age_hours": float(np.nanmax(age_t) / 60.0) if np.isfinite(age_t).any() else None}
    return out


# ------------------------------------------------------------------------------------------------ signal


def _lag(values: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(values, np.nan)
    if n < len(values):
        out[n:] = values[:-n]
    return out


def _start_ok(index: pd.DatetimeIndex, params: Mapping[str, Any]) -> np.ndarray:
    start = params.get("trade_start")
    if start is None:
        return np.ones(len(index), dtype=bool)
    ts = pd.Timestamp(start)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return np.asarray(index >= ts)


def _volume_ok(data: Mapping[str, Any], close: pd.DataFrame) -> np.ndarray:
    if "volume" not in data:
        raise CascadeError("panels without perp quote volume: events need volume > 0 in the bar")
    vol = data["volume"].reindex(index=close.index, columns=close.columns).to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        return vol > 0.0


def event_matrices(data: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """``r4`` / ``oi4`` and the event masks (rows = hourly grid, columns = contracts).

    ``raw_long`` / ``raw_short`` hold the price and open-interest conditions only; ``long`` / ``short`` are the tradable
    events: raw events at closes on or after ``trade_start`` whose bar has quote volume > 0.
    """
    lookback = int(params["lookback_hours"])
    if lookback < 1:
        raise CascadeError("lookback_hours must be >= 1")
    p, o = float(params["price_threshold"]), float(params["oi_threshold"])
    close = data["close"]
    c = close.to_numpy(dtype=float)
    oi_now = data["oi"].reindex(index=close.index, columns=close.columns).to_numpy(dtype=float)
    c0, oi0 = _lag(c, lookback), _lag(oi_now, lookback)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where((c0 > 0) & (c > 0), c / c0 - 1.0, np.nan)
        oi4 = np.where((oi0 > 0) & np.isfinite(oi_now), oi_now / oi0 - 1.0, np.nan)
    with np.errstate(invalid="ignore"):
        drop = oi4 <= -o + THRESHOLD_TOLERANCE
        raw_long = (r <= -p + THRESHOLD_TOLERANCE) & drop
        raw_short = (r >= p - THRESHOLD_TOLERANCE) & drop
    tradable = _volume_ok(data, close) & _start_ok(close.index, params)[:, None]
    return {"r4": r, "oi4": oi4, "raw_long": raw_long, "raw_short": raw_short, "long": raw_long & tradable,
            "short": raw_short & tradable}


def event_report(data: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    """Descriptive counts (no rule uses them): raw events and how many each filter removed, and OI staleness.

    ``dropped_dead_bar``: raw events at closes on or after ``trade_start`` whose bar has no volume.
    ``dropped_before_start``: raw events at closes before ``trade_start``.  ``tradable_with_oi_older_than_30min``:
    tradable events whose as-of OI record was older than 30 minutes at ``t`` or ``t - lookback`` (they stay events).
    ``price_trigger_without_oi``: price condition met at a tradable close but OI missing at ``t`` or ``t - lookback``.
    """
    ev = event_matrices(data, params)
    close = data["close"]
    lookback = int(params["lookback_hours"])
    p = float(params["price_threshold"])
    start_ok = _start_ok(close.index, params)[:, None]
    vol_ok = _volume_ok(data, close)
    raw = ev["raw_long"] | ev["raw_short"]
    tradable = ev["long"] | ev["short"]
    out: dict[str, Any] = {
        "raw_events_long": int(ev["raw_long"].sum()), "raw_events_short": int(ev["raw_short"].sum()),
        "dropped_dead_bar_long": int((ev["raw_long"] & start_ok & ~vol_ok).sum()),
        "dropped_dead_bar_short": int((ev["raw_short"] & start_ok & ~vol_ok).sum()),
        "dropped_before_start": int((raw & ~start_ok).sum()),
        "tradable_events_long": int(ev["long"].sum()), "tradable_events_short": int(ev["short"].sum())}
    with np.errstate(invalid="ignore"):
        trigger = (ev["r4"] <= -p + THRESHOLD_TOLERANCE) | (ev["r4"] >= p - THRESHOLD_TOLERANCE)
    out["price_trigger_without_oi"] = int((trigger & start_ok & vol_ok & ~np.isfinite(ev["oi4"])).sum())
    if "oi_age" in data:
        age = data["oi_age"].reindex(index=close.index, columns=close.columns).to_numpy(dtype=float)
        with np.errstate(invalid="ignore"):
            stale = (age > STALE_EVENT_OI_MINUTES) | (_lag(age, lookback) > STALE_EVENT_OI_MINUTES)
        out["tradable_with_oi_older_than_30min"] = int((tradable & stale).sum())
    else:
        out["tradable_with_oi_older_than_30min"] = None
    return out


def cascade_weights(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    """Entries decided at every hourly close (see the module docstring).  Strictly causal: row ``t`` uses data <= t."""
    p = {**DEFAULT_PARAMS, **dict(params)}
    close = data["close"]
    hold_ns = int(p["hold_hours"]) * 3600 * 10**9
    if int(p["hold_hours"]) < 1:
        raise CascadeError("hold_hours must be >= 1")
    ev = event_matrices(data, p)
    any_event = (ev["long"] | ev["short"]).any(axis=1)
    out = np.full(close.shape, np.nan)
    index_ns = pd.DatetimeIndex(close.index).as_unit("ns").asi8
    open_until: dict[int, int] = {}  # column -> exit time (ns) of the open position
    for i in np.flatnonzero(any_event):
        t_ns = int(index_ns[i])
        for j in [j for j, exit_ns in open_until.items() if exit_ns <= t_ns]:
            del open_until[j]
        capacity = MAX_CONCURRENT - len(open_until)
        if capacity <= 0:
            continue
        cols = [int(j) for j in np.flatnonzero(ev["long"][i] | ev["short"][i]) if int(j) not in open_until]
        if not cols:
            continue
        cols.sort(key=lambda j: (-abs(float(ev["r4"][i, j])), j))
        row = np.zeros(close.shape[1])
        for j in cols[:capacity]:
            row[j] = POSITION_FRACTION if ev["long"][i, j] else -POSITION_FRACTION
            open_until[j] = t_ns + hold_ns
        out[i] = row
    weights = pd.DataFrame(out, index=close.index, columns=close.columns)
    weights.attrs["params"] = dict(p)
    return weights


# ------------------------------------------------------------------------------------------- accounting


@dataclass
class CascadeInputs:
    data: dict[str, pd.DataFrame]
    funding: Mapping[str, pd.DataFrame]
    max_exit: pd.Timestamp | None = None
    mark: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    perp_hl: Mapping[str, pd.DataFrame] = field(default_factory=dict)  # perp 1h high / low: liquidation-check fallback


def make_inputs(universe: Mapping[str, Any], *, max_exit: pd.Timestamp | str | None = None,
                oi_lag_minutes: float = OI_SNAPSHOT_LAG_MINUTES) -> CascadeInputs:
    """``universe`` as returned by ``load_data`` (keys ``perp``, ``oi``, ``funding``, ``mark``)."""
    cap = None if max_exit is None else pd.Timestamp(max_exit)
    if cap is not None and cap.tzinfo is None:
        cap = cap.tz_localize("UTC")
    validate_funding(universe["funding"])
    return CascadeInputs(data=build_panels(universe["perp"], universe["oi"], oi_lag_minutes=oi_lag_minutes),
                         funding=universe["funding"], max_exit=cap, mark=universe.get("mark", {}),
                         perp_hl=universe.get("perp_hl", {}))


def _params_of(weights: pd.DataFrame, params: Mapping[str, Any] | None) -> dict[str, Any]:
    p = dict(DEFAULT_PARAMS)
    p.update(weights.attrs.get("params", {}) if params is None else params)
    return p


def unit_panel(inputs: CascadeInputs, hold_hours: int) -> dict[str, Any]:
    """For an entry at every grid row and contract: entry/exit price, price return and funding sum over (entry, exit].

    ``unit`` = price return minus the funding sum = the return of one unit of LONG notional (a short earns ``-unit``).
    ``valid`` marks rows whose exit is inside the grid and on or before ``max_exit``.  A contract without a bar at the
    exit uses its last close up to the exit (forward fill; flat if it has no bar after the entry).
    """
    hold = int(hold_hours)
    close = inputs.data["close"]
    idx = close.index
    n, m = close.shape
    c = close.to_numpy(dtype=float)
    cf = close.ffill().to_numpy(dtype=float)
    exit_times = idx + pd.Timedelta(hours=hold)
    valid = np.zeros(n, dtype=bool)
    if hold < n:
        valid[:n - hold] = True
    if inputs.max_exit is not None:
        valid &= np.asarray(exit_times <= inputs.max_exit)
    p1 = np.full((n, m), np.nan)
    if hold < n:
        p1[:n - hold] = cf[hold:]
    with np.errstate(divide="ignore", invalid="ignore"):
        price = np.where((c > 0) & np.isfinite(p1) & valid[:, None], p1 / c - 1.0, np.nan)
    fsum = np.zeros((n, m))
    idx_ns = pd.DatetimeIndex(idx).as_unit("ns").asi8
    exit_ns = idx_ns + hold * 3600 * 10**9
    for j, name in enumerate(close.columns):
        f = inputs.funding.get(base_name(name))
        if f is None or len(f) == 0:
            continue
        ts = pd.DatetimeIndex(f.index).as_unit("ns").asi8
        cs = np.concatenate([[0.0], np.cumsum(f["rate"].to_numpy(dtype=float))])
        fsum[:, j] = cs[np.searchsorted(ts, exit_ns, side="right")] - cs[np.searchsorted(ts, idx_ns, side="right")]
    if np.isnan(fsum).any():
        raise CascadeError("NaN funding sum: non-finite funding rates must never be treated as zero")
    return {"exit_times": exit_times, "valid": valid, "p0": c, "p1": p1, "price": price, "funding_sum": fsum,
            "unit": price - fsum, "columns": list(close.columns)}


TRADE_COLUMNS = ["entry_time", "exit_time", "symbol", "mark_key", "side", "weight", "entry_price", "exit_price",
                 "price_return", "funding_return", "unit_return", "trade_gross", "price_pnl", "funding_pnl", "gross",
                 "cost", "net", "turnover", "row", "col"]


def build_trades(weights: pd.DataFrame, inputs: CascadeInputs, params: Mapping[str, Any] | None = None,
                 cost_bps: float = COST_BPS_ROUND_TRIP) -> pd.DataFrame:
    """One row per taken trade.  ``trade_gross`` = side * unit return (per unit of notional); the account columns
    (``price_pnl``, ``funding_pnl``, ``gross``, ``cost``, ``net``) are fractions of equity; ``turnover`` = 2 |weight|
    (entry plus exit) so ``cost = turnover * cost_bps / 2 / 1e4``.  Trades without a usable exit are dropped (counted in
    ``attrs['diagnostics']``)."""
    p = _params_of(weights, params)
    close = inputs.data["close"]
    rows_all = close.index.get_indexer(weights.index)
    if (rows_all < 0).any():
        raise CascadeError("weights rows outside the price grid")
    unknown = [c for c in weights.columns if c not in close.columns]
    if unknown:
        raise CascadeError(f"weights for instruments without panel data: {unknown[:5]}")
    wv = weights.reindex(columns=close.columns).fillna(0.0).to_numpy(dtype=float)
    r_local, cols = np.nonzero(wv)
    rows = rows_all[r_local]
    panel = unit_panel(inputs, int(p["hold_hours"]))
    price = panel["price"][rows, cols]
    usable = np.isfinite(price)
    diagnostics = {"entries": int(len(rows)), "dropped_unusable_exit": int((~usable).sum())}
    rows, cols, r_local = rows[usable], cols[usable], r_local[usable]
    w = wv[r_local, cols]
    price = price[usable]
    fsum = panel["funding_sum"][rows, cols]
    names = np.asarray(panel["columns"], dtype=object)[cols]
    out = pd.DataFrame({
        "entry_time": close.index[rows], "exit_time": panel["exit_times"][rows], "symbol": names,
        "mark_key": [base_name(s) for s in names], "side": np.sign(w), "weight": w,
        "entry_price": panel["p0"][rows, cols], "exit_price": panel["p1"][rows, cols], "price_return": price,
        "funding_return": -fsum, "unit_return": price - fsum, "trade_gross": np.sign(w) * (price - fsum),
        "price_pnl": w * price, "funding_pnl": -w * fsum, "gross": w * (price - fsum),
        "cost": np.abs(w) * cost_bps / 1e4, "net": w * (price - fsum) - np.abs(w) * cost_bps / 1e4,
        "turnover": 2.0 * np.abs(w), "row": rows, "col": cols}, columns=TRADE_COLUMNS)
    out.attrs["diagnostics"] = diagnostics
    return out


DETAIL_COLUMNS = ["gross", "net", "turnover", "price_pnl", "funding_pnl", "cost"]


def daily_detail(trades: pd.DataFrame, windows: Sequence[tuple[pd.Timestamp, pd.Timestamp]] | None = None
                 ) -> pd.DataFrame:
    """Daily gross / net / turnover stamped by the UTC day of the EXIT.

    Without ``windows`` the series is zero-filled between the first and last exit day.  With ``windows`` (the registered
    development and validation windows) every day of each window is present, zero where nothing exited, so a window
    with a quiet start or end is not shortened; a trade that exits outside all windows is an error.
    """
    if trades.empty:
        return pd.DataFrame({c: [] for c in DETAIL_COLUMNS}, index=pd.DatetimeIndex([], tz="UTC"))
    day = pd.DatetimeIndex(trades["exit_time"]).normalize()
    daily = trades[DETAIL_COLUMNS].groupby(day).sum()
    if windows:
        full = pd.DatetimeIndex(sorted({d for lo, hi in windows for d in pd.date_range(lo, hi, freq="D", tz="UTC")}))
        outside = daily.index.difference(full)
        if len(outside):
            raise CascadeError(f"trades exit outside the registered windows: {[str(d.date()) for d in outside[:5]]}")
    else:
        full = pd.date_range(daily.index[0], daily.index[-1], freq="D", tz="UTC")
    return daily.reindex(full).fillna(0.0)


def make_detail_fn(inputs: CascadeInputs, windows: Sequence[tuple[pd.Timestamp, pd.Timestamp]] | None = None
                   ) -> Callable[[pd.DataFrame, Any, float], pd.DataFrame]:
    """``detail_fn(weights, returns, cost_bps)`` for ``strategy_search_round2.evaluate_candidate_general``.

    ``windows`` = the registered (development, validation) windows to zero-fill over (see ``daily_detail``)."""

    def account(weights: pd.DataFrame, returns: Any, cost_bps: float) -> pd.DataFrame:
        return daily_detail(build_trades(weights, inputs, None, cost_bps), windows)

    return account


# --------------------------------------------------------------------------------------------------- null


@dataclass
class NullGroup:
    """Trades of one (contract, calendar month): their sides and own candidate positions, plus the candidate closes."""

    col: int
    month: int  # year * 12 + month - 1
    sides: np.ndarray
    own_pos: np.ndarray  # position of each trade's own entry among ``cand_rows``
    cand_rows: np.ndarray  # grid rows (entry closes) of the same contract in the same month with a usable exit
    cand_unit: np.ndarray  # unit return of each candidate


def _month_number(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(index.year * 12 + index.month - 1)


def event_null_groups(weights: pd.DataFrame, inputs: CascadeInputs, dev_start: pd.Timestamp, dev_end: pd.Timestamp
                      ) -> tuple[list[NullGroup], float, int]:
    """Groups, observed statistic (mean per-trade gross return of the development trades) and the number of trades."""
    p = _params_of(weights, None)
    trades = build_trades(weights, inputs, None, 0.0)
    exit_day = pd.DatetimeIndex(trades["exit_time"]).normalize()
    dev = trades.loc[np.asarray((exit_day >= dev_start) & (exit_day <= dev_end))]
    if dev.empty:
        raise CascadeError("no development trades for the null")
    panel = unit_panel(inputs, int(p["hold_hours"]))
    idx = inputs.data["close"].index
    months = _month_number(idx)
    day_exit_ok = np.asarray(panel["exit_times"].normalize() <= dev_end)
    usable = np.isfinite(panel["unit"]) & day_exit_ok[:, None]
    usable &= _volume_ok(inputs.data, inputs.data["close"])                 # a live bar at the candidate close
    usable &= _start_ok(idx, p)[:, None]                                    # nothing before the development start
    trade_month = months[dev["row"].to_numpy()]
    groups: list[NullGroup] = []
    members: dict[tuple[int, int], list[int]] = {}
    for k, key in enumerate(zip(dev["col"].to_numpy().tolist(), trade_month.tolist(), strict=True)):
        members.setdefault(key, []).append(k)
    for (col, month), pos in sorted(members.items()):
        sel = np.asarray(pos)
        in_month = np.flatnonzero(months == month)
        cand_rows = in_month[usable[in_month, col]]
        own_rows = dev["row"].to_numpy()[sel]
        own_pos = np.searchsorted(cand_rows, own_rows)
        if (own_pos >= len(cand_rows)).any() or (cand_rows[own_pos] != own_rows).any():
            raise CascadeError("a real trade is not among its own null candidates")
        groups.append(NullGroup(int(col), int(month), dev["side"].to_numpy()[sel], own_pos, cand_rows,
                                panel["unit"][cand_rows, col]))
    observed = float(dev["trade_gross"].mean())
    return groups, observed, int(len(dev))


def null_draws(groups: list[NullGroup], n_trades: int, *, n_draws: int = N_NULL_DRAWS, seed: int = NULL_SEED,
               identity: bool = False) -> np.ndarray:
    """``n_draws`` null statistics.  ``identity=True`` keeps every trade where it is: it must reproduce the observed
    statistic exactly (used by the tests)."""
    rng = np.random.default_rng(seed)
    total = np.zeros(n_draws)
    for g in groups:
        if identity:
            pick = np.broadcast_to(g.own_pos, (n_draws, len(g.own_pos)))
        else:
            pick = rng.integers(0, len(g.cand_rows), size=(n_draws, len(g.sides)))
        total += (g.cand_unit[pick] * g.sides[None, :]).sum(axis=1)
    return total / n_trades


def event_null(weights: pd.DataFrame, inputs: CascadeInputs, dev_start: pd.Timestamp, dev_end: pd.Timestamp, *,
               n_draws: int = N_NULL_DRAWS, seed: int = NULL_SEED) -> dict[str, Any]:
    """G4: the observed mean per-trade gross return of the development trades against ``n_draws`` re-timings."""
    groups, observed, n_trades = event_null_groups(weights, inputs, dev_start, dev_end)
    draws = null_draws(groups, n_trades, n_draws=n_draws, seed=seed)
    res = action_matched_null_p(observed, draws, alternative="greater")
    return {"pass": bool(res["p"] <= 0.05), "observed_mean_trade_gross": observed, "null_type": "event",
            "accounting": "mean per-trade gross return (price + realized funding), same contract / direction / month, "
                          "uniformly random 1h close",
            "n_trades": n_trades, "n_groups": len(groups), **res}


def make_null_fn(inputs: CascadeInputs) -> Callable[..., dict[str, Any]]:
    """``null_fn(weights, dev_start, dev_end, n_draws=, seed=)``; the registered null seed (20261012) is fixed."""

    def null_fn(weights: pd.DataFrame, dev_start: pd.Timestamp, dev_end: pd.Timestamp, *, n_draws: int,
                seed: int) -> dict[str, Any]:
        return event_null(weights, inputs, dev_start, dev_end, n_draws=n_draws, seed=NULL_SEED)

    return null_fn


# ------------------------------------------------------------------------------------- spec and integrity


def candidate_spec(round_cfg: Mapping[str, Any]) -> dict[str, Any]:
    cands = round_cfg["candidates"]
    if len(cands) != 1 or cands[0]["id"] != CANDIDATE_ID:
        raise CascadeError(f"expected the single candidate {CANDIDATE_ID}")
    cand = cands[0]
    params = dict(DEFAULT_PARAMS)
    unknown = [k for k in cand.get("perturb", {}) if k not in params]
    if unknown:
        raise CascadeError(f"perturbed parameters not in params: {unknown}")
    null_type = str(cand["null"]).split()[0].strip(":,;").lower()
    if null_type != "event":
        raise CascadeError(f"unknown null type in {cand['null']!r}")
    spec = {**cand, "params": params, "null": null_type, "null_registered_text": cand["null"]}
    # amendments (in date order) restate registered fields before any data was loaded: the development window moved to
    # 2021-12-01 because open interest is published from then on
    for amendment in round_cfg.get("amendments", []):
        changes = amendment.get("changes", {})
        if isinstance(changes.get("development"), list):
            spec["development"] = [str(x) for x in changes["development"]]
        if isinstance(changes.get("validation"), list):
            spec["validation"] = [str(x) for x in changes["validation"]]
    # no entries before the development start (look-back history before it is read, never traded)
    spec["params"] = {**spec["params"], "trade_start": str(spec["development"][0])}
    return spec


def oi_integrity(perp: Mapping[str, pd.DataFrame], oi: Mapping[str, pd.Series], *, required_first: pd.Timestamp,
                 required_last: pd.Timestamp, active_from: pd.Timestamp) -> dict[str, Any]:
    """Open-interest coverage.  Raises ``CascadeError`` on non-finite values, a contract without any (positive) OI, a
    contract whose first positive record is after ``required_first`` (coverage from the sample start), or a contract
    still trading (volume > 0) at ``active_from`` whose last positive record is before ``required_last``.  Rows with
    ``sum_open_interest <= 0`` are missing data (the as-of lookup skips them); they are counted per contract."""
    problems: list[str] = []
    detail: dict[str, Any] = {}
    for name, frame in perp.items():
        series = oi.get(base_name(name))
        if series is None or len(series) == 0:
            problems.append(f"{name}: no open-interest records")
            continue
        if not np.isfinite(series.to_numpy(dtype=float)).all():
            problems.append(f"{name}: non-finite open interest")
        nonpositive = int((series.to_numpy(dtype=float) <= 0.0).sum())
        series = series[series.to_numpy(dtype=float) > 0.0]
        if len(series) == 0:
            problems.append(f"{name}: no positive open-interest records")
            continue
        traded = frame[frame["quote_volume"] > 0]
        last_bar = traded.index[-1] if len(traded) else None
        active = last_bar is not None and last_bar >= active_from
        info = {"first_record": str(series.index[0]), "last_record": str(series.index[-1]),
                "last_traded_bar": None if last_bar is None else str(last_bar), "active_at_end": bool(active),
                "nonpositive_rows_treated_as_missing": nonpositive}
        if series.index[0] > required_first:
            problems.append(f"{name}: first record {series.index[0]} is after {required_first}")
        if active and series.index[-1] < required_last:
            problems.append(f"{name}: trading at {active_from} but last record {series.index[-1]} < {required_last}")
        detail[name] = info
    if problems:
        raise CascadeError(f"{len(problems)} open-interest coverage problems: {problems[:10]}")
    return {"required_first": str(required_first), "required_last": str(required_last),
            "active_from": str(active_from), "symbols": len(detail),
            "nonpositive_rows_total": int(sum(v["nonpositive_rows_treated_as_missing"] for v in detail.values())),
            "per_symbol": detail}


# ------------------------------------------------------------------------------------------------ leverage


def positions_for_leverage(trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
                           ) -> tuple[pd.DataFrame, pd.Series]:
    """Trades whose EXIT day lies in ``[start, end]`` as a leverage-sim book, and their 1x costs stamped at the exit."""
    day = pd.DatetimeIndex(trades["exit_time"]).normalize()
    keep = np.asarray((day >= start) & (day <= end))
    sel = trades.loc[keep]
    positions = sel[["entry_time", "exit_time", "symbol", "mark_key", "weight", "entry_price", "unit_return"]]
    cost = pd.Series(sel["cost"].to_numpy(), index=pd.DatetimeIndex(sel["exit_time"]))
    return positions.reset_index(drop=True), cost


def mark_with_perp_fallback(mark: Mapping[str, pd.DataFrame], perp_hl: Mapping[str, pd.DataFrame] | None
                            ) -> dict[str, pd.DataFrame]:
    """Mark high / low where the mark archive has a bar, the perp 1h high / low in every other hour (as in the
    trend-core leverage study).  The frames carry ``is_mark`` so the fallback bars can be counted."""
    out: dict[str, pd.DataFrame] = {}
    for key in set(mark) | set(perp_hl or {}):
        m = mark.get(key)
        parts = []
        if m is not None and len(m):
            parts.append(m[["high", "low"]].assign(is_mark=True))
        q = (perp_hl or {}).get(key)
        if q is not None and len(q):
            q = q[["high", "low"]].dropna()
            if m is not None and len(m):
                q = q.loc[~q.index.isin(m.index)]
            parts.append(q.assign(is_mark=False))
        if parts:
            out[key] = pd.concat(parts).sort_index()
    return out


def _window_bar_counts(positions: pd.DataFrame, frames: Mapping[str, pd.DataFrame]) -> tuple[np.ndarray, np.ndarray]:
    """Per position: number of mark bars and of perp-fallback bars ending in ``(entry_time, exit_time]``."""
    n_mark = np.zeros(len(positions), dtype=int)
    n_fallback = np.zeros(len(positions), dtype=int)
    entry = pd.DatetimeIndex(positions["entry_time"]).as_unit("ns").asi8
    exit_ = pd.DatetimeIndex(positions["exit_time"]).as_unit("ns").asi8
    cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for i, key in enumerate(positions["mark_key"]):
        if key not in cache:
            f = frames.get(key)
            cache[key] = ((np.empty(0, dtype=np.int64), np.empty(0, dtype=bool)) if f is None or not len(f)
                          else (pd.DatetimeIndex(f.index).as_unit("ns").asi8, f["is_mark"].to_numpy(dtype=bool)
                                if "is_mark" in f else np.ones(len(f), dtype=bool)))
        ts, is_mark = cache[key]
        a, b = np.searchsorted(ts, entry[i], side="right"), np.searchsorted(ts, exit_[i], side="right")
        n_mark[i] = int(is_mark[a:b].sum())
        n_fallback[i] = int((~is_mark[a:b]).sum())
    return n_mark, n_fallback


def assess_trade_book(positions: pd.DataFrame, mark: Mapping[str, pd.DataFrame], period_costs: pd.Series, *,
                      config: lev.LeverageConfig = lev.LeverageConfig(), levels: tuple[int, ...] | None = None,
                      perp_hl: Mapping[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    """``leverage_sim.assess_leverage`` for positions that overlap in time.

    Same registered mechanics (mark-price liquidation per position, ruin, bootstrap), with three differences: the
    adverse excursion of every position is measured over its OWN window ``(entry_time, exit_time]``; its P&L and cost
    are stamped at the EXIT time so the daily returns match the gate accounting (daily returns by exit day); and hours
    without a mark-price bar (``perp_hl`` given) use the perp 1h high / low instead, counted in the report.
    """
    frames = mark_with_perp_fallback(mark, perp_hl) if perp_hl is not None else dict(mark)
    adverse, missing = lev.position_adverse_excursions(positions, frames)
    n_mark, n_fallback = _window_bar_counts(positions, frames)
    stamped = positions.assign(entry_time=positions["exit_time"])
    levels = tuple(levels if levels is not None else config.levels)
    report: dict[str, dict[str, Any]] = {}
    indices: np.ndarray | None = None
    for level in levels:
        sim = lev.simulate_leverage(stamped, adverse, period_costs, level, config=config)
        daily = sim["daily_returns"]
        if indices is None and len(daily):
            indices = lev.stationary_bootstrap_indices(len(daily), config.paths, config.horizon_days,
                                                       config.mean_block_days, config.seed)
        boot = lev.bootstrap_ruin_probability(daily, indices=indices, config=config)
        report[str(level)] = {
            "ruin_probability": boot["ruin_probability"], "median_final_equity_365d": boot["median_final_equity"],
            "p05_final_equity_365d": boot["p05_final_equity"], "n_liquidations": sim["n_liquidations"],
            "n_positions": sim["n_positions"], "liquidation_threshold": sim["liquidation_threshold"],
            "historical_final_equity": sim["final_equity"], "historical_min_equity": sim["min_equity"],
            "historical_max_drawdown": sim["max_drawdown"], "historical_ruin": sim["historical_ruin"],
            "daily_mean": float(daily.mean()) if len(daily) else None,
            "daily_std": float(daily.std(ddof=1)) if len(daily) > 1 else None}
    return {"levels": report, "max_safe_leverage": lev.max_safe_leverage(report, config.max_ruin_probability),
            "positions_without_any_bars": int(missing),
            "positions_without_mark_bars": int((n_mark == 0).sum()),
            "positions_using_perp_fallback_bars": int((n_fallback > 0).sum()),
            "perp_fallback_bars_in_windows": int(n_fallback.sum()), "mark_bars_in_windows": int(n_mark.sum()),
            "max_adverse_excursion": float(adverse.max()) if len(adverse) else 0.0,
            "stamping": "P&L and costs stamped at the position exit time (daily returns by exit day)",
            "config": {"maintenance_margin_rate": config.maintenance_margin_rate,
                       "liquidation_fee_rate": config.liquidation_fee_rate, "ruin_fraction": config.ruin_fraction,
                       "paths": config.paths, "mean_block_days": config.mean_block_days,
                       "horizon_days": config.horizon_days, "seed": config.seed,
                       "liquidation_fee_basis": "fraction of notional (L*|w|) on top of the lost margin |w|"}}


# ------------------------------------------------------------------------------------------------ loading


def load_data(symbols: list[str], *, end: str = fa.END_DATE, mark_start: str = "2023-06-01", workers: int = 24,
              fetch: fa.Fetcher = fa.http_fetch, directory: Any = None, metrics_directory: Any = None,
              oi_start: str = bfm.OI_LOAD_START, progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Perp (close, quote volume), funding, mark (high, low) and 5-minute OI of ``symbols`` from the archive.

    Perp / funding are loaded from the first month the archive has; mark prices from ``mark_start`` (one month before
    the validation start so positions entered just before it have their whole mark window).
    """
    base = directory if directory is not None else fa.cache_dir()

    def work(sym: str) -> tuple[str, dict[str, pd.DataFrame]]:
        return sym, {
            "perp": fa.load_dataset("perp", sym, end=end, fetch=fetch, directory=base),
            "funding": fa.load_dataset("funding", sym, end=end, fetch=fetch, directory=base),
            "mark": fa.load_dataset("mark", sym, end=end, start=mark_start, fetch=fetch, directory=base)}

    perp: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    mark: dict[str, pd.DataFrame] = {}
    perp_hl: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for done, (sym, parts) in enumerate(pool.map(work, symbols), start=1):
            if len(parts["perp"]) == 0:
                raise CascadeError(f"{sym}: no perp klines in the archive")
            perp[sym] = parts["perp"][list(fa.PERP_KEEP)]
            perp_hl[sym] = parts["perp"][list(fa.MARK_KEEP)]  # high / low: liquidation-check fallback
            funding[sym] = parts["funding"]
            if len(parts["mark"]):
                mark[sym] = parts["mark"][list(fa.MARK_KEEP)]
            if progress is not None:
                progress(done, len(symbols))
    metrics = bfm.load_metrics_universe(symbols, start=oi_start, end=end, workers=workers, fetch=fetch,
                                        directory=metrics_directory)
    provenance = {
        "symbols": list(symbols), "end": end, "mark_start": mark_start, "oi_start": oi_start,
        "per_instrument": {n: {"first_bar_end": str(f.index[0]), "last_bar_end": str(f.index[-1]), "rows": int(len(f))}
                           for n, f in perp.items()},
        "funding": {s: {"rows": int(len(f)), "first": str(f.index[0]) if len(f) else None,
                        "last": str(f.index[-1]) if len(f) else None,
                        "interval_hours": sorted({float(x) for x in f["interval_hours"].dropna().unique()})}
                    for s, f in funding.items()},
        "oi": metrics["provenance"]}
    return {"perp": perp, "oi": metrics["oi"], "funding": funding, "mark": mark, "perp_hl": perp_hl,
            "provenance": provenance}
