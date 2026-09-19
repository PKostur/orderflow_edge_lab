from __future__ import annotations

import json
import math
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_sectional_momentum import backtest_cross_sectional_momentum
from orderflow_edge_lab.strategy_tournament import generate_target_position

BINANCE_USDM_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"


class StrongestCandidateHardeningError(ValueError):
    pass


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def fetch_binance_usdm_funding_history(
    symbol: str,
    start: str,
    end: str,
    *,
    base_url: str = BINANCE_USDM_FUNDING,
    request_pause_seconds: float = 0.05,
) -> pd.DataFrame:
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    if end_ms <= start_ms:
        raise StrongestCandidateHardeningError("funding end must be after start")
    cursor = start_ms
    rows: dict[int, float] = {}
    normalized = symbol.replace("_", "").upper()
    while cursor < end_ms:
        query = urlencode({"symbol": normalized, "startTime": cursor, "endTime": end_ms - 1, "limit": 1000})
        req = Request(f"{base_url}?{query}", headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
        with urlopen(req, timeout=20.0) as response:
            if response.status != 200:
                raise StrongestCandidateHardeningError(f"Binance funding HTTP {response.status} for {normalized}")
            payload = json.loads(response.read(16_000_000).decode("utf-8"))
        if not isinstance(payload, list):
            raise StrongestCandidateHardeningError(f"Binance funding returned non-list for {normalized}")
        if not payload:
            break
        last = cursor
        for item in payload:
            try:
                ts = int(item["fundingTime"])
                rate = float(item["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_ms <= ts < end_ms and math.isfinite(rate):
                rows[ts] = rate
            last = max(last, ts + 1)
        if last <= cursor:
            break
        cursor = last
        if len(payload) < 1000:
            break
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
    if not rows:
        return pd.DataFrame({"funding_rate": pd.Series(dtype=float)}, index=pd.DatetimeIndex([], tz="UTC"))
    keys = sorted(rows)
    index = pd.to_datetime(keys, unit="ms", utc=True)
    return pd.DataFrame({"funding_rate": [rows[key] for key in keys]}, index=index)


def _funding_between(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame is None or frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    series = pd.to_numeric(frame["funding_rate"], errors="coerce").fillna(0.0)
    return float(series[(series.index > start) & (series.index <= end)].sum())


def _clean_frame(frame: pd.DataFrame, required: set[str], symbol: str) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise StrongestCandidateHardeningError(f"{symbol}: DatetimeIndex required")
    if not required.issubset(frame.columns):
        raise StrongestCandidateHardeningError(f"{symbol}: missing {sorted(required - set(frame.columns))}")
    out = frame.copy().sort_index()
    out.index = out.index.tz_localize("UTC") if out.index.tz is None else out.index.tz_convert("UTC")
    if out.index.has_duplicates:
        raise StrongestCandidateHardeningError(f"{symbol}: duplicate timestamps")
    for column in required:
        values = pd.to_numeric(out[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all() or (values <= 0).any():
            raise StrongestCandidateHardeningError(f"{symbol}: invalid {column}")
        out[column] = values.astype(float)
    return out


def _common_frames(
    frames: Mapping[str, pd.DataFrame],
    symbols: list[str],
    required: set[str],
    *,
    minimum_rows: int,
) -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
    clean: dict[str, pd.DataFrame] = {}
    common: pd.DatetimeIndex | None = None
    for symbol in symbols:
        if symbol not in frames:
            raise StrongestCandidateHardeningError(f"missing symbol {symbol}")
        frame = _clean_frame(frames[symbol], required, symbol)
        clean[symbol] = frame
        common = frame.index if common is None else common.intersection(frame.index)
    if common is None:
        raise StrongestCandidateHardeningError("empty symbol panel")
    common = common.sort_values()
    if len(common) < minimum_rows:
        raise StrongestCandidateHardeningError(f"insufficient common history: {len(common)}/{minimum_rows}")
    return clean, common


def _return_stats(returns: pd.Series, *, bars_per_year: float) -> dict[str, Any]:
    usable = pd.to_numeric(returns, errors="coerce").dropna()
    if usable.empty:
        return {"observations": 0, "net_return": 0.0, "max_drawdown": 0.0, "sharpe": None, "positive_fraction": None}
    equity = (1.0 + usable).cumprod()
    peaks = equity.cummax()
    std = float(usable.std(ddof=0))
    return {
        "observations": int(len(usable)),
        "net_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float((equity / peaks - 1.0).min()),
        "sharpe": float(usable.mean() / std * math.sqrt(bars_per_year)) if std > 0 else None,
        "positive_fraction": float((usable > 0).mean()),
    }


def _calendar_folds(returns: pd.Series, fold_days: int, bars_per_year: float) -> list[dict[str, Any]]:
    if returns.empty:
        return []
    anchor = returns.index.min().normalize()
    fold_ids = ((returns.index.normalize() - anchor).days // int(fold_days)).astype(int)
    out: list[dict[str, Any]] = []
    for fold in sorted(set(int(v) for v in fold_ids)):
        mask = np.asarray(fold_ids == fold)
        part = returns.iloc[mask]
        if len(part) < 10:
            continue
        stats = _return_stats(part, bars_per_year=bars_per_year)
        out.append({"fold": fold, "start": part.index.min().isoformat(), "end": part.index.max().isoformat(), **stats})
    return out


def _funding_matrix(index: pd.DatetimeIndex, symbols: list[str], funding: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=index[:-1], columns=symbols)
    for i, ts in enumerate(index[:-1]):
        end = index[i + 1]
        for symbol in symbols:
            out.loc[ts, symbol] = _funding_between(funding.get(symbol), ts, end)
    return out


def _trend_position_frame(
    clean: Mapping[str, pd.DataFrame],
    common: pd.DatetimeIndex,
    candidate: Mapping[str, Any],
    *,
    reverse: bool = False,
) -> pd.DataFrame:
    spec = candidate["specification"]
    params = {
        "fast": int(spec["fast_ema"]),
        "slow": int(spec["slow_ema"]),
        "atr_period": int(spec["atr_period"]),
        "min_atr_spread": float(spec["min_atr_spread"]),
    }
    positions: dict[str, pd.Series] = {}
    for symbol, frame in clean.items():
        target = generate_target_position(frame, "ema_tsmom", params).reindex(common).fillna(0.0)
        executed = target.shift(1).fillna(0.0).clip(-1.0, 1.0)
        positions[symbol] = -executed if reverse else executed
    return pd.DataFrame(positions, index=common)


def _trend_mode_returns(
    clean: Mapping[str, pd.DataFrame],
    common: pd.DatetimeIndex,
    funding: Mapping[str, pd.DataFrame],
    candidate: Mapping[str, Any],
    *,
    cost_bps: float,
    mode: str,
) -> tuple[pd.Series, pd.DataFrame, dict[str, float]]:
    symbols = [str(x) for x in candidate["specification"]["symbols"] if str(x) in clean]
    opens = pd.DataFrame({s: clean[s].loc[common, "open"] for s in symbols}, index=common)
    if mode == "frozen_original":
        sides = _trend_position_frame({s: clean[s] for s in symbols}, common, candidate)
    elif mode == "exact_signal_reversal":
        sides = _trend_position_frame({s: clean[s] for s in symbols}, common, candidate, reverse=True)
    elif mode == "equal_weight_long_only":
        base = _trend_position_frame({s: clean[s] for s in symbols}, common, candidate)
        first_active = base.abs().sum(axis=1).gt(0)
        sides = pd.DataFrame(0.0, index=common, columns=symbols)
        if first_active.any():
            first = first_active[first_active].index[0]
            sides.loc[sides.index >= first, :] = 1.0
    else:
        raise StrongestCandidateHardeningError(f"unknown trend mode: {mode}")
    active = (sides != 0.0).sum(axis=1).replace(0, np.nan)
    weights = sides.div(active, axis=0).fillna(0.0)
    future_open = opens.shift(-1)
    price = weights.iloc[:-1] * (future_open.iloc[:-1] / opens.iloc[:-1] - 1.0)
    fund_rates = _funding_matrix(common, symbols, funding)
    funding_contrib = -weights.iloc[:-1] * fund_rates
    turnover = (weights - weights.shift(1).fillna(0.0)).abs().sum(axis=1).iloc[:-1]
    side_cost = float(cost_bps) / 2.0 / 10_000.0
    net = price.sum(axis=1) + funding_contrib.sum(axis=1) - turnover * side_cost
    if len(net):
        net.iloc[-1] -= float(weights.iloc[-2].abs().sum()) * side_cost
    symbol_contrib = (price + funding_contrib).sum(axis=0).to_dict()
    return net, weights, {str(k): float(v) for k, v in symbol_contrib.items()}


def evaluate_trend_panel(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    candidate: Mapping[str, Any],
    *,
    cost_bps: float,
    fold_days: int,
    regime_return_days: int = 90,
    regime_vol_days: int = 30,
) -> dict[str, Any]:
    symbols = [str(x) for x in candidate["specification"]["symbols"]]
    clean, common = _common_frames(frames, symbols, {"open", "high", "low", "close"}, minimum_rows=400)
    modes: dict[str, Any] = {}
    mode_returns: dict[str, pd.Series] = {}
    for mode in ("frozen_original", "exact_signal_reversal", "equal_weight_long_only"):
        returns, weights, contributions = _trend_mode_returns(clean, common, funding, candidate, cost_bps=cost_bps, mode=mode)
        folds = _calendar_folds(returns, fold_days, 365.25 * 3.0)
        positive_folds = [row for row in folds if float(row["net_return"]) > 0]
        positives = {k: max(0.0, v) for k, v in contributions.items()}
        positive_total = sum(positives.values())
        modes[mode] = {
            **_return_stats(returns, bars_per_year=365.25 * 3.0),
            "folds": folds,
            "independent_folds": len(folds),
            "positive_fold_fraction": len(positive_folds) / len(folds) if folds else None,
            "median_fold_return": float(np.median([row["net_return"] for row in folds])) if folds else None,
            "total_turnover": float((weights - weights.shift(1).fillna(0.0)).abs().sum(axis=1).sum()),
            "symbol_price_plus_funding_contribution": contributions,
            "top_positive_symbol_share": max(positives.values()) / positive_total if positive_total > 0 and positives else None,
        }
        mode_returns[mode] = returns

    original = mode_returns["frozen_original"]
    btc = clean["BTC_USDT"].loc[common, "close"].astype(float)
    bars_per_day = 3
    trailing = btc.shift(1).pct_change(int(regime_return_days * bars_per_day))
    rv = btc.pct_change().shift(1).rolling(
        int(regime_vol_days * bars_per_day),
        min_periods=int(regime_vol_days * bars_per_day),
    ).std()
    rv_threshold = float(rv.dropna().median()) if not rv.dropna().empty else None
    regimes: dict[str, Any] = {}
    masks = {"btc_trailing_up": trailing > 0, "btc_trailing_down_or_flat": trailing <= 0}
    if rv_threshold is not None:
        masks["btc_high_realized_vol"] = rv > rv_threshold
        masks["btc_low_realized_vol"] = rv <= rv_threshold
    for name, mask in masks.items():
        aligned = mask.reindex(original.index).fillna(False)
        regimes[name] = _return_stats(original[aligned], bars_per_year=365.25 * 3.0)
    regimes["volatility_split_std_threshold"] = rv_threshold

    loo: dict[str, float] = {}
    for omitted in symbols:
        subset = [s for s in symbols if s != omitted]
        subclean = {s: clean[s] for s in subset}
        subfunding = {s: funding.get(s, pd.DataFrame()) for s in subset}
        returns, _, _ = _trend_mode_returns(subclean, common, subfunding, candidate, cost_bps=cost_bps, mode="frozen_original")
        loo[omitted] = float(_return_stats(returns, bars_per_year=365.25 * 3.0)["net_return"])

    return {
        "round_trip_cost_bps": float(cost_bps),
        "common_start": common.min().isoformat(),
        "common_end": common.max().isoformat(),
        "symbols": symbols,
        "modes": modes,
        "regime_diagnostics": regimes,
        "leave_one_symbol_out_net_return": loo,
        "leave_one_out_all_positive": all(value > 0 for value in loo.values()),
        "claims": {
            "candidate_parameters_changed": False,
            "development_diagnostic_only": True,
            "profitable_edge_established": False,
        },
    }


def _aligned_open_close(
    frames: Mapping[str, pd.DataFrame],
    symbols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame], pd.DatetimeIndex]:
    clean, common = _common_frames(frames, symbols, {"open", "close"}, minimum_rows=200)
    opens = pd.DataFrame({s: clean[s].loc[common, "open"] for s in symbols}, index=common)
    closes = pd.DataFrame({s: clean[s].loc[common, "close"] for s in symbols}, index=common)
    return opens, closes, clean, common


def _portfolio_from_signal_weights(
    opens: pd.DataFrame,
    signal_weights: pd.DataFrame,
    funding: Mapping[str, pd.DataFrame],
    *,
    cost_bps: float,
) -> dict[str, Any]:
    weights = signal_weights.shift(1).fillna(0.0)
    next_open = opens.shift(-1)
    price = (weights * (next_open / opens - 1.0)).sum(axis=1).fillna(0.0)
    funding_return = pd.Series(0.0, index=opens.index, dtype=float)
    for i in range(len(opens.index) - 1):
        start, end = opens.index[i], opens.index[i + 1]
        value = 0.0
        for symbol in opens.columns:
            w = float(weights.iloc[i][symbol])
            if abs(w) > 1e-15:
                value += -w * _funding_between(funding.get(symbol), start, end)
        funding_return.iloc[i] = value
    turnover = (weights - weights.shift(1).fillna(0.0)).abs().sum(axis=1)
    side_cost = float(cost_bps) / 2.0 / 10_000.0
    net = price + funding_return - turnover * side_cost
    usable = net.iloc[:-1].copy()
    if len(usable):
        usable.iloc[-1] -= float(weights.iloc[-2].abs().sum()) * side_cost
    return {
        **_return_stats(usable, bars_per_year=365.25),
        "returns": usable,
        "rebalances": int((turnover.iloc[:-1] > 1e-12).sum()),
        "total_turnover": float(turnover.iloc[:-1].sum()),
        "funding_return_sum": float(funding_return.iloc[:-1].sum()),
    }


def _random_rank_signal(
    closes: pd.DataFrame,
    *,
    lookback_days: int,
    holding_days: int,
    quantile_fraction: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    symbols = list(closes.columns)
    n_select = max(1, int(math.floor(len(symbols) * float(quantile_fraction))))
    signal = pd.DataFrame(0.0, index=closes.index, columns=symbols)
    current = pd.Series(0.0, index=symbols, dtype=float)
    for i in range(len(closes)):
        if i >= int(lookback_days) and (i - int(lookback_days)) % int(holding_days) == 0:
            perm = list(rng.permutation(symbols))
            losers = perm[:n_select]
            winners = perm[n_select : 2 * n_select]
            current = pd.Series(0.0, index=symbols, dtype=float)
            current.loc[winners] = 0.5 / len(winners)
            current.loc[losers] = -0.5 / len(losers)
        signal.iloc[i] = current
    return signal


def evaluate_cross_sectional_panel(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    candidate: Mapping[str, Any],
    *,
    cost_bps: float,
    fold_days: int,
    placebo_permutations: int,
    placebo_seed: int,
) -> dict[str, Any]:
    spec = candidate["specification"]
    symbols = [str(x) for x in spec["symbols"]]
    opens, closes, clean, common = _aligned_open_close(frames, symbols)
    actual = backtest_cross_sectional_momentum(
        clean,
        lookback_days=int(spec["lookback_days"]),
        holding_days=int(spec["holding_days"]),
        quantile_fraction=float(spec["quantile_fraction"]),
        variant="dollar_neutral_top_bottom",
        round_trip_cost_bps=float(cost_bps),
        fold_days=int(fold_days),
        funding_frames=funding,
    )
    placebo_returns: list[float] = []
    for i in range(int(placebo_permutations)):
        rng = np.random.default_rng(int(placebo_seed) + i)
        signal = _random_rank_signal(
            closes,
            lookback_days=int(spec["lookback_days"]),
            holding_days=int(spec["holding_days"]),
            quantile_fraction=float(spec["quantile_fraction"]),
            rng=rng,
        )
        trial = _portfolio_from_signal_weights(opens, signal, funding, cost_bps=cost_bps)
        placebo_returns.append(float(trial["net_return"]))
    actual_return = float(actual["net_return"])
    exceed = sum(value >= actual_return for value in placebo_returns)
    placebo_p = (exceed + 1.0) / (len(placebo_returns) + 1.0)

    loo: dict[str, float] = {}
    for omitted in symbols:
        subset = {s: clean[s] for s in symbols if s != omitted}
        subfund = {s: funding.get(s, pd.DataFrame()) for s in subset}
        result = backtest_cross_sectional_momentum(
            subset,
            lookback_days=int(spec["lookback_days"]),
            holding_days=int(spec["holding_days"]),
            quantile_fraction=float(spec["quantile_fraction"]),
            variant="dollar_neutral_top_bottom",
            round_trip_cost_bps=float(cost_bps),
            fold_days=int(fold_days),
            funding_frames=subfund,
        )
        loo[omitted] = float(result["net_return"])

    return {
        "round_trip_cost_bps": float(cost_bps),
        "common_start": common.min().isoformat(),
        "common_end": common.max().isoformat(),
        "symbols": symbols,
        "actual": actual,
        "random_rank_placebo": {
            "permutations": int(placebo_permutations),
            "seed": int(placebo_seed),
            "median_net_return": float(np.median(placebo_returns)) if placebo_returns else None,
            "p95_net_return": float(np.quantile(placebo_returns, 0.95)) if placebo_returns else None,
            "actual_minus_placebo_median": actual_return - float(np.median(placebo_returns)) if placebo_returns else None,
            "one_sided_empirical_p": float(placebo_p),
        },
        "leave_one_symbol_out_net_return": loo,
        "leave_one_out_all_positive": all(value > 0 for value in loo.values()),
        "claims": {
            "candidate_parameters_changed": False,
            "development_diagnostic_only": True,
            "placebo_used_for_diagnostic_not_retuning": True,
            "profitable_edge_established": False,
        },
    }
