"""Single `orderflow` dispatcher for installed operator commands.

This is a discovery layer only. Every subcommand delegates to the same
``cli.<module>:main`` function that the historical ``orderflow-<name>`` console
script calls. No behavior is re-implemented here, so research and safety
behavior is identical no matter which entry point an operator uses.

The flat ``orderflow-<name>`` scripts remain canonical and supported.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys

# Grouped for `--list` readability. Kept in one deterministic, sorted order so
# `--list --json` output is stable across runs.
_COMMANDS: dict[str, str] = {
    # Backtests and strategy research
    "orderflow-backtest": "orderflow_backtest",
    "orderflow-universal-backtest": "universal_backtest",
    "orderflow-strategy-tournament": "strategy_tournament",
    "orderflow-strategy-tournament-aggregate": "strategy_tournament_aggregate",
    "orderflow-strategy-tournament-data": "strategy_tournament_data",
    "orderflow-ema15m-hypothesis": "ema15m_hypothesis",
    "orderflow-direction-pair": "direction_pair",
    "orderflow-cross-pair": "cross_pair",
    "orderflow-cross-sectional-momentum": "cross_sectional_momentum",
    "orderflow-cross-sectional-forward-shadow": "cross_sectional_forward_shadow",
    "orderflow-htf-trend-forward-shadow": "htf_trend_forward_shadow",
    "orderflow-htf-fibonacci-forward-shadow": "htf_fibonacci_forward_shadow",
    "orderflow-htf-fibonacci-paired-forward": "htf_fibonacci_paired_forward",
    "orderflow-ena-forward-shadow": "ena_forward_shadow",
    "orderflow-ena-mean-reversion-risk": "ena_mean_reversion_risk",
    "orderflow-markov-ev-shadow": "markov_ev_shadow",
    "orderflow-markov-price-diagnostics": "markov_price_diagnostics",
    "orderflow-basis-convergence": "basis_convergence",
    "orderflow-pair-screen": "pair_screen",
    "orderflow-correlation-panel": "correlation_panel",
    # Discovery and calibration
    "orderflow-discovery-aggregate": "discovery_aggregate",
    "orderflow-discovery-v2-calibration": "discovery_v2_calibration",
    "orderflow-condition-aggregate": "condition_aggregate",
    "orderflow-conditioned-experiment-v1": "conditioned_experiment_v1",
    "orderflow-conditioned-result-aggregate-v1": "conditioned_result_aggregate_v1",
    # Market state and regime research
    "orderflow-market-conditions": "market_conditions",
    "orderflow-market-state-scan": "market_state_scan",
    "orderflow-market-state-aggregate": "market_state_aggregate",
    "orderflow-market-state-aggregate-v1-1": "market_state_aggregate_v1_1",
    "orderflow-market-state-aggregate-v1-2": "market_state_aggregate_v1_2",
    "orderflow-state-candidate-registry-v1": "state_candidate_registry_v1",
    "orderflow-state-promotion-report": "state_promotion_report",
    "orderflow-state-promotion-report-v1-2": "state_promotion_report_v1_2",
    "orderflow-state-threshold-freeze-v1": "state_threshold_freeze_v1",
    "orderflow-strategy-state-mapping-v1": "strategy_state_mapping_v1",
    "orderflow-strategy-conditioning-freeze": "strategy_conditioning_freeze",
    "orderflow-strategy-conditioning-freeze-v1-1": "strategy_conditioning_freeze_v1_1",
    "orderflow-strategy-conditioning-registry-binding-v1": "strategy_conditioning_registry_binding_v1",
    # Session research
    "orderflow-session-audit": "session_audit",
    "orderflow-session-metrics": "session_metrics",
    "orderflow-session-strategy-report": "session_strategy_report",
    "orderflow-session-excursion-aggregate": "session_excursion_aggregate",
    "orderflow-session-watch": "session_watch",
    "orderflow-mexc-session-research": "mexc_session_research",
    "orderflow-portfolio-session-report": "portfolio_session_report",
    "orderflow-evidence-v2-session-audit": "evidence_v2_session_audit",
    "orderflow-evidence-v2-session-forward": "evidence_v2_session_forward",
    # Risk and economics
    "orderflow-risk-ladder": "risk_ladder",
    "orderflow-stop-risk": "stop_risk",
    # Data access and auditing
    "orderflow-dxfeed-login": "login",
    "orderflow-probe": "probe",
    "orderflow-discover-endpoint": "discover_endpoint",
    "orderflow-analyze-endpoint": "analyze_endpoint",
    "orderflow-audit-causality": "audit_causality",
    "orderflow-mexc-record": "mexc_record",
    "orderflow-mexc-replay": "mexc_replay",
    "orderflow-export-audit": "export_audit",
    "orderflow-export-bundle": "export_bundle",
    "orderflow-news-monitor": "news_monitor",
    "orderflow-sentiment-monitor": "sentiment_monitor",
    # Validity, freezes, and promotion gates
    "orderflow-validate": "validate",
    "orderflow-readiness": "readiness",
    "orderflow-research-freeze": "research_freeze",
    "orderflow-candidate-freeze": "candidate_freeze",
    "orderflow-holdout-audit": "holdout_audit",
    "orderflow-trial-ledger": "trial_ledger",
    "orderflow-promotion-check": "promote",
    "orderflow-multi-agent": "multi_agent",
    "orderflow-review-clock": "review_clock",
    "orderflow-capture-health": "capture_health",
    # Wait-window observability and retention
    "orderflow-review-packet": "review_packet",
    "orderflow-artifact-coverage": "artifact_coverage",
    "orderflow-ops-digest": "ops_digest",
    # Validation statistics and hygiene
    "orderflow-robustness": "robustness",
    "orderflow-research-hygiene": "research_hygiene",
    "orderflow-discovery-screen": "discovery_screen",
    "orderflow-orthogonality": "orthogonality",
    # Paper execution and reliability
    "orderflow-paper": "paper",
    "orderflow-paper-audit": "paper_audit",
    "orderflow-runtime-snapshot": "runtime_snapshot",
}

# Commands whose published console-script name intentionally differs from the
# orderflow-<module_name with dashes> convention.
_NAME_EXCEPTIONS = frozenset({"orderflow-promotion-check", "orderflow-dxfeed-login"})

_ENTRYPOINT_PREFIX = "orderflow_edge_lab.cli."


def _known_modules() -> dict[str, str]:
    """Return command name -> cli module name, deriving any missing entries.

    The table above is the curated grouping; if a future cli module is added
    without a table entry, the dispatcher still finds it by name convention
    (``orderflow-<name>`` -> ``cli/<name>.py``) by scanning the package.
    """

    import pkgutil
    from pathlib import Path

    discovered: dict[str, str] = {}
    covered_modules = set(_COMMANDS.values())
    package_dir = Path(__file__).resolve().parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        module_name = info.name
        if module_name == "main" or module_name.startswith("_"):
            continue
        if module_name in covered_modules:
            # Already reachable under its published console-script name; do not
            # create a second convention-derived alias for it.
            continue
        command = f"orderflow-{module_name.replace('_', '-')}"
        discovered[command] = module_name
    return discovered


def available_commands() -> dict[str, str]:
    """Return all command name -> cli module name mappings."""

    merged = dict(_COMMANDS)
    merged.update(_known_modules())
    return dict(sorted(merged.items()))


def _resolve_target(command: str) -> str | None:
    """Return the full entry-point target string for a command, or None."""

    modules = available_commands()
    module = modules.get(command)
    if module is None:
        return None
    return f"{_ENTRYPOINT_PREFIX}{module}:main"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orderflow",
        description=(
            "Unified dispatcher for Orderflow Edge Lab operator commands. "
            "Each subcommand delegates to the same implementation as its "
            "flat orderflow-<name> console script."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_commands",
        help="List all available commands and exit.",
    )
    parser.add_argument(
        "--list-json",
        action="store_true",
        dest="list_json",
        help="List available commands as JSON and exit.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="Command name (same name as the flat orderflow-<name> script).",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to the target command.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_commands or args.list_json:
        commands = available_commands()
        if args.list_json:
            print(
                json.dumps(
                    {
                        command: f"{_ENTRYPOINT_PREFIX}{module}:main"
                        for command, module in commands.items()
                    },
                    sort_keys=True,
                    indent=2,
                )
            )
        else:
            width = max(len(name) for name in commands)
            for command, module in commands.items():
                print(f"{command:<{width}}  ->  cli/{module}.py")
        return 0

    if not args.command:
        build_parser().print_help()
        return 2

    command = args.command
    target = _resolve_target(command)
    if target is None and not command.startswith("orderflow-"):
        # Accept both `orderflow review-clock` and `orderflow orderflow-review-clock`.
        command = f"orderflow-{command}"
        target = _resolve_target(command)
    if target is None:
        print(
            json.dumps(
                {
                    "status": "unknown_command",
                    "command": args.command,
                    "hint": "run 'orderflow --list' to see available commands",
                }
            )
        )
        return 2

    module_name, function_name = target.split(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(
            json.dumps(
                {
                    "status": "import_failed",
                    "command": args.command,
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        return 2
    entry = getattr(module, function_name, None)
    if entry is None:
        print(
            json.dumps(
                {
                    "status": "missing_entry_point",
                    "command": args.command,
                    "target": target,
                }
            )
        )
        return 2

    # Delegate exactly like the console script would. Newer commands accept an
    # explicit argv; older ones parse sys.argv themselves, so shim sys.argv to
    # look as if the flat script had been invoked directly.
    try:
        accepts_argv = len(inspect.signature(entry).parameters) > 0
    except (TypeError, ValueError):
        accepts_argv = True

    if accepts_argv:
        result = entry(args.args)
    else:
        original_argv = sys.argv
        sys.argv = [command, *args.args]
        try:
            result = entry()
        finally:
            sys.argv = original_argv
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
