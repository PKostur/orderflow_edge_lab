"""Perp log-basis quintile sort, 8h hold (strategy-search-v3 round 1, candidate V3R1C1_logbasis_quintile_8h).

Implements ``config/strategy_search_v3_round1.json`` exactly as registered.  Descriptive research code only: no
promotion, no filters, no order placement.

Registered rule
---------------
At each funding settlement ``t`` in {00:00, 08:00, 16:00} UTC: ``y = ln(F_t) - ln(S_t)`` with ``F_t`` / ``S_t`` the close
of the perp / spot 1h bar ending at ``t``.  Eligible: perp listed >= 1 day, a spot bar ending at ``t``, trailing-24h perp
quote (USDT) volume (bars ending in ``(t-24h, t]``) strictly above ``volume_filter_usd``.  Sort eligible contracts into
``quantiles`` buckets by ``y``; long the lowest, short the highest, equal weight inside a leg, 0.5 gross per leg.
Entry at the perp close of the bar ending at ``t + entry_delay_hours``, exit ``hold_hours`` (8) later.  Position return =
perp price return plus realized funding: settlements in ``(entry, exit]`` pay ``-w * rate`` per unit weight (positive
rate: longs pay, shorts receive) on the entry notional.  Costs: 14 bps round trip = 7 bps per unit of traded notional,
turnover ``sum |w_new - w_old|`` at each rebalance (consecutive books overlap in the symbols they hold).

Conventions
-----------
* Panels are indexed by the bar END time; row ``t`` of ``data`` only holds information available at ``t`` (the
  trailing volume and the listing age are pre-computed causally from the hourly bars by ``build_event_panels``).
* ``basis_quintile_weights`` returns one row per settlement: NaN = not eligible (or fewer eligible contracts than
  ``quantiles``), 0 = eligible but not held.  The parameters travel with the frame in ``weights.attrs["params"]`` so
  the accounting and the null see the entry-delay perturbation.
* Daily series are stamped with the UTC day of the ENTRY of each 8h period (the P&L is earned in that day: entries at
  00/08/16 settle by 24:00; with the 1h delay the 17:00 period settles at 01:00 next day).
* A period only counts when its exit and all its funding settlements are inside the data (``max_exit``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab.binance_futures_archive import base_name
from orderflow_edge_lab.review_methods import action_matched_null_p, deflated_sharpe_null_consistent

CANDIDATE_ID = "V3R1C1_logbasis_quintile_8h"
SETTLEMENT_HOURS = (0, 8, 16)
EVENT_HOURS = (0, 1, 8, 9, 16, 17)  # settlements, +1h entry delay, and the exits 8h after each
DEFAULT_PARAMS: dict[str, Any] = {"quantiles": 5, "volume_filter_usd": 1_000_000.0, "entry_delay_hours": 0,
                                  "hold_hours": 8}
GROSS_PER_LEG = 0.5
COST_BPS_ROUND_TRIP = 14.0
NULL_SEED = 20261012
N_NULL_DRAWS = 999
PERIODS_PER_YEAR = 365


class PerpBasisError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ panels


def _ns(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(pd.DatetimeIndex(index).as_unit("ns").asi8)


def event_grid(first: pd.Timestamp, last: pd.Timestamp, hours: Sequence[int] = EVENT_HOURS) -> pd.DatetimeIndex:
    days = pd.date_range(first.normalize(), last.normalize(), freq="D", tz="UTC")
    stamps = sorted(d + pd.Timedelta(f"{int(h)}h") for d in days for h in hours)
    return pd.DatetimeIndex([s for s in stamps if first <= s <= last])


def trailing_volume(quote_volume: pd.Series, window_hours: int = 24) -> pd.Series:
    """Sum of the quote volume of the last ``window_hours`` hourly bars (a missing hour inside the span counts as 0).

    NaN until ``window_hours`` bars of history exist, i.e. the first value is dated 23h after the first bar END:
    the contract has been listed for at least ``window_hours`` hours.  Causal: value at ``t`` uses bars ending <= t.
    """
    full = pd.date_range(quote_volume.index[0], quote_volume.index[-1], freq="1h")
    hourly = quote_volume.reindex(full).fillna(0.0)
    return hourly.rolling(window_hours, min_periods=window_hours).sum()


def build_event_panels(perp: Mapping[str, pd.DataFrame], spot: Mapping[str, pd.DataFrame], *,
                       hours: Sequence[int] = EVENT_HOURS,
                       spot_scale: Mapping[str, float] | None = None) -> dict[str, pd.DataFrame]:
    """Event-hour panels (rows = bar-end times at ``hours``, columns = perp instruments): ``perp_close``,
    ``spot_close`` and ``perp_dv24`` (trailing 24h perp quote volume, NaN while the contract has been listed for
    less than a day).

    ``spot_close`` is the spot close of the matching pair times the contract multiplier ``k`` of the perp
    (``spot_scale[perp symbol]``, default 1; 1000PEPEUSDT -> 1000 * PEPEUSDT), so ``ln(perp) - ln(spot_close)`` equals
    the registered ``ln(F/k) - ln(S)``.  The perp price itself is never rescaled (returns, funding and liquidation are
    ratios on the perp)."""
    if not perp:
        raise PerpBasisError("no perp data")
    names = list(perp)
    first = min(f.index[0] for f in perp.values())
    last = max(f.index[-1] for f in perp.values())
    grid = event_grid(first, last, hours)
    close = pd.concat({n: perp[n]["close"].reindex(grid) for n in names}, axis=1)
    dv24 = pd.concat({n: trailing_volume(perp[n]["quote_volume"]).reindex(grid) for n in names}, axis=1)
    scale = spot_scale or {}
    spot_close = pd.concat({n: (spot[base_name(n)]["close"].reindex(grid) * float(scale.get(base_name(n), 1.0))
                                if base_name(n) in spot else pd.Series(np.nan, index=grid)) for n in names}, axis=1)
    return {"perp_close": close, "spot_close": spot_close, "perp_dv24": dv24}


# ------------------------------------------------------------------------------------------------ signal


def basis_quintile_weights(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    """Target weights at every settlement row of the panels (see the module docstring)."""
    q = int(params["quantiles"])
    if q < 2:
        raise PerpBasisError("quantiles must be >= 2")
    threshold = float(params["volume_filter_usd"])
    close = data["perp_close"]
    cols = close.columns
    spot = data["spot_close"].reindex(index=close.index, columns=cols)
    dv24 = data["perp_dv24"].reindex(index=close.index, columns=cols)
    rows = np.flatnonzero(np.isin(close.index.hour, SETTLEMENT_HOURS) & (close.index.minute == 0))
    index = close.index[rows]
    perp_v = close.to_numpy(dtype=float)[rows]
    spot_v = spot.to_numpy(dtype=float)[rows]
    vol_v = dv24.to_numpy(dtype=float)[rows]
    with np.errstate(divide="ignore", invalid="ignore"):
        y = np.where((perp_v > 0) & (spot_v > 0), np.log(perp_v) - np.log(spot_v), np.nan)
    with np.errstate(invalid="ignore"):
        eligible = np.isfinite(y) & (vol_v > threshold)
    out = np.full(y.shape, np.nan)
    for i in range(len(rows)):
        idx = np.flatnonzero(eligible[i])
        n = len(idx)
        if n < q:
            continue
        order = idx[np.argsort(y[i, idx], kind="stable")]
        bucket = (np.arange(n) * q) // n
        longs, shorts = order[bucket == 0], order[bucket == q - 1]
        out[i, idx] = 0.0
        out[i, longs] = GROSS_PER_LEG / len(longs)
        out[i, shorts] = -GROSS_PER_LEG / len(shorts)
    weights = pd.DataFrame(out, index=index, columns=cols)
    weights.attrs["params"] = dict(params)
    return weights


# ------------------------------------------------------------------------------------------- accounting


@dataclass
class BasisInputs:
    """Everything the accounting needs besides the weights."""

    data: dict[str, pd.DataFrame]
    perp: Mapping[str, pd.DataFrame]
    funding: Mapping[str, pd.DataFrame]
    max_exit: pd.Timestamp | None = None
    mark: Mapping[str, pd.DataFrame] = field(default_factory=dict)


def validate_funding(funding: Mapping[str, pd.DataFrame]) -> None:
    """Fail loudly if any funding rate is not finite."""
    bad = {s: int((~np.isfinite(f["rate"].to_numpy(dtype=float))).sum()) for s, f in funding.items() if len(f)}
    bad = {s: n for s, n in bad.items() if n}
    if bad:
        raise PerpBasisError(f"non-finite funding rates: {dict(list(bad.items())[:10])}")


def funding_integrity(perp: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.DataFrame], *,
                      required_last: pd.Timestamp, window_start: pd.Timestamp) -> dict[str, Any]:
    """Every contract still trading at ``required_last`` must have a funding settlement on or after it.

    A contract is *active* when its last perp bar ends at or after ``required_last``.  Contracts whose last bar ends in
    ``[window_start, required_last)`` (ended inside the final week) are listed, not failed.  Raises ``PerpBasisError`` when an
    active contract lacks the settlement (a truncated funding download would otherwise read as zero funding).
    """
    validate_funding(funding)
    active: dict[str, str | None] = {}
    ended: dict[str, str] = {}
    missing: list[str] = []
    for name, frame in perp.items():
        # the archive keeps publishing flat zero-volume bars after a delisting, so "trading" means volume > 0
        traded = frame[frame["quote_volume"] > 0] if "quote_volume" in frame.columns else frame
        if traded.empty:
            continue
        last_bar = traded.index[-1]
        base = base_name(name)
        f = funding.get(base)
        last_settlement = f.index[-1] if f is not None and len(f) else None
        if last_bar >= required_last:
            active[name] = None if last_settlement is None else str(last_settlement)
            if last_settlement is None or last_settlement < required_last:
                missing.append(name)
        elif last_bar >= window_start:
            ended[name] = str(last_bar)
    result = {"required_last_settlement": str(required_last), "window_start": str(window_start),
              "active_symbols": len(active), "last_settlement": active, "ended_in_final_week": ended,
              "missing": sorted(missing)}
    if missing:
        raise PerpBasisError(f"{len(missing)} active contracts have no funding settlement on or after {required_last}: "
                             f"{sorted(missing)[:10]}")
    return result


def basis_extreme_stats(data: Mapping[str, Any], params: Mapping[str, Any], *, limit: float = 0.10,
                        top: int = 20) -> dict[str, Any]:
    """Descriptive only (no rule change): per contract the count and share of settlements with ``|y| > limit``.

    Shares are over settlements with a finite basis; ``n_extreme_eligible`` counts the same events among eligible
    settlements (volume above the filter).  ``top`` contracts by share (ties by count, then name).
    """
    close = data["perp_close"]
    cols = close.columns
    spot = data["spot_close"].reindex(index=close.index, columns=cols)
    dv24 = data["perp_dv24"].reindex(index=close.index, columns=cols)
    rows = np.flatnonzero(np.isin(close.index.hour, SETTLEMENT_HOURS) & (close.index.minute == 0))
    perp_v, spot_v = close.to_numpy(dtype=float)[rows], spot.to_numpy(dtype=float)[rows]
    vol_v = dv24.to_numpy(dtype=float)[rows]
    with np.errstate(divide="ignore", invalid="ignore"):
        y = np.where((perp_v > 0) & (spot_v > 0), np.log(perp_v) - np.log(spot_v), np.nan)
        finite = np.isfinite(y)
        extreme = finite & (np.abs(y) > limit)
        eligible_extreme = extreme & (vol_v > float(params["volume_filter_usd"]))
    per_symbol = []
    for j, name in enumerate(cols):
        n_obs = int(finite[:, j].sum())
        if n_obs == 0:
            continue
        n_ext = int(extreme[:, j].sum())
        per_symbol.append({"symbol": str(name), "n_settlements": n_obs, "n_extreme": n_ext,
                           "share_extreme": n_ext / n_obs, "n_extreme_eligible": int(eligible_extreme[:, j].sum())})
    ranked = sorted(per_symbol, key=lambda r: (-r["share_extreme"], -r["n_extreme"], r["symbol"]))
    return {"limit": limit, "n_symbols": len(per_symbol), "n_extreme_total": int(extreme.sum()),
            "n_settlements_total": int(finite.sum()), "top_by_share": ranked[:top], "per_symbol": per_symbol}


def make_inputs(universe: Mapping[str, Any], *, max_exit: pd.Timestamp | str | None = None) -> BasisInputs:
    """``universe`` as returned by ``binance_futures_archive.load_universe``."""
    cap = None if max_exit is None else pd.Timestamp(max_exit)
    if cap is not None and cap.tzinfo is None:
        cap = cap.tz_localize("UTC")
    validate_funding(universe["funding"])
    return BasisInputs(data=build_event_panels(universe["perp"], universe["spot"],
                                           spot_scale=universe.get("spot_scale")), perp=universe["perp"],
                       funding=universe["funding"], max_exit=cap, mark=universe.get("mark", {}))


def _params_of(weights: pd.DataFrame, params: Mapping[str, Any] | None) -> dict[str, Any]:
    p = dict(DEFAULT_PARAMS)
    p.update(weights.attrs.get("params", {}) if params is None else params)
    return p


def unit_return_panel(inputs: BasisInputs, index: pd.DatetimeIndex, params: Mapping[str, Any]) -> dict[str, Any]:
    """Per settlement row and instrument: entry/exit perp price, price return and the funding sum over (entry, exit].

    ``unit`` = price return minus the funding sum = the return of one unit of LONG notional (a short earns ``-unit``).
    A contract with an entry price but no bar at the exit uses its last close in ``(entry, exit]`` (flat if none).
    Rows whose entry or exit is outside the panels or after ``max_exit`` are marked invalid.
    """
    delay, hold = int(params["entry_delay_hours"]), int(params["hold_hours"])
    entry = index + pd.Timedelta(f"{delay}h")
    exit_ = entry + pd.Timedelta(f"{hold}h")
    close = inputs.data["perp_close"]
    cols = list(close.columns)
    vals = close.to_numpy(dtype=float)
    ie, ix = close.index.get_indexer(entry), close.index.get_indexer(exit_)
    valid = (ie >= 0) & (ix >= 0)
    if inputs.max_exit is not None:
        valid &= np.asarray(exit_ <= inputs.max_exit)
    n, m = len(index), len(cols)
    p0 = np.full((n, m), np.nan)
    p1 = np.full((n, m), np.nan)
    p0[valid] = vals[ie[valid]]
    p1[valid] = vals[ix[valid]]
    fallback = np.argwhere(np.isfinite(p0) & ~np.isfinite(p1))
    entry_ns, exit_ns = _ns(entry), _ns(exit_)
    hourly_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for k, j in fallback:
        if j not in hourly_cache:
            series = inputs.perp[cols[j]]["close"]
            hourly_cache[j] = (_ns(series.index), series.to_numpy(dtype=float))
        ts, px = hourly_cache[j]
        lo, hi = np.searchsorted(ts, entry_ns[k], side="right"), np.searchsorted(ts, exit_ns[k], side="right")
        p1[k, j] = px[hi - 1] if hi > lo else p0[k, j]
    with np.errstate(divide="ignore", invalid="ignore"):
        price = np.where((p0 > 0) & np.isfinite(p1), p1 / p0 - 1.0, np.nan)
    fsum = np.zeros((n, m))
    nrec = np.zeros((n, m), dtype=int)
    for j, name in enumerate(cols):
        f = inputs.funding.get(base_name(name))
        if f is None or len(f) == 0:
            continue
        ts = _ns(f.index)
        cs = np.concatenate([[0.0], np.cumsum(f["rate"].to_numpy(dtype=float))])
        a, b = np.searchsorted(ts, entry_ns, side="right"), np.searchsorted(ts, exit_ns, side="right")
        fsum[:, j] = cs[b] - cs[a]
        nrec[:, j] = b - a
    if np.isnan(fsum).any():
        raise PerpBasisError("NaN funding sum: non-finite funding rates must never be treated as zero")
    return {"entry": entry, "exit": exit_, "valid": valid, "p0": p0, "p1": p1, "price": price, "funding_sum": fsum,
            "funding_records": nrec, "unit": price - fsum, "columns": cols, "n_fallback_exit": int(len(fallback))}


@dataclass
class Book:
    positions: pd.DataFrame
    periods: pd.DataFrame
    diagnostics: dict[str, Any]


_POSITION_COLUMNS = ["period_start", "entry_time", "exit_time", "symbol", "mark_key", "weight", "entry_price",
                     "exit_price", "price_return", "funding_return", "unit_return"]


def _align_weights(weights: pd.DataFrame, inputs: BasisInputs) -> pd.DataFrame:
    """Weights on the panel columns (a missing column is not held; an unknown column is an error)."""
    columns = inputs.data["perp_close"].columns
    unknown = [c for c in weights.columns if c not in columns]
    if unknown:
        raise PerpBasisError(f"weights for instruments without panel data: {unknown[:5]}")
    aligned = weights.reindex(columns=columns)
    aligned.attrs = dict(weights.attrs)
    return aligned


def build_book(weights: pd.DataFrame, inputs: BasisInputs, params: Mapping[str, Any] | None = None,
               cost_bps: float = COST_BPS_ROUND_TRIP) -> Book:
    """Positions and per-period P&L of the registered rule (see the module docstring)."""
    p = _params_of(weights, params)
    w = _align_weights(weights, inputs).fillna(0.0)
    nonzero = (w.to_numpy() != 0.0).any(axis=1)
    empty = Book(pd.DataFrame(columns=_POSITION_COLUMNS), pd.DataFrame(), {"periods": 0})
    if not nonzero.any():
        return empty
    start = int(np.argmax(nonzero))
    w = w.iloc[start:]
    panel = unit_return_panel(inputs, w.index, p)
    keep = panel["valid"]
    if not keep.any():
        return empty
    w, sel = w.loc[keep], np.flatnonzero(keep)
    wv = w.to_numpy(dtype=float).copy()
    price, fsum = panel["price"][sel], panel["funding_sum"][sel]
    no_entry = (wv != 0.0) & ~np.isfinite(price)
    wv[no_entry] = 0.0  # cannot be entered (no usable price): not taken
    price0 = np.where(wv != 0.0, price, 0.0)
    price_pnl = (wv * price0).sum(axis=1)
    funding_pnl = -(wv * fsum).sum(axis=1)
    previous = np.vstack([np.zeros((1, wv.shape[1])), wv[:-1]])
    turnover = np.abs(wv - previous).sum(axis=1)
    cost = turnover * (cost_bps / 2.0 / 1e4)
    entry, exit_ = panel["entry"][sel], panel["exit"][sel]
    periods = pd.DataFrame({"entry_time": entry, "exit_time": exit_, "turnover": turnover, "price_pnl": price_pnl,
                            "funding_pnl": funding_pnl, "gross": price_pnl + funding_pnl, "cost": cost,
                            "net": price_pnl + funding_pnl - cost, "n_positions": (wv != 0.0).sum(axis=1)},
                           index=w.index)
    rows, cols = np.nonzero(wv)
    names = np.asarray(panel["columns"], dtype=object)
    inst = names[cols]
    positions = pd.DataFrame({
        "period_start": w.index[rows], "entry_time": entry[rows], "exit_time": exit_[rows], "symbol": inst,
        "mark_key": [base_name(s) for s in inst], "weight": wv[rows, cols],
        "entry_price": panel["p0"][sel][rows, cols], "exit_price": panel["p1"][sel][rows, cols],
        "price_return": price[rows, cols], "funding_return": -fsum[rows, cols],
        "unit_return": price[rows, cols] - fsum[rows, cols]})
    no_funding_records = int(((wv != 0.0) & (panel["funding_records"][sel] == 0)).sum())
    diagnostics = {"periods": int(len(periods)), "positions": int(len(positions)),
                   "skipped_no_entry_price": int(no_entry.sum()), "fallback_exit_prices": panel["n_fallback_exit"],
                   "positions_without_funding_records": no_funding_records}
    return Book(positions, periods, diagnostics)


DETAIL_COLUMNS = ["gross", "net", "turnover", "price_pnl", "funding_pnl", "cost"]


def daily_detail(book: Book) -> pd.DataFrame:
    """Daily gross / net / turnover (UTC day of the entry of each period), zero-filled over the covered range."""
    if book.periods.empty:
        return pd.DataFrame({c: [] for c in DETAIL_COLUMNS}, index=pd.DatetimeIndex([], tz="UTC"))
    per = book.periods
    day = pd.DatetimeIndex(per["entry_time"]).normalize()
    daily = per[DETAIL_COLUMNS].groupby(day).sum()
    full = pd.date_range(daily.index[0], daily.index[-1], freq="D", tz="UTC")
    return daily.reindex(full).fillna(0.0)


def make_detail_fn(inputs: BasisInputs) -> Callable[[pd.DataFrame, Any, float], pd.DataFrame]:
    """``detail_fn(weights, returns, cost_bps)`` for ``strategy_search_round2.evaluate_candidate_general``."""

    def account(weights: pd.DataFrame, returns: Any, cost_bps: float) -> pd.DataFrame:
        return daily_detail(build_book(weights, inputs, None, cost_bps))

    return account


# --------------------------------------------------------------------------------------------------- null


def allocation_null(weights: pd.DataFrame, inputs: BasisInputs, dev_start: pd.Timestamp, dev_end: pd.Timestamp, *,
                    n_draws: int = N_NULL_DRAWS, seed: int = NULL_SEED) -> dict[str, Any]:
    """G4: each settlement the real long / short leg sizes are given to random distinct eligible contracts.

    Statistic = mean daily gross (price + funding) return over the development days.  Settlements whose legs cannot
    be filled (more names than eligible contracts with a usable price) are dropped from the real book and every draw.
    """
    p = _params_of(weights, None)
    weights = _align_weights(weights, inputs)
    panel = unit_return_panel(inputs, weights.index, p)
    days = pd.DatetimeIndex(panel["entry"]).normalize()
    use = panel["valid"] & np.asarray((days >= dev_start) & (days <= dev_end))
    wv = weights.to_numpy(dtype=float)
    unit = panel["unit"]
    rng = np.random.default_rng(seed)
    draws = np.zeros(n_draws)
    observed = 0.0
    kept_days: set[pd.Timestamp] = set()
    n_rows = 0
    for i in np.flatnonzero(use):
        row = wv[i]
        avail = np.flatnonzero(np.isfinite(row) & np.isfinite(unit[i]))
        longs, shorts = np.flatnonzero(row > 0), np.flatnonzero(row < 0)
        held = len(longs) + len(shorts)
        if held > len(avail) or not np.isfinite(unit[i][np.concatenate([longs, shorts]).astype(int)]).all():
            continue
        kept_days.add(days[i])
        n_rows += 1
        if held == 0:
            continue
        w_long = row[longs[0]] if len(longs) else 0.0
        w_short = row[shorts[0]] if len(shorts) else 0.0
        observed += float(row[longs] @ unit[i][longs] + row[shorts] @ unit[i][shorts])
        u = unit[i][avail]
        order = np.argsort(rng.random((n_draws, len(avail))), axis=1)[:, :held]
        picked = u[order]
        draws += w_long * picked[:, :len(longs)].sum(axis=1) + w_short * picked[:, len(longs):held].sum(axis=1)
    n_days = len(kept_days)
    if n_days == 0:
        raise PerpBasisError("no development settlements for the null")
    observed_mean = observed / n_days
    res = action_matched_null_p(observed_mean, draws / n_days, alternative="greater")
    return {"pass": bool(res["p"] <= 0.05), "observed_mean_daily_gross": observed_mean, "null_type": "allocation",
            "accounting": "8h hold, price + realized funding, one permutation per settlement",
            "n_settlements": n_rows, "n_days": n_days, **res}


def make_null_fn(inputs: BasisInputs) -> Callable[..., dict[str, Any]]:
    """``null_fn(weights, dev_start, dev_end, n_draws=, seed=)``; the registered null seed (20261012) is fixed."""

    def null_fn(weights: pd.DataFrame, dev_start: pd.Timestamp, dev_end: pd.Timestamp, *, n_draws: int,
                seed: int) -> dict[str, Any]:
        return allocation_null(weights, inputs, dev_start, dev_end, n_draws=n_draws, seed=NULL_SEED)

    return null_fn


# ------------------------------------------------------------------------------------- spec and G5


def candidate_spec(round_cfg: Mapping[str, Any]) -> dict[str, Any]:
    cands = round_cfg["candidates"]
    if len(cands) != 1 or cands[0]["id"] != CANDIDATE_ID:
        raise PerpBasisError(f"expected the single candidate {CANDIDATE_ID}")
    cand = cands[0]
    params = dict(DEFAULT_PARAMS)
    unknown = [k for k in cand.get("perturb", {}) if k not in params]
    if unknown:
        raise PerpBasisError(f"perturbed parameters not in params: {unknown}")
    null_type = str(cand["null"]).split()[0].strip(":,;").lower()
    if null_type != "allocation":
        raise PerpBasisError(f"unknown null type in {cand['null']!r}")
    return {**cand, "params": params, "null": null_type, "null_registered_text": cand["null"]}


def apply_cumulative_dsr(result: dict[str, Any], n_trials: int) -> dict[str, Any]:
    """G5 (strategy-search-v2/v3): ``review_methods.deflated_sharpe_null_consistent`` on the daily development net
    returns with N = every trial of v1, v2 and v3 so far including this one."""
    try:
        result["gates"]["G5"] = deflated_sharpe_null_consistent(result["_dev_net"], n_trials)
    except ValueError as exc:
        result["gates"]["G5"] = {"pass": False, "error": str(exc), "n_trials": int(n_trials)}
    return result


def positions_in_window(book: Book, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.Series]:
    """Positions and per-period 1x cost whose period ENTRY day lies in ``[start, end]`` (for the leverage study)."""
    per = book.periods
    day = pd.DatetimeIndex(per["entry_time"]).normalize()
    in_window = np.asarray((day >= start) & (day <= end))
    cost = pd.Series(per["cost"].to_numpy()[in_window], index=pd.DatetimeIndex(per["entry_time"])[in_window])
    pos = book.positions
    pday = pd.DatetimeIndex(pos["entry_time"]).normalize()
    return pos.loc[np.asarray((pday >= start) & (pday <= end))].reset_index(drop=True), cost
