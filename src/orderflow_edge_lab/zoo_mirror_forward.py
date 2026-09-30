"""Forward watch: mirrors of strategy-zoo-v1 Z2 and Z4 (config/zoo_mirror_forward_v1.json). Forward days only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.strategy_zoo import BTC, btc_leadlag_targets, max_lottery_score, run_targets
from orderflow_edge_lab.trend_portfolio_forward import _utc, completed_bars, summarize
from orderflow_edge_lab.xs_premia import daily_funding_panel, daily_open_panel, run_xs

WATCH_ID = "zoo-mirror-forward-v1"


def mirror_books(frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series], *, cost_bps: float) -> pd.DataFrame:
    opens = daily_open_panel(frames)
    fund = daily_funding_panel(funding, opens.index)
    if BTC not in opens.columns:
        raise ValueError("BTC_USDT is required for the BTC shock reversal book")
    m2 = run_targets(-btc_leadlag_targets(opens), opens, fund, cost_bps=cost_bps)
    m4 = run_xs(opens, fund, -max_lottery_score(opens), rebalance_days=7, q=0.25, cost_bps=cost_bps)["returns"]
    books = pd.DataFrame({"M2_btc_shock_reversal": m2, "M4_lottery_momentum": m4})
    books.index = books.index + pd.Timedelta(days=1)  # stamp at the end of the held day, like the other watches
    return books


def build_report(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series],
                 *, as_of: Any, cost_bps: float = 20.0) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise ValueError("wrong watch config")
    as_of_ts, start = _utc(as_of), _utc(config["prospective_start_utc"])
    clean = {s: completed_bars(f, as_of_ts) for s, f in frames.items()}
    clean = {s: f for s, f in clean.items() if len(f) >= 100}
    books = mirror_books(clean, funding, cost_bps=cost_bps)
    fwd = books[(books.index - pd.Timedelta(days=1)) >= start]
    days = int(fwd.dropna(how="all").shape[0])
    return {
        "schema_version": 1, "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(),
        "coins_with_data": len(clean),
        "forward": {k: summarize(fwd[k].dropna(), nw_lags=5) for k in fwd.columns},
        "daily_returns": {k: {t.isoformat(): float(v) for t, v in fwd[k].dropna().items()} for k in fwd.columns},
        "review_window_open": days >= int(config["reporting"]["review_after_days"]),
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Run the zoo mirror forward watch.")
    p.add_argument("--config", default="config/zoo_mirror_forward_v1.json")
    p.add_argument("--output", required=True)
    p.add_argument("--as-of", default=None)
    a = p.parse_args(argv)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    universe = json.loads(Path(config["universe_config"].split(" ")[0]).read_text(encoding="utf-8"))
    as_of = _utc(a.as_of) if a.as_of else pd.Timestamp.now(tz="UTC")
    warm = universe["source"]["warmup_start_utc"]

    def load(s):
        try:
            return (s, fetch_mexc_futures_klines(s, "8h", warm, as_of.isoformat()),
                    fetch_mexc_funding_history(s, warm, as_of.isoformat())["funding_rate"])
        except Exception:
            return s, None, None

    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, universe["symbols"]))
    frames = {s: f for s, f, _ in got if f is not None}
    funding = {s: fu for s, f, fu in got if f is not None}
    report = build_report(config, frames, funding, as_of=as_of)
    report["missing_symbols"] = sorted(s for s, f, _ in got if f is None)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "coins": report["coins_with_data"], "missing": report["missing_symbols"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
