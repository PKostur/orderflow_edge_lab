"""Run strategy-search-v1 round 2 exactly once (single look).

Candidates, in registration order: R2C1_CTREND (Binance spot USDT pairs, 365-day annualisation, 20 bps round trip) and
R2C2_FOMC_cycle_even_weeks (SPY, 252-day annualisation, 10 bps round trip).  All eight gates G1-G8; G5 uses every
prior ledger trial plus the two round-2 candidates (order-free).

Refuses to run if ``research/strategy_search_v1/round2_results.json`` exists or the ledger holds any round-2 record.
There is no ``--draws`` option (999 null draws); path overrides exist only behind ``--test-mode``.
Usage: PYTHONPATH=src .venv/Scripts/python scripts/strategy_search_v1_round2.py
Descriptive research only: no promotion, no live trading.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

from orderflow_edge_lab import binance_spot_archive as archive
from orderflow_edge_lab import ctrend
from orderflow_edge_lab import fomc_cycle
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2

ROOT = Path(__file__).resolve().parents[1]
FETCH_START = "1990-01-01"
FETCH_END_EXCLUSIVE = "2026-10-01"  # validation window ends 2026-09-30
OVERRIDE_OPTIONS = ("protocol", "round_config", "results", "ledger", "crypto_config", "crypto_pickle")
ROUND = 2


def load_crypto_panel() -> dict[str, Any]:
    """CTREND data: Binance spot USDT pairs up to 2026-09-30 as dates x symbols frames plus provenance."""
    panel = archive.load_universe(end="2026-09-30", workers=24)
    return {"close": panel["close"], "high": panel["high"], "low": panel["low"],
            "dollar_volume": panel["quote_volume"], "provenance": panel["provenance"]}


def load_spy_data() -> tuple[dict[str, Any], pd.DataFrame, pd.Series, dict[str, Any]]:
    end_ts = pd.Timestamp(FETCH_END_EXCLUSIVE, tz="UTC")
    close = ss.fetch_close("SPY", FETCH_START, FETCH_END_EXCLUSIVE)
    close = close.loc[close.index < end_ts]
    prices = ss.build_prices({"SPY": close}, calendar_symbol="SPY")
    returns = ss.asset_returns(prices)
    data = {"prices": prices, "_calendar": pd.DatetimeIndex(prices.index)}
    return data, returns, returns["SPY"], ss.data_provenance(prices, {})


def crypto_provenance(panel: dict[str, Any]) -> dict[str, Any]:
    prov = dict(panel["provenance"])
    prov["close_frame_sha256"] = ss.frame_sha256(panel["close"])
    prov["dollar_volume_frame_sha256"] = ss.frame_sha256(panel["dollar_volume"])
    prov["high_frame_sha256"] = ss.frame_sha256(panel["high"])
    prov["low_frame_sha256"] = ss.frame_sha256(panel["low"])
    prov["frame_rows"] = int(len(panel["close"]))
    prov["frame_first_date"] = str(panel["close"].index[0].date())
    prov["frame_last_date"] = str(panel["close"].index[-1].date())
    return prov


def ctrend_descriptive(result: dict[str, Any], data: dict[str, Any], returns: pd.DataFrame) -> dict[str, Any]:
    """Descriptive extras for CTREND: the paper's own cost scenarios, model selection counts, universe size."""
    detail = r2.buy_and_hold_detail(result["_weights"], data["close"], 0.0)  # gross + per-leg turnover
    series_by_scenario = {f"{int(cl)}/{int(cs)}": detail["gross"] - detail["turnover_long"] * cl / 1e4
                          - detail["turnover_short"] * cs / 1e4 for cl, cs in ((30.0, 40.0), (40.0, 50.0))}
    scen = {"series": series_by_scenario, "mean_daily_turnover_long": float(detail["turnover_long"].mean()),
            "mean_daily_turnover_short": float(detail["turnover_short"].mean())}
    windows = result["windows"]
    out: dict[str, Any] = {"paper_cost_scenarios_one_way_bps_long_short": {}}
    for name, series in scen["series"].items():
        entry = {}
        for label in ("development", "validation"):
            lo, hi = (ss._utc_ts(windows[label][0]), ss._utc_ts(windows[label][1]))
            entry[label] = ss.perf_stats(ss.slice_window(series, lo, hi), r2.CRYPTO_PERIODS_PER_YEAR)
        out["paper_cost_scenarios_one_way_bps_long_short"][name] = entry
    out["mean_daily_turnover_long"] = scen["mean_daily_turnover_long"]
    out["mean_daily_turnover_short"] = scen["mean_daily_turnover_short"]
    out["note"] = ("weekly buy-and-hold book, 0.5 gross per leg (paper: 1.0 per leg); costs = long-leg turnover x long "
                   "bps + short-leg turnover x short bps, charged on the first day of the week; descriptive only")
    engine = ctrend.get_engine(data)
    sig = engine.signals(result["params"])
    valid = sig["valid"]
    out["weeks_with_model"] = int(valid.sum())
    out["mean_indicators_kept_per_week"] = float(sig["n_kept"][valid].mean()) if valid.any() else None
    out["weeks_without_kept_forecast"] = int((valid & (sig["n_kept"] == 0)).sum())
    out["eligible_coins_per_week"] = {
        "min": int(engine.eligible.sum(axis=1).min()), "median": float(pd.Series(engine.eligible.sum(axis=1)).median()),
        "max": int(engine.eligible.sum(axis=1).max())}
    out["coins_ever_eligible"] = len(engine.columns)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run strategy-search-v1 round 2 once.")
    parser.add_argument("--test-mode", action="store_true", help="allow path overrides (unit tests only)")
    parser.add_argument("--protocol")
    parser.add_argument("--round-config")
    parser.add_argument("--results")
    parser.add_argument("--ledger")
    parser.add_argument("--crypto-config")
    parser.add_argument("--crypto-pickle")
    args = parser.parse_args(argv)

    overridden = [name for name in OVERRIDE_OPTIONS if getattr(args, name) is not None]
    if overridden and not args.test_mode:
        print(f"REFUSED: {overridden} may only be overridden together with --test-mode.", file=sys.stderr)
        return 2

    protocol_path = Path(args.protocol or ROOT / "config" / "strategy_search_v1.json")
    round_path = Path(args.round_config or ROOT / "config" / "strategy_search_v1_round2.json")
    results_path = Path(args.results or ROOT / "research" / "strategy_search_v1" / "round2_results.json")
    ledger_path = Path(args.ledger or ROOT / "research" / "strategy_search_v1" / "trials.jsonl")
    crypto_config = Path(args.crypto_config or ROOT / "config" / "crypto_trend_core_v1.json")
    crypto_pickle = Path(args.crypto_pickle or os.path.join(os.environ.get("TEMP", "."), "multi_premia_data.pkl"))

    if results_path.exists():
        print(f"REFUSED: {results_path} already exists; round 2 is a single look and is never rerun.", file=sys.stderr)
        return 2
    prior = ss.read_trials(ledger_path)
    if any(rec.get("round") == ROUND for rec in prior):
        print(f"REFUSED: {ledger_path} already holds round-2 records; round 2 is a single look.", file=sys.stderr)
        return 2

    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    round_cfg = json.loads(round_path.read_text(encoding="utf-8"))
    if protocol.get("search_id") != "strategy-search-v1" or round_cfg.get("search_id") != "strategy-search-v1":
        raise SystemExit("wrong search id")
    if round_cfg.get("round") != ROUND:
        raise SystemExit("not the round 2 config")
    specs = {s["id"]: s for s in r2.candidate_specs(round_cfg)}
    if list(specs) != [r2.CTREND_ID, r2.FOMC_ID]:
        raise SystemExit(f"unexpected candidate order: {list(specs)}")

    reference = ss.crypto_trend_core_reference(crypto_config, crypto_pickle)

    # ---- R2C1 CTREND
    panel = load_crypto_panel()
    crypto_prov = crypto_provenance(panel)
    crypto_data = {k: panel[k] for k in ("close", "high", "low", "dollar_volume")}
    # a zero close would give an infinite return; treat it as missing
    crypto_returns = ss.asset_returns(panel["close"]).replace([float("inf"), float("-inf")], float("nan"))
    eligible_daily = ctrend.eligible_mask_daily(crypto_data)
    close = panel["close"]

    def account(weights, returns, cost):
        return r2.buy_and_hold_detail(weights, close, cost)

    def allocation_null(weights, dev_start, dev_end, *, n_draws, seed):
        return r2.g4_buy_and_hold_allocation_null(weights, close, eligible_daily, dev_start, dev_end,
                                                  n_draws=n_draws, seed=seed)

    fomc_data, fomc_returns, spy_returns, spy_provenance = load_spy_data()
    results = []
    c1 = r2.evaluate_candidate_general(
        specs[r2.CTREND_ID], crypto_data, crypto_returns, validation_window=specs[r2.CTREND_ID]["validation"],
        crypto_reference=reference, spy_returns=spy_returns, cost_bps=r2.CRYPTO_COST_BPS_ROUND_TRIP,
        periods_per_year=r2.CRYPTO_PERIODS_PER_YEAR, fn=ctrend.ctrend_weights,
        truncation_fn=ctrend.ctrend_weights_last_week, detail_fn=account, null_fn=allocation_null,
        g8_mode="crypto_only",
        n_draws=ss.N_NULL_DRAWS, n_truncation_dates=ss.N_TRUNCATION_DATES)
    c1["descriptive"] = ctrend_descriptive(c1, crypto_data, crypto_returns)
    results.append(c1)

    # ---- R2C2 FOMC cycle
    c2 = r2.evaluate_candidate_general(
        specs[r2.FOMC_ID], fomc_data, fomc_returns, validation_window=specs[r2.FOMC_ID]["validation"],
        crypto_reference=reference, spy_returns=spy_returns, cost_bps=r2.ETF_COST_BPS_ROUND_TRIP,
        periods_per_year=r2.ETF_PERIODS_PER_YEAR, fn=fomc_cycle.weights_R2C2_fomc_cycle, g8_mode="both",
        n_draws=ss.N_NULL_DRAWS, n_truncation_dates=ss.N_TRUNCATION_DATES)
    results.append(c2)

    ss.apply_dsr(results, ss.ledger_trial_sharpes(prior))

    summary = []
    for r in results:
        passed, first_fail = ss.verdict(r)
        summary.append({"id": r["id"], "pass": passed, "first_failing_gate": first_fail})
        print(f"{r['id']:30s} {'PASS' if passed else 'FAIL'}" + ("" if passed else f"  first failing gate: {first_fail}"))

    stamp = datetime.now(timezone.utc).isoformat()
    meetings = fomc_cycle.load_scheduled_meetings()
    payload = {
        "schema_version": 1,
        "search_id": protocol["search_id"],
        "round": ROUND,
        "generated_utc": stamp,
        "cost_bps_round_trip": {r2.CTREND_ID: r2.CRYPTO_COST_BPS_ROUND_TRIP, r2.FOMC_ID: r2.ETF_COST_BPS_ROUND_TRIP},
        "periods_per_year": {r2.CTREND_ID: r2.CRYPTO_PERIODS_PER_YEAR, r2.FOMC_ID: r2.ETF_PERIODS_PER_YEAR},
        "null_draws": ss.N_NULL_DRAWS,
        "n_trials_cumulative": len(ss.ledger_trial_sharpes(prior)) + len(results),
        "g5_note": "trial set = ledger trials before this round + both round-2 candidates (order-free)",
        "g8_reference": {"book": "crypto-trend-core-v1 (DON8+EMA8, 17 coins, canonical v3.1, 20 bps)",
                         "source": ss.CRYPTO_REFERENCE_PROVENANCE,
                         "first_date": str(reference.index[0].date()), "last_date": str(reference.index[-1].date()),
                         "rows": int(len(reference)), "sha256": ss.series_sha256(reference)},
        "data_provenance": {
            "binance_spot": crypto_prov,
            "spy": spy_provenance,
            "fomc_meetings": {"file": "config/fomc_scheduled_meetings_1994_2026.json", "count": len(meetings),
                              "first": str(meetings[0].date()), "last": str(meetings[-1].date())},
        },
        "ctrend_constants": {"min_bars": ctrend.MIN_BARS, "min_dollar_volume": ctrend.MIN_DOLLAR_VOLUME,
                             "dollar_volume_window": ctrend.DOLLAR_VOLUME_WINDOW,
                             "dollar_volume_min_periods": ctrend.DOLLAR_VOLUME_MIN_PERIODS,
                             "min_cross_section": ctrend.MIN_CROSS_SECTION, "gross_per_leg": ctrend.GROSS_PER_LEG,
                             "accounting": "weekly buy-and-hold, turnover charged once per week on its first day",
                             "relisting_gap_days": archive.MAX_GAP_DAYS},
        "summary": summary,
        "candidates": [ss.json_clean(r) for r in results],
        "claims": dict(protocol["claims"]),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("x", encoding="utf-8", newline="\n") as handle:  # "x": never overwrite
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    for r in results:
        ss.append_trial(ledger_path, ss.ledger_record(r, ROUND))
    for record in ss.screened_out_records(round_cfg, ROUND):
        ss.append_trial(ledger_path, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
