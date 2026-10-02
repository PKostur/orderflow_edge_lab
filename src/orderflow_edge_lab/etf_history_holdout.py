"""One-shot evaluation of ``universal-etf-long-history-holdout-v1``.

Frozen trend rules mapped to daily bars at the same calendar horizons, on a
rule-chosen cross-asset ETF universe, 2007-2026.  Primary hypothesis and pass
rule come from the config.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping
import urllib.request

import numpy as np
import pandas as pd

from orderflow_edge_lab.pre_window_holdout import clip_to_window
from orderflow_edge_lab.trend_portfolio_forward import sleeve_daily_returns, summarize

PROTOCOL_ID = "universal-etf-long-history-holdout-v1"


class EtfHoldoutError(ValueError):
    pass


def adjusted_daily_frame(payload: Mapping[str, Any]) -> pd.DataFrame:
    """Yahoo chart payload -> split/dividend-adjusted OHLC stamped at 00:00 UTC."""
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    idx = pd.to_datetime(result["timestamp"], unit="s", utc=True).normalize()
    raw = pd.DataFrame(
        {"open": quote["open"], "high": quote["high"], "low": quote["low"], "close": quote["close"], "adj": adj},
        index=idx,
    ).apply(pd.to_numeric, errors="coerce").dropna()
    raw = raw[(raw[["open", "high", "low", "close", "adj"]] > 0).all(axis=1)]
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    factor = raw["adj"] / raw["close"]
    out = raw[["open", "high", "low", "close"]].mul(factor, axis=0)
    out["high"] = out[["open", "high", "low", "close"]].max(axis=1)
    out["low"] = out[["open", "high", "low", "close"]].min(axis=1)
    return out


def fetch_yahoo_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    p1, p2 = int(pd.Timestamp(start).timestamp()), int(pd.Timestamp(end).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return adjusted_daily_frame(json.load(response))


def evaluate(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    if config.get("protocol_id") != PROTOCOL_ID:
        raise EtfHoldoutError("wrong protocol config")
    classes = config["universe_rule"]["symbols"]
    symbols = [s for members in classes.values() for s in members]
    clipped = clip_to_window({s: frames[s] for s in symbols}, config["window"])
    base = {**config, "source": {**config["source"], "symbols": symbols}}
    base.pop("sizing", None)
    lags = 5
    sized = sleeve_daily_returns({**base, "sizing": config["sizing"]}, clipped)
    plain = sleeve_daily_returns(base, clipped)
    primary_series = sized.mean(axis=1)
    primary = summarize(primary_series, nw_lags=lags)
    passed = bool(primary["mean_daily_bps"] and primary["mean_daily_bps"] > 0
                  and primary["newey_west_t"] is not None and primary["newey_west_t"] >= 2.0)

    def cols(frame: pd.DataFrame, pred) -> list[str]:
        return [c for c in frame.columns if pred(c)]

    per_strategy = {a["audit_id"]: summarize(sized[cols(sized, lambda c, a=a: c.startswith(a["audit_id"] + ":"))].mean(axis=1), nw_lags=lags)
                    for a in config["strategies"]}
    per_class = {k: summarize(sized[cols(sized, lambda c, m=m: c.split(":", 1)[1] in m)].mean(axis=1), nw_lags=lags)
                 for k, m in classes.items()}
    per_year = {str(y): float((1 + r).prod() - 1) for y, r in primary_series.groupby(primary_series.index.year)}
    joined = pd.concat([primary_series.rename("p"), clipped["SPY"]["open"].pct_change().rename("s")], axis=1).dropna()
    data_hash = sha256("".join(f"{s}:{len(clipped[s])}:{float(clipped[s]['open'].sum()):.6f}"
                               for s in sorted(clipped)).encode()).hexdigest()
    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "window": dict(config["window"]),
        "bars_per_symbol": {s: int(len(clipped[s])) for s in sorted(clipped)},
        "first_bar": {s: str(clipped[s].index.min().date()) for s in sorted(clipped) if len(clipped[s])},
        "data_hash": data_hash,
        "primary": {**primary, "pass_rule": config["hypotheses"]["primary"]["pass_rule"], "passed": passed},
        "secondary": {
            "plus_minus_one": summarize(plain.mean(axis=1), nw_lags=lags),
            "per_strategy": per_strategy,
            "per_asset_class": per_class,
            "per_year": per_year,
            "corr_with_spy_daily": float(np.corrcoef(joined["p"], joined["s"])[0, 1]) if len(joined) > 2 else None,
        },
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate the ETF long-history holdout once.")
    parser.add_argument("--config", default="config/universal_etf_long_history_holdout_v1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    symbols = [s for m in config["universe_rule"]["symbols"].values() for s in m]
    frames = {s: fetch_yahoo_daily(s, "2006-01-01", config["window"]["end_exclusive"]) for s in symbols}
    report = evaluate(config, frames)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["primary"]["passed"], "t": report["primary"]["newey_west_t"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
