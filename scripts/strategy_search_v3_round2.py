"""Run strategy-search-v3 round 2 exactly once (single look).

Candidate: V3R2C1_liquidation_cascade_reversal (Binance USDT-M perps, 1h price move <= -5% / >= +5% over 4h together with
a >= 5% fall in 5-minute open interest, fade the move for 24h, 14 bps round trip, realized funding).  Gates G1-G8 at 1x
with the v2 G5 (``deflated_sharpe_null_consistent``, N = every tested trial in the v1, v2 (if the file exists) and v3
ledgers including this one: 11), G8 against the crypto trend core only, then the leverage assessment on the validation
sample using the trade book (positions with their own entry / exit windows and mark-price high / low).

Refuses to run if ``research/strategy_search_v3/round2_results.json`` (or ``round2_leverage.json``) exists or the v3
ledger holds any round-2 record.  There is no draw override; path overrides exist only behind ``--test-mode``.

Order of events (the gate verdict is saved before anything else can fail): data load, funding and open-interest
integrity checks (fail loudly) -> G1-G8 -> ``round2_results.json`` + ledger record -> PASS/FAIL printed -> leverage
assessment -> ``round2_leverage.json`` + a ``leverage_update`` ledger record.

Usage: PYTHONPATH=src .venv/Scripts/python scripts/strategy_search_v3_round2.py
Descriptive research only: no promotion, no live trading, no orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_metrics as bfm
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import perp_basis_strategy as pbs
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2

ROOT = Path(__file__).resolve().parents[1]
SEARCH_ID = "strategy-search-v3-leveraged"
ROUND = 2
DATA_END = "2026-09-30"
MAX_EXIT = "2026-09-30 23:59:59"  # the 2026-10-01 00:00 funding settlement is not in the monthly files
FUNDING_REQUIRED_LAST = "2026-09-30 16:00"  # every contract trading then must have a settlement on or after this
FINAL_WEEK_START = "2026-09-24 00:00"
OI_REQUIRED_FIRST = "2021-12-01 23:55"  # every contract needs open interest from the first sample day (2021-12-01)
OI_REQUIRED_LAST = "2026-09-30 22:00"  # every contract trading at FUNDING_REQUIRED_LAST needs records to here
OVERRIDE_OPTIONS = ("protocol", "round_config", "results", "leverage_results", "ledger", "v1_ledger", "v2_ledger",
                    "crypto_config", "crypto_pickle", "universe_file")


def count_tested(records: list[dict[str, Any]]) -> int:
    return sum(1 for rec in records if rec.get("status") == "tested")


def check_universe_definition(definition: dict[str, Any]) -> None:
    """The fixed universe file must record the amended registered criteria; anything else fails loudly."""
    absent = [k for k in ("symbols", "metrics_day", "size", "rank_window") if k not in definition]
    if absent:
        raise SystemExit(f"universe file lacks {absent}: it was not written by the prefetch script")
    expected = {"symbols": list(definition["symbols"]), "metrics_day": bfm.DATA_START, "size": bfm.UNIVERSE_SIZE,
                "rank_window": [bfm.RANK_START, bfm.RANK_END]}
    if not bfm.universe_matches(definition, expected):
        raise SystemExit(f"universe file criteria differ from the registration {expected}: "
                         f"metrics_day={definition['metrics_day']!r} size={definition['size']!r} "
                         f"rank_window={definition['rank_window']!r}")
    if len(definition["symbols"]) != bfm.UNIVERSE_SIZE or len(set(definition["symbols"])) != len(definition["symbols"]):
        raise SystemExit(f"universe file lists {len(definition['symbols'])} symbols, expected {bfm.UNIVERSE_SIZE} unique")


def load_universe(universe_file: Path | None = None) -> dict[str, Any]:
    """Real archive data.  The fixed universe comes from ``round2_universe.json`` (written by the prefetch script before
    the run) and is verified against the registration; a missing file is an error, never a silent rebuild."""
    path = universe_file or ROOT / "research" / "strategy_search_v3" / "round2_universe.json"
    if not path.exists():
        raise SystemExit(f"{path} is missing: run scripts/prefetch_binance_futures_metrics.py first")
    definition = json.loads(path.read_text(encoding="utf-8"))
    check_universe_definition(definition)
    data = lc.load_data(list(definition["symbols"]), end=DATA_END, workers=24)
    data["universe_definition"] = definition
    return data


def universe_provenance(universe: dict[str, Any], inputs: lc.CascadeInputs) -> dict[str, Any]:
    prov = universe["provenance"]
    out: dict[str, Any] = {"symbols": list(prov["symbols"]), "end": prov["end"], "mark_start": prov["mark_start"],
                           "oi_start": prov["oi_start"], "per_instrument": prov["per_instrument"],
                           "funding_summary": {"symbols": len(universe["funding"]),
                                               "intervals_hours_seen": sorted({x for v in prov["funding"].values()
                                                                               for x in v["interval_hours"]}),
                                               "symbols_without_funding_rows": sorted(
                                                   s for s, v in prov["funding"].items() if v["rows"] == 0)},
                           "oi_files": prov["oi"], "mark_symbols": len(universe["mark"])}
    if "universe_definition" in universe:
        out["universe_definition"] = universe["universe_definition"]
    for key, frame in inputs.data.items():
        out[f"{key}_frame_sha256"] = ss.frame_sha256(frame)
        out[f"{key}_shape"] = list(frame.shape)
    oi = prov["oi"]
    out["oi_summary"] = {
        "nonpositive_rows_total": int(sum(v.get("zero_or_negative_rows", 0) for v in oi.values())),
        "partial_days_total": int(sum(v.get("n_partial_days", 0) for v in oi.values())),
        "symbols_with_partial_days": sorted(s for s, v in oi.items() if v.get("n_partial_days", 0)),
        "duplicate_rows_dropped_total": int(sum(v.get("duplicate_rows_dropped", 0) for v in oi.values()))}
    out["max_exit"] = MAX_EXIT
    out["oi_snapshot_lag_minutes"] = lc.OI_SNAPSHOT_LAG_MINUTES
    return out


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:  # "x": never overwrite
        json.dump(ss.json_clean(payload), handle, indent=2, sort_keys=True, allow_nan=False, default=_json_default)
        handle.write("\n")


def trade_summary(trades: pd.DataFrame, windows: dict[str, list[str]], inputs: lc.CascadeInputs,
                  params: dict[str, Any]) -> dict[str, Any]:
    """Counts and mean per-trade returns by sample (exit day); descriptive only."""
    ev = lc.event_matrices(inputs.data, params)
    report = lc.event_report(inputs.data, params)
    exit_day = pd.DatetimeIndex(trades["exit_time"]).normalize() if len(trades) else pd.DatetimeIndex([], tz="UTC")
    out: dict[str, Any] = {"events_long": int(ev["long"].sum()), "events_short": int(ev["short"].sum()),
                           "event_report": report,
                           "trades_taken": int(len(trades)), "build_diagnostics": trades.attrs.get("diagnostics", {})}
    for label in ("development", "validation"):
        lo, hi = ss._utc_ts(windows[label][0]), ss._utc_ts(windows[label][1])
        part = trades.loc[np.asarray((exit_day >= lo) & (exit_day <= hi))]
        out[label] = {"trades": int(len(part)), "long": int((part["side"] > 0).sum()),
                      "short": int((part["side"] < 0).sum()),
                      "contracts_traded": int(part["symbol"].nunique()),
                      "mean_trade_gross_bps": float(part["trade_gross"].mean() * 1e4) if len(part) else None,
                      "mean_trade_net_bps": float((part["trade_gross"] - lc.COST_BPS_ROUND_TRIP / 1e4).mean() * 1e4)
                      if len(part) else None}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run strategy-search-v3 round 2 once.")
    parser.add_argument("--test-mode", action="store_true", help="allow path overrides (unit tests only)")
    for name in OVERRIDE_OPTIONS:
        parser.add_argument("--" + name.replace("_", "-"))
    args = parser.parse_args(argv)

    overridden = [name for name in OVERRIDE_OPTIONS if getattr(args, name) is not None]
    if overridden and not args.test_mode:
        print(f"REFUSED: {overridden} may only be overridden together with --test-mode.", file=sys.stderr)
        return 2

    protocol_path = Path(args.protocol or ROOT / "config" / "strategy_search_v3_leveraged.json")
    round_path = Path(args.round_config or ROOT / "config" / "strategy_search_v3_round2.json")
    results_path = Path(args.results or ROOT / "research" / "strategy_search_v3" / "round2_results.json")
    leverage_path = Path(args.leverage_results or ROOT / "research" / "strategy_search_v3" / "round2_leverage.json")
    ledger_path = Path(args.ledger or ROOT / "research" / "strategy_search_v3" / "trials.jsonl")
    v1_ledger_path = Path(args.v1_ledger or ROOT / "research" / "strategy_search_v1" / "trials.jsonl")
    v2_ledger_path = Path(args.v2_ledger or ROOT / "research" / "strategy_search_v2" / "trials.jsonl")
    crypto_config = Path(args.crypto_config or ROOT / "config" / "crypto_trend_core_v1.json")
    crypto_pickle = Path(args.crypto_pickle or os.path.join(os.environ.get("TEMP", "."), "multi_premia_data.pkl"))
    universe_file = Path(args.universe_file) if args.universe_file else None

    for existing in (results_path, leverage_path):
        if existing.exists():
            print(f"REFUSED: {existing} already exists; round 2 is a single look and is never rerun.", file=sys.stderr)
            return 2
    prior_v3 = ss.read_trials(ledger_path)
    if any(rec.get("round") == ROUND for rec in prior_v3):
        print(f"REFUSED: {ledger_path} already holds round-2 records; round 2 is a single look.", file=sys.stderr)
        return 2

    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    round_cfg = json.loads(round_path.read_text(encoding="utf-8"))
    if protocol.get("search_id") != SEARCH_ID or round_cfg.get("search_id") != SEARCH_ID:
        raise SystemExit("wrong search id")
    if round_cfg.get("round") != ROUND:
        raise SystemExit("not the round 2 config")
    spec = lc.candidate_spec(round_cfg)
    lev_cfg = protocol["leverage_assessment"]
    if [int(x) for x in lev_cfg["levels"]] != list(lev.LEVERAGE_LEVELS):
        raise SystemExit("leverage levels differ from the registration")

    prior_v1 = ss.read_trials(v1_ledger_path)
    prior_v2 = ss.read_trials(v2_ledger_path)  # a missing file means no v2 trials
    n_trials = count_tested(prior_v1) + count_tested(prior_v2) + count_tested(prior_v3) + 1  # this candidate included

    reference = ss.crypto_trend_core_reference(crypto_config, crypto_pickle)
    universe = load_universe(universe_file) if universe_file is not None else load_universe()
    # data integrity first: nothing is evaluated (or written) on truncated, non-finite or missing data
    funding_check = pbs.funding_integrity(universe["perp"], universe["funding"],
                                          required_last=ss._utc_ts(FUNDING_REQUIRED_LAST),
                                          window_start=ss._utc_ts(FINAL_WEEK_START))
    oi_check = lc.oi_integrity(universe["perp"], universe["oi"], required_first=ss._utc_ts(OI_REQUIRED_FIRST),
                               required_last=ss._utc_ts(OI_REQUIRED_LAST),
                               active_from=ss._utc_ts(FUNDING_REQUIRED_LAST))
    inputs = lc.make_inputs(universe, max_exit=MAX_EXIT)
    staleness = lc.oi_staleness(universe["perp"], universe["oi"])

    # the daily series is zero-filled over the full registered windows (a quiet start or end is not cut off)
    windows = [(ss._utc_ts(spec[k][0]), ss._utc_ts(spec[k][1])) for k in ("development", "validation")]
    result = r2.evaluate_candidate_general(
        spec, inputs.data, None, validation_window=spec["validation"], crypto_reference=reference, spy_returns=None,
        cost_bps=lc.COST_BPS_ROUND_TRIP, periods_per_year=lc.PERIODS_PER_YEAR, fn=lc.cascade_weights,
        detail_fn=lc.make_detail_fn(inputs, windows), null_fn=lc.make_null_fn(inputs), g8_mode="crypto_only",
        n_draws=lc.N_NULL_DRAWS, n_truncation_dates=ss.N_TRUNCATION_DATES, seed=ss.SEED)
    lc.apply_cumulative_dsr(result, n_trials)
    passed, first_fail = ss.verdict(result)

    detail = result["_detail"]
    windows = result["windows"]
    components = {}
    for label in ("development", "validation"):
        lo, hi = ss._utc_ts(windows[label][0]), ss._utc_ts(windows[label][1])
        part = detail.loc[(detail.index >= lo) & (detail.index <= hi)]
        components[label] = {c: float(part[c].mean()) for c in ("gross", "price_pnl", "funding_pnl", "cost", "net")}
        components[label]["mean_daily_turnover"] = float(part["turnover"].mean())
    trades = lc.build_trades(result["_weights"], inputs, None, lc.COST_BPS_ROUND_TRIP)

    provenance = universe_provenance(universe, inputs)
    provenance["funding_integrity"] = funding_check
    provenance["oi_integrity"] = oi_check
    provenance["oi_staleness"] = staleness  # descriptive only: no rule uses it
    payload = {
        "schema_version": 1,
        "search_id": protocol["search_id"],
        "round": ROUND,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cost_bps_round_trip": lc.COST_BPS_ROUND_TRIP,
        "periods_per_year": lc.PERIODS_PER_YEAR,
        "null_draws": lc.N_NULL_DRAWS,
        "null_seed": lc.NULL_SEED,
        "n_trials_cumulative": n_trials,
        "registered_trials_after_round": round_cfg.get("trials_after_round"),
        "n_trials_breakdown": {"v1_tested": count_tested(prior_v1), "v2_tested": count_tested(prior_v2),
                               "v3_tested_before": count_tested(prior_v3), "this_round": 1},
        "g8_reference": {"book": "crypto-trend-core-v1 (DON8+EMA8, 17 coins, canonical v3.1, 20 bps)",
                         "source": ss.CRYPTO_REFERENCE_PROVENANCE,
                         "first_date": str(reference.index[0].date()), "last_date": str(reference.index[-1].date()),
                         "rows": int(len(reference)), "sha256": ss.series_sha256(reference)},
        "data_provenance": provenance,
        "daily_components_mean": components,
        "trade_summary": trade_summary(trades, windows, inputs, result["params"]),
        "summary": {"id": result["id"], "pass": passed, "first_failing_gate": first_fail},
        "leverage_assessment": f"see {leverage_path.name} (computed after this verdict was saved)",
        "candidates": [ss.json_clean(result)],
        "claims": dict(protocol["claims"]),
    }
    _write_new(results_path, payload)  # the verdict is on disk before anything below can fail
    ss.append_trial(ledger_path, ss.ledger_record(result, ROUND))
    for record in ss.screened_out_records(round_cfg, ROUND):
        ss.append_trial(ledger_path, record)
    print(f"{result['id']:40s} {'PASS' if passed else 'FAIL'}" + ("" if passed else f"  first failing gate: {first_fail}"))

    # ---- leverage assessment (validation sample): a separate file, so a failure here cannot lose the verdict
    val_lo, val_hi = ss._utc_ts(windows["validation"][0]), ss._utc_ts(windows["validation"][1])
    positions, period_costs = lc.positions_for_leverage(trades, val_lo, val_hi)
    leverage = lc.assess_trade_book(positions, inputs.mark, period_costs, perp_hl=inputs.perp_hl)
    leverage["sample"] = "validation " + " .. ".join(windows["validation"])
    max_safe = leverage["max_safe_leverage"]
    promising = bool(passed and max_safe is not None and max_safe >= 2)
    _write_new(leverage_path, {
        "schema_version": 1, "search_id": protocol["search_id"], "round": ROUND, "id": result["id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(), "gate_verdict_file": results_path.name,
        "book_diagnostics": trades.attrs.get("diagnostics", {}), "leverage_assessment": leverage,
        "promising_prospect": promising, "claims": dict(protocol["claims"])})
    ss.append_trial(ledger_path, {"id": result["id"], "round": ROUND, "status": "leverage_update",
                                  "max_safe_leverage": max_safe, "promising_prospect": promising,
                                  "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    print(f"max safe leverage (validation): {max_safe}   promising prospect: {promising}")
    return 0


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value)}")


if __name__ == "__main__":
    raise SystemExit(main())
