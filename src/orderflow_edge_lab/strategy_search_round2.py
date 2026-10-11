"""strategy-search-v1 round 2: candidate specs and gate evaluation with a configurable annualisation.

``strategy_search.evaluate_candidate`` fixes 252 periods per year and the two-sided G8 of the ETF candidates.  Round 2
adds a crypto candidate (365 days, G8 against the crypto trend core only), so the evaluation is repeated here with
those two parameters exposed and everything else reused from ``strategy_search`` (gates, nulls, ledger).  With
``periods_per_year=252`` and ``g8_mode='both'`` it reproduces ``evaluate_candidate`` exactly (unit-tested).
Descriptive research code: no promotion, no filters, no leverage, no order placement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import ctrend, fomc_cycle
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab.review_methods import action_matched_null_p

CTREND_ID = "R2C1_CTREND"
FOMC_ID = "R2C2_FOMC_cycle_even_weeks"
CRYPTO_PERIODS_PER_YEAR = 365
ETF_PERIODS_PER_YEAR = 252
CRYPTO_COST_BPS_ROUND_TRIP = 20.0  # protocol: crypto 20 bps round trip (funding n/a: spot, short leg assumed free)
ETF_COST_BPS_ROUND_TRIP = ss.COST_BPS_ROUND_TRIP

DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    CTREND_ID: dict(ctrend.DEFAULT_PARAMS),
    FOMC_ID: dict(fomc_cycle.DEFAULT_PARAMS),
}


def candidate_specs(round_cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Registered candidates in registration order, each with the ``params`` the base parameter set."""
    specs = []
    for cand in round_cfg["candidates"]:
        cid = cand["id"]
        if cid not in DEFAULT_PARAMS:
            raise ss.StrategySearchError(f"unknown round-2 candidate {cid}")
        params = dict(DEFAULT_PARAMS[cid])
        unknown = [k for k in cand.get("perturb", {}) if k not in params]
        if unknown:
            raise ss.StrategySearchError(f"{cid}: perturbed parameters not in params: {unknown}")
        null_type = str(cand["null"]).split()[0].strip(":,;").lower()
        if null_type not in ("timing", "allocation"):
            raise ss.StrategySearchError(f"{cid}: unknown null type in {cand['null']!r}")
        specs.append({**cand, "params": params, "null": null_type, "null_registered_text": cand["null"]})
    return specs


def g2_development(dev_net: pd.Series, periods_per_year: int) -> dict[str, Any]:
    s = ss.perf_stats(dev_net, periods_per_year)
    ok = bool(s["sharpe"] is not None and s["newey_west_t"] is not None and s["sharpe"] >= 0.5
              and s["newey_west_t"] >= 2.0)
    return {"pass": ok, **s}


def g3_validation(dev_stats: Mapping[str, Any], val_net: pd.Series, periods_per_year: int) -> dict[str, Any]:
    s = ss.perf_stats(val_net, periods_per_year)
    dev_sharpe, val_sharpe = dev_stats.get("sharpe"), s["sharpe"]
    ok = bool(dev_sharpe is not None and val_sharpe is not None and dev_sharpe > 0 and val_sharpe > 0
              and val_sharpe >= 0.4 and val_sharpe >= 0.4 * dev_sharpe)
    return {"pass": ok, **s}


def g8_crypto_independence(net: pd.Series, crypto_reference: pd.Series | None, *, spy_returns: pd.Series | None = None,
                           min_overlap: int = 60) -> dict[str, Any]:
    """G8 for a crypto candidate: daily correlation with the crypto trend core <= 0.5 (SPY is descriptive only)."""
    out: dict[str, Any] = {}
    if crypto_reference is None:
        out["crypto_core"] = {"corr": None, "overlap_days": 0, "note": "no reference supplied"}
        ok = False
    else:
        ref = crypto_reference.copy()
        ref.index = ref.index - pd.Timedelta("1D")  # the value stamped d+1 covers day d (as in strategy_search)
        joined = pd.concat([net.rename("c"), ref.rename("r")], axis=1).dropna()
        corr = float(joined["c"].corr(joined["r"])) if len(joined) >= min_overlap else None
        out["crypto_core"] = {"corr": corr, "overlap_days": int(len(joined)), "limit": 0.5}
        ok = corr is not None and bool(np.isfinite(corr)) and corr <= 0.5
    if spy_returns is not None:
        joined = pd.concat([net.rename("c"), spy_returns.rename("s")], axis=1).dropna()
        corr_spy = float(joined["c"].corr(joined["s"])) if len(joined) >= min_overlap else None
        out["spy_buy_and_hold"] = {"corr": corr_spy, "overlap_days": int(len(joined)),
                                   "note": "descriptive only (not required for a crypto candidate)"}
    return {"pass": bool(ok), **out}


