"""Cross-asset trend portfolio forward watch (``universal-cross-asset-trend-forward-v1``).

The frozen DON8/EMA8/VOL8 rules on 10 crypto perps plus liquid MEXC tradfi perps
chosen by a mechanical rule, scored on daily net P&L under canonical v3.1
(fixed quantity plus funding).  Descriptive until the review horizon.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.effective_bets import participation_ratio
from orderflow_edge_lab.trend_portfolio_forward import (
    _utc,
    completed_bars,
    sleeve_daily_returns,
    summarize,
)

WATCH_ID = "universal-cross-asset-trend-forward-v1"


class CrossAssetTrendError(ValueError):
    pass


def build_report(
    config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.Series],
    *,
    as_of: Any,
) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise CrossAssetTrendError("wrong watch config")
    as_of_ts = _utc(as_of)
    start = _utc(config["prospective_start_utc"])
    groups = {name: [str(s) for s in symbols] for name, symbols in config["groups"].items()}
    symbols = [s for members in groups.values() for s in members]
    missing = [s for s in symbols if s not in frames]
    if missing:
        raise CrossAssetTrendError(f"missing frames: {missing}")
    clean = {s: completed_bars(frames[s], as_of_ts) for s in symbols}
    sleeves = sleeve_daily_returns(
        {**config, "source": {**config["source"], "symbols": symbols}}, clean, funding
    )
    no_funding = sleeve_daily_returns(
        {**config, "source": {**config["source"], "symbols": symbols}}, clean, None
    )
    covered_day = sleeves.index - pd.Timedelta(days=1)
    mask = covered_day >= start
    lags = int(config["reporting"]["newey_west_lags"])

    def columns(members: list[str]) -> list[str]:
        return [c for c in sleeves.columns if c.split(":", 1)[1] in members]

    selections = {"combined": list(sleeves.columns), **{g: columns(m) for g, m in groups.items()}}
    series, forward, funding_contribution, breadth = {}, {}, {}, {}
    for name, cols in selections.items():
        r = sleeves[cols].mean(axis=1)
        series[name] = r
        forward[name] = summarize(r.loc[mask], nw_lags=lags)
        diff = (r - no_funding[cols].mean(axis=1)).loc[mask].dropna()
        funding_contribution[name] = {
            "days": int(len(diff)),
            "annualized": float(diff.mean() * 365.0) if len(diff) else None,
        }
        fwd = sleeves.loc[mask, cols].dropna(how="all")
        breadth[name] = participation_ratio(fwd) if len(fwd) >= 60 else None

    days = forward["combined"]["days"]
    return {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "forward": forward,
        "funding_contribution": funding_contribution,
        "forward_sleeve_breadth": breadth,
        "review_window_open": days >= int(config["reporting"]["review_after_days"]),
        "daily_returns": {
            name: {ts.isoformat(): float(v) for ts, v in series[name].loc[mask].dropna().items()}
            for name in selections
        },
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    parser = argparse.ArgumentParser(description="Run the cross-asset trend forward watch.")
    parser.add_argument("--config", default="config/universal_cross_asset_trend_forward_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    src = config["source"]
    symbols = [s for members in config["groups"].values() for s in members]
    frames, funding = {}, {}
    for s in symbols:
        frames[s] = fetch_mexc_futures_klines(s, src["interval"], src["warmup_start_utc"], as_of.isoformat())
        funding[s] = fetch_mexc_funding_history(s, src["warmup_start_utc"], as_of.isoformat())["funding_rate"]
    report = build_report(config, frames, funding, as_of=as_of)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "days": report["forward"]["combined"]["days"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
