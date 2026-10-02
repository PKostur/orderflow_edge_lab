"""Forward watch: crypto-trend-core book with a portfolio-level volatility target."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.portfolio_vol_target import vol_target_overlay
from orderflow_edge_lab.trend_portfolio_forward import _daily, _utc, completed_bars, sleeve_daily_returns, summarize
from orderflow_edge_lab.universal_backtest import legacy_strategy
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

WATCH_ID = "crypto-trend-core-voltarget-v1"


def book_gross(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]) -> pd.Series:
    """Mean over sleeves of the absolute sized weight actually held, at daily stamps."""
    sz = config["sizing"]
    cols = {}
    for spec in config["strategies"]:
        strat = vol_sized_strategy(legacy_strategy(str(spec["family"])), window=int(sz["window_bars"]),
                                   target_vol=float(sz["target_annual_vol"]), cap=float(sz["cap"]),
                                   bars_per_year=int(sz.get("bars_per_year", 1095)))
        for s, f in frames.items():
            held = strat.generate_target(f, spec["parameters"], None).reindex(f.index).fillna(0.0).shift(1).fillna(0.0).abs()
            cols[f"{spec['audit_id']}:{s}"] = _daily(held)
    return pd.DataFrame(cols).mean(axis=1)


def build_report(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series],
                 *, as_of: Any) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise ValueError("wrong watch config")
    as_of_ts, start = _utc(as_of), _utc(config["prospective_start_utc"])
    symbols = config["groups"]["crypto"]
    clean = {s: completed_bars(frames[s], as_of_ts) for s in symbols}
    base_cfg = {**config, "source": {**config["source"], "symbols": symbols}}
    base = sleeve_daily_returns(base_cfg, clean, funding).mean(axis=1).dropna()
    gross = book_gross(config, clean).reindex(base.index).ffill().fillna(0.0)
    o = config["portfolio_overlay"]
    ov = vol_target_overlay(base, gross, target_annual_vol=float(o["target_annual_vol"]),
                            window_days=int(o["window_days"]), max_leverage=float(o["max_leverage"]),
                            rebalance=str(o["rebalance"]), cost_bps=float(config["economics"]["round_trip_cost_bps"]))
    mask = (base.index - pd.Timedelta(days=1)) >= start
    lags = int(config["reporting"]["newey_west_lags"])
    fwd_base = base.loc[mask]
    fwd_ov = ov["returns"].reindex(base.index).loc[mask]
    days = int(len(fwd_base))
    lev, grs = ov["leverage"], ov["gross_exposure"]
    return {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "forward": {"core": summarize(fwd_base, nw_lags=lags), "core_voltarget": summarize(fwd_ov, nw_lags=lags)},
        "overlay_state": {
            "latest_leverage": float(lev.iloc[-1]) if len(lev) else None,
            "latest_gross": float(grs.iloc[-1]) if len(grs) else None,
            "forward_mean_leverage": float(lev.reindex(base.index).loc[mask].mean()) if days else None,
        },
        "daily_returns": {"core": {t.isoformat(): float(v) for t, v in fwd_base.items()},
                          "core_voltarget": {t.isoformat(): float(v) for t, v in fwd_ov.items()}},
        "review_window_open": days >= int(config["reporting"]["review_after_days"]),
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Run the crypto-trend-core vol-target forward watch.")
    p.add_argument("--config", default="config/crypto_trend_core_voltarget_v1.json")
    p.add_argument("--output", required=True)
    p.add_argument("--as-of", default=None)
    a = p.parse_args(argv)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    as_of = _utc(a.as_of) if a.as_of else pd.Timestamp.now(tz="UTC")
    src = config["source"]
    frames, funding = {}, {}
    for s in config["groups"]["crypto"]:
        frames[s] = fetch_mexc_futures_klines(s, src["interval"], src["warmup_start_utc"], as_of.isoformat())
        funding[s] = fetch_mexc_funding_history(s, src["warmup_start_utc"], as_of.isoformat())["funding_rate"]
    report = build_report(config, frames, funding, as_of=as_of)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "days": report["forward"]["core"]["days"],
                      "latest_leverage": report["overlay_state"]["latest_leverage"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
