from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.evolutionary_price_agent import evaluate_genome, evolve, genome_from_dict
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolve a no-indicator raw-price trading agent and test the champion once on an untouched holdout.")
    parser.add_argument("--config", default="config/evolutionary_price_agent_v1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    data = protocol["data"]
    inputs = protocol["inputs"]
    ecfg = protocol["evolution"]
    selection = protocol["selection"]

    full = fetch_mexc_futures_klines(str(data["symbol"]), str(data["interval"]), str(data["start"]), str(data["holdout_end_exclusive"]))
    discovery_end = pd.Timestamp(str(data["discovery_end_exclusive"]), tz="UTC")
    holdout_end = pd.Timestamp(str(data["holdout_end_exclusive"]), tz="UTC")
    discovery = full[full.index < discovery_end].copy()
    holdout = full[(full.index >= discovery_end) & (full.index < holdout_end)].copy()
    if len(discovery) < 1000:
        raise SystemExit(f"discovery sample too small: {len(discovery)} bars")
    if len(holdout) < 200:
        raise SystemExit(f"holdout sample too small: {len(holdout)} bars")

    evolve_cfg = {"maximum_lookback_bars": int(inputs["maximum_lookback_bars"]), "evolution": ecfg}
    result = evolve(discovery, evolve_cfg)
    champion = genome_from_dict(result["best_genome"])

    # Holdout is not available to evolution or selection. It is evaluated exactly once after the champion is frozen.
    holdout_eval = evaluate_genome(
        holdout,
        champion,
        maximum_lookback=int(inputs["maximum_lookback_bars"]),
        round_trip_cost_bps=float(ecfg["round_trip_cost_bps"]),
        fold_days=int(ecfg["fold_days"]),
        minimum_trades_per_fold=max(4, int(ecfg["minimum_trades_per_fold"]) // 2),
        minimum_folds=max(2, min(int(ecfg["minimum_folds"]), 3)),
        fitness_weights=ecfg["fitness_weights"],
    )

    discovery_eval = result["best_discovery_evaluation"]
    discovery_gate = bool(
        float(discovery_eval.get("median_fold_expectancy_bps") or -1e9) > 0.0
        and float(discovery_eval.get("positive_fold_fraction") or 0.0) >= float(selection["winner_requires_positive_fold_fraction"])
        and float(discovery_eval.get("median_fold_profit_factor") or 0.0) >= float(selection["winner_requires_median_profit_factor"])
        and int(discovery_eval.get("trades") or 0) >= int(selection["winner_requires_minimum_total_trades"])
    )
    holdout_aggregate = holdout_eval["aggregate"]
    holdout_survived = bool(
        int(holdout_aggregate.get("trades") or 0) >= 10
        and float(holdout_aggregate.get("expectancy_bps") or -1e9) > 0.0
        and float(holdout_aggregate.get("win_rate") or 0.0) > 0.50
        and (holdout_aggregate.get("profit_factor") == "INF" or float(holdout_aggregate.get("profit_factor") or 0.0) > 1.0)
    )

    report = {
        "schema_version": 1,
        "experiment": "evolutionary_price_agent_v1",
        "protocol_name": protocol["protocol_name"],
        "symbol": data["symbol"],
        "interval": data["interval"],
        "technical_indicators_used": False,
        "execution": {
            "signal_uses_completed_bar_only": True,
            "entry_on_next_bar_open": True,
            "fixed_holding_period_from_genome": True,
            "round_trip_cost_bps": float(ecfg["round_trip_cost_bps"]),
        },
        "samples": {
            "discovery_start": str(discovery.index.min()),
            "discovery_end": str(discovery.index.max()),
            "discovery_bars": len(discovery),
            "holdout_start": str(holdout.index.min()),
            "holdout_end": str(holdout.index.max()),
            "holdout_bars": len(holdout),
        },
        **result,
        "discovery_gate_passed": discovery_gate,
        "holdout_evaluation": holdout_eval,
        "holdout_survived_basic_economic_test": holdout_survived,
        "interpretation": (
            "Champion survived the one-time holdout basic economic test; this is promising but remains exploratory until independent replication."
            if holdout_survived
            else "Champion did not survive the one-time holdout basic economic test; treat the evolved discovery behavior as overfit or regime-dependent until disproven."
        ),
        "claims": {
            "profitable_edge_established": False,
            "single_untouched_holdout_positive": holdout_survived,
            "verified_out_of_sample_evidence": False,
            "standalone_strategy_promotable": False,
            "live_order_transmission_supported": False,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "discovery_gate_passed": discovery_gate,
        "holdout_survived": holdout_survived,
        "champion": {k: v for k, v in result["best_genome"].items() if k != "weights"},
        "discovery": {
            "fitness": discovery_eval.get("fitness"),
            "expectancy_bps": discovery_eval.get("median_fold_expectancy_bps"),
            "win_rate": discovery_eval.get("median_fold_win_rate"),
            "profit_factor": discovery_eval.get("median_fold_profit_factor"),
            "positive_fold_fraction": discovery_eval.get("positive_fold_fraction"),
            "trades": discovery_eval.get("trades"),
        },
        "holdout": holdout_aggregate,
    }, indent=2))


if __name__ == "__main__":
    main()
