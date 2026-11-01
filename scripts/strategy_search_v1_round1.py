"""Run strategy-search-v1 round 1 exactly once (single look).

Refuses to run if ``research/strategy_search_v1/round1_results.json`` already exists or if the ledger already holds
any round-1 record.  Loads the two frozen configs, fetches Yahoo / FRED data, evaluates the seven registered
candidates in registration order, writes the results file and appends one line per candidate to
``research/strategy_search_v1/trials.jsonl``.

Usage: PYTHONPATH=src .venv/Scripts/python scripts/strategy_search_v1_round1.py
Path overrides exist only behind --test-mode (used by the unit tests); the number of null draws is fixed at 999.
Descriptive research only: no promotion, no live trading.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import pandas as pd

from orderflow_edge_lab import strategy_search as ss

ROOT = Path(__file__).resolve().parents[1]
FETCH_START = "1990-01-01"
FETCH_END_EXCLUSIVE = "2026-10-01"  # validation window ends 2026-09-30
OVERRIDE_OPTIONS = ("protocol", "round_config", "results", "ledger", "crypto_config", "crypto_pickle")


def all_tickers(round_cfg: dict) -> list[str]:
    tickers: list[str] = []
    for c in round_cfg["candidates"]:
        uni = c["universe"]
        if isinstance(uni, dict):
            for v in uni.values():
                tickers.extend(v if isinstance(v, list) else [v])
        else:
            tickers.extend(uni)
        tickers.extend(t for t in c.get("signal_data", []) if t.startswith("^"))
    return list(dict.fromkeys(t for t in tickers if not t.startswith("FRED")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run strategy-search-v1 round 1 once.")
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
    round_path = Path(args.round_config or ROOT / "config" / "strategy_search_v1_round1.json")
    results_path = Path(args.results or ROOT / "research" / "strategy_search_v1" / "round1_results.json")
    ledger_path = Path(args.ledger or ROOT / "research" / "strategy_search_v1" / "trials.jsonl")
    crypto_config = Path(args.crypto_config or ROOT / "config" / "crypto_trend_core_v1.json")
    crypto_pickle = Path(args.crypto_pickle or os.path.join(os.environ.get("TEMP", "."), "multi_premia_data.pkl"))

    if results_path.exists():
        print(f"REFUSED: {results_path} already exists; round 1 is a single look and is never rerun.", file=sys.stderr)
        return 2
    prior = ss.read_trials(ledger_path)
    if any(rec.get("round") == 1 for rec in prior):
        print(f"REFUSED: {ledger_path} already holds round-1 records; round 1 is a single look.", file=sys.stderr)
        return 2

    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    round_cfg = json.loads(round_path.read_text(encoding="utf-8"))
    if protocol.get("search_id") != "strategy-search-v1" or round_cfg.get("search_id") != "strategy-search-v1":
        raise SystemExit("wrong search id")
    if round_cfg.get("round") != 1:
        raise SystemExit("not the round 1 config")
    cost_bps = ss.COST_BPS_ROUND_TRIP  # "10 bps round trip on traded weight" (round-1 registration, common.cost)
    end_ts = pd.Timestamp(FETCH_END_EXCLUSIVE, tz="UTC")

    closes = {t: ss.fetch_close(t, FETCH_START, FETCH_END_EXCLUSIVE) for t in all_tickers(round_cfg)}
    closes = {t: s.loc[s.index < end_ts] for t, s in closes.items()}
    prices = ss.build_prices(closes, calendar_symbol="SPY")  # every series on the SPY trading calendar
    fred = {sid: ss.fetch_fred(sid) for sid in ("DTB3", "DCOILWTICO")}
    fred = {sid: s.loc[s.index < end_ts] for sid, s in fred.items()}
    data = {"prices": prices, **fred, "_calendar": pd.DatetimeIndex(prices.index)}
    returns = ss.asset_returns(prices)
    spy_returns = returns["SPY"]
    reference = ss.crypto_trend_core_reference(crypto_config, crypto_pickle)

    results = []
    for spec in round_cfg["candidates"]:
        results.append(ss.evaluate_candidate(
            spec, data, returns, validation_window=round_cfg["common"]["validation_window"],
            crypto_reference=reference, spy_returns=spy_returns, cost_bps=cost_bps, n_draws=ss.N_NULL_DRAWS))
    ss.apply_dsr(results, ss.ledger_trial_sharpes(prior))

    summary = []
    for r in results:
        passed, first_fail = ss.verdict(r)
        summary.append({"id": r["id"], "pass": passed, "first_failing_gate": first_fail})
        print(f"{r['id']:28s} {'PASS' if passed else 'FAIL'}" + ("" if passed else f"  first failing gate: {first_fail}"))

    stamp = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": 1,
        "search_id": protocol["search_id"],
        "round": 1,
        "generated_utc": stamp,
        "cost_bps_round_trip": cost_bps,
        "null_draws": ss.N_NULL_DRAWS,
        "n_trials_cumulative": len(ss.ledger_trial_sharpes(prior)) + len(results),
        "g5_note": "trial set = ledger trials before this round + all seven candidates of this round (order-free)",
        "g8_reference": {"book": "crypto-trend-core-v1 (DON8+EMA8, 17 coins, canonical v3.1, 20 bps)",
                         "source": ss.CRYPTO_REFERENCE_PROVENANCE,
                         "file": "multi_premia_data.pkl cached frames, data to 2026-09-11",
                         "first_date": str(reference.index[0].date()), "last_date": str(reference.index[-1].date()),
                         "rows": int(len(reference)), "sha256": ss.series_sha256(reference)},
        "gem_tbill_scaling": ss.GEM_TBILL_SCALING_NOTE,
        "data_last_date": str(prices.index[-1].date()),
        "data_provenance": ss.data_provenance(prices, fred),
        "summary": summary,
        "candidates": [ss.json_clean(r) for r in results],
        "claims": dict(protocol["claims"]),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("x", encoding="utf-8", newline="\n") as handle:  # "x": never overwrite
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    for r in results:
        ss.append_trial(ledger_path, ss.ledger_record(r, 1))
    for record in ss.screened_out_records(round_cfg, 1):
        ss.append_trial(ledger_path, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
