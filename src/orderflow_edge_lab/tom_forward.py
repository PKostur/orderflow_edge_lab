"""Turn-of-month SPY forward watch (turn-of-month-forward-v1).

Descriptive only.  The rule is strategy-search v1 candidate R1C4 reused byte for byte: the weight function and the
backtest helper come from ``strategy_search``.  Only days strictly after ``prospective_start_utc`` are scored.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab.trend_portfolio_forward import summarize

WATCH_ID = "turn-of-month-forward-v1"
DEFAULT_CONFIG = "config/turn_of_month_forward_v1.json"
PARAMS = {"days_before": 1, "days_after": 3}  # R1C4 as registered in strategy_search_v1_round1.json
COST_BPS_ROUND_TRIP = ss.COST_BPS_ROUND_TRIP
NW_LAGS = 5
HISTORY_START = "2026-01-01"


class TomForwardError(RuntimeError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def tom_weights(spy_close: pd.Series) -> pd.Series:
    prices = ss.build_prices({"SPY": spy_close})
    return ss.weights_R1C4_turn_of_month({"prices": prices}, PARAMS)["SPY"]


def tom_net_returns(spy_close: pd.Series) -> pd.Series:
    """Daily net return of the R1C4 rule on the SPY calendar (same functions as search v1)."""
    prices = ss.build_prices({"SPY": spy_close})
    weights = ss.weights_R1C4_turn_of_month({"prices": prices}, PARAMS)
    net, _ = ss.backtest(weights, ss.asset_returns(prices), COST_BPS_ROUND_TRIP)
    return net


def _summary(returns: pd.Series) -> dict[str, Any]:
    out = summarize(returns, nw_lags=NW_LAGS)
    # summarize annualizes on 365 days; the registration says 252 for SPY
    if out["annualized_sharpe"] is not None:
        out["annualized_sharpe"] = float(out["annualized_sharpe"] * math.sqrt(252.0 / 365.0))
    out["minimum_detectable_sharpe"] = 2.0 * math.sqrt(252.0 / out["days"]) if out["days"] > 0 else None
    return out


def build_report(config: Mapping[str, Any], spy_close: pd.Series, *, as_of: Any) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise TomForwardError("wrong watch config")
    as_of_ts = _utc(as_of)
    start = _utc(config["prospective_start_utc"])
    close = spy_close.dropna().sort_index()
    close = close[close.index <= as_of_ts]
    if close.empty:
        raise TomForwardError("no SPY data")
    net = tom_net_returns(close)
    spy_ret = close.pct_change(fill_method=None)
    tom_fwd = net.loc[net.index > start]
    spy_fwd = spy_ret.reindex(tom_fwd.index)
    held = tom_weights(close).shift(1).reindex(tom_fwd.index).fillna(0.0) > 0
    days = int(len(tom_fwd))
    review_days = int(config["reporting"]["review_after_days"])
    return {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "forward": {"tom": _summary(tom_fwd), "spy": _summary(spy_fwd)},
        "invested_days": int(held.sum()),
        "review_window_open": bool((as_of_ts - start).days >= review_days),
        "daily_returns": {"tom": {ts.isoformat(): float(v) for ts, v in tom_fwd.dropna().items()}},
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the turn-of-month SPY forward watch.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    end = (as_of + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    close = ss.fetch_close("SPY", HISTORY_START, end, cache=False)
    report = build_report(config, close, as_of=as_of)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "days": report["forward"]["tom"]["days"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