def evaluate_candidate_general(
    spec: Mapping[str, Any],
    data: Mapping[str, Any],
    returns: pd.DataFrame,
    *,
    validation_window: Sequence[str],
    crypto_reference: pd.Series | None,
    spy_returns: pd.Series,
    cost_bps: float,
    periods_per_year: int,
    fn: Callable[[Mapping[str, Any], Mapping[str, Any]], pd.DataFrame],
    truncation_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], pd.DataFrame] | None = None,
    null_returns: pd.DataFrame | None = None,
    detail_fn: Callable[[pd.DataFrame, pd.DataFrame, float], pd.DataFrame] | None = None,
    null_fn: Callable[..., dict[str, Any]] | None = None,
    g8_mode: str = "both",
    n_draws: int = ss.N_NULL_DRAWS,
    n_truncation_dates: int = ss.N_TRUNCATION_DATES,
    seed: int = ss.SEED,
) -> dict[str, Any]:
    """All gates except G5 (needs the whole round).  See ``strategy_search.evaluate_candidate``.

    ``null_returns`` (default: ``returns``) is the return frame the allocation null may draw names from; the CTREND run
    passes returns masked to each week's eligible coins.  ``truncation_fn`` (default ``fn``) is the function re-run on
    truncated data in G1.  ``detail_fn(weights, returns, cost_bps)`` (default ``strategy_search.backtest_detail``)
    produces the gross/net/turnover day table used by every gate, and ``null_fn(weights, dev_start, dev_end,
    n_draws=..., seed=...)`` (default ``g4_matched_null``) replaces G4; CTREND passes the weekly buy-and-hold
    accounting for both.
    """
    params = dict(spec["params"])
    account = detail_fn or ss.backtest_detail
    weights = fn(data, params)
    detail = account(weights, returns, cost_bps)
    if detail.empty:
        raise ss.StrategySearchError(f"{spec['id']}: no signal")
    first_day = detail.index[0]
    dev_start, dev_end = ss.resolve_window(spec["development"], first_day)
    val_start = max(ss._utc_ts(validation_window[0]), dev_end + pd.Timedelta("1D"))
    val_end = ss._utc_ts(validation_window[1])
    dev = detail.loc[(detail.index >= dev_start) & (detail.index <= dev_end)]
    val = detail.loc[(detail.index >= val_start) & (detail.index <= val_end)]

    gates: dict[str, Any] = {}
    gates["G1"] = ss.g1_truncation(truncation_fn or fn, data, params, weights, seed=seed, n_dates=n_truncation_dates)
    gates["G2"] = g2_development(dev["net"], periods_per_year)
    gates["G3"] = g3_validation(gates["G2"], val["net"], periods_per_year)
    if null_fn is not None:
        gates["G4"] = null_fn(weights, dev_start, dev_end, n_draws=n_draws, seed=seed)
    else:
        gates["G4"] = ss.g4_matched_null(spec["null"], weights, returns if null_returns is None else null_returns,
                                         dev_start, dev_end, n_draws=n_draws, seed=seed)
    variants = []
    for variant in ss.perturbation_param_sets(spec):
        vd = account(fn(data, variant), returns, cost_bps)
        if vd.empty:
            variants.append({"params": variant, "sharpe": None, "days": 0})
            continue
        v_start = max(dev_start, vd.index[0])
        s = ss.perf_stats(vd.loc[(vd.index >= v_start) & (vd.index <= dev_end), "net"], periods_per_year)
        variants.append({"params": variant, "sharpe": s["sharpe"], "days": s["days"],
                         "first_signal_day": str(vd.index[0].date())})
    gates["G6"] = ss.g6_robustness(gates["G2"], dev["net"], variants)
    gates["G7"] = ss.g7_costs(dev["gross"], dev["turnover"], cost_bps)
    if g8_mode == "both":
        gates["G8"] = ss.g8_independence(detail["net"], crypto_reference, spy_returns)
    elif g8_mode == "crypto_only":
        gates["G8"] = g8_crypto_independence(detail["net"], crypto_reference, spy_returns=spy_returns)
    else:
        raise ss.StrategySearchError(f"unknown g8 mode {g8_mode}")
    return {
        "id": spec["id"],
        "params": params,
        "null": spec["null"],
        "periods_per_year": periods_per_year,
        "cost_bps_round_trip": cost_bps,
        "windows": {"development": [str(dev_start.date()), str(dev_end.date())],
                    "validation": [str(val_start.date()), str(val_end.date())],
                    "first_return_date": str(first_day.date())},
        "dev": gates["G2"],
        "validation": gates["G3"],
        "gates": gates,
        "return_series_sha256": ss.series_sha256(detail["net"]),
        "return_days": int(len(detail)),
        "_dev_net": dev["net"],
        "_detail": detail,
        "_weights": weights,
    }


