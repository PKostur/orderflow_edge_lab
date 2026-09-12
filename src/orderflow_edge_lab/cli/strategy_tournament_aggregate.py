from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.strategy_tournament import rank_results
from orderflow_edge_lab.tournament_robustness import SymbolBreadthGate, apply_symbol_breadth_gate


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate all strategy-tournament-v1 family/timeframe reports.")
    parser.add_argument("results_dir")
    parser.add_argument("--minimum-trades", type=int, default=80)
    parser.add_argument("--minimum-folds", type=int, default=6)
    parser.add_argument("--minimum-symbols", type=int, default=8)
    parser.add_argument("--minimum-positive-symbol-fraction", type=float, default=0.60)
    parser.add_argument("--minimum-pf-symbol-fraction", type=float, default=0.60)
    parser.add_argument("--top", type=int, default=150)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.results_dir)
    reports = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("experiment") == "strategy_tournament_v1":
            reports.append(payload)
    if not reports:
        raise SystemExit("no strategy-tournament-v1 reports found")

    leaderboard = rank_results(
        reports,
        minimum_trades=args.minimum_trades,
        minimum_folds=args.minimum_folds,
    )
    leaderboard = apply_symbol_breadth_gate(
        leaderboard,
        SymbolBreadthGate(
            minimum_symbol_observations=args.minimum_symbols,
            minimum_positive_expectancy_fraction=args.minimum_positive_symbol_fraction,
            minimum_profit_factor_gt_one_fraction=args.minimum_pf_symbol_fraction,
        ),
    )
    leaderboard["source_report_count"] = len(reports)
    leaderboard["source_families"] = sorted({str(report.get("family")) for report in reports})
    leaderboard["source_intervals"] = sorted({str(report.get("interval")) for report in reports})
    leaderboard["leaderboard"] = leaderboard["leaderboard"][: max(1, args.top)]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(leaderboard, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
