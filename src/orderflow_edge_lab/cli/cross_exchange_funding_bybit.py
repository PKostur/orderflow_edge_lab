from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from orderflow_edge_lab.cross_exchange_funding import FundingDispersionSpec, evaluate_window
from orderflow_edge_lab.cross_exchange_funding_bybit import load_symbol_dataset_bybit


def _spec(signal: dict, economics: dict, cost_bps: float) -> FundingDispersionSpec:
    return FundingDispersionSpec(
        funding_lookback_days=int(signal["funding_lookback_days"]),
        minimum_history_days=int(signal["minimum_history_days"]),
        break_even_projection_days=int(signal["break_even_projection_days"]),
        safety_multiple_over_cost=float(signal["safety_multiple_over_cost"]),
        gross_exposure=float(economics["gross_exposure"]),
        round_trip_pair_cost_bps=float(cost_bps),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen MEXC-vs-Bybit perpetual funding-dispersion research.")
    parser.add_argument("--config", default="config/last_chance_structural_edge_v1_1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    symbols = [str(v).upper() for v in protocol["symbols"]]
    data_start = str(protocol["data_start_utc"])
    data_end = str(protocol["validation_end_exclusive_utc"])
    datasets = {}
    failures: list[dict[str, str]] = []

    def load(symbol: str):
        return symbol, load_symbol_dataset_bybit(symbol, data_start, data_end)

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                loaded_symbol, dataset = future.result()
                datasets[loaded_symbol] = dataset
            except Exception as exc:
                failures.append({"symbol": symbol, "error_type": type(exc).__name__, "message": str(exc)[:500]})

    if len(datasets) < 6:
        report = {
            "schema_version": 1,
            "protocol_name": protocol["protocol_name"],
            "status": "data_source_failure",
            "loaded_symbols": sorted(datasets),
            "load_failures": sorted(failures, key=lambda row: row["symbol"]),
            "claims": protocol["claims"],
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        raise SystemExit(2)

    signal, economics, evaluation = protocol["signal"], protocol["economics"], protocol["evaluation"]
    dev_start, dev_end = evaluation["development_window"]
    val_start, val_end = evaluation["later_validation_window"]
    cost_cases = []
    for cost in economics["round_trip_pair_cost_bps_cases"]:
        spec = _spec(signal, economics, float(cost))
        cost_cases.append({
            "round_trip_pair_cost_bps": float(cost),
            "development": evaluate_window(datasets, spec, dev_start, dev_end),
            "validation": evaluate_window(datasets, spec, val_start, val_end),
        })

    primary_cost = float(evaluation["primary_cost_bps"])
    primary = next(row for row in cost_cases if row["round_trip_pair_cost_bps"] == primary_cost)
    control_spec = _spec(signal, economics, primary_cost)
    reverse_development = evaluate_window(datasets, control_spec, dev_start, dev_end, reverse_control=True)
    reverse_validation = evaluate_window(datasets, control_spec, val_start, val_end, reverse_control=True)

    dev_port = primary["development"]["portfolio"]
    val_port = primary["validation"]["portfolio"]
    val_return = float(val_port["return"])
    reverse_val_return = float(reverse_validation["portfolio"]["return"])
    checks = {
        "positive_development_return": float(dev_port["return"]) > 0.0,
        "positive_validation_return": val_return > 0.0,
        "validation_sharpe": val_port["annualized_sharpe"] is not None and float(val_port["annualized_sharpe"]) >= float(evaluation["minimum_validation_sharpe"]),
        "validation_max_drawdown": val_port["max_drawdown"] is not None and float(val_port["max_drawdown"]) >= -float(evaluation["maximum_validation_drawdown"]),
        "positive_symbol_fraction": primary["validation"]["positive_symbol_fraction"] is not None and float(primary["validation"]["positive_symbol_fraction"]) >= float(evaluation["minimum_positive_symbol_fraction"]),
        "reverse_control_underperforms": reverse_val_return < val_return,
    }
    eligible = all(checks.values())
    report = {
        "schema_version": 1,
        "protocol_name": protocol["protocol_name"],
        "family": protocol["family"],
        "status": "research_screen_complete",
        "loaded_symbols": sorted(datasets),
        "load_failures": sorted(failures, key=lambda row: row["symbol"]),
        "frozen_protocol": protocol,
        "cost_cases": cost_cases,
        "primary_cost_bps": primary_cost,
        "reverse_control": {"development": reverse_development, "validation": reverse_validation},
        "screening_gate": {"checks": checks, "eligible_for_separate_forward_paper_freeze": eligible},
        "claims": {**protocol["claims"], "profitable_edge_established": False, "eligible_is_not_promotion": True},
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "loaded_symbols": sorted(datasets),
        "load_failures": failures,
        "primary_development": dev_port,
        "primary_validation": val_port,
        "validation_positive_symbol_fraction": primary["validation"]["positive_symbol_fraction"],
        "reverse_validation": reverse_validation["portfolio"],
        "gate_checks": checks,
        "eligible_for_separate_forward_paper_freeze": eligible,
    }, indent=2))


if __name__ == "__main__":
    main()