def null_returns_eligible_only(returns: pd.DataFrame, eligible_daily: pd.DataFrame) -> pd.DataFrame:
    """Returns where the coin was eligible in the week that the weights of the previous close apply to; else NaN.

    ``eligible_daily`` row ``t`` is the eligibility of the book decided at close ``t``; that book earns the return
    stamped ``t + 1`` (hence the shift), so the allocation null can only draw names that were eligible that week.
    """
    shifted = eligible_daily.astype(float).shift(1).reindex(index=returns.index, columns=returns.columns)
    return returns.where(shifted.fillna(0.0) > 0.5)


# ------------------------------------------------------------------ weekly buy-and-hold accounting (CTREND)


def _week_starts(weights: pd.DataFrame) -> np.ndarray:
    """Positions of the Sunday rows that carry a decided book (the start of each held week)."""
    has = weights.notna().any(axis=1).to_numpy()
    sunday = np.asarray(weights.index.dayofweek == 6)
    return np.flatnonzero(has & sunday)


def buy_and_hold_detail(weights: pd.DataFrame, close: pd.DataFrame, cost_bps_round_trip: float) -> pd.DataFrame:
    """Daily gross/net returns of a book formed at each Sunday close and held buy-and-hold for the week.

    Within week k (days S_k+1 .. S_(k+1)): V_t = 1 + sum_i w_i (P_it / P_i,S_k - 1) with P the close (a coin without a
    bar keeps its last price), daily return V_t / V_(t-1) - 1.  Turnover sum_i |w_k - w_(k-1)| (target weights; the
    first week against zero) is charged once, on the first day of the week, at cost_bps_round_trip / 2 per unit.  No
    intra-week costs.  Also returns the long-leg and short-leg turnover.
    """
    idx = pd.DatetimeIndex(weights.index)
    starts = _week_starts(weights)
    empty = pd.DataFrame({"gross": [], "net": [], "turnover": [], "turnover_long": [], "turnover_short": []},
                         index=idx[:0])
    if len(starts) == 0:
        return empty
    px = close.reindex(index=idx, columns=weights.columns)
    last = len(idx) - 1
    prev = np.zeros(weights.shape[1])
    pieces: list[pd.DataFrame] = []
    for p0 in starts:
        p1 = min(p0 + 7, last)
        w = weights.iloc[p0].fillna(0.0).to_numpy(dtype=float)
        if p1 > p0:
            held = np.flatnonzero(w != 0.0)
            if len(held):
                seg = px.iloc[p0:p1 + 1, held].ffill()
                with np.errstate(divide="ignore", invalid="ignore"):
                    rel = seg.iloc[1:].to_numpy() / seg.iloc[0].to_numpy() - 1.0
                rel = np.where(np.isfinite(rel), rel, 0.0)
                value = 1.0 + rel @ w[held]
            else:
                value = np.ones(p1 - p0)
            before = np.concatenate([[1.0], value[:-1]])
            with np.errstate(divide="ignore", invalid="ignore"):
                gross = value / before - 1.0
            turnover = np.zeros(p1 - p0)
            t_long = np.zeros(p1 - p0)
            t_short = np.zeros(p1 - p0)
            turnover[0] = float(np.abs(w - prev).sum())
            t_long[0] = float(np.abs(np.clip(w, 0, None) - np.clip(prev, 0, None)).sum())
            t_short[0] = float(np.abs(np.clip(-w, 0, None) - np.clip(-prev, 0, None)).sum())
            net = gross - turnover * (cost_bps_round_trip / 2.0 / 1e4)
            pieces.append(pd.DataFrame({"gross": gross, "net": net, "turnover": turnover, "turnover_long": t_long,
                                        "turnover_short": t_short}, index=idx[p0 + 1:p1 + 1]))
        prev = w
    return pd.concat(pieces) if pieces else empty


