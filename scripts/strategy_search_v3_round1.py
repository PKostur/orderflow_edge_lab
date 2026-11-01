"""Run strategy-search-v3 round 1 exactly once (single look).

Candidate: V3R1C1_logbasis_quintile_8h (Binance USDT-M perp log-basis quintile sort at 00/08/16 UTC, 8h hold, 14 bps
round trip, realized funding).  Gates G1-G8 at 1x with the v2 G5 (``deflated_sharpe_null_consistent``, N = every tested
trial in the v1, v2 (if the file exists) and v3 ledgers including this one), G8 against the crypto trend core only (as
round 2 CTREND), then the leverage assessment on the validation sample.

Refuses to run if ``research/strategy_search_v3/round1_results.json`` (or ``round1_leverage.json``) exists or the v3
ledger holds any round-1 record.  There is no draw override; path overrides exist only behind ``--test-mode``.

Order of events (the gate verdict is saved before anything else can fail): data load, funding integrity checks (fail
loudly), G1-G8 -> ``round1_results.json`` + ledger record -> PASS/FAIL printed -> leverage assessment ->
``round1_leverage.json`` + a ``leverage_update`` ledger record.

Usage: PYTHONPATH=src .venv/Scripts/python scripts/strategy_search_v3_round1.py
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

from orderflow_edge_lab import binance_futures_archive as archive
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import perp_basis_strategy as pbs
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2

ROOT = Path(__file__).resolve().parents[1]
SEARCH_ID = "strategy-search-v3-leveraged"
ROUND = 1
DATA_END = "2026-09-30"
MAX_EXIT = "2026-09-30 23:59:59"  # the 2026-10-01 00:00 funding settlement is not in the monthly files
FUNDING_REQUIRED_LAST = "2026-09-30 16:00"  # every contract trading then must have a settlement on or after this
FINAL_WEEK_START = "2026-09-24 00:00"
OVERRIDE_OPTIONS = ("protocol", "round_config", "results", "leverage_results", "ledger", "v1_ledger", "v2_ledger",
                    "crypto_config", "crypto_pickle")


def count_tested(records: list[dict[str, Any]]) -> int:
    return sum(1 for rec in records if rec.get("status") == "tested")


def load_universe() -> dict[str, Any]:
    """Real archive data (cached by ``prefetch_binance_futures_archive.py``); mark prices from the validation start."""
    return archive.load_universe(end=DATA_END, workers=24, include_mark=True, mark_start="2023-07-02")


def universe_provenance(universe: dict[str, Any], inputs: pbs.BasisInputs) -> dict[str, Any]:
    prov = {k: v for k, v in universe["provenance"].items() if k not in ("per_instrument", "funding", "spot")}
    prov["per_instrument_summary"] = {
        "n": len(universe["perp"]),
        "first_bar_end": min(v["first_bar_end"] for v in universe["provenance"]["per_instrument"].values()),
        "last_bar_end": max(v["last_bar_end"] for v in universe["provenance"]["per_instrument"].values())}
    prov["funding_summary"] = {"symbols": len(universe["funding"]),
                               "intervals_hours_seen": sorted({x for v in universe["provenance"]["funding"].values()
                                                               for x in v["interval_hours"]}),
                               "symbols_without_funding_rows": sorted(s for s, v in
                                                                      universe["provenance"]["funding"].items()
                                                                      if v["rows"] == 0)}
    prov["mark_symbols"] = len(universe["mark"])
    for key, frame in inputs.data.items():
        prov[f"{key}_frame_sha256"] = ss.frame_sha256(frame)
        prov[f"{key}_shape"] = list(frame.shape)
    prov["max_exit"] = MAX_EXIT
    return prov


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:  # "x": never overwrite
        json.dump(ss.json_clean(payload), handle, indent=2, sort_keys=True, allow_nan=False, default=_json_default)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run strategy-search-v3 round 1 once.")
    parser.add_argument("--test-mode", action="store_true", help="allow path overrides (unit tests only)")
    for name in OVERRIDE_OPTIONS:
        parser.add_argument("--" + name.replace("_", "-"))
    args = parser.parse_args(argv)

    overridden = [name for name in OVERRIDE_OPTIONS if getattr(args, name) is not None]
    if overridden and not args.test_mode:
        print(f"REFUSED: {overridden} may only be overridden together with --test-mode.", file=sys.stderr)
        return 2

    protocol_path = Path(args.protocol or ROOT / "config" / "strategy_search_v3_leveraged.json")
    round_path = Path(args.round_config or ROOT / "config" / "strategy_search_v3_round1.json")
    results_path = Path(args.results or ROOT / "research" / "strategy_search_v3" / "round1_results.json")
    leverage_path = Path(args.leverage_results or ROOT / "research" / "strategy_search_v3" / "round1_leverage.json")
    ledger_path = Path(args.ledger or ROOT / "research" / "strategy_search_v3" / "trials.jsonl")
    v1_ledger_path = Path(args.v1_ledger or ROOT / "research" / "strategy_search_v1" / "trials.jsonl")
    v2_ledger_path = Path(args.v2_ledger or ROOT / "research" / "strategy_search_v2" / "trials.jsonl")
    crypto_config = Path(args.crypto_config or ROOT / "config" / "crypto_trend_core_v1.json")
    crypto_pickle = Path(args.crypto_pickle or os.path.join(os.environ.get("TEMP", "."), "multi_premia_data.pkl"))

    for existing in (results_path, leverage_path):
        if existing.exists():
            print(f"REFUSED: {existing} already exists; round 1 is a single look and is never rerun.", file=sys.stderr)
            return 2
    prior_v3 = ss.read_trials(ledger_path)
    if any(rec.get("round") == ROUND for rec in prior_v3):
        print(f"REFUSED: {ledger_path} already holds round-1 records; round 1 is a single look.", file=sys.stderr)
        return 2

    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    round_cfg = json.loads(round_path.read_text(encoding="utf-8"))
    if protocol.get("search_id") != SEARCH_ID or round_cfg.get("search_id") != SEARCH_ID:
        raise SystemExit("wrong search id")
    if round_cfg.get("round") != ROUND:
        raise SystemExit("not the round 1 config")
    spec = pbs.candidate_spec(round_cfg)
    lev_cfg = protocol["leverage_assessment"]
    if [int(x) for x in lev_cfg["levels"]] != list(lev.LEVERAGE_LEVELS):
        raise SystemExit("leverage levels differ from the registration")

    prior_v1 = ss.read_trials(v1_ledger_path)
    prior_v2 = ss.read_trials(v2_ledger_path)  # a missing file means no v2 trials
    n_trials = count_tested(prior_v1) + count_tested(prior_v2) + count_tested(prior_v3) + 1  # this candidate included

    reference = ss.crypto_trend_core_reference(crypto_config, crypto_pickle)
    universe = load_universe()
    # data integrity first: nothing is evaluated (or written) on truncated or non-finite funding
    funding_check = pbs.funding_integrity(universe["perp"], universe["funding"],
                                          required_last=ss._utc_ts(FUNDING_REQUIRED_LAST),
                                          window_start=ss._utc_ts(FINAL_WEEK_START))
    inputs = pbs.make_inputs(universe, max_exit=MAX_EXIT)
    extreme_basis = pbs.basis_extreme_stats(inputs.data, spec["params"])

    result = r2.evaluate_candidate_general(
        spec, inputs.data, None, validation_window=spec["validation"], crypto_reference=reference, spy_returns=None,
        cost_bps=pbs.COST_BPS_ROUND_TRIP, periods_per_year=pbs.PERIODS_PER_YEAR, fn=pbs.basis_quintile_weights,
        detail_fn=pbs.make_detail_fn(inputs), null_fn=pbs.make_null_fn(inputs), g8_mode="crypto_only",
        n_draws=pbs.N_NULL_DRAWS, n_truncation_dates=ss.N_TRUNCATION_DATES, seed=ss.SEED)
    pbs.apply_cumulative_dsr(result, n_trials)
    passed, first_fail = ss.verdict(result)

    detail = result["_detail"]
    windows = result["windows"]
    components = {}
    for label in ("development", "validation"):
        lo, hi = ss._utc_ts(windows[label][0]), ss._utc_ts(windows[label][1])
        part = detail.loc[(detail.index >= lo) & (detail.index <= hi)]
        components[label] = {c: float(part[c].mean()) for c in ("gross", "price_pnl", "funding_pnl", "cost", "net")}
        components[label]["mean_daily_turnover"] = float(part["turnover"].mean())
    n_eligible = result["_weights"].notna().sum(axis=1)

    provenance = universe_provenance(universe, inputs)
    provenance["funding_integrity"] = funding_check
    provenance["extreme_basis_abs_gt_10pct"] = extreme_basis  # descriptive only: no rule uses it
    payload = {
        "schema_version": 1,
        "search_id": protocol["search_id"],
        "round": ROUND,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cost_bps_round_trip": pbs.COST_BPS_ROUND_TRIP,
        "periods_per_year": pbs.PERIODS_PER_YEAR,
        "null_draws": pbs.N_NULL_DRAWS,
        "null_seed": pbs.NULL_SEED,
        "n_trials_cumulative": n_trials,
        "n_trials_breakdown": {"v1_tested": count_tested(prior_v1), "v2_tested": count_tested(prior_v2),
                               "v3_tested_before": count_tested(prior_v3), "this_round": 1},
        "g8_reference": {"book": "crypto-trend-core-v1 (DON8+EMA8, 17 coins, canonical v3.1, 20 bps)",
                         "source": ss.CRYPTO_REFERENCE_PROVENANCE,
                         "first_date": str(reference.index[0].date()), "last_date": str(reference.index[-1].date()),
                         "rows": int(len(reference)), "sha256": ss.series_sha256(reference)},
        "data_provenance": provenance,
        "daily_components_mean": components,
        "eligible_contracts_per_settlement": {
            "min": int(n_eligible.min()), "median": float(n_eligible.median()), "max": int(n_eligible.max()),
            "settlements_with_signal": int((n_eligible >= int(spec["params"]["quantiles"])).sum())},
        "summary": {"id": result["id"], "pass": passed, "first_failing_gate": first_fail},
        "leverage_assessment": f"see {leverage_path.name} (computed after this verdict was saved)",
        "candidates": [ss.json_clean(result)],
        "claims": dict(protocol["claims"]),
    }
    _write_new(results_path, payload)  # the verdict is on disk before anything below can fail
    ss.append_trial(ledger_path, ss.ledger_record(result, ROUND))
    for record in ss.screened_out_records(round_cfg, ROUND):
        ss.append_trial(ledger_path, record)
    print(f"{result['id']:32s} {'PASS' if passed else 'FAIL'}" + ("" if passed else f"  first failing gate: {first_fail}"))

    # ---- leverage assessment (validation sample): a separate file, so a failure here cannot lose the verdict
    book = pbs.build_book(result["_weights"], inputs, None, pbs.COST_BPS_ROUND_TRIP)
    val_lo, val_hi = ss._utc_ts(windows["validation"][0]), ss._utc_ts(windows["validation"][1])
    positions, period_costs = pbs.positions_in_window(book, val_lo, val_hi)
    leverage = lev.assess_leverage(positions, inputs.mark, period_costs)
    leverage["sample"] = "validation " + " .. ".join(windows["validation"])
    max_safe = leverage["max_safe_leverage"]
    promising = bool(passed and max_safe is not None and max_safe >= 2)
    _write_new(leverage_path, {
        "schema_version": 1, "search_id": protocol["search_id"], "round": ROUND, "id": result["id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(), "gate_verdict_file": results_path.name,
        "book_diagnostics": book.diagnostics, "leverage_assessment": leverage, "promising_prospect": promising,
        "claims": dict(protocol["claims"])})
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
