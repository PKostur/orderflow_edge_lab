"""Combined trend portfolio, scored on daily P&L (``universal-trend-portfolio-forward-v1``).

One question, answered at the fastest honest rate: does the equal-capital
combination of the frozen trend strategies earn money net of costs, outright
and after a causal beta hedge?  Daily portfolio returns replace per-trade
scoring because they carry far more observations per unit of calendar time.

Sleeves: every (strategy, symbol) pair run with canonical accounting v3.
Portfolio: equal capital across sleeves, rebalanced daily (inter-sleeve
rebalancing is not charged; disclosed).  Hedge: trailing beta to the
equal-weight basket estimated only from days strictly before the scored day,
with hedge turnover charged.  Descriptive until the review horizon; nothing here
authorizes promotion, filters, leverage or live trading.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.universal_backtest import ExecutionModel, legacy_strategy

WATCH_ID = "universal-trend-portfolio-forward-v1"


class TrendPortfolioError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def completed_bars(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise TrendPortfolioError("duplicate timestamps")
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.loc[out.index + pd.Timedelta(hours=8) <= as_of]
    values = out[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise TrendPortfolioError("invalid OHLC")
    return out


def _daily(series: pd.Series) -> pd.Series:
    """Values stamped at 00:00 UTC, one per day."""
    return series.loc[(series.index.hour == 0) & (series.index.minute == 0)]


def sleeve_daily_returns(
    config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.Series] | None = None,
) -> pd.DataFrame:
    execution = ExecutionModel(
        round_trip_cost_bps=float(config["economics"]["round_trip_cost_bps"]),
        max_abs_position=float(config["economics"]["max_abs_position"]),
    )
    columns = {}
    sizing = config.get("sizing")
    for spec in config["strategies"]:
        strategy = legacy_strategy(str(spec["family"]))
        if sizing:
            if sizing.get("method") != "entry_inverse_vol":
                raise TrendPortfolioError(f"unknown sizing method: {sizing.get('method')}")
            from orderflow_edge_lab.vol_sizing import vol_sized_strategy

            strategy = vol_sized_strategy(
                strategy,
                window=int(sizing["window_bars"]),
                target_vol=float(sizing["target_annual_vol"]),
                cap=float(sizing["cap"]),
                bars_per_year=int(sizing.get("bars_per_year", 3 * 365)),
            )
        for symbol in config["source"]["symbols"]:
            result = run_canonical_backtest_v3(
                frames[symbol], strategy, dict(spec["parameters"]), execution, return_equity=True,
                funding=None if funding is None else funding.get(symbol, pd.Series(dtype=float)),
            )
            equity = result.get("equity_path")
            if equity is None or len(equity) < 2:
                raise TrendPortfolioError(f"{spec['audit_id']}/{symbol}: no equity path")
            # Drop the terminal liquidation point: it marks where the data ends, not a trade.
            columns[f"{spec['audit_id']}:{symbol}"] = _daily(equity.iloc[:-1]).pct_change()
    return pd.DataFrame(columns).iloc[1:]


def basket_daily_returns(frames: Mapping[str, pd.DataFrame], symbols: list[str]) -> pd.Series:
    opens = pd.DataFrame({s: _daily(frames[s]["open"].astype(float)) for s in symbols})
    # Return from open at day d to open at day d+1, stamped at d+1 like sleeve equity.
    return opens.pct_change().iloc[1:].mean(axis=1)


def causal_beta(portfolio: pd.Series, basket: pd.Series, *, window: int, minimum: int) -> pd.Series:
    """Beta for day t from days strictly before t."""
    joined = pd.concat([portfolio.rename("p"), basket.rename("b")], axis=1).dropna()
    cov = joined["p"].rolling(window, min_periods=minimum).cov(joined["b"])
    var = joined["b"].rolling(window, min_periods=minimum).var()
    return (cov / var).shift(1).fillna(0.0).reindex(portfolio.index).fillna(0.0)


def hedged_returns(
    portfolio: pd.Series, basket: pd.Series, beta: pd.Series, *, side_cost_bps: float
) -> pd.Series:
    turnover = beta.diff().abs().fillna(beta.abs())
    return portfolio - beta * basket.reindex(portfolio.index).fillna(0.0) - turnover * side_cost_bps / 10_000.0


def newey_west_t(values: pd.Series, lags: int) -> float | None:
    x = values.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < max(10, lags + 2):
        return None
    d = x - x.mean()
    s = float(d @ d) / n
    for lag in range(1, lags + 1):
        s += 2.0 * (1.0 - lag / (lags + 1.0)) * float(d[lag:] @ d[:-lag]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else None


def minimum_detectable_sharpe(days: int, t_threshold: float = 2.0) -> float | None:
    return t_threshold * math.sqrt(365.0 / days) if days > 0 else None


def summarize(returns: pd.Series, *, nw_lags: int) -> dict[str, Any]:
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"days": 0, "mean_daily_bps": None, "annualized_sharpe": None, "cumulative_return": 0.0,
                "max_drawdown": None, "newey_west_t": None, "minimum_detectable_sharpe": None}
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    equity = (1.0 + r).cumprod()
    return {
        "days": n,
        "mean_daily_bps": float(r.mean() * 10_000.0),
        "annualized_sharpe": float(r.mean() / sd * math.sqrt(365.0)) if sd > 0 else None,
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float((equity / equity.cummax() - 1.0).min()),
        "newey_west_t": newey_west_t(r, nw_lags),
        "minimum_detectable_sharpe": minimum_detectable_sharpe(n),
    }


def portfolio_series(
    config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.Series] | None = None,
) -> dict[str, pd.Series]:
    symbols = [str(s) for s in config["source"]["symbols"]]
    sleeves = sleeve_daily_returns(config, frames, funding)
    plain = sleeves.mean(axis=1)
    basket = basket_daily_returns(frames, symbols).reindex(plain.index)
    hedge = config["hedge"]
    beta = causal_beta(plain, basket, window=int(hedge["window_days"]), minimum=int(hedge["minimum_days"]))
    hedged = hedged_returns(plain, basket, beta, side_cost_bps=float(config["economics"]["round_trip_cost_bps"]) / 2.0)
    return {"plain": plain, "hedged": hedged, "beta": beta, "basket": basket}


def build_report(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], *, as_of: Any) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise TrendPortfolioError("wrong watch config")
    as_of_ts = _utc(as_of)
    start = _utc(config["prospective_start_utc"])
    clean = {s: completed_bars(frames[s], as_of_ts) for s in config["source"]["symbols"]}
    series = portfolio_series(config, clean)
    # A return stamped at day d+1 covers day d; score it only if day d >= start.
    covered_day = series["plain"].index - pd.Timedelta(days=1)
    mask = covered_day >= start
    lags = int(config["reporting"]["newey_west_lags"])
    forward = {
        name: summarize(series[name].loc[mask], nw_lags=lags) for name in ("plain", "hedged", "basket")
    }
    days = forward["plain"]["days"]
    return {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "forward": forward,
        "latest_beta": float(series["beta"].iloc[-1]) if len(series["beta"]) else None,
        "historical_anchor": config["historical_anchor"],
        "days_to_detect_anchor_sharpe": {
            name: (
                math.ceil(365.0 * (2.0 / anchor["annualized_sharpe"]) ** 2)
                if anchor.get("annualized_sharpe") and anchor["annualized_sharpe"] > 0
                else None
            )
            for name, anchor in config["historical_anchor"]["series"].items()
        },
        "review_window_open": days >= int(config["reporting"]["review_after_days"]),
        "daily_returns": {
            name: {ts.isoformat(): float(v) for ts, v in series[name].loc[mask].dropna().items()}
            for name in ("plain", "hedged")
        },
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    parser = argparse.ArgumentParser(description="Run the combined trend portfolio forward watch.")
    parser.add_argument("--config", default="config/universal_trend_portfolio_forward_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    src = config["source"]
    frames = {
        s: fetch_mexc_futures_klines(s, src["interval"], src["warmup_start_utc"], as_of.isoformat())
        for s in src["symbols"]
    }
    report = build_report(config, frames, as_of=as_of)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "days": report["forward"]["plain"]["days"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