def weekly_spells(weights: pd.DataFrame, close: pd.DataFrame, eligible_daily: pd.DataFrame, start: pd.Timestamp,
                  end: pd.Timestamp) -> list[dict[str, Any]]:
    """Weekly spells inside ``[start, end]`` (return days): asset returns P_end/P_start - 1 (compounded) and the book.

    A spell is the part of the held week S_k+1 .. S_(k+1) that lies in the window.  P_start is the close at S_k,
    P_end the last available close up to the spell's last day (a delisted coin keeps its last price).  ``available`` =
    eligible at S_k with a start price.
    """
    idx = pd.DatetimeIndex(weights.index)
    cols = weights.columns
    px = close.reindex(index=idx, columns=cols)
    elig = eligible_daily.reindex(index=idx, columns=cols).fillna(False).to_numpy(dtype=bool)
    last = len(idx) - 1
    spells = []
    for p0 in _week_starts(weights):
        first_day, last_day = p0 + 1, min(p0 + 7, last)
        if last_day < first_day:
            continue
        keep = [d for d in range(first_day, last_day + 1) if start <= idx[d] <= end]
        if not keep:
            continue
        seg = px.iloc[p0:keep[-1] + 1].ffill()
        p_start, p_end = seg.iloc[0].to_numpy(dtype=float), seg.iloc[-1].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = p_end / p_start - 1.0
        spells.append({"week_start": idx[p0], "days": len(keep), "returns": np.where(np.isfinite(r), r, np.nan),
                       "weights": weights.iloc[p0].fillna(0.0).to_numpy(dtype=float),
                       "available": elig[p0] & np.isfinite(r)})
    return spells


def spell_statistic(spells: Sequence[Mapping[str, Any]], rng: np.random.Generator | None = None,
                    identity: bool = False) -> float:
    """Mean daily gross return over the spell days: sum of spell book returns / sum of spell days.

    ``rng=None`` is the real book.  Otherwise the real long and short weight values are assigned to a random
    permutation of the spell's available coins (``identity=True``: the actual coins in the same order, which must
    reproduce the real statistic).  Spells whose names cannot be filled (more names than available coins, or a held
    coin without a return) are dropped from the real book and from every draw alike.
    """
    total, days = 0.0, 0
    for sp in spells:
        w = sp["weights"]
        longs, shorts = np.flatnonzero(w > 0), np.flatnonzero(w < 0)
        held = np.concatenate([longs, shorts])
        if len(held) == 0:
            days += sp["days"]
            continue
        values = w[held]
        avail = np.flatnonzero(sp["available"])
        if len(held) > len(avail) or not np.isfinite(sp["returns"][held]).all():
            continue
        chosen = held if (rng is None or identity) else rng.permutation(avail)[:len(held)]
        total += float(values @ sp["returns"][chosen])
        days += sp["days"]
    return float(total / days) if days else float("nan")


def g4_buy_and_hold_allocation_null(weights: pd.DataFrame, close: pd.DataFrame, eligible_daily: pd.DataFrame,
                                    dev_start: pd.Timestamp, dev_end: pd.Timestamp, *,
                                    n_draws: int = ss.N_NULL_DRAWS, seed: int = ss.SEED) -> dict[str, Any]:
    """G4 with the weekly buy-and-hold accounting: the real statistic against ``n_draws`` per-week re-allocations."""
    spells = weekly_spells(weights, close, eligible_daily, dev_start, dev_end)
    observed = spell_statistic(spells)
    rng = np.random.default_rng(seed)
    draws = np.array([spell_statistic(spells, rng) for _ in range(n_draws)])
    res = action_matched_null_p(observed, draws, alternative="greater")
    return {"pass": bool(res["p"] <= 0.05), "observed_mean_daily_gross": observed, "null_type": "allocation",
            "accounting": "weekly buy-and-hold, compounded spell returns", "n_spells": len(spells), **res}
